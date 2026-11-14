"""Accès par le réseau : un second point d'écoute, en HTTPS, pour joindre la console ailleurs que sur la machine.

Fermé par défaut. Une fois ouvert par un administrateur, la console répond sur toutes les interfaces, sur un port
choisi, sous les seuls noms d'hôte déclarés. Le point d'écoute local (127.0.0.1) ne change pas : il garde le lien
de connexion locale, refusé sur le réseau. Sur le réseau, un administrateur ne se connecte qu'avec la double
authentification. Le certificat est autosigné, produit par OpenSSL, ou fourni par l'administrateur.
"""
import hashlib
import ipaddress
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import spaces

KEY = 'network'
NAME = re.compile(r'[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?\Z')
HOSTS_MAX = 8
PER_ADDRESS = 8
PER_MINUTE = 120
LOCK = threading.RLock()
LISTENER = {'server': None, 'error': ''}


def read(app, db=None):
    if db is None:
        with app.database() as connection:
            return read(app, connection)
    doc = spaces.get(db, KEY, {})
    doc = doc if isinstance(doc, dict) else {}
    return {'enabled': doc.get('enabled') is True, 'port': doc.get('port') if type(doc.get('port')) is int else 8443,
            'hosts': [h for h in doc.get('hosts', []) if isinstance(h, str)][:HOSTS_MAX],
            'require_totp': 'everyone' if doc.get('require_totp') == 'everyone' else 'admins', 'certificate': doc.get('certificate', '')}


def folder(app):
    path = Path(app.STATE) / 'tls'
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def is_address(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def host(app, value):
    """Nom ou adresse sous lequel la console est jointe : jamais d'espace, de port ni de chemin."""
    text = value.strip().lower() if isinstance(value, str) else ''
    if not (is_address(text) or (NAME.fullmatch(text) and '..' not in text)):
        raise app.Problem('Nom d’hôte invalide : un nom comme nas.local ou une adresse comme 192.168.1.20, sans port ni « https:// ».')
    return text


def addresses():
    """Adresses IPv4 de la machine sur ses réseaux, pour aider à remplir les noms. Aucun paquet n'est envoyé."""
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith('127.'))


def generate(app, hosts):
    """Certificat autosigné pour les noms déclarés, valable 825 jours. La clé ne quitte pas le dossier privé de la console."""
    binary = shutil.which('openssl')
    if not binary:
        raise app.Problem('OpenSSL est introuvable sur cette machine : installez-le, ou fournissez votre propre certificat.', 503)
    target, stamp = folder(app), secrets.token_hex(6)
    key, cert = target / f'key-{stamp}.pem', target / f'cert-{stamp}.pem'
    names = ','.join(('IP:' if is_address(h) else 'DNS:') + h for h in hosts)
    try:
        subprocess.run([binary, 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-days', '825',
                        '-subj', '/CN=' + hosts[0][:60], '-addext', 'subjectAltName=' + names, '-keyout', str(key), '-out', str(cert)],
                       check=True, capture_output=True, timeout=60)
        place(app, cert.read_text(), key.read_text())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        raise app.Problem('OpenSSL n’a pas produit le certificat. Rien n’a été changé.', 503) from None
    finally:
        key.unlink(missing_ok=True)
        cert.unlink(missing_ok=True)


def place(app, certificate, key):
    """Installe un certificat et sa clé après avoir vérifié qu'ils vont ensemble. L'ancien couple reste en place en cas de refus."""
    target, stamp = folder(app), secrets.token_hex(6)
    paths = [target / f'new-{stamp}-cert.pem', target / f'new-{stamp}-key.pem']
    try:
        for path, content in zip(paths, (certificate, key)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(content)
        try:
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(paths[0], paths[1])
        except (ssl.SSLError, OSError, ValueError):
            raise app.Problem('Certificat ou clé illisible, ou qui ne vont pas ensemble. Rien n’a été changé.') from None
        os.replace(paths[1], target / 'key.pem')
        os.replace(paths[0], target / 'cert.pem')
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def describe(app):
    """Empreinte et échéance du certificat en place, ou None."""
    path = folder(app) / 'cert.pem'
    try:
        der = ssl.PEM_cert_to_DER_cert(path.read_text())
    except (OSError, ValueError):
        return None
    digest = hashlib.sha256(der).hexdigest().upper()
    found = {'fingerprint': ':'.join(digest[i:i + 2] for i in range(0, 64, 2)), 'expires': None, 'names': []}
    try:
        decoded = ssl._ssl._test_decode_cert(str(path))
        found['expires'] = ssl.cert_time_to_seconds(decoded['notAfter'])
        found['names'] = [value for _, value in decoded.get('subjectAltName', ())]
    except Exception:
        pass
    return found


def allowed_hosts(server):
    """Valeurs acceptées de l'en-tête Host : chaque nom déclaré, avec ou sans le port (un relais peut l'omettre)."""
    return {h for name in server.hosts for h in (name, f'{name}:{server.server_port}', f'[{name}]:{server.server_port}')}


def origins(server):
    return {o for name in server.hosts for o in (f'https://{name}', f'https://{name}:{server.server_port}')}


class NetworkServer(ThreadingHTTPServer):
    """Point d'écoute réseau : TLS négocié dans le fil de la connexion, jamais dans la boucle d'acceptation."""
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64
    network = True

    def __init__(self, address, handler, context, hosts):
        super().__init__(address, handler)
        self.context, self.hosts = context, list(hosts)
        self.attempts, self.limit_lock = {}, threading.Lock()

    def get_request(self):
        sock, address = self.socket.accept()
        sock.settimeout(20)
        return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), address

    def handle_error(self, request, client_address):
        # Poignée de main abandonnée, client qui coupe : rien à journaliser, et surtout rien qui arrête l'écoute.
        pass

    def login_limit(self, address=None):
        """Huit tentatives par minute et par adresse, et un plafond d'ensemble."""
        with self.limit_lock:
            now = time.time()
            self.attempts = {key: [t for t in times if t > now - 60] for key, times in self.attempts.items()}
            self.attempts = {key: times for key, times in self.attempts.items() if times}
            mine = self.attempts.setdefault(address or '', [])
            if len(mine) >= PER_ADDRESS or sum(len(times) for times in self.attempts.values()) >= PER_MINUTE:
                return False
            mine.append(now)
            return True


def context(app):
    made = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    made.minimum_version = ssl.TLSVersion.TLSv1_2
    made.load_cert_chain(folder(app) / 'cert.pem', folder(app) / 'key.pem')
    return made


def stop():
    with LOCK:
        server, LISTENER['server'] = LISTENER['server'], None
    if server:
        server.shutdown()
        server.server_close()


def apply(app, address='0.0.0.0'):
    """Met le point d'écoute en accord avec les réglages : arrêté, ou démarré sur le port et les noms déclarés."""
    with LOCK:
        stop()
        LISTENER['error'] = ''
        settings = read(app)
        if not settings['enabled']:
            return
        try:
            server = NetworkServer((address, settings['port']), app.Handler, context(app), settings['hosts'])
        except (OSError, ssl.SSLError, ValueError) as error:
            LISTENER['error'] = 'Port déjà utilisé ou certificat illisible : l’accès réseau n’a pas démarré.' if isinstance(error, (OSError, ssl.SSLError)) else str(error)
            return
        LISTENER['server'] = server
        threading.Thread(target=server.serve_forever, daemon=True, name='nacre-network').start()


def later(app):
    """Applique un changement après la réponse en cours : la requête qui le demande peut arriver par ce même point d'écoute."""
    threading.Timer(.4, lambda: apply(app)).start()


def start(app):
    try:
        apply(app)
    except Exception:
        LISTENER['error'] = 'L’accès réseau n’a pas démarré.'


def status(app, session=None):
    settings, server = read(app), LISTENER['server']
    import totp
    with app.database() as db:
        protected = totp.enabled(db, session['name']) if session else False
    return {**{key: settings[key] for key in ('enabled', 'port', 'hosts', 'require_totp')}, 'running': server is not None, 'error': LISTENER['error'],
            'certificate': describe(app), 'provided': settings['certificate'] == 'provided', 'openssl': bool(shutil.which('openssl')), 'addresses': addresses(),
            'urls': [f'https://{name}:{settings["port"]}/' for name in settings['hosts']] if settings['enabled'] else [],
            'my_totp': protected, 'hosts_max': HOSTS_MAX}


def configure(app, body, session):
    """Ouvre, règle ou ferme l'accès réseau. Ouvrir demande une confirmation explicite."""
    enabled, port, policy = body.get('enabled'), body.get('port'), body.get('require_totp', 'admins')
    if type(enabled) is not bool or type(port) is not int or not 1024 <= port <= 65535 or policy not in ('admins', 'everyone'):
        raise app.Problem('Réglages invalides : port entre 1024 et 65535.')
    values = body.get('hosts')
    if not isinstance(values, list) or len(values) > HOSTS_MAX:
        raise app.Problem(f'Noms invalides : {HOSTS_MAX} au plus.')
    hosts = list(dict.fromkeys(host(app, value) for value in values))
    if enabled and not hosts:
        raise app.Problem('Indiquez au moins un nom ou une adresse sous lequel la console sera jointe.')
    if enabled and body.get('confirm') is not True:
        raise app.Problem('Ouvrir la console au réseau demande une confirmation.')
    with LOCK:
        before = read(app)
        current = LISTENER['server']
        if enabled and not (current and current.server_port == port):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind(('0.0.0.0', port))
            except OSError:
                raise app.Problem(f'Le port {port} est déjà utilisé sur cette machine. Choisissez-en un autre.', 409) from None
        kind = before['certificate']
        found = describe(app)
        # Un certificat autosigné suit les noms déclarés ; un certificat fourni n'est jamais remplacé d'office.
        if enabled and kind != 'provided' and (not found or set(found['names']) != set(hosts)):
            generate(app, hosts)
            kind = 'self'
        with app.database() as db:
            spaces.put(db, KEY, {'enabled': enabled, 'port': port, 'hosts': hosts, 'require_totp': policy, 'certificate': kind})
            db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'],
                       'Accès réseau ouvert' if enabled and not before['enabled'] else 'Accès réseau fermé' if before['enabled'] and not enabled else 'Accès réseau réglé',
                       f'port {port} · {", ".join(hosts) or "aucun nom"}' if enabled else ''))
    later(app)
    return {'ok': True}


def certificate(app, body, session):
    """Refait le certificat autosigné, ou installe celui que fournit l'administrateur."""
    with LOCK:
        settings = read(app)
        if body.get('action') == 'regenerate':
            if not settings['hosts']:
                raise app.Problem('Déclarez d’abord les noms sous lesquels la console sera jointe.')
            generate(app, settings['hosts'])
            kind, what = 'self', 'Certificat autosigné refait'
        elif body.get('action') == 'provide':
            if not isinstance(body.get('certificate'), str) or not isinstance(body.get('key'), str) or len(body['certificate']) > 200000 or len(body['key']) > 50000:
                raise app.Problem('Certificat et clé attendus au format PEM.')
            place(app, body['certificate'], body['key'])
            kind, what = 'provided', 'Certificat fourni installé'
        else:
            raise app.Problem('Action inconnue.')
        with app.database() as db:
            spaces.put(db, KEY, {**{key: settings[key] for key in ('enabled', 'port', 'hosts', 'require_totp')}, 'certificate': kind})
            db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], what, (describe(app) or {}).get('fingerprint', '')[:23] + '…'))
    later(app)
    return {'ok': True, 'certificate': describe(app)}


def login_refusal(app, db, handler, name, role):
    """Sur le réseau, un administrateur (ou tout le monde, selon le réglage) ne se connecte qu'avec la double authentification."""
    if not getattr(handler.server, 'network', False):
        return None
    import totp
    if (role == 'admin' or read(app, db)['require_totp'] == 'everyone') and not totp.enabled(db, name):
        return 'Par le réseau, ce compte doit avoir la double authentification. Activez-la dans Mon compte depuis la machine elle-même, puis reconnectez-vous.'
    return None
