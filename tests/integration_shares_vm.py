#!/usr/bin/env python3
"""Tests HTTP/SMB/restic dans la VM Nacre, jamais sur le NAS réel."""
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import urlencode

os.environ['NAS_ROOT']='/home/ubuntu/nacre-v05-console'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'console'))
import server as app


def request(route,body=None,raw=None):
    client=http.client.HTTPConnection('127.0.0.1',8767,timeout=120)
    headers={'Cookie':'nas_session='+TOKEN,'X-CSRF-Token':CSRF,'Content-Type':'application/json'}
    client.request('POST' if body is not None or raw is not None else 'GET','/api/'+route,
                   body=raw if raw is not None else json.dumps(body) if body is not None else None,headers=headers)
    response=client.getresponse();payload=response.read();client.close()
    if response.status!=200:raise RuntimeError('API '+route.split('?')[0]+' : '+str(response.status)+' '+payload.decode())
    return payload if route.startswith('download?') else json.loads(payload)


def smb(share,command,unauthorized=False,success=True):
    script='''set -eu
d=$(mktemp -d)
trap 'rm -rf "$d"' EXIT
if [ "$3" = bad ]; then
  printf 'username = refuse\npassword = Banc-test-uniquement-1234\n' > "$d/auth"  # gitleaks:allow — identifiant synthétique du banc VM uniquement
else
  { printf 'username = nas\npassword = '; cat /run/secrets/smb_password; } > "$d/auth"
fi
printf 'preuve SMB v05\n' > /tmp/nacre-client-source
smbclient "//127.0.0.1/$1" -A "$d/auth" -c "$2" >/dev/null 2>&1
'''
    from compose_support import arguments
    result=subprocess.run(arguments(app.ROOT,'exec','-T','fichiers','sh','-c',script,'sh',share,command,'bad' if unauthorized else 'ok'),capture_output=True,text=True)
    if (result.returncode==0)!=success:raise AssertionError('Résultat SMB inattendu pour '+share+' / '+command)


def wait_job(identifier):
    for _ in range(300):
        job=next(j for j in request('jobs') if j['id']==identifier)
        if job['status'] not in ('queued','running'):return job
        time.sleep(.1)
    raise RuntimeError('Tâche non terminée')


def main():
    assert os.geteuid()!=0 and os.environ.get('NACRE_VM_LAB')=='1'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
    resources=app.native_resources()
    mirror=next(r for r in resources if r.get('kind')=='volume' and r['name']=='Test mirror')
    single=next(r for r in resources if r.get('kind')=='volume' and r['name']=='Test single')
    area='native_'+mirror['id'];other='native_'+single['id']
    request('folder',{'area':area,'name':'preuve-v05'})
    request('upload?'+urlencode({'area':area,'path':'preuve-v05','name':'original.txt'}),raw=b'version native 1\n')
    request('rename',{'area':area,'path':'preuve-v05/original.txt','name':'renomme.txt'})
    request('trash',{'area':area,'path':'preuve-v05/renomme.txt'})
    trashed=next(t for t in request('trash') if t['area']==area and t['original']=='preuve-v05/renomme.txt')
    request('smb/share',{'name':'volume_test','area':area,'path':'','readonly':False,'users':['nas']})
    request('smb/share',{'name':'volume_lecture','area':area,'path':'preuve-v05','readonly':True,'users':['nas']})
    request('smb/user',{'name':'refuse','password':'Banc-test-uniquement-1234'})  # gitleaks:allow — identifiant synthétique du banc VM uniquement
    smb('volume_test','ls',unauthorized=True,success=False)
    smb('volume_test','get .nacre-trash/'+trashed['id']+' /tmp/secret',success=False)
    request('restore',{'id':trashed['id']})
    assert request('download?'+urlencode({'area':area,'path':'preuve-v05/renomme.txt'}))==b'version native 1\n'
    smb('volume_test','put /tmp/nacre-client-source preuve-v05/smb.txt; get preuve-v05/smb.txt /tmp/nacre-client-copy')
    assert Path(mirror['path'],'preuve-v05/smb.txt').read_text()=='preuve SMB v05\n'
    smb('volume_lecture','put /tmp/nacre-client-source interdit.txt',success=False)
    # Dépôt sur le deuxième volume, et capture de ce volume aussi : son dépôt
    # interne et les corbeilles ne doivent pas être capturés récursivement.
    repo=request('protection/repository',{'name':'Banc multi-volumes','target':other,'password':'Chiffrement-banc-uniquement-1234'})['id']  # gitleaks:allow — identifiant synthétique du banc VM uniquement
    smb('volume_test','get .nacre-repos/inexistant /tmp/secret',success=False)
    job=request('protection/snapshot',{'repo':repo,'sources':['fichiers',area,other],'configuration':False,'video':False,'label':'Multi-volumes'})['job']
    completed=wait_job(job);assert completed['status']=='done',completed
    point=json.loads(completed['result'])['snapshot']
    restored=wait_job(request('protection/restore',{'repo':repo,'snapshot':point})['job'])
    assert restored['status']=='done',restored
    destination=app.ROOT/'data/restaurations'/json.loads(restored['result'])['directory']
    data=next(p for p in destination.glob('volume-Test-mirror-*'))
    assert (data/'preuve-v05/renomme.txt').read_text()=='version native 1\n'
    assert len(list(destination.glob('volume-*')))==2
    assert not list(destination.rglob('.nacre-repos')) and not list(destination.rglob('.nacre-trash'))
    # Plan automatique réellement distribué par le scheduler du serveur de QA.
    plan=request('protection/plan',{'name':'Plan natif QA','repo':repo,'sources':[area],'configuration':False,'video':False,'enabled':True,'time':'23:59','timezone':'UTC','weekdays':list(range(7))})['id']
    with app.database() as db:db.execute('UPDATE plans SET next_run=? WHERE id=?',(time.time()-10,plan))
    for _ in range(100):
        with app.database() as db:row=dict(db.execute('SELECT * FROM plans WHERE id=?',(plan,)).fetchone())
        if row['last_job']:break
        time.sleep(.1)
    assert wait_job(row['last_job'])['status']=='done'
    request('protection/plan',{'id':plan,'name':'Plan natif QA','repo':repo,'sources':[area],'configuration':False,'video':False,'enabled':False})
    # Indisponibilité du contrôleur : aucun nouveau fichier ni ancien partage
    # natif ne doit être proposé comme un dossier de secours sur le système.
    subprocess.run(['sudo','-n','systemctl','stop','nacre-storage'],check=True)
    try:
        for _ in range(100):
            shares=request('smb')['shares']
            if not next(s for s in shares if s['name']=='volume_test')['available']:break
            time.sleep(.1)
        # Attendre la convergence SMB du watcher, et pas seulement sa vue API.
        for _ in range(100):
            config=(app.ROOT/'state/samba/smb.conf').read_text()
            if 'available = no' in config:break
            time.sleep(.1)
        time.sleep(1)
        smb('volume_test','ls',success=False)
        smb('fichiers','ls')
    finally:subprocess.run(['sudo','-n','systemctl','start','nacre-storage'],check=True)
    for _ in range(150):
        if next(s for s in request('smb')['shares'] if s['name']=='volume_test')['available']:break
        time.sleep(.1)
    smb('volume_test','get preuve-v05/renomme.txt /tmp/nacre-client-copy')
    result={'native_http_write_trash_restore':True,'smb_rw':True,'smb_readonly_enforced':True,'unauthorized_account_refused':True,
            'private_trash_vetoed':True,'multi_volume_encrypted_backup_restore':True,'internal_data_excluded':True,
            'automatic_plan_selected_native_source_verified':True,'offline_native_share_disabled_base_preserved':True,'native_share_recovery':True}
    Path('/home/ubuntu/shares-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':
    app.initialize();TOKEN,CSRF=app.make_session('admin');main()
