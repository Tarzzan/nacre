"""Périodes calendaires, preuves locales et dépôts chiffrés jetables."""
import json
import os
import secrets
import unittest
from unittest.mock import patch
import test_retention as base
import calendar_retention as calendar
import automatic_retention as auto
import retention

app=base.app


class CalendarTests(base.RetentionFixture):
    def points(self,*dates):
        points=[self.point(i+1,time=date) for i,date in enumerate(dates)]
        for p in points:self.record(p,configuration=False)
        return points

    def select(self,points,**rule):
        return retention.selection(app,{'id':'repo'},points,1,rule)

    def ids(self,result):return {p['id'] for p in result['keep']}

    def test_invalid_calendar_is_rejected_before_repository_access(self):
        invalid=[None,[],True,{'yearly':2},{'daily':True},{'weekly':-1},{'monthly':1.5},{'daily':'2'},
                 {'monthly':1000001},{'timezone':None},{'timezone':'../UTC'},{'timezone':'Missing/Zone'}]
        with patch.object(retention,'proposal') as proposal:
            for value in invalid:
                with self.subTest(value=value),self.assertRaises(app.Problem):
                    retention.preview(app,{'repo':'repo','keep_last':1,'calendar':value},'admin')
            proposal.assert_not_called()

    def test_union_keeps_latest_per_occupied_period_with_explanations(self):
        p=self.points('2024-01-15T12:00:00Z','2024-02-01T12:00:00Z','2024-02-01T18:00:00Z',
                      '2024-02-20T12:00:00Z','2024-03-01T12:00:00Z','2024-03-01T18:00:00Z',
                      '2024-03-04T12:00:00Z','2024-03-04T18:00:00Z')
        result=self.select(p,daily=2,weekly=3,monthly=3)
        self.assertEqual(self.ids(result),{p[i]['id'] for i in (0,3,5,7)})
        self.assertEqual(len(result['remove']),4)
        latest=next(x for x in result['keep'] if x['id']==p[7]['id'])
        self.assertEqual(len(latest['reasons']),4)
        self.assertIn('Mois · 2024-01',result['keep'][-1]['reasons'])
        self.assertEqual(self.ids(self.select(p)),{p[-1]['id']})

    def test_timezone_midnight_changes_day_representative(self):
        p=self.points('2024-03-03T20:00:00Z','2024-03-04T01:00:00Z','2024-03-04T12:00:00Z')
        self.assertEqual(self.ids(self.select(p,daily=2,timezone='UTC')),{p[0]['id'],p[2]['id']})
        self.assertEqual(self.ids(self.select(p,daily=2,timezone='America/Cayenne')),{p[1]['id'],p[2]['id']})

    def test_iso_week_year_and_repeated_dst_hour_use_actual_instant(self):
        p=self.points('2020-12-28T12:00:00Z','2021-01-01T12:00:00Z','2021-01-04T12:00:00Z')
        result=self.select(p,weekly=2)
        self.assertEqual(self.ids(result),{p[1]['id'],p[2]['id']})
        self.assertIn('Semaine ISO · 2020-W53',result['keep'][-1]['reasons'])
        p=self.points('2024-11-03T05:45:00Z','2024-11-03T06:15:00Z','2024-11-04T12:00:00Z')
        self.assertEqual(self.ids(self.select(p,daily=2,timezone='America/New_York')),{p[1]['id'],p[2]['id']})

    def test_protected_points_do_not_consume_periods_and_groups_stay_separate(self):
        p=self.points('2024-01-01T12:00:00Z','2024-02-01T12:00:00Z','2024-02-02T12:00:00Z')
        imported=self.point(9,time='2024-03-01T12:00:00Z')
        partial=self.point(10,time='2024-04-01T12:00:00Z');self.record(partial,status='partial')
        second=self.point(11,time='2024-01-01T12:00:00Z',hostname='other');self.record(second,configuration=False)
        result=self.select(p+[imported,partial,second],monthly=2)
        self.assertEqual(self.ids(result),{p[0]['id'],p[2]['id'],second['id']})
        self.assertEqual({x['id'] for x in result['protected']},{imported['id'],partial['id']})
        self.assertEqual(result['groups'],2)

    def test_increasing_retention_never_removes_previously_kept_points(self):
        p=self.points('2024-01-01T12:00:00Z','2024-02-01T12:00:00Z','2024-03-01T12:00:00Z')
        previous=self.ids(self.select(p))
        for count in range(1,5):
            current=self.ids(self.select(p,daily=count,weekly=count,monthly=count))
            self.assertLessEqual(previous,current);previous=current

    def test_ambiguous_date_without_timezone_refuses_selection(self):
        p=self.points('2024-01-01T12:00:00')
        with self.assertRaises(app.Problem):self.select(p,daily=2)

    def test_legacy_policy_keeps_counts_disabled_and_activation_freezes_simulated_rule(self):
        repo='a'*24
        with app.database() as db:db.execute('INSERT INTO repositories(id,name,path,target) VALUES(?,?,?,?)',(repo,'Fixture',str(app.ROOT/'repo'),'local'))
        self.assertEqual(auto.listing(app)[0]['calendar'],calendar.defaults())
        with patch.object(self.manager,'repository',return_value={'id':repo,'name':'Fixture'}),patch.object(self.manager,'points',return_value=[]),patch.object(retention,'identity',return_value={'id':'fixture'}):
            p=retention.preview(app,{'repo':repo,'keep_last':1,'calendar':{'daily':7,'weekly':4,'monthly':12,'timezone':'America/Cayenne'}},'admin')
            auto.configure(app,{'repo':repo,'version':0,'enabled':True,'confirm':True,'token':p['token'],'calendar':{'monthly':0}},'admin')
        with app.database() as db:
            saved=auto.read(db,repo)
            self.assertEqual(saved['calendar'],p['calendar'])
            auto.disable_after_recovery(db)
            self.assertFalse(auto.read(db,repo)['enabled'])
            self.assertEqual(auto.read(db,repo)['calendar'],p['calendar'])


@unittest.skipUnless(os.environ.get('NAS_RESTIC_BIN'),'Runtime restic requis.')
class RealCalendarTests(base.RetentionFixture):
    def test_manual_and_automatic_calendar_preserve_historical_month_and_restore(self):
        repo=self.manager.create_repository({'name':'Calendrier isolé','target':'local','password':'synthetic-calendar-key-only'},'admin')['id']
        repository=self.manager.repository(repo);source=app.ROOT/'data/fichiers/temoin.txt'
        snapshot_ids=[]
        # Dates synthétiques écrites dans un vrai dépôt, provenance Nacre enregistrée.
        for day,content in [('2024-01-15 12:00:00','janvier conservé'),('2024-02-01 12:00:00','février ancien'),('2024-02-20 12:00:00','février conservé'),('2024-03-01 12:00:00','mars conservé')]:
            source.write_text(content)
            output=self.manager.checked(repository,'backup','--json','--tag','nacre','--time',day,str(source),timeout=60)
            summary=json.loads(output.splitlines()[-1]);identifier=summary['snapshot_id'];snapshot_ids.append(identifier)
            self.record({'id':identifier},repo=repo,configuration=False)
        p=retention.preview(app,{'repo':repo,'keep_last':1,'calendar':{'monthly':3,'timezone':'UTC'}},'admin')
        self.assertEqual({x['id'] for x in p['keep']},{snapshot_ids[i] for i in (0,2,3)})
        with patch.object(self.manager,'spawn'):job=retention.submit(app,{'token':p['token'],'confirm':True},'admin')['job']
        self.manager.run_job(job)
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0],'done')
        p=retention.preview(app,{'repo':repo,'keep_last':1,'calendar':{'monthly':3,'timezone':'UTC'}},'admin')
        auto.configure(app,{'repo':repo,'version':p['policy_version'],'enabled':True,'confirm':True,'token':p['token']},'admin')
        source.write_text('nouvelle capture conservée')
        with patch.object(self.manager,'spawn'):job=self.manager.submit('snapshot','admin',{'repo':repo,'configuration':False})
        self.manager.run_job(job)
        with patch.object(self.manager,'spawn'):jobs=auto.dispatch(app)
        self.assertEqual(len(jobs),1);self.manager.run_job(jobs[0])
        with app.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(jobs[0],)).fetchone()[0],'done')
        remaining={x['id'] for x in self.manager.points(repo)}
        self.assertNotIn(snapshot_ids[0],remaining);self.assertIn(snapshot_ids[2],remaining);self.assertIn(snapshot_ids[3],remaining)
        self.assertEqual(len(remaining),3)
        self.manager.checked(repository,'check','--read-data',timeout=60)
        restored=app.ROOT/'restore-month'
        self.manager.checked(repository,'restore',snapshot_ids[2],'--target',str(restored),timeout=60)
        self.assertEqual((restored/source.relative_to('/')).read_text(),'février conservé')
