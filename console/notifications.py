"""Outbox transactionnelle : webhook JSON / ntfy / SMTP, sans secret dans les réponses API."""
import copy
from datetime import datetime, timezone
import json
import re
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler

KEY = 'notifications_v1'
PENDING = ('queued', 'sending')
RETRIES = (30, 120, 600, 1800)
LEASE = 60
MAX_QUEUE = 1000
HISTORY = 100


def read(db):
    row = db.execute('SELECT value FROM settings WHERE key=?', (KEY,)).fetchone()
    state = json.loads(row[0]) if row else {
        'config': {'version':0, 'enabled':False, 'kind':'webhook', 'url':'', 'token':'', 'minimum':'warning', 'recovery':True},
        'items':[], 'dropped':0, 'last_test':0}
    from smtp_notifications import defaults
    state['config'].setdefault('smtp',defaults())
    return state


def write(db, state):
    terminal = [item for item in state['items'] if item['status'] not in PENDING][-HISTORY:]
    keep = {item['id'] for item in terminal}
    state['items'] = [item for item in state['items'] if item['status'] in PENDING or item['id'] in keep]
    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY,json.dumps(state)))


def audit(db, now, actor, action, identifier=''):
    db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (now,actor,action,identifier))


def validate_url(app, value):
    try:
        if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError()
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:raise ValueError()
        if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError()
        if parsed.scheme != 'https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','::1')):raise ValueError()
        return value
    except ValueError:
        raise app.Problem('Adresse HTTPS requise, sans identifiant intégré ni fragment. HTTP est réservé à 127.0.0.1 ou ::1 pour un relais local.') from None


def version(app, body, config):
    if type(body.get('version')) is not int or body['version']!=config['version']:
        raise app.Problem('La configuration a changé. Actualisez avant de continuer.',409)


def status(app):
    with app.database() as db:state=read(db)
    config=state['config']
    # Le chemin et la requête d'un webhook peuvent contenir des secrets.
    parsed=urlsplit(config['url'])
    public={key:config[key] for key in ('version','enabled','kind','minimum','recovery')}
    public.update(configured=configured(config),has_token=bool(config['token']),destination=(parsed.scheme+'://'+parsed.netloc) if config['url'] else '')
    public['smtp']={key:value for key,value in config['smtp'].items() if key!='password'}
    public['smtp']['has_password']=bool(config['smtp']['password'])
    if config['kind']=='smtp':public['destination']=config['smtp']['host']+':'+str(config['smtp']['port'])
    fields=('id','event','title','severity','created','status','attempts','next','result','finished','config_version')
    return {'config':public, 'pending':sum(i['status'] in PENDING for i in state['items']), 'dropped':state['dropped'],
            'deliveries':[{key:item[key] for key in fields} for item in reversed(state['items'][-100:])]}


def configured(config):
    return bool(config['smtp']['host']) if config['kind']=='smtp' else bool(config['url'])


def configure(app, body, actor):
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');state=read(db);old=state['config'];version(app,body,old)
        config={key:body.get(key) for key in ('enabled','kind','minimum','recovery')}
        if type(config['enabled']) is not bool or type(config['recovery']) is not bool or config['kind'] not in ('webhook','ntfy','smtp') or config['minimum'] not in ('warning','critical'):
            raise app.Problem('Options de notification invalides.')
        from smtp_notifications import configure as configure_smtp, defaults
        if config['kind']=='smtp':
            config['smtp']=configure_smtp(app,body,old['smtp'])
            config['url']='';config['token']=''
        else:
            config['smtp']=defaults()
            url=body.get('url','');token=body.get('token','')
            if not isinstance(url,str) or not isinstance(token,str) or type(body.get('clear_token',False)) is not bool:
                raise app.Problem('Destination ou jeton invalide.')
            config['url']=validate_url(app,url) if url else old['url']
            if not config['url'] and config['enabled']:raise app.Problem('Renseignez une destination avant d’activer les envois.')
            # Ne jamais transmettre implicitement un ancien secret à une nouvelle destination.
            if url and url!=old['url'] and old['token'] and not token and not body.get('clear_token'):
                raise app.Problem('Pour changer de destination, renseignez le jeton adapté ou choisissez de le supprimer.')
            if token and (len(token)>4096 or not re.fullmatch(r'[A-Za-z0-9._~+/=-]+',token)):
                raise app.Problem('Jeton Bearer invalide.')
            config['token']='' if body.get('clear_token') else token or old['token']
        config['version']=old['version']+1
        now=time.time()
        for item in state['items']:
            if item['status'] in PENDING:item.update(status='cancelled',finished=now,result='Configuration modifiée ; envoi annulé.')
        state['config']=config;write(db,state)
        audit(db,now,actor,'Notifications configurées')
    return {'ok':True}


def append(state, event, incident, now):
    if sum(item['status'] in PENDING for item in state['items'])>=MAX_QUEUE:
        state['dropped']+=1
        return None
    identifier=secrets.token_hex(16)
    state['items'].append({'id':identifier,'event':event,'incident':incident.get('id'),'version':incident.get('version',1),
        'title':incident['title'],'message':incident['message'],'severity':incident['severity'],
        'created':now,'status':'queued','attempts':0,'next':now,'lease':'','result':'En attente.','finished':None,
        'config_version':state['config']['version']})
    return identifier


def enqueue(db, event, incident, now):
    """Appelé dans la transaction de l'incident, sans aucune opération réseau."""
    state=read(db);config=state['config']
    if not config['enabled']:return
    if event=='resolved':
        if not config['recovery'] or incident.get('notification_config')!=config['version']:return
    elif config['minimum']=='critical' and incident['severity']!='critical':return
    identifier=append(state,event,incident,now)
    if identifier and event!='resolved':incident['notification_config']=config['version']
    write(db,state)


def test(app, body, actor):
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');state=read(db);version(app,body,state['config'])
        if not configured(state['config']):raise app.Problem('Enregistrez une destination avant le test.')
        now=time.time()
        if now-state['last_test']<30:raise app.Problem('Attendez 30 secondes avant un nouveau test.',429)
        identifier=append(state,'test',{'title':'Test de notification Nacre','message':'Ce message de test confirme le trajet depuis Nacre vers votre destination. Aucun incident réel ni donnée de caméra ne sont inclus.','severity':'warning'},now)
        if not identifier:raise app.Problem('La file de notifications est pleine.',409)
        state['last_test']=now;write(db,state);audit(db,now,actor,'Notification de test demandée',identifier)
    return {'ok':True,'id':identifier}


def retry(app, body, actor):
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');state=read(db);config=state['config'];version(app,body,config)
        item=next((i for i in state['items'] if i['id']==body.get('id')),None)
        if not item or item['status']!='failed' or item['config_version']!=config['version']:
            raise app.Problem('Cet envoi ne peut plus être relancé avec la configuration courante.',409)
        if not config['enabled'] and item['event']!='test':raise app.Problem('Les notifications sont désactivées.',409)
        if sum(i['status'] in PENDING for i in state['items'])>=MAX_QUEUE:raise app.Problem('La file de notifications est pleine.',409)
        now=time.time();item.update(status='queued',attempts=0,next=now,finished=None,result='Relance demandée.')
        # Une relance explicite rejoint la fin de la file.
        state['items'].remove(item);state['items'].append(item);write(db,state)
        audit(db,now,actor,'Notification relancée',item['id'])
    return {'ok':True}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):return None


def deliver(config, item):
    if config['kind']=='smtp':
        from smtp_notifications import deliver as deliver_smtp
        return deliver_smtp(config['smtp'],item)
    payload={'schema':'nacre.alert.v1','id':item['id'],'event':item['event'],'incident_id':item['incident'],
             'version':item['version'],'severity':item['severity'],'title':item['title'],'message':item['message'],'occurred_at':item['created']}
    headers={'User-Agent':'Nacre/notifications','X-Nacre-Event-Id':item['id']}
    if config['token']:headers['Authorization']='Bearer '+config['token']
    if config['kind']=='ntfy':
        labels={'opened':'Incident détecté','updated':'Incident actualisé','resolved':'Retour à la normale','test':'Test'}
        occurred=datetime.fromtimestamp(item['created'],timezone.utc).isoformat()
        data=(labels[item['event']]+' · '+item['title']+'\n'+item['message']+'\nÉvénement : '+occurred).encode('utf-8')
        headers.update({'Content-Type':'text/plain; charset=utf-8','Title':'Nacre','Priority':'4' if item['severity']=='critical' and item['event']!='resolved' else '3'})
    else:
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8');headers['Content-Type']='application/json'
    try:
        # Pas de proxy implicite ni de redirection susceptible de déplacer un secret.
        opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(Request(config['url'],data=data,headers=headers,method='POST'),timeout=10) as response:
            code=response.status
        if 200<=code<300:return True,False,'Accepté par le destinataire (HTTP '+str(code)+').'
        return False,False,'Réponse HTTP '+str(code)+'.'
    except HTTPError as error:
        code=error.code;error.close()
        return False,code in (408,425,429) or 500<=code<600,'Refus du destinataire (HTTP '+str(code)+').'
    except Exception:
        # Les exceptions réseau peuvent contenir l'URL complète : ne jamais les enregistrer.
        return False,True,'Connexion impossible, délai dépassé ou certificat TLS non valide.'


def dispatch(app, now=None):
    clock=time.time if now is None else lambda: now
    now=clock()
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');state=read(db)
        item=next((i for i in state['items'] if i['status'] in PENDING),None)
        if not item or item['next']>now:return False
        if item['config_version']!=state['config']['version'] or (not state['config']['enabled'] and item['event']!='test'):
            item.update(status='cancelled',finished=now,result='Envoi désactivé.');write(db,state);return True
        if item['attempts']>=5:
            item.update(status='failed',finished=now,result='Résultat de la dernière tentative inconnu après interruption.');write(db,state);return True
        item.update(status='sending',attempts=item['attempts']+1,next=now+(180 if state['config']['kind']=='smtp' else LEASE),lease=secrets.token_hex(16),result='Envoi en cours.')
        snapshot=copy.deepcopy(item);config=copy.deepcopy(state['config']);write(db,state)
    # Aucun verrou SQLite pendant le réseau ; une sauvegarde reste possible.
    ok,transient,result=deliver(config,snapshot)
    finished=clock()
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');state=read(db)
        item=next((i for i in state['items'] if i['id']==snapshot['id']),None)
        if not item or item['status']!='sending' or item['lease']!=snapshot['lease']:return True
        item.update(result=result,finished=finished)
        if ok:item['status']='sent'
        elif transient and item['attempts']<5:
            item.update(status='queued',next=finished+RETRIES[item['attempts']-1],finished=None)
        else:item['status']='failed'
        write(db,state)
        if item['status'] in ('sent','failed'):audit(db,finished,'notifications','Notification acceptée' if ok else 'Notification en échec',item['id'])
    return True


def start(app):
    def loop():
        while True:
            try:dispatch(app)
            except Exception:pass
            time.sleep(2)
    threading.Thread(target=loop,daemon=True,name='nacre-notifications').start()
