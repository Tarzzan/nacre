"""WebDAV : les fichiers des espaces, pour les outils et les appareils, sous /dav/.

Chaque requête commence sans aucun droit, puis prend ceux de l'appareil qui s'annonce (voir devices.py). Les fichiers
passent par les mêmes portes que la console : un espace n'est ouvert que si la personne y a droit, aucun lien n'est
suivi, les dossiers internes ne se voient pas. Une erreur n'est jamais déguisée en dossier vide : un outil de
synchronisation y lirait « tout a été supprimé ».

L'arborescence réserve dès maintenant la place des autres services :
  /dav/files/<espace>/…      les fichiers (ce module) : lecture, et écriture pour un appareil qui l'a reçue
  /dav/principals/, /dav/calendars/, /dav/addressbooks/   à venir
"""
import email.utils
import errno
import mimetypes
import os
import re
import secrets
import stat
import threading
import time
import xml.etree.ElementTree as ElementTree
import xml.parsers.expat as expat
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

import devices
import spaces

READ = ('OPTIONS', 'PROPFIND', 'GET', 'HEAD')
BODY_MAX = 64 * 1024
ENTRIES_MAX = 50_000
CHUNK = 256 * 1024
KNOWN = ('resourcetype', 'displayname', 'getcontentlength', 'getlastmodified', 'getetag', 'getcontenttype', 'quota-available-bytes')
RANGE = re.compile(r'bytes=(\d*)-(\d*)\Z')


def send(handler, status, body=b'', kind='text/plain; charset=utf-8', headers=None):
    body = body.encode() if isinstance(body, str) else body
    handler.send_response(status)
    handler.send_header('Content-Type', kind)
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Cache-Control', 'no-store')
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    if handler.close_connection:
        handler.send_header('Connection', 'close')
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(body)


def plain(name):
    return re.sub(r'[/\\\x00-\x1f\x7f]', ' ', str(name)).strip()


def zones(app, session):
    """Espaces que l'appareil peut ouvrir, sous le nom qui les désigne dans l'adresse.

    Le nom d'un espace ne dépend pas de l'ordre de création : « Mon espace » et « Fichiers partagés » désignent toujours les deux
    espaces de base, et des espaces d'équipe de même nom portent tous une marque qui les distingue.
    """
    areas = [area for area in spaces.areas(app, session) if area['id'] == 'fichiers' or area['id'].startswith('espace_')]
    base = [area for area in areas if area['id'] == 'fichiers' or area.get('kind') == 'personal']
    held = {plain(area['name']).casefold() for area in base}
    seen = {}
    for area in areas:
        if area not in base:
            seen[plain(area['name']).casefold()] = seen.get(plain(area['name']).casefold(), 0) + 1
    found = []
    for area in areas:
        name = plain(area['name']) or area['id']
        if area not in base and (name.casefold() in held or seen.get(name.casefold(), 0) > 1 or name.startswith('.')):
            name = f'{name} ~{area["id"][-4:]}'
        found.append({'id': area['id'], 'segment': name, 'writable': bool(area['writable'])})
    return found


def stamp(seconds):
    return email.utils.formatdate(seconds, usegmt=True)


def etag(info):
    return f'"{info.st_mtime_ns:x}-{info.st_size:x}"'


def wanted(app, handler):
    """Propriétés demandées par un PROPFIND : None pour toutes, une liste sinon, ou 'names' pour leurs seuls noms."""
    if handler.headers.get('Transfer-Encoding'):
        raise app.Problem('Corps de requête en morceaux non pris en charge ici.', 411)
    length = int(handler.headers.get('Content-Length') or 0)
    if length < 0 or length > BODY_MAX:
        raise app.Problem('Requête trop volumineuse.', 413)
    if length:
        proceed(handler)   # l'appareil est déjà reconnu : un outil qui attend le feu vert avant tout corps ne reste pas bloqué
    raw = handler.rfile.read(length) if length else b''
    handler.unread = False
    if not raw.strip():
        return None
    # Aucune déclaration de type, donc aucune entité : refusée par l'analyseur lui-même, quel que soit l'encodage du corps.
    def declared(*_):
        raise app.Problem('Requête refusée.', 400)
    probe = expat.ParserCreate()
    probe.StartDoctypeDeclHandler = declared
    try:
        probe.Parse(raw, True)
        tree = ElementTree.fromstring(raw)
    except (expat.ExpatError, ElementTree.ParseError):
        raise app.Problem('Requête illisible.', 400) from None
    if tree.find('{DAV:}propname') is not None:
        return 'names'
    prop = tree.find('{DAV:}prop')
    if prop is None:
        return None
    return [(child.tag[1:].partition('}')[0], child.tag.partition('}')[2]) if child.tag.startswith('{') else ('', child.tag) for child in prop][:64]


def entry(href, name, info, ask, free=None):
    """Réponse d'une ressource : ses propriétés connues, et un refus net pour celles qu'on ne tient pas."""
    folder = info is None or stat.S_ISDIR(info.st_mode)
    values = {'resourcetype': '<D:collection/>' if folder else '', 'displayname': escape(plain(name) or name)}
    if info is not None:
        values['getlastmodified'] = stamp(info.st_mtime)
    if not folder:
        values.update(getcontentlength=str(info.st_size), getetag=escape(etag(info)), getcontenttype=escape(mimetypes.guess_type(name)[0] or 'application/octet-stream'))
    elif free is not None:
        values['quota-available-bytes'] = str(free)
    if ask == 'names':
        found, missing = ''.join(f'<D:{key}/>' for key in values), ''
    elif ask is None:
        found, missing = ''.join(f'<D:{key}>{value}</D:{key}>' for key, value in values.items()), ''
    else:
        found = ''.join(f'<D:{key}>{values[key]}</D:{key}>' for space, key in ask if space == 'DAV:' and key in values)
        # Une propriété inconnue est rendue sous un préfixe neutre : son nom vient du client, il est échappé et borné.
        missing = ''.join(f'<x:{key} xmlns:x="{escape(space, {chr(34): "&quot;"})}"/>' if space else f'<{key}/>'
                          for space, key in ask if not (space == 'DAV:' and key in values) and re.fullmatch(r'[A-Za-z_][\w.-]{0,63}', key) and len(space) < 200)
    out = f'<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop>{found}</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>'
    if missing:
        out += f'<D:propstat><D:prop>{missing}</D:prop><D:status>HTTP/1.1 404 Not Found</D:status></D:propstat>'
    return out + '</D:response>'


def multistatus(handler, parts):
    body = '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">' + ''.join(parts) + '</D:multistatus>'
    return send(handler, 207, body, 'application/xml; charset=utf-8')


def link(*segments, folder=False):
    return '/dav/' + '/'.join(quote(segment, safe='') for segment in segments) + ('/' if folder and segments else '')


def depth(app, handler):
    value = handler.headers.get('Depth', 'infinity').strip().lower()
    if value not in ('0', '1'):
        problem = app.Problem('Profondeur refusée : 0 ou 1.', 403)
        problem.xml = '<?xml version="1.0" encoding="utf-8"?><D:error xmlns:D="DAV:"><D:propfind-finite-depth/></D:error>'
        raise problem
    return int(value)


def locate(app, session, segments):
    """Espace et chemin désignés par une adresse sous /dav/files/."""
    area = next((zone for zone in zones(app, session) if zone['segment'] == segments[0]), None)
    if area is None:
        raise app.Problem('Espace inconnu ou fermé.', 404)
    path = '/'.join(segments[1:])
    if any(part in ('.', '..') or part.startswith('.nacre-') or '\\' in part or '\x00' in part for part in segments[1:]) or len(path) > 2048:
        raise app.Problem('Chemin non autorisé.', 403)
    return area, path


def propfind(app, handler, session, segments):
    ask, deep = wanted(app, handler), depth(app, handler)
    if not segments:
        return multistatus(handler, [entry('/dav/', 'Nacre', None, ask)] + ([entry(link('files', folder=True), 'files', None, ask)] if deep else []))
    if segments[0] != 'files':
        raise app.Problem('Ressource inconnue.', 404)
    if len(segments) == 1:
        parts = [entry(link('files', folder=True), 'files', None, ask)]
        for zone in zones(app, session) if deep else ():
            # Chaque espace avec sa date, comme lorsqu'on l'interroge lui-même ; un espace momentanément illisible reste listé.
            try:
                with app.folder(zone['id'], '') as fd:
                    info = os.fstat(fd)
            except (OSError, app.Problem):
                info = None
            parts.append(entry(link('files', zone['segment'], folder=True), zone['segment'], info if info is not None else None, ask))
        return multistatus(handler, parts)
    area, path = locate(app, session, segments[1:])
    here = link('files', *segments[1:])
    if not path:
        opened = app.folder(area['id'], '')
    else:
        with app.parent(area['id'], path) as (fd, name):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise FileNotFoundError()
        if stat.S_ISREG(info.st_mode):
            return multistatus(handler, [entry(here, segments[-1], info, ask)])
        opened = app.folder(area['id'], path)
    with opened as fd:
        parts = [entry(here + '/', segments[-1], os.fstat(fd), ask, app.available_bytes(fd))]
        if deep:
            with os.scandir(fd) as entries:
                for item in entries:
                    if item.name.startswith('.nacre-') or item.is_symlink() or not listable(item.name):
                        continue
                    info = item.stat(follow_symlinks=False)
                    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        continue
                    if len(parts) > ENTRIES_MAX:
                        raise app.Problem('Dossier trop grand pour être listé d’un seul tenant.', 507)
                    parts.append(entry(here + '/' + quote(item.name, safe='') + ('/' if stat.S_ISDIR(info.st_mode) else ''), item.name, info, ask))
    return multistatus(handler, parts)


def listable(name):
    """Nom qu'une réponse peut porter : un nom illisible ou à caractère de contrôle rendrait tout le dossier illisible aux appareils."""
    try:
        name.encode()
    except UnicodeEncodeError:
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in name)


def matches(header, tag):
    """Vrai si l'en-tête If-None-Match désigne cette version du fichier : liste, marque faible ou étoile."""
    return any(item.strip() in ('*', tag, 'W/' + tag) for item in header.split(','))


def span(app, header, size):
    """Plage d'octets demandée : (début, fin incluse), ou None pour le fichier entier."""
    found = RANGE.fullmatch(header.strip()) if header else None
    if not found or (not found[1] and not found[2]):
        return None
    if not found[1]:
        count = int(found[2])
        start, end = max(0, size - count), size - 1
    else:
        start, end = int(found[1]), min(int(found[2]), size - 1) if found[2] else size - 1
    if start >= size or start > end:
        problem = app.Problem('Plage hors du fichier.', 416)
        problem.headers = {'Content-Range': f'bytes */{size}'}
        raise problem
    return start, end


def get(app, handler, session, segments):
    if len(segments) < 3 or segments[0] != 'files':
        if len(segments) < 3 and (not segments or segments[0] == 'files'):
            raise app.Problem('Un dossier se lit par PROPFIND.', 405)
        raise app.Problem('Ressource inconnue.', 404)
    area, path = locate(app, session, segments[1:])
    with app.parent(area['id'], path) as (fd, name):
        # L'entrée est regardée sans la suivre : un lien n'existe pas ici, un dossier ne se télécharge pas.
        seen = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(seen.st_mode):
            raise app.Problem('Un dossier se lit par PROPFIND.', 405)
        if not stat.S_ISREG(seen.st_mode):
            raise FileNotFoundError()
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except OSError as error:
            if error.errno == errno.ELOOP:   # remplacé par un lien entre-temps
                raise FileNotFoundError() from None
            raise
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise FileNotFoundError()
        tag = etag(info)
        headers = {'ETag': tag, 'Last-Modified': stamp(info.st_mtime), 'Accept-Ranges': 'bytes', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-cache',
                   'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name)}
        asked, since = handler.headers.get('If-None-Match'), handler.headers.get('If-Modified-Since')
        unchanged = matches(asked, tag) if asked is not None else False
        if asked is None and since:
            # Certains clients ne valident que par la date (le Finder) : inchangé si le fichier n'est pas plus récent, à la seconde.
            try:
                unchanged = int(info.st_mtime) <= email.utils.parsedate_to_datetime(since).timestamp()
            except (TypeError, ValueError, OverflowError):
                unchanged = False
        if unchanged:
            handler.send_response(304)
            for key in ('ETag', 'Last-Modified'):
                handler.send_header(key, headers[key])
            handler.end_headers()
            return
        # Une plage ne vaut que pour le fichier qu'on avait, désigné par sa marque ou par sa date : sinon il est renvoyé entier.
        fresh = handler.headers.get('If-Range', tag).strip() in (tag, headers['Last-Modified'])
        part = span(app, handler.headers.get('Range'), info.st_size) if fresh else None
        start, end = part if part else (0, info.st_size - 1)
        length = end - start + 1
        handler.send_response(206 if part else 200)
        handler.send_header('Content-Type', mimetypes.guess_type(name)[0] or 'application/octet-stream')
        handler.send_header('Content-Length', str(length))
        if part:
            handler.send_header('Content-Range', f'bytes {start}-{end}/{info.st_size}')
        for key, value in headers.items():
            handler.send_header(key, value)
        handler.end_headers()
        if handler.command == 'HEAD':
            return
        # Les en-têtes sont partis : quoi qu'il arrive ensuite, plus aucune autre réponse ne s'écrit sur cette connexion.
        handler.started = True
        try:
            source.seek(start)
            while length > 0:
                data = source.read(min(CHUNK, length))
                if not data:
                    break
                handler.wfile.write(data)
                length -= len(data)
        finally:
            if length > 0:
                handler.close_connection = True   # fichier raccourci ou lecture interrompue : le compte n'y est pas


# ------------------------------------------------------------------------------------------------------------------------------
# Écriture : dépôt, dossier, corbeille, déplacement, copie. Mêmes portes que la console : droits de la personne, remplacement
# d'un seul tenant, ancienne version gardée, suppression vers la corbeille. Rien n'est jamais écrit à moitié sous son nom final.

WRITE = ('PUT', 'DELETE', 'MKCOL', 'MOVE', 'COPY')
SAME = 600               # un outil qui renvoie le même fichier coup sur coup ne remplit pas les versions
NOTE = 3600              # une ligne de journal par heure et par appareil, pas une par fichier
FLUSH = 5                # la ligne en cours suit le compte réel à quelques secondes près
STALE = 86400            # un fichier provisoire de plus d'un jour est le reste d'un envoi interrompu
ACTION = 'Fichiers modifiés par un appareil'
SIZE = re.compile(rb'[0-9A-Fa-f]{1,16}')
WRITTEN, COUNTS, SWEPT = {}, {}, {}
NOTES = threading.Lock()


def named(app, name):
    """Nom qu'un appareil peut créer. Les noms à point sont admis (un outil de synchronisation en porte), jamais les dossiers internes."""
    if (not name or name in ('.', '..') or name != name.strip() or name.startswith('.nacre-') or '\\' in name or '/' in name
            or len(name.encode('utf-8', 'surrogatepass')) > 255 or not listable(name)):
        raise app.Problem('Nom non autorisé.', 403)
    return name


def place(app, session, segments, what='Cette adresse', create=True):
    """Espace et chemin d'une écriture : jamais la racine, la liste des espaces ni un espace lui-même.

    Les règles de nom ne valent que pour ce qui est créé : un fichier déjà là sous un nom que Nacre n'aurait pas donné
    (une espace en fin de nom, déposé par le partage réseau) doit pouvoir être supprimé ou déplacé.
    """
    if len(segments) < 3 or segments[0] != 'files':
        raise app.Problem(f'{what} ne se modifie pas : les espaces se créent et se retirent dans la console.', 403)
    area, path = locate(app, session, segments[1:])
    if create:
        named(app, segments[-1])
    return area, path


def summary(state):
    count, removed = state['count'], state['removed']
    text = f'{state["label"]} · {count} opération{"s" if count > 1 else ""}'
    return text + (f', dont {removed} suppression{"s" if removed > 1 else ""}' if removed else '')


def write(app, state):
    """Écrit la ligne de journal de la fenêtre en cours, ou la met à jour avec le compte du moment."""
    with NOTES:
        state['timer'] = False
        try:
            with app.database() as db:
                if state['row'] is None:
                    state['row'] = db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',
                                              (state['since'], state['name'], ACTION, summary(state))).lastrowid
                else:
                    db.execute('UPDATE audit SET detail=? WHERE rowid=? AND ts=? AND action=?', (summary(state), state['row'], state['since'], ACTION))
        except Exception:
            pass


def settle(app):
    """Met à jour sans attendre les lignes en cours."""
    for state in list(COUNTS.values()):
        write(app, state)


def noted(app, session, removed=False):
    """Journal : une ligne par heure et par appareil, écrite dès la première opération puis tenue à jour.

    La trace existe donc tout de suite, et son compte (dont les suppressions) suit ce que l'appareil a réellement fait,
    sans une écriture en base par fichier.
    """
    device = session.get('device') or {}
    key, now = device.get('id'), time.time()
    with NOTES:
        state = COUNTS.get(key)
        if state is None or now - state['since'] >= NOTE:
            if len(COUNTS) > 2000:
                COUNTS.clear()
            state = COUNTS[key] = {'since': now, 'row': None, 'count': 0, 'removed': 0, 'timer': False,
                                   'name': session['name'], 'label': device.get('label') or 'appareil'}
        state['count'] += 1
        state['removed'] += 1 if removed else 0
        first = state['row'] is None and not state['timer']
        if not first and not state['timer']:
            state['timer'] = True
            timer = threading.Timer(FLUSH, write, (app, state))
            timer.daemon = True
            timer.start()
        elif first:
            state['timer'] = True   # la première écriture est en cours : les suivantes attendent leur tour
    if first:
        write(app, state)


def incoming(app, handler):
    """Corps d'un dépôt : sa longueur si elle est annoncée, et ses morceaux. Les envois « en morceaux » sont décodés ici."""
    coding = (handler.headers.get('Transfer-Encoding') or '').strip().lower()
    announced = handler.headers.get('Content-Length')
    if coding:
        if coding != 'chunked' or announced is not None:
            raise app.Problem('Envoi ambigu : une longueur ou des morceaux, pas les deux.', 400)

        def chunks():
            while True:
                line = handler.rfile.readline(1026)
                if not line.endswith(b'\n'):
                    raise app.Problem('Envoi illisible.', 400)
                token = line.split(b';', 1)[0].strip(b' \t\r\n')
                if not SIZE.fullmatch(token):   # ni signe, ni préfixe, ni soulignement : rien qu'un autre lecteur comprendrait autrement
                    raise app.Problem('Envoi illisible.', 400)
                size = int(token, 16)
                if size == 0:
                    for _ in range(64):   # en-têtes de fin, ignorés
                        if handler.rfile.readline(8192) in (b'\r\n', b'\n', b''):
                            handler.unread = False
                            break
                    return   # fin jamais trouvée : le corps reste « non lu », la connexion sera fermée
                while size:
                    data = handler.rfile.read(min(CHUNK, size))
                    if not data:
                        raise app.Problem('Envoi interrompu.', 400)
                    size -= len(data)
                    yield data
                if handler.rfile.read(2) != b'\r\n':
                    raise app.Problem('Envoi illisible.', 400)
        return None, chunks()
    if announced is None or not announced.strip().isdigit():
        raise app.Problem('Taille de l’envoi manquante.', 411)
    total = int(announced)

    def whole():
        remaining = total
        while remaining:
            data = handler.rfile.read(min(CHUNK, remaining))
            if not data:
                raise app.Problem('Envoi interrompu.', 400)
            remaining -= len(data)
            yield data
        handler.unread = False
    return total, whole()


def proceed(handler):
    """Le client attendait un feu vert avant d'envoyer : il ne le reçoit qu'ici, une fois ses droits vérifiés."""
    asked = (handler.headers.get('Expect') or '').strip().lower() == '100-continue'   # cette requête-ci, pas une précédente
    if getattr(handler, 'expects', False) and asked:
        handler.expects = False
        handler.send_response_only(100)
        handler.end_headers()


def moment(app, handler):
    """Date que l'outil veut donner au fichier (en-tête X-OC-Mtime, celui de rclone), ou None."""
    value = handler.headers.get('X-OC-Mtime')
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if -2**31 <= seconds < 4_102_444_800 else None   # avant 1970 aussi : sinon l'outil renverrait le fichier à chaque passage


def fits(app, fd, name, total):
    """Ce qui occupe le nom avant un dépôt (ou None), après les refus qui ne demandent pas de recevoir le corps."""
    try:
        existing = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and stat.S_ISDIR(existing.st_mode):
        raise app.Problem('Un dossier porte déjà ce nom.', 405)
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise app.Problem('Ce nom n’est pas un fichier ordinaire : il n’est pas remplacé.', 403)
    if total is not None and total > app.available_bytes(fd):
        raise app.Problem('Espace insuffisant sur le volume.', 507)
    return existing


def sweep(fd, key, now=None):
    """Retire du dossier les fichiers provisoires qu'un envoi interrompu (console arrêtée en plein dépôt) a laissés.

    Une fois par jour et par dossier au plus, à l'occasion d'un dépôt. Fichiers ordinaires seulement, et d'après la date
    que seul le système pose : un envoi en cours, même daté du passé par l'outil, n'est jamais pris pour un reste.
    """
    now = time.time() if now is None else now
    if now - SWEPT.get(key, 0) < STALE:
        return 0
    if len(SWEPT) > 4096:
        SWEPT.clear()
    SWEPT[key] = now
    removed = 0
    try:
        for name in os.listdir(fd):
            if not name.startswith('.nacre-upload-'):
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and now - info.st_ctime > STALE:
                os.unlink(name, dir_fd=fd)
                removed += 1
    except OSError:
        pass
    return removed


def aside(app, fd, temporary, target_fd, name):
    """L'ancien contenu n'a pas pu rejoindre les versions : il reste à côté, sous un nom visible, plutôt que d'être perdu."""
    try:
        app.rename_noreplace(fd, temporary, target_fd, f'{name}.avant-remplacement-{secrets.token_hex(3)}')
    except FileNotFoundError:
        pass   # déjà rangé parmi les versions avant l'échec : il n'y a plus rien à mettre de côté


def store(app, session, area, path, fd, name, total, chunks, when=None):
    """Écrit un fichier à côté de sa place puis l'y met d'un seul tenant. Rend (créé, informations du fichier en place)."""
    import versions
    existing = fits(app, fd, name, total)
    temporary = '.nacre-upload-' + secrets.token_hex(12)
    out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
    try:
        with os.fdopen(out, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(existing.st_mode) if existing is not None else 0o660)
            for data in chunks:
                if len(data) > app.available_bytes(fd):
                    raise app.Problem('Espace insuffisant sur le volume.', 507)
                output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if when is not None:
            os.utime(temporary, (when, when), dir_fd=fd, follow_symlinks=False)
        key, device, kept = (area, path), (session.get('device') or {}).get('id'), 0
        if existing is None:
            app.rename_noreplace(fd, temporary, fd, name)
        else:
            versions.exchange(fd, temporary, fd, name)
            # Ce qui vient réellement d'être retiré, et non ce qui était là avant l'envoi : pendant qu'un gros fichier arrivait,
            # quelqu'un d'autre a pu enregistrer le sien par la console ou le partage réseau.
            old = os.stat(temporary, dir_fd=fd, follow_symlinks=False)
            last = WRITTEN.get(key)
            # Le même appareil renvoie coup sur coup le fichier qu'il vient d'écrire, et une version en a déjà été gardée il y a peu :
            # les états intermédiaires n'encombrent pas les versions. La première modification, elle, en garde toujours une.
            if last and stat.S_ISREG(old.st_mode) and last[:3] == (device, old.st_mtime_ns, old.st_size) and time.time() - last[3] < SAME:
                kept = last[3]
                os.unlink(temporary, dir_fd=fd)
            else:
                kept = time.time()
                try:
                    versions.keep(app, area, path, fd, temporary, session['name'])
                except Exception:
                    aside(app, fd, temporary, fd, name)
        os.fsync(fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=fd)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            pass
        raise
    sweep(fd, (area, path.rpartition('/')[0]))
    fresh = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if len(WRITTEN) > 4096:
        WRITTEN.clear()
    # Dernier état écrit par cet appareil, et moment où une version a été gardée pour lui (0 : jamais, le fichier vient d'être créé).
    WRITTEN[key] = (device, fresh.st_mtime_ns, fresh.st_size, kept)
    return existing is None, fresh


class Parent:
    """Dossier parent ouvert, refermé à la sortie ; son absence est un conflit (409)."""

    def __init__(self, app, area, path, write=True):
        self.manager = app.parent(area['id'], path, write=write)
        self.app = app

    def __enter__(self):
        try:
            return self.manager.__enter__()
        except (FileNotFoundError, NotADirectoryError):
            raise self.app.Problem('Le dossier qui doit recevoir cet élément n’existe pas.', 409) from None

    def __exit__(self, *details):
        return self.manager.__exit__(*details)


def checked(app, handler, existing):
    """Conditions posées par le client : ne créer que si rien n'existe, ne remplacer que la version qu'il connaît."""
    absent, known = handler.headers.get('If-None-Match'), handler.headers.get('If-Match')
    if absent is not None and existing is not None and matches(absent, etag(existing)):
        raise app.Problem('Un fichier porte déjà ce nom.', 412)
    if known is not None and (existing is None or not matches(known, etag(existing))):
        raise app.Problem('Le fichier a changé depuis votre dernière lecture.', 412)


def put(app, handler, session, segments):
    area, path = place(app, session, segments)
    if handler.headers.get('Content-Range') is not None:
        # Un fragment pris pour le fichier entier le tronquerait sans erreur : la reprise d'envoi n'existe pas ici.
        raise app.Problem('Envoi partiel non pris en charge : renvoyer le fichier entier.', 400)
    total, chunks = incoming(app, handler)
    with Parent(app, area, path) as (fd, name):
        checked(app, handler, fits(app, fd, name, total))   # tous les refus connus d'avance, avant le feu vert
        proceed(handler)
        when = moment(app, handler)
        created, fresh = store(app, session, area['id'], path, fd, name, total, chunks, when)
    noted(app, session)
    return send(handler, 201 if created else 204, b'', headers={'ETag': etag(fresh), **({'X-OC-Mtime': 'accepted'} if when is not None else {})})


def mkcol(app, handler, session, segments):
    if not segments or segments == ['files'] or (len(segments) == 2 and segments[0] == 'files'
                                                 and any(zone['segment'] == segments[1] for zone in zones(app, session))):
        raise app.Problem('Ce dossier existe déjà.', 405)   # « créer s'il manque » : un outil le demande pour l'espace lui-même
    area, path = place(app, session, segments)
    if handler.unread:
        raise app.Problem('Un dossier se crée sans contenu.', 415)
    with Parent(app, area, path) as (fd, name):
        try:
            os.mkdir(name, mode=0o770, dir_fd=fd)
        except FileExistsError:
            raise app.Problem('Ce nom existe déjà.', 405) from None
        os.chmod(name, 0o2770, dir_fd=fd, follow_symlinks=False)
    noted(app, session)
    return send(handler, 201)


def discard(app, area, path, fd, name):
    """Vers la corbeille de l'espace, d'où la console sait restaurer."""
    token = secrets.token_hex(16)
    with app.trash_folder(area) as target:
        with app.database() as db:
            db.execute('INSERT INTO trash(id,original,ts,area) VALUES(?,?,?,?)', (token, path, time.time(), area))
            app.rename_noreplace(fd, name, target, token)


def delete(app, handler, session, segments):
    area, path = place(app, session, segments, 'Un espace', create=False)
    with app.parent(area['id'], path, write=True) as (fd, name):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise FileNotFoundError()
        discard(app, area['id'], path, fd, name)
    noted(app, session, removed=True)
    return send(handler, 204)


def destination(app, handler, session):
    """Adresse d'arrivée d'un déplacement ou d'une copie : sur ce même NAS, sous /dav/files/."""
    raw = handler.headers.get('Destination')
    if not raw or len(raw) > 4096:
        raise app.Problem('Adresse d’arrivée manquante.', 400)
    url = urlsplit(raw)
    # Le nom d'hôte seul : un outil y joint parfois l'identifiant, et un relais peut retirer le port. Ce n'est pas ce contrôle
    # qui protège : seul le chemin sert ensuite, et l'espace comme les droits sont vérifiés de nouveau.
    if url.netloc and (url.hostname or '') != (urlsplit('//' + (handler.headers.get('Host') or '')).hostname or ''):
        raise app.Problem('L’arrivée doit se trouver sur ce même NAS.', 502)
    path = unquote(url.path, errors='strict')
    if not path.startswith('/dav/'):
        raise app.Problem('L’arrivée doit se trouver sous /dav/files/.', 403)
    return place(app, session, [part for part in path[4:].split('/') if part], 'Cette arrivée')


def transfer(app, handler, session, segments, move):
    source, origin = place(app, session, segments, 'Un espace', create=False)
    target, arrival = destination(app, handler, session)
    replace = (handler.headers.get('Overwrite') or 'T').strip().upper() != 'F'
    same = source['id'] == target['id']
    if same and (arrival == origin or arrival.startswith(origin + '/')):
        raise app.Problem('Un élément ne se déplace ni ne se copie dans lui-même.', 409 if arrival != origin else 403)
    if same and origin.startswith(arrival + '/'):
        raise app.Problem('Un élément ne prend pas la place du dossier qui le contient.', 409)
    import versions
    with app.parent(source['id'], origin, write=move) as (sfd, sname), Parent(app, target, arrival) as (dfd, dname):
        info = os.stat(sname, dir_fd=sfd, follow_symlinks=False)
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise FileNotFoundError()
        try:
            there = os.stat(dname, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            there = None
        if there is not None and not replace:
            raise app.Problem('L’arrivée existe déjà.', 412)
        if not move:
            if not stat.S_ISREG(info.st_mode):
                raise app.Problem('Un dossier ne se copie pas d’un seul geste : copiez son contenu.', 403)
            descriptor = os.open(sname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=sfd)
            with os.fdopen(descriptor, 'rb') as reader:
                size = os.fstat(reader.fileno()).st_size
                store(app, session, target['id'], arrival, dfd, dname, size, iter(lambda: reader.read(CHUNK), b''), info.st_mtime)
        else:
            try:
                if there is None:
                    app.rename_noreplace(sfd, sname, dfd, dname)
                else:
                    # L'élément vient d'abord à côté de l'arrivée, sous un nom provisoire : deux volumes différents ou une source
                    # disparue se voient avant tout geste, et l'ancien contenu de l'arrivée ne passe jamais par l'espace de départ.
                    temporary = '.nacre-upload-' + secrets.token_hex(12)
                    app.rename_noreplace(sfd, sname, dfd, temporary)
                    try:
                        if stat.S_ISREG(info.st_mode) and stat.S_ISREG(there.st_mode):
                            versions.exchange(dfd, temporary, dfd, dname)   # à aucun instant l'arrivée n'est absente
                        else:
                            # Un dossier en jeu : ce qui occupait l'arrivée part à la corbeille, puis la place est prise.
                            discard(app, target['id'], arrival, dfd, dname)
                            app.rename_noreplace(dfd, temporary, dfd, dname)
                            temporary = None
                    except BaseException:
                        try:
                            app.rename_noreplace(dfd, temporary, sfd, sname)   # rien n'a eu lieu : la source retrouve sa place
                        except OSError:
                            pass
                        raise
                    if temporary is not None:   # l'ancien contenu de l'arrivée rejoint ses versions
                        try:
                            versions.keep(app, target['id'], arrival, dfd, temporary, session['name'])
                        except Exception:
                            aside(app, dfd, temporary, dfd, dname)
            except OSError as error:
                if error.errno == errno.EXDEV:
                    raise app.Problem('Ces deux espaces ne sont pas sur le même volume : copiez puis supprimez.', 502) from None
                raise
            os.fsync(dfd)
    if move and same and there is None:
        versions.moved(app, source['id'], origin, arrival)
    noted(app, session)
    return send(handler, 201 if there is None else 204)


def handle(app, handler, method):
    """Point d'entrée de toute requête sous /dav/. Aucun droit avant l'authentification, et aucun après un refus."""
    app.ACTOR.session = dict(devices.DENIED)
    handler.started = False
    # Corps annoncé et pas encore lu : après un refus, la connexion est fermée pour qu'il ne passe pas pour la requête suivante.
    handler.unread = bool(handler.headers.get('Transfer-Encoding')) or (handler.headers.get('Content-Length') or '0').strip() not in ('', '0')
    if handler.unread and method not in ('PROPFIND', 'PUT'):
        handler.close_connection = True   # seuls PROPFIND et PUT lisent un corps : ailleurs il ne sera jamais lu, la connexion s'arrête là
    try:
        if not handler.allowed_host():
            raise app.Problem('Hôte non autorisé.', 403)
        from updates import maintenance
        if maintenance(app):
            problem = app.Problem('Nacre se met à jour. Réessayer dans un instant.', 503)
            problem.retry = 30
            raise problem
        path = unquote(urlsplit(handler.path).path, errors='strict')
        if path != '/dav' and not path.startswith('/dav/'):
            raise app.Problem('Ressource inconnue.', 404)
        session = devices.authenticate(app, handler)
        app.ACTOR.session = session
        segments = [part for part in path[4:].split('/') if part]
        if method == 'OPTIONS':
            return send(handler, 200, b'', headers={'DAV': '1', 'Allow': ', '.join(READ + WRITE), 'MS-Author-Via': 'DAV'})
        if method == 'PROPFIND':
            return propfind(app, handler, session, segments)
        if method in ('GET', 'HEAD'):
            return get(app, handler, session, segments)
        if method == 'PUT':
            return put(app, handler, session, segments)
        if method == 'MKCOL':
            return mkcol(app, handler, session, segments)
        if method == 'DELETE':
            return delete(app, handler, session, segments)
        if method in ('MOVE', 'COPY'):
            return transfer(app, handler, session, segments, method == 'MOVE')
        raise app.Problem('Méthode non prise en charge.', 405)
    except app.Problem as problem:
        headers = dict(getattr(problem, 'headers', {}))
        if getattr(problem, 'challenge', False):
            headers['WWW-Authenticate'] = 'Basic realm="Nacre", charset="UTF-8"'
        if getattr(problem, 'retry', None):
            headers['Retry-After'] = str(problem.retry)
        if problem.status == 405:
            headers['Allow'] = ', '.join(READ + WRITE)
        refuse(handler, problem.status, getattr(problem, 'xml', None) or problem.message, headers, bool(getattr(problem, 'xml', None)))
    except (FileNotFoundError, NotADirectoryError):
        refuse(handler, 404, 'Fichier ou dossier introuvable.')
    except FileExistsError:
        refuse(handler, 412, 'Ce nom vient d’être pris. Rien n’a été remplacé.')
    except (BrokenPipeError, ConnectionResetError):
        handler.close_connection = True
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        refuse(handler, 400, 'Requête invalide.')
    except OSError:
        refuse(handler, 503, 'Espace momentanément indisponible.')
    except Exception:
        # Rien d'inattendu ne doit laisser un appareil sans réponse, ni dire ce qui s'est passé.
        handler.close_connection = True
        refuse(handler, 500, 'Erreur interne.')
    finally:
        app.ACTOR.session = dict(devices.DENIED)
        handler.expects = False
        if getattr(handler, 'unread', False):
            handler.close_connection = True   # corps jamais lu, même après une réussite : il ne doit pas passer pour la requête suivante


def refuse(handler, status, text, headers=None, xml=False):
    if getattr(handler, 'unread', False) or getattr(handler, 'started', False):
        handler.close_connection = True
    if getattr(handler, 'started', False):
        return   # une réponse est déjà en route : on ferme, sans en écrire une seconde au milieu
    try:
        send(handler, status, text, 'application/xml; charset=utf-8' if xml else 'text/plain; charset=utf-8', headers)
    except (BrokenPipeError, ConnectionResetError):
        handler.close_connection = True
