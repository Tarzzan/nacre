"""Recherche dans le contenu : retrouver un document par ce qu'il dit, pas seulement par son nom.

Un index plein texte, à part de la base de Nacre et reconstructible, garde le texte des documents des espaces. Il
est commun ; la réponse ne l'est jamais : chacun ne trouve que dans les espaces qu'il peut lire. Le texte est tiré
des fichiers sans jamais les interpréter : pas de macro, pas d'entité, pas de lien suivi, et des plafonds partout.
"""
import html
import os
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import zipfile

import library

VERSION = 1
SCHEMA = '''
CREATE TABLE docs(id INTEGER PRIMARY KEY, area TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
  state TEXT NOT NULL, UNIQUE(area, path));
CREATE VIRTUAL TABLE texts USING fts5(name, body, tokenize="unicode61 remove_diacritics 2");
'''
PLAIN = ('.txt', '.md', '.csv', '.log', '.json', '.yaml', '.yml', '.ini', '.conf', '.tex', '.rst', '.srt')
MARKUP = ('.html', '.htm', '.xml')
PACKED = {'.docx': (('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml'), ('word/header', 'word/footer')), '.xlsx': (('xl/sharedStrings.xml',), ()),
          '.pptx': ((), ('ppt/slides/slide', 'ppt/notesSlides/notesSlide')), '.odt': (('content.xml',), ()), '.ods': (('content.xml',), ()), '.odp': (('content.xml',), ())}
PDF = '.pdf'
KINDS = PLAIN + MARKUP + tuple(PACKED) + (PDF,)
TEXT_MAX = 2 * 1024 ** 2          # un fichier texte plus gros n'est pas un document à lire
FILE_MAX = 64 * 1024 ** 2         # document bureautique ou PDF
MEMBER_MAX = 16 * 1024 ** 2       # partie décompressée d'un document
BODY_MAX = 300_000                # caractères gardés par document
RESULTS = 50
QUERY = 80
PAGES = 60
SECONDS = 30
WORD = re.compile(r'[^\W_]+')
DECLARATION = re.compile(r'<![^<>]*>')
TAG = re.compile(r'<(/?)(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)[^<>]*>')
# Balises après lesquelles deux mots ne se touchent pas ; les autres tombent sans laisser d'espace, un mot pouvant être coupé par sa mise en forme.
BREAKS = frozenset(('p', 'h', 'br', 'tab', 'line-break', 's', 'tc', 'table-cell', 'si', 'tr', 'row', 'table-row', 'li', 'div', 'title', 'td', 'th', 'cr',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'list-item', 'sp', 'txBody', 'note'))


def without(text, start, end):
    """Retire chaque passage de `start` à `end`, d'un seul balayage ; un passage jamais refermé emporte la fin."""
    out, at = [], 0
    while True:
        found = text.find(start, at)
        if found < 0:
            out.append(text[at:])
            break
        out.append(text[at:found])
        out.append(' ')
        close = text.find(end, found + len(start))
        if close < 0:
            break
        at = close + len(end)
    return ''.join(out)


def plain(markup, page=False):
    """Texte d'un balisage, sans l'interpréter : aucune entité déclarée n'est développée, aucun script n'est lu."""
    text = without(without(markup, '<!--', '-->'), '<?', '?>')
    if page:
        lowered = text.lower()
        for name in ('script', 'style'):
            # Les positions se cherchent dans la version en minuscules, de même longueur.
            kept, at = [], 0
            while True:
                found = lowered.find('<' + name, at)
                if found < 0:
                    kept.append(text[at:])
                    break
                kept.append(text[at:found])
                close = lowered.find('</' + name, found)
                if close < 0:
                    break
                at = close
            text = ' '.join(kept)
            lowered = text.lower()
    text = text.replace('<![CDATA[', ' ').replace(']]>', ' ')
    text = DECLARATION.sub(' ', text)
    text = TAG.sub(lambda match: ' ' if match[2] in BREAKS else '', text)
    return html.unescape(text.replace('<', ' ').replace('>', ' '))


def decode(raw):
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode('utf-8', 'replace')
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', 'replace')
    if b'\x00' in raw[:8192]:
        return None   # binaire
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp1252', 'replace')


def order(name):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', name)]


def packed(source, exact, prefixes):
    """Texte des parties utiles d'un document compressé, sous plafonds : un fichier piégé ne coûte ni mémoire ni temps."""
    out, budget, size = [], MEMBER_MAX * 2, 0
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 5000:
            return ''
        wanted = [entry for entry in entries if entry.filename in exact or (entry.filename.endswith('.xml') and entry.filename.startswith(prefixes) if prefixes else False)]
        wanted.sort(key=lambda entry: (entry.filename not in exact, order(entry.filename)))
        for entry in wanted[:400]:
            if entry.flag_bits & 0x1 or entry.file_size > MEMBER_MAX:
                continue   # chiffré, ou trop gros pour être du texte
            with archive.open(entry) as member:
                raw = member.read(min(MEMBER_MAX, budget) + 1)   # la lecture s'arrête là, quoi qu'annonce l'en-tête
            if len(raw) > min(MEMBER_MAX, budget):
                break
            budget -= len(raw)
            text = plain(raw.decode('utf-8', 'replace'))
            out.append(text)
            size += len(text)
            if size > BODY_MAX or budget <= 0:
                break
    return ' '.join(out)


def reader():
    return shutil.which('pdftotext')


def pdf(source):
    """Texte d'un PDF par l'outil du système, s'il est là : lu sur son entrée, borné en temps, en mémoire et en pages."""
    tool = reader()
    if not tool:
        return None
    process = subprocess.Popen(['/bin/sh', '-c', 'ulimit -t 20; ulimit -v 1048576; ulimit -f 0; exec "$0" "$@"', tool, '-q', '-l', str(PAGES), '-enc', 'UTF-8', '-nopgbrk', '-', '-'],
                               stdin=source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}, close_fds=True, start_new_session=True)
    try:
        raw, _ = process.communicate(timeout=SECONDS)
    except subprocess.TimeoutExpired:
        # L'outil et tout ce qu'il aurait lancé : rien ne doit survivre au délai.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        return ''
    return raw[:BODY_MAX * 4].decode('utf-8', 'replace') if process.returncode == 0 else ''


def extract(fd, name, kind, info):
    """Texte d'un fichier et ce qu'il en est advenu. Ne lève jamais : un fichier illisible reste trouvable par son nom."""
    try:
        if info.st_size > (TEXT_MAX if kind in PLAIN + MARKUP else FILE_MAX):
            return '', 'big'
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(descriptor, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return '', 'skipped'
            if kind in PLAIN or kind in MARKUP:
                text = decode(source.read(TEXT_MAX + 1))
                if text is None:
                    return '', 'skipped'
                if kind in MARKUP:
                    text = plain(text, page=True)
            elif kind == PDF:
                text = pdf(source)
                if text is None:
                    return '', 'nopdf'
            else:
                text = packed(source, *PACKED[kind])
        body = ' '.join(text.split())[:BODY_MAX]
        return body, 'text' if body else 'empty'
    except Exception:
        return '', 'failed'


def work(app, progress, note):
    """Parcours de fond : ne relit que les documents nouveaux ou changés, oublie ceux qui ont disparu."""
    areas, partial, tool = library.everything(app), None, bool(reader())
    with library.index(app, 'search.db', VERSION, SCHEMA) as db:
        for area in areas:
            known = {row['path']: (row['id'], row['size'], row['mtime_ns'], row['state']) for row in db.execute('SELECT id,path,size,mtime_ns,state FROM docs WHERE area=?', (area,))}
            seen, pending = set(), [0]

            def visit(fd, base, name, info, area=area, known=known, seen=seen, pending=pending):
                kind = os.path.splitext(name)[1].lower()
                if kind not in KINDS:
                    return
                path = '/'.join(base + [name])
                seen.add(path)
                progress['kept'] += 1
                old = known.get(path)
                # Un PDF laissé de côté faute d'outil est repris quand l'outil arrive.
                if old and old[1:3] == (info.st_size, info.st_mtime_ns) and not (old[3] == 'nopdf' and tool):
                    return
                body, state = extract(fd, name, kind, info)
                if old:
                    ident = old[0]
                    db.execute('DELETE FROM texts WHERE rowid=?', (ident,))
                    db.execute('UPDATE docs SET name=?,size=?,mtime_ns=?,state=? WHERE id=?', (name, info.st_size, info.st_mtime_ns, state, ident))
                else:
                    ident = db.execute('INSERT INTO docs(area,path,name,size,mtime_ns,state) VALUES(?,?,?,?,?,?)', (area, path, name, info.st_size, info.st_mtime_ns, state)).lastrowid
                # Le nom est indexé même sans texte : un document illisible reste trouvable par son nom.
                db.execute('INSERT INTO texts(rowid,name,body) VALUES(?,?,?)', (ident, name, body))
                pending[0] += 1
                if pending[0] % 40 == 0:
                    db.commit()
                    note(progress)

            complete = True
            try:
                with app.folder(area, '') as fd:
                    library.walk(fd, [], progress, visit)
            except library.Stop as stop:
                partial, complete = str(stop), False
            except (app.Problem, OSError):
                complete = False   # espace indisponible : ce qu'on en savait est gardé
            if complete:
                for path, value in known.items():
                    if path not in seen:
                        db.execute('DELETE FROM texts WHERE rowid=?', (value[0],))
                        db.execute('DELETE FROM docs WHERE id=?', (value[0],))
            db.commit()
            note(progress)
            if partial:
                break
        if not partial:
            for row in db.execute('SELECT DISTINCT area FROM docs').fetchall():
                if row['area'] not in areas:
                    db.execute('DELETE FROM texts WHERE rowid IN (SELECT id FROM docs WHERE area=?)', (row['area'],))
                    db.execute('DELETE FROM docs WHERE area=?', (row['area'],))
    return partial


SCAN = library.Scanner(work)


def terms(text):
    """Mots cherchés : lettres et chiffres seulement, rien qui puisse devenir un opérateur de la recherche."""
    return [word for word in WORD.findall(text)[:8] if len(word) >= 2 or word.isdigit()]


def search(app, query, session):
    """Documents dont le texte contient tous les mots, les plus pertinents d'abord, dans les seuls espaces de la session."""
    text, chosen = query.get('q', ''), query.get('area') or None
    if not isinstance(text, str) or len(text) > QUERY:
        raise app.Problem('Recherche trop longue.')
    words = terms(text)
    if not words or sum(len(word) for word in words) < 2:
        raise app.Problem('Saisir au moins deux caractères à chercher dans les documents.')
    areas = library.visible(app, session)
    names = [area['id'] for area in areas]
    if chosen is not None and chosen not in names:
        raise app.Problem('Accès refusé à cet espace.', 403)
    allowed = [chosen] if chosen else names[:900]
    started = SCAN.ensure(app)
    marks = ','.join('?' * len(allowed))
    try:
        with library.index(app, 'search.db', VERSION, SCHEMA) as db:
            if allowed:
                # Chaque mot est cherché comme début de mot ; le nom du fichier pèse plus que son texte.
                rows = db.execute(f'SELECT d.area,d.path,d.name,d.size,d.mtime_ns,snippet(texts,1,?,?,?,18) AS extract FROM texts JOIN docs d ON d.id=texts.rowid '
                                  f'WHERE texts MATCH ? AND d.area IN ({marks}) ORDER BY bm25(texts,6.0,1.0) LIMIT ?',
                                  ['\x02', '\x03', ' … ', ' '.join(f'"{word}"*' for word in words), *allowed, RESULTS + 1]).fetchall()
                read = db.execute(f"SELECT count(*) FROM docs WHERE state='text' AND area IN ({marks})", allowed).fetchone()[0]
            else:
                rows, read = [], 0
    except sqlite3.OperationalError as failure:
        if 'fts5' in str(failure).lower():
            raise app.Problem('La recherche dans le contenu n’est pas disponible sur ce système : son moteur de base de données ne sait pas indexer du texte.', 501) from None
        raise
    items = []
    for row in rows[:RESULTS]:
        folder, _, _ = row['path'].rpartition('/')
        items.append({'area': row['area'], 'path': folder, 'name': row['name'], 'directory': False, 'link': False, 'size': row['size'], 'modified': row['mtime_ns'] / 1e9,
                      'extract': row['extract']})
    return {'query': text, 'words': words, 'items': items, 'partial': len(rows) > RESULTS, 'limit': RESULTS, 'read': read, 'pdf': bool(reader()),
            'scan': {**SCAN.status(), 'started_now': started}}
