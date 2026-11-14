#!/usr/bin/env python3
"""Banc de la conservation automatique des points natifs, UNIQUEMENT dans la VM QEMU NACRE-LAB dédiée.

Part de la VM laissée par integration_native_vm.py : quatre volumes inscrits, un point manuel par volume. Ce banc ne
formate rien. Il réinstalle le service natif depuis les sources et accorde la suppression dans la politique de l'invité,
puis laisse la console, sous son compte non privilégié, programmer de vraies captures et appliquer la règle après
chacune, par le socket du vrai service. Chaque effet est vérifié sur le stockage lui-même.
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
RESULTS = Path('/home/ubuntu/native-auto-results.json')
POLICY = Path('/etc/nacre-storage/policy.json')


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


def inventory():
    """Objets natifs « nacre_… » réellement présents sur le stockage du banc, par volume."""
    lvs = run('lvs', '--noheadings', '-o', 'lv_name,origin', 'nacre_test').splitlines()
    return {'btrfs': sorted(os.listdir('/srv/nacre-lab/btrfs/snapshots')),
            'zfs': sorted(line.split('@')[1] for line in run('zfs', 'list', '-H', '-t', 'snapshot', '-o', 'name', 'nacre_lab/data').splitlines() if '@' in line),
            'classic': sorted(line.split()[0] for line in lvs if line.split()[1:] == ['classic']),
            'thin': sorted(line.split()[0] for line in lvs if line.split()[1:] == ['thin'])}


def console(phase, root=None):
    """Côté console, sous le compte non privilégié. Rend ce qu'elle croit présent : le banc le confronte au stockage."""
    assert os.geteuid() == 1000
    root = Path(root or tempfile.mkdtemp(prefix='nacre-auto-'))
    import server
    server.ROOT, server.STATE = root, root / 'state/console'
    server.DB = server.STATE / 'console.db'
    server.initialize()
    import native_auto
    import native_retention
    import native_schedule

    def occurrence(*volumes):
        for volume in volumes:
            native_schedule.write(server, volume, {**native_schedule.read(server, volume), 'next_run': time.time() - 1})
        return dict(native_schedule.tick(server))

    def scheduled(volume):
        """Points programmés que le service dit présents, du plus ancien au plus récent."""
        marks = set(native_schedule.marked(server, volume))
        points = [point for point in server.native_storage('status', 'admin')['points'] if point['volume'] == volume and point['id'] in marks]
        assert all(point['status'] == 'ready' and point['actor'] == 'programmation' for point in points), points
        return [point['id'] for point in sorted(points, key=lambda point: point['created'])]

    def enable(volume, cap=5):
        return native_auto.configure(server, {'volume': volume, 'enabled': True, 'cap': cap, 'confirmation': 'AUTOMATISER ' + volume}, 'admin')

    def refused(call):
        try:
            call()
        except server.Problem as problem:
            return problem.message
        raise AssertionError('Demande acceptée à tort')

    out = {'root': str(root)}
    if phase == 'withdrawn':
        # L'accord de suppression vient d'être retiré de la politique : la capture a lieu, la conservation se suspend.
        before = scheduled('classic')
        assert occurrence('classic') == {'classic': 'done'}
        state = native_auto.read(server, 'classic')
        assert not state['enabled'] and state['reason'] == 'Le service natif n’accorde plus la suppression de points.', state
        assert len(scheduled('classic')) == len(before) + 1 and set(before) <= set(scheduled('classic'))
        assert [key for key, *_ in native_auto.conditions(server)].count('native-auto:classic') == 1
        out.update(present={volume: scheduled(volume) for volume in VOLUMES}, withdrawn=state['reason'])
        print(json.dumps(out))
        return
    status = server.native_storage('status', 'admin')
    assert status['connected'] and status['deletion'] is True and all(volume['ready'] for volume in status['volumes'] if volume['id'] in VOLUMES), status['volumes']
    manual = {volume: [point['id'] for point in status['points'] if point['volume'] == volume] for volume in VOLUMES}
    assert all(len(manual[volume]) == 1 for volume in VOLUMES), manual
    # Activation : règle enregistrée, maximum et phrase exigés.
    out['refused_without_rule'] = refused(lambda: enable('btrfs'))
    for volume in VOLUMES:
        native_schedule.configure(server, {'volume': volume, 'enabled': True, 'cap': 10, 'confirmation': 'PROGRAMMER ' + volume}, 'admin')
        native_retention.save(server, {'volume': volume, 'keep_last': 2}, 'admin')
    out['refused_without_phrase'] = refused(lambda: native_auto.configure(server, {'volume': 'btrfs', 'enabled': True, 'cap': 5, 'confirmation': 'AUTOMATISER'}, 'admin'))
    assert occurrence(*VOLUMES) == dict.fromkeys(VOLUMES, 'done')   # avant activation : aucune suppression
    first = {volume: scheduled(volume)[0] for volume in VOLUMES}
    for volume in VOLUMES:
        assert enable(volume)['enabled']
    # Quatre familles, trois captures de plus : la règle « 2 derniers » retire le plus ancien point programmé après chacune des deux dernières.
    history = {volume: [first[volume]] for volume in VOLUMES}
    for expected in (2, 2, 2):
        assert occurrence(*VOLUMES) == dict.fromkeys(VOLUMES, 'done')
        for volume in VOLUMES:
            present = scheduled(volume)
            history[volume] += [point for point in present if point not in history[volume]]
            assert len(present) == expected and present == history[volume][-2:], (volume, present, history[volume])
            last = native_auto.read(server, volume)['last']
            assert last['outcome'] in ('done', 'nothing') and native_auto.read(server, volume)['enabled'], last
    assert all(len(history[volume]) == 4 and native_auto.read(server, volume)['last']['deleted'] == 1 for volume in VOLUMES), history
    assert all(manual[volume][0] not in history[volume] for volume in VOLUMES)
    out['deleted_after_captures'] = {volume: history[volume][:2] for volume in VOLUMES}
    # Une programmation au plafond : pas de capture, mais le passage automatique libère la place pour la suivante.
    native_schedule.configure(server, {'volume': 'btrfs', 'enabled': True, 'cap': 2, 'confirmation': 'PROGRAMMER btrfs'}, 'admin')
    assert native_retention.save(server, {'volume': 'btrfs', 'keep_last': 1}, 'admin')['auto_stopped'] is True and not native_auto.read(server, 'btrfs')['enabled']
    enable('btrfs')
    assert occurrence('btrfs') == {'btrfs': 'capped'} and scheduled('btrfs') == history['btrfs'][-1:]
    assert occurrence('btrfs') == {'btrfs': 'done'} and len(scheduled('btrfs')) == 1 and scheduled('btrfs')[0] not in history['btrfs']
    out['capped_then_freed'] = True
    # Plus de points sortants que le maximum : rien n'est supprimé, la conservation se suspend et l'alerte se lève.
    native_auto.configure(server, {'volume': 'zfs', 'enabled': False}, 'admin')
    for _ in range(2):
        assert occurrence('zfs') == {'zfs': 'done'}
    assert enable('zfs', cap=1)['pending'] == 2
    assert occurrence('zfs') == {'zfs': 'done'}
    state = native_auto.read(server, 'zfs')
    assert not state['enabled'] and state['reason'].startswith('3 points sortiraient, plus que le maximum de 1 par passage'), state
    assert len(scheduled('zfs')) == 5 and ('native-auto:zfs', 'Conservation automatique suspendue') in [(key, title) for key, title, *_ in native_auto.conditions(server)]
    out['suspended_over_maximum'] = state['reason']
    with server.database() as db:
        journal = [row['action'] for row in db.execute("SELECT action FROM audit WHERE username='programmation' AND action LIKE 'Conservation automatique%' ORDER BY rowid")]
    assert journal.count('Conservation automatique appliquée') == 4 * 2 + 2 and journal.count('Conservation automatique suspendue') == 1, journal
    out.update(present={volume: scheduled(volume) for volume in VOLUMES}, manual=manual, journal=len(journal))
    print(json.dumps(out))


def main():
    for device, target in (('/dev/vdb', '/srv/nacre-lab/btrfs'), ('/dev/nacre_test/classic', '/srv/nacre-lab/classic')):
        if subprocess.run(['findmnt', '-n', target], capture_output=True).returncode:
            run('mount', device, target)
    from install_native import stage
    stage('/', 1000)
    policy = json.loads(POLICY.read_text())
    POLICY.write_text(json.dumps({**policy, 'deletion': True}))
    run('systemctl', 'daemon-reload')
    run('systemctl', 'restart', 'nacre-storage.service')
    for _ in range(50):
        if Path('/run/nacre-storage/control.sock').exists():
            break
        time.sleep(.1)
    witnesses = ('/srv/nacre-lab/btrfs/data/version.txt', '/srv/nacre-lab/classic/version.txt', '/srv/nacre-lab/zfs/version.txt')
    before = inventory()
    assert all(len(before[volume]) == 1 for volume in VOLUMES), before

    def phase(*arguments):
        return json.loads(run('runuser', '-u', 'ubuntu', '--', 'env', 'NACRE_VM_LAB=1', 'python3', str(Path(__file__).resolve()), 'console', *arguments).splitlines()[-1])

    def confront(report):
        """Sur le stockage : le point manuel d'origine et les points programmés que la console dit présents, rien d'autre, en lecture seule."""
        found = inventory()
        for volume in VOLUMES:
            assert found[volume] == sorted(before[volume] + ['nacre_' + point for point in report['present'][volume]]), (volume, found[volume], report['present'][volume])
        for name in found['btrfs']:
            assert run('btrfs', 'property', 'get', '-ts', '/srv/nacre-lab/btrfs/snapshots/' + name, 'ro') == 'ro=true'
        for volume in ('classic', 'thin'):
            assert all(run('lvs', '--noheadings', '-o', 'lv_attr', 'nacre_test/' + name).strip()[1] == 'r' for name in found[volume])
        return found

    first = phase('nominal')
    found = confront(first)
    for volume in VOLUMES:
        assert all('nacre_' + point not in found[volume] for point in first['deleted_after_captures'][volume])
        assert before[volume] == ['nacre_' + first['manual'][volume][0]]
    assert {volume: len(first['present'][volume]) for volume in VOLUMES} == {'btrfs': 1, 'zfs': 5, 'classic': 2, 'thin': 2}, first['present']
    # Accord retiré par root : plus aucune suppression, même activée.
    POLICY.write_text(json.dumps(policy))
    second = phase('withdrawn', first['root'])
    found = confront(second)
    assert len(second['present']['classic']) == 3
    assert all(Path(path).read_text() == 'version 2\n' for path in witnesses) and run('systemctl', 'is-active', 'nacre-storage.service') == 'active'
    result = {'verified': list(VOLUMES), 'deleted_after_captures': {volume: len(first['deleted_after_captures'][volume]) for volume in VOLUMES}, 'manual_points_intact': True,
              'capped_then_freed': first['capped_then_freed'], 'suspended_over_maximum': first['suspended_over_maximum'], 'suspended_without_grant': second['withdrawn'],
              'refused_without_rule': first['refused_without_rule'], 'refused_without_phrase': first['refused_without_phrase'], 'data_intact': True,
              'points_on_storage': {volume: len(found[volume]) for volume in VOLUMES}}
    RESULTS.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    guard()
    console(*sys.argv[2:]) if sys.argv[1:2] == ['console'] else main()
