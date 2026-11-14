"""Opérations de services : la seule porte de la console vers Docker.

Le compte de la console peut piloter Docker, ce qui vaut des pouvoirs élevés sur l'hôte. Ce module ferme la liste de ce
que le processus web lui demande : chaque opération a un nom, des paramètres validés et une ligne de commande fixe.
Aucune ne reçoit de commande, d'option ni de chemin libre. Le reste de la console passe par `request`.

Les opérations s'exécutent encore dans le processus web. Elles sont écrites pour partir telles quelles dans un agent
séparé, joint par un socket : voir docs/SERVICE-AGENT.md.
"""
import re
from pathlib import Path

COMPONENTS = ('video', 'fichiers')
ACTIONS = ('start', 'stop', 'restart')
# Seul programme jamais exécuté dans le conteneur vidéo : faire valider une configuration par Frigate.
VALIDATE = 'import json,sys;from frigate.config import FrigateConfig;FrigateConfig.model_validate(json.load(sys.stdin))'
# Seul script jamais exécuté dans le conteneur de fichiers : lecture, traversée et, au besoin, écriture d'un dossier partagé.
ACCESS = 'test -r "$1" && test -x "$1" && { [ "$2" = r ] || test -w "$1"; }'
ACCOUNT = re.compile(r'[a-z][a-z0-9_-]{2,23}\Z')
SHARE = re.compile(r'[a-z][a-z0-9_-]{1,31}\Z')
AREA = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z')
CONTAINER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
CANDIDATE = re.compile(r'\.smb-[a-f0-9]{20}\.conf\Z')
MOUNTS = re.compile(r'\.mounts-[a-f0-9]{20}\.json\Z')


def _require(app, condition):
    if not condition:
        raise app.Problem('Opération de service non autorisée.')


def _timed(timeout):
    return {} if timeout is None else {'timeout': timeout}


def _component(app, name):
    _require(app, name in COMPONENTS)
    return name


def status(app, component=None, timeout=3):
    """État des conteneurs du projet, tel que Compose le rend."""
    _require(app, type(timeout) in (int, float) and 0 < timeout <= 60)
    return app.compose('ps', '--all', '--format', 'json', *([_component(app, component)] if component is not None else []), timeout=timeout)


def video_address(app):
    """Adresse du conteneur vidéo sur son réseau ; chaîne vide s'il est arrêté ou redémarre. Rien d'autre de son inspection ne sort."""
    import json
    identifier = app.compose('ps', '-q', 'video').strip()
    if not identifier:
        return None
    _require(app, CONTAINER.fullmatch(identifier))
    data = json.loads(app.command(['docker', 'inspect', identifier]))[0]
    return next(iter(data['NetworkSettings']['Networks'].values()))['IPAddress'] or ''


def control(app, name, action, timeout=None):
    """Démarrer, arrêter ou redémarrer un des deux services."""
    _require(app, action in ACTIONS and (timeout is None or (type(timeout) in (int, float) and 0 < timeout <= 600)))
    return app.compose(action, _component(app, name), **_timed(timeout))


def recreate_files(app):
    """Recréer le conteneur de fichiers, pour prendre de nouveaux montages."""
    return app.compose('up', '-d', '--no-deps', '--force-recreate', 'fichiers', timeout=90)


def engine(app, lookup=True):
    """Docker et Compose répondent-ils au compte de la console ?"""
    import onboarding
    info, version = ['docker', 'info', '--format', '{{.ServerVersion}}'], ['docker', 'compose', 'version']
    if lookup:
        present = bool(onboarding.shutil.which('docker'))
        return {'docker': present, 'engine': bool(present and onboarding.probe(info)), 'compose': bool(present and onboarding.probe(version))}
    ready = bool(onboarding.probe(info))
    return {'docker': ready, 'engine': ready, 'compose': bool(ready and onboarding.probe(version))}


def build(app, component):
    """Construire l'image d'un service depuis les sources de l'installation."""
    return app.compose('build', _component(app, component), timeout=1800 if component == 'video' else 1200)


def start_component(app, component):
    """Démarrer un service déjà construit, sans ses dépendances."""
    return app.compose('up', '-d', '--no-deps', '--no-build', _component(app, component), timeout=180)


def video_validate(app, document, timeout=None):
    """Soumettre une configuration à Frigate, sans l'appliquer."""
    import json
    _require(app, isinstance(document, dict) and (timeout is None or (type(timeout) in (int, float) and 0 < timeout <= 120)))
    return app.compose('exec', '-T', 'video', 'python3', '-c', VALIDATE, data=json.dumps(document), **_timed(timeout))


def samba_group(app):
    """Numéro du groupe des comptes de partage dans le conteneur."""
    return app.compose('exec', '-T', 'fichiers', 'id', '-g', 'nas')


def samba_access(app, uid, group, path, readonly):
    """Un compte peut-il lire, traverser et au besoin écrire un dossier partagé ? Échoue sinon."""
    parts = path.split('/') if isinstance(path, str) else []
    _require(app, type(uid) is int and 0 < uid < 2**31 and isinstance(group, str) and group.isdecimal() and type(readonly) is bool
             and len(parts) >= 3 and parts[:2] == ['', 'shares'] and AREA.fullmatch(parts[2]) and len(path) <= 4096
             and not any(part in ('', '.', '..') for part in parts[2:]) and not any(ord(char) < 32 or char == '\x7f' for char in path))
    return app.compose('exec', '-T', '--user', str(uid) + ':' + group, 'fichiers', 'sh', '-c', ACCESS, 'sh', path, 'r' if readonly else 'rw')


def samba_identity(app, area):
    """Périphérique et inode du dossier monté pour un espace, vus du conteneur."""
    _require(app, isinstance(area, str) and AREA.fullmatch(area))
    return app.compose('exec', '-T', 'fichiers', 'stat', '-c', '%d:%i', '/shares/' + area)


def samba_mounts_check(app, override):
    """Faire valider par Compose un fichier de montages candidat, écrit par la console dans son dossier Samba."""
    from compose_support import arguments
    path = Path(override)
    _require(app, path.parent == Path(app.ROOT) / 'state/samba' and MOUNTS.fullmatch(path.name))
    return app.command(arguments(app.ROOT, 'config', '--quiet', override=path))


def samba_config_check(app, name):
    """Faire valider par Samba une configuration candidate, écrite par la console dans son dossier Samba."""
    _require(app, isinstance(name, str) and CANDIDATE.fullmatch(name))
    return app.compose('exec', '-T', 'fichiers', 'testparm', '-s', '/etc/nas-autonome/' + name)


def samba_reload(app):
    return app.compose('exec', '-T', 'fichiers', 'smbcontrol', 'all', 'reload-config')


def samba_close(app, share):
    """Fermer les connexions ouvertes sur un partage : un rechargement seul ne révoque pas leurs droits."""
    _require(app, isinstance(share, str) and SHARE.fullmatch(share))
    return app.compose('exec', '-T', 'fichiers', 'smbcontrol', 'all', 'close-share', share)


def samba_ping(app):
    return app.compose('exec', '-T', 'fichiers', 'smbcontrol', 'smbd', 'ping', timeout=10)


def samba_account(app, name, uid):
    """Créer le compte système d'un utilisateur de partage, sans dossier personnel ni mot de passe."""
    _require(app, isinstance(name, str) and ACCOUNT.fullmatch(name) and type(uid) is int and 0 < uid < 2**31)
    return app.compose('exec', '-T', 'fichiers', 'adduser', '-D', '-H', '-u', str(uid), '-G', 'nas', name)


def samba_password(app, name, password):
    """Fixer le mot de passe SMB d'un compte ; il voyage par l'entrée standard, jamais dans la ligne de commande."""
    _require(app, isinstance(name, str) and ACCOUNT.fullmatch(name) and isinstance(password, str) and 12 <= len(password) <= 128
             and not any(char in password for char in '\r\n\x00'))
    return app.compose('exec', '-T', 'fichiers', 'smbpasswd', '-s', '-a', name, data=password + '\n' + password + '\n')


def samba_enable(app, name, enabled):
    _require(app, isinstance(name, str) and ACCOUNT.fullmatch(name) and type(enabled) is bool)
    return app.compose('exec', '-T', 'fichiers', 'smbpasswd', '-e' if enabled else '-d', name)


OPERATIONS = {handler.__name__: handler for handler in (
    status, video_address, control, recreate_files, engine, build, start_component, video_validate, samba_group, samba_access, samba_identity,
    samba_mounts_check, samba_config_check, samba_reload, samba_close, samba_ping, samba_account, samba_password, samba_enable)}


def request(app, operation, **parameters):
    """Exécuter une opération de la liste, et aucune autre."""
    handler = OPERATIONS.get(operation) if isinstance(operation, str) else None
    if handler is None:
        raise app.Problem('Opération de service inconnue.')
    try:
        return handler(app, **parameters)
    except TypeError as error:
        # Paramètre inconnu ou manquant : refus, sans rien exécuter. Une erreur de type survenue plus loin n'est pas masquée.
        if 'argument' in str(error) and handler.__name__ in str(error):
            raise app.Problem('Opération de service non autorisée.') from None
        raise
