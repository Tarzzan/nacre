"""Politiques et captures synthétiques ; aucun dépôt de déploiement."""
import json
import os
import secrets
import time
import unittest
from unittest.mock import patch
import test_retention as base
import automatic_retention as auto
import retention

app=base.app


class PolicyTests(base.RetentionFixture):
    def setUp(self):
        super().setUp();self.repo='a'*24
        with app.database() as db:db.execute('INSERT INTO repositories(id,name,path,target) VALUES(?,?,?,?)',(self.repo,'Fixture',str(app.ROOT/'repo'),'local'))
        self.repository={'id':self.repo,'name':'Fixture'}
        self.points=[self.point(1)]
        for target,name,value in ((self.manager,'repository',self.repository),(self.manager,'points',self.points),
                                  (self.manager,'checked','[]'),(retention,'identity',{'id':'fixture','ino':1,'dev':1,'path':'fixture'})):
            p=patch.object(target,name,return_value=value);p.start();self.addCleanup(p.stop)

    def activate(self):
        proposal=retention.preview(app,{'repo':self.repo,'keep_last':1},'admin')
        auto.configure(app,{'repo':self.repo,'version':proposal['policy_version'],'enabled':True,'confirm':True,'token':proposal['token']},'admin')
        return proposal

    def capture(self,status='done',repo=None):
        identifier=secrets.token_hex(12)
        with app.database() as db:db.execute('INSERT INTO jobs(id,kind,status,result,options,username,ts) VALUES(?,?,?,?,?,?,?)',
            (identifier,'snapshot',status,json.dumps({'snapshot':self.points[0]['id']}),json.dumps({'repo':repo or self.repo}),'admin',time.time()))
        return identifier

    def dispatch(self):
        with patch.object(self.manager,'spawn'):return auto.dispatch(app)

    def policy(self):
        with app.database() as db:return auto.read(db,self.repo)

    def test_default_disabled_activation_excludes_history_partial_and_other_repositories(self):
        self.capture();self.assertEqual(self.dispatch(),[]);self.assertFalse(auto.listing(app)[0]['enabled'])
        self.activate();self.assertEqual(self.dispatch(),[])
        self.capture('partial');self.capture('failed');self.capture(repo='other');self.assertEqual(self.dispatch(),[])
        self.capture();self.assertEqual(len(self.dispatch()),1)

    def test_simulation_actor_confirmation_version_and_single_consumption(self):
        p=retention.preview(app,{'repo':self.repo,'keep_last':1},'admin')
        body={'repo':self.repo,'version':p['policy_version'],'enabled':True,'confirm':True,'token':p['token']}
        for changes,actor in (({'confirm':False},'admin'),({},'other'),({'version':100},'admin')):
            with self.assertRaises(app.Problem):auto.configure(app,{**body,**changes},actor)
        with patch.object(auto.time,'time',return_value=p['expires']+1),self.assertRaises(app.Problem):auto.configure(app,body,'admin')
        auto.configure(app,body,'admin')
        with self.assertRaises(app.Problem):auto.configure(app,body,'admin')
        with self.assertRaises(app.Problem):auto.configure(app,{'repo':self.repo,'version':0,'enabled':False},'admin')

    def test_dispatch_is_durable_deduplicated_and_serial_per_repository(self):
        self.activate();self.capture();first=self.dispatch();self.assertEqual(len(first),1)
        self.capture();self.assertEqual(self.dispatch(),[])
        self.manager.update(first[0],status='done')
        second=self.dispatch();self.assertEqual(len(second),1);self.assertNotEqual(first,second)
        self.manager.update(second[0],status='done');self.assertEqual(self.dispatch(),[])

    def test_concurrent_dispatchers_claim_one_job(self):
        from concurrent.futures import ThreadPoolExecutor
        self.activate();self.capture()
        with patch.object(self.manager,'spawn') as spawn,ThreadPoolExecutor(max_workers=4) as pool:
            claimed=list(pool.map(lambda _:auto.dispatch(app),range(4)))
        self.assertEqual(sum(len(jobs) for jobs in claimed),1);spawn.assert_called_once()

    def test_disable_cancels_waiting_work_without_suspending_replacement(self):
        self.activate();self.capture();job=self.dispatch()[0]
        auto.configure(app,{'repo':self.repo,'version':1,'enabled':False},'admin')
        self.activate()
        with patch.object(retention,'run') as run:self.manager.run_job(job);run.assert_not_called()
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'cancelled')
        self.assertTrue(self.policy()['enabled']);self.assertEqual(self.policy()['version'],3)

    def test_changed_repository_suspends_without_mutation(self):
        self.activate();self.capture();job=self.dispatch()[0]
        with patch.object(retention,'identity',return_value={'id':'changed'}),patch.object(retention,'run') as run:
            self.manager.run_job(job);run.assert_not_called()
        self.assertFalse(self.policy()['enabled']);self.assertTrue(self.policy()['reason'])
        self.assertEqual(self.dispatch(),[])

    def test_revoked_administrator_prevents_automatic_deletion(self):
        self.activate();self.capture();job=self.dispatch()[0]
        with app.database() as db:db.execute("UPDATE users SET active=0 WHERE name='admin'")
        with patch.object(retention,'run') as run:self.manager.run_job(job);run.assert_not_called()
        self.assertFalse(self.policy()['enabled'])

    def test_dead_worker_suspends_policy_and_never_replays(self):
        self.activate();self.capture();job=self.dispatch()[0]
        with app.database() as db:db.execute("UPDATE jobs SET status='running',pid=999999999,ts=? WHERE id=?",(time.time()-60,job))
        self.manager.recover();self.assertFalse(self.policy()['enabled']);self.assertEqual(self.dispatch(),[])
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'partial')

    def test_crash_between_failure_and_suspension_blocks_future_dispatch(self):
        self.activate();self.capture();job=self.dispatch()[0]
        self.manager.update(job,status='partial')
        self.capture();self.assertEqual(self.dispatch(),[])
        self.assertFalse(self.policy()['enabled'])

    def test_suspension_is_collected_as_local_alert(self):
        import alerts
        self.activate();self.capture();job=self.dispatch()[0];self.manager.cancel(job);self.manager.run_job(job)
        with patch.object(app,'compose',side_effect=app.Problem('fixture offline')):
            scopes,_=alerts.collect(app)
        incident=next(x for x in scopes['backups'] if x['key']=='retention:'+self.repo)
        self.assertEqual(incident['page'],'retention');self.assertEqual(incident['severity'],'critical')


@unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Runtime restic requis pour le scénario isolé.')
class AutomaticRealTests(base.RetentionFixture):
    def setUp(self):
        super().setUp()
        self.repo=self.manager.create_repository({'name':'Rétention automatique isolée','target':'local','password':'synthetic-retention-key-only'},'admin')['id']

    def capture(self,text):
        (app.ROOT/'data/fichiers/temoin.txt').write_text(text)
        with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot','admin',{'repo':self.repo,'configuration':False})
        self.manager.run_job(job)
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'done')
        return job

    def activate(self):
        p=retention.preview(app,{'repo':self.repo,'keep_last':1},'admin')
        auto.configure(app,{'repo':self.repo,'version':p['policy_version'],'token':p['token'],'enabled':True,'confirm':True},'admin')

    def test_future_success_cleans_once_and_latest_data_restores(self):
        self.capture('ancienne');self.activate()
        with patch.object(self.manager,'spawn'):self.assertEqual(auto.dispatch(app),[])
        self.capture('version conservée')
        with patch.object(self.manager,'spawn'):job=auto.dispatch(app)[0]
        self.manager.run_job(job)
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'done')
        points=self.manager.points(self.repo);self.assertEqual(len(points),1)
        self.manager.checked(self.manager.repository(self.repo),'check','--read-data',timeout=60)
        with patch.object(self.manager,'spawn'):
            self.assertEqual(auto.dispatch(app),[])
            restored=self.manager.submit('snapshot_restore','admin',{'repo':self.repo,'snapshot':points[0]['id']})
        self.manager.run_job(restored)
        self.assertEqual((app.ROOT/'data/restaurations'/restored/'fichiers/temoin.txt').read_text(),'version conservée')

    def test_cleanup_failure_preserves_backup_success_and_suspends_policy(self):
        self.capture('ancienne');self.activate();capture=self.capture('réussie')
        with patch.object(self.manager,'spawn'):job=auto.dispatch(app)[0]
        stream=self.manager.stream
        def fail(repository,identifier,*operation):
            if operation[0]=='prune':raise InterruptedError()
            return stream(repository,identifier,*operation)
        with patch.object(self.manager,'stream',side_effect=fail):self.manager.run_job(job)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(capture,)).fetchone()[0],'done')
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'partial')
            self.assertFalse(auto.read(db,self.repo)['enabled'])
