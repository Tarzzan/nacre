import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'console'))
import native_storage as native
import native_service as service


class NativeDeleteTests(unittest.TestCase):
    """Service natif face à un stockage simulé : LVM classique « documents » et dataset ZFS « archives »."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.policy = {'version': 1, 'allowed_uid': 1000, 'deletion': True, 'volumes': [
            {'id': 'documents', 'name': 'Documents', 'family': 'lvm', 'lv': 'data/documents',
             'vg_uuid': 'vg-original', 'lv_uuid': 'lv-original', 'segtype': 'linear', 'cow_bytes': 1024**3},
            {'id': 'archives', 'name': 'Archives', 'family': 'zfs', 'dataset': 'pool/archives', 'guid': '77', 'restore_parent': 'pool/restores', 'restore_parent_guid': '88'}]}
        self.copies, self.mounted, self.parent = set(), 'no', '88'       # copies ZFS présentes sous le parent de restauration
        self.calls = []
        self.lvm, self.zfs = {}, {}        # nom → identité, tels que le stockage les porte
        self.open, self.clones = set(), set()
        self.refuse = self.silent = self.blind = False
        self.serial = 0
        patches = [patch.object(native, 'read_policy', side_effect=lambda _: copy.deepcopy(self.policy)),
                   patch.object(native, 'private_directory'), patch('provisioning.private_directory'),
                   patch.object(service, 'print', create=True)]  # le journal root du service n'a rien à faire dans la sortie des essais
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temp.cleanup)
        self.engine = self.start()
        self.addCleanup(lambda: self.engine.db.close())

    def start(self):
        return service.Engine(Path(self.temp.name) / 'policy.json', self.temp.name, self.run_command)

    def run_command(self, args, pass_fds=()):
        self.calls.append(args)
        tool, last = args[0], args[-1]
        if tool == 'lsblk':
            return json.dumps({'blockdevices': [{'mountpoints': []}]})
        if tool == 'vgs':
            return json.dumps({'report': [{'vg': [{'vg_free': str(10 * 1024**3)}]}]})
        if tool == 'lvcreate':
            self.serial += 1
            self.lvm[args[args.index('--name') + 1]] = 'lv-point-%d' % self.serial
            return ''
        if tool == 'lvremove':
            if self.refuse:
                raise native.NativeError('refus')
            if not self.silent:
                self.lvm.pop(last.split('/')[1])
            return ''
        if tool == 'lvs':
            if self.blind:
                raise native.NativeError('stockage muet')
            if last == 'data':
                return json.dumps({'report': [{'lv': [{'lv_name': name} for name in ['documents', *self.lvm]]}]})
            name = last.split('/')[1]
            if name.startswith('nacre_'):
                if name not in self.lvm:
                    raise native.NativeError('absent')
                return json.dumps({'report': [{'lv': [{'lv_uuid': self.lvm[name], 'lv_attr': 'sri-ao----' if name in self.open else 'sri-a-s---',
                                                        'origin': 'documents', 'data_percent': '0'}]}]})
            return json.dumps({'report': [{'lv': [{'vg_uuid': 'vg-original', 'lv_uuid': 'lv-original', 'lv_attr': 'owi-aos---', 'segtype': 'linear', 'pool_lv': ''}]}]})
        if tool == 'zfs':
            if args[1] == 'snapshot':
                self.serial += 1
                self.zfs[last.split('@')[1]] = str(9000 + self.serial)
                return ''
            if args[1] == 'destroy':
                assert not {'-r', '-R', '-f'} & set(args), args
                name = last.split('@')[1]
                if name in self.clones:
                    raise native.NativeError('clone dépendant')
                self.zfs.pop(name)
                return ''
            if args[1] == 'list':
                if 'snapshot' not in args:
                    return 'pool/restores\n' + ''.join('pool/restores/%s\n' % name for name in self.copies)
                return ''.join('pool/archives@%s\n' % name for name in self.zfs)
            if last == 'pool/restores':
                return self.parent + '\n'
            if 'mounted' in args:
                return self.mounted + '\n'
            if 'guid,type,mountpoint,readonly' in args:
                return 'guid\t77\ntype\tfilesystem\nmountpoint\t/srv/archives\nreadonly\toff\n'
            name = last.split('@')[1]
            if name not in self.zfs:
                raise native.NativeError('absent')
            if 'clones,userrefs' in args:
                return 'clones\t%s\nuserrefs\t0\n' % ('pool/restores/copie' if name in self.clones else '')
            return self.zfs[name] + '\n'
        raise AssertionError(args)

    def ask(self, method, body, actor='admin'):
        return self.engine.request(1000, {'method': method, 'actor': actor, 'body': body})

    def capture(self, volume='documents', count=3):
        made = []
        for _ in range(count):
            plan = self.ask('prepare', {'action': 'snapshot', 'volume': volume})
            self.ask('commit', {'plan': plan['id'], 'confirmation': plan['confirmation']})
            made.append(plan['id'])
        return made

    def plan(self, points, volume='documents'):
        return self.ask('prepare', {'action': 'delete', 'volume': volume, 'points': points})

    def commit(self, plan, actor='admin', confirmation=None):
        return self.ask('commit', {'plan': plan['id'], 'confirmation': confirmation or plan['confirmation']}, actor)

    def removed(self):
        return [args[-1] for args in self.calls if args[0] in ('lvremove',) or args[:2] == ['zfs', 'destroy']]

    def catalog(self):
        return {row['id']: row['status'] for row in self.engine.db.execute('SELECT id,status FROM points')}

    def journal(self):
        return [row['status'] for row in self.engine.db.execute("SELECT status FROM actions WHERE action='delete' ORDER BY ts")]

    def test_policy_must_allow_deletion(self):
        points = self.capture()
        self.policy['deletion'] = 'oui'
        with self.assertRaises(native.NativeError):
            self.engine.status()
        self.policy['deletion'] = False
        self.assertFalse(self.engine.status()['deletion'])
        with self.assertRaises(native.NativeError):
            self.plan(points[:1])
        self.policy['deletion'] = True
        plan = self.plan(points[:1])
        del self.policy['deletion']
        with self.assertRaises(native.NativeError):
            self.commit(plan)
        self.assertEqual(self.removed(), [])
        self.assertEqual(len(self.lvm), 3)

    def test_exact_list_is_deleted_once_and_nothing_else(self):
        points = self.capture()
        plan = self.plan(points[:2])
        self.assertEqual(plan['confirmation'], 'SUPPRIMER 2 POINTS DE documents')
        self.assertEqual([item['id'] for item in plan['points']], points[:2])
        with self.assertRaises(native.NativeError):
            self.commit(plan, actor='autre')
        with self.assertRaises(native.NativeError):
            self.commit(plan, confirmation='SUPPRIMER 3 POINTS DE documents')
        self.assertEqual(self.removed(), [])
        result = self.commit(plan)
        self.assertEqual(result, {'ok': True, 'deleted': points[:2], 'uncertain': [], 'kept': [], 'reason': ''})
        self.assertEqual(self.removed(), ['data/nacre_' + points[0], 'data/nacre_' + points[1]])
        self.assertEqual(list(self.lvm), ['nacre_' + points[2]])
        self.assertEqual(self.catalog(), {points[2]: 'ready'})
        self.assertEqual(self.journal(), ['done', 'done'])
        with self.assertRaises(native.NativeError):
            self.commit(plan)
        self.assertEqual(len(self.removed()), 2)
        self.assertEqual(self.plan(points[2:])['confirmation'], 'SUPPRIMER 1 POINT DE documents')

    def test_one_refused_point_refuses_the_whole_plan(self):
        points = self.capture()
        other = self.capture('archives', 1)
        for wanted in ([], points + points[:1], ['x' * 32], [points[0], 'f' * 32], [points[0], other[0]], 'tout', [points[0]] * 2, ['f' * 32] * 51):
            with self.assertRaises(native.NativeError, msg=wanted):
                self.plan(wanted)
        self.engine.db.execute("UPDATE points SET status='uncertain' WHERE id=?", (points[1],))
        self.engine.db.commit()
        with self.assertRaises(native.NativeError):
            self.plan(points[:2])
        self.assertEqual(self.removed(), [])

    def test_changes_after_the_plan_refuse_without_deleting(self):
        points = self.capture()
        plan = self.plan(points)
        self.lvm['nacre_' + points[2]] = 'lv-remplace'          # même nom, autre objet
        with self.assertRaises(native.NativeError):
            self.commit(plan)
        self.lvm['nacre_' + points[2]] = 'lv-point-3'
        plan = self.plan(points)
        self.policy['volumes'][0]['cow_bytes'] += 1
        with self.assertRaises(native.NativeError):
            self.commit(plan)
        plan = self.plan(points)
        self.engine.db.execute('UPDATE plans SET expires=0')
        self.engine.db.commit()
        with self.assertRaises(native.NativeError):
            self.commit(plan)
        plan = self.plan(points)
        self.open.add('nacre_' + points[1])                     # ouvert entre-temps
        with self.assertRaises(native.NativeError):
            self.commit(plan)
        self.assertEqual(self.removed(), [])
        self.assertEqual(self.catalog(), dict.fromkeys(points, 'ready'))

    def test_point_read_by_a_restoration_or_cloned_is_protected(self):
        points = self.capture()
        for status in ('queued', 'running', 'uncertain'):
            self.engine.db.execute("INSERT OR REPLACE INTO actions(id,ts,actor,action,volume,object,status) VALUES('r',1,'admin','clone','documents','restore_x',?)", (status,))
            self.engine.db.commit()
            with self.assertRaises(native.NativeError):
                self.plan(points[:1])
        self.engine.db.execute("UPDATE actions SET status='done' WHERE id='r'")
        self.engine.db.commit()
        self.open.add('nacre_' + points[0])
        with self.assertRaises(native.NativeError):
            self.plan(points[:1])
        archives = self.capture('archives', 2)
        self.clones.add('nacre_' + archives[0])
        with self.assertRaises(native.NativeError):
            self.plan(archives, 'archives')
        result = self.commit(self.plan(archives[1:], 'archives'))
        self.assertEqual(result['deleted'], archives[1:])
        self.assertEqual(list(self.zfs), ['nacre_' + archives[0]])
        self.assertEqual(self.removed(), ['pool/archives@nacre_' + archives[1]])

    def test_refused_command_stops_and_leaves_the_rest_intact(self):
        points = self.capture()
        plan = self.plan(points)
        self.refuse = True
        result = self.commit(plan)
        self.assertEqual((result['ok'], result['deleted'], result['uncertain'], result['kept']), (False, [], [], points))
        self.assertEqual(self.catalog(), dict.fromkeys(points, 'ready'))
        self.assertEqual(self.journal(), ['failed'])
        self.assertEqual(len(self.removed()), 1)
        with self.assertRaises(native.NativeError):
            self.commit(plan)

    def test_unconfirmed_deletion_is_uncertain_then_settled_from_real_state(self):
        points = self.capture()
        plan = self.plan(points)
        real = self.run_command

        def muted(args, pass_fds=()):
            # La commande de suppression aboutit, puis le stockage ne répond plus : rien ne prouve l'absence.
            out = real(args, pass_fds)
            if args[0] == 'lvremove':
                self.blind = True
            return out
        self.engine.run = muted
        result = self.commit(plan)
        self.assertEqual((result['ok'], result['deleted'], result['uncertain'], result['kept']), (False, [], points[:1], points[1:]))
        self.assertEqual(self.catalog(), {points[0]: 'uncertain', points[1]: 'ready', points[2]: 'ready'})
        self.assertEqual(self.journal(), ['uncertain'])
        with self.assertRaises(native.NativeError):
            self.plan(points[:1])                                # un point à vérifier n'entre dans aucun plan
        self.blind = False
        status = self.engine.status()
        self.assertEqual(sorted(point['id'] for point in status['points']), sorted(points[1:]))
        self.assertEqual(self.journal(), ['done'])
        self.assertEqual(len(self.removed()), 1)                  # rien n'a été rejoué

    def test_interrupted_service_marks_uncertain_and_never_replays(self):
        points = self.capture()
        for index, survives in ((0, True), (1, False)):
            self.engine.db.execute("UPDATE points SET status='deleting' WHERE id=?", (points[index],))
            self.engine.db.execute("INSERT INTO actions(id,ts,actor,action,volume,object,status) VALUES(?,?,?,?,?,?,?)",
                                   ('a%d' % index, time.time(), 'admin', 'delete', 'documents', 'nacre_' + points[index], 'running'))
            if not survives:
                self.lvm.pop('nacre_' + points[index])
        self.engine.db.commit()
        self.engine.db.close()
        self.engine = self.start()
        self.assertEqual(self.catalog(), {points[0]: 'uncertain', points[1]: 'uncertain', points[2]: 'ready'})
        self.assertEqual(sorted(self.journal()), ['uncertain', 'uncertain'])
        self.blind = True
        self.assertEqual({point['id']: point['status'] for point in self.engine.status()['points']}[points[0]], 'uncertain')
        self.blind = False
        status = {point['id']: point['status'] for point in self.engine.status()['points']}
        self.assertEqual(status, {points[0]: 'ready', points[2]: 'ready'})
        self.assertEqual(sorted(self.journal()), ['done', 'failed'])
        self.assertEqual(self.removed(), [])

    def test_time_budget_leaves_remaining_points_untouched(self):
        points = self.capture()
        plan = self.plan(points)
        clock = iter([0, 1, 100, 200, 300])
        with patch.object(native.time, 'monotonic', side_effect=lambda: next(clock)):
            result = self.commit(plan)
        self.assertEqual((result['ok'], result['deleted'], result['kept']), (False, points[:1], points[1:]))
        self.assertEqual(self.catalog(), {points[1]: 'ready', points[2]: 'ready'})


    def test_installed_service_starts_the_extended_engine_and_leaves_the_frozen_module_alone(self):
        from install_native import stage
        files = stage(Path(self.temp.name) / 'racine', 1000)
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/lib/nacre-storage/native_service.py\n', files['etc/systemd/system/nacre-storage.service'])
        for name in ('native_service.py', 'native_storage.py'):
            self.assertEqual(files['usr/local/lib/nacre-storage/' + name], (SOURCE / 'console' / name).read_text())
        self.assertNotIn('deletion', json.loads(files['etc/nacre-storage/policy.json']))
        self.assertTrue(issubclass(service.Engine, native.Engine))
        self.assertNotIn('delete', (SOURCE / 'console/native_storage.py').read_text().split('def request')[1].split('class NativeClient')[0])


    def test_an_uncertain_restoration_is_settled_from_real_state_and_stops_blocking_deletion(self):
        points = self.capture('archives', 2)
        copy = 'restore_' + 'c' * 32

        def restoration(identifier, volume='archives', name=copy, age=3600, status='uncertain'):
            self.engine.db.execute("INSERT OR REPLACE INTO actions(id,ts,actor,action,volume,object,status) VALUES(?,?,?,?,?,?,?)", (identifier, time.time() - age, 'admin', 'clone', volume, name, status))
            self.engine.db.commit()

        def state(identifier):
            return tuple(self.engine.db.execute('SELECT status,location FROM actions WHERE id=?', (identifier,)).fetchone())
        # Trop récente, parent de restauration changé, copie encore montée, nom non géré : elle reste « à vérifier », et protège le volume.
        restoration('r1', age=30)
        self.engine.status(); self.assertEqual(state('r1'), ('uncertain', ''))
        restoration('r1'); self.parent = '99'
        self.engine.status(); self.assertEqual(state('r1'), ('uncertain', ''))
        self.parent = '88'; self.copies.add(copy); self.mounted = 'yes'
        self.engine.status(); self.assertEqual(state('r1'), ('uncertain', ''))
        restoration('r2', name='restore_x')
        with self.assertRaises(native.NativeError):
            self.plan(points[:1], 'archives')
        # Copie présente et non montée : terminée, avec sa destination. Copie absente : échouée. Rien n'est créé ni supprimé.
        self.mounted = 'no'; before = len(self.calls)
        self.engine.status()
        self.assertEqual(state('r1'), ('done', 'pool/restores/' + copy))
        self.assertFalse([call for call in self.calls[before:] if call[:2] in (['zfs', 'clone'], ['zfs', 'destroy'], ['zfs', 'snapshot'])])
        self.copies.clear(); restoration('r1')
        self.engine.status(); self.assertEqual(state('r1'), ('failed', ''))
        self.assertEqual(state('r2'), ('uncertain', ''))
        self.engine.db.execute("DELETE FROM actions WHERE id='r2'"); self.engine.db.commit()
        self.assertEqual(self.commit(self.plan(points[:1], 'archives'))['deleted'], points[:1])      # la suppression n'est plus bloquée
        # Copie LVM : processus disparu, la tâche est close en échec ; encore en cours, on n'y touche pas.
        lvm = self.capture('documents', 1)
        for identifier, pid, status, age in (('d' * 32, 2**22 + 1, 'uncertain', 3600), ('e' * 32, 2**22 + 2, 'running', 5)):
            self.engine.db.execute('INSERT INTO native_jobs(id,actor,ts,status,options,pid) VALUES(?,?,?,?,?,?)', (identifier, 'admin', time.time() - age, status, '{}', pid))
            restoration(identifier, 'documents', 'restore_' + identifier, age, status)
        with self.assertRaises(native.NativeError):
            self.plan(lvm, 'documents')
        self.engine.status()
        self.assertEqual((state('d' * 32)[0], state('e' * 32)[0]), ('failed', 'running'))
        job = self.engine.db.execute('SELECT status,error FROM native_jobs WHERE id=?', ('d' * 32,)).fetchone()
        self.assertEqual((job['status'], 'dossier partiel reste privé' in job['error']), ('failed', True))
        self.engine.db.execute("DELETE FROM actions WHERE id=?", ('e' * 32,)); self.engine.db.execute("DELETE FROM native_jobs WHERE id=?", ('e' * 32,)); self.engine.db.commit()
        self.assertEqual(self.commit(self.plan(lvm, 'documents'))['deleted'], lvm)


if __name__ == '__main__':
    unittest.main()
