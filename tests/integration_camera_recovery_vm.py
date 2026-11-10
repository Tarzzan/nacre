#!/usr/bin/env python3
"""Capture/reprise vidéo ARM64 sur deux VM vierges successives et privées.

La source et la cible sont arrêtées successivement par le contrôleur du banc.
Les données caméra, clés et attentes ne doivent jamais être ajoutées au dépôt.
"""
import argparse,hashlib,json,os,secrets,shutil,sqlite3,subprocess,sys,time,tarfile,tempfile
from pathlib import Path
assert os.environ.get('NACRE_VM_LAB')=='1' and os.uname().machine=='aarch64'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('capture','restore'));phase=p.parse_args().phase
SOURCE=Path(__file__).resolve().parents[1];BASE=Path('/home/ubuntu/nacre-fresh-test');ROOT=BASE/'restored';BUNDLE=BASE/'camera-bundle'
os.environ['NAS_ROOT']=str(ROOT);os.environ['NAS_RESTIC_BIN']=str(SOURCE/'.tools/restic')
sys.path.insert(0,str(SOURCE/'console'));sys.path.insert(0,str(SOURCE))
from system_recovery import capture,prepare,samba_restore,attach,run,restic
from compose_support import arguments

def digest(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,value):path.write_text(json.dumps(value,indent=2));path.chmod(0o600)
def private_video_files():
 container=run(arguments(ROOT,'ps','--all','--quiet','video')).decode().strip();assert container
 with tempfile.TemporaryFile() as f:
  run(['docker','cp',container+':/config/.','-'],stdout=f);f.seek(0)
  with tarfile.open(fileobj=f) as archive:
   result={}
   for member in archive:
    name=str(Path(member.name))
    if name in ('.jwt_secret','backup_config.yaml'):
     assert member.isfile()
     with archive.extractfile(member) as source:checksum=hashlib.file_digest(source,'sha256').hexdigest()
     result[name]={'sha256':checksum,'uid':member.uid,'gid':member.gid,'mode':member.mode}
   assert result['.jwt_secret']['uid']==0 and result['.jwt_secret']['mode']==0o600
   return result

def smb(user,share,operation,ok=True):
 secret='Banc-reprise-samba-seulement-42' # gitleaks:allow — fixture synthétique
 script='set -eu; umask 077; p=$(mktemp); trap \'rm -f "$p"\' EXIT; cat > "$p"; smbclient "//127.0.0.1/$1" -A "$p" -c "$2" >/dev/null 2>&1'
 r=subprocess.run(arguments(ROOT,'exec','-T','fichiers','sh','-c',script,'sh',share,operation),input=f'username = {user}\npassword = {secret}\n'.encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 assert (r.returncode==0)==ok

if phase=='capture':
 assert json.loads((BASE/'camera-source-proof.json').read_text())['recording_decoded']
 io=json.loads((BASE/'concurrent-io.json').read_text());assert io['orderly_reboot_hashes_and_services']
 from native_storage import NativeClient
 status=NativeClient().request('status','admin');pool=json.loads((BASE/'result.json').read_text())['pool']
 volume=next(r for r in status['resources'] if r['id']==pool);assert volume['writable']
 BUNDLE.mkdir(mode=0o700)
 expected=json.loads((BASE/'camera-expectations.json').read_text())
 expected.update(samba_sid=run(arguments(ROOT,'exec','-T','fichiers','net','getlocalsid')).decode().split()[-1],
                 config_sha256=digest(ROOT/'state/frigate/config.yml'),pool=pool,private_video_files=private_video_files())
 save(BUNDLE/'camera-expectations.json',expected);save(BUNDLE/'concurrent-io.json',io)
 shutil.copytree(BASE/'bundle/history',BUNDLE/'history')
 access=BUNDLE/'source-lost/state/console';access.mkdir(parents=True,mode=0o700)
 shutil.copyfile(BASE/'bundle/source-lost/state/console/acces.txt',access/'acces.txt');(access/'acces.txt').chmod(0o600)
 save(ROOT/'state/console/recovery-volumes.json',{'native_'+pool:volume['path']})
 run(['systemctl','--user','stop','nacre-console.service']);run(arguments(ROOT,'stop'))
 with (ROOT/'state/native-recovery.tar').open('wb') as f:run(['sudo',sys.executable,str(SOURCE/'console/system_recovery.py'),'native-export'],stdout=f)
 key=BUNDLE/'bootstrap.key';key.write_text(secrets.token_hex(32)+'\n');key.chmod(0o600)
 restic(BUNDLE/'recovery-repo',key,'init')
 receipt=capture(ROOT,BUNDLE/'recovery-repo',key)
 save(BUNDLE/'receipt.json',receipt)
 print(json.dumps({'offline_capture_complete':receipt['complete'],'native_volumes':receipt['native_volumes'],'source_services_stopped':True}));sys.exit()

assert not ROOT.exists() and not Path('/var/lib/nacre-storage').exists()
assert not run(['docker','image','ls','-q']).strip() and not run(['docker','volume','ls','-q']).strip()
expected=json.loads((BUNDLE/'camera-expectations.json').read_text());receipt=json.loads((BUNDLE/'receipt.json').read_text())
prepare(BUNDLE/'recovery-repo',BUNDLE/'bootstrap.key',receipt['snapshot'],ROOT)
assert digest(ROOT/'state/frigate/config.yml')==expected['config_sha256']
for r in expected['recordings']:
 local=ROOT/'data/video'/Path(r['path']).relative_to('/media/frigate');assert digest(local)==r['sha256']
with sqlite3.connect(ROOT/'state/console/console.db') as db:
 assert db.execute('SELECT sum(enabled) FROM plans').fetchone()[0]==0
 assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
 assert db.execute('SELECT count(*) FROM tickets').fetchone()[0]==0
samba_restore(ROOT);attach(ROOT,'a'*24,BUNDLE/'history')
assert json.loads(restic(BUNDLE/'history',ROOT/'state/console/keys'/('a'*24+'.key'),'snapshots','--json'))
io=json.loads((BUNDLE/'concurrent-io.json').read_text());folder=ROOT/'data/fichiers/reprise-volumes'/('native_'+expected['pool'])
for r in io['acknowledged']:assert digest(folder/r['name'])==r['sha256']
run([sys.executable,str(ROOT/'console/install_restic.py')])
run(arguments(ROOT,'pull','video'));run(arguments(ROOT,'up','-d','--no-build','fichiers','video'))
assert private_video_files()==expected['private_video_files']
assert run(arguments(ROOT,'exec','-T','fichiers','net','getlocalsid')).decode().split()[-1]==expected['samba_sid']
for attempt in range(60):
 try:smb('alice','fichiers','get temoin.txt /tmp/witness');break
 except AssertionError:
  if attempt==59:raise
  time.sleep(.5)
smb('desactive','fichiers','ls',False);smb('alice','lecture','put /tmp/witness refused.txt',False)
run(['sudo','loginctl','enable-linger','ubuntu']);run([sys.executable,str(ROOT/'console/install_service.py')])
shutil.copyfile(BUNDLE/'camera-expectations.json',BASE/'camera-expectations.json')
# Le vérificateur HTTP lit uniquement les identifiants synthétiques du banc.
shutil.copytree(BUNDLE/'source-lost',BASE/'bundle/source-lost')
save(BASE/'camera-recovery-proof.json',{'architecture':os.uname().machine,'fresh_guest_without_images_volumes_or_native_catalog':True,
 'restored_camera_configuration_exact':True,'root_private_video_files_hashes_owners_modes_preserved':True,'restored_original_recording_hashes':len(expected['recordings']),
 'concurrent_files_restored':len(io['acknowledged']),'historical_repository_unlocked':True,'samba_sid_preserved':True,
 'samba_password_and_permissions':True,'sessions_revoked_and_plans_disabled':True,'native_data_restored_to_ordinary_directories':True})
print((BASE/'camera-recovery-proof.json').read_text())
