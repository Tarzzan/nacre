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

    def me(self,token=None):
        code,raw=self.request('GET','/api/me',token=token or self.token)
        self.assertEqual(code,200,raw);return json.loads(raw)

    def test_timezone_is_proposed_to_administrators_until_a_first_choice_is_saved(self):
        # Assistant en cours : il demandera le fuseau lui-même.
        self.assertIs(self.me()['timezone_unset'],False)
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
            # Installation antérieure à l'assistant : aucune préférence enregistrée.
            db.execute("DELETE FROM settings WHERE key='onboarding'")
        reader,_=app.make_session('reader')
        self.assertIs(self.me()['timezone_unset'],True)
        self.assertIs(self.me(reader)['timezone_unset'],False)
        value=self.get()
        self.assertEqual((value['timezone'],value['timezone_unset'],value['revision']),('UTC',True,0))
        with app.database() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM settings WHERE key='onboarding'").fetchone())
        # « Garder UTC » est un choix : il est enregistré et la question ne revient pas.
        code,raw=self.post('/api/control-panel/configure',{'name':'Nacre','timezone':'UTC','revision':0})
        self.assertEqual(code,200,raw)
        self.assertEqual((self.me()['timezone_unset'],self.me()['timezone'],self.get()['timezone_unset']),(False,'UTC',False))
        with app.database() as db:
            self.assertEqual(tuple(db.execute('SELECT username,action,detail FROM audit ORDER BY id DESC LIMIT 1').fetchone()),('admin','Préférences du NAS modifiées','Nacre · UTC'))
        # Un second onglet resté sur la proposition ne remplace pas ce choix.
        self.assertEqual(self.post('/api/control-panel/configure',{'name':'Nacre','timezone':'America/Cayenne','revision':0})[0],409)
        self.assertEqual(self.me()['timezone'],'UTC')
        for state,expected in [({'phase':'complete','name':'Atelier','timezone':'UTC','existing':True},True),
                               ({'phase':'complete','name':'Atelier','timezone':'Europe/Paris','existing':True},False),
                               ({'phase':'complete','name':'Atelier','timezone':'UTC','preferences_revision':1},False),
                               ({'phase':'system','name':'Atelier','timezone':'UTC','existing':False},False)]:
            with app.database() as db:onboarding.write(db,state)
            self.assertIs(self.me()['timezone_unset'],expected,state)
        self.assertEqual(self.post('/api/setup/finish',{'name':'Atelier','timezone':'UTC'})[0],200)
        self.assertIs(self.me()['timezone_unset'],False)

    def test_offered_timezones_are_geographic_and_technical_names_are_refused(self):
        self.ready();zones=self.get()['timezones']
        self.assertEqual(zones[0],'UTC');self.assertEqual(zones[1:],sorted(zones[1:]));self.assertEqual(len(zones),len(set(zones)))
        for name in ('America/Cayenne','Europe/Paris','America/Argentina/Buenos_Aires'):self.assertIn(name,zones)
        for name in zones[1:]:
            self.assertIn('/',name);self.assertFalse(name.startswith(('Etc/','posix/','right/','SystemV/')),name)
        # La détection de l'assistant interroge Docker : neutralisée ici, elle n'est pas l'objet de l'essai.
        with patch.object(onboarding.shutil,'which',return_value=None),patch.object(onboarding.os.path,'exists',return_value=False):
            code,raw=self.request('GET','/api/setup',token=self.token)
        self.assertEqual(code,200,raw);self.assertEqual(json.loads(raw)['timezones'],zones)
        before=onboarding.read(app)
        for name in ('localtime','posixrules','Factory','posix/Europe/Paris','right/Europe/Paris','SystemV/AST4',' UTC','UTC\n',''):
            for route,body in (('/api/control-panel/configure',{'name':'Atelier','timezone':name,'revision':0}),('/api/setup/finish',{'name':'Atelier','timezone':name})):
                code,raw=self.post(route,body)
                self.assertEqual((code,json.loads(raw)['error']),(400,'Fuseau horaire inconnu sur ce système.'),name)
        self.assertEqual(onboarding.read(app),before)
        # Un nom que le serveur propose est accepté tel quel.
        self.assertEqual(self.post('/api/control-panel/configure',{'name':'Atelier','timezone':zones[-1],'revision':0})[0],200)

    def test_timezone_script_is_served_with_the_console(self):
        code,raw=self.request('GET','/timezone.js')
        self.assertEqual(code,200);self.assertIn('zonePrompt',raw if isinstance(raw,str) else raw.decode())
        code,raw=self.request('GET','/')
        self.assertIn('/timezone.js',raw if isinstance(raw,str) else raw.decode())
        # Le bureau est servi avec la console et chargé avant les pages qu'il habille.
        self.assertIn('/desktop.js',raw if isinstance(raw,str) else raw.decode())
        code,raw=self.request('GET','/desktop.js')
        self.assertEqual(code,200);self.assertIn('deskShell',raw if isinstance(raw,str) else raw.decode())
        code,raw=self.request('GET','/bell.js')
        self.assertEqual(code,200);self.assertIn('refreshBell',raw if isinstance(raw,str) else raw.decode())
        code,raw=self.request('GET','/palette.js')
        self.assertEqual(code,200);self.assertIn('paletteSearch',raw if isinstance(raw,str) else raw.decode())
        code,raw=self.request('GET','/surveillance.js')
        self.assertEqual(code,200);self.assertIn('renderSurveillanceApp',raw if isinstance(raw,str) else raw.decode())
        code,raw=self.request('GET','/files.js')
        self.assertEqual(code,200);self.assertIn('renderFileManager',raw if isinstance(raw,str) else raw.decode())

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
