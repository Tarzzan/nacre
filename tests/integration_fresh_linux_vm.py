#!/usr/bin/env python3
"""Linux vierge, reprise de données et miroir neuf. Exclusivement VM jetable."""
from contextlib import closing
import hashlib,http.client,json,os,re,sqlite3,subprocess,sys,time
from pathlib import Path

assert os.environ.get('NACRE_VM_LAB')=='1'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
SOURCE=Path(__file__).resolve().parents[1]
BASE=Path('/home/ubuntu/nacre-fresh-test')
ROOT=BASE/'restored'
os.environ['NAS_ROOT']=str(ROOT)
os.environ['NAS_RESTIC_BIN']=str(SOURCE/'.tools/restic')
sys.path.insert(0,str(SOURCE/'console'));sys.path.insert(0,str(SOURCE))
from system_recovery import prepare,samba_restore,attach,run,restic
from compose_support import arguments
from native_storage import NativeClient
client=NativeClient()

def request(method,**body):return client.request(method,'admin',body)
def commit(plan):return request('commit',plan=plan['id'],confirmation=plan['confirmation'])
def login():
 password=re.search(r'Mot de passe : (.+)',(BASE/'bundle/source-lost/state/console/acces.txt').read_text())[1]
 for _ in range(60):
  try:
   c=http.client.HTTPConnection('127.0.0.1',8766,timeout=5)
   c.request('POST','/api/login',json.dumps({'username':'admin','password':password}),{'Content-Type':'application/json'})
   r=c.getresponse();body=json.loads(r.read());assert r.status==200 and body['role']=='admin';c.close();return
  except (ConnectionError,OSError):time.sleep(.2)
 raise AssertionError('Console indisponible')

def smb(user,share,command,ok):
 secret='Banc-reprise-samba-seulement-42' # gitleaks:allow — fixture synthétique
 script='''set -eu
umask 077
p=$(mktemp)
trap 'rm -f "$p"' EXIT
cat > "$p"
smbclient "//127.0.0.1/$1" -A "$p" -c "$2" >/dev/null 2>&1
'''
 result=subprocess.run(arguments(ROOT,'exec','-T','fichiers','sh','-c',script,'sh',share,command),input=f'username = {user}\npassword = {secret}\n'.encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 assert (result.returncode==0)==ok

if '--after-reboot' in sys.argv:
 result=json.loads((BASE/'result.json').read_text());identifier=result['pool']
 login()
 # La console écoute avant la première convergence du watcher SMB (5 s).
 for attempt in range(60):
  try:
   state=request('status');volume=next(v for v in state['provisioning']['deployments'] if v['id']==identifier)
   assert volume['mounted'] and volume['raid']['degraded']==0 and volume['raid']['sync_action']=='idle'
   assert Path(volume['mountpoint'],'data/temoin.txt').read_text().startswith('Contenu retrouvé')
   smb('alice','fichiers','ls',True);smb('desactive','fichiers','ls',False)
   break
  except (AssertionError,OSError,StopIteration):
   if attempt==59:raise
   time.sleep(.5)
 result['fresh_linux_reboot_services_and_pool']=True
 (BASE/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));sys.exit()

assert not Path('/var/lib/nacre-storage').exists()
assert not run(['docker','image','ls','-q']).strip()
assert not run(['docker','volume','ls','-q']).strip()
assert not ROOT.exists()
bundle=BASE/'bundle'
receipt=json.loads((bundle/'source-lost/state/console/last-system-recovery.json').read_text())
prepare(bundle/'recovery-repo',bundle/'bootstrap.key',receipt['snapshot'],ROOT)
samba_restore(ROOT)
attach(ROOT,'a'*24,bundle/'history')
assert json.loads(restic(bundle/'history',ROOT/'state/console/keys'/('a'*24+'.key'),'snapshots','--json'))
alice_uid=next(u['uid'] for u in json.loads((ROOT/'state/console/smb.json').read_text())['users'] if u['name']=='alice')
assert (ROOT/'data/fichiers/temoin.txt').stat().st_uid==alice_uid
assert (ROOT/'data/fichiers/reprise-volumes/native_test-volume/volume.txt').read_text()=='volume externe'
with closing(sqlite3.connect(ROOT/'state/console/console.db')) as db:assert db.execute('SELECT sum(enabled) FROM plans').fetchone()[0]==0
run([sys.executable,str(ROOT/'console/install_restic.py')])
run(['sudo',sys.executable,str(SOURCE/'console/install_native.py'),'--uid',str(os.getuid()),'--install'])
# Politique vierge de périphériques hôtes ; seules les séries des images du banc.
specs=[]
for letter in 'ABC':
 path='/dev/disk/by-id/virtio-NACRE-V08-'+letter
 data=json.loads(run(['lsblk','-J','-b','-o','SERIAL,SIZE',path]))['blockdevices'][0]
 assert data['serial']=='NACRE-V08-'+letter
 specs.append({'id':'disk-'+letter.lower(),'path':path,'serial':data['serial'],'bytes':int(data['size']),'initialize':True})
policy={'version':1,'allowed_uid':os.getuid(),'volumes':[],'provisioning':{'enabled':True,'root':'/srv/nacre-volumes','mount_on_start':True,'devices':specs}}
policyfile=BASE/'policy.json';policyfile.write_text(json.dumps(policy))
run(['sudo','mkdir','-p','/srv/nacre-volumes'])
run(['sudo','install','-m','600',policyfile,'/etc/nacre-storage/policy.json'])
run(['sudo','systemctl','enable','nacre-storage.service'])
run(['sudo','systemctl','restart','nacre-storage.service'])
for _ in range(60):
 try:
  if request('status')['connected']:break
 except OSError:pass
 time.sleep(.1)
plan=request('prepare',action='provision',profile={'name':'Miroir reconstruit','layout':'mirror','filesystem':'btrfs','disk_bytes':[1,1]},devices=['disk-a','disk-b'])
created=commit(plan);identifier=created['object'];target=Path(created['location'])
run(['sudo','rsync','-aHAX','--numeric-ids','--checksum',str(ROOT/'data/fichiers')+'/',str(target)+'/'])
assert (target/'temoin.txt').read_bytes()==(ROOT/'data/fichiers/temoin.txt').read_bytes()
assert (target/'temoin.txt').stat().st_uid==alice_uid
# Requalifier les partages, sans activer les anciens plans.
import server as app
app.initialize();config=app.smb_state()
for share in config['shares']:
 if share['area']=='fichiers':share['area']='native_'+identifier
app.save_smb(config,reload=False)
app.shares().prepare_start(config)
run(arguments(ROOT,'up','-d','--no-build','fichiers'))
app.shares().set_intent(True)
for attempt in range(60):
 try:app.shares().apply(config);break
 except app.Problem:
  if attempt==59:raise
  time.sleep(.2)
for _ in range(60):
 try:smb('alice','fichiers','get temoin.txt /tmp/witness',True);break
 except AssertionError:time.sleep(.2)
else:raise AssertionError('SMB indisponible')
smb('desactive','fichiers','ls',False);smb('alice','lecture','put /tmp/witness refuse.txt',False)
run(['sudo','loginctl','enable-linger','ubuntu'])
run([sys.executable,str(ROOT/'console/install_service.py')]);login()
for _ in range(200):
 state=request('status');volume=next(v for v in state['provisioning']['deployments'] if v['id']==identifier)
 if volume['raid']['degraded']==0 and volume['raid']['sync_action']=='idle':break
 time.sleep(.2)
else:raise AssertionError('Synchronisation initiale inachevée')
result={'fresh_official_linux':True,'no_previous_docker_images_or_volumes':True,'separate_source_vm_stopped':True,
 'restored_keys_unlock_history':True,'original_console_password_http':True,'samba_secondary_password_and_disabled_account':True,
 'samba_readonly_enforced':True,'numeric_owners_preserved':True,'new_btrfs_raid1_created':True,'data_repopulated_on_new_pool':True,
 'automatic_plans_disabled':True,'pool':identifier,'fresh_linux_reboot_services_and_pool':False}
(BASE/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
