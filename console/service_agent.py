#!/usr/bin/env python3
"""Opérations de services : la seule porte de la console vers Docker, et l'agent qui peut la tenir à sa place.

Piloter Docker vaut les droits de root sur l'hôte. Ce module ferme la liste de ce que le processus web lui demande :
chaque opération a un nom, des paramètres validés et une ligne de commande fixe. Aucune ne reçoit de commande,
d'option ni de chemin libre. Le reste de la console passe par `request`.

Deux façons d'exécuter la même liste :
- dans le processus web, tant qu'aucun agent n'est installé : le compte de la console garde alors son accès à Docker ;
- dans l'agent de services, un daemon root lancé par ce même fichier. Il n'écoute que le compte de la console, sur un
  socket local, et ne fait confiance ni à la description des services ni aux montages que ce compte peut écrire :
  il utilise sa propre copie de la description, et confronte chaque montage aux emplacements approuvés par root.

Voir docs/SERVICE-AGENT.md.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
from pathlib import Path

SOCKET = '/run/nacre-services/control.sock'
POLICY = '/etc/nacre-services/policy.json'
DESCRIPTION = '/usr/local/lib/nacre-services/compose.yaml'
MAX_MESSAGE = 1024 * 1024
# Durée la plus longue qu'une opération peut demander ; le client attend un peu plus.
CEILING = {'build': 1800, 'control': 600, 'start_component': 180, 'video_validate': 120, 'recreate_files': 90, 'status': 60}

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
    _require(app, type(lookup) is bool)
    if hasattr(app, 'probe'):
        probe, which = app.probe, app.which
    else:
        import onboarding
        probe, which = onboarding.probe, onboarding.shutil.which
    info, version = ['docker', 'info', '--format', '{{.ServerVersion}}'], ['docker', 'compose', 'version']
    if lookup:
        present = bool(which('docker'))
        return {'docker': present, 'engine': bool(present and probe(info)), 'compose': bool(present and probe(version))}
    ready = bool(probe(info))
    return {'docker': ready, 'engine': ready, 'compose': bool(ready and probe(version))}


def protection(app):
    """Les dossiers de l'hôte où les conteneurs écrivent sont-ils à l'abri des programmes privilégiés et des périphériques ?"""
    if not hasattr(app, 'protection'):
        return {'agent': False, 'sources': [], 'protected': False, 'required': False}
    return app.protection()


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
    path = Path(override)
    _require(app, path.parent == Path(app.ROOT) / 'state/samba' and MOUNTS.fullmatch(path.name))
    return app.command(app.arguments('config', '--quiet', override=path))


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
    status, video_address, control, recreate_files, engine, protection, build, start_component, video_validate, samba_group, samba_access, samba_identity,
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


# --- Agent de services : la même liste, tenue par un daemon root que seul le compte de la console peut joindre. ---

class AgentError(ValueError):
    """Refus de l'agent. `status` suit le sens des réponses de la console : 400 refusé, 503 service indisponible."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def read_policy(path=POLICY):
    """Politique écrite par root : qui peut parler à l'agent, quelle installation il sert, où un partage peut pointer."""
    from native_storage import NativeError, trusted_directory
    path = Path(path)
    try:
        with trusted_directory(path.parent) as directory:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd) as file:
                meta = os.fstat(file.fileno())
                if meta.st_uid != 0 or meta.st_mode & 0o022 or meta.st_size > 65536:
                    raise AgentError('Politique des services non protégée par root.')
                policy = json.loads(file.read())
    except (NativeError, OSError, ValueError) as error:
        raise AgentError(str(error) if isinstance(error, (NativeError, AgentError)) else 'Politique des services illisible.') from None
    roots = policy.get('mount_roots', [])
    if type(policy.get('require_protected_mounts', False)) is not bool or not isinstance(policy.get('frigate_image', ''), str) \
            or (policy.get('frigate_image') and not Host.IMAGE.fullmatch(policy['frigate_image'])):
        raise AgentError('Politique des services invalide.')
    if (policy.get('version') != 1 or type(policy.get('allowed_uid')) is not int or policy['allowed_uid'] <= 0
            or not isinstance(policy.get('root'), str) or not Path(policy['root']).is_absolute() or '..' in Path(policy['root']).parts
            or not isinstance(roots, list) or not all(isinstance(root, str) and Path(root).is_absolute() and root != '/' and '..' not in Path(root).parts for root in roots)):
        raise AgentError('Politique des services invalide.')
    return policy


class Host:
    """Ce que le catalogue attend d'une console, vu de l'agent : deux exécuteurs, sur des entrées qu'il a lui-même vérifiées."""
    Problem = AgentError
    IMAGE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}\Z')

    def __init__(self, policy, description=DESCRIPTION, runtime=None, runner=subprocess.run):
        # Une politique donnée par son chemin est relue à chaque demande : root approuve ou retire un emplacement sans redémarrer l'agent.
        self.source = policy
        self.ROOT, self.run = Path(self.policy['root']), runner
        self.description, self.runtime = Path(description), Path(runtime or Path(SOCKET).parent)
        text = self.description.read_text()
        meta = os.stat(self.description)
        name = re.search(r'^name:\s*([a-z0-9][a-z0-9_-]{0,62})\s*$', text, re.M)
        if meta.st_uid != 0 or meta.st_mode & 0o022 or not name:
            raise AgentError('Description des services absente ou non protégée par root.')
        self.project = name[1]

    @property
    def policy(self):
        return self.source if isinstance(self.source, dict) else read_policy(self.source)

    @policy.setter
    def policy(self, value):
        self.source = value

    def which(self, name):
        return shutil.which(name, path='/usr/sbin:/usr/bin:/sbin:/bin')

    def probe(self, args):
        try:
            return self.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, env=self.environment()).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def environment(self):
        return {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root'}

    def readable(self, path, limit=65536):
        """Lire un fichier que le compte de la console écrit : jamais par un lien, jamais au-delà d'une taille raisonnable."""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd) as file:
            text = file.read(limit + 1)
        if len(text) > limit:
            raise AgentError('Fichier de la console trop volumineux.')
        return text

    def private(self, name, value):
        """Écrire la version vérifiée d'un fichier dans le dossier de l'agent, que la console ne peut pas modifier."""
        text = json.dumps(value, sort_keys=True)
        path = self.runtime / (name + '-' + hashlib.sha256(text.encode()).hexdigest()[:16] + '.json')
        if not path.exists():
            temporary = path.with_name('.' + path.name + '.' + os.urandom(6).hex())
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as file:
                file.write(text)
            os.replace(temporary, path)
        return path

    def mounts(self, path):
        """Montages de partages demandés par la console, réduits à ce que root a approuvé. Refus au moindre écart."""
        text = self.readable(path)
        if text is None:
            return None, []
        refusal = AgentError('Montage de partage non approuvé par la politique système.')
        try:
            document = json.loads(text)
            volumes = document['services']['fichiers']['volumes']
            if set(document) != {'services'} or set(document['services']) != {'fichiers'} or set(document['services']['fichiers']) != {'volumes'} or not isinstance(volumes, list):
                raise refusal
            checked = []
            for item in volumes:
                if set(item) != {'type', 'source', 'target', 'read_only', 'bind'} or item['type'] != 'bind' or item['bind'] != {'create_host_path': False} \
                        or type(item['read_only']) is not bool or not isinstance(item['source'], str) or not isinstance(item['target'], str):
                    raise refusal
                area = item['target'][len('/shares/'):] if item['target'].startswith('/shares/') else ''
                source = item['source'].replace('$$', '$')
                real = os.path.realpath(source)
                if not area.startswith('native_') or not AREA.fullmatch(area) or not Path(source).is_absolute() or '$' in source or not os.path.isdir(real) \
                        or not any(real == os.path.realpath(root) or real.startswith(os.path.realpath(root).rstrip('/') + '/') for root in self.policy.get('mount_roots', [])):
                    raise refusal
                checked.append({'type': 'bind', 'source': real, 'target': '/shares/' + area, 'read_only': item['read_only'], 'bind': {'create_host_path': False}})
        except (ValueError, KeyError, TypeError, AttributeError):
            raise refusal from None
        return self.private('mounts', {'services': {'fichiers': {'volumes': checked}}}), checked

    def recovered(self):
        """Installation reprise : projet et volume Samba repris, relus et réduits à leur forme attendue."""
        result = []
        project = self.readable(self.ROOT / 'state/console/recovery-project.json')
        if project is not None:
            name = json.loads(project).get('project')
            if not isinstance(name, str) or not re.fullmatch(r'nacre-recovered-[a-f0-9]{24}', name):
                raise AgentError('Projet de reprise invalide.')
            self.project = name
        text = self.readable(self.ROOT / 'state/samba/recovery.compose.json')
        if text is not None:
            try:
                document = json.loads(text)
                service, volume = document['services']['fichiers'], document['volumes']['samba-state']
                if set(document) != {'services', 'volumes'} or set(document['services']) != {'fichiers'} or set(document['volumes']) != {'samba-state'} \
                        or set(service) != {'image', 'hostname'} or set(volume) != {'external', 'name'} or volume['external'] is not True \
                        or not re.fullmatch(r'sha256:[a-f0-9]{64}', service['image']) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,62}', service['hostname']) \
                        or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', volume['name']):
                    raise AgentError('État Samba repris invalide.')
            except (ValueError, KeyError, TypeError, AttributeError):
                raise AgentError('État Samba repris invalide.') from None
            result += ['-f', str(self.private('recovery', {'services': {'fichiers': {'image': service['image'], 'hostname': service['hostname']}},
                                                           'volumes': {'samba-state': {'external': True, 'name': volume['name']}}}))]
        return result

    def settings(self):
        """Seules variables que la description attend, relues du fichier de l'installation et validées une à une."""
        values = {}
        for line in (self.readable(self.ROOT / '.env') or '').splitlines():
            key, _, value = line.partition('=')
            value = value.strip().strip('"\'')
            if key.strip() == 'NACRE_FRIGATE_IMAGE' and self.IMAGE.fullmatch(value):
                # Une image fixée par root dans la politique l'emporte sur celle que la console a écrite.
                values['NACRE_FRIGATE_IMAGE'] = self.policy.get('frigate_image') or value
            elif key.strip() in ('NACRE_UID', 'NACRE_GID') and value.isdecimal() and 0 < int(value) < 2**31:
                values[key.strip()] = value
        path = self.runtime / ('env-' + hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16])
        if not path.exists():
            temporary = path.with_name('.' + path.name + '.' + os.urandom(6).hex())
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as file:
                file.write(''.join(f'{key}={value}\n' for key, value in sorted(values.items())))
            os.replace(temporary, path)
        return path

    WRITABLE = re.compile(r'^\s*-\s*\./([^:\s]+):/[^:\s]+\s*$', re.M)

    def exposure(self, approved=()):
        """Dossiers de l'hôte où un conteneur peut écrire, et les protections du montage qui les porte.

        Un conteneur tourne en root : sans « nosuid » et « nodev » sur ces dossiers, ce qu'il y dépose peut donner les
        droits de root à qui l'exécute ou l'ouvre depuis l'hôte.
        """
        paths = [str(self.ROOT / name) for name in self.WRITABLE.findall(self.description.read_text())]
        paths += [item['source'] for item in approved if not item['read_only']]
        found = []
        for path in dict.fromkeys(paths):
            try:
                flags = os.statvfs(path).f_flag
                found.append({'path': path, 'nosuid': bool(flags & os.ST_NOSUID), 'nodev': bool(flags & os.ST_NODEV)})
            except OSError:
                found.append({'path': path, 'nosuid': False, 'nodev': False, 'missing': True})
        return found

    def protection(self):
        try:
            _, approved = self.mounts(self.ROOT / 'state/samba/volumes.compose.json')
        except AgentError:
            approved = []
        sources = self.exposure(approved)
        return {'agent': True, 'sources': sources, 'protected': bool(sources) and all(item['nosuid'] and item['nodev'] for item in sources),
                'required': self.policy.get('require_protected_mounts') is True}

    def arguments(self, *args, override=None):
        """Ligne Compose de l'agent : sa description, le dossier de l'installation, et rien que la console puisse détourner."""
        self.project = re.search(r'^name:\s*(\S+)\s*$', self.description.read_text(), re.M)[1]
        extra = self.recovered()
        if any(arg in ('up', 'start', 'restart') for arg in args) and (self.ROOT / 'state/console/system-recovery-status.json').exists() \
                and not (self.ROOT / 'state/samba/recovery.compose.json').exists():
            raise AgentError('Préparer l’état Samba récupéré avant de démarrer les services.')
        mounts, approved = self.mounts(override if override is not None else self.ROOT / 'state/samba/volumes.compose.json')
        if any(arg in ('up', 'start', 'restart') for arg in args) and self.policy.get('require_protected_mounts') is True:
            exposed = [item['path'] for item in self.exposure(approved) if not (item['nosuid'] and item['nodev'])]
            if exposed:
                raise AgentError('Dossier de données non protégé contre les programmes privilégiés et les périphériques : ' + ', '.join(exposed) + '. Démarrage refusé par la politique système.')
        return ['docker', 'compose', '--project-directory', str(self.ROOT), '--project-name', self.project, '--env-file', str(self.settings()),
                '-f', str(self.description), *extra, *(['-f', str(mounts)] if mounts else []), *args]

    def command(self, args, data=None, timeout=20):
        result = self.run(args, cwd=self.ROOT, input=data, text=True, capture_output=True, timeout=timeout, env=self.environment())
        if result.returncode:
            print(json.dumps({'command': ' '.join(args[:2]), 'code': result.returncode, 'detail': (result.stderr or '')[-2000:]}), flush=True)
            raise AgentError('Le service n’a pas accepté cette opération. Consulter son état.', 503)
        return result.stdout

    def compose(self, *args, data=None, timeout=25):
        return self.command(self.arguments(*args), data, timeout)


def answer(host, uid, message):
    """Une demande reçue sur le socket : identité, forme, puis la liste fermée. Jamais d'exception vers l'appelant."""
    try:
        policy = host.policy
        if uid != policy['allowed_uid'] or Path(policy['root']) != host.ROOT:
            raise AgentError('Identité du client système non autorisée.' if uid != policy['allowed_uid'] else 'Installation servie modifiée : redémarrer l’agent de services.', 403)
        operation, parameters = message.get('operation'), message.get('parameters', {})
        if not isinstance(parameters, dict) or not all(isinstance(key, str) for key in parameters):
            raise AgentError('Opération de service non autorisée.')
        return {'result': request(host, operation, **parameters)}
    except AgentError as error:
        return {'error': error.message, 'status': error.status}
    except subprocess.TimeoutExpired:
        return {'error': 'Délai dépassé.', 'status': 503, 'kind': 'timeout'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'error': 'Opération de service refusée ; consulter le journal du système.', 'status': 503}


class AgentHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        uid = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]
        try:
            raw = self.rfile.readline(MAX_MESSAGE + 1)
            if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
                raise ValueError
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError
        except (ValueError, OSError):
            response = {'error': 'Requête système invalide.', 'status': 400}
        else:
            self.connection.settimeout(None)
            response = answer(self.server.host, uid, message)
        try:
            self.wfile.write((json.dumps(response) + '\n').encode())
        except OSError:
            pass


class AgentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    # L'état des services reste lisible pendant une construction d'image, qui peut durer.
    daemon_threads = True


class AgentClient:
    """Côté console : une demande, une réponse. Les erreurs gardent le sens qu'elles avaient sans agent."""
    def __init__(self, path=SOCKET):
        self.path = path

    def request(self, app, operation, parameters):
        try:
            body = (json.dumps({'operation': operation, 'parameters': parameters}, default=str) + '\n').encode()
        except (TypeError, ValueError):
            raise app.Problem('Opération de service non autorisée.') from None
        if len(body) > MAX_MESSAGE:
            raise app.Problem('Demande trop volumineuse pour l’agent de services.')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(CEILING.get(operation, 25) + 30)
            client.connect(self.path)
            client.sendall(body)
            with client.makefile('rb') as file:
                raw = file.readline(MAX_MESSAGE * 4 + 1)
        try:
            response = json.loads(raw)
        except ValueError:
            raise OSError('Réponse de l’agent de services illisible.') from None
        if 'error' in response:
            if response.get('kind') == 'timeout':
                raise subprocess.TimeoutExpired(operation, CEILING.get(operation, 25))
            raise app.Problem(response['error'], response.get('status', 400))
        return response.get('result')


def agent_present(path=SOCKET):
    return os.path.exists(path)


def serve():
    if os.geteuid() != 0:
        raise SystemExit('L’agent de services doit être exécuté par root avec sa politique dédiée.')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from native_storage import private_directory
    os.umask(0o077)
    policy = read_policy()
    directory = Path(SOCKET).parent
    directory.mkdir(mode=0o755, exist_ok=True)
    private_directory(directory)
    host = Host(POLICY)
    if Path(SOCKET).exists():
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(SOCKET)
            except ConnectionRefusedError:
                Path(SOCKET).unlink()
            else:
                raise SystemExit('Un agent de services utilise déjà le socket.')
    with AgentServer(SOCKET, AgentHandler) as server:
        server.host = host
        os.chown(SOCKET, policy['allowed_uid'], -1)
        os.chmod(SOCKET, 0o600)
        server.serve_forever()


if __name__ == '__main__':
    serve()

