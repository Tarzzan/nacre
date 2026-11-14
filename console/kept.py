"""Passages conservés et autonomie du volume vidéo.

Un passage conservé est un export de Frigate : une copie à part de l'extrait, que n'effacent ni la durée de
conservation ni le nettoyage d'un volume plein. Nacre ne lit ni n'écrit lui-même aucun fichier vidéo.
"""
import datetime
import math
import re
import time

import playback

# Identifiant d'export de Frigate : nom de caméra, puis suffixe aléatoire.
EXPORT_ID = re.compile(r'[A-Za-z0-9_-]{1,60}\Z')
VIDEO_FILE = re.compile(r'[A-Za-z0-9_.-]{1,200}\.mp4\Z')
# Nom donné par Nacre à l'export : début et fin de l'extrait, puis le nom choisi.
NAME = re.compile(r'(\d{9,11})-(\d{9,11})(?: (.{1,60}))?\Z', re.S)
NAME_MAX = 60
# Passages présentés pour une caméra ; au-delà, il faut en retirer avant d'en conserver d'autres.
KEPT_MAX = 500
RECORDINGS = '/media/frigate/recordings'
MIB = 1024 ** 2
UNAVAILABLE = 'Passages conservés indisponibles : le service vidéo ne les fournit pas.'


def label(app, value):
    """Nom facultatif d'un passage : texte simple, sans caractère de contrôle."""
    if value is None:
        return ''
    if not isinstance(value, str):
        raise app.Problem('Nom de passage invalide.')
    text = ' '.join(value.split())
    if len(text) > NAME_MAX or not all(ch.isprintable() for ch in text):
        raise app.Problem(f'Nom de passage invalide ({NAME_MAX} caractères au plus).')
    return text


def sizes(app):
    """Taille de chaque fichier conservé, d'après le dossier des exports ; vide si le service ne le liste pas."""
    try:
        payload = playback.fetch(app, '/exports/')
    except app.Problem:
        return {}
    return {item['name']: item['size'] for item in payload if isinstance(item, dict) and isinstance(item.get('name'), str)
            and type(item.get('size')) is int and item['size'] >= 0} if isinstance(payload, list) else {}


def entry(item, camera, weights):
    if not isinstance(item, dict) or item.get('camera') != camera:
        return None
    ident, name, path = item.get('id'), item.get('name'), item.get('video_path')
    if not isinstance(ident, str) or not EXPORT_ID.fullmatch(ident):
        return None
    file = path.rsplit('/', 1)[-1] if isinstance(path, str) else ''
    file = file if VIDEO_FILE.fullmatch(file) else ''
    match = NAME.fullmatch(name) if isinstance(name, str) else None
    if match and int(match[1]) < int(match[2]):
        start, end, name = int(match[1]), int(match[2]), match[3] or ''
    else:
        # Export créé hors de Nacre : seule sa date de début est connue.
        start, end = item.get('date'), None
        if not playback.number(start) or start <= 0:
            return None
        name = name[:NAME_MAX] if isinstance(name, str) and all(ch.isprintable() for ch in name[:NAME_MAX]) else ''
    return {'id': ident, 'start': start, 'end': end, 'name': name, 'pending': item.get('in_progress') is not False,
            'size': weights.get(file), 'file': file}


def exports(app, camera, weights=None):
    try:
        payload = playback.fetch(app, f'/api/exports?cameras={camera}')
    except app.Problem:
        raise app.Problem(UNAVAILABLE, 503) from None
    if not isinstance(payload, list):
        raise app.Problem(UNAVAILABLE, 503)
    found = [e for e in (entry(item, camera, weights or {}) for item in payload) if e]
    return sorted(found, key=lambda e: -e['start'])


def listing(app, camera):
    """Passages conservés d'une caméra, du plus récent au plus ancien."""
    tz_name, tz = playback.zone(app)
    found = exports(app, camera, sizes(app))
    items = found[:KEPT_MAX]
    for e in items:
        e['day'] = datetime.datetime.fromtimestamp(e['start'], tz).date().isoformat()
        del e['file']
    return {'camera': camera, 'timezone': tz_name, 'items': items, 'more': len(found) > KEPT_MAX,
            'size': sum(e['size'] or 0 for e in items), 'keep_max': playback.CLIP_MAX, 'name_max': NAME_MAX}


def keep(app, body, actor, now=None):
    """Demande à Frigate une copie à part de l'extrait. La copie se termine en arrière-plan."""
    from cameras import identifier
    now = time.time() if now is None else now
    camera = identifier(app, body.get('camera'))
    start, end = body.get('start'), body.get('end')
    if not playback.number(start) or not playback.number(end) or isinstance(start, bool) or isinstance(end, bool):
        raise app.Problem('Extrait invalide.')
    if not 0 < end - start <= playback.CLIP_MAX:
        raise app.Problem('Extrait invalide (5 minutes maximum).')
    if start < now - playback.CLIP_HISTORY or end > now + 60:
        raise app.Problem('Extrait hors de la période consultable.')
    name = label(app, body.get('name'))
    # Frigate arrondit à la seconde : l'extrait gardé couvre au moins celui qui a été vu.
    first, last = math.floor(start), math.ceil(end)
    known = exports(app, camera)
    if len(known) >= KEPT_MAX:
        raise app.Problem(f'Cette caméra compte déjà {KEPT_MAX} passages conservés. Retirez-en avant d’en ajouter.', 409)
    if any(e['start'] == first and e['end'] == last for e in known):
        raise app.Problem('Cet extrait est déjà conservé.', 409)
    status, answer = app.video_post(f'/api/export/{camera}/start/{first}/end/{last}', {'name': f'{first}-{last} {name}'.strip()})
    if status == 400:
        raise app.Problem('Rien à conserver : la vidéo de cet extrait n’est plus enregistrée.', 409)
    if status == 503:
        raise app.Problem('Le service vidéo prépare déjà beaucoup de copies. Réessayez dans un instant.', 503)
    if not 200 <= status < 300 or not isinstance(answer, dict) or answer.get('success') is not True:
        raise app.Problem('Le service vidéo n’a pas accepté la conservation. Rien n’a été gardé.', 502)
    stamp = datetime.datetime.fromtimestamp(first, playback.zone(app)[1]).strftime('%Y-%m-%d %H:%M:%S')
    app.audit(actor, 'Extrait vidéo conservé', f'{camera} · {stamp} · {last - first} s' + (f' · {name}' if name else ''))
    ident = answer.get('export_id')
    return {'ok': True, 'id': ident if isinstance(ident, str) and EXPORT_ID.fullmatch(ident) else None}


def find(app, camera, ident):
    if not isinstance(ident, str) or not EXPORT_ID.fullmatch(ident):
        raise app.Problem('Identifiant de passage invalide.')
    for e in exports(app, camera):
        if e['id'] == ident:
            return e
    raise app.Problem('Passage inconnu pour cette caméra.', 404)


def remove(app, body, actor):
    """Supprime la copie conservée. L'enregistrement d'origine, s'il existe encore, n'est pas touché."""
    from cameras import identifier
    camera = identifier(app, body.get('camera'))
    if body.get('confirm') is not True:
        raise app.Problem('Confirmation requise pour retirer un passage conservé.')
    e = find(app, camera, body.get('id'))
    if e['pending']:
        raise app.Problem('La copie de ce passage est encore en cours. Réessayez dans un instant.', 409)
    status, answer = app.video_post('/api/exports/delete', {'ids': [e['id']]})
    if not 200 <= status < 300 or not isinstance(answer, dict) or answer.get('success') is not True:
        raise app.Problem('Le service vidéo n’a pas retiré ce passage. Il est toujours conservé.', 502)
    stamp = datetime.datetime.fromtimestamp(e['start'], playback.zone(app)[1]).strftime('%Y-%m-%d %H:%M:%S')
    app.audit(actor, 'Passage conservé retiré', f'{camera} · {stamp}' + (f' · {e["name"]}' if e['name'] else ''))
    return {'ok': True}


def video(app, camera, query):
    """Chemin du fichier conservé dans le service vidéo, puis le nom de fichier si un téléchargement est demandé."""
    e = find(app, camera, query.get('id'))
    if e['pending'] or not e['file']:
        raise app.Problem('La copie de ce passage n’est pas encore prête.', 409)
    name = None
    if query.get('download') == '1':
        stamp = datetime.datetime.fromtimestamp(e['start'], playback.zone(app)[1]).strftime('%Y%m%d-%H%M%S')
        name = f'nacre-{camera}-conserve-{stamp}.mp4'
    return '/exports/' + e['file'], name


def measure(value):
    """Mesure de Frigate en mébioctets, convertie en octets ; None si elle est absente ou incohérente."""
    return round(value * MIB) if playback.number(value) and not isinstance(value, bool) and value >= 0 else None


def storage(app):
    """Autonomie du volume vidéo : espace libre rapporté au débit d'enregistrement mesuré par Frigate.

    Lecture seule. L'estimation porte sur l'enregistrement continu ; elle ne prédit pas les événements à venir.
    """
    from cameras import config
    cameras = config(app).get('cameras', {})
    try:
        stats = app.video_json('/api/stats')
        disk = stats['service']['storage'][RECORDINGS]
        total, free = measure(disk.get('total')), measure(disk.get('free'))
        usage = playback.fetch(app, '/api/recordings/storage')
    except (app.Problem, OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'available': False}
    if not total or free is None or free > total or not isinstance(usage, dict):
        return {'available': False}
    rows, rate, recorded, needed = [], 0, 0, 0
    for ident, settings in cameras.items():
        sample = usage.get(ident) if isinstance(usage.get(ident), dict) else {}
        flow, used = measure(sample.get('bandwidth')), measure(sample.get('usage'))
        record = settings.get('record', {}) if isinstance(settings, dict) else {}
        days = record.get('continuous', {}).get('days', 1) if isinstance(record, dict) and isinstance(record.get('continuous', {}), dict) else 1
        days = days if type(days) in (int, float) and 0 < days <= 3650 else 1
        active = isinstance(settings, dict) and settings.get('enabled', True) is not False
        rows.append({'id': ident, 'name': settings.get('friendly_name') or ident if isinstance(settings, dict) else ident,
                     'rate': flow if active else 0, 'used': used, 'days': days})
        recorded += used or 0
        if active and flow:
            rate += flow
            needed += flow * 24 * days
    weights = sizes(app)
    kept = {'count': len(weights), 'size': sum(weights.values())}
    result = {'available': True, 'total': total, 'free': free, 'recorded': recorded, 'kept': kept, 'cameras': rows,
              'rate': rate or None, 'hours': None, 'needed': None, 'reach_days': None, 'state': 'unknown'}
    if rate:
        hours = free / rate
        result.update(hours=round(hours, 1), needed=needed)
        if hours < 1:
            result['state'] = 'full'
        elif needed - recorded > free:
            # La durée réglée ne tient pas : voici jusqu'où le volume permet de remonter au débit actuel.
            result.update(state='short', reach_days=round((recorded + free) / (rate * 24), 1))
        else:
            result['state'] = 'ample'
    return result
