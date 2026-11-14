"""Première configuration authentifiée ; détection sans modification de l’hôte."""
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

# Fichiers techniques de la base des fuseaux : lisibles par le serveur, inconnus des navigateurs.
PSEUDO_ZONES = ('localtime', 'posixrules', 'Factory')
ZONE_FAMILIES = ('posix/', 'right/', 'SystemV/')


def read(app, db=None):
    if db is None:
        with app.database() as connection:
            return read(app, connection)
    row = db.execute("SELECT value FROM settings WHERE key='onboarding'").fetchone()
    # Une mise à jour n’impose pas de réinitialiser les comptes existants.
    return json.loads(row[0]) if row else {'phase': 'complete', 'name': 'Nacre', 'timezone': 'UTC', 'existing': True}


def write(db, value):
    db.execute("INSERT INTO settings(key,value) VALUES('onboarding',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(value),))


def unset(state):
    """Le fuseau n'a jamais été choisi : installation antérieure à l'assistant, encore sur l'UTC d'origine."""
    return state['phase'] == 'complete' and state.get('timezone') == 'UTC' and not state.get('preferences_revision', 0)


@lru_cache(maxsize=1)
def zones():
    """Fuseaux proposés au choix : UTC et les noms géographiques connus de ce système."""
    try:
        names = available_timezones()
    except OSError:
        names = set()
    return ['UTC'] + sorted(z for z in names if '/' in z and not z.startswith(('Etc/',) + ZONE_FAMILIES))


def account(app, body, session):
    password = body.get('password')
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise app.Problem('Choisissez un mot de passe de 12 à 128 caractères.')
    if password != body.get('confirmation'):
        raise app.Problem('Les deux mots de passe ne correspondent pas.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        state = read(app, db)
        if state['phase'] != 'account' or session['name'] != 'admin':
            raise app.Problem('Le compte initial est déjà configuré. Utilisez la page Utilisateurs.', 409)
        old = db.execute("SELECT * FROM users WHERE name='admin' AND active=1 AND role='admin'").fetchone()
        if not old:
            raise app.Problem('Le compte initial n’est plus disponible.', 409)
        if app.password_hash(password, old['salt']) == old['hash']:
            raise app.Problem('Choisissez un mot de passe différent de l’accès provisoire.')
        salt, csrf = secrets.token_hex(16), secrets.token_urlsafe(24)
        db.execute("UPDATE users SET salt=?,hash=? WHERE name='admin'", (salt, app.password_hash(password, salt)))
        db.execute('DELETE FROM sessions WHERE token<>?', (session['token'],))
        db.execute('UPDATE sessions SET csrf=? WHERE token=?', (csrf, session['token']))
        db.execute('DELETE FROM tickets')
        state['phase'] = 'system'
        write(db, state)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], 'Compte initial sécurisé', ''))
    # Le mot de passe choisi ne quitte jamais la base sous forme lisible.
    app.private_write(app.STATE/'acces.txt', 'Console Nacre — utilisateur admin.\nUtiliser le mot de passe choisi dans l’assistant.\n')
    return {'csrf': csrf, 'phase': 'system'}


def preferences(app, body):
    name, timezone = body.get('name'), body.get('timezone')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48 or any(ord(c) < 32 for c in name):
        raise app.Problem('Le nom du NAS doit contenir de 1 à 48 caractères.')
    if not isinstance(timezone, str) or len(timezone) > 100:
        raise app.Problem('Choisissez un fuseau horaire valide.')
    try:
        if timezone in PSEUDO_ZONES or timezone.startswith(ZONE_FAMILIES):
            raise ValueError(timezone)
        ZoneInfo(timezone)
    except (ValueError, OSError, ZoneInfoNotFoundError):
        raise app.Problem('Fuseau horaire inconnu sur ce système.') from None
    return name.strip(), timezone


def finish(app, body, session):
    name, timezone = preferences(app, body)
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        state = read(app, db)
        if state['phase'] == 'account':
            raise app.Problem('Sécurisez d’abord le compte administrateur.', 409)
        state.update(phase='complete', name=name, timezone=timezone, preferences_revision=state.get('preferences_revision',0)+1)
        write(db, state)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], 'Première configuration enregistrée', ''))
    return state


ACCESS = {
    'direct': {True: 'Docker et Compose accessibles. Démarrez les services lorsque vous êtes prêt.',
               False: 'Installer Docker Engine et Compose v2, puis autoriser le compte de console.'},
    'agent': {True: 'Docker est piloté par l’agent de services ; le compte de la console n’y a plus d’accès direct.',
              False: 'L’agent de services ne joint pas Docker. Consulter son journal système.'},
    'mixed': {True: 'L’agent de services est actif, mais le compte de la console garde un accès direct à Docker : la réduction de privilèges reste à terminer.',
              False: 'L’agent de services ne joint pas Docker. Consulter son journal système.'},
}


def probe(args):
    try:
        return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def status(app):
    state = read(app)
    capacity = shutil.disk_usage(app.ROOT)
    found = app.service_op('engine')
    docker, engine, compose = found['docker'], found['engine'], found['compose']
    # Qui pilote Docker : l'agent de services seul, l'agent alors que le compte de la console y accède encore, ou ce compte seul.
    from service_agent import agent_present
    direct = os.access('/var/run/docker.sock', os.W_OK)
    access = ('mixed' if direct else 'agent') if agent_present() else 'direct'
    protection = app.protection().capabilities()
    from native_storage import SOCKET
    native_socket = os.path.exists(SOCKET)
    with app.database() as db:
        repositories = db.execute('SELECT count(*) FROM repositories').fetchone()[0]
        plans = db.execute('SELECT count(*) FROM plans WHERE enabled=1').fetchone()[0]
    return {**state, 'timezones': zones(), 'system': {'os': platform.system(), 'architecture': platform.machine(),
            'python': platform.python_version(), 'cpus': os.cpu_count(), 'free': capacity.free,
            'supported': platform.system() == 'Linux' and platform.machine() in ('x86_64', 'amd64', 'aarch64', 'arm64') and sys.version_info >= (3, 11),
            'non_root': os.getuid() != 0},
        'capabilities': [
            {'id': 'files', 'title': 'Fichiers', 'ready': os.access(app.ROOT/'data/fichiers', os.W_OK),
             'detail': 'Espace local de fichiers de cette installation.', 'page': 'files'},
            {'id': 'docker', 'title': 'Partages et vidéo', 'ready': bool(engine and compose), 'access': access,
             'detail': ACCESS[access][bool(engine and compose)], 'page': 'services'},
            {'id': 'restic', 'title': 'Sauvegardes', 'ready': protection['available'],
             'detail': f'{repositories} dépôt(s), {plans} plan(s) actif(s).' if protection['available'] else 'Installer le moteur restic sur le serveur pour créer des sauvegardes.', 'page': 'backups'},
            {'id': 'native', 'title': 'Pools et snapshots natifs', 'ready': False,
             'detail': 'Service natif détecté : vérifier ses droits et volumes dans Stockage.' if native_socket else 'Service natif optionnel à installer avec une politique de disques explicite.', 'page': 'native',
             'detected': native_socket},
        ]}
