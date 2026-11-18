"""Corbeille : retirer pour de bon, la vider, et ne plus la laisser grossir sans fin.

Mettre en corbeille et restaurer restent dans le serveur. Ici : ce qui ne se rattrape pas. Trois règles.

- Retirer pour de bon et vider appartiennent à qui répond de l'espace : chacun dans son espace personnel, un
  administrateur partout ailleurs. C'est une garde contre le geste malheureux, pas une barrière : qui écrit dans un
  espace peut toujours restaurer un fichier puis le remplacer.
- Rien n'est effacé à la place de personne tant qu'un administrateur n'a pas choisi une durée de garde. Sans ce réglage,
  la corbeille ne se vide que d'un geste confirmé.
- Aucun lien n'est suivi, et rien n'est touché hors du dossier de corbeille : un élément y est d'abord mis de côté d'un
  seul geste, sa ligne retirée, puis son contenu effacé. Une panne au milieu ne laisse ni élément à demi restaurable,
  ni reste que le vidage suivant ne retire pas.
"""
import os
import re
import secrets
import stat
import threading
import time

import spaces

SETTING = 'trash'
CHOICES = (0, 7, 30, 90, 365)   # jours de garde ; 0 : jamais vidée seule
IDENT = re.compile(r'[a-f0-9]{32}\Z')
GONE = '.suppr-'     # mis de côté, en cours d'effacement : jamais listé, jamais restaurable
DEPTH = 64           # au-delà, un sous-dossier est remonté à la racine de la corbeille plutôt que descendu
ORPHAN = 3600        # un élément sans ligne n'est un reste qu'au bout d'une heure : une mise en corbeille peut être en cours
WATCH = 3600
FIRST = 300          # premier passage de la durée de garde après le démarrage : jamais pendant, la console répond d'abord
ACTOR = 'conservation'
LOCK = threading.Lock()


def days(db):
    doc = spaces.get(db, SETTING, {})
    value = doc.get('days') if isinstance(doc, dict) else 0
    return value if type(value) is int and value in CHOICES else 0


def erasable(app, session, area):
    """Vrai si cette personne peut retirer pour de bon ce que contient la corbeille de l'espace."""
    if spaces.level(app, session, area) != 'write':
        return False
    return session.get('role') == 'admin' or spaces.private(app, area)


def named(app, area, text):
    return spaces.detail(app, area, text) if area.startswith('espace_') else f'{area}: {text}'


def listing(app, session):
    """Ce que la personne voit de la corbeille : celle des espaces où elle écrit ; un compte en lecture seule garde celle de l'espace commun."""
    with app.database() as db:
        rows = [dict(row) for row in db.execute('SELECT * FROM trash ORDER BY ts DESC')]
    levels, rights, found = {}, {}, []
    for row in rows:
        area = row['area']
        if area not in levels:
            levels[area] = spaces.level(app, session, area)
            rights[area] = levels[area] == 'write' and erasable(app, session, area)
        if levels[area] == 'write' or (session.get('role') == 'viewer' and area == 'fichiers'):
            found.append({**row, 'restore': levels[area] == 'write', 'erase': rights[area]})
    return found


def pending(app, area):
    """Nombre d'effacements interrompus restés dans la corbeille d'un espace, sans créer son dossier s'il n'existe pas."""
    try:
        if area == 'fichiers':
            with app.trash_folder(area) as fd:
                return len(interrupted(fd))
        with app.folder(area, write=True) as root:
            fd = os.open('.nacre-trash', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                return len(interrupted(fd))
            finally:
                os.close(fd)
    except Exception:
        return 0


def overview(app, session):
    """Par espace : combien d'éléments, et si la personne peut les retirer pour de bon. Avec la durée de garde.

    `at` date ce qui est montré : un vidage confirmé sur cette page n'efface rien de ce qui a été jeté depuis.
    """
    at = time.time()
    names = {area['id']: area['name'] for area in spaces.areas(app, session)}
    areas = {}
    for row in listing(app, session):
        entry = areas.setdefault(row['area'], {'id': row['area'], 'name': names.get(row['area'], row['area']), 'count': 0, 'erase': row['erase'], 'oldest': row['ts'], 'leftovers': 0})
        entry['count'] += 1
        entry['oldest'] = min(entry['oldest'], row['ts'])
    # Un effacement interrompu n'a plus de ligne : l'espace reste proposé au vidage tant qu'il en garde un reste.
    for area, name in names.items():
        if area in areas and not areas[area]['erase']:
            continue
        if area in areas or erasable(app, session, area):
            left = pending(app, area)
            if left and area not in areas:
                areas[area] = {'id': area, 'name': name, 'count': 0, 'erase': True, 'oldest': None, 'leftovers': 0}
            if area in areas:
                areas[area]['leftovers'] = left
    with app.database() as db:
        kept = days(db)
    return {'days': kept, 'choices': list(CHOICES), 'manage': session.get('role') == 'admin', 'at': at, 'areas': list(areas.values())}


def opened(fd, name):
    """Ouvre un sous-dossier sans suivre de lien, en se rendant d'abord les droits s'il est fermé à son propre propriétaire."""
    try:
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    except PermissionError:
        # Par le descripteur, jamais par le nom : un lien glissé à cette place ne peut pas détourner le changement de droits.
        handle = os.open(name, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            os.chmod(f'/proc/self/fd/{handle}', 0o700)
        finally:
            os.close(handle)
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        if os.fstat(child).st_mode & 0o300 != 0o300:
            os.fchmod(child, 0o700)   # un dossier en lecture seule ne laisserait pas retirer ce qu'il contient
    except OSError:
        os.close(child)
        raise
    return child


def clear(root, fd, name, depth, pending):
    """Efface `name` du dossier ouvert `fd`. Rend (éléments, octets). Un dossier trop profond rejoint `pending`, à la racine."""
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(name, dir_fd=fd)   # un lien se retire comme un fichier : sa cible n'est jamais touchée
        return 1, info.st_size if stat.S_ISREG(info.st_mode) else 0
    if depth >= DEPTH:
        moved = GONE + secrets.token_hex(12)
        os.rename(name, moved, src_dir_fd=fd, dst_dir_fd=root)
        pending.append(moved)
        return 0, 0
    count, size = 1, 0
    child = opened(fd, name)
    try:
        for entry in os.listdir(child):
            more, weight = clear(root, child, entry, depth + 1, pending)
            count, size = count + more, size + weight
    finally:
        os.close(child)
    os.rmdir(name, dir_fd=fd)
    return count, size


def wipe(root, name):
    """Efface pour de bon un élément du dossier de corbeille ouvert, avec tout ce qu'il contient. Rend (éléments, octets)."""
    pending, count, size = [name], 0, 0
    while pending:
        more, weight = clear(root, root, pending.pop(), 0, pending)
        count, size = count + more, size + weight
    return count, size


def erase(app, fd, row):
    """Retire pour de bon un élément de la corbeille : mis de côté, ligne retirée, contenu effacé, versions oubliées."""
    ident = str(row['id'])
    aside = GONE + ident if IDENT.fullmatch(ident) else None
    if aside:
        try:
            os.rename(ident, aside, src_dir_fd=fd, dst_dir_fd=fd)
        except FileNotFoundError:
            try:
                os.stat(aside, dir_fd=fd, follow_symlinks=False)   # effacement interrompu, déjà mis de côté : on reprend
            except FileNotFoundError:
                # La ligne ne désigne plus rien : restauré à l'instant, ou base reprise d'une copie. Elle part seule ;
                # ni fichier ni version n'est touché.
                aside = None
    with app.database() as db:
        db.execute('DELETE FROM trash WHERE id=?', (row['id'],))
    return finish(app, row['area'], fd, aside) if aside else (0, 0)


def finish(app, area, fd, name):
    """Efface un élément mis de côté, puis oublie les versions rangées avec lui à sa mise en corbeille : les siennes, et elles seules."""
    import versions
    count, size = wipe(fd, name)
    try:
        versions.forget(app, area, name[len(GONE):])
    except Exception:
        pass
    return count, size


def interrupted(fd):
    return [name for name in os.listdir(fd) if name.startswith(GONE)]


def leftovers(app, fd, now):
    """Restes dans le dossier de corbeille : effacements interrompus, et éléments sans ligne depuis plus d'une heure."""
    with app.database() as db:
        known = {row[0] for row in db.execute('SELECT id FROM trash')}
    found = []
    for name in os.listdir(fd):
        if name.startswith(GONE):
            found.append(name)
        elif name not in known:
            try:
                if now - os.stat(name, dir_fd=fd, follow_symlinks=False).st_ctime > ORPHAN:
                    found.append(name)
            except FileNotFoundError:
                pass
    return found


def confirmed(app, body):
    if not isinstance(body, dict) or body.get('confirm') is not True:
        raise app.Problem('Confirmation requise : ce qui est retiré de la corbeille ne se récupère pas.')


def remove(app, body, session):
    """Retire pour de bon un élément de la corbeille."""
    confirmed(app, body)
    ident = body.get('id')
    with LOCK:
        with app.database() as db:
            row = db.execute('SELECT * FROM trash WHERE id=?', (ident,)).fetchone() if isinstance(ident, str) else None
        if not row or spaces.level(app, session, row['area']) != 'write':
            raise app.Problem('Élément introuvable.', 404)
        if not erasable(app, session, row['area']):
            raise app.Problem('Retirer pour de bon revient à un administrateur dans cet espace.', 403)
        row, count, size, failed = dict(row), 0, 0, False
        with app.trash_folder(row['area']) as fd:
            try:
                count, size = erase(app, fd, row)
            except OSError:
                # La ligne est peut-être déjà retirée : le dire et l'inscrire, plutôt qu'une erreur muette sur un geste sans retour.
                failed = True
    app.audit(session['name'], 'Retiré pour de bon de la corbeille', named(app, row['area'], row['original']) + (' (effacement à finir)' if failed else ''))
    return {'ok': not failed, 'items': count, 'bytes': size, 'failed': int(failed)}


def empty(app, body, session, now=None):
    """Vide la corbeille d'un espace : ce qu'elle listait à l'instant `until` de l'affichage, et les restes que plus rien ne liste.

    Ce qui a été jeté depuis n'a pas été montré à qui confirme : il reste en corbeille.
    """
    confirmed(app, body)
    now = time.time() if now is None else now
    area, until = body.get('area'), body.get('until')
    if not isinstance(area, str) or spaces.level(app, session, area) != 'write':
        raise app.Problem('Espace inconnu ou fermé.', 404)
    if not erasable(app, session, area):
        raise app.Problem('Vider la corbeille revient à un administrateur dans cet espace.', 403)
    if type(until) not in (int, float) or not 0 < until < now + 60:
        raise app.Problem('Relire la corbeille avant de la vider.')
    removed = count = size = 0
    with LOCK, app.trash_folder(area) as fd:
        with app.database() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM trash WHERE area=? AND ts<=? ORDER BY ts', (area, until))]
        for row in rows:
            try:
                more, weight = erase(app, fd, row)
                removed, count, size = removed + 1, count + more, size + weight
            except OSError:
                pass   # ce qui n'a pas pu partir est compté plus bas, d'après ce qui reste réellement
        for name in leftovers(app, fd, now):
            try:
                more, weight = finish(app, area, fd, name) if name.startswith(GONE) else wipe(fd, name)
                count, size = count + more, size + weight
            except OSError:
                pass
        with app.database() as db:
            left = db.execute('SELECT COUNT(*) FROM trash WHERE area=? AND ts<=?', (area, until)).fetchone()[0]
            later = db.execute('SELECT COUNT(*) FROM trash WHERE area=? AND ts>?', (area, until)).fetchone()[0]
        failed = left + len(interrupted(fd))
    app.audit(session['name'], 'Corbeille vidée', named(app, area, f'{removed} élément{"s" if removed > 1 else ""}' + (f', {failed} non retiré{"s" if failed > 1 else ""}' if failed else '')))
    return {'ok': not failed, 'removed': removed, 'items': count, 'bytes': size, 'failed': failed, 'later': later}


def configure(app, body, session):
    """Durée de garde : au-delà, un élément est retiré pour de bon, sans geste de personne. Réservé à un administrateur."""
    if session.get('role') != 'admin':
        raise app.Problem('Un compte administrateur est nécessaire.', 403)
    value = body.get('days') if isinstance(body, dict) else None
    if type(value) is not int or value not in CHOICES:
        raise app.Problem('Durée de garde inconnue.')
    if value and body.get('confirm') is not True:
        raise app.Problem('Confirmation requise : passé ce délai, les éléments en corbeille seront retirés pour de bon.')
    with app.database() as db:
        spaces.put(db, SETTING, {'days': value})
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',
                   (time.time(), session['name'], 'Garde de la corbeille', f'{value} jours' if value else 'jamais vidée seule'))
    return {'ok': True, 'days': value}


def sweep(app, now=None):
    """Passage de la durée de garde, pour le système : retire ce qui est en corbeille depuis plus longtemps. Rend le nombre retiré."""
    now = time.time() if now is None else now
    with app.database() as db:
        kept = days(db)
        rows = [dict(row) for row in db.execute('SELECT * FROM trash WHERE ts<? ORDER BY area,ts', (now - kept * 86400,))] if kept else []
    removed = 0
    for area in dict.fromkeys(row['area'] for row in rows):
        try:
            with LOCK, app.trash_folder(area) as fd:
                for row in (row for row in rows if row['area'] == area):
                    with app.database() as db:   # restauré entre-temps : il n'est plus à retirer
                        if not db.execute('SELECT 1 FROM trash WHERE id=? AND ts=?', (row['id'], row['ts'])).fetchone():
                            continue
                    try:
                        if erase(app, fd, row) != (0, 0):
                            removed += 1
                    except OSError:
                        pass
                for name in interrupted(fd):   # un effacement resté en route n'est plus restaurable : il est fini ici
                    try:
                        finish(app, area, fd, name)
                    except OSError:
                        pass
        except Exception:
            continue   # espace momentanément absent ou fermé : au passage suivant
    if removed:
        try:
            app.audit(ACTOR, 'Corbeille : éléments anciens retirés', f'{removed} élément{"s" if removed > 1 else ""} de plus de {kept} jours')
        except Exception:
            pass
    return removed


def disable_after_recovery(db):
    """Après une récupération de l'installation, la base peut dater : la corbeille ne se vide plus seule tant qu'un administrateur ne l'a pas redemandé."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone():
        db.execute('DELETE FROM settings WHERE key=?', (SETTING,))


def passage(app):
    try:
        sweep(app)
    except Exception:
        pass
    watch(app, WATCH)


def watch(app, delay=FIRST):
    """Toutes les heures : applique la durée de garde, si un administrateur en a choisi une. Dans son propre fil, jamais au démarrage même."""
    timer = threading.Timer(delay, passage, (app,))
    timer.daemon = True
    timer.start()
    return timer
