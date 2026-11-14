"""Liens de partage : un fichier ou un dossier ouvert en lecture, sans compte, jusqu'à une date.

Le jeton n'est jamais conservé : seule son empreinte l'est (`link:<empreinte>` dans la table de réglages).
Un lien cesse de fonctionner à son échéance, à sa révocation, si sa cible disparaît, ou dès que son auteur
n'a plus accès à l'espace. Le visiteur ne lit que ce que le lien désigne, par les mêmes contrôles que tout le monde.
"""
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import time
from urllib.parse import quote

import spaces

DAYS = (1, 7, 30, 90)
PASSWORD_MIN = 8
PER_PERSON = 200
PROOF_SECONDS = 3600
GONE = 'Ce lien n’existe pas ou n’est plus valable.'
# Preuves de mot de passe saisi, gardées en mémoire : un redémarrage les oublie, il suffit de le ressaisir.
PROOFS = {}
LOCK = threading.Lock()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def target(app, area, path):
    """Nom et nature de la cible ; un lien symbolique ou un fichier spécial ne se partage pas."""
    with app.parent(area, path) as (fd, name):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise app.Problem('Seuls un fichier ordinaire ou un dossier se partagent.')
    return name, stat.S_ISDIR(info.st_mode)


def create(app, body, session, now=None):
    now = time.time() if now is None else now
    area, path, days, password = body.get('area'), body.get('path'), body.get('days'), body.get('password') or ''
    if not isinstance(area, str) or not (area == 'fichiers' or spaces.SPACE.fullmatch(area)):
        raise app.Problem('Cet espace ne se partage pas par lien.', 403)
    if spaces.level(app, session, area) != 'write':
        raise app.Problem('Créer un lien demande l’écriture dans cet espace.', 403)
    if days not in DAYS or isinstance(days, bool):
        raise app.Problem('Durée invalide : 1, 7, 30 ou 90 jours.')
    if not isinstance(password, str) or (password and not PASSWORD_MIN <= len(password) <= 128):
        raise app.Problem(f'Mot de passe du lien : {PASSWORD_MIN} caractères minimum.')
    if not isinstance(path, str) or not app.parts(path):
        raise app.Problem('Choisir un fichier ou un dossier à partager.')
    name, directory = target(app, area, path)
    token = secrets.token_urlsafe(32)
    doc = {'area': area, 'path': '/'.join(app.parts(path)), 'name': name, 'directory': directory, 'by': session['name'],
           'created': now, 'expires': now + days * 86400, 'uses': 0, 'last': None}
    if password:
        salt = secrets.token_hex(16)
        doc['password'] = {'salt': salt, 'hash': app.password_hash(password, salt)}
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        if sum(1 for link in spaces.every(db, 'link:') if link.get('by') == session['name'] and link.get('expires', 0) > now) >= PER_PERSON:
            raise app.Problem(f'Vous avez déjà {PER_PERSON} liens actifs. Révoquez-en avant d’en créer d’autres.', 409)
        spaces.put(db, 'link:' + digest(token), doc)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (now, session['name'], 'Lien de partage créé',
                   spaces.detail(app, area, f'{doc["path"]} · {days} jour(s)' + (' · avec mot de passe' if password else ''))))
    return {'ok': True, 'url': '/p/' + token, 'expires': doc['expires'], 'name': name}


def records(db):
    return [(row['key'][5:], json.loads(row['value'])) for row in db.execute("SELECT key,value FROM settings WHERE key LIKE 'link:%'")]


def listing(app, session, now=None):
    """Liens de la personne ; un administrateur les voit tous, sans les noms d'un espace personnel qui n'est pas le sien."""
    now = time.time() if now is None else now
    admin = session.get('role') == 'admin'
    with app.database() as db:
        found = records(db)
        # Ménage : un lien échu depuis plus de trente jours disparaît de la liste.
        for key, doc in found:
            if doc.get('expires', 0) < now - 30 * 86400:
                db.execute('DELETE FROM settings WHERE key=?', ('link:' + key,))
    items = []
    for key, doc in sorted(found, key=lambda entry: -entry[1].get('created', 0)):
        if doc.get('expires', 0) < now - 30 * 86400 or not (admin or doc.get('by') == session['name']):
            continue
        hidden = doc.get('by') != session['name'] and spaces.private(app, doc.get('area'))
        items.append({'id': key[:16], 'name': 'espace personnel' if hidden else doc.get('name', ''), 'path': '' if hidden else doc.get('path', ''),
                      'directory': bool(doc.get('directory')), 'space': space_name(app, doc.get('area')), 'by': doc.get('by', ''),
                      'created': doc.get('created'), 'expires': doc.get('expires'), 'expired': doc.get('expires', 0) <= now,
                      'protected': 'password' in doc, 'uses': int(doc.get('uses', 0)), 'last': doc.get('last')})
    return {'links': items, 'days': list(DAYS), 'password_min': PASSWORD_MIN}


def space_name(app, area):
    if area == 'fichiers':
        return 'Fichiers partagés'
    match = spaces.SPACE.fullmatch(area) if isinstance(area, str) else None
    with app.database() as db:
        doc = spaces.get(db, 'space:' + match[1], {}) if match else {}
    return 'Espace personnel' if doc.get('kind') == 'personal' else doc.get('name', 'Espace supprimé')


def revoke(app, body, session):
    ident = body.get('id')
    if not isinstance(ident, str) or len(ident) != 16:
        raise app.Problem('Lien invalide.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        match = next(((key, doc) for key, doc in records(db) if key[:16] == ident), None)
        if not match or not (session.get('role') == 'admin' or match[1].get('by') == session['name']):
            raise app.Problem('Lien inconnu.', 404)
        db.execute('DELETE FROM settings WHERE key=?', ('link:' + match[0],))
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], 'Lien de partage révoqué',
                   spaces.detail(app, match[1].get('area'), match[1].get('path', ''))))
    with LOCK:
        for proof in [p for p, (key, _) in PROOFS.items() if key == match[0]]:
            PROOFS.pop(proof, None)
    return {'ok': True}


# Côté visiteur.

def resolve(app, token, now=None):
    """Lien valable et son empreinte, ou un refus identique quelle qu'en soit la raison."""
    now = time.time() if now is None else now
    if not isinstance(token, str) or not 40 <= len(token) <= 64:
        raise app.Problem(GONE, 404)
    key = digest(token)
    with app.database() as db:
        doc = spaces.get(db, 'link:' + key)
        author = db.execute('SELECT role FROM users WHERE name=? AND active=1', (doc.get('by'),)).fetchone() if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or doc.get('expires', 0) <= now or not author:
        raise app.Problem(GONE, 404)
    # L'auteur doit encore pouvoir lire l'espace : un accès retiré éteint ses liens.
    if spaces.level(app, {'name': doc['by'], 'role': author['role']}, doc.get('area')) is None:
        raise app.Problem(GONE, 404)
    return key, doc


def unlocked(key, doc, proof):
    if 'password' not in doc:
        return True
    with LOCK:
        entry = PROOFS.get(proof) if isinstance(proof, str) else None
        return bool(entry) and entry[0] == key and entry[1] > time.time()


def unlock(app, handler, token, body):
    key, doc = resolve(app, token)
    if 'password' not in doc:
        return {'ok': True}, None
    if not handler.server.login_limit(handler.client_address[0]):
        raise app.Problem('Trop de tentatives. Attendre une minute.', 429)
    password = body.get('password') if isinstance(body, dict) else None
    if not isinstance(password, str) or not hmac.compare_digest(app.password_hash(password, doc['password']['salt']), doc['password']['hash']):
        raise app.Problem('Mot de passe refusé.', 403)
    proof = secrets.token_urlsafe(32)
    with LOCK:
        now = time.time()
        for old in [p for p, (_, until) in PROOFS.items() if until <= now]:
            PROOFS.pop(old, None)
        if len(PROOFS) < 10000:
            PROOFS[proof] = (key, now + PROOF_SECONDS)
    return {'ok': True}, f'nacre_link={proof}; HttpOnly; SameSite=Strict; Path=/api/public/; Max-Age={PROOF_SECONDS}'


def inside(app, doc, sub):
    """Chemin réel d'un élément du lien. Un lien de fichier ne désigne que ce fichier."""
    extra = app.parts(sub or '')
    if extra and not doc.get('directory'):
        raise app.Problem(GONE, 404)
    if any(name.startswith('.') for name in extra):
        raise app.Problem(GONE, 404)
    return '/'.join(app.parts(doc['path']) + extra)


def used(app, key, doc, what):
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        current = spaces.get(db, 'link:' + key)
        if isinstance(current, dict):
            current.update(uses=int(current.get('uses', 0)) + 1, last=time.time())
            spaces.put(db, 'link:' + key, current)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), 'lien', 'Lien de partage utilisé',
                   spaces.detail(app, doc.get('area'), what)))


def public(app, handler, path, query, post):
    """Routes sans compte : /api/public/<jeton>[/unlock|/download|/archive]. La session du fil devient celle du lien."""
    pieces = path[len('/api/public/'):].split('/')
    token, action = pieces[0], pieces[1] if len(pieces) > 1 else ''
    if len(pieces) > 2 or action not in ('', 'unlock', 'download', 'archive') or post != (action == 'unlock'):
        raise app.Problem(GONE, 404)
    if post:
        if handler.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise app.Problem('Origine non autorisée.', 403)
        answer, cookie = unlock(app, handler, token, handler.body())
        return handler.reply(200, answer, extra={'Set-Cookie': cookie} if cookie else None)
    key, doc = resolve(app, token)
    proof = next((part.strip().partition('=')[2] for part in handler.headers.get('Cookie', '').split(';') if part.strip().startswith('nacre_link=')), None)
    opened = unlocked(key, doc, proof)
    base = {'name': doc['name'], 'directory': bool(doc.get('directory')), 'expires': doc['expires'], 'protected': 'password' in doc, 'locked': not opened}
    if not opened:
        if action:
            raise app.Problem('Mot de passe requis.', 403)
        return handler.reply(200, base)
    # À partir d'ici, tout dossier ouvert l'est avec les droits du lien : lecture, dans son seul espace.
    app.ACTOR.session = {'name': 'lien', 'role': 'link', 'link': doc}
    try:
        full = inside(app, doc, query.get('path', ''))
        if action == 'download':
            name, directory = target(app, doc['area'], full)
            if directory:
                raise app.Problem('Choisir un fichier.', 400)
            used(app, key, doc, full)
            return handler.download({'area': doc['area'], 'path': full})
        if action == 'archive':
            if not doc.get('directory'):
                raise app.Problem(GONE, 404)
            parent, _, name = full.rpartition('/')
            used(app, key, doc, full + ' (archive)')
            return handler.archive({'area': doc['area'], 'path': parent}, [name], {'name': 'lien'})
        if not doc.get('directory'):
            with app.parent(doc['area'], full) as (fd, name):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise app.Problem(GONE, 404)
            return handler.reply(200, {**base, 'size': info.st_size, 'modified': info.st_mtime})
        items = [item for item in app.list_files(doc['area'], full) if not item['link']]
        return handler.reply(200, {**base, 'path': '/'.join(app.parts(query.get('path', ''))), 'items': items})
    except (FileNotFoundError, NotADirectoryError):
        raise app.Problem(GONE, 404) from None
