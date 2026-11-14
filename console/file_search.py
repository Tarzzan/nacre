"""Recherche de fichiers et de dossiers par leur nom, par des critères ou les deux, dans un dossier, un espace ou tous les espaces.

Parcours direct, sans index : rien à tenir à jour, rien d'écrit sur le NAS. En contrepartie le parcours est borné
(éléments visités, durée, résultats) et dit quand il s'arrête avant la fin. Il ne suit aucun lien, ignore les noms
cachés et ne lit jamais le contenu des fichiers.

Trois filtres facultatifs resserrent les résultats : famille de type (d'après l'extension), modification récente, taille
minimale. Ils s'appliquent après le nom : seuls les éléments dont le nom correspond sont examinés.

Sans nom, la recherche se fait par critères seuls et répond à « qu'est-ce qui prend de la place ? ». Elle est alors
classée : les plus gros fichiers d'abord, ou les modifications les plus récentes. Un classement lit tout ce qu'il peut
dans ses bornes de parcours et ne garde que les meilleurs résultats ; la mémoire reste bornée.

Le poids d'un dossier (`usage`) complète ce classement : pour chaque élément du dossier ouvert, la taille cumulée de
tout ce qu'il contient. Mêmes bornes, mêmes deux parcours à la fois ; un dossier que les bornes n'ont pas laissé finir
est donné comme un minimum, et ceux qui n'ont pas été commencés sont signalés.
"""
import heapq
import json
import os
import threading
import time
import unicodedata

RESULTS = 200
VISITED = 200_000
SECONDS = 4.0
DEPTH = 64
QUERY = 80
DAYS = 36500
SIZE = 1 << 50
SORTS = ('size', 'recent')
# Familles de types, d'après l'extension seulement : le contenu n'est jamais lu.
KINDS = {
    'image': ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.bmp', '.tif', '.tiff', '.svg'),
    'video': ('.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v'),
    'audio': ('.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac'),
    'document': ('.pdf', '.doc', '.docx', '.odt', '.xls', '.xlsx', '.ods', '.ppt', '.pptx', '.odp', '.txt', '.md', '.csv', '.rtf'),
    'archive': ('.zip', '.tar', '.gz', '.tgz', '.7z', '.rar', '.bz2', '.xz'),
}
# Deux parcours à la fois au plus : une recherche ne doit pas monopoliser les disques.
_slots = threading.BoundedSemaphore(2)
KEPT = 'usage-kept:'  # dernière pesée de la racine de chaque espace, pour les comparer sans relire le disque


class _Stop(Exception):
    pass


def norm(text):
    """Sans accents ni casse : « ete » trouve « Été »."""
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c)).casefold()


def wanted_kind(kind, plain, directory, link):
    if kind is None:
        return True
    if kind == 'folder':
        return directory
    return not directory and not link and plain.endswith(KINDS[kind])


def whole(app, text, most, message):
    """Entier strictement positif et borné, ou None si le filtre est absent."""
    if text is None or text == '':
        return None
    if not isinstance(text, str) or not text.isascii() or not text.isdigit() or not 1 <= int(text) <= most:
        raise app.Problem(message)
    return int(text)


def _keep(state, item, info):
    state['matched'] += 1
    if state['sort'] is None:
        state['items'].append(item)
        if len(state['items']) >= RESULTS:
            raise _Stop('results')
        return
    # Classement : seuls les meilleurs restent ; à égalité, le premier rencontré est gardé.
    entry = (info.st_size if state['sort'] == 'size' else info.st_mtime, -state['matched'], item)
    if len(state['items']) < RESULTS:
        heapq.heappush(state['items'], entry)
    elif entry > state['items'][0]:
        heapq.heapreplace(state['items'], entry)


def _walk(fd, base, state):
    folders = []
    tokens, since, size = state['tokens'], state['since'], state['size']
    with os.scandir(fd) as entries:
        for entry in entries:
            name = entry.name
            if name.startswith('.'):
                continue
            state['visited'] += 1
            if state['visited'] > VISITED:
                raise _Stop('count')
            if state['visited'] % 256 == 0 and time.monotonic() > state['deadline']:
                raise _Stop('time')
            try:
                link = entry.is_symlink()
                directory = not link and entry.is_dir(follow_symlinks=False)
                plain = norm(name)
                if all(token in plain for token in tokens) and wanted_kind(state['kind'], plain, directory, link):
                    info = entry.stat(follow_symlinks=False)
                    # Une taille ne se compare que pour un vrai fichier : ni dossier ni lien.
                    if (since is None or info.st_mtime >= since) and not (state['sized'] and (directory or link)) and (size is None or info.st_size >= size):
                        _keep(state, {'area': state['area'], 'path': '/'.join(base), 'name': name, 'directory': directory, 'link': link,
                                      'size': info.st_size, 'modified': info.st_mtime, 'rank': 0 if tokens and plain.startswith(tokens[0]) else 1}, info)
            except OSError:
                continue
            if directory:
                folders.append(name)
    if len(base) + 1 >= DEPTH:
        return
    for name in sorted(folders, key=str.casefold):
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            continue
        try:
            _walk(child, base + [name], state)
        finally:
            os.close(child)


def search(app, query, session):
    text, area, path = query.get('q', ''), query.get('area'), query.get('path', '')
    tokens = norm(text).split() if isinstance(text, str) and len(text) <= QUERY else None
    kind = query.get('kind') or None
    if kind is not None and kind != 'folder' and kind not in KINDS:
        raise app.Problem('Type de fichier inconnu.')
    days = whole(app, query.get('days'), DAYS, 'Ancienneté invalide : un nombre de jours est attendu.')
    size = whole(app, query.get('min_size'), SIZE, 'Taille minimale invalide : un nombre d’octets est attendu.')
    sort = query.get('sort') or None
    if sort is not None and sort not in SORTS:
        raise app.Problem('Classement inconnu.')
    if tokens == [] and (sort or kind or days or size):
        # Par critères seuls : toujours classé, par taille sauf pour des dossiers, qui n'en ont pas en propre.
        sort = sort or ('recent' if kind == 'folder' else 'size')
    elif sum(len(token) for token in tokens or []) < 2:
        raise app.Problem('Saisir au moins deux caractères du nom recherché.')
    admin = session['role'] == 'admin'
    if area is None:
        if path:
            raise app.Problem('Un dossier de départ demande son espace.')
        # Partout : les espaces que le compte peut ouvrir, sauf les restaurations, qui répéteraient chaque fichier.
        spaces = [a['id'] for a in app.file_areas(session) if a.get('kind') != 'restore']
        spaces.sort(key=lambda space: (space != 'fichiers', not space.startswith('native_')))
    else:
        if (area == 'restaurations' or area.startswith('native_')) and not admin:
            raise app.Problem('Accès réservé aux administrateurs.', 403)
        spaces = [area]
    if not _slots.acquire(blocking=False):
        raise app.Problem('Deux recherches sont déjà en cours. Réessayer dans un instant.', 429)
    state = {'tokens': tokens, 'items': [], 'visited': 0, 'matched': 0, 'deadline': time.monotonic() + SECONDS, 'area': '', 'kind': kind, 'sort': sort,
             'since': None if days is None else time.time() - days * 86400, 'size': size, 'sized': size is not None or sort == 'size'}
    partial, skipped = None, []
    try:
        for space in spaces:
            state['area'] = space
            try:
                with app.folder(space, path) as fd:
                    _walk(fd, app.parts(path), state)
            except _Stop as stop:
                partial = str(stop)
                break
            except (app.Problem, OSError):
                # Une recherche ciblée dit pourquoi elle échoue ; partout, un espace indisponible est seulement signalé.
                if area is not None:
                    raise
                skipped.append(space)
    finally:
        _slots.release()
    if sort is None:
        order = {space: index for index, space in enumerate(spaces)}
        items = sorted(state['items'], key=lambda item: (item['rank'], order[item['area']], item['path'].count('/') + bool(item['path']), item['name'].casefold()))
    else:
        items = [entry[2] for entry in sorted(state['items'], reverse=True)]
    for item in items:
        del item['rank']
    # « matched » compte les correspondances rencontrées : au-delà de « limit », un classement n'en montre que les meilleures.
    return {'query': text, 'items': items, 'partial': partial, 'visited': state['visited'], 'matched': state['matched'], 'skipped': skipped, 'limit': RESULTS,
            'sort': sort, 'filters': {'kind': kind, 'days': days, 'min_size': size}}


def _weigh(fd, depth, state):
    """Ajoute à « state » la taille et le nombre de tout ce que contient un dossier ouvert, noms cachés compris."""
    folders = []
    with os.scandir(fd) as entries:
        for entry in entries:
            state['visited'] += 1
            if state['visited'] > VISITED:
                raise _Stop('count')
            if state['visited'] % 256 == 0 and time.monotonic() > state['deadline']:
                raise _Stop('time')
            try:
                # Un lien n'est jamais suivi : il compte pour lui-même, pas pour ce qu'il désigne.
                if entry.is_dir(follow_symlinks=False):
                    folders.append(entry.name)
                else:
                    state['size'] += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            state['count'] += 1
    if depth >= DEPTH:
        state['whole'] = state['whole'] and not folders
        return
    for name in folders:
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            state['whole'] = False
            continue
        try:
            _weigh(child, depth + 1, state)
        finally:
            os.close(child)


def usage(app, query, session):
    """Poids de chaque élément d'un dossier : sa taille pour un fichier, celle de tout son contenu pour un dossier."""
    area, path = query.get('area', 'fichiers'), query.get('path', '')
    if not isinstance(area, str) or ((area == 'restaurations' or area.startswith('native_')) and session['role'] != 'admin'):
        raise app.Problem('Accès réservé aux administrateurs.', 403)
    if not _slots.acquire(blocking=False):
        raise app.Problem('Deux recherches sont déjà en cours. Réessayer dans un instant.', 429)
    state = {'visited': 0, 'deadline': time.monotonic() + SECONDS}
    items, waiting, partial = [], [], None
    hidden = {'size': 0, 'count': 0, 'state': 'whole'}
    try:
        with app.folder(area, path) as fd:
            depth = len(app.parts(path)) + 1
            try:
                with os.scandir(fd) as entries:
                    for entry in entries:
                        state['visited'] += 1
                        if state['visited'] > VISITED:
                            raise _Stop('count')
                        try:
                            link = entry.is_symlink()
                            directory = not link and entry.is_dir(follow_symlinks=False)
                            info = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        item = {'name': entry.name, 'directory': directory, 'link': link, 'size': 0 if directory else info.st_size, 'modified': info.st_mtime,
                                'count': 0, 'state': 'waiting' if directory else 'whole'}
                        if entry.name.startswith('.'):
                            # Cachés et corbeille : jamais nommés, mais ils occupent de la place et sont comptés ensemble.
                            hidden['count'] += 1
                            hidden['size'] += item['size']
                            item['hidden'] = True
                        else:
                            items.append(item)
                        if directory:
                            waiting.append(item)
                # Les dossiers visibles d'abord, dans l'ordre des noms ; cachés et corbeille en dernier.
                waiting.sort(key=lambda item: (item.get('hidden', False), item['name'].casefold()))
                for item in waiting:
                    state.update(size=0, count=0, whole=True)
                    item['state'] = 'partial'
                    try:
                        child = os.open(item['name'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except OSError:
                        continue
                    try:
                        _weigh(child, depth, state)
                        item['state'] = 'whole' if state['whole'] else 'partial'
                    finally:
                        os.close(child)
                        item['size'], item['count'] = state['size'], state['count']
            except _Stop as stop:
                partial = str(stop)
    finally:
        _slots.release()
    for item in waiting:
        if item.get('hidden'):
            hidden['size'] += item['size']
            hidden['count'] += item['count']
            if item['state'] != 'whole':
                hidden['state'] = 'partial'
    total = {'size': hidden['size'] + sum(item['size'] for item in items), 'count': hidden['count'] + len(items) + sum(item['count'] for item in items),
             'state': 'whole' if hidden['state'] == 'whole' and all(item['state'] == 'whole' for item in items) else 'partial'}
    # Pesés d'abord, du plus lourd au plus léger ; ce qui n'a pas pu être commencé vient ensuite.
    items.sort(key=lambda item: (item['state'] == 'waiting', -item['size'], item['name'].casefold()))
    rest = items[RESULTS:]
    if partial:
        # Pesée arrêtée avant la fin : le total est un minimum, même si tout ce qui a été lu l'a été en entier.
        total['state'] = 'partial'
    if not app.parts(path):
        keep(app, area, total)
    return {'area': area, 'path': path, 'items': items[:RESULTS], 'total': total, 'hidden': hidden,
            'others': {'count': len(rest), 'size': sum(item['size'] for item in rest)}, 'partial': partial, 'visited': state['visited'], 'limit': RESULTS}


def keep(app, area, total):
    """Garder le poids d'un espace entier, avec son heure. Ne fait jamais échouer la pesée qui vient d'aboutir."""
    try:
        value = json.dumps({'at': time.time(), 'size': total['size'], 'count': total['count'], 'state': total['state']})
        with app.database() as db:
            db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEPT + area, value))
    except Exception:
        pass


def spaces(app, session):
    """Les espaces que ce compte peut voir, chacun avec sa dernière pesée gardée. Aucune lecture du disque."""
    found = []
    with app.database() as db:
        kept = {row['key'][len(KEPT):]: row['value'] for row in db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (KEPT + '%',))}
    for item in app.file_areas(session):
        try:
            value = json.loads(kept[item['id']])
            last = {'at': float(value['at']), 'size': int(value['size']), 'count': int(value['count']), 'state': 'whole' if value['state'] == 'whole' else 'partial'}
        except (KeyError, ValueError, TypeError):
            last = None
        found.append({'id': item['id'], 'name': item['name'], 'kept': last})
    return {'spaces': found}

