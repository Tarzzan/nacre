"""Personnes, groupes et espaces : qui peut lire ou écrire où.

Trois rôles : administrateur, membre (ses espaces seulement) et lecture seule (consultation de tout, comme avant).
Un espace est un dossier sous data/espaces/<identifiant> : personnel (une personne, fermé à tous les autres, y compris
aux administrateurs) ou d'équipe (personnes et groupes, en lecture ou en écriture). « Fichiers partagés » reste l'espace commun.

Tout vit dans la table de réglages, sans changement de schéma : `person:<nom>`, `group:<id>`, `space:<id>`.
Les droits sont appliqués par la console, à l'ouverture de tout dossier ; ce ne sont pas des permissions Unix.
"""
import json
import os
import re
import secrets
import time
from pathlib import Path

SPACE = re.compile(r'espace_([a-f0-9]{12})\Z')
IDENT = re.compile(r'[a-f0-9]{12}\Z')
NAME_MAX = 60
LEVELS = ('read', 'write')
COMMON = 'space:fichiers'
# Ce qu'un membre peut lire et écrire dans la console ; tout le reste lui est refusé par défaut.
MEMBER_READS = ('/api/me', '/api/desk', '/api/areas', '/api/files', '/api/files/search', '/api/files/usage', '/api/files/usage-spaces',
                '/api/download', '/api/archive', '/api/trash', '/api/overview', '/api/account')
MEMBER_WRITES = ('/api/logout', '/api/desk', '/api/upload', '/api/folder', '/api/rename', '/api/move', '/api/trash', '/api/restore',
                 '/api/account/password')
CAMERA_READS = ('/api/cameras', '/api/camera/')


def get(db, key, default=None):
    row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row[0]) if row else default
    except ValueError:
        return default


def put(db, key, value):
    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


def every(db, prefix):
    found = []
    for key, value in db.execute("SELECT key,value FROM settings WHERE key LIKE ? ESCAPE '\\'", (prefix.replace('_', '\\_') + '%',)):
        try:
            doc = json.loads(value)
        except ValueError:
            continue
        if isinstance(doc, dict):
            found.append(doc)
    return found


def title(app, value, what):
    if not isinstance(value, str):
        raise app.Problem(f'Nom {what} invalide.')
    text = ' '.join(value.split())
    if not 1 <= len(text) <= NAME_MAX or not all(ch.isprintable() for ch in text):
        raise app.Problem(f'Nom {what} invalide : 1 à {NAME_MAX} caractères.')
    return text


def person(db, name):
    doc = get(db, 'person:' + name, {})
    return doc if isinstance(doc, dict) else {}


def groups_of(db, name):
    return {g['id'] for g in every(db, 'group:') if name in g.get('members', [])}


def common(db):
    doc = get(db, COMMON, {})
    doc = doc if isinstance(doc, dict) else {}
    return {'everyone': doc.get('everyone', 'read') if doc.get('everyone', 'read') in LEVELS + (None,) else 'read',
            'members': doc.get('members', {}), 'groups': doc.get('groups', {})}


def granted(db, doc, name):
    """Meilleur niveau qu'un espace accorde à une personne, directement ou par ses groupes."""
    found = [doc.get('members', {}).get(name)]
    mine = groups_of(db, name) if doc.get('groups') else set()
    found += [level for group, level in doc.get('groups', {}).items() if group in mine]
    found = [level for level in found if level in LEVELS]
    return max(found, key=LEVELS.index) if found else None


def level(app, session, area):
    """Niveau d'accès de la session à un espace : None, 'read' ou 'write'."""
    role, name = session.get('role'), session.get('name')
    if not isinstance(area, str):
        return None
    match = SPACE.fullmatch(area)
    if match:
        with app.database() as db:
            doc = get(db, 'space:' + match[1])
            if not isinstance(doc, dict):
                return None
            if doc.get('kind') == 'personal':
                # Fermé à tous sauf à sa personne : un administrateur ne l'ouvre pas depuis la console.
                return 'write' if doc.get('owner') == name and role in ('admin', 'member') else None
            if role == 'admin':
                return 'write'
            found = granted(db, doc, name)
        return 'read' if found and role == 'viewer' else found if role == 'member' else None
    if role == 'admin':
        return 'write'
    if role == 'viewer':
        return 'read' if area in ('fichiers', 'video', 'sauvegardes') else None
    if role == 'member' and area == 'fichiers':
        with app.database() as db:
            doc = common(db)
            found = [level for level in (doc['everyone'], granted(db, doc, name)) if level in LEVELS]
        return max(found, key=LEVELS.index) if found else None
    return None


def authorize(app, session, area, write=False):
    found = level(app, session, area)
    if found is None:
        raise app.Problem('Cet espace ne vous est pas ouvert.', 403)
    if write and found != 'write':
        raise app.Problem('Cet espace est en lecture seule pour vous.', 403)


def root(app):
    return Path(app.ROOT) / 'data/espaces'


def resource(app, area):
    """Dossier d'un espace, créé au premier accès. L'existence de l'espace est vérifiée à chaque ouverture."""
    match = SPACE.fullmatch(area) if isinstance(area, str) else None
    with app.database() as db:
        doc = get(db, 'space:' + match[1]) if match else None
    if not isinstance(doc, dict):
        raise app.Problem('Espace inconnu.')
    path = root(app) / match[1]
    if not path.is_dir():
        root(app).mkdir(mode=0o750, exist_ok=True)
        path.mkdir(mode=0o2770, exist_ok=True)
        os.chmod(path, 0o2770)
    return {'id': area, 'name': doc.get('name', area), 'path': str(path), 'kind': 'space', 'writable': True}


def personal(db, name):
    return next((s for s in every(db, 'space:') if s.get('kind') == 'personal' and s.get('owner') == name), None)


def ensure_personal(app, session):
    """Espace personnel d'un administrateur ou d'un membre, créé la première fois qu'il ouvre ses fichiers."""
    if session.get('role') not in ('admin', 'member'):
        return None
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        doc = personal(db, session['name'])
        if not doc:
            doc = {'id': secrets.token_hex(6), 'kind': 'personal', 'owner': session['name'], 'name': 'Mon espace', 'members': {}, 'groups': {}, 'created': time.time()}
            put(db, 'space:' + doc['id'], doc)
    return doc


def areas(app, session):
    """Espaces que la session peut ouvrir, dans l'ordre où ils sont présentés."""
    role, name = session.get('role'), session.get('name')
    found = []
    mine = ensure_personal(app, session)
    if mine:
        found.append({'id': 'espace_' + mine['id'], 'name': 'Mon espace', 'writable': True, 'kind': 'personal'})
    with app.database() as db:
        teams = sorted((s for s in every(db, 'space:') if s.get('kind') == 'team' and isinstance(s.get('id'), str) and IDENT.fullmatch(s['id'])),
                       key=lambda s: str(s.get('name', '')).casefold())
    for doc in teams:
        access = level(app, session, 'espace_' + doc['id'])
        if access:
            found.append({'id': 'espace_' + doc['id'], 'name': doc.get('name', ''), 'writable': access == 'write', 'kind': 'team'})
    for item in app.file_areas(role == 'admin'):
        access = level(app, session, item['id'])
        if access:
            found.append({**item, 'writable': bool(item['writable']) and access == 'write'})
    return found


def private(app, area):
    """Vrai pour un espace personnel : ses noms de fichiers ne vont pas au journal commun."""
    match = SPACE.fullmatch(area) if isinstance(area, str) else None
    if not match:
        return False
    with app.database() as db:
        doc = get(db, 'space:' + match[1])
    return isinstance(doc, dict) and doc.get('kind') == 'personal'


def detail(app, area, text):
    """Détail d'une ligne de journal : le nom de l'espace remplace son identifiant, et un espace personnel ne livre aucun nom."""
    if private(app, area):
        return 'espace personnel'
    match = SPACE.fullmatch(area) if isinstance(area, str) else None
    if match:
        with app.database() as db:
            doc = get(db, 'space:' + match[1], {})
        return f"{doc.get('name', area)} : {text}"
    return text


def allowed(app, session, path, post):
    """Un membre n'atteint que les routes de ses fichiers et de son compte ; la surveillance s'ajoute si elle lui est ouverte."""
    if session.get('role') != 'member':
        return True
    if post:
        return path in MEMBER_WRITES
    if path in MEMBER_READS:
        return True
    if path == CAMERA_READS[0] or path.startswith(CAMERA_READS[1]):
        with app.database() as db:
            return person(db, session['name']).get('camera') is True
    return False


def me(app, session):
    with app.database() as db:
        return {'camera': session.get('role') != 'member' or person(db, session['name']).get('camera') is True}


# Administration : personnes, groupes et espaces.

def accounts(db):
    return [dict(row) for row in db.execute('SELECT name,role,active FROM users ORDER BY name')]


def access(app, body, known, groups):
    """Valide les accès d'un espace : personnes et groupes existants, niveau lecture ou écriture."""
    members, shared = body.get('members', {}), body.get('groups', {})
    if not isinstance(members, dict) or not isinstance(shared, dict) or len(members) > 500 or len(shared) > 200:
        raise app.Problem('Accès invalides.')
    for name, value in members.items():
        if name not in known or value not in LEVELS:
            raise app.Problem('Accès invalides : personne ou niveau inconnu.')
    for group, value in shared.items():
        if group not in groups or value not in LEVELS:
            raise app.Problem('Accès invalides : groupe ou niveau inconnu.')
    return dict(members), dict(shared)


def overview(app):
    with app.database() as db:
        people, groups, spaces = accounts(db), every(db, 'group:'), every(db, 'space:')
        shared = common(db)
        flags = {p['name']: person(db, p['name']) for p in people}
    groups = sorted(({'id': g['id'], 'name': g.get('name', ''), 'members': sorted(m for m in g.get('members', []) if m in flags)}
                     for g in groups if isinstance(g.get('id'), str) and IDENT.fullmatch(g['id'])), key=lambda g: g['name'].casefold())
    owners = {s.get('owner'): s for s in spaces if s.get('kind') == 'personal'}
    active = {p['name'] for p in people if p['active']}
    return {
        'people': [{'name': p['name'], 'role': p['role'], 'active': bool(p['active']), 'camera': flags[p['name']].get('camera') is True,
                    'groups': [g['id'] for g in groups if p['name'] in g['members']], 'personal': p['name'] in owners} for p in people],
        'groups': groups,
        'spaces': sorted(({'id': 'espace_' + s['id'], 'name': s.get('name', ''), 'members': s.get('members', {}), 'groups': s.get('groups', {}),
                           'former': s.get('former')} for s in spaces if s.get('kind') == 'team'), key=lambda s: s['name'].casefold()),
        'common': shared,
        # Espaces personnels de comptes désactivés : seuls ceux-là peuvent être repris.
        'orphans': sorted(name for name in owners if name not in active),
        'levels': list(LEVELS), 'name_max': NAME_MAX}


def save_group(app, body, actor):
    name = title(app, body.get('name'), 'de groupe')
    members = body.get('members', [])
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        known = {p['name'] for p in accounts(db)}
        if not isinstance(members, list) or len(members) > 500 or any(m not in known for m in members):
            raise app.Problem('Membres invalides.')
        ident = body.get('id')
        if ident is None:
            ident = secrets.token_hex(6)
        elif not isinstance(ident, str) or not IDENT.fullmatch(ident) or not get(db, 'group:' + ident):
            raise app.Problem('Groupe inconnu.', 404)
        if any(g.get('name', '').casefold() == name.casefold() and g.get('id') != ident for g in every(db, 'group:')):
            raise app.Problem('Un groupe porte déjà ce nom.', 409)
        put(db, 'group:' + ident, {'id': ident, 'name': name, 'members': sorted(set(members))})
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Groupe enregistré', f'{name} · {len(set(members))} membre(s)'))
    return {'ok': True, 'id': ident}


def delete_group(app, body, actor):
    ident = body.get('id')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        doc = get(db, 'group:' + ident) if isinstance(ident, str) and IDENT.fullmatch(ident) else None
        if not doc:
            raise app.Problem('Groupe inconnu.', 404)
        # Le groupe disparaît aussi des espaces : aucun accès ne survit à sa suppression.
        for space in every(db, 'space:'):
            if space.get('kind') and ident in space.get('groups', {}):
                space['groups'].pop(ident)
                put(db, 'space:' + space['id'], space)
        shared = common(db)
        if shared['groups'].pop(ident, None):
            put(db, COMMON, shared)
        db.execute('DELETE FROM settings WHERE key=?', ('group:' + ident,))
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Groupe supprimé', doc.get('name', '')))
    return {'ok': True}


def save_space(app, body, actor):
    """Crée un espace d'équipe ou en change le nom et les accès. Aucun fichier n'est déplacé."""
    name = title(app, body.get('name'), 'd’espace')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        known, groups = {p['name'] for p in accounts(db)}, {g['id'] for g in every(db, 'group:')}
        members, shared = access(app, body, known, groups)
        ident = body.get('id')
        if ident is None:
            doc = {'id': secrets.token_hex(6), 'kind': 'team', 'created': time.time()}
        else:
            match = SPACE.fullmatch(ident) if isinstance(ident, str) else None
            doc = get(db, 'space:' + match[1]) if match else None
            if not isinstance(doc, dict) or doc.get('kind') != 'team':
                raise app.Problem('Espace d’équipe inconnu.', 404)
        if any(s.get('kind') == 'team' and s.get('name', '').casefold() == name.casefold() and s.get('id') != doc['id'] for s in every(db, 'space:')):
            raise app.Problem('Un espace porte déjà ce nom.', 409)
        doc.update(name=name, members=members, groups=shared)
        put(db, 'space:' + doc['id'], doc)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Espace enregistré', f'{name} · {len(members)} personne(s), {len(shared)} groupe(s)'))
    resource(app, 'espace_' + doc['id'])
    return {'ok': True, 'id': 'espace_' + doc['id']}


def delete_space(app, body, actor):
    """Supprime un espace d'équipe vide. Un espace qui contient encore quelque chose, corbeille comprise, est refusé."""
    ident = body.get('id')
    match = SPACE.fullmatch(ident) if isinstance(ident, str) else None
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        doc = get(db, 'space:' + match[1]) if match else None
        if not isinstance(doc, dict) or doc.get('kind') != 'team':
            raise app.Problem('Espace d’équipe inconnu.', 404)
        path = root(app) / match[1]
        if path.is_dir():
            trash = path / '.nacre-trash'
            if any(name != '.nacre-trash' for name in os.listdir(path)) or (trash.is_dir() and os.listdir(trash)):
                raise app.Problem('Cet espace contient encore des fichiers ou une corbeille non vide. Videz-le avant de le supprimer : rien n’est effacé à votre place.', 409)
            if trash.is_dir():
                trash.rmdir()
            path.rmdir()
        db.execute('DELETE FROM settings WHERE key=?', ('space:' + match[1],))
        db.execute('DELETE FROM settings WHERE key=?', ('usage-kept:' + ident,))
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Espace supprimé', doc.get('name', '')))
    return {'ok': True}


def save_common(app, body, actor):
    """Accès des membres à l'espace commun « Fichiers partagés »."""
    everyone = body.get('everyone')
    if everyone not in LEVELS + (None,):
        raise app.Problem('Niveau invalide pour l’espace commun.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        known, groups = {p['name'] for p in accounts(db)}, {g['id'] for g in every(db, 'group:')}
        members, shared = access(app, body, known, groups)
        put(db, COMMON, {'everyone': everyone, 'members': members, 'groups': shared})
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Accès à l’espace commun modifiés',
                   {'read': 'tous les membres en lecture', 'write': 'tous les membres en écriture', None: 'fermé aux membres par défaut'}[everyone]))
    return {'ok': True}


def save_person(app, body, actor):
    """Ce qu'un membre voit en plus de ses fichiers. Le rôle et le mot de passe restent gérés avec le compte."""
    name, camera = body.get('name'), body.get('camera')
    if type(camera) is not bool:
        raise app.Problem('Réglage invalide.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not isinstance(name, str) or not db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
            raise app.Problem('Compte inconnu.', 404)
        put(db, 'person:' + name, {**person(db, name), 'camera': camera})
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Accès d’une personne modifiés', f'{name} · surveillance {"ouverte" if camera else "fermée"}'))
    return {'ok': True}


def adopt(app, body, actor):
    """Reprend l'espace personnel d'un compte désactivé : il devient un espace d'équipe, sans déplacer un seul fichier."""
    name = body.get('name')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT active FROM users WHERE name=?', (name,)).fetchone() if isinstance(name, str) else None
        doc = personal(db, name) if row else None
        if not doc:
            raise app.Problem('Aucun espace personnel à reprendre pour ce compte.', 404)
        if row['active']:
            raise app.Problem('Ce compte est actif : son espace personnel reste fermé. Désactivez le compte avant de reprendre son espace.', 409)
        wanted, index = f'Espace de {name}', 1
        names = {s.get('name', '').casefold() for s in every(db, 'space:') if s.get('kind') == 'team'}
        while wanted.casefold() in names:
            index += 1
            wanted = f'Espace de {name} ({index})'
        doc.update(kind='team', name=wanted, former=name, owner=None, members={}, groups={})
        put(db, 'space:' + doc['id'], doc)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Espace personnel repris', f'{name} → {wanted}'))
    return {'ok': True, 'id': 'espace_' + doc['id']}


def change_password(app, body, session):
    """Changement de son propre mot de passe : l'ancien est exigé, les autres sessions du compte sont fermées."""
    import hmac
    current, wanted = body.get('current'), body.get('password')
    if not isinstance(current, str) or not isinstance(wanted, str) or not 12 <= len(wanted) <= 128:
        raise app.Problem('Mot de passe invalide : 12 caractères minimum.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT salt,hash FROM users WHERE name=? AND active=1', (session['name'],)).fetchone()
        if not row or not hmac.compare_digest(app.password_hash(current, row['salt']), row['hash']):
            raise app.Problem('Mot de passe actuel refusé.', 403)
        salt = secrets.token_hex(16)
        db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, app.password_hash(wanted, salt), session['name']))
        db.execute('DELETE FROM sessions WHERE name=? AND token<>?', (session['name'], session['token']))
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], 'Mot de passe modifié', ''))
    return {'ok': True}
