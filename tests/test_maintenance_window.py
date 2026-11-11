"""Créneaux et reprise persistante, sans horloge ni installation de production."""
from datetime import datetime
import json
import os
import secrets
import sqlite3
import time
import unittest
from unittest.mock import patch
import test_retention as base
import automatic_retention as auto
import maintenance_window as window
import retention

app=base.app

def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


class ClockTests(base.RetentionFixture):
    def test_validation_rejects_ambiguous_times_before_repository_access(self):
        invalid=[None,[],{'days':[1]},{'enabled':1},{'start':'24:00'},{'end':'2:00'},{'start':'02:30:00'},
                 {'end':True},{'enabled':True,'start':'02:00','end':'02:00'}]
        with patch.object(retention,'proposal') as proposal:
            for value in invalid:
                with self.subTest(value=value),self.assertRaises(app.Problem):
                    retention.preview(app,{'repo':'fixture','keep_last':1,'window':value},'admin')
            proposal.assert_not_called()

    def test_boundaries_overnight_and_timezone(self):
        rule=window.validate(app,{'enabled':True,'start':'22:00','end':'02:00'})
        for value,expected in [('2024-01-02T00:59:00Z',False),('2024-01-02T01:00:00Z',True),
                               ('2024-01-02T04:59:59Z',True),('2024-01-02T05:00:00Z',False)]:
            self.assertEqual(window.allows(rule,'America/Cayenne',stamp(value)),expected)
        self.assertTrue(window.allows(window.defaults(),'UTC',stamp('2024-01-01T12:00:00Z')))

    def test_dst_gap_skips_missing_window_and_repeated_hour_stays_eligible(self):
        rule=window.validate(app,{'enabled':True,'start':'02:00','end':'03:00'})
        for value in ('2024-03-31T00:59:00Z','2024-03-31T01:00:00Z'):
            self.assertFalse(window.allows(rule,'Europe/Paris',stamp(value)))
        for value in ('2024-10-27T00:30:00Z','2024-10-27T01:30:00Z'):
            self.assertTrue(window.allows(rule,'Europe/Paris',stamp(value)))


class WeeklyClockTests(base.RetentionFixture):
    def test_invalid_weekly_rules_fail_before_repository_access(self):
        day={'day':0,'start':'22:00','end':'02:00'}
        bad=[{'mode':None},{'mode':[]},{'mode':'weekly','enabled':True},
             {'week':None},{'week':{}},{'week':[day]*8},{'week':[day,day]},
             *({'week':[{**day,'day':v}]} for v in (-1,7,True,1.0,'1')),
             {'week':[{**day,'extra':1}]},{'week':[{'day':0}]},{'week':[None]},
             {'week':[{**day,'start':'24:00'}]},{'week':[{**day,'end':'22:00'}]}]
        with patch.object(retention,'proposal') as proposal:
            for value in bad:
                with self.subTest(value=value),self.assertRaises(app.Problem):
                    retention.preview(app,{'repo':'fixture','keep_last':1,'window':value},'admin')
            proposal.assert_not_called()

    def test_legacy_daily_rule_remains_daily_and_disabled_weekly_is_unrestricted(self):
        legacy={'enabled':True,'start':'22:00','end':'02:00'}
        normalized=window.validate(app,legacy)
        self.assertEqual(normalized['mode'],'daily')
        for day in range(1,8):
            now=stamp(f'2024-01-{day:02}T23:00:00Z')
            self.assertTrue(window.allows(legacy,'UTC',now));self.assertTrue(window.allows(normalized,'UTC',now))
        self.assertTrue(window.allows(window.validate(app,{'enabled':False,'mode':'weekly'}),'UTC',stamp('2024-01-01T12:00:00Z')))

    def test_distinct_weekday_hours_use_local_day_and_exact_boundaries(self):
        rule=window.validate(app,{'enabled':True,'mode':'weekly','week':[
            {'day':4,'start':'10:00','end':'11:00'},{'day':0,'start':'22:00','end':'23:00'}]})
        self.assertEqual([e['day'] for e in rule['week']],[0,4])
        for value,expected in [('2024-01-02T00:59:59Z',False),('2024-01-02T01:00:00Z',True),
            ('2024-01-02T02:00:00Z',False),('2024-01-03T01:30:00Z',False),
            ('2024-01-05T13:00:00Z',True),('2024-01-05T14:00:00Z',False)]:
            self.assertEqual(window.allows(rule,'America/Cayenne',stamp(value)),expected,value)

    def test_overnight_belongs_to_start_day_including_sunday_to_monday(self):
        rule=window.validate(app,{'enabled':True,'mode':'weekly','week':[{'day':6,'start':'22:00','end':'02:00'}]})
        for value,expected in [('2024-01-07T01:00:00Z',False),('2024-01-07T22:00:00Z',True),
            ('2024-01-08T01:59:59Z',True),('2024-01-08T02:00:00Z',False),('2024-01-08T22:00:00Z',False)]:
            self.assertEqual(window.allows(rule,'UTC',stamp(value)),expected,value)

    def test_overlapping_days_form_union_without_gap(self):
        rule=window.validate(app,{'enabled':True,'mode':'weekly','week':[
            {'day':0,'start':'22:00','end':'03:00'},{'day':1,'start':'02:00','end':'04:00'}]})
        for value in ('2024-01-01T23:00:00Z','2024-01-02T01:00:00Z','2024-01-02T02:30:00Z','2024-01-02T03:00:00Z'):
            self.assertTrue(window.allows(rule,'UTC',stamp(value)))
        self.assertFalse(window.allows(rule,'UTC',stamp('2024-01-02T04:00:00Z')))

    def test_weekly_dst_uses_local_calendar_not_elapsed_24_hours(self):
        rule=window.validate(app,{'enabled':True,'mode':'weekly','week':[{'day':5,'start':'22:00','end':'03:00'}]})
        self.assertTrue(window.allows(rule,'Europe/Paris',stamp('2024-03-31T00:59:59Z')))
        self.assertFalse(window.allows(rule,'Europe/Paris',stamp('2024-03-31T01:00:00Z')))
        for value in ('2024-10-27T00:30:00Z','2024-10-27T01:30:00Z'):
            self.assertTrue(window.allows(rule,'Europe/Paris',stamp(value)))
        self.assertFalse(window.allows(rule,'Europe/Paris',stamp('2024-10-27T02:00:00Z')))


class WindowTests(base.RetentionFixture):
    def setUp(self):
        super().setUp();self.repo='b'*24;self.points=[self.point(1),self.point(2)]
        with app.database() as db:db.execute('INSERT INTO repositories(id,name,path,target) VALUES(?,?,?,?)',(self.repo,'Fixture',str(app.ROOT/'repo'),'local'))
        for p in self.points:self.record(p,repo=self.repo,configuration=False)
        for target,name,value in ((self.manager,'repository',{'id':self.repo,'name':'Fixture'}),(self.manager,'points',self.points),
                                  (self.manager,'checked','[]'),(retention,'identity',{'id':'fixture'})):
            mock=patch.object(target,name,return_value=value);mock.start();self.addCleanup(mock.stop)
        p=retention.preview(app,{'repo':self.repo,'keep_last':1,'window':{'enabled':True,'start':'02:00','end':'04:00'}},'admin')
        auto.configure(app,{'repo':self.repo,'version':0,'enabled':True,'confirm':True,'token':p['token'],'window':{'enabled':False}},'admin')

    def capture(self):
        p=self.point(len(self.points)+1);self.points.append(p);identifier=secrets.token_hex(12)
        with app.database() as db:db.execute('INSERT INTO jobs(id,kind,status,result,options,username,ts) VALUES(?,?,?,?,?,?,?)',
            (identifier,'snapshot','done',json.dumps({'snapshot':p['id']}),json.dumps({'repo':self.repo,'configuration':False}),'admin',time.time()))
        return identifier

    def policy(self):
        with app.database() as db:return auto.read(db,self.repo)

    def job(self,identifier):
        with app.database() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone())

    def dispatch(self,opened=True):
        with patch.object(auto,'allowed',return_value=opened),patch.object(self.manager,'spawn'):return auto.dispatch(app)

    def deferred(self):
        self.capture();job=self.dispatch()[0]
        with patch.object(auto,'allowed',return_value=False):self.manager.run_job(job)
        self.assertEqual(self.job(job)['status'],'deferred')
        return job

    def test_activation_uses_simulated_window_and_dispatch_waits_without_worker(self):
        self.assertTrue(self.policy()['window']['enabled'])
        self.capture();self.assertEqual(self.dispatch(False),[])
        with patch.object(auto,'allowed',return_value=False):
            p=auto.listing(app)[0];self.assertEqual(p['pending'],1);self.assertFalse(p['window_open'])
        job=self.dispatch()[0];self.assertEqual(self.job(job)['status'],'queued');self.assertEqual(self.dispatch(),[])

    def test_deferred_job_survives_recovery_and_requeues_same_identifier(self):
        job=self.deferred();self.manager.recover()
        self.assertEqual(self.job(job)['status'],'deferred');self.assertTrue(self.policy()['enabled'])
        self.assertEqual(self.dispatch(False),[])
        self.assertEqual(self.dispatch(),[job]);self.assertEqual(self.dispatch(),[])
        self.assertEqual(self.job(job)['status'],'queued')

    def test_disable_and_offline_recovery_cancel_deferred_tasks(self):
        job=self.deferred()
        auto.configure(app,{'repo':self.repo,'enabled':False,'version':1},'admin')
        self.assertEqual(self.job(job)['status'],'cancelled');self.assertEqual(self.dispatch(),[])
        # La reprise hors ligne utilise des tuples sqlite, sans row_factory.
        with sqlite3.connect(app.DB) as db:
            db.execute("UPDATE jobs SET status='deferred' WHERE id=?",(job,))
            auto.disable_after_recovery(db)
        self.assertEqual(self.job(job)['status'],'cancelled');self.assertFalse(self.policy()['enabled'])

    def test_backlog_is_coalesced_and_late_completion_is_not_lost(self):
        first=self.capture();second=self.capture()
        with app.database() as db:db.execute("UPDATE jobs SET status='running' WHERE id=?",(first,))
        third=self.capture();job=self.dispatch()[0]
        options=json.loads(self.job(job)['options'])
        self.assertEqual(set(options['triggers']),{second,third});self.assertEqual(options['trigger'],third)
        self.manager.update(job,status='done');self.assertEqual(self.dispatch(),[])
        with app.database() as db:db.execute("UPDATE jobs SET status='done' WHERE id=?",(first,))
        followup=self.dispatch();self.assertEqual(len(followup),1)
        self.assertEqual(json.loads(self.job(followup[0])['options'])['trigger'],first)

    def test_existing_deferred_task_absorbs_new_successes_once(self):
        job=self.deferred();second=self.capture()
        self.assertEqual(self.dispatch(),[job])
        options=json.loads(self.job(job)['options']);self.assertIn(second,options['triggers']);self.assertEqual(len(options['triggers']),2)
        self.manager.update(job,status='done');self.assertEqual(self.dispatch(),[])

    def test_concurrent_dispatchers_claim_deferred_job_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        job=self.deferred()
        with patch.object(auto,'allowed',return_value=True),patch.object(self.manager,'spawn') as spawn,ThreadPoolExecutor(max_workers=4) as pool:
            claimed=list(pool.map(lambda _:auto.dispatch(app),range(4)))
        self.assertEqual(sum(len(ids) for ids in claimed),1);spawn.assert_called_once_with(job)


    def test_saved_weekly_policy_defers_and_restarts_only_on_selected_day(self):
        rule={'enabled':True,'mode':'weekly','week':[{'day':0,'start':'22:00','end':'02:00'}]}
        p=retention.preview(app,{'repo':self.repo,'keep_last':1,'window':rule},'admin')
        auto.configure(app,{'repo':self.repo,'version':1,'enabled':True,'confirm':True,'token':p['token'],
                            'window':{'enabled':False}},'admin')
        self.assertEqual(self.policy()['window']['week'],rule['week'])
        self.capture();allows=window.allows;current=['2024-01-01T23:00:00Z']
        with patch.object(window,'allows',side_effect=lambda r,t:allows(r,t,stamp(current[0]))),patch.object(self.manager,'spawn'):
            job=auto.dispatch(app)[0]
            current[0]='2024-01-02T02:00:00Z';self.manager.run_job(job)
            self.assertEqual(self.job(job)['status'],'deferred');self.manager.recover()
            current[0]='2024-01-03T23:00:00Z';self.assertEqual(auto.dispatch(app),[])
            current[0]='2024-01-08T23:00:00Z';self.assertEqual(auto.dispatch(app),[job]);self.assertEqual(auto.dispatch(app),[])
            self.assertEqual(auto.listing(app)[0]['window']['week'],rule['week'])


@unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Runtime restic requis.')
class RealWindowTests(base.RetentionFixture):
    def test_window_checked_after_queue_and_before_forget_but_not_during_started_cleanup(self):
        repo=self.manager.create_repository({'name':'Créneau isolé','target':'local','password':'synthetic-window-key-only'},'admin')['id']
        source=app.ROOT/'data/fichiers/temoin.txt'
        def capture(text):
            source.write_text(text)
            with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot','admin',{'repo':repo,'configuration':False})
            self.manager.run_job(job)
            with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'done')
        def status(job):
            with app.database() as db:return db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]
        def dispatch(opened):
            with patch.object(auto,'allowed',return_value=opened),patch.object(self.manager,'spawn'):return auto.dispatch(app)
        capture('avant activation')
        p=retention.preview(app,{'repo':repo,'keep_last':1,'window':{'enabled':True}},'admin')
        auto.configure(app,{'repo':repo,'version':0,'enabled':True,'confirm':True,'token':p['token']},'admin')
        capture('première capture en attente');capture('dernière version conservée')
        self.assertEqual(dispatch(False),[]);job=dispatch(True)[0]
        with patch.object(auto,'allowed',return_value=False):self.manager.run_job(job)
        self.assertEqual(status(job),'deferred');self.assertEqual(len(self.manager.points(repo)),3)
        self.assertEqual(dispatch(True),[job])
        with patch.object(auto,'allowed',side_effect=[True,False]):self.manager.run_job(job)
        self.assertEqual(status(job),'deferred');self.assertEqual(len(self.manager.points(repo)),3)
        self.assertEqual(dispatch(True),[job]);opened=[True];stream=self.manager.stream
        def closes_after_forget(repository,identifier,*operation):
            result=stream(repository,identifier,*operation)
            if operation[0]=='forget':opened[0]=False
            return result
        with patch.object(auto,'allowed',side_effect=lambda *a:opened[0]),patch.object(self.manager,'stream',side_effect=closes_after_forget):self.manager.run_job(job)
        self.assertEqual(status(job),'done');self.assertFalse(opened[0]);self.assertEqual(len(self.manager.points(repo)),1)
        self.assertEqual(dispatch(True),[])
        with app.database() as db:self.assertTrue(auto.read(db,repo)['enabled'])
        self.manager.checked(self.manager.repository(repo),'check','--read-data',timeout=60)
        point=self.manager.points(repo)[0]
        with patch.object(self.manager,'spawn'):restored=self.manager.submit('snapshot_restore','admin',{'repo':repo,'snapshot':point['id']})
        self.manager.run_job(restored);self.assertEqual(status(restored),'done')
        self.assertEqual((app.ROOT/'data/restaurations'/restored/'fichiers/temoin.txt').read_text(),'dernière version conservée')


    def test_weekly_day_filter_with_real_cleanup_and_exact_restore(self):
        repo=self.manager.create_repository({'name':'Semaine isolée','target':'local','password':'synthetic-weekly-key-only'},'admin')['id']
        source=app.ROOT/'data/fichiers/temoin.txt'
        def status(job):
            with app.database() as db:return db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]
        def capture(text):
            source.write_text(text)
            with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot','admin',{'repo':repo,'configuration':False})
            self.manager.run_job(job);self.assertEqual(status(job),'done')
        capture('avant activation')
        rule={'enabled':True,'mode':'weekly','week':[{'day':0,'start':'22:00','end':'02:00'},{'day':4,'start':'10:00','end':'12:00'}]}
        p=retention.preview(app,{'repo':repo,'keep_last':1,'calendar':{'timezone':'America/Cayenne'},'window':rule},'admin')
        auto.configure(app,{'repo':repo,'version':0,'enabled':True,'confirm':True,'token':p['token']},'admin')
        capture('version hebdomadaire conservée');allows=window.allows;current=['2024-01-04T02:00:00Z']
        with patch.object(window,'allows',side_effect=lambda r,t:allows(r,t,stamp(current[0]))),patch.object(self.manager,'spawn'):
            self.assertEqual(auto.dispatch(app),[]);self.assertEqual(len(self.manager.points(repo)),2)
            self.manager.recover();current[0]='2024-01-09T04:00:00Z' # Mardi UTC, continuation du lundi local.
            job=auto.dispatch(app)[0];self.manager.run_job(job);self.assertEqual(status(job),'done')
            self.assertEqual(auto.dispatch(app),[]);self.assertEqual(auto.listing(app)[0]['pending'],0)
        self.manager.checked(self.manager.repository(repo),'check','--read-data',timeout=60)
        points=self.manager.points(repo);self.assertEqual(len(points),1)
        with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot_restore','admin',{'repo':repo,'snapshot':points[0]['id']})
        self.manager.run_job(job);self.assertEqual(status(job),'done')
        self.assertEqual((app.ROOT/'data/restaurations'/job/'fichiers/temoin.txt').read_text(),'version hebdomadaire conservée')
