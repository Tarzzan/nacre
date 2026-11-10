#!/usr/bin/env python3
"""Vérifier les services installés par le navigateur, exclusivement dans une VM jetable.

NACRE_VM_LAB=1 NAS_PORT=8769 python3 tests/integration_web_install_vm.py
Prérequis du banc : smbclient. Aucune installation n'est déclenchée par ce script.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile


def main():
    if os.environ.get('NACRE_VM_LAB') != '1' or os.getuid() == 0:
        raise SystemExit('VM jetable explicitement autorisée et compte non root requis.')
    vendor = Path('/sys/class/dmi/id/sys_vendor')
    if not vendor.exists() or vendor.read_text().strip() not in ('QEMU', 'Bochs'):
        raise SystemExit('Ce contrôle est réservé au banc QEMU.')
    root = Path(__file__).resolve().parents[1]
    os.environ['NAS_ROOT'] = str(root)
    sys.path.insert(0, str(root/'console'))
    import server
    token, _ = server.make_session('admin')
    def get(path):
        connection = http.client.HTTPConnection('127.0.0.1', int(os.environ.get('NAS_PORT', '8766')), timeout=30)
        try:
            connection.request('GET', '/api/'+path, headers={'Cookie': 'nas_session='+token})
            response = connection.getresponse()
            body = json.loads(response.read())
            assert response.status == 200, (path, response.status)
            return body
        finally:
            connection.close()
    try:
        catalog, overview = get('components'), get('overview')
        completed = {j.get('component') for j in catalog['jobs'] if j['status']=='done'}
        assert {'fichiers','video'} <= completed
        services = {s['name']:s for s in overview['services']}
        assert services['fichiers']['state']=='running'
        assert services['video']['state']=='running' and services['video']['health']=='healthy'
        stats = server.video_json('/api/stats')
        assert stats['cameras']=={}, 'Le banc neuf doit rester sans caméra réelle.'
        with server.database() as db:
            assert db.execute('SELECT count(*) FROM plans').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM repositories').fetchone()[0]==0
        with tempfile.TemporaryDirectory(prefix='nacre-web-smb-') as directory:
            temp = Path(directory)
            auth = temp/'auth'
            server.private_write(auth, 'username = nas\npassword = '+(root/'state/smb_password').read_text().strip()+'\n')
            data = os.urandom(1024*1024)
            source, target = temp/'source.bin', temp/'read.bin'
            source.write_bytes(data)
            remote = 'nacre-proof-'+os.urandom(8).hex()+'.bin'
            def smb(share, command):
                return subprocess.run(['smbclient','//127.0.0.1/'+share,'-p','1445','-A',str(auth),'-m','SMB3','-c',command], capture_output=True, timeout=30)
            result = smb('fichiers',f'put {source} {remote}; get {remote} {target}')
            assert result.returncode==0, 'Écriture/lecture SMB refusée.'
            assert target.read_bytes()==data
            assert (root/'data/fichiers'/remote).read_bytes()==data
            denied = smb('video',f'put {source} {remote}')
            assert denied.returncode != 0 and b'NT_STATUS_ACCESS_DENIED' in denied.stdout+denied.stderr
            assert not (root/'data/video'/remote).exists()
            assert smb('fichiers','del '+remote).returncode==0
        proof = {
            'architecture':platform.machine(),
            'docker':server.command(['docker','info','--format','{{.ServerVersion}}']).strip(),
            'compose':server.command(['docker','compose','version','--short']).strip(),
            'samba':server.compose('exec','-T','fichiers','smbd','--version').strip(),
            'frigate':stats['service']['version'],
            'web_jobs_done':sorted(completed),
            'smb_roundtrip_bytes':len(data), 'smb_sha256':hashlib.sha256(data).hexdigest(),
            'smb_video_write_denied':True,'frigate_health':'healthy',
            'camera_count':0,'backup_plans':0,'backup_repositories':0,
        }
        print(json.dumps(proof,indent=2))
    finally:
        with server.database() as db:db.execute('DELETE FROM sessions WHERE token=?',(server.digest(token),))


if __name__=='__main__':main()
