#!/usr/bin/env python3
"""Suite 0.4 dans une VM du banc 0.3 + trois disques virtuels D/E/F vierges."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'console'))
from native_storage import Engine, NativeError, NativeClient
from install_native import stage


def run(*args):return subprocess.check_output(args,text=True).strip()


def rpc(method,body=None):
    code="import sys,json;sys.path.insert(0,'/usr/local/lib/nacre-storage');from native_storage import NativeClient;r=json.load(sys.stdin);print(json.dumps(NativeClient().request(r['method'],'admin',r['body'])))"
    result=subprocess.run(['runuser','-u','ubuntu','--','python3','-c',code],input=json.dumps({'method':method,'body':body or {}}),text=True,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def prepare_fixture():
    if os.geteuid()!=0 or os.environ.get('NACRE_VM_LAB')!='1' or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() not in ('QEMU','Bochs'):
        raise RuntimeError('Banc QEMU dédié requis')
    disks=json.loads(run('lsblk','-J','-b','-o','NAME,TYPE,SERIAL,SIZE,MOUNTPOINTS'))['blockdevices']
    run('systemctl','stop','nacre-storage')
    for letter,serial in zip('efg','DEF'):
        node=next(d for d in disks if d['name']=='vd'+letter)
        if node.get('children') or node['serial']!='NACRE-LAB-'+serial or node['size']!=3*1024**3 or any(node.get('mountpoints') or []):
            raise RuntimeError('Disques virtuels inattendus ou déjà utilisés')
        if run('wipefs','--noheadings','--no-act','/dev/vd'+letter):raise RuntimeError('Le banc nécessite des images vierges')
    run('mkdir','-p','/srv/nacre-managed','/srv/nacre-lvm-restores')
    run('modprobe','btrfs');run('modprobe','dm_snapshot');run('modprobe','zfs')
    if '/srv/nacre-lab/btrfs' not in run('findmnt','-rn','-o','TARGET').splitlines():
        if next(d for d in disks if d['name']=='vdb')['serial']!='NACRE-LAB-A':raise RuntimeError('Source virtuelle Btrfs inattendue')
        run('mount','/dev/vdb','/srv/nacre-lab/btrfs')
    run('vgchange','-ay','nacre_test')
    path=Path('/etc/nacre-storage/policy.json')
    policy=json.loads(path.read_text())
    for volume in policy['volumes']:
        if volume['family']=='lvm':volume['restore_directory']='/srv/nacre-lvm-restores'
    policy['provisioning']={'enabled':True,'root':'/srv/nacre-managed','mount_on_start':True,
       'devices':[{'id':'disk-'+s.lower(),'path':'/dev/disk/by-id/virtio-NACRE-LAB-'+s,'serial':'NACRE-LAB-'+s,'bytes':3*1024**3,'initialize':True} for s in 'DEF']}
    path.write_text(json.dumps(policy))
    stage('/',1000)
    run('systemctl','daemon-reload')
    run('modprobe','md_mod');run('modprobe','raid1')
    run('systemctl','start','nacre-storage')
    for _ in range(100):
        if Path('/run/nacre-storage/control.sock').exists():break
        time.sleep(.1)
    return policy


def create_volume(engine,layout,filesystem,disks):
    plan=rpc('prepare',{'action':'provision','profile':{'name':'Test '+layout,'layout':layout,'filesystem':filesystem,'disk_bytes':[3*1024**3]*len(disks)},'devices':disks})
    result=rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})
    path=Path(result['location']);path.joinpath('volume-test.txt').write_text('créé sur un nouveau volume\n')
    assert os.stat(path).st_uid==1000
    try:engine.commit(1000,'admin',{'plan':plan['id'],'confirmation':plan['confirmation']})
    except NativeError:pass
    else:raise AssertionError('Plan rejoué')
    return result


def tests():
    engine=Engine(recover=False)
    single=create_volume(engine,'single','ext4',['disk-d'])
    mirror=create_volume(engine,'mirror','btrfs',['disk-e','disk-f'])
    # Le sous-volume du miroir est immédiatement utilisable par l'adaptateur Btrfs.
    plan=engine.prepare(1000,'admin',{'action':'snapshot','volume':mirror['object']})
    engine.commit(1000,'admin',{'plan':plan['id'],'confirmation':plan['confirmation']})
    cloneplan=engine.prepare(1000,'admin',{'action':'clone','volume':mirror['object'],'point':plan['id']})
    clone=engine.commit(1000,'admin',{'plan':cloneplan['id'],'confirmation':cloneplan['confirmation']})
    assert Path(clone['location'],'volume-test.txt').read_text()=='créé sur un nouveau volume\n'
    # Refus des disques réutilisés après la première écriture.
    try:engine.prepare(1000,'admin',{'action':'provision','profile':{'name':'Refus','layout':'single','filesystem':'ext4','disk_bytes':[1]},'devices':['disk-d']})
    except NativeError:pass
    else:raise AssertionError('Disque utilisé accepté')
    # Copie réelle depuis le point LVM 0.3, dans un worker systemd privé.
    point=next(p for p in engine.status()['points'] if p['volume']=='classic' and p['status']=='ready')
    plan=rpc('prepare',{'action':'clone','volume':'classic','point':point['id']})
    job=rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})['job']
    for _ in range(200):
        row=next(j for j in engine.restorations().list() if j['id']==job)
        if row['status'] not in ('queued','running'):break
        time.sleep(.1)
    assert row['status']=='done',row
    assert Path(row['location'],'version.txt').read_text()=='version 1\n'
    # Le montage temporaire du worker n'a pas été propagé sur l'hôte invité.
    mounts=run('findmnt','-rn','-o','TARGET')
    assert '/run/nacre-restore-' not in mounts
    status=engine.status()
    assert len(status['provisioning']['deployments'])==2
    assert all(d['mounted'] for d in status['provisioning']['deployments'])
    assert next(d for d in status['provisioning']['deployments'] if d['layout']=='mirror')['raid']['degraded']==0
    assert any(resource['path']==row['location'] for resource in engine.resources())
    result={'single':single,'mirror':mirror,'mirror_snapshot_clone':True,'lvm_restore':row,'host_view_mounts_visible':True,'worker_mount_namespace_private':True}
    Path('/home/ubuntu/provision-results.json').write_text(json.dumps(result,indent=2))
    engine.db.close()
    run('systemctl','start','nacre-storage')
    return result


def xfs_tests():
    if os.geteuid()!=0 or os.environ.get('NACRE_VM_LAB')!='1' or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() not in ('QEMU','Bochs'):
        raise RuntimeError('Banc QEMU dédié requis')
    assert run('lsblk','-dn','-o','SERIAL','/dev/vdc')=='NACRE-LAB-B'
    assert any(v['id']=='thin' and v['ready'] for v in rpc('status')['volumes'])
    run('mkfs.xfs','/dev/nacre_test/thin')
    run('mkdir','-p','/srv/nacre-xfs')
    run('mount','/dev/nacre_test/thin','/srv/nacre-xfs')
    Path('/srv/nacre-xfs/version-xfs.txt').write_text('version XFS 1\n')
    plan=rpc('prepare',{'action':'snapshot','volume':'thin'})
    rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})
    Path('/srv/nacre-xfs/version-xfs.txt').write_text('version XFS 2\n')
    plan=rpc('prepare',{'action':'clone','volume':'thin','point':plan['id']})
    job=rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})['job']
    for _ in range(200):
        row=next(j for j in rpc('status')['jobs'] if j['id']==job)
        if row['status'] not in ('queued','running'):break
        time.sleep(.1)
    assert row['status']=='done',row
    assert Path(row['location'],'version-xfs.txt').read_text()=='version XFS 1\n'
    assert Path('/srv/nacre-xfs/version-xfs.txt').read_text()=='version XFS 2\n'
    result=json.loads(Path('/home/ubuntu/provision-results.json').read_text())
    result['xfs_restore']=row
    Path('/home/ubuntu/provision-results.json').write_text(json.dumps(result,indent=2))
    return row


if __name__=='__main__':
    prepare_fixture()
    result=tests()
    print(json.dumps({'single':result['single']['object'],'mirror':result['mirror']['object'],'lvm_restore':result['lvm_restore']['status']}))
