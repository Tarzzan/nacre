#!/usr/bin/env python3
"""Banc de la suppression des points natifs, UNIQUEMENT dans la VM QEMU NACRE-LAB dédiée.

Part de la VM laissée par integration_native_vm.py : quatre volumes inscrits, un point par volume, service natif actif.
Ce banc ne formate rien. Il réinstalle le service depuis les sources copiées, crée de vrais points par le socket du vrai
service sous le compte non privilégié, puis en supprime, et vérifie chaque effet sur le stockage lui-même.
Les coupures sont injectées dans un moteur lancé à part, service arrêté : jamais ailleurs que dans cette VM.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / 'console')]
VOLUMES = ('btrfs', 'zfs', 'classic', 'thin')
RESULTS = Path('/home/ubuntu/native-delete-results.json')
POLICY = Path('/etc/nacre-storage/policy.json')
SOCKET = Path('/run/nacre-storage/control.sock')
CLIENT = '''import json,sys
sys.path.insert(0,sys.argv[1])
from native_storage import NativeClient,NativeError
try:print(json.dumps({'result':NativeClient().request(sys.argv[2],sys.argv[3],json.loads(sys.argv[4]))}))
except NativeError as error:print(json.dumps({'error':str(error)}))'''


class Refused(Exception):
    pass


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def guard():
    assert os.environ.get('NACRE_VM_LAB') == '1', 'Banc VM explicitement requis'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU', 'Bochs')
    if os.geteuid() != 0:
        return
    policy = json.loads(POLICY.read_text())
    assert policy['allowed_uid'] == 1000 and [volume['id'] for volume in policy['volumes']][:4] == list(VOLUMES), 'Fixture du banc natif attendue'
    serials = {item['name']: item.get('serial') for item in json.loads(run('lsblk', '-J', '-o', 'NAME,SERIAL'))['blockdevices']}
    assert serials.get('vdb') == 'NACRE-LAB-A', serials


def ask(method, body=None, actor='admin'):
    """Une requête au vrai service, par son socket, sous le compte non privilégié de la console."""
    reply = json.loads(run('runuser', '-u', 'ubuntu', '--', 'python3', '-c', CLIENT, str(SOURCE / 'console'), method, actor, json.dumps(body or {})).splitlines()[-1])
    if 'error' in reply:
        raise Refused(reply['error'])
    return reply['result']


def refused(method, body, actor='admin'):
    try:
        ask(method, body, actor)
    except Refused as error:
        return str(error)
    raise AssertionError('Requête acceptée à tort : ' + json.dumps(body))


def inventory():
    """Objets natifs « nacre_… » réellement présents sur le stockage du banc, par volume."""
    lvs = run('lvs', '--noheadings', '-o', 'lv_name,origin', 'nacre_test').splitlines()
    return {'btrfs': sorted(os.listdir('/srv/nacre-lab/btrfs/snapshots')),
            'zfs': sorted(line.split('@')[1] for line in run('zfs', 'list', '-H', '-t', 'snapshot', '-o', 'name', 'nacre_lab/data').splitlines() if '@' in line),
            'classic': sorted(line.split()[0] for line in lvs if line.split()[1:] == ['classic']),
            'thin': sorted(line.split()[0] for line in lvs if line.split()[1:] == ['thin'])}


def catalog(query, *values):
    with sqlite3.connect('file:/var/lib/nacre-storage/catalog.db?mode=ro', uri=True) as db:
        return db.execute(query, values).fetchall()


def service(action):
    run('systemctl', action, 'nacre-storage.service')
    if action != 'stop':
        for _ in range(100):
            if SOCKET.exists():
                try:
                    ask('status')
                    return
                except (Refused, subprocess.CalledProcessError):
                    pass
            time.sleep(.1)
        raise AssertionError('Service natif non joignable')


def swap(volume, name):
    """Remplacer un point par un autre objet de même nom : son identité native change."""
    if volume == 'btrfs':
        run('btrfs', 'subvolume', 'delete', '--commit-after', '/srv/nacre-lab/btrfs/snapshots/' + name)
        run('btrfs', 'subvolume', 'snapshot', '-r', '/srv/nacre-lab/btrfs/data', '/srv/nacre-lab/btrfs/snapshots/' + name)
    elif volume == 'zfs':
        run('zfs', 'destroy', 'nacre_lab/data@' + name)
        run('zfs', 'snapshot', 'nacre_lab/data@' + name)
    else:
        run('lvremove', '--yes', 'nacre_test/' + name)
        run('lvcreate', '--snapshot', '--permission', 'r', '--name', name, *(['--size', '128M'] if volume == 'classic' else []), 'nacre_test/' + volume)


def crash(volume, point, moment):
    """Moteur à part, tué juste avant ou juste après la commande destructive. Ne répond jamais."""
    from native_service import Engine
    from native_storage import execute

    def runner(argv, pass_fds=()):
        destructive = argv[:3] == ['btrfs', 'subvolume', 'delete'] or argv[:2] == ['zfs', 'destroy'] or argv[0] == 'lvremove'
        if destructive and moment == 'before':
            os._exit(9)
        out = execute(argv, pass_fds)
        if destructive:
            os._exit(9)
        return out
    engine = Engine(runner=runner, recover=False)
    plan = engine.prepare(1000, 'admin', {'action': 'delete', 'volume': volume, 'points': [point]})
    engine.commit(1000, 'admin', {'plan': plan['id'], 'confirmation': plan['confirmation']})
    os._exit(1)


def console(volume):
    """Côté console, sous le compte non privilégié : simulation, plan pour la liste affichée, validation, journal."""
    assert os.geteuid() == 1000
    root = Path(tempfile.mkdtemp(prefix='nacre-prune-'))
    import server
    server.ROOT, server.STATE = root, root / 'state/console'
    server.DB = server.STATE / 'console.db'
    server.initialize()
    import native_retention
    rule = {'volume': volume, 'keep_last': 1, 'manual': True}
    preview = native_retention.simulate(server, rule, 'admin')
    leaving = [point['id'] for point in preview['remove']]
    assert preview['deletion'] and len(leaving) == 1 and len(preview['keep']) == 1 and len(preview['protected']) == 1, preview
    with server.database() as db:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?)", ('native-scheduled:' + volume, json.dumps(leaving + ['f' * 32])))
    # Une liste qui n'est pas celle de la simulation ne produit aucun plan.
    try:
        native_retention.prune_prepare(server, {**rule, 'expected': []}, 'admin')
    except server.Problem:
        pass
    else:
        raise AssertionError('Plan préparé pour une liste non affichée')
    plan = native_retention.prune_prepare(server, {**rule, 'manual': True, 'expected': leaving}, 'admin')
    assert plan['confirmation'] == 'SUPPRIMER 1 POINT DE ' + volume and [point['id'] for point in plan['points']] == leaving, plan
    result = native_retention.prune_commit(server, {'volume': volume, 'plan': plan['id'], 'confirmation': plan['confirmation']}, 'admin')
    after = native_retention.simulate(server, {**rule, 'manual': True}, 'admin')
    with server.database() as db:
        journal = [tuple(row) for row in db.execute("SELECT username,action,detail FROM audit ORDER BY rowid")]
        marks = json.loads(db.execute('SELECT value FROM settings WHERE key=?', ('native-scheduled:' + volume,)).fetchone()['value'])
    assert result['ok'] and result['deleted'] == leaving and after['remove'] == [] and marks == ['f' * 32], (result, after, marks)
    assert journal == [('admin', 'Points natifs supprimés', volume + ' : 1 supprimé')], journal
    print(json.dumps({'deleted': result['deleted']}))


def main():
    out = {}
    for device, target in (('/dev/vdb', '/srv/nacre-lab/btrfs'), ('/dev/nacre_test/classic', '/srv/nacre-lab/classic')):
        if subprocess.run(['findmnt', '-n', target], capture_output=True).returncode:
            run('mount', device, target)
    from install_native import stage
    stage('/', 1000)
    run('systemctl', 'daemon-reload')
    service('restart')
    policy = json.loads(POLICY.read_text())
    assert 'deletion' not in policy
    witnesses = ('/srv/nacre-lab/btrfs/data/version.txt', '/srv/nacre-lab/classic/version.txt', '/srv/nacre-lab/zfs/version.txt')
    assert all(Path(path).read_text() == 'version 2\n' for path in witnesses)
    # Une charge sur le volume LVM classique, pour qu'une restauration dure le temps d'être observée.
    load = Path('/srv/nacre-lab/classic/charge.bin')
    load.write_bytes(os.urandom(64 * 2**20))
    run('sync')
    digest = hashlib.sha256(load.read_bytes()).hexdigest()

    def capture(volume):
        plan = ask('prepare', {'action': 'snapshot', 'volume': volume})
        ask('commit', {'plan': plan['id'], 'confirmation': plan['confirmation']})
        return plan['id']

    def delete(volume, points, **changes):
        plan = ask('prepare', {'action': 'delete', 'volume': volume, 'points': points})
        return plan, {'plan': plan['id'], 'confirmation': plan['confirmation'], **changes}

    def states():
        return {point['id']: point['status'] for point in ask('status')['points']}

    status = ask('status')
    assert status['deletion'] is False and all(volume['ready'] for volume in status['volumes']), status['volumes']
    old = {volume: [point['id'] for point in status['points'] if point['volume'] == volume] for volume in VOLUMES}
    assert all(len(old[volume]) == 1 for volume in VOLUMES) and set(states().values()) == {'ready'}, old
    fresh = {volume: [capture(volume) for _ in range(5)] for volume in VOLUMES}
    start = inventory()
    assert all(len(start[volume]) == 6 for volume in VOLUMES), start

    # 1. Sans accord de root dans la politique, aucune suppression n'est même préparée.
    out['refused_without_policy'] = refused('prepare', {'action': 'delete', 'volume': 'btrfs', 'points': fresh['btrfs'][:1]})
    policy['deletion'] = True
    POLICY.write_text(json.dumps(policy))
    assert ask('status')['deletion'] is True

    # 2. Suppression nominale : deux points par volume, exactement ceux-là.
    for volume in VOLUMES:
        plan, body = delete(volume, fresh[volume][:2])
        assert plan['confirmation'] == 'SUPPRIMER 2 POINTS DE ' + volume, plan
        refused('commit', body, actor='autre')
        refused('commit', {**body, 'confirmation': 'SUPPRIMER 3 POINTS DE ' + volume})
        assert inventory()[volume] == start[volume]
        result = ask('commit', body)
        assert result == {'ok': True, 'deleted': fresh[volume][:2], 'uncertain': [], 'kept': [], 'reason': ''}, result
        refused('commit', body)  # plan rejoué
    after = inventory()
    for volume in VOLUMES:
        assert set(start[volume]) - set(after[volume]) == {'nacre_' + point for point in fresh[volume][:2]} and set(after[volume]) < set(start[volume]), (volume, after[volume])
    now = states()
    assert all(point not in now for volume in VOLUMES for point in fresh[volume][:2]) and set(now.values()) == {'ready'} and len(now) == 16, now
    assert all(Path(path).read_text() == 'version 2\n' for path in witnesses) and hashlib.sha256(load.read_bytes()).hexdigest() == digest
    out['nominal'] = {volume: 2 for volume in VOLUMES}

    # 3. Un seul point refusé annule le plan entier : autre volume, inconnu, clone ZFS dépendant, point ZFS retenu.
    refused('prepare', {'action': 'delete', 'volume': 'btrfs', 'points': [fresh['btrfs'][2], fresh['zfs'][2]]})
    refused('prepare', {'action': 'delete', 'volume': 'btrfs', 'points': [fresh['btrfs'][2], 'f' * 32]})
    assert run('zfs', 'get', '-H', '-o', 'value', 'clones', 'nacre_lab/data@nacre_' + old['zfs'][0]).startswith('nacre_lab/restores/')
    out['refused_zfs_clone'] = refused('prepare', {'action': 'delete', 'volume': 'zfs', 'points': [fresh['zfs'][4], old['zfs'][0]]})
    held = 'nacre_lab/data@nacre_' + fresh['zfs'][4]
    run('zfs', 'hold', 'banc', held)
    out['refused_zfs_hold'] = refused('prepare', {'action': 'delete', 'volume': 'zfs', 'points': [fresh['zfs'][4]]})
    run('zfs', 'release', 'banc', held)
    # Politique modifiée entre le plan et sa validation.
    plan, body = delete('btrfs', [fresh['btrfs'][4]])
    POLICY.write_text(json.dumps({**policy, 'volumes': [{**policy['volumes'][0], 'name': 'Autre nom'}, *policy['volumes'][1:]]}))
    out['refused_policy_changed'] = refused('commit', body)
    POLICY.write_text(json.dumps(policy))
    assert inventory() == after

    # 4. Coupure pendant la suppression, juste avant puis juste après la commande, pour chaque famille.
    service('stop')
    for volume in VOLUMES:
        for point, moment in ((fresh[volume][2], 'before'), (fresh[volume][3], 'after')):
            code = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'crash', volume, point, moment], env={**os.environ, 'NACRE_VM_LAB': '1'}).returncode
            assert code == 9, (volume, moment, code)
            assert catalog('SELECT status FROM points WHERE id=?', point) == [('deleting',)]
            assert catalog("SELECT status FROM actions WHERE action='delete' AND object=?", 'nacre_' + point) == [('running',)]
    cut = inventory()
    for volume in VOLUMES:
        assert set(after[volume]) - set(cut[volume]) == {'nacre_' + fresh[volume][3]}, (volume, cut[volume])
    run('systemctl', 'start', 'nacre-storage.service')
    for _ in range(100):
        if catalog("SELECT COUNT(*) FROM points WHERE status='deleting'") == [(0,)] and SOCKET.exists():
            break
        time.sleep(.1)
    # Au redémarrage : « à vérifier », rien de rejoué.
    assert catalog("SELECT COUNT(*) FROM points WHERE status='uncertain'") == [(8,)] and inventory() == cut
    service('restart')
    now = states()  # la lecture d'état relit le stockage : présent → prêt, absent → retiré du catalogue
    for volume in VOLUMES:
        assert now.get(fresh[volume][2]) == 'ready' and fresh[volume][3] not in now, (volume, now)
        assert catalog("SELECT status FROM actions WHERE action='delete' AND object=?", 'nacre_' + fresh[volume][2]) == [('failed',)]
        assert catalog("SELECT status FROM actions WHERE action='delete' AND object=?", 'nacre_' + fresh[volume][3]) == [('done',)]
    assert inventory() == cut and set(now.values()) == {'ready'} and len(now) == 12
    out['interrupted'] = {volume: {'before_command': 'point intact, de nouveau prêt', 'after_command': 'point absent, retiré du catalogue'} for volume in VOLUMES}

    # 5. Identité modifiée après le plan : l'objet de remplacement n'est pas supprimé.
    for volume in VOLUMES:
        point = fresh[volume][2]
        plan, body = delete(volume, [point])
        swap(volume, 'nacre_' + point)
        reason = refused('commit', body)
        assert 'nacre_' + point in inventory()[volume] and states()[point] == 'invalid', (volume, reason)
        refused('prepare', {'action': 'delete', 'volume': volume, 'points': [point]})
        out.setdefault('refused_identity_changed', {})[volume] = reason
    assert inventory() == cut

    # 6. Point lu par une restauration : refusé pendant la copie, supprimable une fois la copie terminée et le point refermé.
    point = fresh['classic'][4]
    run('mkdir', '-m', '700', '-p', '/srv/nacre-lab/restore-classic')
    policy['volumes'][2]['restore_directory'] = '/srv/nacre-lab/restore-classic'
    POLICY.write_text(json.dumps(policy))
    plan = ask('prepare', {'action': 'clone', 'volume': 'classic', 'point': point})
    job = ask('commit', {'plan': plan['id'], 'confirmation': plan['confirmation']})
    out['refused_during_restore'] = refused('prepare', {'action': 'delete', 'volume': 'classic', 'points': [point]})
    assert 'restauration' in out['refused_during_restore'], out
    for _ in range(600):
        current = next(item for item in ask('status')['jobs'] if item['id'] == job['job'])
        if current['status'] not in ('queued', 'running'):
            break
        time.sleep(.2)
    assert current['status'] == 'done', current
    assert hashlib.sha256(Path(current['location'], 'charge.bin').read_bytes()).hexdigest() == digest
    run('mkdir', '-p', '/srv/nacre-lab/classic-view')
    run('mount', '-t', 'ext4', '-o', 'ro,noload', '/dev/nacre_test/nacre_' + point, '/srv/nacre-lab/classic-view')
    out['refused_open_lvm'] = refused('prepare', {'action': 'delete', 'volume': 'classic', 'points': [point]})
    run('umount', '/srv/nacre-lab/classic-view')
    plan, body = delete('classic', [point])
    assert ask('commit', body)['deleted'] == [point]

    # 7. Toute la chaîne depuis la console, sous son compte : la règle « garder le dernier » sort le plus ancien point Btrfs.
    chain = json.loads(run('runuser', '-u', 'ubuntu', '--', 'env', 'NACRE_VM_LAB=1', 'python3', str(Path(__file__).resolve()), 'console', 'btrfs').splitlines()[-1])
    assert chain['deleted'] == old['btrfs'], chain
    out['console_chain'] = 'simulation, plan, validation et journal depuis la console : 1 point Btrfs supprimé'

    # Bilan sur le stockage : exactement les points annoncés ont disparu, rien d'autre, et les données sont intactes.
    final = inventory()
    gone = {volume: {'nacre_' + fresh[volume][index] for index in (0, 1, 3)} for volume in VOLUMES}
    gone['classic'].add('nacre_' + point)
    gone['btrfs'].add('nacre_' + old['btrfs'][0])
    for volume in VOLUMES:
        assert set(start[volume]) - set(final[volume]) == gone[volume] and set(final[volume]) < set(start[volume]), (volume, final[volume])
        assert volume == 'btrfs' or 'nacre_' + old[volume][0] in final[volume]
    assert all(Path(path).read_text() == 'version 2\n' for path in witnesses) and hashlib.sha256(load.read_bytes()).hexdigest() == digest
    status = ask('status')
    assert all(volume['ready'] for volume in status['volumes']) and run('systemctl', 'is-active', 'nacre-storage.service') == 'active'
    journal = dict(catalog("SELECT status,COUNT(*) FROM actions WHERE action='delete' GROUP BY status"))
    assert journal == {'done': 14, 'failed': 4}, journal
    result = {'verified': list(VOLUMES), 'deleted_on_storage': {volume: len(gone[volume]) for volume in VOLUMES}, 'other_points_intact': True, 'data_intact': True,
              'journal': journal, **out}
    RESULTS.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    guard()
    crash(*sys.argv[2:]) if sys.argv[1:2] == ['crash'] else console(*sys.argv[2:]) if sys.argv[1:2] == ['console'] else main()
