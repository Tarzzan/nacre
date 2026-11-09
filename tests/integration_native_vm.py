#!/usr/bin/env python3
"""Banc destructible UNIQUEMENT dans la VM QEMU NACRE-LAB dédiée.

Ce script formate les trois disques virtuels identifiés ci-dessous. Ne pas
l'exécuter sur le serveur NAS. Son garde vérifie hyperviseur + noms + séries.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'console'))
from native_storage import Engine, NativeError, NativeClient
from install_native import stage


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def guard():
    assert os.geteuid() == 0 and os.environ.get('NACRE_VM_LAB') == '1', 'Banc VM explicitement requis'
    vendor = Path('/sys/class/dmi/id/sys_vendor').read_text().strip()
    assert vendor in ('QEMU', 'Bochs'), vendor
    devices = json.loads(run('lsblk', '-J', '-b', '-o', 'NAME,SERIAL,SIZE,TYPE,MOUNTPOINTS'))['blockdevices']
    expected = {'vdb': 'NACRE-LAB-A', 'vdc': 'NACRE-LAB-B', 'vdd': 'NACRE-LAB-C'}
    for name, serial in expected.items():
        item = next(x for x in devices if x['name'] == name)
        assert item['serial'] == serial and item['type'] == 'disk' and item['size'] == 3 * 1024**3
        assert not item.get('children') and not any(item.get('mountpoints') or [])
        assert not run('wipefs', '--noheadings', '-n', '/dev/' + name), 'Le banc doit partir de disques virtuels vierges'


def policy_for_fixture():
    run('mkdir', '-p', '/srv/nacre-lab/btrfs', '/srv/nacre-lab/classic', '/srv/nacre-lab/zfs')
    run('mkfs.btrfs', '/dev/vdb')
    run('mount', '/dev/vdb', '/srv/nacre-lab/btrfs')
    run('btrfs', 'subvolume', 'create', '/srv/nacre-lab/btrfs/data')
    run('mkdir', '/srv/nacre-lab/btrfs/snapshots', '/srv/nacre-lab/btrfs/restores')
    source = '/srv/nacre-lab/btrfs/data'
    filesystem_uuid = run('findmnt', '-n', '-T', source, '-o', 'UUID')
    import re
    subvolume_uuid = re.search(r'^\s*UUID:\s+(\S+)', run('btrfs', 'subvolume', 'show', source), re.M)[1]
    run('pvcreate', '/dev/vdc')
    run('vgcreate', 'nacre_test', '/dev/vdc')
    run('lvcreate', '-L', '512M', '-n', 'classic', 'nacre_test')
    run('lvcreate', '--type', 'thin-pool', '-L', '1G', '-n', 'pool', 'nacre_test')
    run('lvcreate', '-V', '512M', '-T', 'nacre_test/pool', '-n', 'thin')
    run('mkfs.ext4', '/dev/nacre_test/classic')
    run('mount', '/dev/nacre_test/classic', '/srv/nacre-lab/classic')
    run('zpool', 'create', '-m', 'none', 'nacre_lab', '/dev/vdd')
    run('zfs', 'create', '-o', 'mountpoint=/srv/nacre-lab/zfs', 'nacre_lab/data')
    run('zfs', 'create', '-o', 'mountpoint=none', '-o', 'canmount=off', 'nacre_lab/restores')
    classic = json.loads(run('lvs', '--reportformat', 'json', '-o', 'vg_uuid,lv_uuid', 'nacre_test/classic'))['report'][0]['lv'][0]
    thin = json.loads(run('lvs', '--reportformat', 'json', '-o', 'vg_uuid,lv_uuid', 'nacre_test/thin'))['report'][0]['lv'][0]
    volumes = [
        {'id': 'btrfs', 'name': 'Btrfs laboratoire', 'family': 'btrfs', 'source': source,
         'filesystem_uuid': filesystem_uuid, 'subvolume_uuid': subvolume_uuid,
         'snapshots': '/srv/nacre-lab/btrfs/snapshots', 'restores': '/srv/nacre-lab/btrfs/restores'},
        {'id': 'zfs', 'name': 'ZFS laboratoire', 'family': 'zfs', 'dataset': 'nacre_lab/data',
         'guid': run('zfs', 'get', '-Hp', '-o', 'value', 'guid', 'nacre_lab/data'),
         'restore_parent': 'nacre_lab/restores', 'restore_parent_guid': run('zfs', 'get', '-Hp', '-o', 'value', 'guid', 'nacre_lab/restores')},
        {'id': 'classic', 'name': 'LVM classique laboratoire', 'family': 'lvm', 'lv': 'nacre_test/classic',
         'vg_uuid': classic['vg_uuid'].strip(), 'lv_uuid': classic['lv_uuid'].strip(), 'segtype': 'linear', 'cow_bytes': 128 * 1024**2},
        {'id': 'thin', 'name': 'LVM thin laboratoire', 'family': 'lvm', 'lv': 'nacre_test/thin',
         'vg_uuid': thin['vg_uuid'].strip(), 'lv_uuid': thin['lv_uuid'].strip(), 'segtype': 'thin'},
    ]
    stage('/', 1000)
    Path('/etc/nacre-storage/policy.json').write_text(json.dumps({'version':1,'allowed_uid':1000,'volumes':volumes}))
    run('mkdir', '-p', '/var/lib/nacre-storage')
    return volumes


def direct_tests(volumes):
    engine = Engine()
    results = {}
    for path in ('/srv/nacre-lab/btrfs/data/version.txt', '/srv/nacre-lab/classic/version.txt', '/srv/nacre-lab/zfs/version.txt'):
        Path(path).write_text('version 1\n')
    for volume in volumes:
        plan = engine.request(1000, {'method':'prepare','actor':'admin','body':{'action':'snapshot','volume':volume['id']}})
        result = engine.request(1000, {'method':'commit','actor':'admin','body':{'plan':plan['id'],'confirmation':plan['confirmation']}})
        results[volume['id']] = {'snapshot': result, 'point': plan['id']}
        try:
            engine.commit(1000, 'admin', {'plan':plan['id'],'confirmation':plan['confirmation']})
        except NativeError:
            pass
        else:
            raise AssertionError('Plan rejoué')
    for path in ('/srv/nacre-lab/btrfs/data/version.txt', '/srv/nacre-lab/classic/version.txt', '/srv/nacre-lab/zfs/version.txt'):
        Path(path).write_text('version 2\n')
    for family in ('btrfs', 'zfs'):
        plan = engine.prepare(1000, 'admin', {'action':'clone','volume':family,'point':results[family]['point']})
        clone = engine.commit(1000, 'admin', {'plan':plan['id'],'confirmation':plan['confirmation']})
        if family == 'btrfs':
            assert Path(clone['location'], 'version.txt').read_text() == 'version 1\n'
            Path(clone['location'], 'clone-only.txt').write_text('nouveau fichier\n')
            assert Path('/srv/nacre-lab/btrfs/data/version.txt').read_text() == 'version 2\n'
        else:
            assert run('zfs','get','-Hp','-o','value','mounted',clone['location']) == 'no'
            assert run('zfs','get','-Hp','-o','value','canmount',clone['location']) == 'noauto'
            # Montage de validation effectué par le banc, pas par l'API.
            run('zfs','set','mountpoint=/srv/nacre-lab/zfs-clone',clone['location'])
            run('zfs','mount',clone['location'])
            assert Path('/srv/nacre-lab/zfs-clone/version.txt').read_text() == 'version 1\n'
            assert Path('/srv/nacre-lab/zfs/version.txt').read_text() == 'version 2\n'
        results[family]['clone'] = clone
    run('mkdir', '/srv/nacre-lab/classic-view')
    run('mount','-t','ext4','-o','ro,noload,nodev,nosuid,noexec','/dev/'+results['classic']['snapshot']['location'],'/srv/nacre-lab/classic-view')
    assert Path('/srv/nacre-lab/classic-view/version.txt').read_text() == 'version 1\n'
    run('umount','/srv/nacre-lab/classic-view')
    assert all(point['status']=='ready' for point in engine.status()['points'])
    # Une identité différente après préparation ne doit déclencher aucune capture.
    plan = engine.prepare(1000,'admin',{'action':'snapshot','volume':'btrfs'})
    policy_path=Path('/etc/nacre-storage/policy.json')
    original=policy_path.read_text();changed=json.loads(original)
    changed['volumes'][0]['subvolume_uuid']='changed'
    policy_path.write_text(json.dumps(changed))
    try:engine.commit(1000,'admin',{'plan':plan['id'],'confirmation':plan['confirmation']})
    except NativeError:pass
    else:raise AssertionError('Politique modifiée acceptée')
    policy_path.write_text(original)
    engine.db.close()
    return results


def socket_tests():
    stage('/',1000)
    run('systemctl','daemon-reload')
    run('systemctl','enable','--now','nacre-storage.service')
    run('systemctl','restart','nacre-storage.service')
    import time
    for _ in range(30):
        if Path('/run/nacre-storage/control.sock').exists():break
        time.sleep(.1)
    code = "import sys;sys.path.insert(0,'/usr/local/lib/nacre-storage');from native_storage import NativeClient;s=NativeClient().request('status','admin');assert s['connected'] and len(s['volumes'])==4 and all(v['ready'] for v in s['volumes']) and all(p['status']=='ready' for p in s['points']),s;print('peer_uid_allowed')"
    assert run('runuser','-u','ubuntu','--','python3','-c',code)=='peer_uid_allowed'
    try:NativeClient().request('status','admin')
    except NativeError:pass
    else:raise AssertionError('UID root non autorisé accepté par le socket')
    run('systemctl','restart','nacre-storage.service')
    for _ in range(30):
        if Path('/run/nacre-storage/control.sock').exists():break
        time.sleep(.1)
    assert run('runuser','-u','ubuntu','--','python3','-c',code)=='peer_uid_allowed'
    return {'allowed_uid':1000,'unauthorized_uid_refused':True,'restart_persistence':True}


if __name__ == '__main__':
    guard()
    volumes = policy_for_fixture()
    result = {'engine':direct_tests(volumes), 'socket':socket_tests(), 'host_disks_exposed':False}
    Path('/home/ubuntu/native-results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'verified':list(result['engine']),'socket':result['socket']}))
