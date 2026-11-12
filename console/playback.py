"""Relecture des enregistrements : plages conservées par jour civil, événements, recherche sur une période et extraits bornés.

Lecture seule de l'API interne de Frigate. Aucune configuration, tâche ou vidéo n'est écrite.
"""
import datetime
import json
import math
import re
import time
from collections import Counter
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
# Identifiant d'événement Frigate : horodatage de début, puis suffixe aléatoire.
EVENT_ID = re.compile(r'\d{1,12}(\.\d{1,9})?-[a-z0-9]{1,16}\Z')
# Événements présentés pour une journée ; au-delà, la réponse signale qu'il en reste.
EVENT_MAX = 1000
THUMBNAIL_MAX = 2 * 1024 ** 2
# Recherche sur une période : résultats servis par pages, compteurs établis sur les plus récents.
LABEL = re.compile(r'[a-z][a-z0-9_ ]{0,31}\Z')
SEARCH_PAGE = 60
SEARCH_COUNTED = 10000
SEARCH_DEFAULT_DAYS = 7
SEARCH_UNAVAILABLE = 'Recherche indisponible : le service vidéo ne fournit pas les événements.'


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


def summary(app, camera, tz_name):
    payload = fetch(app, f'/api/{camera}/recordings/summary?timezone={quote(tz_name, safe="/")}')
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, dict) and isinstance(item.get('day'), str) and DAY.fullmatch(item['day']):
            yield item['day'], [h for h in item['hours'] if isinstance(h, dict) and number(h.get('duration')) and h['duration'] > 0] if isinstance(item.get('hours'), list) else []


def available_days(app, camera, tz_name):
    """Jours civils pour lesquels Frigate annonce des enregistrements, du plus récent au plus ancien."""
    days = {}
    for day, hours in summary(app, camera, tz_name):
        seconds = sum(h['duration'] for h in hours)
        if seconds > 0:
            days[day] = days.get(day, 0) + seconds
    return [{'day': day, 'recorded': round(seconds)} for day, seconds in sorted(days.items(), reverse=True)[:HISTORY_DAYS]]


def recorded_hours(app, camera, tz_name):
    """Heures civiles (jour, heure) encore couvertes par un enregistrement ; None si Frigate ne le dit pas."""
    try:
        return {(day, h['hour']) for day, hours in summary(app, camera, tz_name) for h in hours if isinstance(h.get('hour'), str)}
    except app.Problem:
        return None


def score(item):
    data = item.get('data') if isinstance(item.get('data'), dict) else {}
    for value in (data.get('top_score'), data.get('score'), item.get('top_score')):
        if number(value) and 0 < value <= 1:
            return round(value * 100)
    return None


def event(item, camera, start, end, now):
    """Événement Frigate réduit aux champs présentés, ou None s'il est inexploitable ou hors de l'intervalle."""
    if not isinstance(item, dict) or item.get('camera') != camera:
        return None
    ident, label, begin, stop = item.get('id'), item.get('label'), item.get('start_time'), item.get('end_time')
    if not isinstance(ident, str) or not EVENT_ID.fullmatch(ident) or not isinstance(label, str) or not 0 < len(label) <= 64:
        return None
    if not number(begin) or not start <= begin < end or not (stop is None or number(stop)):
        return None
    sub = item.get('sub_label')
    sub = sub[0] if isinstance(sub, list) and sub else sub
    return {'id': ident, 'label': label, 'sub_label': sub[:80] if isinstance(sub, str) and sub else None,
            'start': begin, 'end': max(begin, now if stop is None else stop), 'ongoing': stop is None, 'score': score(item)}


def events(app, camera, start, end, now):
    """Événements Frigate commencés dans l'intervalle, du plus ancien au plus récent.

    Retourne (None, False) si le service ne les fournit pas : la relecture reste utilisable sans eux.
    """
    try:
        payload = fetch(app, f'/api/events?cameras={camera}&after={start}&before={end}&limit={EVENT_MAX + 1}&include_thumbnails=0&sort=date_asc')
    except app.Problem:
        return None, False
    if not isinstance(payload, list):
        return None, False
    found = [e for e in (event(item, camera, start, end, now) for item in payload[:EVENT_MAX]) if e]
    return sorted(found, key=lambda e: e['start']), len(payload) > EVENT_MAX


def search(app, camera, query, now=None):
    """Événements d'une caméra sur une période de jours civils, du plus récent au plus ancien, par pages.

    La première page porte les compteurs par type et par jour ; les suivantes se demandent avec `before`.
    Lecture seule de Frigate.
    """
    now = time.time() if now is None else now
    tz_name, tz = zone(app)
    last, today = bounds(app, query.get('to') or None, tz, now)
    last = last or today
    first = bounds(app, query.get('from') or None, tz, now)[0] or max(last - datetime.timedelta(days=SEARCH_DEFAULT_DAYS - 1), today - datetime.timedelta(days=HISTORY_DAYS))
    if first > last:
        raise app.Problem('Période invalide : le début suit la fin.')
    label = query.get('label') or ''
    if label and not LABEL.fullmatch(label):
        raise app.Problem('Type d’objet invalide.')
    start, end = midnight(first, tz), min(midnight(last + datetime.timedelta(days=1), tz), now)
    cursor = query.get('before')
    if cursor is not None:
        try:
            cursor = float(cursor)
        except ValueError:
            cursor = math.nan
        if not (math.isfinite(cursor) and start < cursor <= end):
            raise app.Problem('Position de recherche invalide.')

    def listing(before, limit, wanted=''):
        try:
            payload = fetch(app, f'/api/events?cameras={camera}&after={start}&before={before}&limit={limit + 1}&include_thumbnails=0&sort=date_desc' + (f'&labels={quote(wanted)}' if wanted else ''))
        except app.Problem:
            raise app.Problem(SEARCH_UNAVAILABLE, 503) from None
        if not isinstance(payload, list):
            raise app.Problem(SEARCH_UNAVAILABLE, 503)
        found = [e for e in (event(item, camera, start, end, now) for item in payload[:limit]) if e]
        return sorted(found, key=lambda e: -e['start']), len(payload) > limit

    def civil(e):
        return datetime.datetime.fromtimestamp(e['start'], tz)

    facets = following = None
    if end <= start:
        page, facets = [], {'total': 0, 'matched': 0, 'more': False, 'types': [], 'days': []}
    elif cursor is None:
        counted, more = listing(end, SEARCH_COUNTED)
        chosen = [e for e in counted if not label or e['label'] == label]
        types, days = Counter(e['label'] for e in counted), Counter(civil(e).date().isoformat() for e in chosen)
        facets = {'total': len(counted), 'matched': len(chosen), 'more': more,
                  'types': [{'label': name, 'count': count} for name, count in sorted(types.items(), key=lambda t: (-t[1], t[0]))],
                  'days': [{'day': day, 'count': count} for day, count in sorted(days.items(), reverse=True)]}
        page = chosen[:SEARCH_PAGE]
        # Au-delà des événements comptés, la suite se lit directement dans Frigate.
        following = page[-1]['start'] if len(chosen) > SEARCH_PAGE else counted[-1]['start'] if more and counted else None
    else:
        page, more = listing(cursor, SEARCH_PAGE, label)
        following = page[-1]['start'] if more and page else None
    hours = recorded_hours(app, camera, tz_name) if page else None
    for e in page:
        moment = civil(e)
        e['day'] = moment.date().isoformat()
        # Indice seulement : la relecture du jour dit précisément ce qui est conservé.
        e['recorded'] = hours is None or (e['day'], moment.strftime('%H')) in hours
    return {'camera': camera, 'timezone': tz_name, 'from': first.isoformat(), 'to': last.isoformat(), 'today': today.isoformat(),
            'label': label, 'events': page, 'next': following, 'facets': facets}


def thumbnail(app, camera, ident):
    """Chemin Frigate de la vignette d'un événement, après vérification qu'il appartient à la caméra."""
    if not isinstance(ident, str) or not EVENT_ID.fullmatch(ident):
        raise app.Problem('Identifiant d’événement invalide.')
    event = fetch(app, f'/api/events/{ident}')
    if not isinstance(event, dict) or event.get('id') != ident or event.get('camera') != camera:
        raise app.Problem('Événement inconnu pour cette caméra.', 404)
    return f'/api/events/{ident}/thumbnail.jpg'


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
    found, more = events(app, camera, start, limit, now) if limit > start else ([], False)
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
            'events': found, 'events_more': more, 'clip_max': CLIP_MAX}


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
