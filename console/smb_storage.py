"""Partages SMB et montages dédiés aux volumes Nacre autorisés."""
import json
from pathlib import Path
import secrets
import threading
import time
import configparser
from compose_support import arguments


def manifest(config, resources):
    areas=sorted({s['area'] for s in config['shares'] if s['area'].startswith('native_')})
    mounts=[]
    for area in areas:
        resource=resources.get(area)
        if not resource:continue
        mounts.append({'type':'bind','source':resource['path'].replace('$','$$'),'target':'/shares/'+area,
                       'read_only':not resource.get('writable',False),'bind':{'create_host_path':False}})
    return {'services':{'fichiers':{'volumes':mounts}}}


def render(config, available):
    enabled={u['name'] for u in config['users'] if u['enabled']}
    lines=['[global]','server role = standalone server','workgroup = WORKGROUP','security = user',
           'map to guest = never','server min protocol = SMB2','smb ports = 445','disable netbios = yes',
           'load printers = no','printing = bsd','printcap name = /dev/null','log file = /dev/stdout',
           'max log size = 0','follow symlinks = no','wide links = no','invalid users = root',
           'veto files = /.nacre-*/','delete veto files = no']
    for share in config['shares']:
        users=[u for u in share['users'] if u in enabled]
        if not users:continue
        area=share['area']
        online=not area.startswith('native_') or area in available
        readonly=share['readonly'] or (area.startswith('native_') and not available.get(area,{}).get('writable',False))
        lines+=['','['+share['name']+']','path = /shares/'+area+('/'+share['path'] if share['path'] else ''),
                'available = '+('yes' if online else 'no'),'valid users = '+' '.join(users),
                'read only = '+('yes' if readonly else 'no'),'force group = nas','create mask = 0660','directory mask = 0770']
    return '\n'.join(lines)+'\n'


class Shares:
    def __init__(self, app):
        self.app=app
        self.directory=app.ROOT/'state/samba'
        self.override=self.directory/'volumes.compose.json'
        self.runtime=self.directory/'smb.conf'
        self.intent=app.STATE/'smb-intent.json'

    def resources(self,config):
        if not any(s['area'].startswith('native_') for s in config['shares']):return {}
        return {'native_'+r['id']:r for r in self.app.native_resources() if r.get('kind')=='volume' and r.get('identity')}

    def view(self,config):
        resources=self.resources(config)
        parsed=configparser.ConfigParser(interpolation=None,strict=False)
        try:parsed.read(self.runtime)
        except configparser.Error:pass
        return {**config,'shares':[{**s,'available':not s['area'].startswith('native_') or
                (s['area'] in resources and parsed.get(s['name'],'available',fallback='no')=='yes')} for s in config['shares']]}

    def intent_enabled(self):
        try:return json.loads(self.intent.read_text()).get('enabled',True)
        except FileNotFoundError:return True

    def set_intent(self,enabled):
        self.app.private_write(self.intent,json.dumps({'enabled':enabled}))

    def prepare_start(self,config):
        resources=self.resources(config)
        self.app.private_write(self.override,json.dumps(manifest(config,resources),indent=2)+'\n')
        self.app.private_write(self.runtime,render(config,{}))

    def check_permissions(self,config,resources):
        group=self.app.compose('exec','-T','fichiers','id','-g','nas').strip()
        if not group.isdecimal():raise self.app.Problem('Groupe SMB indisponible.',503)
        for share in config['shares']:
            if share['area'] not in resources:continue
            path='/shares/'+share['area']+('/'+share['path'] if share['path'] else '')
            readonly=share['readonly'] or not resources[share['area']].get('writable',False)
            for username in share['users']:
                uid=next(u['uid'] for u in config['users'] if u['name']==username)
                self.app.compose('exec','-T','--user',str(uid)+':'+group,'fichiers','sh','-c',
                    'test -r "$1" && test -x "$1" && { [ "$2" = r ] || test -w "$1"; }','sh',path,'r' if readonly else 'rw')

    def valid_bindings(self,resources):
        for area,r in resources.items():
            observed=self.app.compose('exec','-T','fichiers','stat','-c','%d:%i','/shares/'+area).strip()
            if observed!=str(r['identity']['dev'])+':'+str(r['identity']['ino']):return False
        return True

    def apply(self,config,reload=True,reconcile=False):
        resources=self.resources(config)
        desired=manifest(config,resources)
        desired_text=json.dumps(desired,indent=2)+'\n'
        previous={path:path.read_text() if path.exists() else None for path in (self.override,self.runtime,self.app.STATE/'smb.json',self.directory/'users.tsv')}
        users=''.join(f'{u["name"]}\t{u["uid"]}\n' for u in config['users'])
        if not reload:
            self.app.private_write(self.app.STATE/'smb.json',json.dumps(config,indent=2)+'\n')
            self.app.private_write(self.runtime,render(config,resources))
            self.app.private_write(self.directory/'users.tsv',users)
            # Le profil initial ne nécessite aucun montage supplémentaire.
            if resources:self.app.private_write(self.override,desired_text)
            return
        if not self.intent_enabled():
            if reconcile:return
            raise self.app.Problem('Démarrer le service de fichiers avant de modifier ses partages.',503)
        # Ne monter que les ressources effectivement référencées par un partage.
        used={s['area'] for s in config['shares']}
        resources={a:r for a,r in resources.items() if a in used}
        token=secrets.token_hex(10)
        candidate=self.directory/('.smb-'+token+'.conf')
        candidate_override=self.directory/('.mounts-'+token+'.json')
        changed=previous[self.override]!=desired_text and (previous[self.override] is not None or bool(desired['services']['fichiers']['volumes']))
        try:
            if reconcile and not changed and previous[self.runtime]==render(config,resources) and self.valid_bindings(resources):return
            # Pendant une recréation, les nouveaux partages restent désactivés
            # jusqu'au contrôle des inodes montés à l'intérieur du conteneur.
            provisional=render(config,{} if changed else resources)
            self.app.private_write(candidate,provisional)
            self.app.private_write(candidate_override,desired_text)
            self.app.command(arguments(self.app.ROOT,'config','--quiet',override=candidate_override))
            self.app.compose('exec','-T','fichiers','testparm','-s','/etc/nas-autonome/'+candidate.name)
            if not changed and resources:
                try:changed=not self.valid_bindings(resources)
                except self.app.Problem:changed=True
            if changed:
                self.app.private_write(self.runtime,render(config,{}))
                self.app.private_write(self.directory/'users.tsv',users)
                self.app.private_write(self.override,desired_text)
                self.app.compose('up','-d','--no-deps','--force-recreate','fichiers',timeout=90)
                last=None
                for _ in range(20):
                    try:
                        if not self.valid_bindings(resources):raise self.app.Problem('Le montage SMB ne correspond pas au volume autorisé.',503)
                        last=None;break
                    except self.app.Problem as error:last=error;time.sleep(.2)
                if last:raise last
            if changed or previous[self.app.STATE/'smb.json']!=json.dumps(config,indent=2)+'\n':
                self.check_permissions(config,resources)
            final=render(config,resources)
            if previous[self.runtime]!=final or changed:
                self.app.private_write(self.runtime,final)
                self.app.compose('exec','-T','fichiers','smbcontrol','all','reload-config')
                # Fermer aussi les arbres SMB déjà connectés : un rechargement
                # seul ne révoque pas leurs anciens droits.
                for share in config['shares']:
                    self.app.compose('exec','-T','fichiers','smbcontrol','all','close-share',share['name'])
            self.app.private_write(self.app.STATE/'smb.json',json.dumps(config,indent=2)+'\n')
            self.app.private_write(self.directory/'users.tsv',users)
        except Exception:
            for path,value in previous.items():
                if value is not None:self.app.private_write(path,value)
                elif path.exists():path.unlink()
            try:
                old=json.loads(previous[self.app.STATE/'smb.json']) if previous[self.app.STATE/'smb.json'] else config
                # Après un échec de contrôle, aucun ancien partage natif ne
                # doit être réactivé sans vérification de son montage.
                self.app.private_write(self.runtime,render(old,{}))
                self.app.private_write(self.override,json.dumps(manifest(old,self.resources(old)),indent=2)+'\n')
                if changed or reconcile:self.app.compose('up','-d','--no-deps','--force-recreate','fichiers',timeout=90)
                self.app.compose('exec','-T','fichiers','smbcontrol','all','reload-config')
                for share in old['shares']:
                    if share['area'].startswith('native_'):
                        self.app.compose('exec','-T','fichiers','smbcontrol','all','close-share',share['name'])
            except Exception:pass
            raise
        finally:
            candidate.unlink(missing_ok=True);candidate_override.unlink(missing_ok=True)

    def watch(self):
        while True:
            try:
                with self.app.LOCK:
                    from deployment import ensure_idle
                    ensure_idle(self.app)
                    config=self.app.smb_state()
                    if any(s['area'].startswith('native_') for s in config['shares']) and self.intent_enabled():
                        self.apply(config,reconcile=True)
            except Exception:
                # Le prochain passage reprend le contrôle ; aucun volume n'est
                # créé, reformaté ou remplacé pour réparer une indisponibilité.
                pass
            time.sleep(5)

    def start_watch(self):
        threading.Thread(target=self.watch,daemon=True,name='nacre-smb-volumes').start()
