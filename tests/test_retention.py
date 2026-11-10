"""Dépôts et fichiers temporaires uniquement ; jamais de cible de déploiement."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'console'))
import retention
spec=importlib.util.spec_from_file_location('retention_test_app',SOURCE/'console/server.py')
app=importlib.util.module_from_spec(spec);sys.modules[spec.name]=app;spec.loader.exec_module(app)


class RetentionFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        app.ROOT=Path(self.temp.name);app.STATE=app.ROOT/'state/console';app.DB=app.STATE/'console.db';app.initialize()
        self.manager=app.protection()
        manager_patch=patch.object(app,'protection',return_value=self.manager)
        manager_patch.start();self.addCleanup(manager_patch.stop)

    def record(self, point, status='done', **options):
        with app.database() as db:
            db.execute('INSERT INTO jobs(id,kind,status,result,ts,options,username) VALUES(?,?,?,?,?,?,?)',
                       (secrets.token_hex(12),'snapshot',status,json.dumps({'snapshot':point['id']}),time.time(),json.dumps({'repo':'repo',**options}),'admin'))

    def point(self, number, **changes):
        return {'id':format(number,'064x'),'time':f'2020-01-{number:02d}T12:00:00Z','tags':['nacre'],'hostname':'fixture',**changes}

    def plan(self):
        plan={'token':secrets.token_hex(24),'actor':'admin','repo':'repo','name':'Test',
              'expires':time.time()+900,'remove':[self.point(1)]}
        with app.database() as db:db.execute('INSERT INTO settings VALUES(?,?)',(retention.PREFIX+plan['token'],json.dumps(plan)))
        return plan


class RetentionTests(RetentionFixture):
    def test_keep_minimum_and_reject_non_integer_policy(self):
        for value in (0,-1,True,'7',1.5,None,1000001):
            with self.subTest(value=value),self.assertRaises(app.Problem):retention.preview(app,{'keep_last':value},'admin')

    def test_groups_and_unproven_partial_future_snapshots_remain_protected(self):
        points=[self.point(i) for i in range(1,9)]
        for p in points[:3]:self.record(p,configuration=True,plan='one')
        self.record(points[3],configuration=True,plan='two')
        self.record(points[4],configuration=False,plan='one')
        self.record(points[5],status='partial',plan='one')
        # Point 7 is imported; point 8 claims a future date.
        points[7]['time']='2999-01-01T00:00:00Z';self.record(points[7],plan='one')
        result=retention.selection(app,{'id':'repo'},points,1)
        self.assertEqual({p['id'] for p in result['remove']},{points[0]['id'],points[1]['id']})
        self.assertEqual(len(result['keep']),3);self.assertEqual(len(result['protected']),3)

    def test_confirmation_actor_expiry_and_single_consumption(self):
        plan=self.plan()
        for body,actor in (({'token':plan['token']},'admin'),({'token':plan['token'],'confirm':True},'other')):
            with self.assertRaises(app.Problem):retention.submit(app,body,actor)
        with patch.object(self.manager,'spawn') as spawn:
            job=retention.submit(app,{'token':plan['token'],'confirm':True},'admin')['job']
            spawn.assert_called_once_with(job)
            with self.assertRaises(app.Problem):retention.submit(app,{'token':plan['token'],'confirm':True},'admin')
        plan=self.plan()
        with patch.object(retention.time,'time',return_value=plan['expires']+1),self.assertRaises(app.Problem):
            retention.submit(app,{'token':plan['token'],'confirm':True},'admin')

    def test_busy_preview_refuses_before_reading_repository(self):
        with (app.STATE/'task.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with self.assertRaises(app.Problem) as raised:retention.preview(app,{'repo':'repo','keep_last':1},'admin')
            self.assertEqual(raised.exception.status,409)

    def test_recovery_of_dead_worker_reports_possible_partial_deletion(self):
        with patch.object(self.manager,'spawn'):
            job=self.manager.submit('retention','admin',{'repo':'fixture'})
        with app.database() as db:db.execute("UPDATE jobs SET status='running',pid=999999999,ts=? WHERE id=?",(time.time()-60,job))
        self.manager.recover()
        with app.database() as db:row=db.execute('SELECT status,result FROM jobs WHERE id=?',(job,)).fetchone()
        self.assertEqual(row['status'],'partial');self.assertIn('supprimés',json.loads(row['result'])['warning'])


@unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Runtime restic requis pour les suppressions isolées.')
class RealRetentionTests(RetentionFixture):
    def setUp(self):
        super().setUp()
        self.repo=self.manager.create_repository({'name':'Fixture rétention','target':'local','password':'synthetic-retention-key-only'},'admin')['id']
        self.repository=self.manager.repository(self.repo)
        self.source=app.ROOT/'data/fichiers/temoin.txt'
        self.capture('ancienne version');self.capture('version conservée')

    def capture(self, text):
        self.source.write_text(text)
        with patch.object(self.manager,'spawn'):
            job=self.manager.submit('snapshot','admin',{'repo':self.repo,'configuration':False})
        self.manager.run_job(job)
        row=self.job(job);self.assertEqual(row['status'],'done',row['result'])
        return json.loads(row['result'])['snapshot']

    def job(self, identifier):
        with app.database() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone())

    def preview(self):return retention.preview(app,{'repo':self.repo,'keep_last':1},'admin')

    def submit(self, p):
        with patch.object(self.manager,'spawn'):
            return retention.submit(app,{'token':p['token'],'confirm':True},'admin')['job']

    def test_real_dry_run_prune_check_and_restore_preserve_latest_bytes(self):
        before={p['id'] for p in self.manager.points(self.repo)}
        p=self.preview();self.assertEqual(len(p['remove']),1)
        self.assertEqual(before,{p['id'] for p in self.manager.points(self.repo)})
        self.assertNotIn('identity',p)
        job=self.submit(p);self.manager.run_job(job)
        row=self.job(job);self.assertEqual(row['status'],'done',row['result'])
        points=self.manager.points(self.repo);self.assertEqual(len(points),1)
        self.assertEqual(points[0]['id'],p['keep'][0]['id'])
        self.manager.checked(self.repository,'check','--read-data',timeout=60)
        with patch.object(self.manager,'spawn'):
            restored=self.manager.submit('snapshot_restore','admin',{'repo':self.repo,'snapshot':points[0]['id']})
        self.manager.run_job(restored)
        self.assertEqual(self.job(restored)['status'],'done')
        self.assertEqual((app.ROOT/'data/restaurations'/restored/'fichiers/temoin.txt').read_text(),'version conservée')

    def test_changed_points_and_repository_identity_refuse_deletion(self):
        p=self.preview();self.capture('nouvelle capture après simulation')
        job=self.submit(p);self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'failed');self.assertEqual(len(self.manager.points(self.repo)),3)
        p=self.preview();job=self.submit(p)
        original=retention.identity
        with patch.object(retention,'identity',side_effect=lambda *a:{**original(*a),'id':'different'}):self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'failed');self.assertEqual(len(self.manager.points(self.repo)),3)

    def test_interrupted_prune_is_partial_and_never_replayed(self):
        p=self.preview();job=self.submit(p);stream=self.manager.stream
        def interrupt(repository,identifier,*operation):
            if operation[0]=='prune':raise InterruptedError()
            return stream(repository,identifier,*operation)
        with patch.object(self.manager,'stream',side_effect=interrupt):self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'partial')
        self.assertEqual(len(self.manager.points(self.repo)),1)
        with patch.object(self.manager,'stream') as again:self.manager.run_job(job);again.assert_not_called()
        self.assertEqual(self.preview()['remove'],[])

    def test_cancel_before_work_keeps_every_snapshot(self):
        p=self.preview();job=self.submit(p);self.manager.cancel(job);self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'cancelled');self.assertEqual(len(self.manager.points(self.repo)),2)
