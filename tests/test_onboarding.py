"""Assistant sur bases et HTTP temporaires ; aucun service ou disque modifié."""
import json
import secrets
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import test_console
server = test_console.server
import onboarding
import schema


class OnboardingTests(unittest.TestCase):
    request = test_console.ConsoleSecurityTests.request

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = server.ROOT, server.STATE, server.DB
        server.ROOT = Path(self.temp.name)
        server.STATE = server.ROOT/'state/console'
        server.DB = server.STATE/'console.db'
        server.initialize()
        self.original = (server.STATE/'acces.txt').read_text().split('Mot de passe : ')[1].strip()
        self.token, self.csrf = server.make_session('admin')
        self.http = server.Server(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.password = secrets.token_urlsafe(24)

    def tearDown(self):
        self.http.shutdown(); self.http.server_close()
        server.ROOT, server.STATE, server.DB = self.previous
        self.temp.cleanup()

    def post(self, path, value):
        return self.request('POST', path, value, self.token, self.csrf)

    def secure(self):
        status, value = self.post('/api/setup/account', {'password': self.password, 'confirmation': self.password})
        self.assertEqual(status, 200, value)
        self.csrf = json.loads(value)['csrf']

    def test_first_run_requires_setup_and_authorization(self):
        status, value = self.request('GET', '/api/me', token=self.token)
        self.assertTrue(json.loads(value)['setup_required'])
        self.assertEqual(self.request('GET', '/api/setup')[0], 401)
        with server.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token, csrf = server.make_session('reader')
        self.assertEqual(self.request('GET','/api/setup',token=token)[0],403)
        self.assertEqual(self.request('POST','/api/setup/finish',{},token,csrf)[0],403)
        self.assertEqual(self.request('POST','/api/setup/account',{},self.token)[0],403)
        self.assertEqual(self.request('POST','/api/setup/account',{},self.token,self.csrf,origin='https://untrusted.invalid')[0],403)
        self.assertEqual(self.post('/api/setup/finish',{'name':'Atelier','timezone':'UTC'})[0],409)

    def test_password_rotation_revokes_other_sessions_and_tickets_and_survives_restart(self):
        other, _ = server.make_session('admin')
        with server.database() as db:
            db.execute('INSERT INTO tickets VALUES(?,?)', ('synthetic',9999999999))
        old_csrf = self.csrf
        self.secure()
        self.assertNotEqual(self.csrf, old_csrf)
        self.assertEqual(self.request('GET','/api/me',token=other)[0],401)
        with server.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tickets').fetchone()[0],0)
        self.assertNotIn(self.password,(server.STATE/'acces.txt').read_text())
        self.assertNotIn(self.original,(server.STATE/'acces.txt').read_text())
        for password, expected in [(self.original,401),(self.password,200)]:
            self.assertEqual(self.request('POST','/api/login',{'username':'admin','password':password})[0],expected)
        self.assertEqual(self.request('POST','/api/setup/finish',{'name':'Atelier','timezone':'UTC'},self.token,old_csrf)[0],403)
        server.initialize()
        self.assertEqual(onboarding.read(server)['phase'],'system')
        self.assertEqual(self.post('/api/setup/account',{'password':self.password,'confirmation':self.password})[0],409)

    def test_invalid_password_does_not_advance_or_invalidate_session(self):
        for password, confirmation in [('short','short'),(self.password,'different'),(None,None),(self.original,self.original)]:
            self.assertEqual(self.post('/api/setup/account',{'password':password,'confirmation':confirmation})[0],400)
            self.assertEqual(onboarding.read(server)['phase'],'account')
        self.assertEqual(self.request('GET','/api/me',token=self.token)[0],200)

    def test_finish_persists_preferences_without_creating_plans_or_repositories(self):
        self.secure()
        for name, timezone in [('', 'UTC'),('Atelier','../UTC'),('Atelier','Invalid/Zone'),('line\nbreak','UTC')]:
            self.assertEqual(self.post('/api/setup/finish',{'name':name,'timezone':timezone})[0],400)
        status, _ = self.post('/api/setup/finish',{'name':'Atelier','timezone':'Europe/Paris'})
        self.assertEqual(status,200)
        server.initialize()
        _, value = self.request('GET','/api/me',token=self.token)
        account = json.loads(value)
        self.assertFalse(account['setup_required']); self.assertEqual(account['nas_name'],'Atelier')
        self.assertEqual(account['timezone'],'Europe/Paris')
        with server.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM repositories').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM plans').fetchone()[0],0)

    def test_missing_components_are_reported_without_starting_services(self):
        with patch.object(onboarding.shutil,'which',return_value=None), patch.object(onboarding.os.path,'exists',return_value=False), patch.object(onboarding,'probe') as probe:
            code, raw = self.request('GET','/api/setup',token=self.token)
        self.assertEqual(code,200,raw); probe.assert_not_called()
        data = json.loads(raw)
        capabilities = {c['id']:c for c in data['capabilities']}
        self.assertFalse(capabilities['docker']['ready'])
        self.assertFalse(capabilities['native']['ready'])
        self.assertNotIn(self.original,raw.decode()); self.assertNotIn('salt',raw.decode())
        with patch.object(server,'compose',side_effect=FileNotFoundError):
            code, raw = self.request('GET','/api/overview',token=self.token)
        self.assertEqual(code,200,raw)
        self.assertFalse(json.loads(raw)['services_available'])

    def test_upgrade_v1_preserves_accounts_and_does_not_force_setup(self):
        with server.database() as db:
            before = tuple(db.execute("SELECT salt,hash FROM users WHERE name='admin'").fetchone())
            db.execute('DROP TABLE settings'); db.execute('PRAGMA user_version=1')
        server.initialize()
        self.assertTrue(onboarding.read(server)['existing'])
        self.assertEqual(onboarding.read(server)['phase'],'complete')
        with server.database() as db:
            self.assertEqual(tuple(db.execute("SELECT salt,hash FROM users WHERE name='admin'").fetchone()),before)
        checkpoint = schema.status(server.DB)['checkpoints'][-1]
        self.assertEqual((checkpoint['source_version'],checkpoint['target_version']),(1,2))
        self.assertEqual(self.post('/api/setup/account',{'password':self.password,'confirmation':self.password})[0],409)
        self.assertEqual(self.post('/api/setup/finish',{'name':'Existant','timezone':'UTC'})[0],200)
        with server.database() as db:
            self.assertEqual(tuple(db.execute("SELECT salt,hash FROM users WHERE name='admin'").fetchone()),before)
