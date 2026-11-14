"""Conservation des points natifs : une règle par volume, sa simulation, et la suppression explicite des points sortants.

Ce module enregistre la règle de conservation d'un volume et dit exactement quels points elle garderait, lesquels
sortiraient et lesquels sont protégés. La règle vit dans la table `settings` existante ; l'état des points vient du
service natif, lu tel quel. Ni la règle ni la simulation ne suppriment quoi que ce soit.

La suppression part toujours d'une simulation : la console la recalcule, vérifie qu'elle est celle qui était affichée,
puis demande au service natif un plan pour cette liste exacte. Le service revérifie tout et exige sa phrase de
confirmation. Voir docs/NATIVE-SNAPSHOT-POLICY.md.
"""
import json
import re
import time

import calendar_retention

KEY = 'native-retention:'
# Points créés par la programmation des captures, quand elle existera : tous les autres sont des captures manuelles.
SCHEDULED = 'native-scheduled:'
VOLUME = re.compile(r'[a-z][a-z0-9_-]{0,47}\Z')
POINT = re.compile(r'[a-f0-9]{32}\Z')
KEEP = 1000
BATCH = 50  # points par opération de suppression : la limite du service natif
STATES = {'creating': 'Création en cours.', 'uncertain': 'État à vérifier sur le stockage.', 'invalid': 'Point absent, modifié ou saturé.'}


def defaults(app):
    from playback import zone
    return {'keep_last': 7, 'calendar': {**calendar_retention.defaults(), 'timezone': zone(app)[0]}, 'manual': False}


def rule(app, body):
    """Règle validée : derniers points, périodes calendaires, et si les captures manuelles y sont soumises."""
    if not isinstance(body, dict):
        raise app.Problem('Règle de conservation non reconnue.')
    base = defaults(app)
    keep, manual, calendar = body.get('keep_last', base['keep_last']), body.get('manual', False), body.get('calendar', {})
    if type(keep) is not int or not 1 <= keep <= KEEP:
        raise app.Problem('Le nombre de derniers points à garder doit être un entier de 1 à 1 000.')
    if type(manual) is not bool:
        raise app.Problem('Choix invalide pour les captures manuelles.')
    if not isinstance(calendar, dict):
        raise app.Problem('Règle calendaire non reconnue.')
    return {'keep_last': keep, 'calendar': calendar_retention.validate(app, {**base['calendar'], **calendar}), 'manual': manual}


def native(app, actor):
    status = app.native_storage('status', actor)
    if not status.get('connected'):
        raise app.Problem('Le service de stockage natif n’est pas activé sur ce matériel.', 503)
    return status


def volume(app, status, identifier):
    if isinstance(identifier, str) and VOLUME.fullmatch(identifier):
        for item in status.get('volumes', []):
            if item.get('id') == identifier:
                return item
    raise app.Problem('Volume natif inconnu.', 404)


def stored(app, prefix, identifier, fallback):
    with app.database() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (prefix + identifier,)).fetchone()
    try:
        return json.loads(row['value']) if row else fallback
    except ValueError:
        return fallback


def listing(app, actor):
    """Règle de chaque volume inscrit ; sans service natif, une liste vide plutôt qu'une erreur."""
    import native_auto
    status = app.native_storage('status', actor)
    policies = []
    for item in status.get('volumes', []):
        saved = stored(app, KEY, item['id'], None)
        try:
            policies.append({'volume': item['id'], 'saved': saved is not None, **rule(app, saved or {})})
        except app.Problem:
            saved = None
            policies.append({'volume': item['id'], 'saved': False, **defaults(app)})
        policies[-1]['auto'] = native_auto.public(app, status, item, saved)
    return {'connected': bool(status.get('connected')), 'policies': policies, 'defaults': defaults(app), 'deletion': status.get('deletion') is True,
            'auto_phrase': native_auto.PHRASE, 'auto_floor': native_auto.FLOOR, 'batch': BATCH}


def save(app, body, actor):
    body = body if isinstance(body, dict) else {}
    item, value = volume(app, native(app, actor), body.get('volume')), rule(app, body)
    with app.database() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + item['id'], json.dumps(value)))
    periods = ', '.join(f'{value["calendar"][key]} {label}' for key, label in (('daily', 'jours'), ('weekly', 'semaines'), ('monthly', 'mois')) if value['calendar'][key])
    app.audit(actor, 'Règle de conservation des points natifs enregistrée', f'{item["id"]} : {value["keep_last"]} derniers points' + (f', {periods}' if periods else '')
              + (' ; captures manuelles comprises' if value['manual'] else '') + ' ; aucune suppression')
    import native_auto
    stopped = native_auto.rule_saved(app, item['id'], value, actor)
    return {'volume': item['id'], 'saved': True, **value, 'auto': native_auto.public(app, native(app, actor), item, value), 'auto_stopped': stopped}


def selection(status, item, value, scheduled, now):
    """Répartit les points d'un volume : gardés (avec leurs motifs), sortants, protégés (avec la raison)."""
    # Une restauration en cours ou incertaine sur ce volume protège tous ses points : la console ne sait pas lequel elle lit.
    busy = any(action.get('volume') == item['id'] and action.get('action') == 'clone' and action.get('status') in ('queued', 'running', 'uncertain')
               for action in status.get('actions', []))
    values, protected = [], []
    for point in status.get('points', []):
        identifier, created = point.get('id'), point.get('created')
        if point.get('volume') != item['id'] or not isinstance(identifier, str) or not POINT.fullmatch(identifier):
            continue
        public = {'id': identifier, 'created': created, 'manual': identifier not in scheduled}
        if point.get('status') != 'ready':
            reason = STATES.get(point.get('status'), 'État inconnu.') + ' Jamais proposé à la suppression.'
        elif type(created) not in (int, float) or created > now:
            reason = 'Date de création absente ou dans le futur.'
        elif busy:
            reason = 'Une restauration est en cours ou à vérifier sur ce volume.'
        elif public['manual'] and not value['manual']:
            reason = 'Capture manuelle : la règle ne porte que sur les captures programmées.'
        else:
            values.append((created, identifier, public))
            continue
        protected.append({**public, 'reason': reason})
    values.sort(reverse=True)
    reasons = calendar_retention.choose(values, value['keep_last'], value['calendar'])
    return {'keep': [{**public, 'reasons': reasons[identifier]} for _, identifier, public in values if identifier in reasons],
            'remove': [public for _, identifier, public in reversed(values) if identifier not in reasons],
            'protected': sorted(protected, key=lambda point: (type(point['created']) in (int, float), point['created'] if type(point['created']) in (int, float) else 0, point['id']), reverse=True),
            'busy': busy}


def simulate(app, body, actor):
    """Ce que la règle donnée ferait des points existants. Lecture seule : rien n'est enregistré ni supprimé.

    `deletion` dit seulement si le service natif de ce matériel accepte de supprimer des points.
    """
    body = body if isinstance(body, dict) else {}
    status = native(app, actor)
    item, value = volume(app, status, body.get('volume')), rule(app, body)
    scheduled = stored(app, SCHEDULED, item['id'], [])
    now = time.time()
    return {'volume': item['id'], 'name': item.get('name', item['id']), 'rule': value, 'at': now, 'deletion': status.get('deletion') is True,
            **selection(status, item, value, set(scheduled) if isinstance(scheduled, list) else set(), now)}


def forget(app, identifier, deleted):
    """Les points supprimés quittent aussi la note des points programmés."""
    marks = stored(app, SCHEDULED, identifier, None)
    if deleted and isinstance(marks, list):
        with app.database() as db:
            db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps([point for point in marks if point not in deleted]), SCHEDULED + identifier))


def prune_prepare(app, body, actor):
    """Plan de suppression des points sortants de la simulation affichée, cinquante au plus, les plus anciens d'abord."""
    body = body if isinstance(body, dict) else {}
    result = simulate(app, body, actor)
    if not result['deletion']:
        raise app.Problem('La suppression de points n’est pas accordée sur ce matériel.', 409)
    leaving = result['remove']
    if body.get('expected') != [point['id'] for point in leaving]:
        raise app.Problem('Les points ont changé depuis la simulation. Simuler de nouveau avant de supprimer.', 409)
    if not leaving:
        raise app.Problem('Aucun point ne sort de cette règle : rien à supprimer.')
    plan = app.native_storage('prepare', actor, {'action': 'delete', 'volume': result['volume'], 'points': [point['id'] for point in leaving[:BATCH]]})
    manual = {point['id']: point['manual'] for point in leaving}
    return {**plan, 'name': result['name'], 'remaining': len(leaving) - len(leaving[:BATCH]),
            'points': [{'id': point['id'], 'created': point.get('created'), 'manual': manual.get(point['id'], True)} for point in plan.get('points', [])]}


def prune_commit(app, body, actor):
    """Valider un plan de suppression. Le service natif supprime, s'arrête au premier refus et dit ce qu'il a fait."""
    body = body if isinstance(body, dict) else {}
    item = volume(app, native(app, actor), body.get('volume'))
    plan, confirmation = body.get('plan'), body.get('confirmation')
    if not isinstance(plan, str) or not POINT.fullmatch(plan) or not isinstance(confirmation, str) or not confirmation.startswith('SUPPRIMER '):
        raise app.Problem('Recopier exactement la phrase du plan de suppression.')
    result = app.native_storage('commit', actor, {'plan': plan, 'confirmation': confirmation})
    deleted, uncertain, kept = (result.get(key) if isinstance(result.get(key), list) else [] for key in ('deleted', 'uncertain', 'kept'))
    forget(app, item['id'], deleted)
    detail = f'{item["id"]} : {len(deleted)} supprimé{"s" if len(deleted) > 1 else ""}'
    if not result.get('ok'):
        detail += f', {len(uncertain)} à vérifier, {len(kept)} non touché{"s" if len(kept) > 1 else ""} ; ' + str(result.get('reason', ''))
    app.audit(actor, 'Points natifs supprimés' if result.get('ok') else 'Suppression de points natifs interrompue', detail)
    return {'volume': item['id'], 'name': item.get('name', item['id']), 'ok': bool(result.get('ok')), 'deleted': deleted, 'uncertain': uncertain, 'kept': kept,
            'reason': str(result.get('reason', ''))}
