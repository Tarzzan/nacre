"""Suite bureautique : Nacre garde les fichiers, les droits et les versions ; une suite en conteneur les édite.

Le dialogue suit le protocole WOPI, celui de Collabora Online. Nacre en est l'hôte : il délivre, pour un fichier et
une personne, un jeton à durée limitée ; la suite s'en sert pour lire le fichier et y enregistrer. À chaque appel,
les droits de la personne sont revérifiés. La suite elle-même n'est ni installée ni pilotée par Nacre : un
administrateur la lance, puis indique ici où la joindre.
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import stat
import threading
import time
import zipfile
import io
import xml.etree.ElementTree as ElementTree
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import spaces
import versions

KEY = 'office'
TOKEN_SECONDS = 8 * 3600
DISCOVERY_SECONDS = 600
DISCOVERY_MAX = 4 * 1024 ** 2
SAME_SESSION = 600
TOKENS, FILES, CACHE, WRITTEN = {}, {}, {}, {}
LOCK = threading.RLock()
OPEN = 'office:open'
LOADED = {'done': False}
TOKEN_LIMIT = 2000
ADDRESS = re.compile(r'https?://[A-Za-z0-9.\-\[\]:]+(:\d{1,5})?\Z')
NEW = {'odt': 'application/vnd.oasis.opendocument.text', 'ods': 'application/vnd.oasis.opendocument.spreadsheet'}


def read(app, db=None):
    if db is None:
        with app.database() as connection:
            return read(app, connection)
    doc = spaces.get(db, KEY, {})
    doc = doc if isinstance(doc, dict) else {}
    return {'enabled': doc.get('enabled') is True, 'url': doc.get('url', '') if isinstance(doc.get('url'), str) else '',
            'internal': doc.get('internal', '') if isinstance(doc.get('internal'), str) else '',
            'wopi': doc.get('wopi', '') if isinstance(doc.get('wopi'), str) else ''}


def address(app, value, what, required=True):
    text = value.strip().rstrip('/') if isinstance(value, str) else ''
    if not text and not required:
        return ''
    if not ADDRESS.fullmatch(text):
        raise app.Problem(f'Adresse {what} invalide : attendu « http://hôte:port » ou « https://hôte », sans chemin.')
    return text


# Formats proposés dans Fichiers : la suite sait aussi ouvrir du texte, que l'éditeur intégré garde pour lui.
FORMATS = ('odt', 'ods', 'odp', 'odg', 'docx', 'xlsx', 'pptx', 'doc', 'xls', 'ppt', 'rtf')
ORIGIN = {'until': 0, 'value': ''}


def origin(app):
    """Origine de la suite pour le navigateur, quand elle est activée : sert à la politique de sécurité des pages. Relue toutes les cinq secondes au plus."""
    now = time.time()
    if ORIGIN['until'] > now:
        return ORIGIN['value']
    try:
        settings = read(app)
        value = settings['url'] if settings['enabled'] and ADDRESS.fullmatch(settings['url']) else ''
    except Exception:
        value = ''
    ORIGIN.update(until=now + 5, value=value)
    return value


def discovery(app, settings, force=False):
    """Formats que la suite annonce, avec l'adresse de son éditeur pour chacun. Gardé dix minutes."""
    source = settings['internal'] or settings['url']
    with LOCK:
        cached = CACHE.get(source)
        if cached and not force and cached[0] > time.time():
            return cached[1]
    try:
        with urlopen(Request(source + '/hosting/discovery'), timeout=6) as response:
            raw = response.read(DISCOVERY_MAX + 1)
    except Exception:
        raise app.Problem('La suite bureautique ne répond pas à cette adresse.', 503) from None
    if len(raw) > DISCOVERY_MAX or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise app.Problem('Réponse inattendue de la suite bureautique.', 502)
    try:
        tree = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise app.Problem('Réponse illisible de la suite bureautique.', 502) from None
    found = {}
    for action in tree.iter('action'):
        ext, name, src = action.get('ext', '').lower(), action.get('name', ''), action.get('urlsrc', '')
        if not ext or not src or name not in ('edit', 'view', 'view_comment'):
            continue
        parts = urlsplit(src)
        # L'adresse annoncée est celle que la suite se connaît ; pour le navigateur, c'est l'adresse déclarée ici qui vaut.
        entry = found.setdefault(ext, {})
        entry['edit' if name == 'edit' else 'view'] = settings['url'] + parts.path + ('?' + parts.query if parts.query else '?')
    if not found:
        raise app.Problem('La suite bureautique n’annonce aucun format.', 502)
    with LOCK:
        CACHE[source] = (time.time() + DISCOVERY_SECONDS, found)
    return found


def status(app, session=None, port=None):
    settings = read(app)
    result = {**settings, 'formats': [], 'reachable': None, 'default_wopi': f'http://127.0.0.1:{int(port or os.environ.get("NAS_PORT", "8766"))}'}
    if settings['enabled']:
        try:
            result.update(formats=[f for f in sorted(discovery(app, settings, force=True)) if f in FORMATS], reachable=True)
        except app.Problem as error:
            result.update(reachable=False, error=str(error))
    return result


def configure(app, body, session):
    """Indique où joindre la suite, et où la suite joint Nacre. L'activation vérifie que la suite répond."""
    enabled = body.get('enabled')
    if type(enabled) is not bool:
        raise app.Problem('Réglages invalides.')
    settings = {'enabled': enabled, 'url': address(app, body.get('url'), 'de la suite', enabled), 'internal': address(app, body.get('internal'), 'interne de la suite', False),
                'wopi': address(app, body.get('wopi'), 'de Nacre vue par la suite', enabled)}
    formats = []
    if enabled:
        formats = sorted(discovery(app, settings, force=True))
    with app.database() as db:
        spaces.put(db, KEY, settings)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(), session['name'],
                   'Suite bureautique raccordée' if enabled else 'Suite bureautique débranchée', settings['url'] if enabled else ''))
    ORIGIN['until'] = 0
    with LOCK:
        CACHE.clear()
        if not enabled:
            TOKENS.clear(); FILES.clear()
    if not enabled:
        remember(app)
    return {'ok': True, 'formats': [f for f in formats if f in FORMATS]}


def available(app, session):
    """Extensions que la suite sait ouvrir, pour proposer le bouton ; vide si elle n'est pas raccordée ou ne répond pas."""
    settings = read(app)
    if not settings['enabled']:
        return []
    with LOCK:
        if CACHE.get('absente', (0,))[0] > time.time():
            return []
    try:
        return [f for f in sorted(discovery(app, settings)) if f in FORMATS]
    except app.Problem:
        # Suite injoignable : on ne la redemande pas à chaque page, seulement une minute plus tard.
        with LOCK:
            CACHE['absente'] = (time.time() + 60, None)
        return []


def remember(app):
    """Note les documents en cours, par l'empreinte de leur jeton seulement : un redémarrage de Nacre ne les coupe pas."""
    with LOCK:
        doc = {'tokens': dict(TOKENS), 'files': dict(FILES)}
    with app.database() as db:
        spaces.put(db, OPEN, doc)


def recall(app, now):
    """Au premier besoin après un démarrage, retrouve les documents encore en cours."""
    with LOCK:
        if LOADED['done']:
            return
        LOADED['done'] = True
    try:
        with app.database() as db:
            doc = spaces.get(db, OPEN, {})
    except Exception:
        return
    tokens, files = (doc.get(key) if isinstance(doc, dict) and isinstance(doc.get(key), dict) else {} for key in ('tokens', 'files'))
    with LOCK:
        for ident, value in files.items():
            if (isinstance(value, dict) and isinstance(value.get('area'), str) and isinstance(value.get('path'), str)
                    and isinstance(value.get('expires'), (int, float)) and value['expires'] > now):
                FILES.setdefault(ident, {'area': value['area'], 'path': value['path'], 'expires': value['expires']})
        for digest, value in tokens.items():
            if (isinstance(value, dict) and isinstance(value.get('name'), str) and value.get('file') in FILES and type(value.get('write')) is bool
                    and isinstance(value.get('expires'), (int, float)) and value['expires'] > now):
                TOKENS.setdefault(digest, {'name': value['name'], 'role': value.get('role'), 'file': value['file'], 'write': value['write'], 'expires': value['expires']})


def open_document(app, body, session, now=None):
    """Prépare l'ouverture d'un fichier dans la suite : adresse de son éditeur et jeton limité à ce fichier et à cette personne."""
    now = time.time() if now is None else now
    settings = read(app)
    if not settings['enabled']:
        raise app.Problem('Aucune suite bureautique n’est raccordée.', 409)
    recall(app, now)
    area, path = body.get('area', 'fichiers'), body.get('path')
    if not isinstance(area, str) or not isinstance(path, str) or not app.parts(path):
        raise app.Problem('Choisir un fichier.')
    path = '/'.join(app.parts(path))
    level = spaces.level(app, session, area)
    with app.parent(area, path) as (fd, name):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise app.Problem('Seul un fichier ordinaire s’ouvre dans la suite bureautique.')
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    entry = discovery(app, settings).get(ext) if ext in FORMATS else None
    if not entry:
        raise app.Problem('La suite bureautique n’ouvre pas ce type de fichier.', 415)
    write = level == 'write' and 'edit' in entry
    token, ident = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    with LOCK:
        for old in [t for t, value in TOKENS.items() if value['expires'] <= now]:
            TOKENS.pop(old)
        for old in [f for f, value in FILES.items() if value['expires'] <= now]:
            FILES.pop(old)
        if len(TOKENS) >= TOKEN_LIMIT:
            raise app.Problem('Trop de documents ouverts dans la suite bureautique. Réessayez plus tard.', 503)
        expires = now + TOKEN_SECONDS
        FILES[ident] = {'area': area, 'path': path, 'expires': expires}
        TOKENS[hashlib.sha256(token.encode()).hexdigest()] = {'name': session['name'], 'role': session['role'], 'file': ident, 'write': write, 'expires': expires}
    remember(app)
    src = (entry.get('edit') if write else entry.get('view') or entry.get('edit'))
    app.audit(session['name'], 'Document ouvert dans la suite bureautique', spaces.detail(app, area, path) if area.startswith('espace_') else area + ': ' + path)
    return {'action': src + ('' if src.endswith(('?', '&')) else '&') + 'WOPISrc=' + quote(f'{settings["wopi"]}/wopi/files/{ident}', safe=''),
            'token': token, 'ttl': int(expires * 1000), 'write': write, 'name': name}


def stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'


def grant(app, ident, token, now=None):
    """Jeton valable pour ce fichier : rend la personne et l'emplacement, ou refuse sans dire pourquoi."""
    now = time.time() if now is None else now
    recall(app, now)
    with LOCK:
        value = TOKENS.get(hashlib.sha256(token.encode()).hexdigest()) if isinstance(token, str) and token else None
        target = FILES.get(ident)
    if not value or not target or value['file'] != ident or value['expires'] <= now:
        raise app.Problem('Jeton invalide ou expiré.', 401)
    with app.database() as db:
        row = db.execute('SELECT role FROM users WHERE name=? AND active=1', (value['name'],)).fetchone()
    if not row:
        raise app.Problem('Jeton invalide ou expiré.', 401)
    return {'name': value['name'], 'role': row['role']}, value, target


def recent(app, area, path, actor, now):
    with versions.LOCK, versions.store(app, area) as fd:
        values = versions.load(fd).get(path, []) if fd is not None else []
    last = values[0] if values else None
    return bool(last) and last.get('by') == actor and last.get('editor') is True and now - (last.get('ts') or 0) < SAME_SESSION


def wopi(app, handler, path, query, post):
    """Routes de la suite : /wopi/files/<id> (informations) et /wopi/files/<id>/contents (lecture, enregistrement)."""
    match = re.fullmatch(r'/wopi/files/([A-Za-z0-9_-]{10,40})(/contents)?', path)
    if not match or (post and not match[2]):
        raise app.Problem('Ressource inconnue.', 404)
    person, value, target = grant(app, match[1], query.get('access_token', ''))
    app.ACTOR.session = person   # les droits de la personne s'appliquent à chaque appel
    area, where = target['area'], target['path']
    level = spaces.level(app, person, area)
    if level is None:
        raise app.Problem('Jeton invalide ou expiré.', 401)
    writable = value['write'] and level == 'write'
    try:
        if not match[2]:
            with app.parent(area, where) as (fd, name):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            return handler.reply(200, {'BaseFileName': name, 'Size': info.st_size, 'UserId': person['name'], 'OwnerId': 'nacre', 'UserFriendlyName': person['name'],
                                       'UserCanWrite': writable, 'ReadOnly': not writable, 'LastModifiedTime': stamp(info.st_mtime), 'UserCanNotWriteRelative': True,
                                       'SupportsUpdate': writable, 'SupportsLocks': False, 'DisablePrint': False, 'HideSaveOption': not writable})
        if not post:
            return handler.download({'area': area, 'path': where})
        if not writable:
            raise app.Problem('Ce document est ouvert en lecture.', 403)
        return put(app, handler, person, area, where)
    except (FileNotFoundError, NotADirectoryError):
        raise app.Problem('Le fichier n’existe plus.', 404) from None


def put(app, handler, person, area, where, now=None):
    """Enregistrement par la suite : écrit à côté, échange les noms d'un coup, garde l'ancien contenu comme version."""
    now = time.time() if now is None else now
    length = int(handler.headers.get('Content-Length', '-1'))
    if length < 0:
        handler.close_connection = True
        raise app.Problem('Taille de l’enregistrement manquante.', 411)
    known = handler.headers.get('X-COOL-WOPI-Timestamp') or handler.headers.get('X-LOOL-WOPI-Timestamp')
    with app.parent(area, where, write=True) as (fd, name):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise app.Problem('Le fichier n’existe plus.', 404)
        unchanged = not known or known == stamp(info.st_mtime)
        if not unchanged:
            # La suite demande alors à la personne quoi faire ; rien n'est écrasé sans elle.
            handler.close_connection = True
            return handler.reply(409, {'COOLStatusCode': 1010, 'LOOLStatusCode': 1010})
        if length > app.available_bytes(fd):
            handler.close_connection = True
            raise app.Problem('Espace physique insuffisant sur le volume.', 507)
        temporary = '.nacre-upload-' + secrets.token_hex(12)
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
        try:
            with os.fdopen(out, 'wb') as output:
                os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
                remaining = length
                while remaining:
                    data = handler.rfile.read(min(1024 ** 2, remaining))
                    if not data:
                        raise app.Problem('Enregistrement interrompu.')
                    output.write(data)
                    remaining -= len(data)
                output.flush()
                os.fsync(output.fileno())
            versions.exchange(fd, temporary, fd, name)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
        try:
            # Regroupés seulement si le contenu remplacé est bien le dernier enregistrement de cette même personne :
            # un contenu venu d'ailleurs, écrasé à sa demande, reste retrouvable.
            if WRITTEN.get((area, where)) == (person['name'], info.st_mtime_ns, info.st_size) and recent(app, area, where, person['name'], now):
                os.unlink(temporary, dir_fd=fd)
            else:
                ident = versions.keep(app, area, where, fd, temporary, person['name'], now)
                with versions.LOCK, versions.store(app, area, create=True) as store:
                    index = versions.load(store)
                    for item in index.get(where, []):
                        if item['id'] == ident:
                            item['editor'] = True
                    versions.save(store, index)
        except Exception:
            app.rename_noreplace(fd, temporary, fd, f'{name}.avant-enregistrement-{secrets.token_hex(3)}')
        os.fsync(fd)
        fresh = os.stat(name, dir_fd=fd, follow_symlinks=False)
        with LOCK:
            if len(WRITTEN) > 512:
                WRITTEN.clear()
            WRITTEN[(area, where)] = (person['name'], fresh.st_mtime_ns, fresh.st_size)
    return handler.reply(200, {'LastModifiedTime': stamp(fresh.st_mtime)})


def blank(kind):
    """Document OpenDocument vide, texte ou classeur : le plus petit fichier que la suite ouvre."""
    body = '<office:text><text:p/></office:text>' if kind == 'odt' else '<office:spreadsheet><table:table table:name="Feuille1"><table:table-column/><table:table-row><table:table-cell/></table:table-row></table:table></office:spreadsheet>'
    content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" office:version="1.2">'
               f'<office:body>{body}</office:body></office:document-content>')
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{NEW[kind]}"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr(zipfile.ZipInfo('mimetype'), NEW[kind], compress_type=zipfile.ZIP_STORED)
        archive.writestr('content.xml', content, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr('META-INF/manifest.xml', manifest, compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()


def create(app, body, session):
    """Nouveau document bureautique vide dans un dossier. Un nom déjà pris est refusé."""
    area, folder = body.get('area', 'fichiers'), body.get('path', '')
    name = app.safe_name(body.get('name'))
    kind = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if kind not in NEW or not isinstance(area, str) or not isinstance(folder, str):
        raise app.Problem('Nom invalide : terminez-le par .odt (texte) ou .ods (classeur).')
    data = blank(kind)
    with app.folder(area, folder, write=True) as fd:
        if name in os.listdir(fd):
            raise FileExistsError()
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
        with os.fdopen(out, 'wb') as output:
            os.fchmod(output.fileno(), 0o660)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(fd)
    path = '/'.join(app.parts(folder) + [name])
    app.audit(session['name'], 'Document créé', spaces.detail(app, area, path) if area.startswith('espace_') else area + ': ' + path)
    return {'ok': True, 'path': path}
