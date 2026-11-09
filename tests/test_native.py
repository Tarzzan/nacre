import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from contextlib import nullcontext
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'console'))
import native_storage as native
from install_native import stage
from provisioning import reject_used


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.policy = {'version': 1, 'allowed_uid': 1000, 'volumes': [
            {'id': 'documents', 'name': 'Documents', 'family': 'lvm', 'lv': 'data/documents',
             'vg_uuid': 'vg-original', 'lv_uuid': 'lv-original', 'segtype': 'linear', 'cow_bytes': 1024**3}]}
        self.calls = []
        self.bad_identity = False
        self.fail_create = False
        self.attr = '-wi-a-----'
        self.system_mount=False
        self.read = patch.object(native, 'read_policy', side_effect=lambda _: copy.deepcopy(self.policy))
        self.private = patch.object(native, 'private_directory')
        self.provision_private=patch('provisioning.private_directory')
        self.read.start(); self.private.start(); self.provision_private.start()
        self.engine = native.Engine(Path(self.temp.name) / 'policy.json', self.temp.name, self.run_command)

    def tearDown(self):
        self.engine.db.close()
        self.read.stop(); self.private.stop(); self.provision_private.stop(); self.temp.cleanup()

    def run_command(self, args, pass_fds=()):
        self.calls.append(args)
        if args[0]=='lsblk':return json.dumps({'blockdevices':[{'mountpoints':['/'] if self.system_mount else []}]})
        if args[0] == 'lvcreate':
            if self.fail_create:
                raise native.NativeError('Interruption du stockage')
            return ''
        if args[0] == 'vgs':
            return json.dumps({'report': [{'vg': [{'vg_free': str(10 * 1024**3)}]}]})
        if args[0] == 'lvs':
            if 'nacre_' in args[-1]:
                return json.dumps({'report': [{'lv': [{'lv_uuid': 'snapshot-original', 'lv_attr': 'sri-a-s---', 'origin': 'documents', 'data_percent': '0'}]}]})
            if args[-1] == 'data/pool':
                return json.dumps({'report': [{'lv': [{'lv_attr': 'twi-aotz--', 'data_percent': '1', 'metadata_percent': '2'}]}]})
            return json.dumps({'report': [{'lv': [{'vg_uuid': 'vg-original', 'lv_uuid': 'changed' if self.bad_identity else 'lv-original',
                'lv_attr': self.attr, 'segtype': self.policy['volumes'][0]['segtype'], 'pool_lv': 'pool'}]}]})
        raise AssertionError(args)

    def prepare(self):
        return self.engine.request(1000, {'method': 'prepare', 'actor': 'admin', 'body': {'action': 'snapshot', 'volume': 'documents'}})

    def commit(self, plan, actor='admin'):
        return self.engine.request(1000, {'method': 'commit', 'actor': actor, 'body': {'plan': plan['id'], 'confirmation': plan['confirmation']}})

    def test_snapshot_plan_bound_to_actor_uid_confirmation_and_single_execution(self):
        plan = self.prepare()
        with self.assertRaises(native.NativeError): self.commit(plan, 'autre')
        with self.assertRaises(native.NativeError): self.engine.request(1001, {'method': 'status', 'actor': 'admin'})
        with self.assertRaises(native.NativeError): self.commit({**plan, 'confirmation': 'oui'})
        self.commit(plan)
        self.assertEqual(len([a for a in self.calls if a[0] == 'lvcreate']), 1)
        with self.assertRaises(native.NativeError): self.commit(plan)

    def test_expired_policy_and_identity_changes_refuse_without_mutation(self):
        plan = self.prepare()
        self.engine.db.execute('UPDATE plans SET expires=0')
        self.engine.db.commit()
        with self.assertRaises(native.NativeError): self.commit(plan)
        plan = self.prepare()
        self.policy['volumes'][0]['cow_bytes'] += 1
        with self.assertRaises(native.NativeError): self.commit(plan)
        plan = self.prepare()
        self.bad_identity = True
        with self.assertRaises(native.NativeError): self.commit(plan)
        self.assertFalse(any(a[0] == 'lvcreate' for a in self.calls))

    def test_classic_cow_and_thin_use_distinct_constructors(self):
        self.commit(self.prepare())
        command = next(a for a in self.calls if a[0] == 'lvcreate')
        self.assertEqual(command[command.index('--size') + 1], '1073741824b')
        self.assertNotIn('--activate', command)
        self.policy['volumes'][0]['segtype'] = 'thin'
        self.attr = 'Vwi-a-tz--'
        self.calls.clear()
        self.commit(self.prepare())
        command = next(a for a in self.calls if a[0] == 'lvcreate')
        self.assertNotIn('--size', command)
        self.assertIn('r', command)

    def test_failure_is_uncertain_and_cannot_be_replayed(self):
        plan = self.prepare(); self.fail_create = True
        with self.assertRaises(native.NativeError): self.commit(plan)
        row = self.engine.db.execute('SELECT status FROM points').fetchone()
        self.assertEqual(row['status'], 'uncertain')
        with self.assertRaises(native.NativeError): self.commit(plan)

    def test_user_writable_parent_cannot_be_a_privileged_storage_anchor(self):
        with self.assertRaises(native.NativeError):
            with native.trusted_directory(self.temp.name):
                self.fail('Un parent /tmp inscriptible par tous ne doit pas être approuvé')

    def test_existing_classic_origin_can_create_another_snapshot(self):
        self.attr = 'owi-aos---'
        self.commit(self.prepare())
        self.assertEqual(self.engine.db.execute('SELECT status FROM points').fetchone()['status'],'ready')

    def test_lvm_system_volume_refused_even_if_mistakenly_enrolled(self):
        self.system_mount=True
        with self.assertRaises(native.NativeError):self.prepare()
        self.assertFalse(any(a[0]=='lvcreate' for a in self.calls))

    def provision(self):
        self.policy['provisioning']={'enabled':True,'root':'/srv/nacre-test','devices':[
            {'id':'disk-a','path':'/dev/disk/by-id/aaa','serial':'AAA','bytes':10**12,'initialize':True},
            {'id':'disk-b','path':'/dev/disk/by-id/bbb','serial':'BBB','bytes':10**12,'initialize':True}]}
        manager=self.engine.provisioning()
        def probe(spec,blank=True):
            return {'id':spec['id'],'path':'/dev/'+spec['id'],'serial':spec['serial'],'bytes':spec['bytes'],'device':'8:'+('0' if spec['id']=='disk-a' else '16')}
        return manager,probe

    def test_system_mounted_partitioned_readonly_and_stacked_disks_refused(self):
        for node in ({'type':'disk','mountpoints':['/']},{'type':'disk','fstype':'LVM2_member'},
                     {'type':'disk','pttype':'gpt'},{'type':'disk','ro':True},
                     {'type':'disk','children':[{'type':'part'}]},{'type':'raid1'},{'type':'part'}):
            with self.assertRaises(native.NativeError):reject_used(node)
        reject_used({'type':'disk','mountpoints':[],'ro':False})

    def test_provision_policy_change_aliases_and_insufficient_capacity(self):
        manager,probe=self.provision()
        body={'action':'provision','profile':{'name':'NAS','layout':'mirror','filesystem':'btrfs','disk_bytes':[1,1]},'devices':['disk-a','disk-b']}
        with patch.object(type(manager),'probe',side_effect=probe):
            plan=self.engine.prepare(1000,'admin',body)
            self.policy['provisioning']['devices'][0]['serial']='REPLACED'
            with self.assertRaises(native.NativeError):self.commit(plan)
            body['profile']['disk_bytes']=[10**15,1]
            with self.assertRaises(native.NativeError):self.engine.prepare(1000,'admin',body)
            body['profile']['disk_bytes']=[1,1];body['devices']=['disk-a','disk-a']
            with self.assertRaises(native.NativeError):self.engine.prepare(1000,'admin',body)
        self.assertFalse(any(a[0].startswith('mkfs') or a[0]=='mdadm' for a in self.calls))

    def test_provision_failure_consumes_plan_and_never_reformats_on_retry(self):
        manager,probe=self.provision()
        body={'action':'provision','profile':{'name':'NAS','layout':'mirror','filesystem':'ext4','disk_bytes':[1,1]},'devices':['disk-a','disk-b']}
        with patch.object(type(manager),'probe',side_effect=probe),patch.object(type(manager),'pinned',return_value=nullcontext(())):
            plan=self.engine.prepare(1000,'admin',body)
            with patch.object(self.engine,'run',side_effect=native.NativeError('Erreur de périphérique')):
                with self.assertRaises(native.NativeError):self.commit(plan)
            self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()['phase'],'uncertain')
            with self.assertRaises(native.NativeError):self.commit(plan)

    def test_interrupted_initialization_is_uncertain_after_daemon_restart(self):
        self.engine.provisioning()
        self.engine.db.execute('INSERT INTO deployments VALUES(?,?,?,?,?,?)',('managed-fixture',time.time(),'admin','creating','{}',''))
        self.engine.db.commit();self.engine.db.close()
        self.engine=native.Engine(Path(self.temp.name)/'policy.json',self.temp.name,self.run_command)
        self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()['phase'],'uncertain')

    def test_restore_copy_preserves_bytes_sparse_size_symlink_without_following(self):
        root=Path(self.temp.name);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
        (source/'version.txt').write_text('contenu')
        (source/'lien').symlink_to('/etc/shadow')
        with (source/'sparse').open('wb') as file:file.truncate(1024**3+7)
        identifier='a'*32
        manager=self.engine.restorations()
        self.engine.db.execute('INSERT INTO native_jobs(id,actor,ts,status,options) VALUES(?,?,?,?,?)',(identifier,'admin',time.time(),'running','{}'));self.engine.db.commit()
        with patch.object(self.engine,'policy',return_value={**self.policy,'allowed_uid':os.getuid()}):
            manager.copy(identifier,source,target)
        self.assertEqual((target/'version.txt').read_text(),'contenu')
        self.assertEqual(os.readlink(target/'lien'),'/etc/shadow')
        self.assertEqual((target/'sparse').stat().st_size,1024**3+7)
        self.assertLess((target/'sparse').stat().st_blocks*512,1024**2)
        self.assertEqual(self.engine.db.execute('SELECT bytes FROM native_jobs WHERE id=?',(identifier,)).fetchone()['bytes'],1024**3+14)

    def test_restore_cancel_and_special_files_are_not_reported_complete(self):
        root=Path(self.temp.name);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
        identifier='b'*32;manager=self.engine.restorations()
        self.engine.db.execute('INSERT INTO native_jobs(id,actor,ts,status,options) VALUES(?,?,?,?,?)',(identifier,'admin',time.time(),'running','{}'));self.engine.db.commit()
        os.mkfifo(source/'special')
        with self.assertRaises(native.NativeError):manager.copy(identifier,source,target)
        (source/'special').unlink();manager.cancel(identifier)
        with self.assertRaises(InterruptedError):manager.copy(identifier,source,target)

    def test_restore_physical_capacity_guard_stops_without_overwriting_source(self):
        root=Path(self.temp.name);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
        (source/'original').write_bytes(b'contenu conserve')
        identifier='c'*32;manager=self.engine.restorations()
        self.engine.db.execute('INSERT INTO native_jobs(id,actor,ts,status,options) VALUES(?,?,?,?,?)',(identifier,'admin',time.time(),'running','{}'));self.engine.db.commit()
        with patch('native_restore.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaises(native.NativeError):manager.copy(identifier,source,target)
        self.assertEqual((source/'original').read_bytes(),b'contenu conserve')
        self.assertEqual((target/'original').stat().st_size,0)

    def test_arbitrary_command_volume_path_or_snapshot_id_is_rejected(self):
        for body in ({'action':'format','volume':'documents'}, {'action':'snapshot','volume':'/dev/sda'},
                     {'action':'clone','volume':'documents','point':'../../etc/passwd'}):
            with self.assertRaises(native.NativeError):
                self.engine.request(1000, {'method':'prepare','actor':'admin','body':body})
        with self.assertRaises(native.NativeError):
            self.engine.request(1000, {'method':'exec','actor':'admin','body':{'command':'id'}})
        self.assertFalse(any(a[0] == 'lvcreate' for a in self.calls))

    def test_installer_preserves_existing_policy_and_does_not_enable_service(self):
        target = Path(self.temp.name) / 'stage'
        stage(target, 1000)
        policy = target / 'etc/nacre-storage/policy.json'
        self.assertEqual(json.loads(policy.read_text())['volumes'], [])
        policy.write_text('existing policy')
        stage(target, 1001)
        self.assertEqual(policy.read_text(), 'existing policy')
        self.assertFalse((target / 'etc/systemd/system/multi-user.target.wants').exists())

    def test_missing_socket_reports_unconfigured_not_operational(self):
        result = native.NativeClient(str(Path(self.temp.name) / 'absent.sock')).status('admin')
        self.assertFalse(result['connected'])
        self.assertFalse(result['execution_enabled'])


if __name__ == '__main__':
    unittest.main()
