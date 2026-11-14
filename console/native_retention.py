"""Conservation des points natifs : une règle par volume et sa simulation. Rien n'est supprimé.

Le service natif sait créer un point et le restaurer, pas le supprimer. Ce module prépare la suite sans y toucher : il
enregistre la règle de conservation d'un volume et dit exactement quels points elle garderait, lesquels sortiraient et
lesquels sont protégés. La règle vit dans la table `settings` existante ; l'état des points vient du service natif, lu
tel quel. Voir docs/NATIVE-SNAPSHOT-POLICY.md.
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
    status = app.native_storage('status', actor)
    policies = []
    for item in status.get('volumes', []):
        saved = stored(app, KEY, item['id'], None)
        try:
            policies.append({'volume': item['id'], 'saved': saved is not None, **rule(app, saved or {})})
        except app.Problem:
            policies.append({'volume': item['id'], 'saved': False, **defaults(app)})
    return {'connected': bool(status.get('connected')), 'policies': policies, 'defaults': defaults(app), 'deletion': False}


def save(app, body, actor):
    body = body if isinstance(body, dict) else {}
    item, value = volume(app, native(app, actor), body.get('volume')), rule(app, body)
    with app.database() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + item['id'], json.dumps(value)))
    periods = ', '.join(f'{value["calendar"][key]} {label}' for key, label in (('daily', 'jours'), ('weekly', 'semaines'), ('monthly', 'mois')) if value['calendar'][key])
    app.audit(actor, 'Règle de conservation des points natifs enregistrée', f'{item["id"]} : {value["keep_last"]} derniers points' + (f', {periods}' if periods else '')
              + (' ; captures manuelles comprises' if value['manual'] else '') + ' ; aucune suppression')
    return {'volume': item['id'], 'saved': True, **value}


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
    """Ce que la règle donnée ferait des points existants. Lecture seule : rien n'est enregistré ni supprimé."""
    body = body if isinstance(body, dict) else {}
    status = native(app, actor)
    item, value = volume(app, status, body.get('volume')), rule(app, body)
    scheduled = stored(app, SCHEDULED, item['id'], [])
    now = time.time()
    return {'volume': item['id'], 'name': item.get('name', item['id']), 'rule': value, 'at': now, 'deletion': False,
            **selection(status, item, value, set(scheduled) if isinstance(scheduled, list) else set(), now)}
