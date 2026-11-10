#!/usr/bin/env python3
"""Écritures pendant RAID1 : VM QEMU jetable, disques NACRE-V08 exclusivement.

Préparer integration_fresh_linux_vm.py, puis limiter labC à 16 Mio/s côté QEMU.
Aucune coupure n’est injectée pendant les nouvelles écritures de ce scénario.
"""
import argparse,concurrent.futures,hashlib,http.client,json,os,re,subprocess,sys,time
from pathlib import Path
assert os.environ.get('NACRE_VM_LAB')=='1'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
SOURCE=Path(__file__).resolve().parents[1];BASE=Path('/home/ubuntu/nacre-fresh-test');ROOT=BASE/'restored'
sys.path.insert(0,str(SOURCE/'console'));sys.path.insert(0,str(SOURCE))
from native_storage import NativeClient
from compose_support import arguments
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--old',choices=('B','C'),default='B');parser.add_argument('--replacement',choices=('B','C'),default='C');parser.add_argument('--after-reboot',action='store_true');options=parser.parse_args();assert options.old!=options.replacement
client=NativeClient();identifier=json.loads((BASE/'result.json').read_text())['pool']
def request(method,**body):return client.request(method,'admin',body)
def commit(p):return request('commit',plan=p['id'],confirmation=p['confirmation'])
def state():return next(v for v in request('status')['provisioning']['deployments'] if v['id']==identifier)
def command(*args):return subprocess.check_output(args,stderr=subprocess.PIPE,text=True)
def digest(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def auth():
 password=re.search(r'Mot de passe : (.+)',(BASE/'bundle/source-lost/state/console/acces.txt').read_text())[1]
 c=http.client.HTTPConnection('127.0.0.1',8766,timeout=30)
 c.request('POST','/api/login',json.dumps({'username':'admin','password':password}),{'Content-Type':'application/json'})
 r=c.getresponse();body=json.loads(r.read());assert r.status==200
 headers={'Cookie':r.getheader('Set-Cookie').split(';')[0],'X-CSRF-Token':body['csrf'],'Content-Type':'application/octet-stream'};c.close();return headers

def smb(user,share,operation,ok=True):
 secret='Banc-reprise-samba-seulement-42' # gitleaks:allow — fixture synthétique
 script='set -eu; umask 077; p=$(mktemp); trap \'rm -f "$p"\' EXIT; cat > "$p"; smbclient "//127.0.0.1/$1" -A "$p" -c "$2" >/dev/null 2>&1'
 r=subprocess.run(arguments(ROOT,'exec','-T','fichiers','sh','-c',script,'sh',share,operation),input=f'username = {user}\npassword = {secret}\n'.encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 assert (r.returncode==0)==ok,(user,share,r.returncode)

v=state();target=Path(v['mountpoint'])/'data';proof_path=BASE/'concurrent-io.json'
if '--after-reboot' in sys.argv:
 proof=json.loads(proof_path.read_text());auth()
 for _ in range(60):
  try:smb('alice','fichiers','ls');break
  except AssertionError:time.sleep(.5)
 else:raise AssertionError('SMB après redémarrage indisponible')
 assert v['phase']=='ready' and v['raid']['degraded']==0
 for row in proof['acknowledged']:assert digest(target/row['name'])==row['sha256']
 smb('desactive','fichiers','ls',False)
 proof['orderly_reboot_hashes_and_services']=True
 proof_path.write_text(json.dumps(proof,indent=2));print(json.dumps({k:v for k,v in proof.items() if k!='acknowledged'}));sys.exit()
assert not proof_path.exists()
for _ in range(600):
 v=state()
 if v['phase']=='ready' and v['raid']['degraded']==0:break
 time.sleep(.5)
else:raise AssertionError('Miroir initial non prêt')
for letter in 'ABC':
 p='/dev/disk/by-id/virtio-NACRE-V08-'+letter
 assert json.loads(command('lsblk','-J','-o','NAME,SERIAL',p))['blockdevices'][0]['serial']=='NACRE-V08-'+letter
headers=auth();baseline=digest(target/'temoin.txt');snapshot=request('prepare',action='snapshot',volume=identifier);commit(snapshot)
device=json.loads(command('findmnt','-J','-M',v['mountpoint'],'-o','SOURCE'))['filesystems'][0]['source'].split('[')[0]
md=Path('/sys/class/block')/Path(device).resolve().name/'md'
original_uuid=command('sudo','blkid','-p','-s','UUID','-o','value',device).strip()
# Précharger le client SMB avant la reconstruction ; aucun mot de passe dans argv.
payload=os.urandom(512*1024);payload_path=BASE/'write-payload.bin';payload_path.write_bytes(payload)
container=command(*arguments(ROOT,'ps','-q','fichiers')).strip()
command('docker','cp',str(payload_path),container+':/tmp/write-payload.bin')
command('sudo','mdadm','--manage',device,'--fail','/dev/disk/by-id/virtio-NACRE-V08-'+options.old,'--remove','/dev/disk/by-id/virtio-NACRE-V08-'+options.old)
assert commit(request('prepare',action='repair',volume=identifier,replace='disk-'+options.old.lower(),device='disk-'+options.replacement.lower()))['rebuilding']
for _ in range(100):
 progress=(md/'sync_completed').read_text().strip()
 if '/' in progress and int(progress.split('/')[0])>0:break
 time.sleep(.1)
else:raise AssertionError('Reconstruction non observée')
def sample():return {'progress':(md/'sync_completed').read_text().strip(),'action':(md/'sync_action').read_text().strip()}
prefix='concurrent-'+str(time.time_ns())+'-'
def writer(protocol):
 rows=[]
 for i in range(24):
  before=sample();name=prefix+f'{protocol}-{i:03}.bin'
  if protocol=='local':
   temporary=target/('.io-'+name)
   with temporary.open('xb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
   temporary.rename(target/name)
   fd=os.open(target,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
  elif protocol=='http':
   c=http.client.HTTPConnection('127.0.0.1',8766,timeout=30)
   c.request('POST','/api/upload?area=native_'+identifier+'&name='+name,payload,headers)
   r=c.getresponse();response=r.read();assert r.status==200,(r.status,response.decode());c.close()
  else:smb('alice','fichiers','put /tmp/write-payload.bin '+name)
  after=sample();assert before['action']=='recover' and after['action']=='recover',(before,after)
  assert '/' in before['progress'] and '/' in after['progress']
  rows.append({'name':name,'sha256':hashlib.sha256(payload).hexdigest(),'before':before['progress'],'after':after['progress']})
  time.sleep(.2)
 return rows
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 futures={p:pool.submit(writer,p) for p in ('local','http','smb')}
 rows={p:f.result() for p,f in futures.items()}
smb('alice','lecture','put /tmp/write-payload.bin refused.bin',False)
smb('desactive','fichiers','ls',False)
assert state()['phase']=='repairing'
for _ in range(600):
 v=state()
 if v['phase']=='ready' and v['raid']['degraded']==0 and v['raid']['sync_action']=='idle':break
 time.sleep(.5)
else:raise AssertionError('Reconstruction inachevée')
all_rows=sum(rows.values(),[])
for row in all_rows:assert digest(target/row['name'])==row['sha256']
clone=commit(request('prepare',action='clone',volume=identifier,point=snapshot['id']))
assert digest(Path(clone['location'])/'temoin.txt')==baseline
assert not list(Path(clone['location']).glob(prefix+'*'))
assert command('sudo','blkid','-p','-s','UUID','-o','value',device).strip()==original_uuid
assert set(v['members'])=={'disk-a','disk-'+options.replacement.lower()}
proof={'architecture':os.uname().machine,'bytes_per_file':len(payload),'acknowledged_during_recover':{p:len(r) for p,r in rows.items()},
 'all_hashes_after_rebuild':True,'snapshot_before_writes_unchanged':True,'filesystem_uuid_preserved':True,'readonly_and_disabled_smb_refused':True,
 'orderly_reboot_hashes_and_services':False,'power_cut_during_writes_tested':False,'acknowledged':all_rows}
proof_path.write_text(json.dumps(proof,indent=2));print(json.dumps({k:v for k,v in proof.items() if k!='acknowledged'}))
