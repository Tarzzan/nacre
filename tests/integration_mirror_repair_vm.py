#!/usr/bin/env python3
"""Retrait d’un membre et reconstruction RAID1, sur les images NACRE-V08 seulement."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
assert os.environ.get('NACRE_VM_LAB')=='1'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
SOURCE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SOURCE/'console'))
from native_storage import NativeClient,NativeError
client=NativeClient();base=Path('/home/ubuntu/nacre-fresh-test')
result=json.loads((base/'result.json').read_text());identifier=result['pool']
def request(method,**body):return client.request(method,'admin',body)
def command(*args):return subprocess.check_output(args,stderr=subprocess.STDOUT).decode()
def plan():return request('prepare',action='repair',volume=identifier,replace='disk-b',device='disk-c')
def commit(p):return request('commit',plan=p['id'],confirmation=p['confirmation'])
def state():return next(v for v in request('status')['provisioning']['deployments'] if v['id']==identifier)
v=state();target=Path(v['mountpoint'])/'data'
assert v['raid']['degraded']==0
snapshot=request('prepare',action='snapshot',volume=identifier)
commit(snapshot)
before=hashlib.sha256((target/'temoin.txt').read_bytes()).hexdigest()
try:plan();raise AssertionError('Miroir sain accepté')
except NativeError:pass
source=json.loads(command('findmnt','-J','-M',v['mountpoint'],'-o','SOURCE'))['filesystems'][0]['source'].split('[')[0]
for letter in 'ABC':
 observed=json.loads(command('lsblk','-J','-o','NAME,SERIAL','/dev/disk/by-id/virtio-NACRE-V08-'+letter))['blockdevices'][0]['serial']
 assert observed=='NACRE-V08-'+letter
# Injection de panne exclusivement sur le membre B de cette VM.
missing='/dev/disk/by-id/virtio-NACRE-V08-B'
command('sudo','mdadm','--manage',source,'--fail',missing,'--remove',missing)
assert state()['raid']['degraded']==1
assert hashlib.sha256((target/'temoin.txt').read_bytes()).hexdigest()==before
p=plan()
try:request('commit',plan=p['id'],confirmation='oui');raise AssertionError('Confirmation non vérifiée')
except NativeError:pass
out=commit(p);assert out['rebuilding']
try:commit(p);raise AssertionError('Rejeu accepté')
except NativeError:pass
# Redémarrer le démon pendant/juste après l’ajout ne doit jamais rejouer mdadm.
command('sudo','systemctl','restart','nacre-storage.service')
for _ in range(300):
 try:
  v=state()
  if v['phase']=='ready' and v['raid']['degraded']==0 and v['raid']['sync_action']=='idle':break
 except OSError:pass
 time.sleep(.2)
else:raise AssertionError('Miroir non reconstruit')
assert hashlib.sha256((target/'temoin.txt').read_bytes()).hexdigest()==before
assert set(v['members'])=={'disk-a','disk-c'}
assert 'linux_raid_member' in command('sudo','blkid','-p',missing)
# Le membre sorti est conservé : pas de wipefs ni de mkfs.
clone=commit(request('prepare',action='clone',volume=identifier,point=snapshot['id']))
assert hashlib.sha256(Path(clone['location'],'temoin.txt').read_bytes()).hexdigest()==before
result.update(native_snapshot_preserved_after_repair=True,mirror_rebuilt_on_replacement=True,data_hash_preserved_after_member_loss=True,old_member_signature_preserved=True,
              repair_restart_without_replay=True,healthy_mirror_repair_refused=True,exact_confirmation_required=True,
              original_pool_filesystem_preserved=True)
(base/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
