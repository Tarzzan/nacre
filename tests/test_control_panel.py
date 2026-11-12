"""Panneau et révocation sur HTTP/SQLite temporaires, sans service NAS."""
import json
import time
import unittest
from unittest.mock import patch
import test_onboarding as base
import control_panel
import onboarding

app=base.server


class ControlPanelTests(unittest.TestCase):
    setUp=base.OnboardingTests.setUp
    tearDown=base.OnboardingTests.tearDown
    request=base.OnboardingTests.request
    post=base.OnboardingTests.post

    def ready(self):
        with app.database() as db:
            onboarding.write(db,{'phase':'complete','name':'Atelier','timezone':'UTC','existing':True})
    def get(self):
        code,raw=self.request('GET','/api/control-panel',token=self.token)
        self.assertEqual(code,200,raw);return json.loads(raw)
    def test_administrator_csrf_and_origin_required(self):
        self.assertEqual(self.request('GET','/api/control-panel')[0],401)
        with app.database() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token,csrf=app.make_session('reader')
        self.assertEqual(self.request('GET','/api/control-panel',token=token)[0],403)
        for route in ('/api/control-panel/configure','/api/control-panel/revoke'):
            self.assertEqual(self.request('POST',route,{},token,csrf)[0],403)
            self.assertEqual(self.request('POST',route,{},self.token)[0],403)
            self.assertEqual(self.request('POST',route,{},self.token,self.csrf,'https://other.invalid')[0],403)

    def test_counts_ignore_expired_disabled_and_exclude_secrets(self):
        self.ready();other,_=app.make_session('admin')
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role,active) VALUES('disabled','private-salt','private-hash','viewer',0)")
            db.execute("INSERT INTO sessions VALUES('expired','admin','private-csrf',0)")
            db.execute("INSERT INTO sessions VALUES('hidden','disabled','private-csrf',?)",(time.time()+600,))
        with patch.object(app,'compose') as compose,patch.object(app,'video_json') as video:
            value=self.get()
        compose.assert_not_called();video.assert_not_called()
        self.assertEqual([a['valid_sessions'] for a in value['accounts']],[2,0])
        self.assertTrue(value['accounts'][0]['current'])
        for secret in (self.token,other,self.csrf,'private-salt','private-hash','private-csrf','token','expires'):
            self.assertNotIn(secret,json.dumps(value))

    def test_preferences_persist_without_changing_plans_accounts_or_sessions(self):
        self.ready()
        with app.database() as db:
            db.execute("INSERT INTO plans(id,name,enabled,config) VALUES('fixture','Plan',0,?)",(json.dumps({'timezone':'Europe/Paris'}),))
            before={table:[tuple(r) for r in db.execute('SELECT * FROM '+table)] for table in ('users','sessions','plans')}
        with patch.object(app,'compose') as compose:
            code,raw=self.post('/api/control-panel/configure',{'name':' Mon NAS ','timezone':'America/Cayenne','revision':0})
        self.assertEqual(code,200,raw);compose.assert_not_called()
        app.initialize();value=self.get()
        self.assertEqual((value['name'],value['timezone'],value['revision']),('Mon NAS','America/Cayenne',1))
        with app.database() as db:
            for table,rows in before.items():self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM '+table)],rows)
            self.assertEqual(db.execute('SELECT action FROM audit ORDER BY id DESC LIMIT 1').fetchone()[0],'Préférences du NAS modifiées')
        _,raw=self.request('GET','/api/me',token=self.token)
        self.assertEqual(json.loads(raw)['timezone'],'America/Cayenne')

    def test_invalid_preferences_and_unfinished_setup_do_not_mutate(self):
        body={'name':'Atelier','timezone':'UTC','revision':0}
        self.assertEqual(self.post('/api/control-panel/configure',body)[0],409)
        self.ready();before=onboarding.read(app)
        for change,expected in [({'name':''},400),({'name':'a\nb'},400),({'timezone':'../UTC'},400),({'timezone':'Invalid/Zone'},400),({'revision':True},409),({'revision':-1},409),({'revision':None},409)]:
            self.assertEqual(self.post('/api/control-panel/configure',{**body,**change})[0],expected)
            self.assertEqual(onboarding.read(app),before)

    def test_two_tabs_and_legacy_setup_changes_do_not_overwrite_new_preferences(self):
        self.ready();body={'name':'Premier','timezone':'UTC','revision':0}
        self.assertEqual(self.post('/api/control-panel/configure',body)[0],200)
        self.assertEqual(self.post('/api/control-panel/configure',{**body,'name':'Ancien onglet'})[0],409)
        self.assertEqual(onboarding.read(app)['name'],'Premier')
        self.assertEqual(self.post('/api/setup/finish',{'name':'Assistant','timezone':'Europe/Paris'})[0],200)
        self.assertEqual(self.post('/api/control-panel/configure',{**body,'revision':1})[0],409)
        self.assertEqual(self.get()['revision'],2)

    def test_revocation_targets_one_account_and_preserves_current_session(self):
        self.ready();other,_=app.make_session('admin')
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','salt','unused','viewer')")
            before=[tuple(r) for r in db.execute('SELECT * FROM users')]
        reader,_=app.make_session('reader')
        code,raw=self.post('/api/control-panel/revoke',{'name':'reader','confirm':True})
        self.assertEqual(code,200);self.assertEqual(json.loads(raw)['revoked'],1)
        self.assertEqual(self.request('GET','/api/me',token=reader)[0],401)
        self.assertEqual(self.request('GET','/api/me',token=other)[0],200)
        code,raw=self.post('/api/control-panel/revoke',{'name':'admin','confirm':True})
        self.assertEqual(json.loads(raw)['revoked'],1)
        self.assertEqual(self.request('GET','/api/me',token=other)[0],401)
        self.assertEqual(self.request('GET','/api/me',token=self.token)[0],200)
        self.assertEqual(self.get()['accounts'][0]['valid_sessions'],1)
        with app.database() as db:self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM users')],before)
        code,raw=self.post('/api/control-panel/revoke',{'name':'admin','confirm':True})
        self.assertEqual(json.loads(raw)['revoked'],0)

    def test_actor_is_revalidated_under_transaction(self):
        self.ready()
        with app.database() as db:
            session=dict(db.execute('SELECT * FROM sessions WHERE token=?',(app.digest(self.token),)).fetchone())
            db.execute('DELETE FROM sessions')
        for action,body in [(control_panel.configure,{'name':'Changed','timezone':'UTC','revision':0}),(control_panel.revoke,{'name':'admin','confirm':True})]:
            with self.assertRaises(app.Problem) as error:action(app,body,session)
            self.assertEqual(error.exception.status,403)
        self.assertEqual(onboarding.read(app)['name'],'Atelier')

    def test_unknown_target_and_missing_confirmation_preserve_sessions(self):
        self.ready();other,_=app.make_session('admin')
        for body,expected in [({'name':'absent','confirm':True},404),({'name':'admin'},400),({'name':'admin','confirm':1},400),({'name':['admin'],'confirm':True},400)]:
            self.assertEqual(self.post('/api/control-panel/revoke',body)[0],expected)
        self.assertEqual(self.request('GET','/api/me',token=other)[0],200)
