"""Nettoyage sur dépôts jetables, aucune donnée utilisateur."""
import json
import os
import time
import unittest
from unittest.mock import patch
import test_retention as base
import cleanup

app=base.app


class CleanupTests(base.RetentionFixture):
    def setUp(self):
        super().setUp()
        self.repo={'id':'repo','name':'Fixture'}
        for name,value in [('repository',self.repo),('points',[self.point(1)]),('stream',({},0))]:
            mock=patch.object(self.manager,name,return_value=value);mock.start();self.addCleanup(mock.stop)
        mock=patch.object(cleanup.retention,'identity',return_value={'id':'fixture'});mock.start();self.addCleanup(mock.stop)

    def job(self, job):
        with app.database() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())

    def preview(self):
        with patch.object(self.manager,'spawn'):job=cleanup.preview(app,{'repo':'repo'},'admin')['job']
        self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'done',self.job(job)['result'])
        return job,cleanup.review(app,job,'admin')

    def apply(self, job, plan):
        with patch.object(self.manager,'spawn'):
            return cleanup.submit(app,{'job':job,'token':plan['token'],'confirm':True},'admin')['job']

    def test_author_confirmation_token_expiry_and_single_use(self):
        job,p=self.preview()
        self.assertNotIn('identity',p);self.assertNotIn('token',self.job(job)['result'])
        with self.assertRaises(app.Problem):cleanup.review(app,job,'other')
        for body,actor in [({'job':job,'token':p['token']},'admin'),({'job':job,'token':p['token'],'confirm':True},'other'),({'job':job,'token':'wrong','confirm':True},'admin')]:
            with self.assertRaises(app.Problem):cleanup.submit(app,body,actor)
        with patch.object(cleanup.time,'time',return_value=p['expires']+1),self.assertRaises(app.Problem):cleanup.review(app,job,'admin')
        self.apply(job,p)
        with self.assertRaises(app.Problem):self.apply(job,p)

    def test_failed_dry_run_never_issues_confirmation(self):
        with patch.object(self.manager,'spawn'):job=cleanup.preview(app,{'repo':'repo'},'admin')['job']
        self.manager.stream.side_effect=app.Problem('fixture failure')
        self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'failed')
        with self.assertRaises(app.Problem):cleanup.review(app,job,'admin')

    def test_changes_and_expiry_refuse_before_mutation(self):
        for change in ('points','identity','expiry'):
            with self.subTest(change=change):
                job,p=self.preview();task=self.apply(job,p);self.manager.stream.reset_mock()
                if change=='points':mock=patch.object(self.manager,'points',return_value=[self.point(2)])
                elif change=='identity':mock=patch.object(cleanup.retention,'identity',return_value={'id':'replaced'})
                else:mock=patch.object(cleanup.time,'time',return_value=p['expires']+1)
                with mock:self.manager.run_job(task)
                self.assertEqual(self.job(task)['status'],'failed');self.manager.stream.assert_not_called()

    def test_cancellation_and_partial_result_never_replay(self):
        job,p=self.preview();task=self.apply(job,p);self.manager.cancel(task);self.manager.stream.reset_mock()
        self.manager.run_job(task);self.assertEqual(self.job(task)['status'],'cancelled');self.manager.stream.assert_not_called()
        job,p=self.preview();task=self.apply(job,p)
        self.manager.stream.side_effect=InterruptedError()
        self.manager.run_job(task);self.assertEqual(self.job(task)['status'],'partial')
        self.manager.stream.reset_mock();self.manager.run_job(task);self.manager.stream.assert_not_called()

    def test_dead_worker_is_partial_but_dead_simulation_is_failed(self):
        for kind,status in [('cleanup','partial'),('cleanup_preview','failed')]:
            with patch.object(self.manager,'spawn'):job=self.manager.submit(kind,'admin',{'repo':'repo'})
            with app.database() as db:db.execute("UPDATE jobs SET status='running',pid=999999999,ts=? WHERE id=?",(time.time()-60,job))
            self.manager.recover();self.assertEqual(self.job(job)['status'],status)

    def test_check_failure_cannot_claim_success_or_reactivate_policy(self):
        policy={'repo':'repo','version':3,'enabled':False,'reason':'Incident'}
        with app.database() as db:db.execute('INSERT INTO settings VALUES(?,?)',('retention-policy:repo',json.dumps(policy)))
        job,p=self.preview();task=self.apply(job,p)
        self.manager.stream.side_effect=[({},0),app.Problem('check failed')]
        self.manager.run_job(task);self.assertEqual(self.job(task)['status'],'partial')
        with app.database() as db:self.assertEqual(json.loads(db.execute("SELECT value FROM settings WHERE key='retention-policy:repo'").fetchone()[0]),policy)


@unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Runtime restic requis.')
class RealCleanupTests(base.RetentionFixture):
    def test_resume_after_forget_dry_run_preserves_points_and_restore_exact_bytes(self):
        repo=self.manager.create_repository({'name':'Fixture nettoyage','target':'local','password':'synthetic-cleanup-key-only'},'admin')['id']
        source=app.ROOT/'data/fichiers/temoin.txt'
        for content in ('ancienne version abandonnée','version conservée après reprise'):
            source.write_text(content)
            with patch.object(self.manager,'spawn'):task=self.manager.submit('snapshot','admin',{'repo':repo,'configuration':False})
            self.manager.run_job(task)
        p=base.retention.preview(app,{'repo':repo,'keep_last':1},'admin')
        with patch.object(self.manager,'spawn'):task=base.retention.submit(app,{'token':p['token'],'confirm':True},'admin')['job']
        stream=self.manager.stream
        def interrupt(repository,job,*operation):
            if operation[0]=='prune':raise InterruptedError()
            return stream(repository,job,*operation)
        with patch.object(self.manager,'stream',side_effect=interrupt):self.manager.run_job(task)
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(task,)).fetchone()[0],'partial')
        expected={p['keep'][0]['id']}
        self.assertEqual({x['id'] for x in self.manager.points(repo)},expected)
        with patch.object(self.manager,'stream',wraps=stream) as calls:
            with patch.object(self.manager,'spawn'):preview=cleanup.preview(app,{'repo':repo},'admin')['job']
            self.manager.run_job(preview)
            p=cleanup.review(app,preview,'admin')
            self.assertEqual({x['id'] for x in self.manager.points(repo)},expected)
            with patch.object(self.manager,'spawn'):task=cleanup.submit(app,{'job':preview,'token':p['token'],'confirm':True},'admin')['job']
            self.manager.run_job(task)
            self.assertEqual([call.args[2] for call in calls.call_args_list],['prune','prune','check'])
            self.assertIn('--dry-run',calls.call_args_list[0].args)
        with app.database() as db:
            row=db.execute('SELECT status,result FROM jobs WHERE id=?',(task,)).fetchone()
            self.assertEqual(row['status'],'done',row['result']);self.assertEqual(json.loads(row['result'])['removed'],0)
        self.assertEqual({x['id'] for x in self.manager.points(repo)},expected)
        self.manager.checked(self.manager.repository(repo),'check','--read-data',timeout=60)
        with patch.object(self.manager,'spawn'):restored=self.manager.submit('snapshot_restore','admin',{'repo':repo,'snapshot':next(iter(expected))})
        self.manager.run_job(restored)
        self.assertEqual((app.ROOT/'data/restaurations'/restored/'fichiers/temoin.txt').read_text(),content)
