#!/usr/bin/env python3
"""Retrait d'un montage de la fixture et refus de repli sur le système."""
import json
import os
from pathlib import Path
import subprocess
import time
import integration_shares_vm as qa


def main():
    assert os.geteuid()!=0 and os.environ.get('NACRE_VM_LAB')=='1'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
    qa.app.initialize();qa.TOKEN,qa.CSRF=qa.app.make_session('admin')
    mirror=next(r for r in qa.app.native_resources() if r.get('kind')=='volume' and r['name']=='Test mirror')
    area='native_'+mirror['id'];mountpoint=Path(mirror['path']).parent
    assert str(mountpoint).startswith('/srv/nacre-managed/managed-')
    # Un vrai dépôt existant est lisible par l'UID Unix nas, mais doit rester
    # inaccessible via SMB grâce au veto, y compris pour son propriétaire.
    repo=qa.request('protection/repository',{'name':'Veto QA','target':area,'password':'Cle-banc-veto-uniquement-1234'})['id']  # gitleaks:allow — identifiant synthétique du banc VM uniquement
    assert Path(mirror['path'],'.nacre-repos',repo,'config').is_file()
    qa.smb('volume_test','get .nacre-repos/'+repo+'/config /tmp/interdit',success=False)
    subprocess.run(['sudo','-n','umount','-l',str(mountpoint)],check=True)
    try:
        assert subprocess.run(['sudo','-n','test','!','-e',mirror['path']]).returncode==0
        try:qa.request('folder',{'area':area,'name':'ne-pas-creer'})
        except RuntimeError:pass
        else:raise AssertionError('Écriture sur un volume absent acceptée')
        for _ in range(150):
            config=(qa.app.ROOT/'state/samba/smb.conf').read_text()
            if 'available = no' in config:break
            time.sleep(.1)
        time.sleep(1)
        qa.smb('volume_test','ls',success=False)
        qa.smb('fichiers','ls')
        assert subprocess.run(['sudo','-n','test','!','-e',mirror['path']]).returncode==0, 'Aucun dossier hôte de remplacement ne doit être créé'
    finally:
        subprocess.run(['sudo','-n','systemctl','restart','nacre-storage'],check=True)
    for _ in range(150):
        if next(s for s in qa.request('smb')['shares'] if s['name']=='volume_test')['available']:break
        time.sleep(.1)
    qa.smb('volume_test','get preuve-v05/renomme.txt /tmp/nacre-client-copy')
    assert Path(mirror['path'],'preuve-v05/renomme.txt').read_text()=='version native 1\n'
    result={'actual_mount_disappearance_refuses_writes':True,'no_fallback_host_directory_created':True,
            'native_smb_disabled_on_loss':True,'base_smb_preserved':True,'remount_and_share_recovery':True,'existing_repository_vetoed':True}
    Path('/home/ubuntu/disappearance-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
