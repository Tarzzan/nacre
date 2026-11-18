"""Accès par le réseau : second point d'écoute en HTTPS, noms déclarés, double authentification pour les administrateurs.

Vrai serveur, vrai TLS sur la boucle locale, certificat produit par OpenSSL. Rien ne sort de la machine.
"""
import http.client
import json
import shutil
import subprocess
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

    def trust(self):
        """Ce qu'un appareil installe pour reconnaître le NAS : l'autorité locale, ou à défaut le certificat lui-même."""
        authority = network.folder(app) / 'ca.pem'
        return authority if authority.is_file() else network.folder(app) / 'cert.pem'

    def shown(self, name, *extensions):
        return subprocess.run(['openssl', 'x509', '-in', str(network.folder(app) / name), '-noout', '-ext', ','.join(extensions)], capture_output=True, text=True).stdout

    def legacy(self, hosts=('localhost', '127.0.0.1')):
        """Installation d'avant l'autorité locale : un seul certificat autosigné, tel que les versions précédentes le produisaient."""
        folder = network.folder(app)
        names = ','.join(('IP:' if network.is_address(h) else 'DNS:') + h for h in hosts)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-days', '825', '-subj', '/CN=' + hosts[0],
                        '-addext', 'subjectAltName=' + names, '-keyout', str(folder / 'old-key.pem'), '-out', str(folder / 'old.pem')], check=True, capture_output=True)
        network.place(app, (folder / 'old.pem').read_text(), (folder / 'old-key.pem').read_text())
        (folder / 'old.pem').unlink(); (folder / 'old-key.pem').unlink()
        with app.database() as db:
            test_spaces.spaces.put(db, network.KEY, {'enabled': True, 'port': self.port, 'hosts': list(hosts), 'require_totp': 'admins', 'certificate': 'self'})

    def secure(self, method, path, body=None, cookie=None, host='localhost', origin=None, csrf=None):
        """Requête par le point d'écoute réseau, certificat vérifié : (code, en-têtes, contenu)."""
        context = ssl.create_default_context(cafile=str(self.trust()))
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
        # Durée que tous les appareils acceptent pour un certificat de serveur ; il se renouvelle seul avant.
        self.assertTrue(time.time() + 390 * 86400 < state['certificate']['expires'] < time.time() + 400 * 86400)
        self.assertEqual((state['kind'], state['provided']), ('authority', False))
        self.assertEqual((network.folder(app) / 'key.pem').stat().st_mode & 0o777, 0o600)
        status, headers, page = self.secure('GET', '/')
        self.assertEqual(status, 200); self.assertIn(b'<title>Nacre', page)
        # Un nom non déclaré est refusé, même avec un certificat valable ; le nom seul, sans port, passe (cas d'un relais).
        self.assertEqual(self.secure('GET', '/', host='autre.exemple')[0], 403)
        context = ssl.create_default_context(cafile=str(self.trust()))
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

    def test_devices_trust_a_local_authority_once_and_it_cannot_vouch_for_the_internet(self):
        self.people(camille='member')
        self.assertEqual(self.get('admin', '/api/network/authority')[0], 404)
        self.assertIsNone(self.get('admin', '/api/account')[1]['authority'])
        self.open(hosts=('127.0.0.1', 'localhost', 'nas.local'))
        state = self.get('admin', '/api/network')[1]
        authority = state['authority']
        self.assertRegex(authority['fingerprint'], r'^([0-9A-F]{2}:){31}[0-9A-F]{2}$')
        self.assertNotEqual(authority['fingerprint'], state['certificate']['fingerprint'])
        # Le domaine d'office s'arrête au réseau local : cette machine elle-même n'y entre que parce qu'elle est déclarée ici.
        self.assertEqual((authority['extra'], authority['expires'] > time.time() + 3600 * 86400), (['localhost', '127.0.0.1/32'], True))
        self.assertRegex(authority['fingerprint_sha1'], r'^([0-9A-F]{2}:){19}[0-9A-F]{2}$')
        # Le certificat de serveur dit ce qu'il est : un serveur, pas une autorité. Les appareils Apple l'exigent.
        leaf = self.shown('cert.pem', 'basicConstraints', 'keyUsage', 'extendedKeyUsage')
        self.assertIn('CA:FALSE', leaf); self.assertIn('TLS Web Server Authentication', leaf); self.assertIn('Digital Signature', leaf)
        root = self.shown('ca.pem', 'basicConstraints', 'keyUsage', 'extendedKeyUsage', 'nameConstraints')
        self.assertIn('CA:TRUE', root); self.assertIn('Certificate Sign', root); self.assertIn('DNS:local', root); self.assertIn('IP:192.168.0.0/255.255.0.0', root)
        # Une autorité de serveurs, et de rien d'autre : ni courrier, ni adresse de page.
        self.assertIn('TLS Web Server Authentication', root); self.assertIn('email:invalid', root); self.assertIn('URI:invalid', root)
        subject = subprocess.run(['openssl', 'x509', '-in', str(network.folder(app) / 'cert.pem'), '-noout', '-subject'], capture_output=True, text=True).stdout
        self.assertNotIn('CN', subject)
        self.assertEqual((network.folder(app) / 'ca-key.pem').stat().st_mode & 0o777, 0o600)
        # Un appareil qui n'a installé que l'autorité joint le NAS sous chacun de ses noms, nom vérifié.
        for name in ('localhost', '127.0.0.1'):
            context = ssl.create_default_context(cafile=str(network.folder(app) / 'ca.pem'))
            conn = http.client.HTTPSConnection(name, self.port, timeout=6, context=context)
            conn.putrequest('GET', '/', skip_host=True); conn.putheader('Host', f'localhost:{self.port}'); conn.endheaders()
            self.assertEqual(conn.getresponse().status, 200, name); conn.close()
        # L'autorité se télécharge, sans secret, par quiconque a une session ; personne d'autre.
        for who in ('admin', 'camille'):
            status, data = self.request('GET', '/api/network/authority', token=self.sessions[who][0])
            self.assertEqual((status, data), (200, (network.folder(app) / 'ca.pem').read_bytes()), who)
            self.assertEqual(self.get(who, '/api/account')[1]['authority']['fingerprint'], authority['fingerprint'])
        self.assertNotIn(b'PRIVATE', (network.folder(app) / 'ca.pem').read_bytes())
        self.assertEqual(self.request('GET', '/api/network/authority')[0], 401)
        self.assertNotIn('PRIVATE', json.dumps(state))
        # Clé de l'autorité volée : un certificat pour un site d'Internet, signé avec elle, reste refusé par les appareils.
        folder = network.folder(app)
        (folder / 'vol.cnf').write_text('[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=banque.example.com\n[leaf]\nbasicConstraints=critical,CA:FALSE\n'
                                        'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:banque.example.com\n')
        subprocess.run(['openssl', 'req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-config', str(folder / 'vol.cnf'),
                        '-keyout', str(folder / 'vol-key.pem'), '-out', str(folder / 'vol.csr')], check=True, capture_output=True)
        subprocess.run(['openssl', 'x509', '-req', '-in', str(folder / 'vol.csr'), '-CA', str(folder / 'ca.pem'), '-CAkey', str(folder / 'ca-key.pem'), '-set_serial', '0x77',
                        '-days', '30', '-extfile', str(folder / 'vol.cnf'), '-extensions', 'leaf', '-out', str(folder / 'vol.pem')], check=True, capture_output=True)
        verdict = lambda name: subprocess.run(['openssl', 'verify', '-CAfile', str(folder / 'ca.pem'), '-purpose', 'sslserver', str(folder / name)], capture_output=True, text=True)
        self.assertEqual(verdict('cert.pem').returncode, 0)
        stolen = verdict('vol.pem')
        self.assertNotEqual(stolen.returncode, 0); self.assertIn('permitted subtree violation', stolen.stderr + stolen.stdout)
        # Refaire le certificat de serveur ne change pas l'autorité : les appareils n'ont rien à refaire.
        self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'regenerate'})[0], 200)
        after = self.get('admin', '/api/network')[1]
        self.assertEqual(after['authority']['fingerprint'], authority['fingerprint'])
        self.assertNotEqual(after['certificate']['fingerprint'], state['certificate']['fingerprint'])
        # Un nom hors de son domaine est refusé tant que l'autorité n'est pas refaite, ce qui se demande explicitement.
        base = {'enabled': True, 'confirm': True, 'port': self.port, 'require_totp': 'admins'}
        status, data = self.post('admin', '/api/network/configure', {**base, 'hosts': ['localhost', 'nas.exemple.org']})
        self.assertEqual(status, 409); self.assertIn('ne peut pas certifier « nas.exemple.org »', data['error'])
        self.assertEqual(self.get('admin', '/api/network')[1]['hosts'], ['127.0.0.1', 'localhost', 'nas.local'])
        self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': ['localhost', 'nas.exemple.org'], 'authority': 'renew'})[0], 200)
        renewed = self.get('admin', '/api/network')[1]
        self.assertNotEqual(renewed['authority']['fingerprint'], authority['fingerprint'])
        self.assertEqual((renewed['authority']['extra'], sorted(renewed['certificate']['names'])), (['localhost', 'nas.exemple.org'], ['localhost', 'nas.exemple.org']))
        self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'authority'})[0], 400)
        self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'authority', 'confirm': True})[0], 200)
        self.assertNotEqual(self.get('admin', '/api/network')[1]['authority']['fingerprint'], renewed['authority']['fingerprint'])
        self.assertEqual(self.audit()[-1][:2], ('admin', 'Autorité locale et certificat refaits'))
        self.assertEqual(sorted(p.name for p in folder.iterdir() if not p.name.startswith('vol')), ['authority.json', 'ca-key.pem', 'ca.pem', 'cert.pem', 'key.pem'])
        # Clé volée, suite : ni courrier signé au nom de quelqu'un, ni adresse de page.
        (folder / 'vol.cnf').write_text('[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=quelqu un\n[leaf]\nbasicConstraints=critical,CA:FALSE\n'
                                        'extendedKeyUsage=emailProtection\nsubjectAltName=email:quelqu.un@example.org\n')
        subprocess.run(['openssl', 'req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes', '-config', str(folder / 'vol.cnf'),
                        '-keyout', str(folder / 'vol-key.pem'), '-out', str(folder / 'vol.csr')], check=True, capture_output=True)
        subprocess.run(['openssl', 'x509', '-req', '-in', str(folder / 'vol.csr'), '-CA', str(folder / 'ca.pem'), '-CAkey', str(folder / 'ca-key.pem'), '-set_serial', '0x78',
                        '-days', '30', '-extfile', str(folder / 'vol.cnf'), '-extensions', 'leaf', '-out', str(folder / 'vol.pem')], check=True, capture_output=True)
        mail = subprocess.run(['openssl', 'verify', '-CAfile', str(folder / 'ca.pem'), '-purpose', 'smimesign', str(folder / 'vol.pem')], capture_output=True, text=True)
        self.assertNotEqual(mail.returncode, 0); self.assertIn('permitted subtree violation', mail.stderr + mail.stdout)
        # Adresses seules, adresse publique, IPv6 écrite en long : le certificat reste accepté, les noms se comparent sous une seule forme.
        self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': ['203.0.113.9', 'FD12:0:0:0:0:0:0:5'], 'authority': 'renew'})[0], 200)
        state = self.get('admin', '/api/network')[1]
        self.assertEqual((state['hosts'], sorted(state['certificate']['names']), state['authority']['extra']), (['203.0.113.9', 'fd12::5'], ['203.0.113.9', 'fd12::5'], ['203.0.113.9/32']))
        strict = subprocess.run(['openssl', 'verify', '-x509_strict', '-CAfile', str(folder / 'ca.pem'), '-purpose', 'sslserver', '-verify_ip', '203.0.113.9', str(folder / 'cert.pem')], capture_output=True, text=True)
        self.assertEqual(strict.returncode, 0, strict.stderr)
        again = network.describe(app)['fingerprint']
        self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': ['203.0.113.9', 'fd12::5']})[0], 200)
        self.assertEqual(network.describe(app)['fingerprint'], again)

    def test_names_cannot_widen_the_authority_nor_reach_its_settings_file(self):
        self.people()
        base = {'enabled': True, 'confirm': True, 'port': self.port, 'require_totp': 'admins'}
        # Zone d'interface, saut de ligne, caractère de réglage : refusés à l'entrée.
        for name in ('fe80::1%eth0', '2001:db8::5%z\n[req]\nx509_extensions=e', 'nas.local\nCN=x', 'nas$.local', 'nas local'):
            self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': [name]})[0], 400, name)
        # Un nom sans point couvrirait tout ce qui s'y termine : refusé avec le conseil, sans rien créer.
        for name in ('nas', 'com', 'fr'):
            status, data = self.post('admin', '/api/network/configure', {**base, 'hosts': [name]})
            self.assertEqual(status, 400, name); self.assertIn(f'{name}.local', data['error'])
        self.assertEqual([p.name for p in network.folder(app).iterdir()], [])
        # Un nom abîmé dans la base n'atteint jamais le fichier de réglage : ni à la remise à neuf, ni au renouvellement.
        self.open(hosts=('nas.local',))
        before = (network.trusted(app)['fingerprint'], network.describe(app)['fingerprint'])
        with app.database() as db:
            test_spaces.spaces.put(db, network.KEY, {'enabled': True, 'port': self.port, 'hosts': ['2001:db8::5%z\n[req]\nx509_extensions=e'], 'require_totp': 'admins', 'certificate': 'authority'})
        for body in ({'action': 'regenerate'}, {'action': 'authority', 'confirm': True}):
            self.assertEqual(self.post('admin', '/api/network/certificate', body)[0], 400, body)
        self.assertFalse(network.renewal(app, now=time.time() + 380 * 86400))
        self.assertEqual((network.trusted(app)['fingerprint'], network.describe(app)['fingerprint']), before)
        # Nom de NAS très long : l'autorité se crée quand même, son nom tient dans la limite d'un certificat.
        import onboarding
        with unittest.mock.patch.object(onboarding, 'read', return_value={'name': 'Mediatheque municipale du quartier des Palmiers 2026', 'timezone': 'UTC'}):
            self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': ['nas.local']})[0], 200)
            self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'authority', 'confirm': True})[0], 200)
        subject = subprocess.run(['openssl', 'x509', '-in', str(network.folder(app) / 'ca.pem'), '-noout', '-subject', '-nameopt', 'multiline'], capture_output=True, text=True).stdout
        name = subject.split('commonName')[1].split('=', 1)[1].strip()
        self.assertLessEqual(len(name), 64); self.assertTrue(name.startswith('Nacre Mediatheque municipale du quarti'), name)

    def test_a_failed_renewal_of_the_authority_changes_nothing(self):
        self.people()
        self.open(hosts=('nas.local',))
        folder = network.folder(app)
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        real = network.sign
        # La signature du certificat de serveur échoue après la création de la nouvelle autorité : rien ne doit avoir bougé.
        with unittest.mock.patch.object(network, 'sign', side_effect=subprocess.CalledProcessError(1, 'openssl')):
            status, data = self.post('admin', '/api/network/certificate', {'action': 'authority', 'confirm': True})
            self.assertEqual(status, 503); self.assertIn('Rien n’a été changé', data['error'])
            self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'regenerate'})[0], 503)
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before)
        self.assertEqual(subprocess.run(['openssl', 'verify', '-CAfile', str(folder / 'ca.pem'), str(folder / 'cert.pem')], capture_output=True).returncode, 0)
        self.assertNotIn('Autorité locale et certificat refaits', [a[1] for a in self.audit()])
        # Réglage du domaine illisible : l'autorité est refaite, et la réponse le dit au lieu de promettre « la même autorité ».
        (folder / 'authority.json').write_text('{abîmé')
        status, data = self.post('admin', '/api/network/certificate', {'action': 'regenerate'})
        self.assertEqual((status, data['authority_made']), (200, True))
        self.assertEqual(self.audit()[-1][:2], ('admin', 'Autorité locale et certificat refaits'))
        # Fichiers abîmés : pris pour absents, jamais une erreur ; l'alerte reste « non vérifiée » plutôt que de se refermer.
        import alerts
        (folder / 'cert.pem').write_bytes(b'\xff\xfe pas un certificat')
        self.assertIsNone(network.describe(app))
        self.assertEqual(self.get('admin', '/api/network')[0], 200)
        with self.assertRaises(ValueError):
            network.conditions(app)
        self.assertIsNone(alerts.collect(app)[0]['network'])
        (folder / 'ca.pem').write_bytes(b'\xff\xfe')
        self.assertIsNone(network.trusted(app))
        self.assertEqual(self.get('admin', '/api/account')[0], 200)
        del real

    def test_an_older_self_signed_certificate_is_kept_until_replacing_it_is_asked(self):
        self.people()
        self.legacy()
        network.apply(app, '127.0.0.1')
        state = self.get('admin', '/api/network')[1]
        old = state['certificate']['fingerprint']
        self.assertEqual((state['kind'], state['authority'], state['running']), ('self', None, True))
        self.assertEqual(self.secure('GET', '/')[0], 200)
        base = {'enabled': True, 'confirm': True, 'port': self.port, 'require_totp': 'everyone'}
        # Mêmes noms : rien n'est refait, ce que les appareils avaient accepté tient toujours.
        self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': ['localhost', '127.0.0.1']})[0], 200)
        self.assertEqual(network.describe(app)['fingerprint'], old)
        # Autres noms : le remplacement se demande, il n'arrive jamais en silence.
        status, data = self.post('admin', '/api/network/configure', {**base, 'hosts': ['localhost', 'nas.local']})
        self.assertEqual(status, 409); self.assertIn('Confirmez ce remplacement', data['error'])
        self.assertEqual((network.describe(app)['fingerprint'], self.get('admin', '/api/network')[1]['hosts']), (old, ['localhost', '127.0.0.1']))
        self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'hosts': ['localhost', 'nas.local'], 'replace': True})[0], 200)
        state = self.get('admin', '/api/network')[1]
        self.assertEqual((state['kind'], state['authority'] is not None, state['certificate']['fingerprint'] != old), ('authority', True, True))

    def test_server_certificate_renews_itself_and_an_expiring_one_raises_an_alert(self):
        import alerts
        self.people()
        self.assertEqual(network.conditions(app), [])
        self.open()
        first, authority = network.describe(app), network.trusted(app)['fingerprint']
        # Loin de l'échéance : rien. À moins de trente jours : refait sous la même autorité, l'écoute repart.
        self.assertFalse(network.renewal(app))
        self.assertFalse(network.renewal(app, now=first['expires'] - 31 * 86400))
        self.assertTrue(network.renewal(app, now=first['expires'] - 29 * 86400))
        second = network.describe(app)
        self.assertNotEqual(second['fingerprint'], first['fingerprint'])
        self.assertEqual(network.trusted(app)['fingerprint'], authority)
        self.assertIsNotNone(network.LISTENER['server'])
        self.assertEqual(self.secure('GET', '/')[0], 200)
        self.assertEqual(self.audit()[-1], ('Nacre', 'Certificat de serveur renouvelé', 'sous la même autorité locale'))
        self.assertEqual(network.conditions(app), [])
        self.assertEqual(alerts.collect(app)[0]['network'], [])
        # Le journal en panne n'empêche pas de servir le nouveau certificat.
        listener = network.LISTENER['server']
        with unittest.mock.patch.object(app, 'audit', side_effect=OSError('journal indisponible')):
            self.assertTrue(network.renewal(app, now=second['expires'] - 86400))
        third = network.describe(app)
        self.assertNotEqual(third['fingerprint'], second['fingerprint']); self.assertIsNot(network.LISTENER['server'], listener)
        network.apply(app, '127.0.0.1')
        # Accès fermé puis rouvert près de l'échéance : le certificat est refait à la réouverture, sous la même autorité.
        base = {'port': self.port, 'hosts': ['localhost', '127.0.0.1'], 'require_totp': 'admins'}
        self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'enabled': False})[0], 200)
        with unittest.mock.patch.object(network, 'RENEW_BEFORE', 400 * 86400):
            self.assertEqual(self.post('admin', '/api/network/configure', {**base, 'enabled': True, 'confirm': True}), (200, {'ok': True, 'authority_made': False}))
        second = network.describe(app)
        self.assertNotEqual(second['fingerprint'], third['fingerprint']); self.assertEqual(network.trusted(app)['fingerprint'], authority)
        network.apply(app, '127.0.0.1')
        # L'autorité elle-même finit par échoir : prévenu trois mois avant, puis dit.
        end = network.trusted(app)['expires']
        with unittest.mock.patch.object(network, 'describe', return_value={**second, 'expires': end + 400 * 86400}):
            self.assertEqual(network.conditions(app, now=end - 91 * 86400), [])
            self.assertEqual([(c[0], c[4], c[5]) for c in network.conditions(app, now=end - 10 * 86400)], [('network:certificate:authority', 'warning', 'authority-soon')])
            self.assertEqual([(c[0], c[4], c[5]) for c in network.conditions(app, now=end + 5)], [('network:certificate:authority', 'critical', 'authority-expired')])
        # Docker muet ou installation en cours : le certificat se lit sur place, son alerte est évaluée quand même.
        with unittest.mock.patch.object(app, 'service_op', side_effect=app.Problem('Docker ne répond pas.', 503)), \
                unittest.mock.patch.object(network, 'conditions', return_value=[('network:certificate', 'Titre', 'Message', 'network', 'warning', 'soon')]):
            self.assertEqual([c['key'] for c in alerts.collect(app)[0]['network']], ['network:certificate'])
        # Un certificat qui ne peut pas se renouveler seul (fourni par l'administrateur) prévient avant, puis dit qu'il est échu.
        self.assertIsNotNone(self.get('admin', '/api/account')[1]['authority'])
        self.assertEqual(self.post('admin', '/api/network/certificate', {'action': 'provide', 'certificate': (network.folder(app) / 'cert.pem').read_text(),
                                                                       'key': (network.folder(app) / 'key.pem').read_text()})[0], 200)
        # L'autorité ne signe plus le certificat en service : Mon compte ne propose plus de l'installer.
        self.assertIsNone(self.get('admin', '/api/account')[1]['authority'])
        self.assertFalse(network.renewal(app, now=second['expires'] - 86400))
        self.assertEqual(network.conditions(app, now=second['expires'] - 22 * 86400), [])
        soon = network.conditions(app, now=second['expires'] - 10 * 86400 - 60)
        self.assertEqual([(c[0], c[1], c[4], c[5]) for c in soon], [('network:certificate', 'Le certificat de l’accès réseau arrive à échéance', 'warning', 'soon')])
        self.assertIn('Il reste 10 jours. Fournissez-en un nouveau', soon[0][2])
        late = network.conditions(app, now=second['expires'] + 5)
        self.assertEqual([(c[0], c[4], c[5]) for c in late], [('network:certificate', 'critical', 'expired')])
        # Accès fermé : plus rien à surveiller.
        self.assertEqual(self.post('admin', '/api/network/configure', {'enabled': False, 'port': self.port, 'hosts': ['localhost'], 'require_totp': 'admins'})[0], 200)
        self.assertEqual(network.conditions(app, now=second['expires'] + 5), [])

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
