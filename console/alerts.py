"""Surveillance locale, incidents persistants et acquittement sans action corrective."""
import hashlib
import json
import secrets
import shutil
import threading
import time
from notifications import enqueue

KEY = 'alerts_v1'
INTERVAL = 30
HISTORY = 100
SCOPES = ('services', 'cameras', 'backups', 'storage', 'docker', 'video_api', 'video_storage')


def read(app, db=None):
    if db is None:
        with app.database() as connection:return read(app, connection)
    row = db.execute('SELECT value FROM settings WHERE key=?', (KEY,)).fetchone()
    return json.loads(row[0]) if row else {'active':{}, 'history':[], 'pending':{}, 'seen_services':[], 'checked':0, 'unavailable':[]}


def write(db, state):
    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY,json.dumps(state)))


def condition(key, title, message, page, severity='warning', revision=''):
    return {'key':key, 'title':title, 'message':message, 'page':page, 'severity':severity, 'revision':revision}


def collect(app):
    state = read(app)
    scopes = {scope:[] for scope in SCOPES}
    seen = set(state['seen_services'])
    with app.database() as db:
        busy = db.execute("SELECT 1 FROM jobs WHERE kind IN ('component_install','camera_add') AND status IN ('queued','running')").fetchone()
        installed = db.execute("SELECT options FROM jobs WHERE kind='component_install' AND status='done'").fetchall()
        jobs = db.execute("SELECT id,kind,status,options FROM jobs WHERE kind IN ('snapshot','backup') AND status IN ('failed','partial','done') ORDER BY ts DESC,rowid DESC").fetchall()
    for row in installed:
        component = json.loads(row['options']).get('component')
        if component in ('video','fichiers'):seen.add(component)
    latest = set()
    from automatic_retention import listing
    for policy in listing(app):
        if policy['reason']:
            scopes['backups'].append(condition('retention:'+policy['repo'],'Rétention automatique suspendue',
                policy['name']+' : '+policy['reason'],'retention','critical',str(policy['version'])))
    for row in jobs:
        options = json.loads(row['options'])
        target = 'plan:'+str(options['plan']) if options.get('plan') else 'repo:'+str(options['repo']) if options.get('repo') else 'archive'
        group = row['kind']+':'+target
        if group in latest:continue
        latest.add(group)
        if row['status']=='done':continue
        key = 'backup:'+hashlib.sha256(group.encode()).hexdigest()[:24]
        scopes['backups'].append(condition(key, 'Sauvegarde incomplète' if row['status']=='partial' else 'Sauvegarde en échec',
            'Consultez les tâches de sauvegarde et leur destination. Un prochain succès du même plan ou dépôt clôturera cet incident.',
            'snapshots' if row['kind']=='snapshot' else 'backups', 'critical', row['id']))
    try:
        from native_schedule import conditions
        scopes['storage'].extend(condition(*values) for values in conditions(app))
    except Exception:
        pass
    try:
        from native_auto import conditions as automatic
        scopes['storage'].extend(condition(*values) for values in automatic(app))
    except Exception:
        pass
    try:
        disk = shutil.disk_usage(app.ROOT)
        ratio = disk.used / disk.total
        if ratio >= .9:
            scopes['storage'].append(condition('storage:application','Le volume de Nacre manque d’espace',
                'Au moins '+('97' if ratio>=.97 else '90')+' % du volume hébergeant Nacre est utilisé. Consultez Stockage avant de poursuivre les écritures.',
                'storage','critical' if ratio>=.97 else 'warning'))
    except (OSError,ZeroDivisionError):scopes['storage']=None
    if busy:
        scopes['services']=scopes['cameras']=scopes['docker']=scopes['video_api']=scopes['video_storage']=None
        return scopes, seen
    try:
        lines = app.service_op('status').splitlines()
        services = {item['Service']:item for item in (json.loads(line) for line in lines if line.strip())}
    except Exception:
        scopes['services']=scopes['cameras']=None if seen else []
        scopes['video_api']=scopes['video_storage']=None if 'video' in seen else []
        if seen:scopes['docker'].append(condition('monitor:docker','Les services ne peuvent pas être contrôlés',
            'Docker ne répond pas au contrôle local. Les incidents précédents sont conservés ; vérifiez Services.', 'services'))
        return scopes, seen
    for component,label in (('video','Frigate'),('fichiers','Samba')):
        service = services.get(component,{})
        if service.get('State')=='running':seen.add(component)
        if component not in seen:continue
        if service.get('State')!='running' or service.get('Health') in ('unhealthy','starting'):
            scopes['services'].append(condition('service:'+component,label+' n’est pas prêt',
                'Le service précédemment démarré est arrêté, en démarrage ou déclaré non sain. Consultez son état.', 'services'))
    video = services.get('video',{})
    if video.get('State')!='running' or video.get('Health') in ('unhealthy','starting'):
        scopes['cameras']=scopes['video_api']=scopes['video_storage']=None if 'video' in seen else []
    else:
        payload=None
        try:
            from cameras import config, IDENTIFIER, fresh_stats
            values = config(app).get('cameras',{})
            payload=app.video_json('/api/stats')
            if not fresh_stats(payload):raise ValueError('stale stats')
            stats = payload['cameras']
            if not isinstance(stats,dict):raise ValueError('stats')
            for name,camera in values.items():
                if IDENTIFIER.fullmatch(name) and camera.get('enabled',True) and not (stats.get(name,{}).get('camera_fps',0)>0):
                    scopes['cameras'].append(condition('camera:'+name,'Caméra '+name+' : flux absent',
                        'Frigate répond, mais aucun débit vidéo n’est confirmé pour cette caméra activée. Vérifiez sa connexion locale.', 'camera'))
        except Exception:
            scopes['cameras']=None
            scopes['video_api'].append(condition('monitor:camera','La surveillance ne peut pas être vérifiée',
                'La configuration ou les statistiques vidéo sont indisponibles ou périmées. Aucun retour à la normale des caméras n’est déduit.', 'camera'))
        # Volume vidéo : mesuré à part, pour qu’une mesure manquante ne dise rien des caméras, et inversement.
        try:
            from cameras import fresh_stats as fresh
            from kept import conditions as video_storage, ALERT
            found = video_storage(app, payload, ALERT in state['active']) if payload is not None and fresh(payload) else None
            scopes['video_storage'] = None if found is None else [condition(*values) for values in found]
        except Exception:
            scopes['video_storage']=None
    return scopes, seen


def record(app, scopes, seen=(), now=None):
    now = time.time() if now is None else now
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        state = read(app, db)
        if now-state['checked']>INTERVAL*3:state['pending']={}
        for scope in SCOPES:
            observations = scopes.get(scope)
            active = state['active']
            if observations is None:
                state['pending']={key:item for key,item in state['pending'].items() if item['scope']!=scope}
                continue
            current = {item['key']:item for item in observations}
            keys = set(current) | {key for key,item in active.items() if item['scope']==scope} | {key for key,item in state['pending'].items() if item['scope']==scope}
            for key in keys:
                bad = key in current
                if bad and key in active:
                    old = active[key];item=current[key]
                    changed=False
                    if (item['severity']=='critical' and old['severity']!='critical') or old['revision']!=item['revision']:
                        changed=True
                        old['acknowledged']=None;old['ackby']=None;old['version']+=1
                        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',(now,'surveillance','Incident actualisé',old['id']))
                    old.update(item,last=now)
                    if changed:enqueue(db,'updated',old,now)
                    state['pending'].pop(key,None)
                    continue
                if not bad and key not in active:
                    state['pending'].pop(key,None)
                    continue
                pending = state['pending'].get(key)
                if not pending or pending['bad']!=bad:
                    pending={'scope':scope,'bad':bad,'since':now};state['pending'][key]=pending
                if scope!='backups' and now-pending['since']<INTERVAL:continue
                if bad:
                    active[key]={**current[key],'id':secrets.token_hex(12),'version':1,'scope':scope,'first':now,'last':now,'resolved':None,'acknowledged':None,'ackby':None}
                    enqueue(db,'opened',active[key],now)
                    action='Incident détecté';identifier=active[key]['id']
                else:
                    incident=active.pop(key);incident.update(resolved=now,last=now)
                    enqueue(db,'resolved',incident,now)
                    state['history'].insert(0,incident)
                    action='Incident résolu';identifier=incident['id']
                state['pending'].pop(key,None)
                db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',(now,'surveillance',action,identifier))
        state['seen_services']=sorted(set(state['seen_services'])|set(seen))
        state['history']=sorted(state['history'],key=lambda item:item['resolved'],reverse=True)[:HISTORY]
        state.update(checked=now,unavailable=[scope for scope in SCOPES if scopes.get(scope) is None])
        write(db,state)


def listing(app):
    state=read(app)
    fields=('id','version','scope','title','message','page','severity','first','last','resolved','acknowledged','ackby')
    active=sorted(state['active'].values(),key=lambda item:(bool(item['acknowledged']),item['severity']!='critical',-item['first']))
    return {'checked':state['checked'],'stale':not state['checked'] or time.time()-state['checked']>INTERVAL*3,
            'unavailable':state['unavailable'],'interval':INTERVAL,
            'active':[{key:item[key] for key in fields} for item in active],
            'history':[{key:item[key] for key in fields} for item in state['history']],
            'attention':sum(not item['acknowledged'] for item in active)}


def acknowledge(app, body, actor):
    identifier=body.get('id')
    if not isinstance(identifier,str):raise app.Problem('Incident invalide.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');state=read(app,db)
        incident=next((item for item in state['active'].values() if item['id']==identifier),None)
        if not incident:raise app.Problem('Cet incident est déjà résolu ou absent.',409)
        if type(body.get('version')) is not int or body['version']!=incident['version']:
            raise app.Problem('Cet incident a changé. Actualisez avant de le prendre en compte.',409)
        if not incident['acknowledged']:
            incident.update(acknowledged=time.time(),ackby=actor)
            write(db,state)
            db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',(time.time(),actor,'Incident pris en compte',identifier))
    return {'ok':True}


def start(app):
    def loop():
        while True:
            try:
                scopes,seen=collect(app);record(app,scopes,seen)
            except Exception:
                # Une collecte interrompue ne peut jamais résoudre les incidents.
                # L'horodatage devient périmé et le navigateur le signale.
                pass
            time.sleep(INTERVAL)
    threading.Thread(target=loop,daemon=True,name='nacre-alerts').start()
