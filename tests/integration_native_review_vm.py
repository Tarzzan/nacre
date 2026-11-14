#!/usr/bin/env python3
"""Banc de la relecture des restaurations restées « à vérifier », UNIQUEMENT dans la VM QEMU NACRE-LAB dédiée.

Part de la VM laissée par integration_native_vm.py. Ne formate rien. Interrompt de vraies restaurations Btrfs, ZFS et
LVM, puis vérifie que le service natif accorde son journal à l'état réel du stockage, sans rien créer ni supprimer, et
que la suppression de points n'est plus bloquée. Les coupures sont injectées dans l'invité seulement.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import integration_native_delete_vm as base

SOURCE, POLICY, run, ask, refused = base.SOURCE, base.POLICY, base.run, base.ask, base.refused
RESULTS = Path('/home/ubuntu/native-review-results.json')
CATALOG = '/var/lib/nacre-storage/catalog.db'


def crash(volume, point, moment):
    """Moteur à part, tué juste avant ou juste après la commande qui crée la copie. Ne répond jamais."""
    from native_service import Engine
    from native_storage import execute

    def runner(argv, pass_fds=()):
        copying = argv[:3] == ['btrfs', 'subvolume', 'snapshot'] or argv[:2] == ['zfs', 'clone']
        if copying and moment == 'before':
            os._exit(9)
        out = execute(argv, pass_fds)
        if copying:
            os._exit(9)
        return out
    engine = Engine(runner=runner, recover=False)
    plan = engine.prepare(1000, 'admin', {'action': 'clone', 'volume': volume, 'point': point})
    engine.commit(1000, 'admin', {'plan': plan['id'], 'confirmation': plan['confirmation']})
    os._exit(1)


def age(*identifiers):
    """Vieillir des opérations dans le catalogue de l'invité : le service ne tranche qu'une fois leur commande forcément finie."""
    with sqlite3.connect(CATALOG) as db:
        db.executemany('UPDATE actions SET ts=ts-600 WHERE id=?', [(identifier,) for identifier in identifiers])


def actions():
    return {item['id']: item for item in ask('status')['actions'] if item['action'] == 'clone'}


def main():
    out = {}
    for device, target in (('/dev/vdb', '/srv/nacre-lab/btrfs'), ('/dev/nacre_test/classic', '/srv/nacre-lab/classic')):
        if subprocess.run(['findmnt', '-n', target], capture_output=True).returncode:
            run('mount', device, target)
    from install_native import stage
    stage('/', 1000)
    policy = json.loads(POLICY.read_text())
    run('mkdir', '-m', '700', '-p', '/srv/nacre-lab/restore-classic')
    policy['deletion'] = True
    policy['volumes'][2]['restore_directory'] = '/srv/nacre-lab/restore-classic'
    POLICY.write_text(json.dumps(policy))
    run('systemctl', 'daemon-reload')
    base.service('restart')
    load = Path('/srv/nacre-lab/classic/charge.bin')
    load.write_bytes(os.urandom(64 * 2**20))
    run('sync')

    def capture(volume):
        plan = ask('prepare', {'action': 'snapshot', 'volume': volume})
        ask('commit', {'plan': plan['id'], 'confirmation': plan['confirmation']})
        return plan['id']

    def delete(volume, point):
        plan = ask('prepare', {'action': 'delete', 'volume': volume, 'points': [point]})
        return ask('commit', {'plan': plan['id'], 'confirmation': plan['confirmation']})

    known = set(actions())
    points = {volume: [capture(volume), capture(volume)] for volume in ('btrfs', 'zfs', 'classic')}

    # 1. Btrfs et ZFS : restauration coupée juste avant, puis juste après la création de la copie.
    base.service('stop')
    for volume in ('btrfs', 'zfs'):
        for moment in ('before', 'after'):
            code = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'crash', volume, points[volume][0], moment], env={**os.environ, 'NACRE_VM_LAB': '1'}).returncode
            assert code == 9, (volume, moment, code)
    base.service('start')
    interrupted = {identifier: item for identifier, item in actions().items() if identifier not in known}
    by_volume = {volume: sorted((item for item in interrupted.values() if item['volume'] == volume), key=lambda item: item['ts']) for volume in ('btrfs', 'zfs')}
    assert all(len(by_volume[volume]) == 2 and all(item['status'] == 'uncertain' for item in by_volume[volume]) for volume in by_volume), interrupted
    # Tant qu'elle est « à vérifier », et récente, la restauration protège tout son volume.
    out['blocked_while_uncertain'] = refused('prepare', {'action': 'delete', 'volume': 'btrfs', 'points': [points['btrfs'][1]]})
    assert 'restauration' in out['blocked_while_uncertain'] and all(item['status'] == 'uncertain' for item in actions().values() if item['id'] in interrupted)
    restores = {'btrfs': sorted(os.listdir('/srv/nacre-lab/btrfs/restores')), 'zfs': run('zfs', 'list', '-H', '-o', 'name', '-r', 'nacre_lab/restores').splitlines()}
    age(*interrupted)
    settled = actions()
    for volume in ('btrfs', 'zfs'):
        before, after = (settled[item['id']] for item in by_volume[volume])
        assert (before['status'], before['location']) == ('failed', ''), before
        assert after['status'] == 'done' and after['location'].endswith(after['object']), after
    # Rien n'a été créé ni supprimé par la relecture ; la copie Btrfs reconnue est lisible, la copie ZFS reste non montée.
    assert restores == {'btrfs': sorted(os.listdir('/srv/nacre-lab/btrfs/restores')), 'zfs': run('zfs', 'list', '-H', '-o', 'name', '-r', 'nacre_lab/restores').splitlines()}
    kept = settled[by_volume['btrfs'][1]['id']]
    assert Path(kept['location'], 'version.txt').read_text() == 'version 2\n' and any(item['id'] == 'clone-' + kept['id'] for item in ask('status')['resources'])
    assert by_volume['btrfs'][0]['object'] not in restores['btrfs'] and by_volume['btrfs'][1]['object'] in restores['btrfs']
    assert run('zfs', 'get', '-Hp', '-o', 'value', 'mounted', settled[by_volume['zfs'][1]['id']]['location']) == 'no'
    out['settled'] = {volume: {'cut_before_copy': 'failed', 'cut_after_copy': 'done'} for volume in ('btrfs', 'zfs')}
    # La suppression n'est plus bloquée ; le point dont dépend la copie ZFS reconnue reste protégé, à juste titre.
    assert delete('btrfs', points['btrfs'][1])['deleted'] == [points['btrfs'][1]]
    assert delete('zfs', points['zfs'][1])['deleted'] == [points['zfs'][1]]
    out['zfs_point_with_recognized_copy'] = refused('prepare', {'action': 'delete', 'volume': 'zfs', 'points': [points['zfs'][0]]})
    assert 'copie ZFS' in out['zfs_point_with_recognized_copy']

    # 2. LVM : la copie de fichiers est tuée en cours de route.
    plan = ask('prepare', {'action': 'clone', 'volume': 'classic', 'point': points['classic'][0]})
    job = ask('commit', {'plan': plan['id'], 'confirmation': plan['confirmation']})['job']
    killed = False
    for _ in range(2000):
        for entry in os.listdir('/proc'):
            if entry.isdigit():
                try:
                    command = Path('/proc', entry, 'cmdline').read_bytes()
                except OSError:
                    continue
                if b'native_restore.py' in command and job.encode() in command:
                    os.kill(int(entry), 9)
                    killed = True
        if killed:
            break
        time.sleep(.002)
    assert killed, 'Copie LVM terminée avant d’avoir pu être interrompue'
    time.sleep(32)       # le service ne déclare une tâche disparue qu'après trente secondes
    assert actions()[job]['status'] == 'uncertain'
    assert 'restauration' in refused('prepare', {'action': 'delete', 'volume': 'classic', 'points': [points['classic'][1]]})
    age(job)
    final = actions()[job]
    task = next(item for item in ask('status')['jobs'] if item['id'] == job)
    assert final['status'] == 'failed' and task['status'] == 'failed' and 'privé' in task['error'], (final, task)
    partial = Path('/srv/nacre-lab/restore-classic/restore_' + job)
    assert not any(item['id'] == 'restore-' + job for item in ask('status')['resources'])
    if partial.exists():
        assert partial.stat().st_uid == 0 and partial.stat().st_mode & 0o077 == 0
    assert delete('classic', points['classic'][1])['deleted'] == [points['classic'][1]]
    assert delete('classic', points['classic'][0])['deleted'] == [points['classic'][0]]      # le point qu'elle lisait n'est plus tenu
    out['lvm_copy_killed'] = {'settled': 'failed', 'partial_folder_private': True, 'deletion_unblocked': True}
    assert run('systemctl', 'is-active', 'nacre-storage.service') == 'active'
    reviews = sum('"event":"restore-review"' in line for line in run('journalctl', '-u', 'nacre-storage.service', '--no-pager').splitlines())
    assert reviews == 5, reviews      # quatre copies Btrfs et ZFS, une copie LVM
    RESULTS.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    base.guard()
    crash(*sys.argv[2:]) if sys.argv[1:2] == ['crash'] else main()
