"""Créneaux de démarrage, évalués dans le fuseau et le jour de départ."""
from datetime import datetime
import re
import time
from zoneinfo import ZoneInfo


def defaults():
    return {'enabled':False,'start':'02:00','end':'05:00','mode':'daily','week':[]}


def valid_hours(app, value):
    for key in ('start','end'):
        if not isinstance(value.get(key),str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value[key]):
            raise app.Problem('Heures du créneau attendues au format HH:MM.')


def validate(app, value):
    if not isinstance(value,dict) or set(value)-set(defaults()):
        raise app.Problem('Créneau de nettoyage non reconnu.')
    rule={**defaults(),**value}
    if type(rule['enabled']) is not bool:raise app.Problem('État du créneau invalide.')
    if rule['mode'] not in ('daily','weekly'):raise app.Problem('Rythme du créneau invalide.')
    valid_hours(app,rule)
    if rule['enabled'] and rule['mode']=='daily' and rule['start']==rule['end']:
        raise app.Problem('Le début et la fin du créneau doivent être différents.')
    if not isinstance(rule['week'],list) or len(rule['week'])>7:
        raise app.Problem('Choisissez au plus un créneau par jour de la semaine.')
    days=set()
    for entry in rule['week']:
        if not isinstance(entry,dict) or set(entry)!={'day','start','end'}:
            raise app.Problem('Créneau hebdomadaire non reconnu.')
        day=entry['day']
        if type(day) is not int or not 0<=day<=6 or day in days:
            raise app.Problem('Jour invalide ou répété : lundi vaut 0, dimanche vaut 6.')
        days.add(day);valid_hours(app,entry)
        if entry['start']==entry['end']:raise app.Problem('Le début et la fin du créneau doivent être différents.')
    if rule['enabled'] and rule['mode']=='weekly' and not days:
        raise app.Problem('Choisissez au moins un jour pour le créneau hebdomadaire.')
    rule['week']=sorted((dict(entry) for entry in rule['week']),key=lambda entry:entry['day'])
    return rule


def allows(rule, timezone, now=None):
    if not rule['enabled']:return True
    local=datetime.fromtimestamp(time.time() if now is None else now,ZoneInfo(timezone))
    clock=local.strftime('%H:%M')
    if rule.get('mode','daily')=='weekly':
        today=local.weekday();previous=(today-1)%7
        for entry in rule['week']:
            start,end=entry['start'],entry['end']
            if start<end:
                if entry['day']==today and start<=clock<end:return True
            elif (entry['day']==today and clock>=start) or (entry['day']==previous and clock<end):return True
        return False
    start,end=rule['start'],rule['end']
    # Début inclus, fin exclue. Une fenêtre nocturne traverse minuit.
    return start<=clock<end if start<end else clock>=start or clock<end
