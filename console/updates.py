"""Authenticated web adapter for the independent, persistent update supervisor."""
import hmac
import os
from pathlib import Path
import secrets
import shutil
import time
import tarfile
import update_engine as engine


def maintenance(app):return engine.state(app.ROOT)['phase'] in engine.ACTIVE

def status(app):
    s=engine.state(app.ROOT)
    heartbeat=engine.read(engine.area(app.ROOT)/'heartbeat.json',{})
    ready=os.environ.get('NACRE_SUPERVISED')=='1' and time.time()-heartbeat.get('updated_at',0)<30
    return {**{k:s[k] for k in ('phase','id','version','previous_version','commit','updated_at','error','prepared_at') if k in s},
            'available':ready,'current_version':app.release_version(),'package_limit':engine.MAX_PACKAGE,
            'reason':None if ready else 'Installer ou actualiser le service utilisateur Nacre pour activer son superviseur de mise à jour.'}

def require(app):
    if not status(app)['available']:raise app.Problem('Le superviseur de mise à jour n’est pas disponible.',409)

def upload(app,handler):
    require(app)
    if maintenance(app):raise app.Problem('Mise à jour déjà engagée.',409)
    try:length=int(handler.headers.get('Content-Length','0'))
    except ValueError:raise app.Problem('Taille du paquet invalide.') from None
    if not 0<length<=engine.MAX_PACKAGE:raise app.Problem('Choisissez un paquet Nacre signé de moins de 32 Mio.',413)
    folder=engine.area(app.ROOT);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if shutil.disk_usage(folder).free<length+engine.MAX_EXPANDED:raise app.Problem('Espace insuffisant pour préparer la mise à jour.',507)
    path=folder/('upload-'+secrets.token_hex(12))
    try:
        with path.open('xb') as stream:
            path.chmod(0o600);remaining=length
            while remaining:
                data=handler.rfile.read(min(remaining,1024**2))
                if not data:raise app.Problem('Import interrompu.')
                stream.write(data);remaining-=len(data)
        engine.prepare(app.ROOT,path)
    except engine.UpdateError as error:raise app.Problem(str(error),409) from None
    except (ValueError,KeyError,OSError,EOFError,tarfile.TarError):raise app.Problem('Paquet de mise à jour non valide.') from None
    finally:path.unlink(missing_ok=True)
    return status(app)

def apply(app,body,session):
    require(app)
    if body.get('confirm') is not True:raise app.Problem('Confirmez l’installation et la brève interruption de la console.')
    identifier=body.get('id')
    if not isinstance(identifier,str):raise app.Problem('Préparation invalide.')
    # The normal admin/CSRF gate has already run; revalidate the actor before queuing.
    from control_panel import authorized
    with app.database() as db:authorized(app,db,session)
    try:engine.request(app.ROOT,identifier,session['name'])
    except engine.UpdateError as error:raise app.Problem(str(error),409) from None
    return status(app)

def probe(app,handler):
    expected=os.environ.get('NACRE_UPDATE_PROBE','')
    if not expected or not hmac.compare_digest(handler.headers.get('X-Nacre-Update-Probe',''),expected):raise app.Problem('Accès refusé.',403)
    with app.database() as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise app.Problem('Base indisponible.',503)
        schema=db.execute('PRAGMA user_version').fetchone()[0]
    return {'version':app.release_version(),'schema':schema,'ready':True}
