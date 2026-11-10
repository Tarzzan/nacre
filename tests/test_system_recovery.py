"""Refus de reprise dangereuse ; aucun démon ni disque de l’hôte utilisé."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'console'))
sys.path.insert(0,str(SOURCE))
import schema
import system_recovery as recovery
from installation_lock import held
from compose_support import arguments


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.root=self.base/'installation'
        (self.root/'state/console').mkdir(parents=True,mode=0o700)
        (self.root/'state/samba').mkdir()
        (self.root/'data/.corbeille').mkdir(parents=True)
        schema.ensure(self.root/'state/console/console.db')
        self.config={'users':[{'name':'nas','uid':os.getuid(),'enabled':True}],'shares':[]}
        (self.root/'state/console/smb.json').write_text(json.dumps(self.config))
        with self.db() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('admin','salt','hash','admin')")
    def tearDown(self):self.temp.cleanup()
    def db(self):return sqlite3.connect(self.root/'state/console/console.db')
    def archive(self,members):
        path=self.base/'samba.tar'
        with tarfile.open(path,'w') as archive:
            for name,kind in members:
                info=tarfile.TarInfo(name);info.type=kind
                archive.addfile(info,io.BytesIO())
        return path
    def test_archive_requires_passdb_and_rejects_links_traversal_duplicates(self):
        recovery.tar_safe(self.archive([('passdb.tdb',tarfile.REGTYPE)]))
        for members in ([('../passdb.tdb',tarfile.REGTYPE)],[('/passdb.tdb',tarfile.REGTYPE)],
                        [('passdb.tdb',tarfile.SYMTYPE)],[('passdb.tdb',tarfile.LNKTYPE)],
                        [('passdb.tdb',tarfile.REGTYPE)]*2,[('other',tarfile.REGTYPE)]):
            with self.subTest(members=members),self.assertRaises(recovery.RecoveryError):recovery.tar_safe(self.archive(members))
    def test_live_installation_excludes_capture_and_capture_excludes_start(self):
        with held(self.root):
            with self.assertRaises(RuntimeError),held(self.root,True):pass
        with held(self.root,True):
            with self.assertRaises(RuntimeError),held(self.root):pass
        with held(self.root,True):pass
    def test_prepare_refuses_existing_target_before_engine_call(self):
        with patch.object(recovery,'restic') as engine,self.assertRaises(recovery.RecoveryError):
            recovery.prepare(self.base/'repo',self.base/'key','a'*64,self.root)
        engine.assert_not_called()
    def test_pending_snapshot_cannot_be_restored(self):
        with patch.object(recovery,'restic',return_value=json.dumps([{'tags':[recovery.PENDING]}]).encode()),self.assertRaises(recovery.RecoveryError):
            recovery.prepare(self.base/'repo',self.base/'key','a'*64,self.base/'new')
        self.assertFalse((self.base/'new').exists())
    def test_native_sources_refuse_nested_and_missing_mappings(self):
        outer=self.base/'external';(outer/'inner').mkdir(parents=True)
        path=self.root/'state/console/recovery-volumes.json'
        path.write_text(json.dumps({'native_outer':str(outer),'native_inner':str(outer/'inner')}))
        with self.assertRaises(recovery.RecoveryError):recovery.native_sources(self.root)
        path.unlink()
        self.config['shares']=[{'area':'native_absent'}]
        (self.root/'state/console/smb.json').write_text(json.dumps(self.config))
        with self.assertRaises(recovery.RecoveryError):recovery.native_sources(self.root)
    def test_neutralize_keeps_accounts_disables_activity_and_detaches_repositories(self):
        with self.db() as db:
            db.execute("INSERT INTO sessions VALUES('s','admin','csrf',9999999999)")
            db.execute("INSERT INTO tickets VALUES('t',9999999999)")
            db.execute('INSERT INTO plans(id,enabled,config,next_run) VALUES(?,1,?,1)',('b'*24,json.dumps({'sources':['native_data','fichiers']})))
            db.execute("INSERT INTO jobs(id,status) VALUES('j','running')")
            db.execute('INSERT INTO repositories(id,key_file,target) VALUES(?,?,?)',('a'*24,'/old/key','native_data'))
        recovery.neutralize(self.root,'/old',{'volumes':{}})
        with self.db() as db:
            self.assertEqual(db.execute('SELECT hash FROM users').fetchone()[0],'hash')
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0],0)
            row=db.execute('SELECT enabled,config,next_run FROM plans').fetchone()
            self.assertEqual((row[0],row[2]),(0,None));self.assertEqual(json.loads(row[1])['sources'],['fichiers'])
            self.assertEqual(db.execute('SELECT status,cancel FROM jobs').fetchone(),('failed',1))
            self.assertEqual(db.execute('SELECT target FROM repositories').fetchone()[0],'recovery-detached')
        project=json.loads((self.root/'state/console/recovery-project.json').read_text())['project']
        self.assertIn(project,arguments(self.root,'ps'))
    def test_future_schema_is_refused_before_modification(self):
        with self.db() as db:
            db.execute('PRAGMA user_version=999');db.execute("INSERT INTO tickets VALUES('t',9999999999)")
        with self.assertRaises(recovery.RecoveryError):recovery.neutralize(self.root,'/old',{'volumes':{}})
        with self.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0],1)
    def test_start_requires_imported_samba_state(self):
        (self.root/'state/console/system-recovery-status.json').write_text('{}')
        for command in ('up','start','restart'):
            with self.assertRaises(ValueError):arguments(self.root,command)
        self.assertIn('stop',arguments(self.root,'stop'))
        (self.root/'state/samba/recovery.compose.json').write_text('{}')
        self.assertIn('up',arguments(self.root,'up'))
    def test_wrong_repository_identity_never_changes_database(self):
        (self.root/'state/console/recovery-repositories.json').write_text(json.dumps({'a'*24:'expected'}))
        with self.db() as db:db.execute('INSERT INTO repositories(id,path,target) VALUES(?,?,?)',('a'*24,'old','recovery-detached'))
        with patch.object(recovery,'restic',return_value=b'{"id":"other"}'),self.assertRaises(recovery.RecoveryError):recovery.attach(self.root,'a'*24,self.base/'repo')
        with self.db() as db:self.assertEqual(db.execute('SELECT path,target FROM repositories').fetchone(),('old','recovery-detached'))
    def test_configuration_symlink_is_refused(self):
        (self.root/'state/samba/unsafe').symlink_to(self.base)
        with self.assertRaises(recovery.RecoveryError):recovery.validate_tree(self.root)
    def test_native_trash_is_rebased_without_losing_data(self):
        identifier='a'*32
        path=self.root/'data/fichiers/reprise-volumes/native_data/.nacre-trash'/identifier
        path.parent.mkdir(parents=True);path.write_text('témoin')
        with self.db() as db:db.execute('INSERT INTO trash(id,original,area) VALUES(?,?,?)',(identifier,'ancien.txt','native_data'))
        recovery.neutralize(self.root,'/old',{'volumes':{'native_data':'/external'}})
        self.assertEqual((self.root/'data/.corbeille'/identifier).read_text(),'témoin')
        with self.db() as db:self.assertEqual(db.execute('SELECT area,original FROM trash').fetchone(),('fichiers','reprise-volumes/native_data/ancien.txt'))

if __name__=='__main__':unittest.main()
