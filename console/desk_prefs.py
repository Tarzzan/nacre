"""Préférences du bureau par compte : widgets affichés, leur ordre, et le fond.

Seul réglage que tout compte, lecture seule comprise, peut enregistrer : il ne concerne que son propre affichage.
Rien d'autre n'est accepté ni stocké ; la valeur vit dans la table `settings` existante, sous une clé par compte.
"""
import json

WIDGETS = ('storage', 'services', 'camera', 'activity', 'memory', 'alerts', 'tasks')
DEFAULT = ('storage', 'services', 'camera', 'activity', 'memory')
BACKGROUNDS = ('nacre', 'lagon', 'sable', 'ardoise')


def key(name):
    return 'desk:' + name


def clean(value):
    """Lecture tolérante : une valeur ancienne ou abîmée retombe sur l'affichage d'origine, élément par élément."""
    value = value if isinstance(value, dict) else {}
    chosen = value.get('widgets')
    widgets = []
    for item in chosen if isinstance(chosen, list) else DEFAULT:
        if item in WIDGETS and item not in widgets:
            widgets.append(item)
    background = value.get('background')
    return {'widgets': widgets, 'background': background if background in BACKGROUNDS else BACKGROUNDS[0]}


def read(app, session):
    with app.database() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key(session['name']),)).fetchone()
    try:
        stored = json.loads(row[0]) if row else {}
    except ValueError:
        stored = {}
    return {**clean(stored), 'catalog': list(WIDGETS), 'backgrounds': list(BACKGROUNDS)}


def save(app, body, session):
    """Écriture stricte : uniquement des widgets connus, sans doublon, et un fond connu."""
    if not isinstance(body, dict) or set(body) - {'widgets', 'background'}:
        raise app.Problem('Préférences du bureau invalides.')
    widgets, background = body.get('widgets'), body.get('background')
    if not isinstance(widgets, list) or len(widgets) > len(WIDGETS) or any(not isinstance(w, str) or w not in WIDGETS for w in widgets) or len(set(widgets)) != len(widgets):
        raise app.Problem('Sélection de widgets invalide.')
    if not isinstance(background, str) or background not in BACKGROUNDS:
        raise app.Problem('Fond de bureau inconnu.')
    value = json.dumps({'widgets': widgets, 'background': background})
    with app.database() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key(session['name']), value))
    return read(app, session)
