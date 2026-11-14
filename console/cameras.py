"""Caméras RTSP nommées, secrets privés et validation par le runtime Frigate."""
import ipaddress
import json
import math
import re
import secrets
import time
from urllib.parse import quote

IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
NEW_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{1,31}\Z')


def config(app):
    path = app.ROOT/'state/frigate/config.yml'
    if not path.exists():
        from lab import initial_config
        return initial_config()
    try:
        return app.load_config(path)
    except (RuntimeError, OSError):
        raise app.Problem('Démarrez Frigate dans Services pour lire sa configuration existante.',503) from None


def identifier(app, value='tapo', require=True):
    if not isinstance(value,str) or not IDENTIFIER.fullmatch(value):
        raise app.Problem('Identifiant caméra invalide.')
    if require and value not in config(app).get('cameras',{}):
        raise app.Problem('Caméra inconnue.',404)
    return value


# Frigate 0.18 échantillonne normalement toutes les 15 s. Six périodes de marge.
STATS_MAX_AGE=90

def measurement_time(payload, now=None):
    now=time.time() if now is None else now
    service=payload.get('service',{}) if isinstance(payload,dict) else {}
    value=service.get('last_updated') if isinstance(service,dict) else None
    try:
        if type(value) in (int,float) and math.isfinite(value) and 0<value<=now+30:return value
    except OverflowError:pass
    return None

def fresh_stats(payload, now=None):
    now=time.time() if now is None else now
    stamp=measurement_time(payload,now)
    return stamp is not None and now-stamp<=STATS_MAX_AGE


def listing(app):
    values = config(app).get('cameras',{})
    # Une réponse absente/incomplète n'est pas une preuve de perte de flux.
    payload={}
    try:
        payload=app.video_json('/api/stats') if values else {}
        stats=payload.get('cameras',{}) if isinstance(payload,dict) else {}
        if not isinstance(stats,dict):stats={}
    except (app.Problem,OSError,ValueError):stats={}
    now=time.time();observed=measurement_time(payload,now);fresh=fresh_stats(payload,now)
    result=[]
    for name,c in values.items():
        if not IDENTIFIER.fullmatch(name):continue
        enabled=c.get('enabled',True)
        sample=stats.get(name,{})
        fps=sample.get('camera_fps') if isinstance(sample,dict) else None
        if type(fps) not in (int,float) or not math.isfinite(fps) or fps<0:fps=None
        status='disabled' if not enabled else 'stale' if observed is not None and not fresh else 'unknown' if not fresh or fps is None else 'receiving' if fps>0 else 'no_frames'
        # Liste blanche : aucune URL, adresse, identité ou clé ONVIF.
        result.append({'id':name,'name':c.get('friendly_name') or name,'enabled':enabled,
            'days':c.get('record',{}).get('continuous',{}).get('days',1),
            'online':status=='receiving','status':status,'fps':fps if enabled and fresh else None,
            'observed_at':observed if enabled and fps is not None else None,
            'onvif':bool(c.get('onvif',{}).get('host'))})
    return result


def build(app, body):
    key = identifier(app,body.get('id'),require=False)
    if body.get('replace') is not True and not NEW_IDENTIFIER.fullmatch(key): raise app.Problem('Identifiant : 2 à 32 lettres minuscules, chiffres ou underscores.')
    name = body.get('name','')
    if not isinstance(name,str) or not 1 <= len(name.strip()) <= 60 or any(ord(c)<32 for c in name):
        raise app.Problem('Choisissez un nom de caméra de 1 à 60 caractères.')
    try: address = ipaddress.IPv4Address(body.get('host',''))
    except (ipaddress.AddressValueError,TypeError): raise app.Problem('Saisissez une adresse IPv4 locale valide.') from None
    if not any(address in ipaddress.IPv4Network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise app.Problem('La caméra doit utiliser une adresse IPv4 privée du réseau local.')
    profile=body.get('profile','tapo')
    if profile not in ('tapo','rtsp'): raise app.Problem('Profil caméra inconnu.')
    port=body.get('port',554);onvif=body.get('onvif',False);onvif_port=body.get('onvif_port',2020)
    if type(port) is not int or not 1<=port<=65535 or type(onvif) is not bool or type(onvif_port) is not int or not 1<=onvif_port<=65535:
        raise app.Problem('Ports ou option ONVIF invalides.')
    username,password=body.get('username',''),body.get('password','')
    if any(not isinstance(v,str) or not 1<=len(v)<=256 or any(ord(c)<32 for c in v) for v in (username,password)):
        raise app.Problem('Renseignez le compte caméra local et son mot de passe.')
    paths = ['/stream1','/stream2'] if profile=='tapo' else [body.get('path',''),body.get('subpath','')]
    for path in paths:
        if path and (not isinstance(path,str) or not path.startswith('/') or len(path)>1024 or any(c in path for c in ('#','\r','\n','\x00'))):
            raise app.Problem('Utilisez un chemin de flux commençant par /, sans URL ni identifiants.')
    if not paths[0]: raise app.Problem('Le chemin du flux principal est obligatoire.')
    base=f'rtsp://{quote(username,safe="")}:{quote(password,safe="")}@{address}:{port}'
    streams={key:[base+paths[0]]}
    inputs=[{'path':f'rtsp://127.0.0.1:8554/{key}','input_args':'preset-rtsp-restream','roles':['record']}]
    if paths[1]:
        streams[key+'_sub']=[base+paths[1]]
        inputs.append({'path':f'rtsp://127.0.0.1:8554/{key}_sub','input_args':'preset-rtsp-restream','roles':['detect']})
    else: inputs[0]['roles'].append('detect')
    camera={'friendly_name':name.strip(),'ffmpeg':{'inputs':inputs},'detect':{'enabled':False,'fps':5},
            'record':{'enabled':True,'continuous':{'days':1}}}
    if onvif: camera['onvif']={'host':str(address),'port':onvif_port,'user':username,'password':password,'autotracking':{'enabled':False}}
    return key, camera, streams


def check_conflicts(app,current,key,streams,replace):
    existing=current.get('cameras',{})
    if replace:
        if key not in existing: raise app.Problem('Caméra à modifier introuvable.',404)
        urls={f'rtsp://127.0.0.1:8554/{key}',f'rtsp://127.0.0.1:8554/{key}_sub'}
        for name,camera in existing.items():
            if name!=key and any(item.get('path') in urls for item in camera.get('ffmpeg',{}).get('inputs',[])):
                raise app.Problem('Ce flux est partagé avec une autre caméra. Préservez sa configuration avant modification.',409)
    elif key in existing or any(name in current.get('go2rtc',{}).get('streams',{}) for name in streams):
        raise app.Problem('Cet identifiant caméra ou flux existe déjà. Choisissez-en un autre.',409)


def submit(app, body, actor):
    from deployment import ensure_idle
    ensure_idle(app)
    if body.get('confirm') is not True:
        raise app.Problem('Confirmez l’enregistrement et le redémarrage du service vidéo.')
    key,camera,streams=build(app,body)
    current=config(app)
    replace=body.get('replace',False)
    if type(replace) is not bool: raise app.Problem('Mode de configuration invalide.')
    check_conflicts(app,current,key,streams,replace)
    # Secrets hors de jobs/options et des réponses HTTP. Identifiant opaque seulement.
    candidate=secrets.token_hex(12)
    directory=app.STATE/'camera-pending';directory.mkdir(mode=0o700,exist_ok=True)
    path=directory/(candidate+'.json')
    app.private_write(path,json.dumps({'id':key,'camera':camera,'streams':streams,'replace':replace}))
    try: job=app.protection().submit('camera_add',actor,{'candidate':candidate})
    except BaseException:
        path.unlink(missing_ok=True);raise
    app.audit(actor,'Ajout caméra demandé',key)
    return {'job':job,'camera':key}


def apply(app,row):
    token=json.loads(row['options'])['candidate']
    if not re.fullmatch(r'[a-f0-9]{24}',token): raise app.Problem('Configuration caméra invalide.')
    pending=app.STATE/'camera-pending'/(token+'.json')
    progress=lambda text:app.protection().update(row['id'],progress={'message':text})
    try:
        payload=json.loads(pending.read_text());key=payload['id'];identifier(app,key,require=False)
        path=app.ROOT/'state/frigate/config.yml'
        original=path.read_bytes()
        current=config(app)
        check_conflicts(app,current,key,payload['streams'],payload.get('replace',False))
        if payload.get('replace'):
            existing=current['cameras'][key]
            existing['friendly_name']=payload['camera']['friendly_name']
            existing.setdefault('ffmpeg',{})['inputs']=payload['camera']['ffmpeg']['inputs']
            if 'onvif' in payload['camera']:existing['onvif']=payload['camera']['onvif']
            else:existing.pop('onvif',None)
        else:current.setdefault('cameras',{})[key]=payload['camera']
        streams=current.setdefault('go2rtc',{}).setdefault('streams',{})
        if payload.get('replace') and key+'_sub' not in payload['streams']:
            streams.pop(key+'_sub',None)
        streams.update(payload['streams'])
        progress('Validation de la configuration par Frigate…')
        try: app.service_op('video_validate',document=current,timeout=30)
        except (app.Problem,OSError):
            raise app.Problem('Frigate doit être démarré et accepter la configuration. Aucun réglage existant n’a été remplacé.',503) from None
        if path.read_bytes()!=original:
            raise app.Problem('La configuration a changé pendant la validation. Relancez l’ajout.',409)
        backup=app.STATE/('camera-before-'+row['id']+'.yml')
        app.private_write(backup,original.decode())
        progress('Configuration enregistrée ; redémarrage de la vidéo…')
        app.private_write(path,json.dumps(current,indent=2)+'\n')
        try:
            app.service_op('control',name='video',action='restart',timeout=90)
            app._upstream_cache=(0,None)
            ready=False
            for _ in range(30):
                try:
                    stats=app.video_json('/api/stats').get('cameras',{})
                    if key in stats or not current['cameras'][key].get('enabled',True):
                        ready=True;break
                except (app.Problem,OSError):pass
                time.sleep(2)
            if not ready: raise app.Problem('Démarrage non confirmé.')
        except (app.Problem,OSError):
            raise app.Problem('Configuration enregistrée, mais redémarrage vidéo non confirmé. La copie précédente est conservée dans le répertoire privé de console. Vérifiez Services avant une nouvelle action.',503) from None
        online=bool(stats.get(key,{}).get('camera_fps',0)>0)
        message='Caméra configurée ; flux vidéo reçu.' if online else 'Caméra configurée ; flux non confirmé. Vérifiez l’adresse, les chemins et le compte local de la caméra.'
        app.protection().update(row['id'],status='done',result={'camera':key,'message':message,'online':online},progress={'message':'Terminé','percent_done':1})
        app.audit(row['username'],'Caméra configurée',key)
    finally:pending.unlink(missing_ok=True)
