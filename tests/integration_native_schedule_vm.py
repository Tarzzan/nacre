#!/usr/bin/env python3
"""Banc de la programmation des captures natives, UNIQUEMENT dans la VM QEMU NACRE-LAB dédiée.

Part de la VM laissée par integration_native_vm.py : quatre volumes inscrits, service natif actif. Ce banc ne formate
rien. Il réinstalle le service depuis les sources copiées, puis laisse la console, sous son compte non privilégié,
programmer de vraies captures par le socket du vrai service, et vérifie chaque point sur le stockage.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / 'console')]
VOLUMES = ('btrfs', 'zfs', 'classic', 'thin')
RESULTS = Path('/home/ubuntu/native-schedule-results.json')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def guard():
    assert os.environ.get('NACRE_VM_LAB') == '1', 'Banc VM explicitement requis'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU', 'Bochs')
    policy = json.loads(Path('/etc/nacre-storage/policy.json').read_text()) if os.geteuid() == 0 else None
    if policy is not None:
        assert policy['allowed_uid'] == 1000 and [volume['id'] for volume in policy['volumes']][:4] == list(VOLUMES), 'Fixture du banc natif attendue'


def inventory():
    """Objets natifs « nacre_… » réellement présents sur le stockage du banc, par volume."""
    lvs = [name for name in run('lvs', '--noheadings', '-o', 'lv_name,origin', 'nacre_test').splitlines()]
    return {'btrfs': sorted(os.listdir('/srv/nacre-lab/btrfs/snapshots')),
            'zfs': sorted(line.split('@')[1] for line in run('zfs', 'list', '-H', '-t', 'snapshot', '-o', 'name', 'nacre_lab/data').splitlines() if '@' in line),
            'classic': sorted(line.split()[0] for line in lvs if line.split()[1:] == ['classic']),
            'thin': sorted(line.split()[0] for line in lvs if line.split()[1:] == ['thin'])}


def console():
    """Côté console, sous le compte non privilégié : réglage, occurrences, plafond, occurrence manquée, désactivation."""
    assert os.geteuid() == 1000
    root = Path(tempfile.mkdtemp(prefix='nacre-schedule-'))
    import server
    server.ROOT, server.STATE = root, root / 'state/console'
    server.DB = server.STATE / 'console.db'
    server.initialize()
    import native_retention
    import native_schedule
    out = {}
    status = server.native_storage('status', 'admin')
    assert status['connected'] and {volume['id']: volume['ready'] for volume in status['volumes'] if volume['id'] in VOLUMES} == dict.fromkeys(VOLUMES, True), status['volumes']
    before = {point['id'] for point in status['points']}

    def force(volume, late=1):
        value = native_schedule.read(server, volume)
        native_schedule.write(server, volume, {**value, 'next_run': time.time() - late})

    def points():
        return {point['id']: point for point in server.native_storage('status', 'admin')['points'] if point['id'] not in before}

    # Sans la confirmation, rien n'est activé et rien ne part.
    try:
        native_schedule.configure(server, {'volume': 'btrfs', 'enabled': True, 'cap': 1}, 'admin')
    except server.Problem:
        pass
    else:
        raise AssertionError('Programmation activée sans confirmation')
    assert native_schedule.tick(server, time.time() + 86400 * 30) == [] and points() == {}
    for volume in VOLUMES:
        native_schedule.configure(server, {'volume': volume, 'enabled': True, 'cap': 1, 'confirmation': 'PROGRAMMER ' + volume}, 'admin')
        force(volume)
    first = dict(native_schedule.tick(server))
    assert first == dict.fromkeys(VOLUMES, 'done'), first
    created = points()
    assert sorted(point['volume'] for point in created.values()) == sorted(VOLUMES)
    assert all(point['actor'] == 'programmation' and point['status'] == 'ready' for point in created.values()), created
    assert all(native_schedule.marked(server, point['volume']) == [identifier] for identifier, point in created.items())
    out['first'] = {point['volume']: identifier for identifier, point in created.items()}
    # Un plan déjà validé ne se rejoue pas, même sous le compte de la programmation.
    try:
        server.native_storage('commit', native_schedule.ACTOR, {'plan': out['first']['btrfs'], 'confirmation': 'CAPTURER btrfs'})
    except server.Problem:
        pass
    else:
        raise AssertionError('Plan rejoué')
    # Plafond atteint : aucune capture, pour aucune famille.
    for volume in VOLUMES:
        force(volume)
    capped = dict(native_schedule.tick(server))
    assert capped == dict.fromkeys(VOLUMES, 'capped') and len(points()) == 4, capped
    # Occurrence trop ancienne : manquée, pas rattrapée ; puis une occurrence à l'heure, sous un plafond relevé.
    native_schedule.configure(server, {'volume': 'btrfs', 'enabled': True, 'cap': 2, 'confirmation': 'PROGRAMMER btrfs'}, 'admin')
    for volume in ('zfs', 'classic', 'thin'):
        native_schedule.configure(server, {'volume': volume, 'enabled': False}, 'admin')
    force('btrfs', native_schedule.GRACE + 60)
    assert native_schedule.tick(server) == [('btrfs', 'missed')] and len(points()) == 4
    force('btrfs')
    assert native_schedule.tick(server) == [('btrfs', 'done')]
    second = [identifier for identifier, point in points().items() if point['volume'] == 'btrfs' and identifier != out['first']['btrfs']]
    assert len(second) == 1 and len(points()) == 5
    out['second_btrfs'] = second[0]
    # La règle de conservation traite les deux points programmés ; les points antérieurs du banc restent des captures manuelles.
    preview = native_retention.simulate(server, {'volume': 'btrfs', 'keep_last': 1}, 'admin')
    assert [point['id'] for point in preview['keep']] == [second[0]] and [point['id'] for point in preview['remove']] == [out['first']['btrfs']], preview
    assert all(point['manual'] for point in preview['protected']) and not preview['deletion']
    out['protected_btrfs'] = len(preview['protected'])
    # Désactivée, la programmation ne demande plus rien.
    native_schedule.configure(server, {'volume': 'btrfs', 'enabled': False}, 'admin')
    assert native_schedule.tick(server, time.time() + 86400 * 30) == [] and len(points()) == 5
    with server.database() as db:
        out['journal'] = [tuple(row) for row in db.execute("SELECT username,action FROM audit WHERE username='programmation' ORDER BY rowid")]
    assert [action for _, action in out['journal']].count('Capture native programmée') == 5
    print(json.dumps(out))


def main():
    guard()
    assert os.geteuid() == 0
    # Après un redémarrage de la VM, les deux montages faits à la main par le banc natif sont à refaire, dans l'invité seulement.
    serials = {item['name']: item.get('serial') for item in json.loads(run('lsblk', '-J', '-o', 'NAME,SERIAL'))['blockdevices']}
    assert serials.get('vdb') == 'NACRE-LAB-A', serials
    for device, target in (('/dev/vdb', '/srv/nacre-lab/btrfs'), ('/dev/nacre_test/classic', '/srv/nacre-lab/classic')):
        if subprocess.run(['findmnt', '-n', target], capture_output=True).returncode:
            run('mount', device, target)
    from install_native import stage
    stage('/', 1000)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'restart', 'nacre-storage.service')
    for _ in range(50):
        if Path('/run/nacre-storage/control.sock').exists():
            break
        time.sleep(.1)
    before = inventory()
    out = json.loads(run('runuser', '-u', 'ubuntu', '--', 'env', 'NACRE_VM_LAB=1', 'python3', str(Path(__file__).resolve()), 'console').splitlines()[-1])
    after = inventory()
    expected = {volume: ['nacre_' + out['first'][volume]] for volume in VOLUMES}
    expected['btrfs'].append('nacre_' + out['second_btrfs'])
    # Sur le stockage : exactement les points annoncés, rien de plus, et tous en lecture seule.
    for volume in VOLUMES:
        assert sorted(set(after[volume]) - set(before[volume])) == sorted(expected[volume]), (volume, before[volume], after[volume])
    for name in expected['btrfs']:
        assert run('btrfs', 'property', 'get', '-ts', '/srv/nacre-lab/btrfs/snapshots/' + name, 'ro') == 'ro=true'
    for volume in ('classic', 'thin'):
        assert run('lvs', '--noheadings', '-o', 'lv_attr', 'nacre_test/' + expected[volume][0]).strip()[1] == 'r'
    assert run('systemctl', 'is-active', 'nacre-storage.service') == 'active'
    result = {'verified': list(VOLUMES), 'created_on_storage': {volume: len(expected[volume]) for volume in VOLUMES}, 'capped_without_capture': True, 'missed_without_capture': True,
              'replayed_plan_refused': True, 'disabled_without_capture': True, 'manual_points_protected': out['protected_btrfs'], 'journal_lines': len(out['journal'])}
    RESULTS.write_text(json.dumps(result, indent=1))
    print(json.dumps(result))


if __name__ == '__main__':
    guard()
    console() if sys.argv[1:] == ['console'] else main()
