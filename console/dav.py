"""WebDAV : les fichiers des espaces, pour les outils et les appareils, sous /dav/.

Chaque requête commence sans aucun droit, puis prend ceux de l'appareil qui s'annonce (voir devices.py). Les fichiers
passent par les mêmes portes que la console : un espace n'est ouvert que si la personne y a droit, aucun lien n'est
suivi, les dossiers internes ne se voient pas. Une erreur n'est jamais déguisée en dossier vide : un outil de
synchronisation y lirait « tout a été supprimé ».

L'arborescence réserve dès maintenant la place des autres services :
  /dav/files/<espace>/…      les fichiers (ce module)
  /dav/principals/, /dav/calendars/, /dav/addressbooks/   à venir
"""
import email.utils
import errno
import mimetypes
import os
import re
import stat
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


def handle(app, handler, method):
    """Point d'entrée de toute requête sous /dav/. Aucun droit avant l'authentification, et aucun après un refus."""
    app.ACTOR.session = dict(devices.DENIED)
    handler.started = False
    # Corps annoncé et pas encore lu : après un refus, la connexion est fermée pour qu'il ne passe pas pour la requête suivante.
    handler.unread = bool(handler.headers.get('Transfer-Encoding')) or (handler.headers.get('Content-Length') or '0').strip() not in ('', '0')
    if handler.unread and method != 'PROPFIND':
        handler.close_connection = True   # seul PROPFIND lit un corps : ailleurs il ne sera jamais lu, la connexion s'arrête là
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
            return send(handler, 200, b'', headers={'DAV': '1', 'Allow': ', '.join(READ), 'MS-Author-Via': 'DAV'})
        if method == 'PROPFIND':
            return propfind(app, handler, session, segments)
        if method in ('GET', 'HEAD'):
            return get(app, handler, session, segments)
        raise app.Problem('Méthode non prise en charge.', 405)
    except app.Problem as problem:
        headers = dict(getattr(problem, 'headers', {}))
        if getattr(problem, 'challenge', False):
            headers['WWW-Authenticate'] = 'Basic realm="Nacre", charset="UTF-8"'
        if getattr(problem, 'retry', None):
            headers['Retry-After'] = str(problem.retry)
        if problem.status == 405:
            headers['Allow'] = ', '.join(READ)
        refuse(handler, problem.status, getattr(problem, 'xml', None) or problem.message, headers, bool(getattr(problem, 'xml', None)))
    except (FileNotFoundError, NotADirectoryError):
        refuse(handler, 404, 'Fichier ou dossier introuvable.')
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
