"""Créneaux de démarrage, évalués dans le fuseau et le jour de départ."""
from datetime import date, datetime, timedelta
import re
import time
from zoneinfo import ZoneInfo


def defaults():
    return {'enabled':False,'start':'02:00','end':'05:00','mode':'daily','week':[],'extra':[],'exceptions':[]}


def valid_hours(app, value):
    for key in ('start','end'):
        if not isinstance(value.get(key),str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value[key]):
            raise app.Problem('Heures du créneau attendues au format HH:MM.')


def slots(app, value):
    if not isinstance(value,list) or len(value)>24:
        raise app.Problem('Au plus 24 plages par jour sont acceptées.')
    seen=set()
    for entry in value:
        if not isinstance(entry,dict) or set(entry)!={'start','end'}:
            raise app.Problem('Plage horaire non reconnue.')
        valid_hours(app,entry)
        pair=(entry['start'],entry['end'])
        if pair[0]==pair[1]:raise app.Problem('Le début et la fin du créneau doivent être différents.')
        if pair in seen:raise app.Problem('Une même plage est répétée.')
        seen.add(pair)
    return [dict(start=start,end=end) for start,end in sorted(seen)]


def validate(app, value):
    if not isinstance(value,dict) or set(value)-set(defaults()):
        raise app.Problem('Créneau de nettoyage non reconnu.')
    rule={**defaults(),**value}
    if type(rule['enabled']) is not bool:raise app.Problem('État du créneau invalide.')
    if rule['mode'] not in ('daily','weekly'):raise app.Problem('Rythme du créneau invalide.')
    valid_hours(app,rule)
    if rule['enabled'] and rule['mode']=='daily' and rule['start']==rule['end']:
        raise app.Problem('Le début et la fin du créneau doivent être différents.')
    if not isinstance(rule['week'],list) or len(rule['week'])>7*24:
        raise app.Problem('Au plus 24 plages par jour sont acceptées.')
    days={}
    for entry in rule['week']:
        if not isinstance(entry,dict) or set(entry)!={'day','start','end'}:
            raise app.Problem('Créneau hebdomadaire non reconnu.')
        day=entry['day']
        if type(day) is not int or not 0<=day<=6:
            raise app.Problem('Jour invalide : lundi vaut 0, dimanche vaut 6.')
        days.setdefault(day,[]).append({key:entry[key] for key in ('start','end')})
    rule['week']=[dict(day=day,**entry) for day in sorted(days) for entry in slots(app,days[day])]
    rule['extra']=slots(app,rule['extra'])
    if rule['mode']=='daily' and rule['extra']:
        slots(app,[{key:rule[key] for key in ('start','end')},*rule['extra']])
    if not isinstance(rule['exceptions'],list) or len(rule['exceptions'])>366:
        raise app.Problem('Au plus 366 exceptions datées sont acceptées.')
    exceptions={}
    for entry in rule['exceptions']:
        if not isinstance(entry,dict) or set(entry)!={'date','slots'}:
            raise app.Problem('Exception datée non reconnue.')
        value=entry['date']
        if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
            raise app.Problem('Date attendue au format AAAA-MM-JJ.')
        try:date.fromisoformat(value)
        except ValueError:raise app.Problem('Date inexistante.')
        if value in exceptions:raise app.Problem('Une date ne peut avoir qu’une exception.')
        exceptions[value]=slots(app,entry['slots'])
    rule['exceptions']=[dict(date=value,slots=exceptions[value]) for value in sorted(exceptions)]
    if rule['enabled'] and rule['mode']=='weekly' and not days and not any(exceptions.values()):
        raise app.Problem('Choisissez au moins un jour pour le créneau hebdomadaire.')
    return rule


def allows(rule, timezone, now=None):
    if not rule['enabled']:return True
    local=datetime.fromtimestamp(time.time() if now is None else now,ZoneInfo(timezone))
    clock=local.strftime('%H:%M')
    exceptions={entry['date']:entry['slots'] for entry in rule.get('exceptions',[])}
    def starting(day):
        if day.isoformat() in exceptions:return exceptions[day.isoformat()]
        if rule.get('mode','daily')=='weekly':return [e for e in rule['week'] if e['day']==day.weekday()]
        return [rule,*rule.get('extra',[])]
    today=local.date()
    for entry in starting(today):
        start,end=entry['start'],entry['end']
        if (start<=clock<end if start<end else clock>=start):return True
    # Toute exception remplace la date civile entière, y compris un report de la veille.
    if today.isoformat() in exceptions:return False
    if today>date.min:
        for entry in starting(today-timedelta(days=1)):
            if entry['start']>entry['end'] and clock<entry['end']:return True
    return False


def preview(app, body, now=None):
    """Projection en lecture seule sur 168 h, balayée en UTC pour respecter les DST."""
    import calendar_retention
    if not isinstance(body,dict) or set(body)-{'window','timezone'}:
        raise app.Problem('Paramètres de calendrier non reconnus.')
    rule=validate(app,body.get('window',{}))
    timezone=calendar_retention.validate(app,{'timezone':body.get('timezone','UTC')})['timezone']
    start=time.time() if now is None else now
    until=start+7*86400
    result={'generated_at':start,'until':until,'timezone':timezone,'enabled':rule['enabled'],'windows':[]}
    if not rule['enabled']:return result
    opened=allows(rule,timezone,start);opening=start if opened else None
    # Toutes les heures configurées sont à la minute. Le balayage UTC inclut
    # chacune des occurrences d'une heure répétée et saute les heures absentes.
    cursor=(int(start)//60+1)*60
    while cursor<until:
        current=allows(rule,timezone,cursor)
        if current and not opened:opening=cursor
        if opened and not current:
            result['windows'].append({'start':opening,'end':cursor,'ongoing':opening==start,'continues':False})
        opened=current;cursor+=60
    if opened:
        result['windows'].append({'start':opening,'end':until,'ongoing':opening==start,'continues':allows(rule,timezone,until)})
    return result
