"""Copies de retour arrière laissées par les mises à jour : inventaire, rétention, suppression.

Module de la console, distinct du superviseur figé. Il n'agit que dans le répertoire privé
`state/console/updates`, sous le même verrou que la préparation d'une mise à jour, et ne
supprime jamais le dossier que l'état du superviseur désigne. Voir docs/BROWSER-UPDATES.md.
"""
from contextlib import contextmanager
import os
import re
import shutil
import stat
import time

import update_engine as engine

KEEP = 3                # copies conservées, celle de la dernière mise à jour comprise
STALE_UPLOAD = 3600     # un import interrompu est effacé après une heure
NAME = re.compile(r'[0-9a-f]{24}\Z')
UPLOAD = re.compile(r'upload-[0-9a-f]{24}\Z')
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]{1,32})?\Z')
BUSY = 'Mise à jour en cours : les copies ne peuvent pas être modifiées.'


def folders(root):
    """Dossiers de préparation du superviseur : nom aléatoire de 24 chiffres hexadécimaux, jamais un lien."""
    try:
        entries = list(engine.area(root).iterdir())
    except OSError:
        return []
    return [p for p in entries if NAME.match(p.name) and not p.is_symlink() and p.is_dir()]


def version(path):
    try:
        value = engine.read(path, {}).get('version')
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and VERSION.match(value) else None


def measure(folder):
    total = 0
    for base, _, names in os.walk(folder):
        for name in names:
            try:
                info = os.lstat(os.path.join(base, name))
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def describe(folder, current):
    """Une copie complète porte `before.json` ; sans lui, c'est un paquet vérifié jamais installé."""
    before = folder / 'before.json'
    copied = before.is_file() and not before.is_symlink()
    try:
        created = (before if copied else folder).stat().st_mtime
    except OSError:
        created = 0
    return {'id': folder.name, 'kind': 'copy' if copied else 'prepared', 'version': version(folder / 'manifest.json'),
            'previous': version(before) if copied else None, 'created': created, 'bytes': measure(folder), 'current': folder.name == current}


def listing(root):
    current = engine.state(root).get('id')
    items = sorted((describe(folder, current) for folder in folders(root)), key=lambda item: (-item['created'], item['id']))
    return {'keep': KEEP, 'bytes': sum(item['bytes'] for item in items), 'items': items}


def drop(root, identifier):
    folder = engine.area(root) / identifier
    if not NAME.match(identifier) or folder.is_symlink() or not folder.is_dir():
        raise engine.UpdateError('Copie introuvable. Rechargez la page.')
    try:
        # Le témoin part en premier : une suppression interrompue laisse un reste que la règle automatique finit d'effacer.
        (folder / 'before.json').unlink(missing_ok=True)
        engine.sync(folder)
        shutil.rmtree(folder)
        engine.sync(folder.parent)
    except OSError:
        raise engine.UpdateError('Suppression impossible : vérifiez les droits du répertoire des mises à jour.') from None


def settled(root):
    state = engine.state(root)
    if state['phase'] in engine.ACTIVE:
        raise engine.UpdateError(BUSY)
    return state.get('id')


@contextmanager
def reserved(root):
    """Verrou de préparation du superviseur, pris seulement hors mise à jour : il ne doit jamais gêner une installation demandée."""
    settled(root)
    with engine.guard(root):
        yield settled(root)


def retain(root, keep=KEEP, now=None):
    """Règle automatique : garder les `keep` copies les plus récentes, effacer les paquets abandonnés et les imports interrompus."""
    now = time.time() if now is None else now
    with reserved(root) as current:
        items = sorted((describe(folder, current) for folder in folders(root)), key=lambda item: (-item['created'], item['id']))
        copies = [item for item in items if item['kind'] == 'copy']
        doomed = [item for item in copies[keep:] + [item for item in items if item['kind'] == 'prepared'] if not item['current']]
        for item in doomed:
            drop(root, item['id'])
        for path in engine.area(root).iterdir():
            if UPLOAD.match(path.name) and not path.is_symlink() and path.is_file() and now - path.stat().st_mtime > STALE_UPLOAD:
                path.unlink()
        return doomed


def delete(root, identifier):
    """Suppression demandée par un administrateur : tout sauf la copie de la dernière mise à jour."""
    if not isinstance(identifier, str) or not NAME.match(identifier):
        raise engine.UpdateError('Copie introuvable. Rechargez la page.')
    with reserved(root) as current:
        if current == identifier:
            raise engine.UpdateError('La copie de la dernière mise à jour est conservée jusqu’à la suivante.')
        folder = engine.area(root) / identifier
        if folder not in folders(root):
            raise engine.UpdateError('Copie introuvable. Rechargez la page.')
        item = describe(folder, None)
        drop(root, identifier)
        return item


def label(item):
    return f"Nacre {item['previous'] or 'version inconnue'}, avant {item['version'] or 'version inconnue'}"


def tidy(app, attempts=5):
    """Au démarrage de la console et après un import : applique la règle sans jamais bloquer ni faire échouer l'appelant."""
    if not engine.area(app.ROOT).is_dir():
        return []
    for _ in range(attempts):
        try:
            removed = retain(app.ROOT)
            break
        except engine.UpdateError:
            # Le superviseur relâche son verrou juste après avoir validé une installation.
            time.sleep(.2)
        except (OSError, ValueError):
            return []
    else:
        return []
    copies = [item for item in removed if item['kind'] == 'copy']
    if copies:
        app.audit('console', 'Anciennes copies de mise à jour supprimées', ' ; '.join(label(item) for item in copies))
    return removed


def remove(app, body, session):
    if body.get('confirm') is not True:
        raise app.Problem('Confirmez la suppression définitive de cette copie.')
    from control_panel import authorized
    with app.database() as db:
        authorized(app, db, session)
    try:
        item = delete(app.ROOT, body.get('id'))
    except engine.UpdateError as error:
        raise app.Problem(str(error), 409) from None
    app.audit(session['name'], 'Copie de mise à jour supprimée', label(item))
    return listing(app.ROOT)
