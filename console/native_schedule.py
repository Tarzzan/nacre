"""Programmation des captures natives : une heure et des jours par volume, sans jamais rien supprimer.

La console demande la capture au service natif par ses deux étapes habituelles, préparation puis validation : identité,
politique et capacité sont revérifiées par le service à chaque fois, et aucun de ses modules n'est modifié. Une
occurrence ne s'empile pas, ne se rattrape pas et ne se rejoue pas ; un plafond de points programmés arrête la
programmation tant que la suppression n'existe pas. Voir docs/NATIVE-SNAPSHOT-POLICY.md.
"""
import json
import re
import threading
import time

from native_retention import POINT, SCHEDULED, native, stored, volume

KEY = 'native-schedule:'
ACTOR = 'programmation'
# Au-delà de ce retard, l'occurrence est dite manquée : la console était arrêtée, rien n'est rattrapé.
GRACE = 900
INTERVAL = 20
CAP = 500
OUTCOMES = {'done': 'Capture créée.', 'missed': 'Occurrence manquée pendant un arrêt de la console : non rattrapée.'}
_lock = threading.Lock()


def defaults(app):
    from playback import zone
    return {'enabled': False, 'time': '02:00', 'weekdays': list(range(7)), 'timezone': zone(app)[0], 'cap': 30, 'next_run': None, 'last': None}


def read(app, identifier):
    value = stored(app, KEY, identifier, None)
    return {**defaults(app), **value} if isinstance(value, dict) else defaults(app)


def write(app, identifier, value):
    with app.database() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + identifier, json.dumps(value)))


def marked(app, identifier):
    """Points que la programmation a demandés pour ce volume, dans l'ordre de création."""
    value = stored(app, SCHEDULED, identifier, [])
    return [point for point in value if isinstance(point, str) and POINT.fullmatch(point)] if isinstance(value, list) else []


def present(status, identifier, scheduled):
    return [point['id'] for point in status.get('points', []) if point.get('volume') == identifier and point.get('id') in scheduled]


def listing(app, actor):
    status = app.native_storage('status', actor)
    schedules = []
    for item in status.get('volumes', []):
        value = read(app, item['id'])
        schedules.append({'volume': item['id'], **{key: value[key] for key in ('enabled', 'time', 'weekdays', 'timezone', 'cap', 'next_run', 'last')},
                          'points': len(present(status, item['id'], set(marked(app, item['id']))))})
    return {'connected': bool(status.get('connected')), 'schedules': schedules, 'defaults': defaults(app), 'confirmation': 'PROGRAMMER '}


def configure(app, body, actor):
    from protection import next_occurrence
    body = body if isinstance(body, dict) else {}
    item = volume(app, native(app, actor), body.get('volume'))
    base = defaults(app)
    enabled, hour, days, cap = body.get('enabled', False), body.get('time', base['time']), body.get('weekdays', base['weekdays']), body.get('cap', base['cap'])
    if type(enabled) is not bool:
        raise app.Problem('État de programmation invalide.')
    if not isinstance(hour, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hour):
        raise app.Problem('Heure invalide.')
    if not isinstance(days, list) or not days or any(type(day) is not int or day not in range(7) for day in days):
        raise app.Problem('Choisir au moins un jour valide.')
    if type(cap) is not int or not 1 <= cap <= CAP:
        raise app.Problem('Le plafond de points programmés doit être un entier de 1 à 500.')
    # Activer vaut consentement durable aux captures de ce volume : la confirmation est exigée à chaque enregistrement actif.
    if enabled and body.get('confirmation') != 'PROGRAMMER ' + item['id']:
        raise app.Problem('Recopier exactement la confirmation pour activer la programmation.')
    # Un nouveau réglage repart sans résultat précédent : l'alerte éventuelle se clôt.
    value = {'enabled': enabled, 'time': hour, 'weekdays': sorted(set(days)), 'timezone': base['timezone'], 'cap': cap, 'next_run': None, 'last': None}
    if enabled:
        value['next_run'] = next_occurrence(value)
    with _lock:
        write(app, item['id'], value)
    names = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.']
    app.audit(actor, 'Programmation des captures natives ' + ('activée' if enabled else 'désactivée'),
              item['id'] + (f' : {hour} ({value["timezone"]}), {" ".join(names[day] for day in value["weekdays"])}, plafond {cap} points' if enabled else ''))
    return {'volume': item['id'], **value}


def attempt(app, identifier, value, due, now):
    """Une occurrence : (résultat, explication). Seul « done » a créé un point."""
    if now - due > GRACE:
        return 'missed', OUTCOMES['missed']
    try:
        status = native(app, ACTOR)
        item = volume(app, status, identifier)
    except app.Problem as problem:
        return 'skipped', problem.message
    if not item.get('ready'):
        return 'skipped', 'Volume indisponible : ' + str(item.get('reason') or 'état inconnu') + '.'
    # Une seule opération native à la fois : l'occurrence est sautée, pas mise en attente.
    if any(action.get('volume') == identifier and action.get('status') in ('queued', 'running') for action in status.get('actions', [])) \
            or any(point.get('volume') == identifier and point.get('status') == 'creating' for point in status.get('points', [])) \
            or (item.get('family') == 'lvm' and any(job.get('status') in ('queued', 'running') for job in status.get('jobs', []))):
        return 'skipped', 'Une opération native était en cours sur ce volume : occurrence sautée.'
    scheduled = marked(app, identifier)
    kept = [point for point in scheduled if point in set(present(status, identifier, set(scheduled)))]
    if len(kept) >= value['cap']:
        return 'capped', f'Plafond de {value["cap"]} points programmés atteint : aucune capture tant qu’aucun point n’est retiré.'
    try:
        plan = app.native_storage('prepare', ACTOR, {'action': 'snapshot', 'volume': identifier})
    except app.Problem as problem:
        return 'refused', problem.message
    if not isinstance(plan, dict) or not isinstance(plan.get('id'), str) or not POINT.fullmatch(plan['id']) or not isinstance(plan.get('confirmation'), str):
        return 'refused', 'Plan de capture non reconnu.'
    # Noté avant la validation : un point créé dont la réponse se perd reste un point programmé.
    with app.database() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SCHEDULED + identifier, json.dumps(kept + [plan['id']])))
    try:
        app.native_storage('commit', ACTOR, {'plan': plan['id'], 'confirmation': plan['confirmation']})
    except app.Problem as problem:
        return 'refused', problem.message + ' Vérifier l’état des points du volume ; rien n’est rejoué.'
    return 'done', OUTCOMES['done']


def tick(app, now=None):
    """Lance les captures arrivées à leur heure. L'occurrence est consommée avant d'être tentée : jamais rejouée."""
    from protection import next_occurrence
    now = time.time() if now is None else now
    due = []
    with _lock:
        with app.database() as db:
            rows = db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (KEY + '%',)).fetchall()
        for row in rows:
            identifier = row['key'][len(KEY):]
            try:
                value = {**defaults(app), **json.loads(row['value'])}
                moment = value['next_run']
                if not value['enabled'] or type(moment) not in (int, float) or moment > now:
                    continue
                value['next_run'] = next_occurrence(value, now)
                value['last'] = {'ts': now, 'outcome': 'running', 'detail': 'Capture demandée au service natif.'}
                write(app, identifier, value)
                due.append((identifier, value, moment))
            except (ValueError, KeyError, TypeError):
                continue
    results = []
    for identifier, value, moment in due:
        # Hors du verrou : le service natif peut prendre du temps, et régler une programmation ne doit pas attendre.
        try:
            outcome, detail = attempt(app, identifier, value, moment, now)
        except Exception:
            outcome, detail = 'refused', 'Erreur interne pendant la programmation ; rien n’est rejoué.'
        with _lock:
            current = read(app, identifier)
            # Une programmation réglée entre-temps repart sans résultat : celui-ci ne la concerne plus.
            if (current.get('last') or {}).get('outcome') == 'running':
                write(app, identifier, {**current, 'last': {'ts': now, 'outcome': outcome, 'detail': detail[:300]}})
        app.audit(ACTOR, 'Capture native programmée' if outcome == 'done' else 'Capture native programmée non faite', identifier + ' : ' + detail)
        results.append((identifier, outcome))
    return results


def conditions(app):
    """Programmations dont la dernière occurrence n'a pas créé de point, pour le centre d'alertes."""
    found = []
    with app.database() as db:
        rows = db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (KEY + '%',)).fetchall()
    for row in rows:
        try:
            value = json.loads(row['value'])
            last = value.get('last') or {}
            if value.get('enabled') and last.get('outcome') in ('skipped', 'refused', 'capped'):
                found.append(('native-schedule:' + row['key'][len(KEY):], 'Capture native programmée non faite',
                              row['key'][len(KEY):] + ' : ' + str(last.get('detail', '')), 'native', 'warning', str(last.get('ts', ''))))
        except (ValueError, AttributeError):
            continue
    return found


def start(app):
    def loop():
        while True:
            try:
                tick(app)
            except Exception:
                pass
            time.sleep(INTERVAL)
    threading.Thread(target=loop, daemon=True, name='nacre-native-schedule').start()
