"""Appareils : un mot de passe par appareil, pour les outils qui ne savent pas passer la double authentification.

Un outil de synchronisation, une application de téléphone ou un lecteur réseau ne saisit ni code à six chiffres ni
mot de passe du compte : il reçoit un mot de passe qui lui est propre, produit par Nacre, montré une seule fois et
gardé sous forme d'empreinte. Il n'ouvre que les fichiers des espaces de la personne, jamais l'administration, et
se retire d'un geste sans toucher aux autres. Changer son mot de passe ou retirer sa double authentification les
retire tous.
"""
import base64
import binascii
import hashlib
import hmac
import json
import secrets
import threading
import time

import spaces

PREFIX = 'device:'
LIMIT = 20
NAME_MAX = 40
ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'   # sans l, i, o, 0 ni 1 : se recopie sans hésiter
GROUPS, GROUP = 6, 4
FAILURES = 10        # refus par minute et par adresse, avant de ne plus lui répondre
TOUCH = 3600         # le dernier usage se note au plus une fois par heure : une synchronisation n'écrit pas à chaque requête
DENIED = {'name': '', 'role': 'none'}
LOCK = threading.Lock()
FAILED = {}


def normal(text):
    return ''.join(c for c in text.lower() if c in ALPHABET) if isinstance(text, str) else ''


def new_password():
    raw = ''.join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP))
    return '-'.join(raw[i:i + GROUP] for i in range(0, len(raw), GROUP))


def digest(password):
    return hashlib.sha256(('nacre-appareil:' + normal(password)).encode()).hexdigest()


def every(db, owner=None):
    found = [doc for doc in spaces.every(db, PREFIX) if isinstance(doc.get('id'), str) and isinstance(doc.get('hash'), str) and isinstance(doc.get('owner'), str)]
    return sorted((doc for doc in found if owner is None or doc['owner'] == owner), key=lambda doc: doc.get('created', 0))


def public(doc):
    return {'id': doc['id'], 'name': doc.get('name', ''), 'write': doc.get('write') is True, 'created': doc.get('created', 0), 'used': doc.get('used', 0)}


def listing(app, name):
    with app.database() as db:
        return [public(doc) for doc in every(db, name)]


def create(app, body, session, now=None):
    """Ajoute un appareil. Le mot de passe du compte est redemandé, et le code si la double authentification est active."""
    import totp
    now = time.time() if now is None else now
    name = body.get('name')
    name = ' '.join(name.split()) if isinstance(name, str) else ''
    if not 1 <= len(name) <= NAME_MAX or any(ord(c) < 32 for c in name):
        raise app.Problem(f'Donnez un nom à cet appareil, {NAME_MAX} caractères au plus.')
    if type(body.get('write', False)) is not bool:
        raise app.Problem('Réglages invalides.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not totp.password_ok(app, db, session['name'], body.get('password')):
            raise app.Problem('Mot de passe actuel refusé.', 403)
        if totp.enabled(db, session['name']) and not totp.check(app, db, session['name'], body.get('code'), now):
            raise app.Problem('Code refusé.', 403)
        if len(every(db, session['name'])) >= LIMIT:
            raise app.Problem(f'Vous avez déjà {LIMIT} appareils. Retirez-en un avant d’en ajouter.', 409)
        password = new_password()
        fingerprint = digest(password)
        doc = {'id': fingerprint[:12], 'owner': session['name'], 'name': name, 'hash': fingerprint, 'write': body.get('write') is True, 'created': now, 'used': 0}
        spaces.put(db, PREFIX + fingerprint[:32], doc)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (now, session['name'], 'Appareil ajouté', name))
    return {'device': public(doc), 'password': password, 'username': session['name']}


def remove(db, doc):
    db.execute('DELETE FROM settings WHERE key=?', (PREFIX + doc['hash'][:32],))


def revoke(app, body, session):
    """Retire un appareil : le sien, ou celui de quelqu'un d'autre pour un administrateur."""
    ident = body.get('id')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        doc = next((d for d in every(db) if d['id'] == ident), None) if isinstance(ident, str) else None
        if not doc or (doc['owner'] != session['name'] and session['role'] != 'admin'):
            raise app.Problem('Appareil inconnu.', 404)
        remove(db, doc)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], 'Appareil retiré',
                   doc.get('name', '') if doc['owner'] == session['name'] else f'{doc.get("name", "")} ({doc["owner"]})'))
    return {'ok': True}


def revoke_all(db, name, actor, reason):
    """Retire tous les appareils d'une personne, dans la transaction de ce qui le motive : mot de passe changé, double authentification retirée."""
    found = every(db, name)
    for doc in found:
        remove(db, doc)
    if found:
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), actor, 'Appareils retirés', f'{len(found)} · {reason}' + ('' if actor == name else f' ({name})')))
    return len(found)


def counts(db):
    found = {}
    for doc in every(db):
        found[doc['owner']] = found.get(doc['owner'], 0) + 1
    return found


def blocked(*keys, now=None):
    now = time.time() if now is None else now
    with LOCK:
        for key in list(FAILED):
            FAILED[key] = [t for t in FAILED[key] if t > now - 60]
            if not FAILED[key]:
                del FAILED[key]
        return any(len(FAILED.get(key, ())) >= FAILURES for key in keys)


def failed(*keys, now=None):
    now = time.time() if now is None else now
    with LOCK:
        if len(FAILED) > 5000:
            FAILED.clear()
        for key in keys:
            FAILED.setdefault(key, []).append(now)


def refuse(app, message='Identifiant ou mot de passe d’appareil refusé.'):
    problem = app.Problem(message, 401)
    problem.challenge = True
    return problem


def authenticate(app, handler, now=None):
    """Session d'un appareil d'après l'en-tête Authorization, ou refus. Les droits restent ceux, vivants, de la personne.

    Un navigateur n'a rien à faire ici : toute requête qui en porte la marque est refusée sans demander de mot de passe,
    pour qu'aucun navigateur ne retienne un mot de passe d'appareil pour l'adresse de la console.
    """
    now = time.time() if now is None else now
    headers = handler.headers
    if headers.get('Origin') is not None or any(key.lower().startswith('sec-fetch-') for key in headers.keys()):
        raise app.Problem('Cette adresse est réservée aux appareils et aux outils de synchronisation.', 403)
    value = headers.get('Authorization', '')
    if not value.startswith('Basic ') or len(value) > 600:
        raise refuse(app, 'Mot de passe d’appareil attendu.')
    try:
        username, _, password = base64.b64decode(value[6:].strip(), validate=True).decode('utf-8').partition(':')
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise refuse(app) from None
    address = 'a:' + str(handler.client_address[0])
    fingerprint = digest(password)
    with app.database() as db:
        doc = spaces.get(db, PREFIX + fingerprint[:32]) if len(normal(password)) == GROUPS * GROUP else None
        valid = isinstance(doc, dict) and isinstance(doc.get('hash'), str) and hmac.compare_digest(doc['hash'], fingerprint) and doc.get('owner') == username
        # Compte désactivé ou rôle changé : pris en compte à la requête suivante, sans attendre.
        row = db.execute('SELECT role FROM users WHERE name=? AND active=1', (username,)).fetchone() if valid else None
        if not row:
            # Les refus se comptent par adresse seulement : compter par identifiant laisserait n'importe qui bloquer les appareils
            # d'un compte dont il connaît le nom. Un mot de passe juste passe toujours ; il ne se devine pas.
            if blocked(address, now=now):
                problem = app.Problem('Trop de refus. Attendre une minute.', 429)
                problem.retry = 60
                raise problem
            failed(address, now=now)
            raise refuse(app)
        if now - (doc.get('used') or 0) > TOUCH:
            # Mise à jour seule, jamais de création : un appareil retiré entre la lecture et cette écriture reste retiré.
            if db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps({**doc, 'used': now}), PREFIX + fingerprint[:32])).rowcount != 1:
                raise refuse(app)
    return {'name': username, 'role': row['role'], 'csrf': '', 'device': {'id': doc['id'], 'write': doc.get('write') is True}}


def revoke_person(app, body, actor):
    """Un administrateur retire tous les appareils d'une personne, par exemple après la perte d'un téléphone."""
    name = body.get('name')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not isinstance(name, str) or not db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
            raise app.Problem('Compte inconnu.', 404)
        removed = revoke_all(db, name, actor, 'retirés par un administrateur')
    return {'ok': True, 'removed': removed}
