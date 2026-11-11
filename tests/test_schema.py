"""Reprise après erreur et arrêt brutal, sur bases temporaires uniquement."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE/'console'))
import schema
from recover_database import prepare


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root/'console.db'

    def tearDown(self):
        self.temp.cleanup()

    def legacy(self, wal=False):
        db = sqlite3.connect(self.db)
        if wal: db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE users(name TEXT PRIMARY KEY,salt TEXT,hash TEXT,role TEXT)')
        salt = '11'*16
        password_hash = hashlib.scrypt(b'compte-synthetique', salt=bytes.fromhex(salt), n=16384,r=8,p=1).hex()
        db.execute('INSERT INTO users VALUES(?,?,?,?)', ('admin',salt,password_hash,'admin'))
        db.commit(); self.db.chmod(0o600)
        return db

    def snapshot(self):
        return next((self.root/'migration-backups').glob('*.sqlite3'))

    def test_new_database_and_idempotent_schema(self):
        schema.ensure(self.db)
        schema.ensure(self.db)
        self.assertEqual(schema.status(self.db)['schema_version'],2)
        self.assertEqual(schema.status(self.db)['checkpoints'],[])
        self.assertEqual(self.db.stat().st_mode & 0o777,0o600)

    def test_legacy_wal_is_preserved_and_checkpoint_is_private(self):
        with closing(self.legacy(wal=True)) as old:
            schema.ensure(self.db)
            self.assertEqual(old.execute('SELECT active FROM users').fetchone()[0],1)
            with closing(schema.readonly(self.snapshot())) as saved:
                self.assertEqual(saved.execute('SELECT name FROM users').fetchone()[0],'admin')
                self.assertNotIn('active',schema.columns(saved,'users'))
            self.assertEqual(self.snapshot().stat().st_mode & 0o777,0o600)
            schema.ensure(self.db)
            self.assertEqual(len(schema.status(self.db)['checkpoints']),1)

    def test_migration_failure_rolls_back_and_can_retry(self):
        self.legacy().close()
        def fail(db):
            db.execute('ALTER TABLE users ADD COLUMN partial TEXT')
            raise RuntimeError('interruption synthétique')
        with patch.object(schema,'migrate_v1',fail), self.assertRaises(RuntimeError):
            schema.ensure(self.db)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertNotIn('partial',schema.columns(db,'users'))
        schema.ensure(self.db)
        self.assertEqual(schema.status(self.db)['schema_version'],2)

    def test_process_killed_during_migration_recovers_old_state(self):
        self.legacy().close()
        script="""
import os, signal, sys
sys.path.insert(0, sys.argv[1])
import schema
from pathlib import Path
def crash(db):
    db.execute('ALTER TABLE users ADD COLUMN uncommitted TEXT')
    os.kill(os.getpid(), signal.SIGKILL)
schema.migrate_v1=crash
schema.ensure(Path(sys.argv[2]))
"""
        result=subprocess.run([sys.executable,'-c',script,str(SOURCE/'console'),str(self.db)],capture_output=True)
        self.assertEqual(result.returncode,-signal.SIGKILL)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertNotIn('uncommitted',schema.columns(db,'users'))
            self.assertEqual(db.execute('SELECT name FROM users').fetchone()[0],'admin')
        self.assertTrue(self.snapshot().is_file())
        schema.ensure(self.db)
        self.assertEqual(schema.status(self.db)['schema_version'],2)

    def test_checkpoint_failure_leaves_schema_unchanged(self):
        self.legacy().close()
        with patch.object(schema,'checkpoint',side_effect=OSError('espace indisponible')),self.assertRaises(OSError):
            schema.ensure(self.db)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertNotIn('active',schema.columns(db,'users'))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)

    def test_incompatible_legacy_schema_is_not_marked_migrated(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE users(name TEXT)')
        self.db.chmod(0o600)
        with self.assertRaises(schema.SchemaError):schema.ensure(self.db)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertNotIn('active',schema.columns(db,'users'))

    def test_future_schema_refused_without_changing_database(self):
        self.legacy().close()
        with closing(sqlite3.connect(self.db)) as db:db.execute('PRAGMA user_version=999')
        before=self.db.read_bytes()
        with self.assertRaises(schema.SchemaError):schema.ensure(self.db)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse((self.root/'migration-backups').exists())

    def test_symlink_database_and_checkpoint_directory_refused(self):
        other=self.root/'other';other.write_bytes(b'untouched')
        self.db.symlink_to(other)
        with self.assertRaises(schema.SchemaError):schema.ensure(self.db)
        self.assertEqual(other.read_bytes(),b'untouched')
        self.db.unlink();self.legacy().close()
        directory=self.root/'elsewhere';directory.mkdir(mode=0o700)
        (self.root/'migration-backups').symlink_to(directory)
        with self.assertRaises(schema.SchemaError):schema.ensure(self.db)
        self.assertEqual(list(directory.iterdir()),[])

    def test_recovery_is_new_file_and_neutralizes_live_state(self):
        self.legacy().close()
        with closing(sqlite3.connect(self.db)) as db:
            schema.migrate_v1(db)
            db.execute("INSERT INTO sessions VALUES('ancien-token','admin','csrf',9999999999)")
            db.execute("INSERT INTO tickets VALUES('ancien-ticket',9999999999)")
            db.execute("INSERT INTO plans(id,enabled,next_run) VALUES('plan',1,1)")
            db.execute("INSERT INTO jobs(id,status,pid) VALUES('job','running',1234)")
            db.commit()
        schema.ensure(self.db)
        current=self.db.read_bytes()
        output=self.root/'recovered.sqlite3'
        result=prepare(self.snapshot(),output)
        self.assertFalse(result['active_database_replaced'])
        self.assertEqual(self.db.read_bytes(),current)
        with closing(sqlite3.connect(output)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT enabled,next_run FROM plans').fetchone(),(0,None))
            self.assertEqual(db.execute('SELECT status,pid,cancel FROM jobs').fetchone(),('failed',None,1))
            salt, saved=db.execute("SELECT salt,hash FROM users WHERE name='admin'").fetchone()
            self.assertEqual(hashlib.scrypt(b'compte-synthetique',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex(),saved)
        schema.ensure(output)
        self.assertEqual(schema.status(output)['schema_version'],2)
        with self.assertRaises(schema.SchemaError):prepare(self.snapshot(),output)

    def test_recovery_disables_automatic_retention_and_discards_confirmations(self):
        self.legacy().close();schema.ensure(self.db)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT INTO settings VALUES(?,?)',('retention-policy:fixture',json.dumps({'repo':'fixture','version':1,'enabled':True})))
            db.execute("INSERT INTO settings VALUES('cleanup-preview:fixture','{}')");db.execute("INSERT INTO settings VALUES('retention-preview:fixture','{}')");db.commit()
        schema.checkpoint(self.db,2)
        source=next(p for p in (self.root/'migration-backups').glob('*.sqlite3') if json.loads(p.with_suffix('.json').read_text())['source_version']==2)
        output=self.root/'neutralized.sqlite3';prepare(source,output)
        with closing(sqlite3.connect(output)) as db:
            policy=json.loads(db.execute("SELECT value FROM settings WHERE key='retention-policy:fixture'").fetchone()[0])
            self.assertFalse(policy['enabled']);self.assertEqual(policy['version'],2)
            self.assertEqual(db.execute("SELECT count(*) FROM settings WHERE key LIKE 'retention-preview:%' OR key LIKE 'cleanup-preview:%'").fetchone()[0],0)

    def test_corrupted_checkpoint_refused(self):
        self.legacy().close();schema.ensure(self.db)
        with self.snapshot().open('ab') as stream:stream.write(b'corruption')
        output=self.root/'recovered.sqlite3'
        with self.assertRaises(schema.SchemaError):prepare(self.snapshot(),output)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.nacre-recovery-*')))

    def test_parallel_startup_creates_one_checkpoint(self):
        self.legacy().close()
        script='import sys;sys.path.insert(0,sys.argv[1]);import schema;schema.ensure(sys.argv[2])'
        processes=[subprocess.Popen([sys.executable,'-c',script,str(SOURCE/'console'),str(self.db)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE) for _ in range(3)]
        for process in processes:
            _,error=process.communicate(timeout=30)
            self.assertEqual(process.returncode,0,error)
        self.assertEqual(len(schema.status(self.db)['checkpoints']),1)


if __name__=='__main__':unittest.main()
