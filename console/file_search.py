"""Recherche d'un fichier ou d'un dossier par son nom, dans un dossier, un espace ou tous les espaces.

Parcours direct, sans index : rien à tenir à jour, rien d'écrit sur le NAS. En contrepartie le parcours est borné
(éléments visités, durée, résultats) et dit quand il s'arrête avant la fin. Il ne suit aucun lien, ignore les noms
cachés et ne lit jamais le contenu des fichiers.
"""
import os
import threading
import time
import unicodedata

RESULTS = 200
VISITED = 200_000
SECONDS = 4.0
DEPTH = 64
QUERY = 80
# Deux parcours à la fois au plus : une recherche ne doit pas monopoliser les disques.
_slots = threading.BoundedSemaphore(2)


class _Stop(Exception):
    pass


def norm(text):
    """Sans accents ni casse : « ete » trouve « Été »."""
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c)).casefold()


def _walk(fd, base, state):
    folders = []
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
                if all(token in plain for token in state['tokens']):
                    info = entry.stat(follow_symlinks=False)
                    state['items'].append({'area': state['area'], 'path': '/'.join(base), 'name': name, 'directory': directory, 'link': link,
                                           'size': info.st_size, 'modified': info.st_mtime, 'rank': 0 if plain.startswith(state['tokens'][0]) else 1})
                    if len(state['items']) >= RESULTS:
                        raise _Stop('results')
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
    tokens = norm(text).split() if isinstance(text, str) and len(text) <= QUERY else []
    if sum(len(token) for token in tokens) < 2:
        raise app.Problem('Saisir au moins deux caractères du nom recherché.')
    admin = session['role'] == 'admin'
    if area is None:
        if path:
            raise app.Problem('Un dossier de départ demande son espace.')
        # Partout : les espaces que le compte peut ouvrir, sauf les restaurations, qui répéteraient chaque fichier.
        spaces = [a['id'] for a in app.file_areas(admin) if a.get('kind') != 'restore']
        spaces.sort(key=lambda space: (space != 'fichiers', not space.startswith('native_')))
    else:
        if (area == 'restaurations' or area.startswith('native_')) and not admin:
            raise app.Problem('Accès réservé aux administrateurs.', 403)
        spaces = [area]
    if not _slots.acquire(blocking=False):
        raise app.Problem('Deux recherches sont déjà en cours. Réessayer dans un instant.', 429)
    state = {'tokens': tokens, 'items': [], 'visited': 0, 'deadline': time.monotonic() + SECONDS, 'area': ''}
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
    order = {space: index for index, space in enumerate(spaces)}
    items = sorted(state['items'], key=lambda item: (item.pop('rank'), order[item['area']], item['path'].count('/') + bool(item['path']), item['name'].casefold()))
    return {'query': text, 'items': items, 'partial': partial, 'visited': state['visited'], 'skipped': skipped, 'limit': RESULTS}
