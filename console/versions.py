"""Versions d'un fichier : ce qu'il contenait avant d'être remplacé, à retrouver ou à remettre en place.

Une version est gardée chaque fois qu'un fichier est remplacé par la console : dépôt d'un fichier du même nom,
enregistrement par l'éditeur, retour à une version plus ancienne. Elle n'est pas une sauvegarde : elle vit sur le
même volume, dans un dossier interne de l'espace, et les plus anciennes sont retirées au-delà d'un nombre fixe.
Un fichier modifié par le réseau (SMB) n'y laisse aucune trace : la console ne voit pas ce changement.
"""
import ctypes
import errno
import json
import os
import re
import secrets
import shutil
import stat
import threading
import time
from contextlib import contextmanager
from urllib.parse import quote

STORE = '.nacre-versions'
INDEX = 'index.json'
KEEP = 10
SHELF = '.nacre-trash/'                       # versions d'un élément en corbeille : clé réservée, suivie de l'identifiant de sa ligne
SHELVED = re.compile(r'[a-f0-9]{32}\Z')
LOCK = threading.RLock()


def exchange(source_fd, source, target_fd, target):
    """Échange deux noms d'un coup : à aucun instant le fichier n'est absent."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), 2):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


@contextmanager
def store(app, area, create=False):
    """Dossier interne des versions d'un espace, ou None s'il n'existe pas et n'est pas à créer."""
    resource = app.resolve_area(area, create)   # les droits de la session s'appliquent ici
    if area == 'fichiers':
        base, name = app.ROOT / 'data', '.versions'
    else:
        base, name = resource['path'], STORE
    base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=base_fd)
            except FileExistsError:
                pass
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd)
        except FileNotFoundError:
            yield None
            return
    finally:
        os.close(base_fd)
    try:
        meta = os.fstat(fd)
        if meta.st_uid != os.getuid() or meta.st_mode & 0o077:
            raise app.Problem('Le dossier des versions de cet espace n’est pas privé.', 403)
        yield fd
    finally:
        os.close(fd)


def load(fd):
    try:
        with open(os.open(INDEX, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd), 'rb') as source:
            doc = json.load(source)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return {path: [v for v in values if isinstance(v, dict) and isinstance(v.get('id'), str)] for path, values in doc.items()
            if isinstance(path, str) and isinstance(values, list)} if isinstance(doc, dict) else {}


def save(fd, index):
    temporary = '.index-' + secrets.token_hex(6)
    out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(out, 'w') as output:
        json.dump({path: values for path, values in index.items() if values}, output)
        output.flush()
        os.fsync(output.fileno())
    os.rename(temporary, INDEX, src_dir_fd=fd, dst_dir_fd=fd)


def key(app, path):
    return '/'.join(app.parts(path))


def keep(app, area, path, parent_fd, name, actor, now=None):
    """Range le fichier `name` du dossier ouvert parmi les versions de `path`. Les plus anciennes au-delà de KEEP sont retirées."""
    now = time.time() if now is None else now
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise app.Problem('Seul un fichier ordinaire garde des versions.', 409)
    ident = secrets.token_hex(12)
    with LOCK, store(app, area, create=True) as fd:
        try:
            os.rename(name, ident, src_dir_fd=parent_fd, dst_dir_fd=fd)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            # Volume différent : la version est copiée puis l'original retiré.
            with open(os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd), 'rb') as source, \
                    open(os.open(ident, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd), 'wb') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            os.unlink(name, dir_fd=parent_fd)
        index = load(fd)
        values = index.setdefault(key(app, path), [])
        values.insert(0, {'id': ident, 'ts': now, 'modified': info.st_mtime, 'size': info.st_size, 'by': actor})
        for old in values[KEEP:]:
            try:
                os.unlink(old['id'], dir_fd=fd)
            except FileNotFoundError:
                pass
        del values[KEEP:]
        save(fd, index)
    return ident


def listing(app, area, path):
    """Versions gardées d'un fichier, de la plus récente à la plus ancienne."""
    with LOCK, store(app, area) as fd:
        values = load(fd).get(key(app, path), []) if fd is not None else []
    return {'area': area, 'path': key(app, path), 'keep': KEEP,
            'versions': [{'id': v['id'], 'ts': v.get('ts'), 'modified': v.get('modified'), 'size': v.get('size'), 'by': v.get('by', '')} for v in values]}


def find(app, fd, path, ident):
    values = load(fd).get(key(app, path), []) if fd is not None else []
    match = next((v for v in values if v['id'] == ident), None) if isinstance(ident, str) else None
    if not match:
        raise app.Problem('Version inconnue pour ce fichier.', 404)
    return match


def send(app, handler, query):
    """Téléchargement d'une version, sous le nom du fichier précédé de sa date."""
    area, path = query.get('area', 'fichiers'), query.get('path', '')
    with LOCK, store(app, area) as fd:
        match = find(app, fd, path, query.get('id'))
        descriptor = os.open(match['id'], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(descriptor, 'rb') as source:
        size = os.fstat(source.fileno()).st_size
        name = key(app, path).rsplit('/', 1)[-1]
        stem, dot, suffix = name.rpartition('.')
        dated = time.strftime('%Y%m%d-%H%M%S', time.localtime(match.get('ts') or 0))
        label = f'{stem} (version du {dated}).{suffix}' if dot and stem else f'{name} (version du {dated})'
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/octet-stream')
        handler.send_header('Content-Length', str(size))
        handler.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(label))
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        shutil.copyfileobj(source, handler.wfile, 256 * 1024)


def restore(app, body, actor):
    """Remet une version en place. Le contenu actuel devient à son tour une version : le retour se défait."""
    area, path, ident = body.get('area', 'fichiers'), body.get('path'), body.get('id')
    if not isinstance(path, str) or not app.parts(path):
        raise app.Problem('Choisir un fichier.')
    with LOCK:
        with app.parent(area, path, write=True) as (parent_fd, name), store(app, area, create=True) as fd:
            match = find(app, fd, path, ident)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode):
                raise app.Problem('Seul un fichier ordinaire se remet à une version.', 409)
            temporary = '.nacre-upload-' + secrets.token_hex(12)
            os.rename(match['id'], temporary, src_dir_fd=fd, dst_dir_fd=parent_fd)
            try:
                exchange(parent_fd, temporary, parent_fd, name)
            except OSError:
                os.rename(temporary, match['id'], src_dir_fd=parent_fd, dst_dir_fd=fd)
                raise
            index = load(fd)
            index[key(app, path)] = [v for v in index.get(key(app, path), []) if v['id'] != match['id']]
            save(fd, index)
            keep(app, area, path, parent_fd, temporary, actor)
            os.fsync(parent_fd)
    import spaces
    app.audit(actor, 'Version remise en place', spaces.detail(app, area, key(app, path)) if area.startswith('espace_') else area + ': ' + key(app, path))
    return {'ok': True}


def delete(app, body, actor):
    """Retire une version pour libérer de la place. Le fichier lui-même n'est pas touché."""
    area, path, ident = body.get('area', 'fichiers'), body.get('path'), body.get('id')
    if not isinstance(path, str) or not app.parts(path) or body.get('confirm') is not True:
        raise app.Problem('Confirmation requise pour retirer une version.')
    with LOCK, store(app, area, create=True) as fd:
        match = find(app, fd, path, ident)
        index = load(fd)
        index[key(app, path)] = [v for v in index.get(key(app, path), []) if v['id'] != match['id']]
        save(fd, index)
        try:
            os.unlink(match['id'], dir_fd=fd)
        except FileNotFoundError:
            pass
    import spaces
    app.audit(actor, 'Version retirée', spaces.detail(app, area, key(app, path)) if area.startswith('espace_') else area + ': ' + key(app, path))
    return {'ok': True}


def rekey(app, area, old, new):
    """Range sous `new` les versions gardées sous `old` et sous ce qu'il contient. Rend le nombre de fichiers concernés."""
    if not old or not new:
        return 0
    with LOCK, store(app, area) as fd:
        if fd is None:
            return 0
        index = load(fd)
        found = {name: values for name, values in index.items() if values and (name == old or name.startswith(old + '/'))}
        for name, values in found.items():
            del index[name]
            target = new + name[len(old):]
            index[target] = sorted(index.get(target, []) + values, key=lambda v: v.get('ts') or 0, reverse=True)
        if found:
            save(fd, index)
    return len(found)


def shelve(app, area, path, ident):
    """Mise en corbeille : les versions de l'élément, et de ce qu'il contient, le suivent sous une clé propre à sa ligne.

    Un fichier créé ensuite sous le même nom commence donc sans versions, et retirer l'élément pour de bon ne peut
    toucher qu'aux siennes. La clé est réservée : aucun chemin d'utilisateur ne commence par un dossier interne.
    """
    return rekey(app, area, key(app, path), SHELF + ident) if SHELVED.fullmatch(ident) else 0


def unshelve(app, area, path, ident):
    """Restauration : l'élément retrouve ses versions à sa place."""
    return rekey(app, area, SHELF + ident, key(app, path)) if SHELVED.fullmatch(ident) else 0


def forget(app, area, ident):
    """Élément retiré pour de bon de la corbeille : ses versions, rangées avec lui à sa mise en corbeille, partent avec lui."""
    if not SHELVED.fullmatch(ident):
        return 0
    base, doomed = SHELF + ident, []
    with LOCK, store(app, area) as fd:
        if fd is None:
            return 0
        index = load(fd)
        for name in [name for name in index if name == base or name.startswith(base + '/')]:
            doomed += index.pop(name)
        if doomed:
            save(fd, index)
            for version in doomed:
                # Un identifiant est un nom de fichier du dossier des versions, jamais un chemin.
                if isinstance(version.get('id'), str) and re.fullmatch(r'[a-f0-9]{24}', version['id']):
                    try:
                        os.unlink(version['id'], dir_fd=fd)
                    except FileNotFoundError:
                        pass
    return len(doomed)


def moved(app, area, old, new):
    """Un fichier ou un dossier renommé ou déplacé par la console emmène ses versions avec lui."""
    old, new = key(app, old), key(app, new)
    try:
        with LOCK, store(app, area) as fd:
            if fd is None:
                return
            index = load(fd)
            changed = {}
            for path, values in index.items():
                if path == old or path.startswith(old + '/'):
                    changed[new + path[len(old):]] = values
                else:
                    changed.setdefault(path, values)
            if changed != index:
                save(fd, changed)
    except (OSError, app.Problem):
        # Les versions restent sous l'ancien nom : rien n'est perdu, et le geste demandé a déjà réussi.
        pass
