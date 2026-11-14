"""Conservation automatique des points natifs : la règle d'un volume, appliquée après ses captures programmées.

Sur demande explicite par volume, et seulement là où le service natif accorde la suppression. Un passage a lieu après
une capture programmée réussie, ou quand la programmation bute sur son plafond. Il recalcule ce que la règle activée
garde, puis demande au service natif de supprimer les points programmés qui sortent, par son plan habituel.

Garde-fous : une capture manuelle n'est jamais supprimée automatiquement ; un passage qui supprimerait plus de points
que le maximum choisi ne supprime rien ; au premier refus ou arrêt, la conservation automatique se suspend et attend
une réactivation ; rien n'est jamais rejoué. Voir docs/NATIVE-SNAPSHOT-POLICY.md.
"""
import json
import time

from native_retention import BATCH, KEY as RULE, POINT, SCHEDULED, forget, native, rule as checked, selection, stored, volume

KEY = 'native-auto:'
ACTOR = 'programmation'
PHRASE = 'AUTOMATISER '
FLOOR = 5  # marge du maximum proposé, au-dessus de ce que la règle ferait sortir aujourd'hui
TITLES = {'done': 'Conservation automatique appliquée', 'skipped': 'Conservation automatique sautée', 'suspended': 'Conservation automatique suspendue'}


def read(app, identifier):
    value = stored(app, KEY, identifier, None)
    return {'enabled': False, 'cap': FLOOR, 'rule': None, 'actor': '', 'since': None, 'reason': '', 'last': None, **(value if isinstance(value, dict) else {})}


def write(app, identifier, value):
    with app.database() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + identifier, json.dumps(value)))


def core(value):
    """Ce qui fait une règle pour la conservation automatique : les captures manuelles n'en font jamais partie."""
    return {'keep_last': value['keep_last'], 'calendar': value['calendar']}


def leaving(app, status, item, value, now):
    """Points programmés que la règle ne garde plus, du plus ancien au plus récent, et si une restauration protège le volume."""
    marks = stored(app, SCHEDULED, item['id'], [])
    result = selection(status, item, {**checked(app, value), 'manual': False}, set(marks) if isinstance(marks, list) else set(), now)
    return [point['id'] for point in result['remove']], result['busy']


def public(app, status, item, saved):
    """État montré à l'administrateur ; `pending` compte ce que la règle enregistrée ferait sortir aujourd'hui."""
    value = read(app, item['id'])
    pending = None
    if saved is not None:
        try:
            pending = len(leaving(app, status, item, saved, time.time())[0])
        except app.Problem:
            pending = None
    return {**{key: value[key] for key in ('enabled', 'cap', 'reason', 'last', 'since')}, 'pending': pending}


def configure(app, body, actor):
    body = body if isinstance(body, dict) else {}
    status = native(app, actor)
    item = volume(app, status, body.get('volume'))
    identifier, enabled, current = item['id'], body.get('enabled'), read(app, item['id'])
    if type(enabled) is not bool:
        raise app.Problem('Préciser si la conservation automatique est activée.')
    saved = stored(app, RULE, identifier, None)
    if not enabled:
        write(app, identifier, {**current, 'enabled': False, 'reason': ''})
        app.audit(actor, 'Conservation automatique désactivée', identifier)
        return {'volume': identifier, **public(app, status, item, saved)}
    if status.get('deletion') is not True:
        raise app.Problem('La suppression de points n’est pas accordée sur ce matériel.', 409)
    if saved is None:
        raise app.Problem('Enregistrer d’abord la règle de conservation de ce volume.', 409)
    value, cap = checked(app, saved), body.get('cap')
    if type(cap) is not int or not 1 <= cap <= BATCH:
        raise app.Problem(f'Le maximum par passage doit être un entier de 1 à {BATCH}.')
    if body.get('confirmation') != PHRASE + identifier:
        raise app.Problem(f'Recopier exactement « {PHRASE}{identifier} » pour activer.')
    write(app, identifier, {'enabled': True, 'cap': cap, 'rule': core(value), 'actor': actor, 'since': time.time(), 'reason': '', 'last': None})
    app.audit(actor, 'Conservation automatique activée', f'{identifier} : {value["keep_last"]} derniers points et périodes de la règle enregistrée, au plus {cap} par passage ; captures manuelles jamais supprimées')
    return {'volume': identifier, **public(app, status, item, saved)}


def rule_saved(app, identifier, value, actor):
    """Une règle enregistrée différente de celle qui a été activée met fin à la conservation automatique."""
    current = read(app, identifier)
    if not current['enabled'] or current.get('rule') == core(value):
        return False
    write(app, identifier, {**current, 'enabled': False, 'reason': ''})
    app.audit(actor, 'Conservation automatique désactivée', identifier + ' : règle modifiée, à réactiver')
    return True


def attempt(app, identifier, value, now):
    """Un passage : (résultat, explication, nombre de points supprimés). Seul « suspended » désactive."""
    try:
        status = native(app, ACTOR)
        item = volume(app, status, identifier)
    except app.Problem as problem:
        return 'skipped', problem.message + ' Passage sauté.', 0
    if status.get('deletion') is not True:
        return 'suspended', 'Le service natif n’accorde plus la suppression de points.', 0
    try:
        wanted, busy = leaving(app, status, item, value['rule'], now)
    except (app.Problem, KeyError, TypeError):
        return 'suspended', 'Règle activée illisible.', 0
    if busy:
        return 'skipped', 'Une restauration est en cours ou à vérifier sur ce volume : passage sauté.', 0
    if not wanted:
        return 'nothing', 'Règle vérifiée : aucun point à supprimer.', 0
    if len(wanted) > value['cap']:
        return 'suspended', f'{len(wanted)} points sortiraient, plus que le maximum de {value["cap"]} par passage : rien n’a été supprimé.', 0
    try:
        plan = app.native_storage('prepare', ACTOR, {'action': 'delete', 'volume': identifier, 'points': wanted})
    except app.Problem as problem:
        return 'suspended', problem.message + ' Rien n’a été supprimé.', 0
    if not isinstance(plan, dict) or not isinstance(plan.get('id'), str) or not POINT.fullmatch(plan['id']) or not isinstance(plan.get('confirmation'), str) \
            or [point.get('id') for point in plan.get('points', []) if isinstance(point, dict)] != wanted:
        return 'suspended', 'Plan de suppression non reconnu. Rien n’a été supprimé.', 0
    try:
        result = app.native_storage('commit', ACTOR, {'plan': plan['id'], 'confirmation': plan['confirmation']})
    except app.Problem as problem:
        return 'suspended', problem.message + ' Vérifier l’état des points du volume ; rien n’est rejoué.', 0
    deleted = [point for point in result.get('deleted', []) if point in wanted] if isinstance(result.get('deleted'), list) else []
    forget(app, identifier, deleted)
    count = f'{len(deleted)} point{"s" if len(deleted) > 1 else ""} supprimé{"s" if len(deleted) > 1 else ""}'
    if result.get('ok') is True and len(deleted) == len(wanted):
        return 'done', count + '.', len(deleted)
    return 'suspended', f'{count} sur {len(wanted)}. ' + str(result.get('reason') or 'Vérifier le stockage.'), len(deleted)


def run(app, identifier, now=None):
    """Passage après une capture programmée. Ne lève jamais : la programmation ne doit pas en dépendre."""
    value = read(app, identifier)
    if not value['enabled'] or not isinstance(value.get('rule'), dict):
        return None
    now = time.time() if now is None else now
    try:
        outcome, detail, deleted = attempt(app, identifier, value, now)
    except Exception:
        outcome, detail, deleted = 'suspended', 'Erreur interne pendant la conservation automatique ; rien n’est rejoué.', 0
    current = read(app, identifier)
    # Une conservation réglée entre-temps n'est pas concernée par ce passage.
    if current['enabled'] and current.get('since') == value.get('since'):
        current['last'] = {'ts': now, 'outcome': outcome, 'detail': detail[:300], 'deleted': deleted}
        if outcome == 'suspended':
            current.update(enabled=False, reason=detail[:300])
        write(app, identifier, current)
    if outcome in TITLES:
        app.audit(ACTOR, TITLES[outcome], identifier + ' : ' + detail)
    return outcome


def conditions(app):
    """Conservations automatiques suspendues, pour le centre d'alertes ; closes à la réactivation ou à la désactivation."""
    found = []
    with app.database() as db:
        rows = db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (KEY + '%',)).fetchall()
    for row in rows:
        try:
            value = json.loads(row['value'])
            if not value.get('enabled') and value.get('reason'):
                found.append(('native-auto:' + row['key'][len(KEY):], 'Conservation automatique suspendue', row['key'][len(KEY):] + ' : ' + str(value['reason']),
                              'native', 'warning', str((value.get('last') or {}).get('ts', ''))))
        except (ValueError, AttributeError):
            continue
    return found


def disable_after_recovery(db):
    """Après une récupération de l'installation, la base peut dater : toute conservation automatique attend une réactivation."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone():
        return
    for key, raw in db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (KEY + '%',)).fetchall():
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('enabled'):
            value.update(enabled=False, reason='Installation récupérée : vérifier les points et la règle avant de réactiver.')
            db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(value), key))
