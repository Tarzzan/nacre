#!/usr/bin/env python3
"""Phases invité du banc de coupure ; uniquement VM QEMU et images NACRE-V08."""
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path

if os.environ.get('NACRE_VM_LAB') != '1' or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() not in ('QEMU','Bochs'):
    raise SystemExit('VM QEMU explicitement réservée au test requise.')
SOURCE=Path(__file__).resolve().parents[1]
BASE=Path('/home/ubuntu/nacre-fresh-test')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('phase',choices=('install-audit','begin','observe','finish'))
phase=parser.parse_args().phase

def command(*args):
    return subprocess.check_output(args,stderr=subprocess.PIPE,text=True)

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def write(path,value):
    with path.open('x') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)

if phase=='install-audit':
    assert os.geteuid()==0
    for letter in 'ABC':
        p='/dev/disk/by-id/virtio-NACRE-V08-'+letter
        assert json.loads(command('lsblk','-J','-o','NAME,SERIAL',p))['blockdevices'][0]['serial']=='NACRE-V08-'+letter
    original=Path('/usr/sbin/mdadm');saved=original.with_name('mdadm.nacre-test-real')
    assert original.is_file() and not saved.exists()
    original.rename(saved)
    original.write_text('''#!/usr/bin/python3
import json,os,sys,time
with open('/var/log/nacre-test-mdadm.jsonl','a') as f:
 json.dump({'args':sys.argv[1:],'time':time.time()},f);f.write('\\n');f.flush();os.fsync(f.fileno())
os.execv('/usr/sbin/mdadm.nacre-test-real',['mdadm',*sys.argv[1:]])
''')
    original.chmod(0o755)
    print(json.dumps({'vm_only_mdadm_audit_installed':True}));sys.exit()

sys.path.insert(0,str(SOURCE/'console'))
from native_storage import NativeClient,NativeError
client=NativeClient()
result=json.loads((BASE/'result.json').read_text());identifier=result['pool']
def request(method,**body):return client.request(method,'admin',body)
def commit(p):return request('commit',plan=p['id'],confirmation=p['confirmation'])
def state():
    s=request('status')
    return s,next(v for v in s['provisioning']['deployments'] if v['id']==identifier)
def identity(device):
    md=dict(line.split('=',1) for line in command('sudo','mdadm','--detail','--export',device).splitlines() if '=' in line)
    return {'md_uuid':md['MD_UUID'],'fs_uuid':command('sudo','blkid','-p','-s','UUID','-o','value',device).strip()}

def physical(volume):
    device=json.loads(command('findmnt','-J','-M',volume['mountpoint'],'-o','SOURCE'))['filesystems'][0]['source'].split('[')[0]
    device=str(Path(device).resolve());md=Path('/sys/class/block')/Path(device).name/'md'
    return device,md

if phase=='begin':
    _,volume=state();assert volume['phase']=='ready' and volume['raid']['degraded']==0 and volume['raid']['sync_action']=='idle'
    target=Path(volume['mountpoint'])/'data';witness=target/'coupure.bin'
    with witness.open('xb') as f:
        for _ in range(64):f.write(os.urandom(1024*1024))
        f.flush();os.fsync(f.fileno())
    fd=os.open(target,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
    snapshot=request('prepare',action='snapshot',volume=identifier);commit(snapshot)
    device,md=physical(volume);expected=identity(device)
    for letter in 'ABC':
        p='/dev/disk/by-id/virtio-NACRE-V08-'+letter
        assert json.loads(command('lsblk','-J','-o','NAME,SERIAL',p))['blockdevices'][0]['serial']=='NACRE-V08-'+letter
    command('sudo','mdadm','--manage',device,'--fail','/dev/disk/by-id/virtio-NACRE-V08-B','--remove','/dev/disk/by-id/virtio-NACRE-V08-B')
    assert 'linux_raid_member' in command('sudo','blkid','-p','/dev/disk/by-id/virtio-NACRE-V08-B')
    p=request('prepare',action='repair',volume=identifier,replace='disk-b',device='disk-c')
    write(BASE/'powercut.json',{'pool':identifier,'plan':p,'snapshot':snapshot['id'],'sha256':digest(witness),'original':expected,'old_member_signature_preserved':True})
    assert commit(p)['rebuilding']
    print(json.dumps({'repair_started':True,'plan':p['id']}));sys.exit()

proof=json.loads((BASE/'powercut.json').read_text())
if phase=='observe':
    s,volume=state();device,md=physical(volume)
    action=next(a for a in s['actions'] if a['id']==proof['plan']['id'])
    progress=(md/'sync_completed').read_text().strip()
    done,total=map(int,progress.split('/'))
    assert 0<done<total and (md/'sync_action').read_text().strip() in ('recover','resync')
    assert volume['phase']=='repairing' and action['status']=='running'
    print(json.dumps({'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'done':done,'total':total,'phase':volume['phase'],'action':action['status'],'sync_action':(md/'sync_action').read_text().strip(),'degraded':int((md/'degraded').read_text())}));sys.exit()

for _ in range(600):
    s,volume=state()
    if volume['phase']=='ready' and volume['raid']['degraded']==0 and volume['raid']['sync_action']=='idle':break
    time.sleep(.5)
else:raise AssertionError('Reconstruction non terminée')
device,md=physical(volume);assert identity(device)==proof['original']
assert set(volume['members'])=={'disk-a','disk-c'}
assert digest(Path(volume['mountpoint'])/'data/coupure.bin')==proof['sha256']
clone=commit(request('prepare',action='clone',volume=identifier,point=proof['snapshot']))
assert digest(Path(clone['location'])/'coupure.bin')==proof['sha256']
try:commit(proof['plan']);raise AssertionError('Ancien plan rejoué')
except NativeError:pass
log=[json.loads(line) for line in command('sudo','cat','/var/log/nacre-test-mdadm.jsonl').splitlines()]
adds=[r for r in log if '--add' in r['args']]
assert len(adds)==1
assert not any('--create' in r['args'] or '--force' in r['args'] for r in log)
assert sum(a['action']=='repair' for a in s['actions'])==1
out={'architecture':os.uname().machine,'original_md_and_fs_uuid_preserved':True,'data_64_mib_sha256_preserved':True,'snapshot_sha256_preserved':True,'two_expected_members_synchronized':True,'mdadm_add_executions':len(adds),'audited_readwrite_requests':sum('--readwrite' in r['args'] for r in log),'catalog_resume_requests':volume.get('repair',{}).get('resume_requests',0),'no_force_or_create_after_fault':True,'consumed_plan_replay_refused':True,'repair_journal_single_action':True}
write(BASE/'powercut-result.json',out);print(json.dumps(out))
