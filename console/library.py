"""Bibliothèque : les espaces où vivent les documents des personnes, et leur parcours.

Photos et recherche dans le contenu tiennent chacune un index, reconstructible, à côté de la base de Nacre. Toutes
deux parcourent les mêmes espaces — ceux des personnes, ceux des équipes, les fichiers partagés, les volumes — et
ne montrent à chacun que ce que ses droits ouvrent : l'index est commun, la réponse ne l'est jamais.
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import spaces

DEPTH = 32
VISITED = 500_000
SETUP = threading.Lock()


class Stop(Exception):
    pass


def kept(area):
    return area['id'] == 'fichiers' or area['id'].startswith('espace_') or area.get('kind') == 'volume'


def everything(app):
    """Tous les espaces à indexer, vus par le système : aucune session n'en voit autant."""
    with app.database() as db:
        found = ['espace_' + doc['id'] for doc in spaces.every(db, 'space:') if isinstance(doc.get('id'), str) and spaces.IDENT.fullmatch(doc['id'])]
    return sorted(found) + [area['id'] for area in app.file_areas(True) if not area['id'].startswith('espace_') and kept(area)]


def visible(app, session):
    """Espaces que cette session peut lire : la seule liste dont une réponse a le droit de sortir."""
    return [area for area in app.file_areas(session) if kept(area)]


def zone(app):
    from onboarding import read
    try:
        return ZoneInfo(read(app).get('timezone') or 'UTC')
    except Exception:
        return timezone.utc


def local(seconds, where):
    """Heure murale du NAS, sans fuseau : c'est ainsi qu'un appareil photo date aussi ses images."""
    try:
        return datetime.fromtimestamp(seconds, where).strftime('%Y-%m-%dT%H:%M:%S')
    except (OverflowError, OSError, ValueError):
        return '1970-01-01T00:00:00'


@contextmanager
def index(app, name, version, schema):
    """Base d'index à part de celle de Nacre : la supprimer ne perd rien, elle se reconstruit au prochain parcours."""
    connection = sqlite3.connect(app.STATE / name, timeout=20)
    try:
        connection.row_factory = sqlite3.Row
        # Une seule ouverture à la fois prépare l'index : la page qui s'ouvre et le parcours qu'elle lance arrivent ensemble sur un index neuf.
        with SETUP:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=NORMAL')
            if connection.execute('PRAGMA user_version').fetchone()[0] != version:
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                    try:
                        connection.execute(f'DROP TABLE IF EXISTS "{row[0]}"')
                    except sqlite3.Error:
                        pass
                connection.executescript(schema)
                connection.execute(f'PRAGMA user_version={int(version)}')
                connection.commit()
        yield connection
        connection.commit()
    finally:
        connection.close()


def walk(fd, base, state, visit):
    """Parcourt un dossier ouvert sans suivre aucun lien ; `visit(fd, base, name, info)` reçoit chaque fichier ordinaire."""
    folders = []
    with os.scandir(fd) as entries:
        for entry in entries:
            name = entry.name
            if name.startswith('.'):
                continue
            state['visited'] += 1
            if state['visited'] > VISITED:
                raise Stop('count')
            if state['visited'] % 512 == 0:
                if state['halt'].is_set():
                    raise Stop('halt')
                time.sleep(0.002)   # laisse la main : un parcours de fond ne doit pas peser sur le reste
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    folders.append(name)
                elif entry.is_file(follow_symlinks=False):
                    visit(fd, base, name, entry.stat(follow_symlinks=False))
            except OSError:
                continue
    if len(base) + 1 >= DEPTH:
        return
    for name in sorted(folders):
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            continue
        try:
            walk(child, base + [name], state, visit)
        finally:
            os.close(child)


class Scanner:
    """Un parcours de fond à la fois par index, lancé à la demande, jamais au démarrage."""

    def __init__(self, work, fresh=120):
        self.work, self.fresh = work, fresh
        self.lock, self.halt = threading.Lock(), threading.Event()
        self.state = {'running': False, 'started': None, 'finished': None, 'visited': 0, 'kept': 0, 'partial': None, 'error': None}
        self.thread = None

    def status(self):
        with self.lock:
            return dict(self.state)

    def ensure(self, app, force=False):
        """Lance un parcours si le dernier date ; rend aussitôt la main."""
        with self.lock:
            done = self.state['finished']
            if self.state['running'] or (not force and done is not None and time.time() - done < self.fresh):
                return False
            self.state.update(running=True, started=time.time(), visited=0, kept=0, partial=None, error=None)
            self.halt.clear()
            self.thread = threading.Thread(target=self.run, args=(app,), daemon=True, name='nacre-index')
            self.thread.start()
            return True

    def run(self, app):
        progress = {'visited': 0, 'kept': 0, 'halt': self.halt}
        partial = error = None
        try:
            partial = self.work(app, progress, self.note)
        except Exception as failure:   # un index est un confort : son échec ne doit rien casser d'autre
            error = type(failure).__name__
        with self.lock:
            self.state.update(running=False, finished=time.time(), visited=progress['visited'], kept=progress['kept'], partial=partial, error=error)

    def note(self, progress):
        with self.lock:
            self.state.update(visited=progress['visited'], kept=progress['kept'])

    def wait(self, seconds=30):
        thread = self.thread
        if thread:
            thread.join(seconds)

    def stop(self):
        self.halt.set()
        self.wait(10)
