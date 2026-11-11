"""Aperçu civil en lecture seule, HTTP et bases temporaires uniquement."""
import http.client
import json
import threading
from datetime import datetime
from unittest.mock import patch
import test_retention as base
import maintenance_window as window

app=base.app
def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


class OpeningTests(base.RetentionFixture):
    def preview(self,rule,now,timezone='UTC'):
        return window.preview(app,{'window':{'enabled':True,**rule},'timezone':timezone},stamp(now))

    def test_current_window_gaps_overlap_union_and_clipped_horizon(self):
        result=self.preview({'mode':'weekly','week':[{'day':0,'start':'08:00','end':'09:00'},
            {'day':0,'start':'08:30','end':'10:00'},{'day':0,'start':'12:00','end':'13:00'},{'day':0,'start':'22:00','end':'02:00'}]},'2024-01-01T08:45:25Z')
        first,*_,last=result['windows']
        self.assertEqual(first,{'start':stamp('2024-01-01T08:45:25Z'),'end':stamp('2024-01-01T10:00:00Z'),'ongoing':True,'continues':False})
        self.assertEqual(len(result['windows']),4)
        self.assertEqual(result['windows'][2]['end'],stamp('2024-01-02T02:00:00Z'))
        self.assertEqual(last['start'],stamp('2024-01-08T08:00:00Z'));self.assertTrue(last['continues']);self.assertFalse(last['ongoing'])
        self.assertEqual(last['end'],result['until'])

    def test_date_closure_cuts_previous_night_and_replacement_uses_local_date(self):
        result=self.preview({'start':'22:00','end':'03:00','exceptions':[{'date':'2024-01-02','slots':[]},
            {'date':'2024-01-03','slots':[{'start':'10:00','end':'11:00'}]}]},'2024-01-02T01:30:00Z','America/Cayenne')
        self.assertEqual(result['windows'][0]['end'],stamp('2024-01-02T03:00:00Z'))
        self.assertEqual(result['windows'][1]['start'],stamp('2024-01-03T13:00:00Z'))
        self.assertEqual(result['windows'][1]['end'],stamp('2024-01-03T14:00:00Z'))

    def test_fall_back_has_two_distinct_openings_with_correct_utc_instants(self):
        result=self.preview({'mode':'weekly','week':[{'day':6,'start':'02:15','end':'02:45'}]},'2024-10-27T00:00:00Z','Europe/Paris')
        first,second=result['windows'][:2]
        self.assertEqual((first['start'],first['end']),(stamp('2024-10-27T00:15:00Z'),stamp('2024-10-27T00:45:00Z')))
        self.assertEqual((second['start'],second['end']),(stamp('2024-10-27T01:15:00Z'),stamp('2024-10-27T01:45:00Z')))

    def test_missing_hour_no_opening_and_disabled_distinguished_from_empty(self):
        result=self.preview({'mode':'weekly','week':[{'day':6,'start':'02:00','end':'03:00'}]},'2024-03-31T00:00:00Z','Europe/Paris')
        self.assertEqual(result['windows'],[]);self.assertTrue(result['enabled'])
        result=self.preview({'enabled':False},'2024-03-31T00:00:00Z')
        self.assertEqual(result['windows'],[]);self.assertFalse(result['enabled'])

    def test_invalid_inputs_are_rejected_before_projection(self):
        with patch.object(window,'allows') as evaluate:
            for body in ({'now':0},{'timezone':'Not/AZone'},{'window':{'exceptions':[{'date':'2024-02-30','slots':[]}]}}):
                with self.assertRaises(app.Problem):window.preview(app,body)
            evaluate.assert_not_called()

    def test_http_admin_csrf_and_no_storage_or_database_changes(self):
        server=app.Server(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(token='',csrf=''):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
            try:
                conn.request('POST','/api/protection/retention-openings',json.dumps({'window':{'enabled':True},'timezone':'UTC'}),{'Cookie':'nas_session='+token,'X-CSRF-Token':csrf,'Content-Type':'application/json'})
                response=conn.getresponse();return response.status,json.loads(response.read())
            finally:conn.close()
        try:
            token,csrf=app.make_session('admin')
            with app.database() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
            reader,reader_csrf=app.make_session('reader')
            self.assertEqual(request()[0],401);self.assertEqual(request(token)[0],403);self.assertEqual(request(reader,reader_csrf)[0],403)
            def inventory():
                with app.database() as db:return {name:[tuple(r) for r in db.execute('SELECT * FROM '+name)] for name in ('settings','jobs','audit','repositories','plans')}
            before=inventory()
            with patch.object(app,'protection',side_effect=AssertionError('No storage in calendar preview')):
                status,result=request(token,csrf)
            self.assertEqual(status,200);self.assertEqual(result['timezone'],'UTC');self.assertTrue(result['windows']);self.assertEqual(inventory(),before)
        finally:server.shutdown();server.server_close();thread.join(2)
