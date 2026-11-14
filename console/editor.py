"""Éditeur de texte intégré : lire, modifier et enregistrer un fichier texte ou Markdown depuis le navigateur.

Chaque enregistrement remplace le fichier d'un seul tenant et garde l'ancien contenu comme version, sauf quand la
même personne enregistre de nouveau dans les dix minutes : ses enregistrements successifs ne chassent pas les
versions plus anciennes. Un fichier modifié entre l'ouverture et l'enregistrement n'est pas écrasé sans le dire.
"""
import os
import secrets
import stat
import threading
import time

import spaces
import versions

EDIT_MAX = 2 * 1024 ** 2
SAME_SESSION = 600
PRESENCE = 75
OPEN = {}
LOCK = threading.Lock()
NAMES = ('.txt', '.md', '.markdown', '.csv', '.json', '.yml', '.yaml', '.ini', '.conf', '.log', '.xml', '.html', '.css', '.js', '.py', '.sh', '.toml', '.env', '.srt')


def editable(name):
    lowered = name.lower()
    return lowered.endswith(NAMES) or '.' not in lowered.strip('.')


def etag(info):
    return f'{info.st_mtime_ns}-{info.st_size}'


def target(app, body):
    area, path = body.get('area', 'fichiers'), body.get('path')
    if not isinstance(area, str) or not isinstance(path, str) or not app.parts(path):
        raise app.Problem('Choisir un fichier.')
    return area, '/'.join(app.parts(path))


def others(area, path, name, now=None):
    now = time.time() if now is None else now
    with LOCK:
        entry = OPEN.get((area, path), {})
        for person in [p for p, seen in entry.items() if seen < now - PRESENCE]:
            entry.pop(person)
        return sorted(p for p in entry if p != name)


def read(app, query, session):
    """Texte d'un fichier, avec de quoi détecter qu'il a changé avant l'enregistrement."""
    area, path = target(app, query)
    with app.parent(area, path) as (fd, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise app.Problem('Seul un fichier ordinaire s’ouvre dans l’éditeur.')
    with os.fdopen(descriptor, 'rb') as source:
        if info.st_size > EDIT_MAX:
            raise app.Problem('Ce fichier dépasse 2 Mio : il se télécharge, mais ne s’ouvre pas dans l’éditeur.', 413)
        raw = source.read(EDIT_MAX + 1)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise app.Problem('Ce fichier n’est pas un texte lisible (UTF-8) : il ne s’ouvre pas dans l’éditeur.', 415) from None
    if '\x00' in text:
        raise app.Problem('Ce fichier n’est pas un texte lisible : il ne s’ouvre pas dans l’éditeur.', 415)
    return {'area': area, 'path': path, 'name': name, 'text': text, 'etag': etag(info), 'modified': info.st_mtime, 'size': info.st_size,
            'writable': spaces.level(app, session, area) == 'write', 'markdown': name.lower().endswith(('.md', '.markdown')),
            'others': others(area, path, session['name']), 'max': EDIT_MAX}


def recent(app, area, path, actor, now):
    """Vrai si la dernière version de ce fichier vient d'un enregistrement de la même personne, il y a peu."""
    with versions.LOCK, versions.store(app, area) as fd:
        values = versions.load(fd).get(path, []) if fd is not None else []
    last = values[0] if values else None
    return bool(last) and last.get('by') == actor and last.get('editor') is True and now - (last.get('ts') or 0) < SAME_SESSION


def save(app, body, session, now=None):
    now = time.time() if now is None else now
    area, path = target(app, body)
    text, known, actor = body.get('text'), body.get('etag'), session['name']
    if not isinstance(text, str) or '\x00' in text:
        raise app.Problem('Texte invalide.')
    raw = text.encode('utf-8')
    if len(raw) > EDIT_MAX:
        raise app.Problem('Ce texte dépasse 2 Mio : enregistrez-le en plusieurs fichiers.', 413)
    with app.parent(area, path, write=True) as (fd, name):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise app.Problem('Seul un fichier ordinaire s’enregistre depuis l’éditeur.')
        unchanged = etag(info) == known
        if not unchanged and body.get('force') is not True:
            raise app.Problem('Ce fichier a changé depuis que vous l’avez ouvert. Rien n’a été enregistré.', 409)
        if len(raw) > app.available_bytes(fd):
            raise app.Problem('Espace physique insuffisant sur le volume.', 507)
        temporary = '.nacre-upload-' + secrets.token_hex(12)
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
        try:
            with os.fdopen(out, 'wb') as output:
                os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            versions.exchange(fd, temporary, fd, name)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
        # L'ancien contenu est maintenant sous le nom temporaire : il devient une version, ou s'efface derrière la précédente.
        try:
            # Regroupement seulement si le contenu remplacé est bien celui que cette personne avait sous les yeux :
            # un contenu venu d'ailleurs entre-temps est toujours gardé.
            if unchanged and recent(app, area, path, actor, now):
                os.unlink(temporary, dir_fd=fd)
            else:
                ident = versions.keep(app, area, path, fd, temporary, actor, now)
                mark(app, area, path, ident)
        except Exception:
            app.rename_noreplace(fd, temporary, fd, f'{name}.avant-enregistrement-{secrets.token_hex(3)}')
        os.fsync(fd)
        fresh = os.stat(name, dir_fd=fd, follow_symlinks=False)
    app.audit(actor, 'Fichier enregistré depuis l’éditeur', spaces.detail(app, area, path) if area.startswith('espace_') else area + ': ' + path)
    return {'ok': True, 'etag': etag(fresh), 'modified': fresh.st_mtime, 'size': fresh.st_size}


def mark(app, area, path, ident):
    """Note qu'une version vient de l'éditeur, pour regrouper les enregistrements rapprochés d'une même personne."""
    with versions.LOCK, versions.store(app, area, create=True) as fd:
        index = versions.load(fd)
        for value in index.get(path, []):
            if value['id'] == ident:
                value['editor'] = True
        versions.save(fd, index)


def create(app, body, session):
    """Nouveau document vide dans un dossier. Un nom déjà pris est refusé : rien n'est remplacé."""
    area, folder = body.get('area', 'fichiers'), body.get('path', '')
    name = app.safe_name(body.get('name'))
    if not isinstance(area, str) or not isinstance(folder, str) or not editable(name):
        raise app.Problem('Nom de document invalide : terminez-le par .md ou .txt.')
    with app.folder(area, folder, write=True) as fd:
        if name in os.listdir(fd):
            raise FileExistsError()
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
        os.fchmod(out, 0o660)
        os.close(out)
        os.fsync(fd)
    path = '/'.join(app.parts(folder) + [name])
    app.audit(session['name'], 'Document créé', spaces.detail(app, area, path) if area.startswith('espace_') else area + ': ' + path)
    return {'ok': True, 'path': path}


def presence(app, body, session, now=None):
    """Signale qu'un fichier est ouvert dans l'éditeur, ou qu'il vient d'être fermé. Simple information, jamais un verrou."""
    now = time.time() if now is None else now
    area, path = target(app, body)
    app.resolve_area(area)   # les droits de la session s'appliquent
    with LOCK:
        entry = OPEN.setdefault((area, path), {})
        if body.get('open') is False:
            entry.pop(session['name'], None)
        else:
            entry[session['name']] = now
        if not entry:
            OPEN.pop((area, path), None)
        if len(OPEN) > 5000:
            OPEN.clear()
    return {'others': others(area, path, session['name'], now)}
