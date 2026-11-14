"""Photos : les images de tous les espaces qu'une personne peut lire, réunies par date.

Rien n'est copié ni transformé. L'index note, pour chaque image, sa date de prise de vue (lue dans le fichier, sinon
sa date de modification), son orientation et l'emplacement de la vignette que l'appareil photo y a glissée ; cette
vignette est servie telle quelle, relue dans le fichier d'origine. Aucune bibliothèque d'images n'est requise.
"""
import os
import re
import stat
import time
from datetime import datetime

import library
import spaces

VERSION = 1
SCHEMA = '''
CREATE TABLE photos(area TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
  taken TEXT NOT NULL, dated INTEGER NOT NULL, orient INTEGER NOT NULL, thumb_at INTEGER NOT NULL, thumb_len INTEGER NOT NULL,
  width INTEGER, height INTEGER, model TEXT, PRIMARY KEY(area, path));
CREATE INDEX photos_taken ON photos(taken DESC);
'''
SHOWN = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')          # ce qu'un navigateur affiche
SENT = SHOWN + ('.heic', '.heif', '.mp4', '.mov', '.webm')          # ce qu'un téléphone envoie
HEAD = 256 * 1024
THUMB = 64 * 1024
PAGE = 120
PLAN = 200
CURSOR = re.compile(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)~(\d{1,18})\Z')
STAMP = re.compile(r'(\d{4}):(\d\d):(\d\d) (\d\d):(\d\d):(\d\d)')
FRAMES = tuple(marker for marker in range(0xC0, 0xD0) if marker not in (0xC4, 0xC8, 0xCC))


def empty():
    return {'taken': None, 'orient': 1, 'thumb_at': 0, 'thumb_len': 0, 'width': None, 'height': None, 'model': None}


def tiff(data, base, out):
    """Bloc EXIF : date de prise de vue, orientation, appareil, et la vignette, repérée par sa place dans le fichier."""
    if len(data) < 8:
        return
    order = {b'II': 'little', b'MM': 'big'}.get(bytes(data[:2]))
    if not order or int.from_bytes(data[2:4], order) != 42:
        return

    def directory(offset):
        entries = {}
        if offset <= 0 or offset + 2 > len(data):
            return entries, 0
        count = int.from_bytes(data[offset:offset + 2], order)
        if count > 256:
            return entries, 0
        for index in range(count):
            at = offset + 2 + 12 * index
            if at + 12 > len(data):
                return entries, 0
            entries[int.from_bytes(data[at:at + 2], order)] = (int.from_bytes(data[at + 2:at + 4], order), int.from_bytes(data[at + 4:at + 8], order), data[at + 8:at + 12])
        end = offset + 2 + 12 * count
        return entries, int.from_bytes(data[end:end + 4], order) if end + 4 <= len(data) else 0

    def number(entry):
        if not entry or entry[1] != 1 or entry[0] not in (3, 4):
            return None
        return int.from_bytes(entry[2][:2] if entry[0] == 3 else entry[2], order)

    def text(entry):
        if not entry or entry[0] != 2 or not 0 < entry[1] <= 64:
            return None
        at = int.from_bytes(entry[2], order)
        chunk = entry[2][:entry[1]] if entry[1] <= 4 else data[at:at + entry[1]]
        return bytes(chunk).split(b'\x00')[0].decode('ascii', 'replace').strip()

    first, second = directory(int.from_bytes(data[4:8], order))
    detail = directory(number(first.get(0x8769)) or 0)[0]
    turn = number(first.get(0x0112))
    if turn in range(1, 9):
        out['orient'] = turn
    model = text(first.get(0x0110))
    if model:
        out['model'] = ''.join(c for c in model if c.isprintable() and c not in '<>&"\'')[:40] or None
    for candidate in (detail.get(0x9003), detail.get(0x9004), first.get(0x0132)):
        found = STAMP.fullmatch(text(candidate) or '')
        if found:
            try:
                when = datetime(*(int(part) for part in found.groups()))
            except ValueError:
                continue
            if 1990 <= when.year <= 2100:
                out['taken'] = when.strftime('%Y-%m-%dT%H:%M:%S')
                break
    wide, high = number(detail.get(0xA002)), number(detail.get(0xA003))
    if wide and high and wide < 1 << 20 and high < 1 << 20:
        out['width'], out['height'] = wide, high
    small = directory(second)[0]
    at, length = number(small.get(0x0201)), number(small.get(0x0202))
    # La vignette n'est retenue que si elle tient dans ce qui a été lu et commence comme un JPEG.
    if at and length and 4 < length <= THUMB and at + length <= len(data) and data[at:at + 2] == b'\xff\xd8':
        out['thumb_at'], out['thumb_len'] = base + at, length


def describe(head):
    """Ce que dit le début d'un fichier image. Ne décode aucune image ; ne lève jamais : un fichier abîmé reste une photo sans date."""
    out = empty()
    try:
        if head[:2] == b'\xff\xd8':
            at = 2
            while at + 4 <= len(head) and head[at] == 0xFF:
                marker = head[at + 1]
                if marker == 0xFF:
                    at += 1
                    continue
                if marker == 0x01 or 0xD0 <= marker <= 0xD8:
                    at += 2
                    continue
                if marker in (0xD9, 0xDA):
                    break
                length = int.from_bytes(head[at + 2:at + 4], 'big')
                if length < 2:
                    break
                body = head[at + 4:at + 2 + length]
                if marker == 0xE1 and body[:6] == b'Exif\x00\x00' and out['taken'] is None and not out['thumb_len']:
                    tiff(body[6:], at + 10, out)
                elif marker in FRAMES and len(body) >= 5:
                    if out['width'] is None:
                        out['height'], out['width'] = int.from_bytes(body[1:3], 'big'), int.from_bytes(body[3:5], 'big')
                    break
                at += 2 + length
        elif head[:8] == b'\x89PNG\r\n\x1a\n' and head[12:16] == b'IHDR':
            out['width'], out['height'] = int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')
        elif head[:6] in (b'GIF87a', b'GIF89a') and len(head) >= 10:
            out['width'], out['height'] = int.from_bytes(head[6:8], 'little'), int.from_bytes(head[8:10], 'little')
    except Exception:
        return empty()
    return out


def work(app, progress, note):
    """Parcours de fond : n'ouvre que les images nouvelles ou changées, oublie celles qui ont disparu."""
    where = library.zone(app)
    areas, partial = library.everything(app), None
    with library.index(app, 'photos.db', VERSION, SCHEMA) as db:
        for area in areas:
            known = {row['path']: (row['size'], row['mtime_ns']) for row in db.execute('SELECT path,size,mtime_ns FROM photos WHERE area=?', (area,))}
            pending, seen = [], set()

            def flush():
                if pending:
                    db.executemany('INSERT INTO photos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(area,path) DO UPDATE SET name=excluded.name,size=excluded.size,'
                                   'mtime_ns=excluded.mtime_ns,taken=excluded.taken,dated=excluded.dated,orient=excluded.orient,thumb_at=excluded.thumb_at,'
                                   'thumb_len=excluded.thumb_len,width=excluded.width,height=excluded.height,model=excluded.model', pending)
                    pending.clear()
                    db.commit()
                note(progress)

            def visit(fd, base, name, info, area=area, known=known, pending=pending, seen=seen):
                if not name.lower().endswith(SHOWN):
                    return
                path = '/'.join(base + [name])
                progress['kept'] += 1
                seen.add(path)
                if known.get(path) != (info.st_size, info.st_mtime_ns):
                    try:
                        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                        with os.fdopen(descriptor, 'rb') as source:
                            head = source.read(HEAD) if stat.S_ISREG(os.fstat(source.fileno()).st_mode) else b''
                    except OSError:
                        return
                    found = describe(head)
                    pending.append((area, path, name, info.st_size, info.st_mtime_ns, found['taken'] or library.local(info.st_mtime, where), int(bool(found['taken'])),
                                    found['orient'], found['thumb_at'], found['thumb_len'], found['width'], found['height'], found['model']))
                if len(pending) >= 200 or progress['kept'] % 1000 == 0:
                    flush()

            complete = True
            try:
                with app.folder(area, '') as fd:
                    library.walk(fd, [], progress, visit)
            except library.Stop as stop:
                partial, complete = str(stop), False
            except (app.Problem, OSError):
                complete = False   # espace indisponible : ce qu'on en savait est gardé
            flush()
            if complete:
                gone = [(area, path) for path in known if path not in seen]
                for start in range(0, len(gone), 500):
                    db.executemany('DELETE FROM photos WHERE area=? AND path=?', gone[start:start + 500])
                db.commit()
            if partial:
                break
        if not partial:
            # Espaces supprimés depuis le dernier parcours.
            for row in db.execute('SELECT DISTINCT area FROM photos').fetchall():
                if row['area'] not in areas:
                    db.execute('DELETE FROM photos WHERE area=?', (row['area'],))
    return partial


SCAN = library.Scanner(work)


def listing(app, query, session):
    """Une page de photos, des plus récentes aux plus anciennes, limitée aux espaces que la session peut lire."""
    areas = library.visible(app, session)
    names = {area['id']: area['name'] for area in areas}
    chosen = query.get('area') or None
    if chosen is not None and chosen not in names:
        raise app.Problem('Accès refusé à cet espace.', 403)
    allowed = [chosen] if chosen else list(names)[:900]
    before = query.get('before') or None
    cursor = CURSOR.fullmatch(before) if isinstance(before, str) else None
    if before is not None and not cursor:
        raise app.Problem('Suite de liste invalide.')
    started = SCAN.ensure(app)
    marks = ','.join('?' * len(allowed))
    with library.index(app, 'photos.db', VERSION, SCHEMA) as db:
        if not allowed:
            rows, total, months = [], 0, []
        else:
            where, values = f'area IN ({marks})', list(allowed)
            if cursor:
                where += ' AND (taken<? OR (taken=? AND rowid<?))'
                values += [cursor[1], cursor[1], int(cursor[2])]
            rows = db.execute(f'SELECT rowid,* FROM photos WHERE {where} ORDER BY taken DESC, rowid DESC LIMIT ?', values + [PAGE + 1]).fetchall()
            total = months = None
            if not cursor:
                total = db.execute(f'SELECT count(*) FROM photos WHERE area IN ({marks})', allowed).fetchone()[0]
                months = [[row[0], row[1]] for row in db.execute(f'SELECT substr(taken,1,7) m,count(*) FROM photos WHERE area IN ({marks}) GROUP BY m ORDER BY m DESC LIMIT 600', allowed)]
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    result = {'items': [{'area': row['area'], 'path': row['path'], 'name': row['name'], 'size': row['size'], 'taken': row['taken'], 'dated': bool(row['dated']),
                         'orient': row['orient'], 'thumb': row['thumb_len'] > 0, 'v': str(row['mtime_ns']), 'width': row['width'], 'height': row['height'],
                         'model': row['model']} for row in rows],
              'next': f'{rows[-1]["taken"]}~{rows[-1]["rowid"]}' if more else None, 'page': PAGE,
              'areas': [{'id': area['id'], 'name': area['name']} for area in areas], 'scan': {**SCAN.status(), 'started_now': started},
              'personal': session.get('role') in ('admin', 'member')}
    if total is not None:
        result.update(total=total, months=months)
    return result


def thumb(app, handler, query, session):
    """Vignette glissée par l'appareil dans le fichier : relue à sa place, après vérification des droits et que le fichier n'a pas changé."""
    area, path = query.get('area'), query.get('path')
    if not isinstance(area, str) or not isinstance(path, str) or not app.parts(path):
        raise app.Problem('Choisir une photo.')
    path = '/'.join(app.parts(path))
    with app.parent(area, path) as (fd, name):   # les droits de la session sur l'espace sont vérifiés ici
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        with library.index(app, 'photos.db', VERSION, SCHEMA) as db:
            row = db.execute('SELECT size,mtime_ns,thumb_at,thumb_len FROM photos WHERE area=? AND path=?', (area, path)).fetchone()
        if not row or not row['thumb_len'] or not stat.S_ISREG(info.st_mode) or (info.st_size, info.st_mtime_ns) != (row['size'], row['mtime_ns']):
            raise app.Problem('Pas de vignette pour cette photo.', 404)
        data = os.pread(source.fileno(), row['thumb_len'], row['thumb_at'])
    if len(data) != row['thumb_len'] or data[:2] != b'\xff\xd8':
        raise app.Problem('Pas de vignette pour cette photo.', 404)
    handler.send_response(200)
    handler.send_header('Content-Type', 'image/jpeg')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('X-Content-Type-Options', 'nosniff')
    # L'adresse porte la date du fichier : une vignette peut rester dans le navigateur de la personne, jamais ailleurs.
    handler.send_header('Cache-Control', 'private, max-age=604800, immutable' if query.get('v') == str(row['mtime_ns']) else 'no-store')
    handler.end_headers()
    handler.wfile.write(data)


def refresh(app, body, session):
    return {'ok': True, 'started': SCAN.ensure(app, force=True), 'scan': SCAN.status()}


def free(name, taken):
    stem, dot, ext = name.rpartition('.')
    stem, ext = (stem, dot + ext) if dot else (name, '')
    for number in range(2, 200):
        candidate = f'{stem[:170 - len(ext)]} ({number}){ext}'
        if candidate not in taken:
            return candidate
    return None


def plan(app, body, session):
    """Prépare un envoi depuis un appareil : range chaque photo par mois dans l'espace personnel et écarte celles déjà là.

    Une photo de même nom et de même taille dans son dossier est tenue pour déjà envoyée : renvoyer toute sa pellicule
    ne crée pas de doublon. Rien n'est écrit ici, sauf les dossiers ; l'envoi passe ensuite par le dépôt ordinaire.
    """
    mine = spaces.ensure_personal(app, session)
    if not mine:
        raise app.Problem('Ce compte n’a pas d’espace personnel où déposer des photos.', 403)
    area, items = 'espace_' + mine['id'], body.get('items')
    if not isinstance(items, list) or not 0 < len(items) <= PLAN:
        raise app.Problem(f'Envoyer de 1 à {PLAN} photos à la fois.')
    where, now, wanted = library.zone(app), time.time(), []
    for item in items:
        if not isinstance(item, dict):
            raise app.Problem('Liste de photos invalide.')
        name, size, modified = item.get('name'), item.get('size'), item.get('modified')
        if type(size) is not int or not 0 <= size < 1 << 50 or type(modified) not in (int, float):
            raise app.Problem('Liste de photos invalide.')
        if not isinstance(name, str) or not name.lower().endswith(SENT):
            wanted.append((name if isinstance(name, str) else '', size, None))
            continue
        app.safe_name(name)
        seconds = modified / 1000
        month = library.local(seconds if 631152000 <= seconds <= now + 86400 else now, where)[:7]
        wanted.append((name, size, month))
    present, out = {}, []
    with app.folder(area, '', write=True) as root:
        for month in sorted({month for _, _, month in wanted if month}):
            fd = root
            opened = []
            try:
                for part in ('Photos', month):
                    try:
                        os.mkdir(part, mode=0o770, dir_fd=fd)
                        os.chmod(part, 0o2770, dir_fd=fd, follow_symlinks=False)
                    except FileExistsError:
                        pass
                    try:
                        fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except OSError:
                        raise app.Problem(f'« {part} » existe déjà dans votre espace et n’est pas un dossier.', 409) from None
                    opened.append(fd)
                names = {}
                with os.scandir(fd) as entries:
                    for entry in entries:
                        try:
                            names[entry.name] = entry.stat(follow_symlinks=False).st_size if entry.is_file(follow_symlinks=False) else None
                        except OSError:
                            names[entry.name] = None
                present[month] = names
            finally:
                for one in opened:
                    os.close(one)
    for name, size, month in wanted:
        if month is None:
            out.append({'name': name, 'state': 'refused'})
            continue
        names, folder = present[month], f'Photos/{month}'
        stem, dot, ext = name.rpartition('.')
        # Même nom ou l'une de ses variantes numérotées, et même taille : déjà là.
        twins = [other for other, weight in names.items() if weight == size and (other == name or (dot and other.startswith(stem + ' (') and other.endswith(').' + ext)))]
        if twins:
            out.append({'name': name, 'state': 'present', 'path': folder, 'as': twins[0]})
            continue
        target = name if name not in names else free(name, names)
        if target is None:
            out.append({'name': name, 'state': 'refused'})
            continue
        names[target] = size
        out.append({'name': name, 'state': 'send', 'path': folder, 'as': target})
    return {'area': area, 'items': out}
