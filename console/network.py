"""Accès par le réseau : un second point d'écoute, en HTTPS, pour joindre la console ailleurs que sur la machine.

Fermé par défaut. Une fois ouvert par un administrateur, la console répond sur toutes les interfaces, sur un port
choisi, sous les seuls noms d'hôte déclarés. Le point d'écoute local (127.0.0.1) ne change pas : il garde le lien
de connexion locale, refusé sur le réseau. Sur le réseau, un administrateur ne se connecte qu'avec la double
authentification.

Le certificat est fourni par l'administrateur, ou produit par OpenSSL sous une autorité locale : Nacre crée une
autorité qui ne peut certifier que des noms locaux et des adresses privées, puis un certificat de serveur signé
par elle. Un appareil qui installe l'autorité une fois reconnaît ensuite le NAS sans avertissement, et le
certificat de serveur se renouvelle sans rien lui redemander.
"""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
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
LEAF_DAYS = 397            # durée qu'acceptent tous les appareils pour un certificat de serveur
AUTHORITY_DAYS = 3650
RENEW_BEFORE = 30 * 86400
WARN_BEFORE = 21 * 86400
WATCH = 12 * 3600
ALERT = 'network:certificate'
# Ce qu'une autorité locale peut certifier : des noms qui n'existent pas sur Internet et des adresses privées. Les appareils qui
# appliquent les contraintes d'une autorité (Apple, Windows, Firefox, Chrome sur ordinateur) s'y tiennent même si sa clé fuit.
LOCAL_NAMES = ('local', 'lan', 'home', 'internal', 'home.arpa', 'localdomain')
PRIVATE = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', '169.254.0.0/16', 'fc00::/7', 'fe80::/10')
AUTHORITY_WARN = 90 * 86400
PEM = re.compile(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', re.S)


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
    if not sound(text):
        raise app.Problem('Nom d’hôte invalide : un nom comme nas.local ou une adresse comme 192.168.1.20, sans port ni « https:// ».')
    # Une adresse est rangée sous sa forme courte : c'est aussi celle que rend le certificat, et les deux se comparent.
    return ipaddress.ip_address(text).compressed if is_address(text) else text


def sound(text):
    """Nom ou adresse sans rien d'autre : ni zone d'interface, ni caractère qui changerait le sens d'un fichier de réglage."""
    if not isinstance(text, str) or '%' in text or any(c.isspace() or ord(c) < 33 for c in text):
        return False
    return is_address(text) or bool(NAME.fullmatch(text) and '..' not in text)


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


def openssl(app):
    binary = shutil.which('openssl')
    if not binary:
        raise app.Problem('OpenSSL est introuvable sur cette machine : installez-le, ou fournissez votre propre certificat.', 503)
    return binary


def scope(app):
    """Ce que l'autorité locale en place peut certifier, ou None s'il n'y en a pas."""
    target = folder(app)
    try:
        doc = json.loads((target / 'authority.json').read_text())
        if not (target / 'ca.pem').is_file() or not (target / 'ca-key.pem').is_file():
            return None
        return {'dns': [n for n in doc['dns'] if isinstance(n, str)], 'ip': [n for n in doc['ip'] if isinstance(n, str)], 'created': doc.get('created', 0)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def within(name, allowed):
    """Nom dans le domaine d'une autorité : lui-même, ou un nom qui s'y termine."""
    return any(name == suffix or name.endswith('.' + suffix) for suffix in allowed)


def covers(limits, name):
    if not is_address(name):
        return within(name, limits['dns'])
    address = ipaddress.ip_address(name)
    return any(address.version == net.version and address in net for net in (ipaddress.ip_network(value) for value in limits['ip']))


def limits_for(hosts):
    """Domaine d'une nouvelle autorité : le local d'office, plus les noms et adresses déclarés qui n'en font pas partie."""
    dns, ip = list(LOCAL_NAMES), list(PRIVATE)
    for name in hosts:
        if covers({'dns': dns, 'ip': ip}, name):
            continue
        if is_address(name):
            ip.append(str(ipaddress.ip_network(name)))
        else:
            dns.append(name)
    return {'dns': dns, 'ip': ip}


def label(app):
    """Nom du NAS réduit à ce qu'un certificat et un fichier de réglage OpenSSL portent sans surprise."""
    try:
        from onboarding import read as setup
        name = str(setup(app).get('name') or '')
    except Exception:
        name = ''
    # Trente-trois caractères au plus : avec le reste du nom de l'autorité, on atteint la limite de 64 d'un certificat.
    return re.sub(r'[^A-Za-z0-9 .-]', '', name).strip()[:33].strip() or 'NAS'


def run(binary, *arguments):
    subprocess.run([binary, *arguments], check=True, capture_output=True, timeout=60)


def checked(app, hosts):
    """Dernière vérification avant d'écrire un fichier de réglage : les noms relus dans la base y passent comme ceux d'une requête."""
    if not hosts or not all(sound(name) for name in hosts):
        raise app.Problem('Un nom déclaré n’est pas valide : corrigez les noms de ce NAS dans les réglages de l’accès réseau.')


def authority(app, hosts, target):
    """Crée une autorité locale dans `target`. Sa clé n'est jamais servie par la console : elle reste dans son dossier privé.

    L'autorité ne peut signer que pour son domaine, et pour des serveurs : ni courrier, ni adresse de page.
    """
    binary = openssl(app)
    limits = limits_for(hosts)
    bare = [name for name in limits['dns'] if '.' not in name and name not in LOCAL_NAMES and name != 'localhost']
    if bare:
        # Une contrainte sur « nas » couvrirait aussi tout ce qui finit par « .nas » ; sur « com », tout un pan d'Internet.
        raise app.Problem(f'« {bare[0]} » n’a pas de point : une autorité locale ne peut pas s’y limiter. Écrivez {bare[0]}.local, {bare[0]}.lan ou {bare[0]}.home, ou le nom complet.')
    config, key, cert = target / 'ca.cnf', target / 'ca-key.pem', target / 'ca.pem'
    constraints = [f'permitted;DNS.{i}={name}' for i, name in enumerate(limits['dns'])]
    for i, value in enumerate(limits['ip']):
        net = ipaddress.ip_network(value)
        constraints.append(f'permitted;IP.{i}={net.network_address}/{net.netmask}')
    # Aucun courrier ni aucune adresse de page : « invalid » est un domaine réservé, que rien ne peut porter.
    constraints += ['permitted;email.0=invalid', 'permitted;URI.0=invalid']
    config.write_text('[req]\ndistinguished_name=dn\nprompt=no\nx509_extensions=v3\n[dn]\nO=Nacre\nCN=Nacre ' + label(app) + ' ' + secrets.token_hex(3) + ' - autorite locale\n'
                      '[v3]\nbasicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n'
                      'nameConstraints=critical,@limits\n[limits]\n' + '\n'.join(constraints) + '\n')
    run(binary, 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-sha256', '-days', str(AUTHORITY_DAYS),
        '-config', str(config), '-keyout', str(key), '-out', str(cert))
    os.chmod(key, 0o600)
    (target / 'authority.json').write_text(json.dumps({**limits, 'created': time.time()}))
    config.unlink()


def sign(app, hosts, source, target):
    """Certificat de serveur pour les noms déclarés, signé par l'autorité de `source`, déposé dans `target` avec sa clé."""
    binary = openssl(app)
    config, request = target / 'leaf.cnf', target / 'leaf.csr'
    names = [('IP' if is_address(h) else 'DNS', h) for h in hosts]
    # Le sujet ne porte aucun nom : les appareils lisent les noms déclarés (SAN), et une adresse en sujet serait prise pour un nom.
    config.write_text('[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nO=Nacre\n'
                      '[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n'
                      'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\nsubjectAltName=@names\n[names]\n' +
                      '\n'.join(f'{kind}.{i}={value}' for i, (kind, value) in enumerate(names)) + '\n')
    run(binary, 'req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-sha256', '-config', str(config), '-keyout', str(target / 'key.pem'), '-out', str(request))
    run(binary, 'x509', '-req', '-in', str(request), '-CA', str(source / 'ca.pem'), '-CAkey', str(source / 'ca-key.pem'), '-set_serial', '0x' + secrets.token_hex(16),
        '-sha256', '-days', str(LEAF_DAYS), '-extfile', str(config), '-extensions', 'leaf', '-out', str(target / 'leaf.pem'))
    # Le serveur présente son certificat suivi de celui de l'autorité.
    (target / 'cert.pem').write_text((target / 'leaf.pem').read_text() + (source / 'ca.pem').read_text())
    os.chmod(target / 'key.pem', 0o600)
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(target / 'cert.pem', target / 'key.pem')


def issue(app, hosts):
    """Refait le certificat de serveur sous l'autorité en place. Les appareils qui la connaissent n'ont rien à refaire."""
    checked(app, hosts)
    openssl(app)
    home = folder(app)
    work = Path(tempfile.mkdtemp(dir=home, prefix='next-'))
    try:
        sign(app, hosts, home, work)
        os.replace(work / 'key.pem', home / 'key.pem')
        os.replace(work / 'cert.pem', home / 'cert.pem')
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError, ssl.SSLError):
        raise app.Problem('OpenSSL n’a pas produit le certificat. Rien n’a été changé.', 503) from None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def generate(app, hosts, renew=False):
    """Met le certificat en accord avec les noms déclarés. L'autorité n'est créée qu'une fois ; la refaire est une demande explicite.

    Rend True quand une autorité vient d'être créée : les appareils doivent alors l'installer (de nouveau). Une autorité neuve et
    son certificat sont produits à part, vérifiés, puis mis en place ensemble : un échec ne laisse rien de changé.
    """
    checked(app, hosts)
    limits = scope(app)
    made = renew or limits is None
    if not made:
        outside = [name for name in hosts if not covers(limits, name)]
        if outside:
            problem = app.Problem(f'L’autorité locale de ce NAS ne peut pas certifier « {outside[0]} » : elle est limitée aux noms locaux, aux adresses privées et aux noms '
                                  'déclarés à sa création. Refaites l’autorité pour l’y ajouter ; les appareils devront alors l’installer de nouveau.', 409)
            problem.reason = 'authority'
            raise problem
        issue(app, hosts)
        return False
    openssl(app)
    home = folder(app)
    work = Path(tempfile.mkdtemp(dir=home, prefix='next-'))
    try:
        authority(app, hosts, work)
        sign(app, hosts, work, work)
        # Tout est prêt et vérifié : la mise en place n'est plus qu'une suite de renommages, le réglage du domaine en dernier.
        for name in ('ca-key.pem', 'ca.pem', 'key.pem', 'cert.pem', 'authority.json'):
            os.replace(work / name, home / name)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError, ssl.SSLError):
        raise app.Problem('OpenSSL n’a pas produit l’autorité locale et son certificat. Rien n’a été changé.', 503) from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return True


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


def print_of(der, algorithm='sha256'):
    digest = hashlib.new(algorithm, der, usedforsecurity=False).hexdigest().upper()
    return ':'.join(digest[i:i + 2] for i in range(0, len(digest), 2))


def decoded(path):
    """Empreintes, échéance et noms du premier certificat d'un fichier PEM, ou None s'il est absent ou illisible."""
    try:
        block = PEM.search(Path(path).read_text())
        der = ssl.PEM_cert_to_DER_cert(block[0]) if block else None
    except (OSError, ValueError):
        return None
    if not der:
        return None
    found = {'fingerprint': print_of(der), 'sha1': print_of(der, 'sha1'), 'expires': None, 'names': []}
    try:
        details = ssl._ssl._test_decode_cert(str(path))   # lit le premier certificat du fichier, celui qu'on décrit
        found['expires'] = ssl.cert_time_to_seconds(details['notAfter'])
        # Les adresses sous leur forme courte, celle sous laquelle elles sont déclarées.
        found['names'] = [ipaddress.ip_address(value).compressed if is_address(value) else value for _, value in details.get('subjectAltName', ())]
    except Exception:
        pass
    return found


def describe(app):
    """Empreinte et échéance du certificat de serveur en place, ou None."""
    found = decoded(folder(app) / 'cert.pem')
    return {key: found[key] for key in ('fingerprint', 'expires', 'names')} if found else None


def trusted(app):
    """L'autorité locale telle qu'un appareil la verra : empreintes, échéance, domaine. None s'il n'y en a pas."""
    limits = scope(app)
    found = decoded(folder(app) / 'ca.pem') if limits else None
    if not found:
        return None
    extra = [name for name in limits['dns'] if name not in LOCAL_NAMES] + [value for value in limits['ip'] if value not in PRIVATE]
    # Windows ne montre que l'empreinte SHA-1 d'un certificat : elle est donnée à côté, pour que la comparaison reste possible.
    return {'fingerprint': found['fingerprint'], 'fingerprint_sha1': found['sha1'], 'expires': found['expires'], 'created': limits['created'], 'extra': extra}


def authority_file(app, handler):
    """Le certificat de l'autorité, à installer sur un appareil. Il ne contient aucun secret."""
    if not scope(app):
        raise app.Problem('Ce NAS n’a pas d’autorité locale.', 404)
    data = (folder(app) / 'ca.pem').read_bytes()
    return handler.reply(200, data, 'application/x-x509-ca-cert', {'Content-Disposition': 'attachment; filename="nacre-autorite-locale.crt"'})


def renewal(app, now=None):
    """Refait le certificat de serveur à l'approche de son échéance, sous la même autorité : aucun appareil n'a rien à refaire."""
    now = time.time() if now is None else now
    with LOCK:
        settings, found = read(app), describe(app)
        if not settings['enabled'] or settings['certificate'] != 'authority' or not found or not found['expires'] or found['expires'] - now > RENEW_BEFORE:
            return False
        limits = scope(app)
        if not limits or not shutil.which('openssl') or not all(covers(limits, name) for name in settings['hosts']):
            return False
        try:
            issue(app, settings['hosts'])
        except Exception:
            return False
        try:
            app.audit('Nacre', 'Certificat de serveur renouvelé', 'sous la même autorité locale')
        except Exception:
            pass   # le journal ne doit pas empêcher de servir le nouveau certificat
    apply(app)
    return True


def conditions(app, now=None):
    """Incidents du certificat en service : échéance proche sans renouvellement possible, échéance dépassée, autorité en fin de vie.

    Lève une exception quand un certificat en service ne se lit pas : l'alerte reste alors « non vérifiée » au lieu de se refermer.
    """
    now = time.time() if now is None else now
    settings = read(app)
    if not settings['enabled']:
        return []
    found = describe(app)
    if not found:
        if (folder(app) / 'cert.pem').exists():
            raise ValueError('certificat illisible')
        return []
    if not found['expires']:
        raise ValueError('échéance illisible')
    where, incidents = ' Réglages, onglet Accès réseau.', []
    plural = lambda days: f'{days} jour{"s" if days > 1 else ""}'
    left = found['expires'] - now
    if left <= 0:
        incidents.append((ALERT, 'Le certificat de l’accès réseau est échu', 'Les navigateurs et les appareils refusent désormais la connexion par le réseau. Refaites ou remplacez le certificat.' + where, 'network', 'critical', 'expired'))
    elif left <= WARN_BEFORE:
        incidents.append((ALERT, 'Le certificat de l’accès réseau arrive à échéance', f'Il reste {plural(max(1, int(left // 86400)))}. ' + (
            'Fournissez-en un nouveau avant cette date.' if settings['certificate'] == 'provided' else 'Il ne s’est pas renouvelé seul : refaites-le.') + where, 'network', 'warning', 'soon'))
    root = trusted(app) if settings['certificate'] == 'authority' else None
    if root and root['expires']:
        left = root['expires'] - now
        if left <= 0:
            incidents.append((ALERT + ':authority', 'L’autorité locale de ce NAS est échue', 'Refaites l’autorité : les appareils devront installer la nouvelle.' + where, 'network', 'critical', 'authority-expired'))
        elif left <= AUTHORITY_WARN:
            incidents.append((ALERT + ':authority', 'L’autorité locale de ce NAS arrive à échéance', f'Il reste {plural(max(1, int(left // 86400)))}. Refaites-la au moment qui vous convient : '
                              'les appareils devront installer la nouvelle.' + where, 'network', 'warning', 'authority-soon'))
    return incidents


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


def watch(app):
    """Deux fois par jour : renouvelle le certificat de serveur s'il approche de son échéance."""
    try:
        renewal(app)
    except Exception:
        pass
    timer = threading.Timer(WATCH, watch, (app,))
    timer.daemon = True
    timer.start()


def start(app):
    try:
        apply(app)
    except Exception:
        LISTENER['error'] = 'L’accès réseau n’a pas démarré.'
    watch(app)


def status(app, session=None):
    settings, server = read(app), LISTENER['server']
    import totp
    with app.database() as db:
        protected = totp.enabled(db, session['name']) if session else False
    return {**{key: settings[key] for key in ('enabled', 'port', 'hosts', 'require_totp')}, 'running': server is not None, 'error': LISTENER['error'],
            'certificate': describe(app), 'provided': settings['certificate'] == 'provided', 'openssl': bool(shutil.which('openssl')), 'addresses': addresses(),
            # « authority » : signé par l'autorité locale ; « self » : ancien certificat autosigné, gardé tel quel tant qu'on n'y touche pas.
            'kind': settings['certificate'] if describe(app) else '', 'authority': trusted(app),
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
        kind, made = before['certificate'], False
        found = describe(app)
        # Un certificat produit ici suit les noms déclarés ; un certificat fourni n'est jamais remplacé d'office.
        if enabled and kind != 'provided' and (not found or set(found['names']) != set(hosts)):
            # Remplacer un ancien certificat autosigné change ce que les appareils avaient accepté : jamais sans que ce soit demandé.
            if found and kind == 'self' and body.get('replace') is not True:
                problem = app.Problem('Changer les noms remplace le certificat actuel par une autorité locale et un nouveau certificat : les appareils qui avaient accepté '
                                      'l’ancien devront accepter le nouveau, ou installer l’autorité une fois pour toutes. Confirmez ce remplacement.', 409)
                problem.reason = 'replace'
                raise problem
            had = scope(app) is not None or (folder(app) / 'ca.pem').exists()
            made = generate(app, hosts, renew=body.get('authority') == 'renew') and had
            kind = 'authority'
        elif enabled and kind == 'authority' and found['expires'] and found['expires'] - time.time() <= RENEW_BEFORE:
            # Réouverture avec un certificat de serveur proche de son échéance : refait sous la même autorité, sans jamais empêcher d'ouvrir.
            try:
                issue(app, hosts)
            except Exception:
                pass
        with app.database() as db:
            spaces.put(db, KEY, {'enabled': enabled, 'port': port, 'hosts': hosts, 'require_totp': policy, 'certificate': kind})
            db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'],
                       'Accès réseau ouvert' if enabled and not before['enabled'] else 'Accès réseau fermé' if before['enabled'] and not enabled else 'Accès réseau réglé',
                       f'port {port} · {", ".join(hosts) or "aucun nom"}' if enabled else ''))
            if made:
                db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'], 'Autorité locale refaite', 'les appareils doivent installer la nouvelle'))
    later(app)
    # « authority_made » : une autorité existante vient d'être remplacée ; les appareils qui avaient l'ancienne doivent installer la nouvelle.
    return {'ok': True, 'authority_made': made}


def certificate(app, body, session):
    """Refait le certificat autosigné, ou installe celui que fournit l'administrateur."""
    with LOCK:
        settings = read(app)
        if body.get('action') in ('regenerate', 'authority'):
            if not settings['hosts']:
                raise app.Problem('Déclarez d’abord les noms sous lesquels la console sera jointe.')
            # « regenerate » refait le certificat de serveur sous l'autorité en place ; « authority » refait aussi l'autorité, ce qui se confirme.
            fresh = body['action'] == 'authority'
            if fresh and body.get('confirm') is not True:
                raise app.Problem('Refaire l’autorité locale demande une confirmation : tous les appareils devront l’installer de nouveau.')
            had = scope(app) is not None or (folder(app) / 'ca.pem').exists()
            made = generate(app, settings['hosts'], renew=fresh)
            kind, what = 'authority', 'Autorité locale et certificat refaits' if made else 'Certificat de serveur refait'
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
    return {'ok': True, 'certificate': describe(app), 'authority_made': body.get('action') != 'provide' and made and had}


def login_refusal(app, db, handler, name, role):
    """Sur le réseau, un administrateur (ou tout le monde, selon le réglage) ne se connecte qu'avec la double authentification."""
    if not getattr(handler.server, 'network', False):
        return None
    import totp
    if (role == 'admin' or read(app, db)['require_totp'] == 'everyone') and not totp.enabled(db, name):
        return 'Par le réseau, ce compte doit avoir la double authentification. Activez-la dans Mon compte depuis la machine elle-même, puis reconnectez-vous.'
    return None
