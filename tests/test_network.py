"""Accès par le réseau : second point d'écoute en HTTPS, noms déclarés, double authentification pour les administrateurs.

Vrai serveur, vrai TLS sur la boucle locale, certificat produit par OpenSSL. Rien ne sort de la machine.
"""
import http.client
import json
import shutil
import socket
import ssl
import time
import unittest
import unittest.mock

import test_spaces
import test_totp
import network
import totp

app = test_spaces.app
PASSWORD = test_totp.PASSWORD


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL absent de cette machine')
class NetworkTests(unittest.TestCase):
    request = test_spaces.SpaceTests.request
    people, get, post, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'audit'))
    person = test_totp.TotpTests.person

    def setUp(self):
        test_spaces.SpaceTests.setUp(self)
        self.port = free_port()
        # En service, un changement de réglage relance l'écoute un instant après la réponse ; ici, chaque essai la relance lui-même.
        deferred = unittest.mock.patch.object(network, 'later', lambda app: None)
        deferred.start(); self.addCleanup(deferred.stop)

    def tearDown(self):
        network.stop()
        test_spaces.SpaceTests.tearDown(self)

    def open(self, hosts=('localhost', '127.0.0.1'), policy='admins'):
        status, data = self.post('admin', '/api/network/configure', {'enabled': True, 'confirm': True, 'port': self.port, 'hosts': list(hosts), 'require_totp': policy})
        self.assertEqual(status, 200, data)
        network.apply(app, '127.0.0.1')
        self.assertIsNotNone(network.LISTENER['server'], network.LISTENER['error'])

    def secure(self, method, path, body=None, cookie=None, host='localhost', origin=None, csrf=None):
        """Requête par le point d'écoute réseau, certificat vérifié : (code, en-têtes, contenu)."""
        context = ssl.create_default_context(cafile=str(network.folder(app) / 'cert.pem'))
        conn = http.client.HTTPSConnection('localhost', self.port, timeout=6, context=context)
        headers = {'Content-Type': 'application/json', 'Host': f'{host}:{self.port}' if host else ''}
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        if csrf:
            headers['X-CSRF-Token'] = csrf
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def enable_totp(self, name):
        if name == 'admin':
            with app.database() as db:
                salt = '44' * 16
                db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, app.password_hash(PASSWORD, salt), name))
        self.assertEqual(self.post(name, '/api/account/totp/start', {'password': PASSWORD})[0], 200)
        with app.database() as db:
            pending = totp.state(db, name)['pending']
        self.assertEqual(self.post(name, '/api/account/totp/confirm', {'code': totp.code(pending, int(time.time() // 30))})[0], 200)
        return lambda: totp.code(pending, int(time.time() // 30) + 1)

    def test_closed_by_default_and_opening_needs_names_confirmation_and_a_free_port(self):
        self.people()
        status, state = self.get('admin', '/api/network')
        self.assertEqual((status, state['enabled'], state['running'], state['hosts'], state['port'], state['certificate'], state['require_totp']), (200, False, False, [], 8443, None, 'admins'))
        good = {'enabled': True, 'confirm': True, 'port': self.port, 'hosts': ['nas.local'], 'require_totp': 'admins'}
        for change in ({'confirm': False}, {'hosts': []}, {'hosts': ['nas local']}, {'hosts': ['https://nas.local']}, {'hosts': ['nas.local:8443']}, {'hosts': ['a..b']}, {'hosts': 'nas.local'},
                       {'hosts': ['h%d.local' % i for i in range(9)]}, {'port': 80}, {'port': 70000}, {'port': '8443'}, {'require_totp': 'none'}, {'enabled': 'oui'}):
            status, data = self.post('admin', '/api/network/configure', {**good, **change})
            self.assertEqual(status, 400, (change, data))
        with socket.socket() as taken:
            taken.bind(('0.0.0.0', self.port)); taken.listen(1)
            self.assertEqual(self.post('admin', '/api/network/configure', good)[0], 409)
        self.assertIsNone(network.describe(app))
        self.assertEqual(self.get('admin', '/api/network')[1]['enabled'], False)
        # Un compte qui n'administre pas ne lit ni ne règle l'accès réseau.
        self.people(camille='member', lecteur='viewer')
        for who in ('camille', 'lecteur'):
            self.assertEqual(self.get(who, '/api/network')[0], 403)
            self.assertEqual(self.post(who, '/api/network/configure', good)[0], 403)

    def test_console_answers_in_https_under_declared_names_only(self):
        self.person()
        self.open(hosts=('LocalHost', '127.0.0.1', 'localhost'))
        state = self.get('admin', '/api/network')[1]
        self.assertEqual((state['enabled'], state['running'], state['hosts'], state['urls']), (True, True, ['localhost', '127.0.0.1'], [f'https://localhost:{self.port}/', f'https://127.0.0.1:{self.port}/']))
        self.assertRegex(state['certificate']['fingerprint'], r'^([0-9A-F]{2}:){31}[0-9A-F]{2}$')
        self.assertEqual(sorted(state['certificate']['names']), ['127.0.0.1', 'localhost'])
        self.assertGreater(state['certificate']['expires'], time.time() + 800 * 86400)
        self.assertEqual((network.folder(app) / 'key.pem').stat().st_mode & 0o777, 0o600)
        status, headers, page = self.secure('GET', '/')
        self.assertEqual(status, 200); self.assertIn(b'<title>Nacre', page)
        # Un nom non déclaré est refusé, même avec un certificat valable ; le nom seul, sans port, passe (cas d'un relais).
        self.assertEqual(self.secure('GET', '/', host='autre.exemple')[0], 403)
        context = ssl.create_default_context(cafile=str(network.folder(app) / 'cert.pem'))
        conn = http.client.HTTPSConnection('localhost', self.port, timeout=6, context=context)
        conn.putrequest('GET', '/', skip_host=True); conn.putheader('Host', 'localhost'); conn.endheaders()
        self.assertEqual(conn.getresponse().status, 200); conn.close()
        # Le lien de connexion locale ne vaut pas sur le réseau, et le port réseau ne parle pas en clair.
        ticket = 'x' * 43
        self.assertEqual(self.secure('GET', '/connexion-locale?ticket=' + ticket)[0], 404)
        plain = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        with self.assertRaises((http.client.HTTPException, OSError)):
            plain.request('GET', '/'); plain.getresponse()
        plain.close()
        # Le point d'écoute local, lui, ne reconnaît toujours que la machine.
        self.assertEqual(self.request('GET', '/', host='localhost:%d' % self.port)[0], 403)
        # Membre sans double authentification : admis par défaut ; session marquée Secure ; origine du réseau exigée pour écrire.
        status, headers, data = self.secure('POST', '/api/login', {'username': 'camille', 'password': PASSWORD}, origin=f'https://localhost:{self.port}')
        self.assertEqual(status, 200, data)
        cookie = headers['Set-Cookie']
        self.assertRegex(cookie, r'^nas_session=[A-Za-z0-9_-]{43}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800; Secure$')
        session, csrf = cookie.split(';')[0], json.loads(data)['csrf']
        self.assertEqual(self.secure('GET', '/api/areas', cookie=session)[0], 200)
        self.assertEqual(self.secure('POST', '/api/desk', {}, cookie=session, csrf=csrf, origin='http://127.0.0.1:%d' % self.http.server_port)[0], 403)
        self.assertEqual(self.secure('POST', '/api/login', {'username': 'camille', 'password': PASSWORD}, origin='https://ailleurs.exemple')[0], 403)
        self.assertIn(('camille', 'Connexion', 'par le réseau, depuis 127.0.0.1'), self.audit())
        self.assertIn(('admin', 'Accès réseau ouvert', f'port {self.port} · localhost, 127.0.0.1'), self.audit())

    def test_administrator_needs_double_authentication_over_the_network(self):
        self.person()
        self.open()
        # Sans double authentification, l'administrateur est refusé par le réseau une fois son mot de passe reconnu, pas avant.
        with app.database() as db:
            salt = '44' * 16
            db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, app.password_hash(PASSWORD, salt), 'admin'))
        status, _, data = self.secure('POST', '/api/login', {'username': 'admin', 'password': 'faux'})
        self.assertEqual((status, 'double' in json.loads(data)['error']), (401, False))
        status, _, data = self.secure('POST', '/api/login', {'username': 'admin', 'password': PASSWORD})
        self.assertEqual(status, 403); self.assertIn('double authentification', json.loads(data)['error'])
        self.assertIn(('admin', 'Connexion par le réseau refusée', 'double authentification absente'), self.audit())
        self.assertEqual(self.request('POST', '/api/login', {'username': 'admin', 'password': PASSWORD})[0], 200)
        fresh = self.enable_totp('admin')
        self.assertEqual(json.loads(self.secure('POST', '/api/login', {'username': 'admin', 'password': PASSWORD})[2])['totp'], True)
        status, headers, data = self.secure('POST', '/api/login', {'username': 'admin', 'password': PASSWORD, 'code': fresh()})
        self.assertEqual((status, json.loads(data)['role']), (200, 'admin'))
        self.assertEqual(self.get('admin', '/api/network')[1]['my_totp'], True)
        # « Pour tout le monde » : un membre sans double authentification est refusé à son tour.
        self.assertEqual(self.post('admin', '/api/network/configure', {'enabled': True, 'confirm': True, 'port': self.port, 'hosts': ['localhost', '127.0.0.1'], 'require_totp': 'everyone'})[0], 200)
        network.apply(app, '127.0.0.1')
        self.assertEqual(self.secure('POST', '/api/login', {'username': 'camille', 'password': PASSWORD})[0], 403)

    def test_a_stalled_client_blocks_nobody_and_attempts_are_limited_per_address(self):
        self.person()
        self.open()
        # Un client qui se connecte sans jamais négocier ne retient pas l'écoute.
        stalled = [socket.create_connection(('127.0.0.1', self.port), timeout=5) for _ in range(5)]
        try:
            started = time.time()
            self.assertEqual(self.secure('GET', '/')[0], 200)
            self.assertLess(time.time() - started, 3)
        finally:
            for sock in stalled:
                sock.close()
        codes = [self.secure('POST', '/api/login', {'username': 'camille', 'password': 'faux'})[0] for _ in range(9)]
        self.assertEqual((codes[0], codes[7], codes[8]), (401, 401, 429))
        server = network.LISTENER['server']
        self.assertTrue(server.login_limit('192.0.2.7'))   # une autre adresse n'est pas pénalisée
        self.assertEqual(self.request('POST', '/api/login', {'username': 'camille', 'password': 'faux'})[0], 401)

    def test_certificate_is_remade_or_provided_and_closing_frees_the_port(self):
        self.people()
        self.open()
        first = network.describe(app)['fingerprint']
        self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'regenerate'})[0], 200)
        second = network.describe(app)['fingerprint']
        self.assertNotEqual(first, second)
        # Certificat fourni : vérifié avec sa clé avant de remplacer quoi que ce soit.
        good_cert, good_key = (network.folder(app) / 'cert.pem').read_text(), (network.folder(app) / 'key.pem').read_text()
        network.generate(app, ['autre.local'])
        other_key = (network.folder(app) / 'key.pem').read_text()
        third = network.describe(app)['fingerprint']
        for body in ({'action': 'provide', 'certificate': good_cert, 'key': other_key}, {'action': 'provide', 'certificate': 'x', 'key': 'y'}, {'action': 'provide', 'certificate': good_cert}, {'action': 'autre'}):
            self.assertEqual(self.post('admin', '/api/network/certificate', body)[0], 400, body.get('action'))
        self.assertEqual(network.describe(app)['fingerprint'], third)
        self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'provide', 'certificate': good_cert, 'key': good_key})[0], 200)
        state = self.get('admin', '/api/network')[1]
        self.assertEqual((state['certificate']['fingerprint'], state['provided']), (second, True))
        self.assertNotIn('PRIVATE', json.dumps(state))
        # Un certificat fourni n'est pas remplacé d'office quand les noms changent.
        self.assertEqual(self.post('admin', '/api/network/configure', {'enabled': True, 'confirm': True, 'port': self.port, 'hosts': ['nas.local'], 'require_totp': 'admins'})[0], 200)
        self.assertEqual(network.describe(app)['fingerprint'], second)
        # Fermer : le port est rendu, et l'état le dit.
        self.assertEqual(self.post('admin', '/api/network/configure', {'enabled': False, 'port': self.port, 'hosts': ['nas.local'], 'require_totp': 'admins'})[0], 200)
        network.apply(app, '127.0.0.1')
        self.assertIsNone(network.LISTENER['server'])
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); probe.bind(('127.0.0.1', self.port))
        state = self.get('admin', '/api/network')[1]
        self.assertEqual((state['enabled'], state['running'], state['urls']), (False, False, []))
        self.assertEqual(self.audit()[-1][:2], ('admin', 'Accès réseau fermé'))


if __name__ == '__main__':
    unittest.main()
