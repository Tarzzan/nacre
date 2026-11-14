from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'console'))
from protection import next_occurrence
from disks import normalize_inventory, normalize_smart
sys.path.insert(0,str(SOURCE))
from platform_config import profile, configure
from install_service import unit_text
spec = importlib.util.spec_from_file_location('nacre_protection_tests', SOURCE / 'console/server.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


class HardwareTests(unittest.TestCase):
    def test_architecture_profile_and_custom_user_identifiers(self):
        x86=profile('x86_64',5001,5002)
        arm=profile('aarch64',1024,100)
        self.assertNotEqual(x86['NACRE_FRIGATE_IMAGE'],arm['NACRE_FRIGATE_IMAGE'])
        self.assertEqual(x86['NACRE_UID'],'5001')
        self.assertEqual(arm['NACRE_GID'],'100')
        with self.assertRaises(RuntimeError):profile('unsupported-cpu',1000,1000)

    def test_existing_installation_options_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('NACRE_FRIGATE_IMAGE=image-personnalisee\nOTHER=value\n')
            configure(directory)
            self.assertIn('NACRE_FRIGATE_IMAGE=image-personnalisee',path.read_text())
            self.assertEqual(path.read_text().count('NACRE_FRIGATE_IMAGE='),1)
            self.assertIn('OTHER=value',path.read_text())

    def test_service_has_no_fixed_host_path(self):
        text=unit_text('/srv/Mon NAS')
        self.assertIn('/srv/Mon NAS/state/console/updates/runtime.py',text)
        self.assertNotIn('tarzzan',text)
        self.assertIn('NACRE_SYSTEMD_TASKS=1',text)

    def test_nvme_system_sata_usb_and_lvm(self):
        data={'blockdevices':[
            {'name':'nvme0n1','type':'disk','size':4000000,'tran':'nvme','children':[{'name':'nvme0n1p2','type':'part','size':3900000,'fstype':'ext4','mountpoints':['/']}]},
            {'name':'sda','type':'disk','size':8000000,'tran':'sata','rota':True,'children':[{'name':'sda1','type':'part','fstype':'btrfs','mountpoints':['/mnt/data']}]},
            {'name':'sdb','type':'disk','size':2000000,'tran':'usb','rm':True,'children':[{'name':'vault','type':'lvm','fstype':'xfs','mountpoints':['/mnt/vault']}]},
            {'name':'loop0','type':'loop','fstype':'squashfs','mountpoints':['/snap/example']},
        ]}
        disks,volumes=normalize_inventory(data)
        self.assertEqual(len(disks),3)
        self.assertTrue(disks[0]['system'])
        self.assertFalse(disks[1]['system'])
        self.assertTrue(disks[2]['removable'])
        self.assertEqual([v['native_snapshot_family'] for v in volumes],[None,'btrfs','lvm'])

    def test_smart_bitmask_and_permission_are_not_reported_as_healthy(self):
        healthy={'smartctl':{'exit_status':0},'smart_status':{'passed':True},'temperature':{'current':37}}
        self.assertEqual(normalize_smart(healthy,0)['state'],'ok')
        alert={'smartctl':{'exit_status':8},'smart_status':{'passed':False}}
        self.assertEqual(normalize_smart(alert,8)['state'],'warning')
        denied={'smartctl':{'exit_status':2,'messages':[{'string':'Permission denied'}]}}
        self.assertEqual(normalize_smart(denied,2)['state'],'permission_required')
        self.assertEqual(normalize_smart(None,None)['state'],'unavailable')


class CalendarTests(unittest.TestCase):
    def test_local_timezone_daily_and_weekly(self):
        now=datetime(2026,11,9,4,0,tzinfo=timezone.utc).timestamp()
        config={'time':'02:00','timezone':'America/Cayenne','weekdays':list(range(7))}
        self.assertEqual(next_occurrence(config,now),datetime(2026,11,9,5,0,tzinfo=timezone.utc).timestamp())
        config['weekdays']=[1]
        self.assertEqual(next_occurrence(config,now),datetime(2026,11,10,5,0,tzinfo=timezone.utc).timestamp())

    def test_nonexistent_dst_time_is_skipped(self):
        now=datetime(2026,3,28,23,0,tzinfo=timezone.utc).timestamp()
        value=next_occurrence({'time':'02:30','timezone':'Europe/Paris','weekdays':list(range(7))},now)
        self.assertEqual(value,datetime(2026,3,30,0,30,tzinfo=timezone.utc).timestamp())


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        app.ROOT=Path(self.temp.name)
        app.STATE=app.ROOT/'state/console'
        app.DB=app.STATE/'console.db'
        app.initialize()
        self.manager=app.protection()
        self.env=patch.dict(os.environ,{'NACRE_SYSTEMD_TASKS':'0'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def fake_repo(self):
        (app.ROOT/'repo').mkdir(exist_ok=True)
        identifier=secrets.token_hex(12)
        with app.database() as db:
            db.execute('INSERT INTO repositories(id,name,path,key_file,created,target) VALUES (?,?,?,?,?,?)',(identifier,'Test',str(app.ROOT/'repo'),str(app.STATE/'fake.key'),time.time(),'local'))
        return identifier

    def test_native_sources_remain_in_disabled_draft_and_cannot_be_arbitrary_paths(self):
        source='native_managed-'+'a'*20
        plan=self.manager.save_plan({'name':'Plan portable','sources':[source],'enabled':False},'admin')['id']
        self.assertEqual(next(p for p in self.manager.plans() if p['id']==plan)['config']['sources'],[source])
        repo=self.fake_repo()
        with self.assertRaises(app.Problem):self.manager.save_plan({'name':'Refus','sources':[source],'repo':repo,'enabled':True},'admin')
        for sources in (['/etc'],['native_restore-inconnu'],[],['../../etc']):
            with self.assertRaises(app.Problem):self.manager.validate_sources(sources)

    def test_source_mount_change_is_partial_even_when_restic_reports_success(self):
        repo=self.fake_repo()
        with patch.object(self.manager,'spawn'):
            job=self.manager.submit('snapshot','admin',{'repo':repo,'configuration':False,'video':False})
        def stream(*args):
            source=app.ROOT/'data/fichiers'
            source.rename(source.with_name('fichiers-ancien'));source.mkdir()
            return {'snapshot_id':'a'*64,'total_files_processed':1},0
        with patch.object(self.manager,'stream',side_effect=stream):self.manager.run_job(job)
        with app.database() as db:row=dict(db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())
        self.assertEqual(row['status'],'partial')
        self.assertIn('volume',json.loads(row['result'])['warning'])

    def wait(self,identifier,seconds=60):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            with app.database() as db:
                row=dict(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone())
            if row['status'] not in ('queued','running'):
                # Laisser le worker terminer son nettoyage privé après publication du résultat.
                if row.get('pid'):
                    for _ in range(30):
                        try:
                            state=Path(f'/proc/{row["pid"]}/stat').read_text().split(') ',1)[1][0]
                        except OSError:break
                        if state=='Z':break
                        time.sleep(.05)
                return row
            time.sleep(.1)
        self.fail('La tâche de test ne se termine pas.')

    def test_initialization_has_no_destination_or_active_plan(self):
        self.assertEqual(self.manager.repositories(),[])
        self.assertEqual(self.manager.plans(),[])
        self.assertEqual(self.manager.scheduler_tick(),[])
        self.assertIsNone(self.manager.capabilities()['backup_size_limit'])

    def test_draft_plan_can_be_designed_without_destination_but_not_enabled(self):
        body={'name':'Brouillon portable','repo':'','enabled':False,'time':'02:00','timezone':'UTC'}
        self.manager.save_plan(body,'test')
        self.assertIsNone(self.manager.plans()[0]['repo'])
        self.assertIsNone(self.manager.plans()[0]['next_run'])
        with self.assertRaises(app.Problem):self.manager.save_plan({**body,'enabled':True},'test')

    def test_scheduler_claims_once_and_disabled_plans_never_run(self):
        repo=self.fake_repo()
        plan=self.manager.save_plan({'name':'Plan test','repo':repo,'enabled':False,'time':'02:00','timezone':'UTC'},'admin')['id']
        with app.database() as db:
            db.execute('UPDATE plans SET next_run=? WHERE id=?',(time.time()-10,plan))
        with patch.object(self.manager,'spawn') as spawn:
            self.assertEqual(self.manager.scheduler_tick(),[])
            spawn.assert_not_called()
            with app.database() as db:
                db.execute('UPDATE plans SET enabled=1 WHERE id=?',(plan,))
            first=self.manager.scheduler_tick()
            self.assertEqual(len(first),1)
            self.assertEqual(self.manager.scheduler_tick(),[])
            spawn.assert_called_once()

    def test_cancelled_queued_task_does_not_capture_data(self):
        with patch.object(self.manager,'spawn'):
            job=self.manager.submit('backup','test')
        self.manager.cancel(job)
        self.manager.run_job(job)
        self.assertEqual(self.wait(job)['status'],'cancelled')
        self.assertFalse(list((app.ROOT/'data/sauvegardes').glob('*.tar.gz')))

    def test_exit_code_three_is_partial_even_if_snapshot_id_exists(self):
        script=app.ROOT/'fake-restic'
        script.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps({"message_type":"summary","snapshot_id":"a"*64}))\nraise SystemExit(3)\n')
        script.chmod(0o755)
        repo=self.fake_repo()
        with patch.dict(os.environ,{'NAS_RESTIC_BIN':str(script)}),patch.object(self.manager,'spawn'):
            job=self.manager.submit('snapshot','test',{'repo':repo,'configuration':False})
            self.manager.run_job(job)
        self.assertEqual(self.wait(job)['status'],'partial')

    def test_archive_larger_than_old_one_gib_limit_and_process_recovery(self):
        path=app.ROOT/'data/fichiers/grand-fichier.bin'
        length=1024**3+7
        with path.open('wb') as f:f.truncate(length)
        job=self.manager.submit('backup','test')
        self.manager.recover()
        row=self.wait(job,90)
        self.assertEqual(row['status'],'done',row['result'])
        result=json.loads(row['result'])
        self.assertEqual(result['bytes'],length)
        with tarfile.open(app.ROOT/'data/sauvegardes'/result['file']) as archive:
            self.assertEqual(archive.getmember('grand-fichier.bin').size,length)

    @unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Définir NAS_RESTIC_BIN pour le test de dépôt réel.')
    def test_real_encrypted_snapshots_restore_and_automatic_dispatch(self):
        repo=self.manager.create_repository({'name':'Dépôt de test','target':'local','password':'mot-de-passe-uniquement-de-test'},'test')['id']
        source=app.ROOT/'data/fichiers/version.txt';source.write_text('version une')
        config=app.ROOT/'state/frigate/config.yml';config.parent.mkdir(parents=True,exist_ok=True);config.write_text('{"camera":"configuration factice"}')
        first=self.manager.submit('snapshot','test',{'repo':repo,'configuration':True})
        row=self.wait(first)
        self.assertEqual(row['status'],'done',row['result'])
        snapshot=json.loads(row['result'])['snapshot']
        source.write_text('version deux')
        plan=self.manager.save_plan({'name':'Plan temporaire','repo':repo,'enabled':False,'time':'02:00','timezone':'UTC'},'test')['id']
        with app.database() as db:
            db.execute('UPDATE plans SET enabled=1,next_run=? WHERE id=?',(time.time()-1,plan))
        dispatched=self.manager.scheduler_tick()
        self.assertEqual(len(dispatched),1)
        self.assertEqual(self.wait(dispatched[0])['status'],'done')
        with app.database() as db:db.execute('UPDATE plans SET enabled=0 WHERE id=?',(plan,))
        self.assertEqual(len(self.manager.points(repo)),2)
        restored=self.manager.submit('snapshot_restore','test',{'repo':repo,'snapshot':snapshot})
        row=self.wait(restored)
        self.assertEqual(row['status'],'done',row['result'])
        destination=app.ROOT/'data/restaurations'/restored
        self.assertEqual((destination/'fichiers/version.txt').read_text(),'version une')
        self.assertEqual(source.read_text(),'version deux')
        self.assertTrue((destination/'configuration/console.db').is_file())
        self.assertEqual(os.stat(destination).st_mode & 0o777,0o700)

    def test_spaces_are_a_backup_source_restored_under_a_stable_name_without_their_trash(self):
        import spaces
        self.assertEqual([s['id'] for s in self.manager.sources()][:2],['fichiers','espaces'])
        self.assertEqual(self.manager.validate_sources(['fichiers','espaces']),['fichiers','espaces'])
        repo=self.manager.create_repository({'name':'Dépôt des espaces','target':'local','password':'mot-de-passe-uniquement-de-test'},'test')['id']
        # Aucun espace encore créé : la source existe quand même, vide.
        self.assertEqual(self.wait(self.manager.submit('snapshot','test',{'repo':repo,'sources':['espaces'],'configuration':False}))['status'],'done')
        with app.database() as db:
            spaces.put(db,'space:'+'c0'*6,{'id':'c0'*6,'kind':'team','name':'Chantier','members':{},'groups':{}})
        folder=Path(spaces.resource(app,'espace_'+'c0'*6)['path'])
        (app.ROOT/'data/fichiers/commun.txt').write_text('commun')
        (folder/'devis.txt').write_text('devis en cours');(folder/'.nacre-trash').mkdir();(folder/'.nacre-trash/jete.txt').write_text('corbeille')
        row=self.wait(self.manager.submit('snapshot','test',{'repo':repo,'sources':['fichiers','espaces'],'configuration':False}))
        self.assertEqual(row['status'],'done',row['result'])
        (folder/'devis.txt').write_text('devis écrasé')
        restored=self.manager.submit('snapshot_restore','test',{'repo':repo,'snapshot':json.loads(row['result'])['snapshot']})
        self.assertEqual(self.wait(restored)['status'],'done')
        destination=app.ROOT/'data/restaurations'/restored
        self.assertEqual((destination/'espaces'/('c0'*6)/'devis.txt').read_text(),'devis en cours')
        self.assertFalse((destination/'espaces'/('c0'*6)/'.nacre-trash').exists())
        self.assertEqual((destination/'fichiers/commun.txt').read_text(),'commun')
        self.assertEqual((folder/'devis.txt').read_text(),'devis écrasé')
