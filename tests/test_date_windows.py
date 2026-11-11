"""Plusieurs plages et exceptions civiles : données et horloge isolées."""
import os
import unittest
from unittest.mock import patch
import test_retention as base
import test_maintenance_window as weekly
import maintenance_window as window
import automatic_retention as auto
import retention

app=base.app
stamp=weekly.stamp

def slot(start='10:00',end='11:00'):return {'start':start,'end':end}
def exception(day,slots=None):return {'date':day,'slots':[] if slots is None else slots}


class DateWindowTests(base.RetentionFixture):
    def test_invalid_dates_duplicates_and_slots_fail_before_repository_access(self):
        bad=[{'extra':None},{'extra':[slot()]*2},{'extra':[slot('02:00','05:00')]},
             {'extra':[slot('10:00','10:00')]},{'extra':[{'start':'02:00'}]},
             {'exceptions':None},{'exceptions':[None]},{'exceptions':[{'date':'2024-01-01','slots':[],'extra':1}]},
             *({'exceptions':[exception(day)]} for day in ('2024-2-01','2024-02-30','2023-02-29','0000-01-01',None,20240101)),
             {'exceptions':[exception('2024-01-01')]*2},{'exceptions':[exception('2024-01-01',[slot()]*2)]},
             {'exceptions':[exception('2024-01-01',[slot('24:00')])]}]
        with patch.object(retention,'proposal') as proposal:
            for rule in bad:
                with self.subTest(rule=rule),self.assertRaises(app.Problem):retention.preview(app,{'repo':'fixture','keep_last':1,'window':rule},'admin')
            proposal.assert_not_called()

    def test_configuration_bounds_and_normalization(self):
        entries=[slot(f'{hour:02}:00',f'{hour:02}:30') for hour in range(24)]
        rule=window.validate(app,{'mode':'weekly','week':[dict(day=1,**e) for e in reversed(entries)],'exceptions':[exception('2024-02-29',entries)]})
        self.assertEqual(len(rule['week']),24);self.assertEqual(rule['week'][0]['start'],'00:00')
        for rule in ({'extra':entries},{'week':[dict(day=1,**e) for e in [*entries,slot('23:40','23:50')]]},
                     {'exceptions':[exception('2024-02-29',entries+[slot('23:40','23:50')])]},{'exceptions':[exception('2024-02-29')]*367}):
            with self.assertRaises(app.Problem):window.validate(app,rule)

    def test_multiple_daily_and_weekly_ranges_keep_the_gap_closed(self):
        for raw in ({'start':'08:00','end':'09:00','extra':[slot('12:00','13:00'),slot('22:00','02:00')]},
                    {'mode':'weekly','week':[dict(day=0,**e) for e in [slot('08:00','09:00'),slot('12:00','13:00'),slot('22:00','02:00')]]}):
            rule=window.validate(app,{'enabled':True,**raw})
            for value,expected in [('2024-01-01T08:00:00Z',True),('2024-01-01T09:00:00Z',False),
                ('2024-01-01T11:59:59Z',False),('2024-01-01T12:00:00Z',True),('2024-01-01T13:00:00Z',False),
                ('2024-01-01T23:00:00Z',True),('2024-01-02T01:00:00Z',True),('2024-01-02T02:00:00Z',False)]:
                self.assertEqual(window.allows(rule,'UTC',stamp(value)),expected,value)

    def test_closed_date_blocks_entire_day_and_previous_night_tail(self):
        rule=window.validate(app,{'enabled':True,'start':'22:00','end':'03:00','exceptions':[exception('2024-01-02')]})
        self.assertTrue(window.allows(rule,'UTC',stamp('2024-01-01T23:00:00Z')))
        for value in ('2024-01-02T00:00:00Z','2024-01-02T02:00:00Z','2024-01-02T23:59:59Z','2024-01-03T01:00:00Z'):
            self.assertFalse(window.allows(rule,'UTC',stamp(value)),value)
        self.assertTrue(window.allows(rule,'UTC',stamp('2024-01-03T22:00:00Z')))

    def test_replacement_uses_local_date_and_does_not_merge_recurring_slots(self):
        rule=window.validate(app,{'enabled':True,'start':'22:00','end':'04:00','exceptions':[exception('2024-01-01',[slot('10:00','11:00'),slot('15:00','16:00')])]})
        for value,expected in [('2024-01-01T03:30:00Z',False),('2024-01-01T13:00:00Z',True),
            ('2024-01-01T14:00:00Z',False),('2024-01-01T18:00:00Z',True),('2024-01-02T01:00:00Z',False),
            ('2024-01-03T01:00:00Z',True)]:self.assertEqual(window.allows(rule,'America/Cayenne',stamp(value)),expected,value)

    def test_exception_overnight_carries_unless_next_date_has_its_own_exception(self):
        raw={'enabled':True,'mode':'weekly','week':[],'exceptions':[exception('2024-12-31',[slot('22:00','03:00')])]}
        rule=window.validate(app,raw)
        self.assertTrue(window.allows(rule,'UTC',stamp('2025-01-01T02:00:00Z')))
        self.assertFalse(window.allows(rule,'UTC',stamp('2025-01-01T03:00:00Z')))
        raw['exceptions'].append(exception('2025-01-01',[slot('10:00','11:00')]))
        rule=window.validate(app,raw)
        self.assertFalse(window.allows(rule,'UTC',stamp('2025-01-01T02:00:00Z')))
        self.assertTrue(window.allows(rule,'UTC',stamp('2025-01-01T10:00:00Z')))
        self.assertFalse(window.allows(rule,'UTC',stamp('2025-12-31T23:00:00Z')))

    def test_exception_dst_gap_and_repeated_hour_follow_civil_time(self):
        rule=window.validate(app,{'enabled':True,'mode':'weekly','exceptions':[
            exception('2024-03-31',[slot('02:00','03:00')]),exception('2024-10-27',[slot('02:00','03:00')])]})
        for value in ('2024-03-31T00:59:00Z','2024-03-31T01:00:00Z'):
            self.assertFalse(window.allows(rule,'Europe/Paris',stamp(value)))
        for value in ('2024-10-27T00:30:00Z','2024-10-27T01:30:00Z'):
            self.assertTrue(window.allows(rule,'Europe/Paris',stamp(value)))

    def test_disabled_window_ignores_exceptions_and_empty_weekly_needs_an_opening(self):
        rule=window.validate(app,{'enabled':False,'mode':'weekly','exceptions':[exception('2024-01-01')]})
        self.assertTrue(window.allows(rule,'UTC',stamp('2024-01-01T12:00:00Z')))
        with self.assertRaises(app.Problem):window.validate(app,{**rule,'enabled':True})


@unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Runtime restic requis.')
class RealDateWindowTests(base.RetentionFixture):
    def test_saved_exception_defers_recovers_then_uses_second_slot_for_real_cleanup(self):
        repo=self.manager.create_repository({'name':'Exceptions isolées','target':'local','password':'synthetic-exception-key-only'},'admin')['id']
        source=app.ROOT/'data/fichiers/temoin.txt'
        def row(job):
            with app.database() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())
        def capture(text):
            source.write_text(text)
            with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot','admin',{'repo':repo,'configuration':False})
            self.manager.run_job(job);self.assertEqual(row(job)['status'],'done')
        capture('avant activation')
        rule={'enabled':True,'start':'00:00','end':'23:59','exceptions':[exception('2024-01-03',[slot('10:00','11:00'),slot('15:00','16:00')])]}
        p=retention.preview(app,{'repo':repo,'keep_last':1,'calendar':{'timezone':'America/Cayenne'},'window':rule},'admin')
        auto.configure(app,{'repo':repo,'version':0,'enabled':True,'confirm':True,'token':p['token'],'window':{'enabled':False}},'admin')
        capture('première attente');capture('dernier contenu après exception')
        allows=window.allows;current=['2024-01-03T12:00:00Z']
        with patch.object(window,'allows',side_effect=lambda r,t:allows(r,t,stamp(current[0]))),patch.object(self.manager,'spawn'):
            self.assertEqual(auto.dispatch(app),[]);self.assertEqual(len(self.manager.points(repo)),3)
            self.assertEqual(auto.listing(app)[0]['window']['exceptions'],rule['exceptions'])
            current[0]='2024-01-03T13:00:00Z';job=auto.dispatch(app)[0]
            checks=iter(['2024-01-03T13:59:59Z','2024-01-03T14:00:00Z'])
            with patch.object(window,'allows',side_effect=lambda r,t:allows(r,t,stamp(next(checks)))):self.manager.run_job(job)
            current[0]='2024-01-03T14:00:00Z'
            self.assertEqual(row(job)['status'],'deferred');self.assertEqual(len(self.manager.points(repo)),3)
            self.manager.recover();self.assertEqual(auto.dispatch(app),[])
            current[0]='2024-01-03T18:00:00Z';self.assertEqual(auto.dispatch(app),[job]);self.manager.run_job(job)
            self.assertEqual(row(job)['status'],'done');self.assertEqual(auto.dispatch(app),[]);self.assertEqual(auto.listing(app)[0]['pending'],0)
        self.manager.checked(self.manager.repository(repo),'check','--read-data',timeout=60)
        points=self.manager.points(repo);self.assertEqual(len(points),1)
        with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot_restore','admin',{'repo':repo,'snapshot':points[0]['id']})
        self.manager.run_job(job);self.assertEqual(row(job)['status'],'done')
        self.assertEqual((app.ROOT/'data/restaurations'/job/'fichiers/temoin.txt').read_text(),'dernier contenu après exception')
