"""Union des derniers points et des dernières périodes contenant des captures."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def defaults():
    return {'daily':0,'weekly':0,'monthly':0,'timezone':'UTC'}


def validate(app, value):
    if not isinstance(value,dict) or set(value)-set(defaults()):
        raise app.Problem('Règle calendaire non reconnue.')
    rule={**defaults(),**value}
    for key in ('daily','weekly','monthly'):
        if type(rule[key]) is not int or not 0<=rule[key]<=1000000:
            raise app.Problem('Les nombres de jours, semaines et mois doivent être des entiers de 0 à 1 000 000.')
    zone=rule['timezone']
    if not isinstance(zone,str) or len(zone)>100:
        raise app.Problem('Fuseau horaire de conservation invalide.')
    try:ZoneInfo(zone)
    except (ValueError,ZoneInfoNotFoundError):raise app.Problem('Fuseau horaire de conservation inconnu sur ce serveur.') from None
    return rule


def choose(values, keep_last, rule):
    """values triées par instant décroissant, puis identifiant pour les égalités."""
    reasons={identifier:['Derniers points'] for _,identifier,_ in values[:keep_last]}
    zone=ZoneInfo(rule['timezone']);seen={key:set() for key in ('daily','weekly','monthly')}
    for stamp,identifier,_ in values:
        if all(len(seen[key])>=rule[key] for key in seen):break
        local=datetime.fromtimestamp(stamp,zone);iso=local.isocalendar()
        periods={'daily':(local.date().isoformat(),'Jour'),
                 'weekly':(f'{iso.year}-W{iso.week:02d}','Semaine ISO'),
                 'monthly':(f'{local.year:04d}-{local.month:02d}','Mois')}
        for key,(period,label) in periods.items():
            if len(seen[key])>=rule[key] or period in seen[key]:continue
            seen[key].add(period)
            reasons.setdefault(identifier,[]).append(label+' · '+period)
    return reasons
