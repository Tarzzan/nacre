#!/usr/bin/env python3
"""Preuve de persistance après bootstrap, réservée à une VM jetable.

Avant puis après un redémarrage planifié :
NACRE_VM_LAB=1 NAS_PORT=8769 python3 tests/integration_host_bootstrap_vm.py [--after-reboot]
Samba doit avoir été installé depuis le navigateur.
"""
import hashlib
import http.client
import json
import os
import pwd
from pathlib import Path
import subprocess
import sys


def main():
    if os.environ.get('NACRE_VM_LAB')!='1' or os.getuid()==0:
        raise SystemExit('Compte non root et banc VM explicitement autorisé requis.')
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() not in ('QEMU','Bochs'):
        raise SystemExit('Banc QEMU requis.')
    root=Path(__file__).resolve().parents[1]
    os.environ['NAS_ROOT']=str(root);sys.path.insert(0,str(root/'console'))
    import server
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    record=server.STATE/'bootstrap-proof.json'
    after='--after-reboot' in sys.argv
    previous=json.loads(record.read_text()) if after else None
    if after:assert previous['boot_id']!=boot
    def run(args):return subprocess.check_output(args,text=True).strip()
    assert run(['systemctl','--user','is-active','nacre-console.service'])=='active'
    assert run(['systemctl','--user','is-enabled','nacre-console.service'])=='enabled'
    assert run(['loginctl','show-user',pwd.getpwuid(os.getuid()).pw_name,'-p','Linger','--value'])=='yes'
    pid=int(run(['systemctl','--user','show','nacre-console.service','-p','MainPID','--value']))
    def ticks(pid):return int(Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19])
    assert ticks(pid)<ticks(os.getppid()), 'La console doit avoir démarré avant la connexion SSH de contrôle.'
    docker=run(['systemd-run','--user','--pipe','--wait','--collect','--quiet','docker','info','--format','{{.ServerVersion}}'])
    token,_=server.make_session('admin')
    try:
        connection=http.client.HTTPConnection('127.0.0.1',int(os.environ.get('NAS_PORT','8766')),timeout=20)
        connection.request('GET','/api/components',headers={'Cookie':'nas_session='+token})
        response=connection.getresponse();catalog=json.loads(response.read());connection.close()
        assert response.status==200 and catalog['docker_ready']
        job=next(j for j in catalog['jobs'] if j.get('component')=='fichiers')
        assert job['status']=='done'
        if after:assert previous['job']==job['id']
    finally:
        with server.database() as db:db.execute('DELETE FROM sessions WHERE token=?',(server.digest(token),))
    data='Nacre bootstrap : fichier synthétique conservé.\n'
    witness=root/'data/fichiers/nacre-bootstrap-proof.txt'
    if not after:
        if witness.exists():raise SystemExit('Fichier témoin déjà présent ; choisir un banc neuf.')
        witness.write_text(data)
    assert witness.read_text()==data
    script='''set -eu
p=$(mktemp -d)
trap 'rm -rf "$p"' EXIT
cat > "$p/auth"
smbclient //127.0.0.1/fichiers -A "$p/auth" -m SMB3 -c "get nacre-bootstrap-proof.txt $p/read" >/dev/null 2>&1
sha256sum "$p/read"
'''
    auth='username = nas\npassword = '+(root/'state/smb_password').read_text().strip()+'\n'
    observed=server.compose('exec','-T','fichiers','sh','-c',script,data=auth).split()[0]
    assert observed==hashlib.sha256(data.encode()).hexdigest()
    with server.database() as db:
        assert db.execute('SELECT count(*) FROM plans').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM repositories').fetchone()[0]==0
    proof={'boot_id':boot,'after_reboot':after,'console_before_ssh':True,'service_active':True,
           'service_enabled':True,'linger':True,'docker_user_manager':docker,
           'compose':run(['docker','compose','version','--short']),
           'job':job['id'],'job_preserved':bool(after),'smb_sha256':observed,
           'smb_read_after_reboot':bool(after),'backup_plans':0,'backup_repositories':0}
    server.private_write(record,json.dumps(proof))
    print(json.dumps(proof,indent=2))


if __name__=='__main__':main()
