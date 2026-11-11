#!/usr/bin/env python3
"""Console NAS locale : API fermée, sessions et opérations limitées au laboratoire."""
import base64
import ctypes
import errno
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import tarfile
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(os.environ.get('NAS_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
from lab import private_write, load_config
from release import version as release_version

STATIC = Path(__file__).resolve().parent / 'static'
STATE = ROOT / 'state/console'
DB = STATE / 'console.db'
LOCK = threading.RLock()
PTZ_LOCK = threading.Lock()
WORKER = ThreadPoolExecutor(max_workers=1)
USER_RE = re.compile(r'[a-z][a-z0-9_-]{2,23}\Z')
SHARE_RE = re.compile(r'[a-z][a-z0-9_-]{1,31}\Z')


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


@contextmanager
def database():
    connection = sqlite3.connect(DB, timeout=20)
    try:
        connection.row_factory = sqlite3.Row
        with connection:
            yield connection
    finally:
        connection.close()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def initialize():
    from installation_lock import held
    with held(ROOT):
        _initialize()


def _initialize():
    STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    for name in ('data/fichiers', 'data/video', 'data/sauvegardes', 'data/.corbeille', 'state/samba'):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    (ROOT / 'data/.corbeille').chmod(0o700)
    (ROOT / 'data/sauvegardes').chmod(0o700)
    from schema import ensure
    ensure(DB)
    with database() as db:
        if not db.execute('SELECT 1 FROM users').fetchone():
            password = secrets.token_urlsafe(24)
            salt = secrets.token_hex(16)
            db.execute('INSERT INTO users(name,salt,hash,role) VALUES (?,?,?,?)', ('admin', salt, password_hash(password, salt), 'admin'))
            from onboarding import write
            write(db, {'phase': 'account', 'name': 'Nacre', 'timezone': 'UTC', 'existing': False})
            private_write(STATE / 'acces.txt', 'Console NAS autonome\nUtilisateur : admin\nMot de passe : ' + password + '\n')
    DB.chmod(0o600)
    if not (STATE / 'smb.json').exists():
        save_smb({'users': [{'name': 'nas', 'uid': os.getuid(), 'enabled': True}], 'shares': [
            {'name': 'fichiers', 'path': '', 'area': 'fichiers', 'readonly': False, 'users': ['nas']},
            {'name': 'video', 'path': '', 'area': 'video', 'readonly': True, 'users': ['nas']},
        ]}, reload=False)
    protection().initialize()


def command(args, data=None, timeout=20):
    result = subprocess.run(args, cwd=ROOT, input=data, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise Problem('Le service n’a pas accepté cette opération. Consulter son état.', 503)
    return result.stdout


def compose(*args, data=None, timeout=25):
    from compose_support import arguments
    return command(arguments(ROOT,*args),data,timeout)


def audit(user, action, detail=''):
    with database() as db:
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES (?,?,?,?)', (time.time(), user, action, detail[:300]))


def make_session(username):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with database() as db:
        db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(token), username, csrf, time.time() + 8 * 3600))
    return token, csrf


def parts(path):
    if not isinstance(path, str) or len(path) > 2048 or '\x00' in path or '\\' in path:
        raise Problem('Chemin invalide.')
    if path.startswith('/') or any(x in ('.', '..') for x in path.split('/')):
        raise Problem('Chemin non autorisé.', 403)
    if any(x.startswith('.nacre-') for x in path.split('/')):
        raise Problem('Espace interne non accessible par ce chemin.',403)
    return [x for x in path.split('/') if x]


def native_resources():
    try:return native_storage('resources','system')
    except Problem:return []


def resolve_area(area,write=False):
    if isinstance(area,str) and area.startswith('native_'):
        resource=next((r for r in native_resources() if r['id']==area[7:]),None)
        if not resource:
            raise Problem('Volume ou restauration non disponible.',503)
        if write and (resource.get('kind')!='volume' or not resource.get('writable')):
            raise Problem('Cet espace est en lecture seule.',403)
        return resource
    if area not in ('fichiers','video','sauvegardes','restaurations'):
        raise Problem('Espace inconnu.')
    if write and area!='fichiers':
        raise Problem('Cet espace est en lecture seule.',403)
    return {'id':area,'name':area,'path':str(ROOT/'data'/area),'kind':'local','writable':area=='fichiers'}


def area_root(area):
    return Path(resolve_area(area)['path'])


def file_areas(admin=True):
    values=[{'id':x,'name':n,'writable':x=='fichiers','kind':'local'} for x,n in
            [('fichiers','Fichiers partagés'),('video','Vidéos'),('sauvegardes','Sauvegardes')]]
    if admin:
        values.append({'id':'restaurations','name':'Restaurations privées','writable':False,'kind':'restore'})
        for r in native_resources():
            values.append({'id':'native_'+r['id'],'name':r['name'],'kind':r.get('kind','restore'),
                           'writable':r.get('kind')=='volume' and r.get('writable',False) and os.access(r['path'],os.W_OK)})
    return values


def available_bytes(fd):
    space=os.fstatvfs(fd)
    return space.f_bavail*space.f_frsize


@contextmanager
def folder(area,path='',write=False):
    resource=resolve_area(area,write)
    fd=os.open(resource['path'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        meta=os.fstat(fd)
        if resource.get('identity') and resource['identity']!={'dev':meta.st_dev,'ino':meta.st_ino}:
            raise Problem('Le volume a changé pendant son ouverture.',503)
        for component in parts(path):
            if component.startswith('.nacre-'):
                raise Problem('Espace interne non accessible par ce chemin.',403)
            next_fd=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=next_fd
        yield fd
    finally:os.close(fd)


@contextmanager
def trash_folder(area):
    if area=='fichiers':
        fd=os.open(ROOT/'data/.corbeille',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:yield fd
        finally:os.close(fd)
        return
    with folder(area,write=True) as root_fd:
        try:os.mkdir('.nacre-trash',mode=0o700,dir_fd=root_fd)
        except FileExistsError:pass
        fd=os.open('.nacre-trash',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root_fd)
        try:
            meta=os.fstat(fd)
            if meta.st_uid!=os.getuid() or meta.st_mode&0o077:
                raise Problem('Le dossier de corbeille du volume n’est pas privé.',403)
            yield fd
        finally:os.close(fd)


@contextmanager
def parent(area, path, write=False):
    components = parts(path)
    if not components:
        raise Problem('Sélectionner un fichier ou un dossier.')
    with folder(area, '/'.join(components[:-1]),write=write) as fd:
        yield fd, components[-1]


def safe_name(name):
    if not isinstance(name, str) or name.strip() != name or not name or len(name) > 180 or name.startswith('.') or any(x in name for x in '/\\\r\n\x00'):
        raise Problem('Nom invalide : éviter les chemins et les noms commençant par un point.')
    return name


def rename_noreplace(source_fd, source, target_fd, target):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def list_files(area, path):
    items = []
    with folder(area, path) as fd:
        for name in os.listdir(fd):
            if name.startswith('.'):
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            items.append({'name': name, 'directory': stat.S_ISDIR(info.st_mode), 'link': stat.S_ISLNK(info.st_mode),
                          'size': info.st_size, 'modified': info.st_mtime})
    return sorted(items, key=lambda x: (not x['directory'], x['name'].casefold()))


def smb_state():
    return json.loads((STATE / 'smb.json').read_text())


def shares():
    from smb_storage import Shares
    return Shares(sys.modules[__name__])


def save_smb(config,reload=True):
    return shares().apply(config,reload=reload)


_upstream_cache = (0, None)


def video_ip():
    global _upstream_cache
    if time.monotonic() - _upstream_cache[0] < 10 and _upstream_cache[1]:
        return _upstream_cache[1]
    cid = compose('ps', '-q', 'video').strip()
    if not cid:
        raise Problem('Le service vidéo est arrêté.', 503)
    data = json.loads(command(['docker', 'inspect', cid]))[0]
    address = next(iter(data['NetworkSettings']['Networks'].values()))['IPAddress']
    if not address:
        raise Problem('Le service vidéo redémarre.', 503)
    _upstream_cache = (time.monotonic(), address)
    return address


def video_get(path, port=5000, headers=None, timeout=10):
    try:
        return urlopen(Request(f'http://{video_ip()}:{port}' + path, headers=headers or {}), timeout=timeout)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise Problem('La vidéo est temporairement indisponible.', 503)


def video_json(path):
    with video_get(path) as response:
        return json.load(response)


def ws_frame(payload):
    data = json.dumps(payload).encode()
    mask = secrets.token_bytes(4)
    head = bytes([0x81, 0x80 | len(data)]) if len(data) < 126 else bytes([0x81, 0xfe]) + struct.pack('!H', len(data))
    return head + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))


def ptz_move(action, preset=None, camera="tapo"):
    allowed = {'left': 'MOVE_LEFT', 'right': 'MOVE_RIGHT', 'up': 'MOVE_UP', 'down': 'MOVE_DOWN', 'stop': 'STOP'}
    if action not in allowed and action != 'preset':
        raise Problem('Commande PTZ non autorisée.')
    from cameras import identifier
    camera=identifier(sys.modules[__name__],camera)
    info = video_json('/api/'+camera+'/ptz/info')
    if action == 'preset':
        if preset not in info.get('presets', []):
            raise Problem('Point de vue non reconnu.')
        allowed['preset'] = 'PRESET_' + preset
    if action != 'stop' and 'pt' not in info.get('features', []):
        raise Problem('Le pilotage PTZ n’est pas encore disponible.', 503)
    with PTZ_LOCK, socket.create_connection((video_ip(), 5000), timeout=4) as sock:
        sock.settimeout(4)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        sock.sendall((f'GET /ws HTTP/1.1\r\nHost: {video_ip()}:5000\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        head = b''
        while b'\r\n\r\n' not in head and len(head) < 16384:
            chunk = sock.recv(2048)
            if not chunk:
                break
            head += chunk
        expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        if not head.startswith(b'HTTP/1.1 101') or expected.lower() not in head.lower():
            raise Problem('Le canal PTZ n’a pas pu être ouvert.', 503)
        try:
            sock.sendall(ws_frame({'topic': camera+'/ptz', 'payload': allowed[action]}))
            if action not in ('stop', 'preset'):
                time.sleep(0.35)
        finally:
            if action != 'preset':
                sock.sendall(ws_frame({'topic': camera+'/ptz', 'payload': 'STOP'}))
            time.sleep(0.08)


def overview():
    disk = shutil.disk_usage(ROOT)
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.split()[0]) * 1024
    services = []
    try:
        service_lines = compose('ps', '--all', '--format', 'json', timeout=3).splitlines()
        services_available = True
    except (Problem, OSError, subprocess.TimeoutExpired):
        service_lines, services_available = [], False
    for line in service_lines:
        if line.strip():
            item = json.loads(line)
            services.append({'name': item['Service'], 'state': item['State'], 'health': item.get('Health', ''), 'status': item['Status']})
    camera = {}
    try:
        stats = video_json('/api/stats') if any(service['name']=='video' and service['state']=='running' for service in services) else {}
        camera_id=next(iter(stats.get('cameras',{})),None)
        c = stats.get('cameras', {}).get(camera_id, {})
        camera = {'id':camera_id, **{key: c.get(key) for key in ('camera_fps', 'process_fps', 'skipped_fps')}}
    except Problem:
        pass
    with database() as db:
        events = [dict(row) for row in db.execute('SELECT ts,username,action,detail FROM audit ORDER BY id DESC LIMIT 8')]
    from onboarding import read
    return {'services_available': services_available, 'host': read(sys.modules[__name__])['name'], 'time': time.time(), 'disk': {'total': disk.total, 'used': disk.used, 'free': disk.free},
            'memory': {'total': memory['MemTotal'], 'used': memory['MemTotal'] - memory['MemAvailable']},
            'load': list(os.getloadavg()), 'cpus': os.cpu_count(), 'uptime': float(Path('/proc/uptime').read_text().split()[0]),
            'services': services, 'camera': camera, 'events': events}


def protection():
    from protection import Protection
    return Protection(sys.modules[__name__])


def storage_profiles():
    from storage_profiles import Profiles
    return Profiles(sys.modules[__name__])


def native_storage(method, actor, body=None):
    from native_storage import NativeClient, NativeError
    client = NativeClient()
    if method == 'status':
        return client.status(actor)
    try:
        return client.request(method, actor, body)
    except NativeError as error:
        raise Problem(str(error)) from None
    except OSError:
        raise Problem('Le service de stockage natif n’est pas activé sur ce matériel.', 503) from None


def run_backup(job, username):
    manager = protection()
    filename = 'fichiers-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + job[:6] + '.tar.gz'
    output = ROOT / 'data/sauvegardes' / filename
    temporary = output.with_name('.' + filename + '.partial')
    total = count = completed = 0
    changed = False
    last = 0

    def progress(amount=0):
        nonlocal completed, last
        completed += amount
        if time.monotonic() - last > .5:
            if manager.cancelled(job):
                raise InterruptedError()
            manager.update(job, progress={'bytes_done': completed, 'total_bytes': total, 'files_done': count})
            last = time.monotonic()

    class Reader:
        def __init__(self, source): self.source = source
        def read(self, length):
            data = self.source.read(length)
            progress(len(data))
            return data

    try:
        with folder('fichiers') as root_fd:
            # Pas de plafond de taille ou de nombre : parcours et copie en flux.
            for base, dirs, files, fd in os.fwalk('.', dir_fd=root_fd, follow_symlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith('.nacre-upload-')]
                for name in files:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not name.startswith('.nacre-upload-') and stat.S_ISREG(info.st_mode):
                        total += info.st_size
                progress()
            with tarfile.open(temporary, 'x:gz', compresslevel=3) as archive:
                temporary.chmod(0o600)
                for base, dirs, files, fd in os.fwalk('.', dir_fd=root_fd, follow_symlinks=False):
                    dirs[:] = [d for d in dirs if not d.startswith('.nacre-upload-')]
                    if base != '.':
                        entry = tarfile.TarInfo(str(PurePosixPath(base)))
                        entry.type, entry.mode = tarfile.DIRTYPE, 0o770
                        archive.addfile(entry)
                        archive.members.clear()
                    for name in files:
                        if name.startswith('.nacre-upload-'):
                            continue
                        if not stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                            continue
                        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                        with os.fdopen(descriptor, 'rb') as source:
                            info = os.fstat(source.fileno())
                            if not stat.S_ISREG(info.st_mode):
                                continue
                            if shutil.disk_usage(temporary.parent).free <= 0:
                                raise OSError(errno.ENOSPC, 'Espace épuisé')
                            count += 1
                            entry = tarfile.TarInfo(str(PurePosixPath(base) / name))
                            entry.size, entry.mtime, entry.mode = info.st_size, info.st_mtime, 0o660
                            archive.addfile(entry, Reader(source))
                            archive.members.clear()
                            after = os.fstat(source.fileno())
                            changed |= (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        if manager.cancelled(job):
            raise InterruptedError()
        temporary.rename(output)
        result = {'file': filename, 'files': count, 'bytes': completed}
        if changed:
            result['warning'] = 'Des fichiers ont changé pendant la copie. Archive partielle.'
        manager.update(job, status='partial' if changed else 'done', result=result, progress={'percent_done':1,'bytes_done':completed,'total_bytes':completed})
        audit(username, 'Archive de fichiers terminée', filename)
    except InterruptedError:
        temporary.unlink(missing_ok=True)
        manager.update(job, status='cancelled', result={'error':'Tâche annulée.'})
    except Exception:
        temporary.unlink(missing_ok=True)
        manager.update(job, status='failed', result={'error':'Sauvegarde interrompue. Vérifier les accès et l’espace physique disponible.'})


class Handler(BaseHTTPRequestHandler):
    server_version = 'NASConsole'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Aucun chemin, ticket ni identifiant dans les journaux HTTP.

    def allowed_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def reply(self, status, data, content='application/json', extra=None):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def session(self):
        # Les cookies sont partagés entre les ports d’un même hôte. Un cookie
        # tiers non reconnu par SimpleCookie ne doit pas masquer celui de Nacre.
        values=[]
        for part in self.headers.get('Cookie','').split(';'):
            name,separator,value=part.strip().partition('=')
            if separator and name=='nas_session':values.append(value)
        # Refuser les doublons ambigus et n’accepter que nos jetons URL-safe.
        if len(values)!=1 or not re.fullmatch(r'[A-Za-z0-9_-]{43}',values[0]):
            raise Problem('Connexion requise.', 401)
        token=values[0]
        with database() as db:
            session = db.execute('SELECT s.*,u.role FROM sessions s JOIN users u ON u.name=s.name WHERE token=? AND expires>? AND u.active=1', (digest(token), time.time())).fetchone()
        if not session:
            raise Problem('Session expirée. Reconnectez-vous.', 401)
        return dict(session)

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0 or length > 32768:
            raise Problem('Requête trop volumineuse.', 413)
        try:
            value = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise Problem('Requête JSON invalide.')
        if not isinstance(value, dict):
            raise Problem('Requête invalide.')
        return value

    def authorize_write(self, session, require_admin=True):
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            raise Problem('Origine non autorisée.', 403)
        if self.headers.get('Sec-Fetch-Site') == 'cross-site' or not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
            raise Problem('Jeton de protection invalide.', 403)
        if require_admin and session['role'] != 'admin':
            raise Problem('Un compte administrateur est nécessaire.', 403)

    def do_GET(self):
        self.handle_request(False)

    def do_POST(self):
        self.handle_request(True)

    def handle_request(self, post):
        try:
            if not self.allowed_host():
                raise Problem('Hôte non autorisé.', 403)
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if not post and url.path == '/connexion-locale':
                token = query.get('ticket', '')
                with database() as db:
                    row = db.execute('DELETE FROM tickets WHERE token=? AND expires>? RETURNING token', (digest(token), time.time())).fetchone()
                if not row:
                    raise Problem('Ce lien de connexion a expiré ou a déjà été utilisé.', 401)
                session_token, _ = make_session('admin')
                return self.reply(303, b'', extra={'Location': '/', 'Set-Cookie': f'nas_session={session_token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'})
            if not post and url.path in ('/', '/app.js', '/native.js', '/onboarding.js', '/components.js', '/alerts.js', '/notifications.js', '/retention.js', '/style.css'):
                path = STATIC / ('index.html' if url.path == '/' else url.path[1:])
                return self.reply(200, path.read_bytes(), mimetypes.guess_type(path)[0] or 'text/plain')
            if post and url.path == '/api/login':
                origin = self.headers.get('Origin')
                if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                    raise Problem('Origine non autorisée.', 403)
                body = self.body()
                if not self.server.login_limit():
                    raise Problem('Trop de tentatives. Attendre une minute.', 429)
                username, password = body.get('username', ''), body.get('password', '')
                with database() as db:
                    user = db.execute('SELECT * FROM users WHERE name=?', (username,)).fetchone()
                salt = user['salt'] if user else '00' * 16
                hashed = password_hash(password, salt)
                if not user or not user['active'] or not hmac.compare_digest(hashed, user['hash']):
                    raise Problem('Identifiant ou mot de passe refusé.', 401)
                token, csrf = make_session(username)
                audit(username, 'Connexion')
                return self.reply(200, {'csrf': csrf, 'name': username, 'role': user['role']}, extra={'Set-Cookie': f'nas_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'})
            session = self.session()
            if post:
                self.authorize_write(session, require_admin=url.path != '/api/logout')
                if url.path == '/api/upload':
                    return self.upload(query, session)
                result = self.mutate(url.path, self.body(), session)
                return self.reply(200, result or {'ok': True})
            if url.path == '/api/me':
                from onboarding import read
                setup = read(sys.modules[__name__])
                return self.reply(200, {**{key: session[key] for key in ('name', 'csrf', 'role')}, 'setup_required': session['role'] == 'admin' and setup['phase'] != 'complete', 'timezone': setup['timezone'], 'nas_name': setup['name'], 'app_version': release_version()})
            if url.path == '/api/setup':
                if session['role'] != 'admin':
                    raise Problem('Accès réservé aux administrateurs.', 403)
                from onboarding import status
                return self.reply(200, status(sys.modules[__name__]))
            if url.path == '/api/notifications':
                if session['role'] != 'admin':raise Problem('Accès réservé aux administrateurs.',403)
                from notifications import status
                return self.reply(200,status(sys.modules[__name__]))
            if url.path == '/api/protection/cleanup-preview':
                if session['role'] != 'admin':raise Problem('Accès réservé aux administrateurs.',403)
                from cleanup import review
                return self.reply(200,review(sys.modules[__name__],query.get('job'),session['name']))
            if url.path == '/api/protection/retention-policies':
                if session['role'] != 'admin':raise Problem('Accès réservé aux administrateurs.',403)
                from automatic_retention import listing
                return self.reply(200,listing(sys.modules[__name__]))
            if url.path == '/api/alerts':
                if session['role'] != 'admin':raise Problem('Accès réservé aux administrateurs.',403)
                from alerts import listing
                return self.reply(200,listing(sys.modules[__name__]))
            if url.path == '/api/overview':
                return self.reply(200, overview())
            if url.path == '/api/areas':
                return self.reply(200,file_areas(session['role']=='admin'))
            if url.path == '/api/files':
                if (query.get('area') == 'restaurations' or query.get('area','').startswith('native_')) and session['role'] != 'admin':
                    raise Problem('Accès réservé aux administrateurs.', 403)
                return self.reply(200, {'items': list_files(query.get('area', 'fichiers'), query.get('path', ''))})
            if url.path == '/api/download':
                if (query.get('area') == 'restaurations' or query.get('area','').startswith('native_')) and session['role'] != 'admin':
                    raise Problem('Accès réservé aux administrateurs.', 403)
                return self.download(query)
            if url.path == '/api/storage':
                import disks
                return self.reply(200, disks.inventory(ROOT))
            if url.path == '/api/storage/health':
                import disks
                return self.reply(200, disks.health(ROOT, query['id']))
            if url.path in ('/api/storage/native', '/api/storage/profiles'):
                if session['role'] != 'admin':
                    raise Problem('Accès réservé aux administrateurs.', 403)
                result = native_storage('status', session['name']) if url.path.endswith('/native') else storage_profiles().list()
                return self.reply(200, result)
            if url.path.startswith('/api/protection/'):
                if session['role'] != 'admin':
                    raise Problem('Accès réservé aux administrateurs.', 403)
                manager = protection()
                if url.path == '/api/protection/installation':
                    from system_recovery import status
                    return self.reply(200, status(ROOT))
                if url.path == '/api/protection/migrations':
                    from schema import status
                    return self.reply(200, status(DB))
                if url.path == '/api/protection/capabilities':
                    return self.reply(200, manager.capabilities())
                if url.path == '/api/protection/sources':
                    return self.reply(200,manager.sources())
                if url.path == '/api/protection/targets':
                    return self.reply(200, manager.targets())
                if url.path == '/api/protection/repositories':
                    return self.reply(200, manager.repositories())
                if url.path == '/api/protection/points':
                    return self.reply(200, manager.points(query['repo']))
                if url.path == '/api/protection/plans':
                    return self.reply(200, manager.plans())
                if url.path == '/api/protection/recovery':
                    repository = manager.repository(query['repo'])
                    return self.reply(200, {'repository': repository['path'], 'password': Path(repository['key_file']).read_text().strip(),
                                            'engine': 'restic', 'version': 1}, extra={'Content-Disposition': 'attachment; filename="nacre-cle-de-recuperation.json"'})
            if url.path == '/api/components':
                if session['role'] != 'admin':
                    raise Problem('Accès réservé aux administrateurs.',403)
                from deployment import catalog
                return self.reply(200,catalog(sys.modules[__name__]))
            if url.path == '/api/cameras':
                from cameras import listing
                return self.reply(200,listing(sys.modules[__name__]))
            if url.path.startswith('/api/camera/'):
                from cameras import identifier
                camera_id=identifier(sys.modules[__name__],query.get('camera','tapo'))
            if url.path == '/api/smb':
                return self.reply(200, shares().view(smb_state()))
            if url.path == '/api/users':
                with database() as db:
                    return self.reply(200, [dict(r) for r in db.execute('SELECT name,role,active FROM users')])
            if url.path == '/api/events':
                with database() as db:
                    return self.reply(200, [dict(r) for r in db.execute('SELECT ts,username,action,detail FROM audit ORDER BY id DESC LIMIT 200')])
            if url.path == '/api/trash':
                with database() as db:
                    return self.reply(200,[dict(r) for r in db.execute('SELECT * FROM trash ORDER BY ts DESC') if session['role']=='admin' or r['area']=='fichiers'])
            if url.path == '/api/jobs':
                with database() as db:
                    return self.reply(200, [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY ts DESC LIMIT 30')])
            if url.path == '/api/camera/info':
                return self.reply(200, video_json('/api/'+camera_id+'/ptz/info'))
            if url.path == '/api/camera/settings':
                camera = load_config(ROOT / 'state/frigate/config.yml')['cameras'][camera_id]
                return self.reply(200, {'enabled': camera.get('enabled', True), 'days': camera.get('record', {}).get('continuous', {}).get('days', 1)})
            if url.path == '/api/camera/recordings':
                after = max(time.time() - 86400, float(query.get('after', time.time() - 3600)))
                return self.reply(200, video_json(f'/api/{camera_id}/recordings?after={after}&before={time.time()}')[-100:])
            if url.path == '/api/camera/snapshot':
                with video_get('/api/'+camera_id+'/latest.jpg?height=720&quality=80') as response:
                    return self.reply(200, response.read(4 * 1024**2), 'image/jpeg')
            if url.path == '/api/camera/live':
                return self.proxy_stream('/api/'+camera_id+'?fps=5&height=720', 'multipart/x-mixed-replace; boundary=frame')
            if url.path == '/api/camera/clip':
                start, end = float(query['start']), float(query['end'])
                if not 0 < end - start <= 300 or start < time.time() - 7 * 86400 or end > time.time() + 60:
                    raise Problem('Intervalle vidéo invalide (5 minutes maximum).')
                return self.proxy_stream(f'/api/{camera_id}/start/{start}/end/{end}/clip.mp4', 'video/mp4')
            raise Problem('Ressource inconnue.', 404)
        except Problem as error:
            self.reply(error.status, {'error': error.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (FileNotFoundError, NotADirectoryError):
            self.reply(404, {'error': 'Fichier ou dossier introuvable.'})
        except FileExistsError:
            self.reply(409, {'error': 'Ce nom existe déjà. Aucun fichier n’a été remplacé.'})
        except (ValueError, KeyError, TypeError):
            self.reply(400, {'error': 'Paramètres invalides.'})
        except OSError as error:
            self.close_connection = True
            if error.errno in (errno.ENOSPC, errno.EDQUOT):
                self.reply(507, {'error': 'Espace physique disponible insuffisant.'})
            elif error.errno in (errno.EACCES, errno.EPERM, errno.ELOOP):
                self.reply(403, {'error': 'Accès au fichier ou au périphérique non autorisé.'})
            else:
                self.reply(500, {'error': 'Opération système non aboutie.'})
        except Exception:
            self.reply(500, {'error': 'Opération non aboutie. Les détails sensibles ne sont pas affichés.'})

    def mutate(self, route, body, session):
        user = session['name']
        with LOCK:
            if route in ('/api/service','/api/camera/settings','/api/smb/user','/api/smb/share'):
                from deployment import ensure_idle
                ensure_idle(sys.modules[__name__])
            if route == '/api/logout':
                with database() as db:
                    db.execute('DELETE FROM sessions WHERE token=?', (session['token'],))
                return {'ok': True}
            if route in ('/api/notifications/configure','/api/notifications/test','/api/notifications/retry'):
                import notifications
                action={'configure':notifications.configure,'test':notifications.test,'retry':notifications.retry}[route.rsplit('/',1)[1]]
                return action(sys.modules[__name__],body,user)
            if route == '/api/alerts/acknowledge':
                from alerts import acknowledge
                return acknowledge(sys.modules[__name__],body,user)
            if route == '/api/components/install':
                from deployment import submit
                return submit(sys.modules[__name__],body,user)
            if route == '/api/cameras/add':
                from cameras import submit
                return submit(sys.modules[__name__],body,user)
            if route == '/api/setup/account':
                from onboarding import account
                return account(sys.modules[__name__], body, session)
            if route == '/api/setup/finish':
                from onboarding import finish
                return finish(sys.modules[__name__], body, session)
            if route == '/api/folder':
                name = safe_name(body['name'])
                with folder(body.get('area','fichiers'), body.get('path', ''),write=True) as fd:
                    os.mkdir(name, mode=0o770, dir_fd=fd)
                    os.chmod(name, 0o2770, dir_fd=fd, follow_symlinks=False)
                audit(user, 'Dossier créé', name)
            elif route == '/api/rename':
                name = safe_name(body['name'])
                with parent(body.get('area','fichiers'), body['path'],write=True) as (fd, old):
                    if name in os.listdir(fd):
                        raise FileExistsError()
                    rename_noreplace(fd, old, fd, name)
                audit(user, 'Fichier renommé', body['path'])
            elif route == '/api/trash':
                token=secrets.token_hex(16)
                area=body.get('area','fichiers')
                with parent(area,body['path'],write=True) as (fd,name),trash_folder(area) as target_fd:
                    with database() as db:
                        db.execute('INSERT INTO trash(id,original,ts,area) VALUES(?,?,?,?)',(token,body['path'],time.time(),area))
                        rename_noreplace(fd,name,target_fd,token)
                audit(user,'Déplacé en corbeille',area+': '+body['path'])
            elif route == '/api/restore':
                with database() as db:
                    row=db.execute('SELECT * FROM trash WHERE id=?',(body['id'],)).fetchone()
                    if not row:raise Problem('Élément introuvable.',404)
                    with parent(row['area'],row['original'],write=True) as (fd,name),trash_folder(row['area']) as trash_fd:
                        rename_noreplace(trash_fd,row['id'],fd,name)
                    db.execute('DELETE FROM trash WHERE id=?',(body['id'],))
                audit(user,'Élément restauré',row['area']+': '+row['original'])
            elif route == '/api/service':
                if body.get('name') not in ('video', 'fichiers') or body.get('action') not in ('start', 'stop', 'restart'):
                    raise Problem('Action de service non autorisée.')
                if body['name']=='fichiers':
                    manager=shares()
                    if body['action']=='stop':
                        manager.set_intent(False);compose('stop','fichiers')
                    else:
                        manager.prepare_start(smb_state());manager.set_intent(True)
                        compose('up','-d','--no-deps','--force-recreate','fichiers',timeout=90)
                        manager.apply(smb_state())
                else:compose(body['action'],body['name'])
                audit(user, 'Service ' + body['action'], body['name'])
            elif route == '/api/camera/ptz':
                ptz_move(body['action'], body.get('preset'), body.get('camera','tapo'))
                audit(user, 'Commande PTZ', body.get('preset', body['action']))
            elif route == '/api/camera/settings':
                days, enabled = body.get('days'), body.get('enabled')
                if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30 or not isinstance(enabled, bool):
                    raise Problem('Choisir une durée de 1 à 30 jours et un état valide.')
                from cameras import identifier
                camera_id=identifier(sys.modules[__name__],body.get('camera','tapo'))
                path = ROOT / 'state/frigate/config.yml'
                config = load_config(path)
                camera = config['cameras'][camera_id]
                camera['enabled'] = enabled
                camera.setdefault('record', {}).setdefault('continuous', {})['days'] = days
                code = 'import json,sys;from frigate.config import FrigateConfig;FrigateConfig.model_validate(json.load(sys.stdin))'
                compose('exec', '-T', 'video', 'python3', '-c', code, data=json.dumps(config))
                private_write(STATE / 'config-avant-reglage-camera.yml', path.read_text())
                private_write(path, json.dumps(config, indent=2) + '\n')
                compose('restart', 'video')
                for _ in range(15):
                    try:
                        with video_get('/api/version', timeout=1):
                            break
                    except Problem:
                        time.sleep(1)
                audit(user, 'Réglages vidéo mis à jour', str(days) + ' jour(s) ; ' + ('active' if enabled else 'en pause'))
            elif route == '/api/backup':
                job = protection().submit('backup', user)
                audit(user, 'Sauvegarde démarrée')
                return {'job': job}
            elif route == '/api/storage/profile':
                return storage_profiles().create(body, user)
            elif route == '/api/storage/profile-delete':
                return storage_profiles().delete(body, user)
            elif route == '/api/storage/profile-prepare':
                return storage_profiles().prepare(body,user)
            elif route == '/api/storage/native-prepare':
                return native_storage('prepare', user, body)
            elif route == '/api/storage/native-commit':
                result = native_storage('commit', user, body)
                audit(user, 'Opération de stockage natif', result.get('object', ''))
                return result
            elif route == '/api/storage/native-cancel':
                return native_storage('cancel',user,body)
            elif route == '/api/protection/repository':
                return protection().create_repository(body, user)
            elif route == '/api/protection/cleanup-preview':
                from cleanup import preview
                return preview(sys.modules[__name__],body,user)
            elif route == '/api/protection/cleanup-apply':
                from cleanup import submit
                return submit(sys.modules[__name__],body,user)
            elif route == '/api/protection/retention-preview':
                from retention import preview
                return preview(sys.modules[__name__],body,user)
            elif route == '/api/protection/retention-openings':
                from maintenance_window import preview
                return preview(sys.modules[__name__],body)
            elif route == '/api/protection/retention-policy':
                from automatic_retention import configure
                return configure(sys.modules[__name__],body,user)
            elif route == '/api/protection/retention-apply':
                from retention import submit
                return submit(sys.modules[__name__],body,user)
            elif route == '/api/protection/snapshot':
                protection().repository(body['repo'])
                options = {'sources':protection().validate_sources(body.get('sources')),'repo': body['repo'], 'configuration': bool(body.get('configuration', True)), 'video': bool(body.get('video', False)), 'label': str(body.get('label', ''))[:100]}
                return {'job': protection().submit('snapshot', user, options)}
            elif route == '/api/protection/restore':
                repository = protection().repository(body['repo'])
                protection().point(repository, body['snapshot'])
                return {'job': protection().submit('snapshot_restore', user, {'repo': body['repo'], 'snapshot': body['snapshot']})}
            elif route == '/api/protection/plan':
                return protection().save_plan(body, user)
            elif route == '/api/protection/run-plan':
                plan = next((p for p in protection().plans() if p['id'] == body['id']), None)
                if not plan:
                    raise Problem('Plan inconnu.', 404)
                if not plan['repo']:
                    raise Problem('Choisir une destination avant d’exécuter ce plan.')
                return {'job': protection().submit('snapshot', user, {**plan['config'], 'repo': plan['repo'], 'plan': plan['id'], 'label': plan['name']})}
            elif route == '/api/protection/cancel':
                protection().cancel(body['job'])
                return {'ok': True}
            elif route == '/api/user':
                name, password, role = body['name'], body['password'], body.get('role', 'viewer')
                if not USER_RE.fullmatch(name) or len(password) < 12 or len(password) > 128 or role not in ('admin', 'viewer'):
                    raise Problem('Nom : 3 à 24 caractères simples. Mot de passe : 12 caractères minimum.')
                salt = secrets.token_hex(16)
                with database() as db:
                    if db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
                        raise Problem('Ce compte existe déjà.', 409)
                    db.execute('INSERT INTO users(name,salt,hash,role) VALUES (?,?,?,?)', (name, salt, password_hash(password, salt), role))
                audit(user, 'Compte console créé', name)
            elif route == '/api/user/update':
                name, role, active = body['name'], body.get('role'), body.get('active')
                password = body.get('password', '')
                if role not in ('admin', 'viewer') or not isinstance(active, bool) or password and not 12 <= len(password) <= 128:
                    raise Problem('Paramètres de compte invalides. Mot de passe : 12 caractères minimum.')
                if name == user and (not active or role != 'admin'):
                    raise Problem('Conserver votre propre compte administrateur actif.')
                with database() as db:
                    target = db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
                    if not target:
                        raise Problem('Compte inconnu.', 404)
                    db.execute('UPDATE users SET role=?,active=? WHERE name=?', (role, int(active), name))
                    if password:
                        salt = secrets.token_hex(16)
                        db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, password_hash(password, salt), name))
                        db.execute('DELETE FROM sessions WHERE name=? AND token<>?', (name, session['token']))
                if name == 'admin' and password:
                    private_write(STATE / 'acces.txt', 'Console Nacre — utilisateur admin.\nMot de passe modifié depuis la console ; utiliser le mot de passe que vous avez choisi.\n')
                audit(user, 'Compte console mis à jour', name)
            elif route == '/api/smb/user':
                config = smb_state()
                name = body['name']
                if not USER_RE.fullmatch(name):
                    raise Problem('Nom de compte invalide.')
                password = body.get('password', '')
                existing = next((u for u in config['users'] if u['name'] == name), None)
                if password:
                    if not 12 <= len(password) <= 128 or any(c in password for c in '\r\n\x00'):
                        raise Problem('Mot de passe SMB : 12 à 128 caractères, sur une seule ligne.')
                    if not existing:
                        uid = max(u['uid'] for u in config['users']) + 1
                        compose('exec', '-T', 'fichiers', 'adduser', '-D', '-H', '-u', str(uid), '-G', 'nas', name)
                        existing = {'name': name, 'uid': uid, 'enabled': True}
                        config['users'].append(existing)
                    compose('exec', '-T', 'fichiers', 'smbpasswd', '-s', '-a', name, data=password + '\n' + password + '\n')
                    if name == 'nas':
                        # Conserver l’inode du secret monté dans le conteneur.
                        fd = os.open(ROOT / 'state/smb_password', os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
                        with os.fdopen(fd, 'w') as output:
                            os.fchmod(output.fileno(), 0o600)
                            output.write(password + '\n')
                if not existing:
                    raise Problem('Saisir un mot de passe pour créer ce compte.')
                enabled = body.get('enabled', True)
                if not isinstance(enabled, bool):
                    raise Problem('Valeur invalide.')
                if name == 'nas' and not enabled:
                    raise Problem('Le compte initial nas doit rester actif.')
                compose('exec', '-T', 'fichiers', 'smbpasswd', '-e' if enabled else '-d', name)
                existing['enabled'] = enabled
                save_smb(config)
                audit(user, 'Compte SMB mis à jour', name)
            elif route == '/api/smb/share':
                config = smb_state()
                name = body['name']
                if not SHARE_RE.fullmatch(name) or name in ('global', 'homes', 'printers', 'print$'):
                    raise Problem('Nom de partage invalide.')
                area, path = body.get('area', 'fichiers'), body.get('path', '')
                if not isinstance(area,str):raise Problem('Espace invalide.')
                if area not in ('fichiers', 'video') and not area.startswith('native_'):
                    raise Problem('Espace non autorisé.')
                resource=resolve_area(area)
                if area.startswith('native_') and resource.get('kind')!='volume':
                    raise Problem('Les restaurations privées ne peuvent pas être partagées.',403)
                with folder(area, path):
                    pass
                if any(c in path for c in '\r\n[]%'):
                    raise Problem('Chemin de partage invalide.')
                users = body.get('users', [])
                if not isinstance(users, list) or not users or not all(isinstance(u, str) and any(x['name'] == u and x['enabled'] for x in config['users']) for u in users):
                    raise Problem('Choisir au moins un compte SMB actif.')
                item = {'name': name, 'area': area, 'path': path, 'readonly': True if area == 'video' or not resource.get('writable',False) else bool(body.get('readonly', False)), 'users': users}
                old = next((s for s in config['shares'] if s['name'] == name), None)
                if old:
                    config['shares'].remove(old)
                config['shares'].append(item)
                save_smb(config)
                audit(user, 'Partage SMB configuré', name)
            else:
                raise Problem('Action inconnue.', 404)

    def upload(self, query, session):
        area=query.get('area','fichiers')
        path, name = query.get('path', ''), safe_name(query['name'])
        length = int(self.headers.get('Content-Length', '-1'))
        if length < 0:
            raise Problem('Taille du transfert manquante.', 411)
        with folder(area,path,write=True) as fd:
            if length>available_bytes(fd):
                self.close_connection=True
                raise Problem('Espace physique insuffisant sur le volume de destination.',507)
            if name in os.listdir(fd):
                raise FileExistsError()
            temporary_name = '.nacre-upload-' + secrets.token_hex(12)
            output_fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
            os.fchmod(output_fd, 0o660)
            try:
                with os.fdopen(output_fd, 'wb') as output:
                    remaining = length
                    while remaining:
                        data = self.rfile.read(min(1024**2, remaining))
                        if not data:
                            raise Problem('Transfert interrompu.')
                        if len(data) > available_bytes(fd):
                            raise OSError(errno.ENOSPC, 'Espace physique épuisé')
                        output.write(data)
                        remaining -= len(data)
                    output.flush()
                    os.fsync(output.fileno())
                rename_noreplace(fd, temporary_name, fd, name)
                # Le succès HTTP suit la synchronisation du contenu et du nom.
                os.fsync(fd)
            except Exception:
                # Après publication, une erreur de fsync du dossier laisse un
                # fichier complet à vérifier ; ne pas le supprimer ni l’écraser.
                try:os.unlink(temporary_name, dir_fd=fd)
                except FileNotFoundError:pass
                raise
        audit(session['name'], 'Fichier déposé', path + '/' + name)
        return self.reply(200, {'ok': True})

    def download(self, query):
        with parent(query.get('area', 'fichiers'), query['path']) as (fd, name):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise Problem('Choisir un fichier ordinaire.')
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(info.st_size))
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(name))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            shutil.copyfileobj(source, self.wfile, 256 * 1024)

    def proxy_stream(self, path, content):
        with video_get(path, headers={'Range': self.headers['Range']} if self.headers.get('Range') else {}, timeout=20) as upstream:
            self.send_response(upstream.status)
            self.send_header('Content-Type', upstream.headers.get('Content-Type', content))
            self.send_header('Cache-Control', 'no-store')
            for key in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
                if upstream.headers.get(key):
                    self.send_header(key, upstream.headers[key])
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            shutil.copyfileobj(upstream, self.wfile, 64 * 1024)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    def __init__(self, address, handler):
        from installation_lock import acquire
        self.installation_fd = acquire(ROOT)
        try:
            super().__init__(address, handler)
        except BaseException:
            if self.installation_fd is not None:os.close(self.installation_fd)
            self.installation_fd=None
            raise
        self.attempts = []
        self.limit_lock = threading.Lock()

    def server_close(self):
        super().server_close()
        if self.installation_fd is not None:
            os.close(self.installation_fd)
            self.installation_fd = None

    def login_limit(self):
        with self.limit_lock:
            now = time.time()
            self.attempts = [x for x in self.attempts if x > now - 60]
            if len(self.attempts) >= 8:
                return False
            self.attempts.append(now)
            return True


if __name__ == '__main__':
    os.umask(0o077)
    from installation_lock import acquire
    process_installation_lock = acquire(ROOT)
    initialize()
    if len(sys.argv) > 1 and sys.argv[1] == 'init':
        print('Console initialisée ; identifiants conservés dans son répertoire privé.')
    elif len(sys.argv) > 1 and sys.argv[1] == 'ticket':
        token = secrets.token_urlsafe(32)
        with database() as db:
            db.execute('DELETE FROM tickets WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO tickets VALUES (?,?)', (digest(token), time.time() + 60))
        print('http://127.0.0.1:'+str(int(os.environ.get('NAS_PORT','8766')))+'/connexion-locale?ticket=' + token)
    else:
        protection().recover()
        protection().start_scheduler()
        shares().start_watch()
        from alerts import start as start_alerts
        start_alerts(sys.modules[__name__])
        from notifications import start as start_notifications
        start_notifications(sys.modules[__name__])
        port=int(os.environ.get('NAS_PORT','8766'))
        print(f'Console NAS sur http://127.0.0.1:{port}', flush=True)
        Server(('127.0.0.1', port), Handler).serve_forever()
