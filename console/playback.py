"""Relecture des enregistrements : plages conservées par jour civil et extraits bornés.

Lecture seule de l'API interne de Frigate. Aucune configuration, tâche ou vidéo n'est écrite.
"""
import datetime
import json
import math
import re
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

DAY = re.compile(r'\d{4}-\d{2}-\d{2}\Z')
# Deux segments séparés de moins de trois secondes forment une même plage.
JOIN = 3
CLIP_MAX = 300
# Bornes de consultation : la conservation réglable s'arrête à 30 jours.
HISTORY_DAYS = 400
CLIP_HISTORY = 31 * 86400
# Plafond de lecture de l'inventaire d'une journée ; sans rapport avec la taille des vidéos.
MAX_BYTES = 96 * 1024 ** 2


def zone(app):
    from onboarding import read
    name = read(app)['timezone']
    try:
        return name, ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return 'UTC', datetime.timezone.utc


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def fetch(app, path):
    with app.video_get(path, timeout=30) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise app.Problem('Inventaire vidéo trop volumineux pour cette journée.', 502)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise app.Problem('Réponse du service vidéo illisible.', 502) from None


def bounds(app, day, tz, now):
    today = datetime.datetime.fromtimestamp(now, tz).date()
    if day is None:
        return None, today
    if not isinstance(day, str) or not DAY.fullmatch(day):
        raise app.Problem('Date invalide. Format attendu : AAAA-MM-JJ.')
    try:
        value = datetime.date.fromisoformat(day)
    except ValueError:
        raise app.Problem('Date invalide. Format attendu : AAAA-MM-JJ.') from None
    if value > today or (today - value).days > HISTORY_DAYS:
        raise app.Problem('Date hors de la période consultable.')
    return value, today


def midnight(day, tz):
    return datetime.datetime(day.year, day.month, day.day, tzinfo=tz).timestamp()


def merge(values):
    result = []
    for start, end in sorted(values):
        if result and start - result[-1][1] <= JOIN:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def overlap(intervals, start, end):
    return sum(max(0, min(b, end) - max(a, start)) for a, b in intervals)


def available_days(app, camera, tz_name):
    """Jours civils pour lesquels Frigate annonce des enregistrements, du plus récent au plus ancien."""
    payload = fetch(app, f'/api/{camera}/recordings/summary?timezone={quote(tz_name, safe="/")}')
    days = {}
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('day'), str) or not DAY.fullmatch(item['day']):
            continue
        hours = item.get('hours') if isinstance(item.get('hours'), list) else []
        seconds = sum(h['duration'] for h in hours if isinstance(h, dict) and number(h.get('duration')) and h['duration'] > 0)
        if seconds > 0:
            days[item['day']] = days.get(item['day'], 0) + seconds
    return [{'day': day, 'recorded': round(seconds)} for day, seconds in sorted(days.items(), reverse=True)[:HISTORY_DAYS]]


def timeline(app, camera, day=None, now=None):
    now = time.time() if now is None else now
    tz_name, tz = zone(app)
    wanted, today = bounds(app, day, tz, now)
    days = available_days(app, camera, tz_name)
    if wanted is None:
        wanted = datetime.date.fromisoformat(days[0]['day']) if days else today
        if wanted > today:
            wanted = today
    start, end = midnight(wanted, tz), midnight(wanted + datetime.timedelta(days=1), tz)
    limit = min(end, now)
    payload = fetch(app, f'/api/{camera}/recordings?after={start}&before={limit}') if limit > start else []
    recorded, detected, count = [], [], 0
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not number(item.get('start_time')) or not number(item.get('end_time')):
            continue
        a, b = max(item['start_time'], start), min(item['end_time'], limit)
        if b <= a:
            continue
        count += 1
        recorded.append((a, b))
        if type(item.get('objects')) is int and item['objects'] > 0:
            detected.append((a, b))
    recorded, detected = merge(recorded), merge(detected)
    hours, cursor = [], start
    while cursor < end:
        stop = min(cursor + 3600, end)
        hours.append({'start': cursor, 'end': stop, 'label': datetime.datetime.fromtimestamp(cursor, tz).strftime('%H:%M'),
                      'recorded': round(overlap(recorded, cursor, stop)), 'detected': round(overlap(detected, cursor, stop))})
        cursor = stop
    return {'camera': camera, 'timezone': tz_name, 'day': wanted.isoformat(), 'today': today.isoformat(),
            'start': start, 'end': end, 'now': now, 'days': days, 'hours': hours,
            'intervals': recorded, 'detections': detected, 'segments': count,
            'recorded': round(overlap(recorded, start, end)), 'detected': round(overlap(detected, start, end)),
            'clip_max': CLIP_MAX}


def clip(app, camera, query, now=None):
    """Valide un extrait et retourne le chemin Frigate, puis le nom de fichier si un téléchargement est demandé."""
    now = time.time() if now is None else now
    start, end = float(query['start']), float(query['end'])
    if not (math.isfinite(start) and math.isfinite(end)):
        raise app.Problem('Intervalle vidéo invalide.')
    if not 0 < end - start <= CLIP_MAX:
        raise app.Problem('Intervalle vidéo invalide (5 minutes maximum).')
    if start < now - CLIP_HISTORY or end > now + 60:
        raise app.Problem('Intervalle vidéo hors de la période consultable.')
    name = None
    if query.get('download') == '1':
        stamp = datetime.datetime.fromtimestamp(start, zone(app)[1]).strftime('%Y%m%d-%H%M%S')
        name = f'nacre-{camera}-{stamp}.mp4'
    return f'/api/{camera}/start/{start}/end/{end}/clip.mp4', name
