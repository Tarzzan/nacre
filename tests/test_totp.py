"""Double authentification : code à usage unique à la connexion, activation par la personne, codes de secours. Vrai serveur."""
import base64
import json
import time
import unittest

import test_spaces
import spaces
import totp

app = test_spaces.app
PASSWORD = 'mot-de-passe-de-banc'


class TotpTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'audit'))

    def person(self, name='camille', role='member'):
        self.people(**{name: role})
        with app.database() as db:
            salt = '22' * 16
            db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, app.password_hash(PASSWORD, salt), name))

    def login(self, name='camille', code=None, password=PASSWORD):
        self.http.attempts = []  # La limite de tentatives par minute a ses propres essais.
        body = {'username': name, 'password': password}
        if code is not None:
            body['code'] = code
        status, data = self.request('POST', '/api/login', body)
        return status, json.loads(data)

    def secret(self, name='camille'):
        with app.database() as db:
            return totp.state(db, name)

    def now(self, name='camille', shift=0):
        return totp.code(self.secret(name).get('secret') or self.secret(name)['pending'], int(time.time() // 30) + shift)

    def enable(self, name='camille'):
        status, made = self.post(name, '/api/account/totp/start', {'password': PASSWORD})
        self.assertEqual(status, 200, made)
        status, done = self.post(name, '/api/account/totp/confirm', {'code': self.now(name)})
        self.assertEqual(status, 200, done)
        return made, done['recovery']

    def test_rfc_vectors_window_and_replay(self):
        key = base64.b32encode(b'12345678901234567890').decode()
        for moment, expected in ((59, '287082'), (1111111109, '081804'), (1111111111, '050471'), (1234567890, '005924'), (2000000000, '279037'), (20000000000, '353130')):
            self.assertEqual(totp.code(key, moment // 30), expected)
        self.assertEqual(totp.match(key, '287082', 59), 1)
        self.assertEqual(totp.match(key, '287 082', 89), 1)      # période précédente, espace toléré
        self.assertEqual(totp.match(key, '287082', 29), 1)       # période suivante
        self.assertIsNone(totp.match(key, '287082', 120))        # trop tard
        self.assertIsNone(totp.match(key, '287082', 59, last=1))  # déjà utilisé
        for bad in ('28708', '2870822', 'abcdef', '', None, 287082):
            self.assertIsNone(totp.match(key, bad, 59), bad)
        self.assertRegex(totp.uri(key, 'camille'), r'^otpauth://totp/Nacre:camille\?secret=[A-Z2-7]{32}&issuer=Nacre&algorithm=SHA1&digits=6&period=30$')
        codes = totp.recovery_codes()
        self.assertEqual((len(codes), len(set(codes))), (10, 10)); self.assertRegex(codes[0], r'^[a-z2-9]{4}-[a-z2-9]{4}$')

    def test_person_enables_it_and_login_then_requires_a_fresh_code(self):
        self.person()
        self.assertEqual(self.get('camille', '/api/account')[1]['totp'], {'enabled': False, 'recovery': 0})
        self.assertEqual(self.login()[0], 200)
        # Activer : le mot de passe est redemandé, et rien n'est actif avant un premier code juste.
        self.assertEqual(self.post('camille', '/api/account/totp/start', {'password': 'faux'})[0], 403)
        status, made = self.post('camille', '/api/account/totp/start', {'password': PASSWORD})
        self.assertEqual(status, 200)
        self.assertRegex(made['secret'], r'^[A-Z2-7]{32}$'); self.assertIn(made['secret'], made['uri'])
        self.assertEqual(self.login()[0], 200)
        self.assertEqual(self.post('camille', '/api/account/totp/confirm', {'code': '000000'})[0], 403)
        self.assertEqual(self.post('camille', '/api/account/totp/confirm', {})[0], 403)
        other = app.make_session('camille')
        status, done = self.post('camille', '/api/account/totp/confirm', {'code': self.now()})
        self.assertEqual((status, len(done['recovery'])), (200, 10))
        self.assertEqual(self.get('camille', '/api/account')[1]['totp'], {'enabled': True, 'recovery': 10})
        # Les autres sessions du compte sont fermées ; les codes de secours ne sont gardés que sous forme d'empreinte.
        self.assertEqual(self.request('GET', '/api/me', token=other[0])[0], 401)
        with app.database() as db:
            stored = json.dumps([tuple(r) for r in db.execute('SELECT value FROM settings')])
        self.assertNotIn(done['recovery'][0], stored)
        self.assertEqual(self.post('camille', '/api/account/totp/start', {'password': PASSWORD})[0], 409)
        self.assertEqual(self.post('camille', '/api/account/totp/confirm', {'code': self.now()})[0], 409)
        # Connexion : le code est demandé après le mot de passe, jamais avant.
        status, data = self.login(password='faux')
        self.assertEqual((status, data.get('totp')), (401, None))
        status, data = self.login()
        self.assertEqual((status, data['totp']), (401, True)); self.assertIn('Saisissez le code', data['error'])
        self.assertEqual(self.login(code='')[1]['totp'], True)
        status, data = self.login(code='000000')
        self.assertEqual((status, data['totp']), (401, True)); self.assertIn('refusé', data['error'])
        # Le code de l'activation ne ressert pas ; celui de la période suivante passe, une seule fois.
        self.assertEqual(self.login(code=self.now())[0], 401)
        fresh = self.now(shift=1)
        status, data = self.login(code=fresh)
        self.assertEqual((status, data['name'], data['role']), (200, 'camille', 'member'))
        self.assertEqual(self.login(code=fresh)[0], 401)
        self.assertIn(('camille', 'Double authentification activée', ''), self.audit())
        self.assertIn(('camille', 'Code de double authentification refusé', ''), self.audit())

    def test_recovery_codes_work_once_and_disabling_needs_password_and_code(self):
        self.person()
        _, codes = self.enable()
        self.assertEqual(self.login(code=codes[0].upper())[0], 200)
        self.assertEqual(self.login(code=codes[0])[0], 401)
        self.assertEqual(self.get('camille', '/api/account')[1]['totp'], {'enabled': True, 'recovery': 9})
        self.assertIn(('camille', 'Code de secours utilisé', '9 restant(s)'), self.audit())
        self.sessions['camille'] = app.make_session('camille')
        self.assertEqual(self.post('camille', '/api/account/totp/disable', {'password': 'faux', 'code': codes[1]})[0], 403)
        self.assertEqual(self.post('camille', '/api/account/totp/disable', {'password': PASSWORD, 'code': '000000'})[0], 403)
        self.assertEqual(self.post('camille', '/api/account/totp/disable', {'password': PASSWORD, 'code': codes[1]})[0], 200)
        self.assertEqual(self.get('camille', '/api/account')[1]['totp'], {'enabled': False, 'recovery': 0})
        self.assertEqual(self.login()[0], 200)
        self.assertEqual(self.post('camille', '/api/account/totp/disable', {'password': PASSWORD, 'code': codes[2]})[0], 409)

    def test_activation_expires_and_every_role_may_enable_it(self):
        self.person('lecteur', 'viewer')
        self.assertEqual(self.post('lecteur', '/api/account/totp/start', {'password': PASSWORD})[0], 200)
        with app.database() as db:
            doc = totp.state(db, 'lecteur'); doc['pending_at'] = time.time() - 1000; totp.save(db, 'lecteur', doc)
        self.assertEqual(self.post('lecteur', '/api/account/totp/confirm', {'code': self.now('lecteur')})[0], 409)
        self.enable('lecteur')
        self.assertEqual(self.login('lecteur')[1]['totp'], True)
        self.assertEqual(self.post('lecteur', '/api/account/totp/inconnu', {})[0], 403)
        self.assertEqual(self.post('admin', '/api/account/totp/inconnu', {})[0], 404)

    def test_administrator_removes_it_for_someone_else_only(self):
        self.person()
        self.enable()
        view = {p['name']: p['totp'] for p in self.get('admin', '/api/spaces')[1]['people']}
        self.assertEqual(view, {'admin': False, 'camille': True})
        self.assertEqual(self.post('camille', '/api/spaces/totp-reset', {'name': 'camille'})[0], 403)
        self.assertEqual(self.post('admin', '/api/spaces/totp-reset', {'name': 'admin'})[0], 409)
        self.assertEqual(self.post('admin', '/api/spaces/totp-reset', {'name': 'absente'})[0], 404)
        self.assertEqual(self.post('admin', '/api/spaces/totp-reset', {'name': 'camille'})[0], 200)
        self.assertEqual(self.get('camille', '/api/me')[0], 401)
        self.assertEqual(self.login()[0], 200)
        self.assertEqual(self.audit()[-2], ('admin', 'Double authentification retirée par un administrateur', 'camille'))
        self.assertEqual(self.post('admin', '/api/spaces/totp-reset', {'name': 'camille'})[0], 409)


if __name__ == '__main__':
    unittest.main()
