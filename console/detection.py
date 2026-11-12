"""Détection d’une caméra : activation et types d’objets suivis, appliqués sans redémarrer Frigate."""
import json
import re
import subprocess
import time

LABEL = re.compile(r'[a-z][a-z0-9_ ]{0,31}\Z')
TRACK_MAX = 32
# Types utiles à la surveillance. Seuls ceux que le modèle installé sait reconnaître sont proposés.
GROUPS = (
    ('people', 'Personnes', ('person',)),
    ('vehicles', 'Véhicules', ('car', 'truck', 'motorcycle', 'bicycle', 'bus', 'train', 'boat', 'airplane')),
    ('animals', 'Animaux', ('dog', 'cat', 'bird', 'horse', 'sheep', 'cow', 'bear', 'deer', 'fox', 'rabbit', 'raccoon', 'squirrel')),
    ('items', 'Objets', ('package', 'backpack', 'handbag', 'suitcase', 'umbrella')),
)
UNAVAILABLE = 'Détection indisponible : le service vidéo ne fournit pas son état.'


def labels(values):
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and LABEL.fullmatch(v)))


def runtime(app, camera):
    """État réellement appliqué par Frigate, pas celui du fichier : liste blanche stricte."""
    try:
        payload = app.video_json('/api/config')
    except (app.Problem, OSError, ValueError):
        raise app.Problem(UNAVAILABLE, 503) from None
    entry = payload.get('cameras', {}).get(camera) if isinstance(payload, dict) and isinstance(payload.get('cameras'), dict) else None
    objects = entry.get('objects') if isinstance(entry, dict) else None
    detect = entry.get('detect') if isinstance(entry, dict) else None
    if not isinstance(objects, dict) or not isinstance(objects.get('track'), list) or not isinstance(detect, dict) or type(detect.get('enabled')) is not bool:
        raise app.Problem(UNAVAILABLE, 503)
    model = []
    detectors = payload.get('detectors')
    for detector in detectors.values() if isinstance(detectors, dict) else ():
        labelmap = detector.get('model', {}).get('labelmap') if isinstance(detector, dict) and isinstance(detector.get('model'), dict) else None
        if isinstance(labelmap, dict):
            model += labelmap.values()
    filters = objects.get('filters')
    return {'enabled': detect['enabled'], 'tracked': labels(objects['track']), 'model': set(labels(model)),
            'filters': set(filters) if isinstance(filters, dict) else set()}


def state(app, camera, live=None):
    live = live or runtime(app, camera)
    groups, known = [], set()
    for ident, name, members in GROUPS:
        known.update(members)
        offered = [label for label in members if label in live['model'] or label in live['tracked']]
        if offered:
            groups.append({'id': ident, 'name': name, 'labels': offered})
    # Un type suivi hors catalogue reste visible pour pouvoir être retiré.
    others = [label for label in live['tracked'] if label not in known]
    if others:
        groups.append({'id': 'others', 'name': 'Autres types déjà suivis', 'labels': others})
    return {'enabled': live['enabled'], 'tracked': live['tracked'], 'groups': groups}


def applied(live, enabled, track):
    # Frigate lit le filtre de chaque type suivi : un type sans filtre ne doit jamais passer pour appliqué.
    return live['enabled'] is enabled and set(live['tracked']) == set(track) and set(track) <= live['filters']


def apply(app, body, actor):
    from cameras import VALIDATE, config, identifier
    camera = identifier(app, body.get('camera'))
    enabled, track = body.get('enabled'), body.get('track')
    if type(enabled) is not bool or not isinstance(track, list) or not 1 <= len(track) <= TRACK_MAX or any(not isinstance(label, str) for label in track) or len(set(track)) != len(track):
        raise app.Problem('Choisissez au moins un type d’objet à suivre.')
    live = runtime(app, camera)
    offered = [label for group in state(app, camera, live)['groups'] for label in group['labels']]
    if any(label not in offered for label in track):
        raise app.Problem('Type d’objet non proposé pour cette caméra.')
    track = [label for label in offered if label in track]
    path = app.ROOT / 'state/frigate/config.yml'
    original = path.read_bytes()
    document = config(app)
    entry = document['cameras'][camera]
    for section in ('objects', 'detect'):
        if not isinstance(entry.get(section), dict):
            entry[section] = {}
    saved = entry['objects'].get('track') == track and entry['detect'].get('enabled') is enabled
    if saved and applied(live, enabled, track):
        return {'message': 'Aucun changement : ce réglage est déjà appliqué.'}
    entry['objects']['track'] = track
    entry['detect']['enabled'] = enabled
    try:
        app.compose('exec', '-T', 'video', 'python3', '-c', VALIDATE, data=json.dumps(document), timeout=30)
    except (app.Problem, OSError, subprocess.TimeoutExpired):
        raise app.Problem('Frigate n’a pas accepté ce réglage. Rien n’a été modifié.', 503) from None
    if path.read_bytes() != original:
        raise app.Problem('La configuration a changé entre-temps. Réessayez.', 409)
    app.private_write(app.STATE / 'config-avant-detection.yml', original.decode())
    app.private_write(path, json.dumps(document, indent=2) + '\n')
    detail = f"{camera} : {'active' if enabled else 'en pause'} ; {', '.join(track)}"
    if set(live['tracked']) != set(track) or not set(track) <= live['filters']:
        # Application en mémoire seulement : Nacre reste l’unique rédacteur du fichier.
        # Le filtre vide donne à chaque nouveau type les seuils par défaut qu’il aurait au démarrage.
        try:
            answer = app.video_put('/api/config/set', {'requires_restart': 0, 'skip_save': True,
                'update_topic': f'config/cameras/{camera}/objects',
                'config_data': {'cameras': {camera: {'objects': {'track': track, 'filters': {label: {} for label in track}}}}}})
            if not isinstance(answer, dict) or answer.get('success') is not True:
                raise app.Problem('Refus.', 503)
        except app.Problem:
            app.private_write(path, original.decode())
            raise app.Problem('Frigate n’a pas appliqué ce réglage. La configuration précédente est rétablie.', 503) from None
    confirmed = False
    try:
        if live['enabled'] is not enabled:
            # Commande de Frigate lui-même : il la mémorise et la rejoue à son prochain démarrage.
            app.video_command(camera + '/detect/set', 'ON' if enabled else 'OFF')
        for _ in range(12):
            if applied(runtime(app, camera), enabled, track):
                confirmed = True
                break
            time.sleep(0.5)
    except app.Problem:
        pass
    if not confirmed:
        app.audit(actor, 'Détection enregistrée, application non confirmée', detail)
        raise app.Problem('Réglage enregistré, mais son application par Frigate n’est pas confirmée. Actualisez la page avant toute nouvelle action.', 503)
    app.audit(actor, 'Détection réglée', detail)
    return {'message': 'Détection mise à jour, sans interruption de l’enregistrement.'}
