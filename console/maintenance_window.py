"""Fenêtre quotidienne de démarrage, évaluée dans le fuseau de la règle."""
from datetime import datetime
import re
import time
from zoneinfo import ZoneInfo


def defaults():
    return {'enabled':False,'start':'02:00','end':'05:00'}


def validate(app, value):
    if not isinstance(value,dict) or set(value)-set(defaults()):
        raise app.Problem('Créneau de nettoyage non reconnu.')
    rule={**defaults(),**value}
    if type(rule['enabled']) is not bool:raise app.Problem('État du créneau invalide.')
    for key in ('start','end'):
        if not isinstance(rule[key],str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',rule[key]):
            raise app.Problem('Heures du créneau attendues au format HH:MM.')
    if rule['enabled'] and rule['start']==rule['end']:
        raise app.Problem('Le début et la fin du créneau doivent être différents.')
    return rule


def allows(rule, timezone, now=None):
    if not rule['enabled']:return True
    clock=datetime.fromtimestamp(time.time() if now is None else now,ZoneInfo(timezone)).strftime('%H:%M')
    start,end=rule['start'],rule['end']
    # Début inclus, fin exclue. Une fenêtre nocturne traverse minuit.
    return start<=clock<end if start<end else clock>=start or clock<end
