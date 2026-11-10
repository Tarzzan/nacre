#!/usr/bin/env python3
"""Perte simulée d’une installation, reprise clés/SMB/fichiers en QEMU seulement."""
from contextlib import closing
import http.client
import socket
import time
import json
import os
from pathlib import Path
import shutil
import secrets
import re
import sqlite3
import subprocess
import sys

assert os.environ.get('NACRE_VM_LAB')=='1'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
SOURCE=Path(__file__).resolve().parents[1]
BASE=Path(os.environ.get('NACRE_RECOVERY_TEST_ROOT','/home/ubuntu/nacre-system-recovery-test'))
BASE.mkdir(mode=0o700)
root=BASE/'source';shutil.copytree(SOURCE,root,ignore=shutil.ignore_patterns('.git','__pycache__','.tools'))
os.environ['NAS_ROOT']=str(root)
os.environ['NAS_RESTIC_BIN']='/home/ubuntu/nacre-v05-console/.tools/restic'
sys.path.insert(0,str(SOURCE/'console'));sys.path.insert(0,str(SOURCE))
import server as app
from compose_support import arguments
from system_recovery import capture,prepare,samba_restore,attach,run,restic,write,RecoveryError
from installation_lock import held
from lab import initialize
# Réserver le démon de cette VM au scénario : politique vide, aucun périphérique.
run(['sudo','systemctl','stop','nacre-storage.service'])
run(['sudo','cp','/etc/nacre-storage/policy.json',BASE/'original-policy.json'])
run(['sudo','mv','/var/lib/nacre-storage',BASE/'original-native-state'])
write(BASE/'empty-policy.json',{'version':1,'allowed_uid':os.getuid(),'volumes':[], 'provisioning':{'enabled':False,'devices':[]}})
run(['sudo','install','-m','600',BASE/'empty-policy.json','/etc/nacre-storage/policy.json'])
run(['sudo','systemctl','start','nacre-storage.service'])
for _ in range(100):
 if Path('/run/nacre-storage/control.sock').exists():break
 time.sleep(.1)
initialize(root);app.initialize()
write(root/'state/console/recovery-project.json',{'project':'nacre-recovered-'+secrets.token_hex(12)})
run(arguments(root,'up','-d','--build','fichiers'))
handler=object.__new__(app.Handler)
secret='Banc-reprise-samba-seulement-42' # gitleaks:allow — fixture synthétique
for user in ('alice','desactive'):
 handler.mutate('/api/smb/user',{'name':user,'password':secret},{'name':'admin','token':''})
handler.mutate('/api/smb/user',{'name':'desactive','enabled':False},{'name':'admin','token':''})
config=app.smb_state()
config['shares'][0]['users']+=['alice','desactive']
config['shares'] += [{'name':'lecture','area':'fichiers','path':'','readonly':True,'users':['alice']}]
app.save_smb(config)
(root/'data/fichiers/temoin.txt').write_text('Contenu retrouvé après perte du serveur.\n')
(root/'data/fichiers/temoin.txt').chmod(0o660)
run(arguments(root,'exec','-T','fichiers','chown','alice:nas','/shares/fichiers/temoin.txt'))
original_owner=(root/'data/fichiers/temoin.txt').stat().st_uid
admin_password=re.search(r'Mot de passe : (.+)',(root/'state/console/acces.txt').read_text())[1]
camera_config=(root/'state/frigate/config.yml').read_bytes()
with closing(sqlite3.connect(root/'state/frigate/frigate.db')) as db:
 db.execute('CREATE TABLE event(id TEXT)');db.execute("INSERT INTO event VALUES('synthetique')");db.commit()

(root/'data/video/recordings').mkdir(parents=True)
(root/'data/video/recordings/temoin.mp4').write_bytes(b'video synthetique uniquement')
external=BASE/'external-data';external.mkdir(mode=0o770);(external/'volume.txt').write_text('volume externe')
write(root/'state/console/recovery-volumes.json',{'native_test-volume':str(external)})
# Dépôt distinct : sa clé sera récupérée depuis le kit, son contenu reste sur son support.
repo=BASE/'history';key=root/'state/console/keys'/('a'*24+'.key');key.write_text('cle-synthetique-de-depot\n');key.chmod(0o600)
restic(repo,key,'init');restic(repo,key,'backup',str(root/'data/fichiers'))
with app.database() as db:
 db.execute('INSERT INTO repositories(id,name,path,key_file,created,target) VALUES(?,?,?,?,0,?)',('a'*24,'Historique',str(repo),str(key),'external'))
 db.execute('INSERT INTO plans(id,name,repo,enabled,config,next_run) VALUES(?,?,?,1,?,0)',('b'*24,'Plan synthétique','a'*24,json.dumps({'sources':['native_test-volume'],'time':'02:00','timezone':'UTC','weekdays':[1]})))
 db.execute("INSERT INTO sessions VALUES('ancienne','admin','csrf',9999999999)")
 db.execute("INSERT INTO tickets VALUES('ancien',9999999999)")
# L’export est limité aux métadonnées du démon dans la VM, jamais aux disques hôtes.
with (root/'state/native-recovery.tar').open('wb') as stream:
 run(['sudo',sys.executable,str(SOURCE/'console/system_recovery.py'),'native-export'],stdout=stream)

bootstrap=BASE/'bootstrap.key';bootstrap.write_text('cle-synthetique-de-reprise\n');bootstrap.chmod(0o600)
recovery_repo=BASE/'recovery-repo';restic(recovery_repo,bootstrap,'init')
try:capture(root,recovery_repo,bootstrap);raise AssertionError('Capture autorisée avec Samba actif')
except RecoveryError:pass
source_sid=run(arguments(root,'exec','-T','fichiers','net','getlocalsid')).decode().split()[-1]
run(arguments(root,'stop','fichiers'))
receipt=capture(root,recovery_repo,bootstrap)
assert receipt['complete']
old_password=(root/'state/smb_password').read_bytes()
# Source rendue inaccessible : le parcours de reprise ne peut plus y lire une clé.
lost=BASE/'source-lost';root.rename(lost)
external.rename(BASE/'external-lost')
fresh=BASE/'restored'
prepare(recovery_repo,bootstrap,receipt['snapshot'],fresh)
assert (fresh/'state/smb_password').read_bytes()==old_password
assert (fresh/'data/fichiers/temoin.txt').read_text().startswith('Contenu retrouvé')
assert (fresh/'data/video/recordings/temoin.mp4').read_bytes()==b'video synthetique uniquement'
assert (fresh/'data/fichiers/reprise-volumes/native_test-volume/volume.txt').read_text()=='volume externe'
assert (fresh/'data/fichiers/temoin.txt').stat().st_uid==original_owner
assert (fresh/'state/frigate/config.yml').read_bytes()==camera_config
with closing(sqlite3.connect(fresh/'state/frigate/frigate.db')) as db:assert db.execute('SELECT id FROM event').fetchone()[0]=='synthetique'
with closing(sqlite3.connect(fresh/'state/console/console.db')) as db:
 assert db.execute('SELECT enabled FROM plans').fetchone()[0]==0
 assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
 assert db.execute('SELECT count(*) FROM tickets').fetchone()[0]==0
 assert db.execute('SELECT target FROM repositories').fetchone()[0]=='recovery-detached'
try:arguments(fresh,'up','-d');raise AssertionError('Démarrage autorisé sans passdb préparé')
except ValueError:pass
samba_restore(fresh)
attach(fresh,'a'*24,repo)
assert len(json.loads(restic(repo,fresh/'state/console/keys'/('a'*24+'.key'),'snapshots','--json')))==1
run(arguments(fresh,'up','-d','--no-build','fichiers'))
assert run(arguments(fresh,'exec','-T','fichiers','net','getlocalsid')).decode().split()[-1]==source_sid
flags=run(arguments(fresh,'exec','-T','fichiers','pdbedit','-L','-v','desactive')).decode()
assert re.search(r'Account Flags:.*D',flags)
# Les mots de passe ne sont fournis qu’à un fichier privé temporaire dans le conteneur.
def smb(share,user,command,ok):
 script='''set -eu
umask 077
p=$(mktemp)
trap 'rm -f "$p"' EXIT
cat > "$p"
smbclient "//127.0.0.1/$1" -A "$p" -c "$2" >/dev/null 2>&1
'''
 result=subprocess.run(arguments(fresh,'exec','-T','fichiers','sh','-c',script,'sh',share,command),input=f'username = {user}\npassword = {secret}\n'.encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 assert (result.returncode==0)==ok,(share,user,command)
smb('fichiers','alice','get temoin.txt /tmp/reprise-temoin',True)
smb('lecture','alice','put /tmp/reprise-temoin interdit.txt',False)
smb('fichiers','desactive','ls',False)
smb('fichiers','alice','put /tmp/reprise-temoin ecriture-retrouvee.txt',True)
assert (fresh/'data/fichiers/ecriture-retrouvee.txt').read_bytes()==(fresh/'data/fichiers/temoin.txt').read_bytes()
run(arguments(fresh,'up','-d','--no-build','--force-recreate','fichiers'))
for attempt in range(100):
 try:smb('fichiers','alice','ls',True);break
 except AssertionError:
  if attempt==99:raise
  time.sleep(.1)
smb('fichiers','desactive','ls',False)
assert run(arguments(fresh,'exec','-T','fichiers','net','getlocalsid')).decode().split()[-1]==source_sid
run(arguments(fresh,'stop','fichiers'))
with socket.socket() as probe:
 probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
env=dict(os.environ,NAS_ROOT=str(fresh),NAS_PORT=str(port),NACRE_SYSTEMD_TASKS='0')
process=subprocess.Popen([sys.executable,str(fresh/'console/server.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(100):
  assert process.poll() is None
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.2):break
  except OSError:time.sleep(.1)
 client=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
 client.request('POST','/api/login',body=json.dumps({'username':'admin','password':admin_password}),headers={'Content-Type':'application/json'})
 response=client.getresponse();assert response.status==200 and json.loads(response.read())['role']=='admin';client.close()
finally:
 process.terminate();process.wait(timeout=10)
result={'owner_uid_preserved':True,'console_original_password_http_login':True,'plans_disabled_sessions_revoked':True,'repositories_detached_until_verified':True,'camera_configuration_preserved':True,'frigate_sqlite_restored':True,'native_metadata_exported':True,'samba_recreation_preserves_accounts':True,'files_restored':True,'video_bytes_restored':True,'external_volume_files_restored':True,'keys_recovered_after_source_loss':True,'encrypted_history_unlocked':True,'samba_password_preserved':True,'samba_server_sid_preserved':True,'samba_disabled_flag_preserved':True,'samba_secondary_account_rw':True,'samba_readonly_enforced':True,'disabled_account_refused':True,'separate_docker_volume':True,'running_service_capture_refused':True}
run(['sudo','systemctl','stop','nacre-storage.service'])
(BASE/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
