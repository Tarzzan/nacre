"""Appareils et WebDAV en lecture : un mot de passe par appareil, aucun droit avant lui, les droits de la personne après."""
import base64
import http.client
import os
import time
import unittest
import unittest.mock
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from urllib.parse import quote, unquote

import test_spaces
import test_totp
import dav
import devices
import totp

app = test_spaces.app
PASSWORD = test_totp.PASSWORD
D = '{DAV:}'


class DavTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home', 'audit'))

    def team(self):
        devices.FAILED.clear()
        self.people(camille='member', bruno='member', dora='member', lecteur='viewer')
        with app.database() as db:
            for name in ('admin', 'camille', 'bruno', 'dora', 'lecteur'):
                salt = '55' * 16
                db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, app.password_hash(PASSWORD, salt), name))
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier école', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.team_dir = Path(app.ROOT) / 'data/espaces' / self.space[7:]
        self.mine = self.home('camille')
        self.mine_dir = Path(app.ROOT) / 'data/espaces' / self.mine[7:]
        self.mine_dir.mkdir(parents=True, exist_ok=True)
        self.common = Path(app.ROOT) / 'data/fichiers'

    def device(self, who, name='Portable', **extra):
        status, data = self.post(who, '/api/account/devices/create', {'password': PASSWORD, 'name': name, **extra})
        self.assertEqual(status, 200, data)
        return data['password']

    def dav(self, method, path, who=None, password=None, body=None, headers=None, raw_auth=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        sent = dict(headers or {})
        if raw_auth is not None:
            sent['Authorization'] = raw_auth
        elif who is not None:
            sent['Authorization'] = 'Basic ' + base64.b64encode(f'{who}:{password}'.encode()).decode()
        conn.request(method, quote(path, safe='/%'), body, sent)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def listed(self, who, password, path, depth='1', body=None):
        status, headers, data = self.dav('PROPFIND', path, who, password, body, {'Depth': depth})
        if status != 207:
            return status, data
        found = {}
        for response in ElementTree.fromstring(data).findall(D + 'response'):
            props = {}
            for propstat in response.findall(D + 'propstat'):
                if ' 200 ' in propstat.find(D + 'status').text:
                    props.update({child.tag: (child.text or ('collection' if child.find(D + 'collection') is not None else '')) for child in propstat.find(D + 'prop')})
            found[unquote(response.find(D + 'href').text)] = props
        return status, found

    def test_an_added_device_gets_a_password_shown_once_and_removed_at_will(self):
        self.team()
        self.assertEqual(self.get('camille', '/api/account')[1]['devices'], [])
        for bad in ({'name': 'Portable'}, {'password': 'faux', 'name': 'Portable'}, {'password': PASSWORD}, {'password': PASSWORD, 'name': ' '}, {'password': PASSWORD, 'name': 'x' * 41},
                    {'password': PASSWORD, 'name': 'a\x07b'}, {'password': PASSWORD, 'name': 'Portable', 'write': 'oui'}):
            self.assertIn(self.post('camille', '/api/account/devices/create', bad)[0], (400, 403), bad)
        status, made = self.post('camille', '/api/account/devices/create', {'password': PASSWORD, 'name': '  Téléphone   de <b>Camille</b> '})
        self.assertEqual((status, made['username'], made['device']['name'], made['device']['write']), (200, 'camille', 'Téléphone de <b>Camille</b>', False))
        self.assertRegex(made['password'], r'^([a-hjkmnp-z2-9]{4}-){5}[a-hjkmnp-z2-9]{4}$')
        # Le mot de passe n'est gardé nulle part : ni dans la liste, ni dans la base, où seule son empreinte figure.
        listed = self.get('camille', '/api/account')[1]['devices']
        self.assertEqual([(d['id'], d['name'], d['used']) for d in listed], [(made['device']['id'], 'Téléphone de <b>Camille</b>', 0)])
        with app.database() as db:
            stored = ' '.join(row[0] + row[1] for row in db.execute("SELECT key,value FROM settings WHERE key LIKE 'device:%'"))
        self.assertNotIn(made['password'], stored); self.assertNotIn(made['password'].replace('-', ''), stored)
        self.assertNotIn(made['password'], str(self.get('camille', '/api/account')[1]))
        self.assertIn(('camille', 'Appareil ajouté', 'Téléphone de <b>Camille</b>'), self.audit())
        # Il ouvre /dav/, saisi avec ou sans tirets, en majuscules ou non ; rien d'autre de la console.
        for typed in (made['password'], made['password'].replace('-', ''), made['password'].upper(), made['password'].replace('-', ' ')):
            self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', typed, headers={'Depth': '0'})[0], 207, typed)
        basic = 'Basic ' + base64.b64encode(f'camille:{made["password"]}'.encode()).decode()
        for path in ('/api/me', '/api/areas', '/api/account', '/api/files?area=fichiers'):
            self.assertEqual(self.dav('GET', path, raw_auth=basic)[0], 401, path)
        self.assertEqual(self.get('camille', '/api/account')[1]['devices'][0]['used'] > 0, True)
        # Retirer un appareil ne touche pas aux autres ; un membre ne retire pas celui d'un autre, un administrateur si.
        second = self.post('camille', '/api/account/devices/create', {'password': PASSWORD, 'name': 'Tablette'})[1]
        other = self.device('bruno', 'Poste de Bruno')
        theirs = self.get('bruno', '/api/account')[1]['devices'][0]['id']
        self.assertEqual(self.post('camille', '/api/account/devices/revoke', {'id': theirs})[0], 404)
        self.assertEqual(self.post('camille', '/api/account/devices/revoke', {'id': made['device']['id']})[0], 200)
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', made['password'], headers={'Depth': '0'})[0], 401)
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', second['password'], headers={'Depth': '0'})[0], 207)
        self.assertEqual(self.post('admin', '/api/account/devices/revoke', {'id': theirs})[0], 200)
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'bruno', other, headers={'Depth': '0'})[0], 401)
        self.assertEqual(self.audit()[-1], ('admin', 'Appareil retiré', 'Poste de Bruno (bruno)'))
        self.assertEqual(self.post('camille', '/api/account/devices/revoke', {'id': 'inconnu'})[0], 404)
        devices.FAILED.clear()
        # Avec la double authentification, le code est redemandé pour ajouter un appareil ; l'appareil, lui, n'en saisit jamais.
        self.assertEqual(self.post('camille', '/api/account/totp/start', {'password': PASSWORD})[0], 200)
        with app.database() as db:
            secret = totp.state(db, 'camille')['pending']
        self.assertEqual(self.post('camille', '/api/account/totp/confirm', {'code': totp.code(secret, int(time.time() // 30))})[0], 200)
        self.assertEqual(self.post('camille', '/api/account/devices/create', {'password': PASSWORD, 'name': 'Téléphone'})[0], 403)
        self.assertEqual(self.post('camille', '/api/account/devices/create', {'password': PASSWORD, 'name': 'Téléphone', 'code': '000000'})[0], 403)
        status, third = self.post('camille', '/api/account/devices/create', {'password': PASSWORD, 'name': 'Téléphone', 'code': totp.code(secret, int(time.time() // 30) + 1)})
        self.assertEqual(status, 200, third)
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', third['password'], headers={'Depth': '0'})[0], 207)
        # Vingt appareils au plus.
        self.device('dora', 'Premier')
        with unittest.mock.patch.object(devices, 'LIMIT', 1):
            self.assertEqual(self.post('dora', '/api/account/devices/create', {'password': PASSWORD, 'name': 'De trop'})[0], 409)

    def test_nothing_is_open_before_the_device_is_known_and_refusals_are_limited(self):
        self.team()
        (self.common / 'public.txt').write_text('commun')
        password = self.device('camille')
        # Sans mot de passe d'appareil, ou avec autre chose : rien, pour toute méthode et toute adresse.
        for method in ('OPTIONS', 'PROPFIND', 'GET', 'HEAD'):
            for path in ('/dav/', '/dav/files/', '/dav/files/Fichiers partagés/public.txt'):
                status, headers, data = self.dav(method, path)
                self.assertEqual((status, headers.get('WWW-Authenticate')), (401, 'Basic realm="Nacre", charset="UTF-8"'), (method, path))
                self.assertNotIn(b'commun', data)
        for who, secret in (('camille', PASSWORD), ('camille', ''), ('camille', 'faux-faux-faux-faux-faux-faux'), ('bruno', password), ('', password), ('admin', password)):
            self.assertEqual(self.dav('GET', '/dav/files/Fichiers partagés/public.txt', who, secret)[0], 401, who)
        for raw in ('Bearer ' + password, 'Basic %%%', 'Basic ' + base64.b64encode(b'\xff\xfe:x').decode(), 'Basic ' + 'A' * 700, 'basic x'):
            self.assertEqual(self.dav('GET', '/dav/files/Fichiers partagés/public.txt', raw_auth=raw)[0], 401, raw[:20])
        # La session de la console n'ouvre pas /dav/, et un navigateur y est refusé sans qu'on lui demande de mot de passe.
        status, headers, _ = self.dav('PROPFIND', '/dav/', headers={'Cookie': 'nas_session=' + self.sessions['camille'][0], 'Depth': '0'})
        self.assertEqual(status, 401)
        for marks in ({'Origin': f'http://127.0.0.1:{self.http.server_port}'}, {'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Mode': 'navigate'}):
            status, headers, _ = self.dav('GET', '/dav/files/Fichiers partagés/public.txt', 'camille', password, headers=marks)
            self.assertEqual((status, 'WWW-Authenticate' in headers), (403, False), marks)
        self.assertEqual(self.dav('GET', '/dav/files/Fichiers partagés/public.txt', 'camille', password, headers={'Host': 'ailleurs.exemple'})[0], 403)
        # Compte désactivé : l'appareil est refusé dès la requête suivante ; réactivé, il revient.
        devices.FAILED.clear()
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': False})[0], 200)
        self.assertEqual(self.dav('GET', '/dav/files/Fichiers partagés/public.txt', 'camille', password)[0], 401)
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': True})[0], 200)
        self.assertEqual(self.dav('GET', '/dav/files/Fichiers partagés/public.txt', 'camille', password)[0], 200)
        # Dix refus en une minute depuis une adresse : elle n'obtient plus de réponse pendant une minute, sans toucher à la connexion de la console.
        devices.FAILED.clear()
        wrong = 'faux-faux-faux-faux-faux-faux'
        for _ in range(devices.FAILURES):
            self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', wrong, headers={'Depth': '0'})[0], 401)
        status, headers, _ = self.dav('PROPFIND', '/dav/', 'camille', wrong, headers={'Depth': '0'})
        self.assertEqual((status, headers.get('Retry-After')), (429, '60'))
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'bruno', wrong, headers={'Depth': '0'})[0], 429)
        self.assertEqual(self.request('POST', '/api/login', {'username': 'camille', 'password': PASSWORD})[0], 200)
        # Un mot de passe juste passe toujours : personne ne peut bloquer les appareils d'un compte en multipliant les refus à son nom.
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', password, headers={'Depth': '0'})[0], 207)
        self.assertEqual(list(devices.FAILED), ['a:127.0.0.1'])
        with unittest.mock.patch.object(devices.time, 'time', return_value=time.time() + 61):
            self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', wrong, headers={'Depth': '0'})[0], 401)
        devices.FAILED.clear()
        # Nom d'hôte saisi avec une majuscule : accepté, comme le ferait un navigateur.
        self.assertEqual(self.dav('PROPFIND', '/dav/', 'camille', password, headers={'Depth': '0', 'Host': f'LocalHost:{self.http.server_port}'})[0], 207)
        # Un corps annoncé et jamais lu ferme la connexion, même quand la requête réussit : il ne passe pas pour la requête suivante.
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        basic = {'Authorization': 'Basic ' + base64.b64encode(f'camille:{password}'.encode()).decode()}
        conn.request('OPTIONS', '/dav/', b'GET /dav/files/ HTTP/1.1\r\n\r\n', basic)
        first = conn.getresponse(); first.read()
        self.assertEqual((first.status, first.getheader('Connection')), (200, 'close'))
        conn.close()
        # Pendant une mise à jour : indisponible, jamais « vide ».
        with unittest.mock.patch('updates.maintenance', return_value=True):
            status, headers, _ = self.dav('PROPFIND', '/dav/files/', 'camille', password)
            self.assertEqual((status, headers.get('Retry-After')), (503, '30'))

    def test_a_device_sees_the_spaces_of_its_person_and_nothing_else(self):
        self.team()
        (self.team_dir / 'Plans').mkdir()
        (self.team_dir / 'Plans/façade & toit.pdf').write_bytes(b'%PDF plan')
        (self.team_dir / 'notes.txt').write_text('équipe')
        (self.mine_dir / 'journal.md').write_text('personnel')
        (self.common / 'public.txt').write_text('commun')
        (self.common / '.cache').mkdir(); (self.common / '.cache/x.txt').write_text('point')
        (self.common / 'lien.txt').symlink_to(self.mine_dir / 'journal.md')
        (self.team_dir / '.nacre-versions').mkdir(exist_ok=True); (self.team_dir / '.nacre-versions/secret').write_text('interne')
        camille, bruno, dora, lecteur, admin = (self.device(who) for who in ('camille', 'bruno', 'dora', 'lecteur', 'admin'))
        status, root = self.listed('camille', camille, '/dav/')
        self.assertEqual((status, sorted(root)), (207, ['/dav/', '/dav/files/']))
        status, found = self.listed('camille', camille, '/dav/files/')
        self.assertEqual(sorted(found), ['/dav/files/', '/dav/files/Chantier école/', '/dav/files/Fichiers partagés/', '/dav/files/Mon espace/'])
        self.assertEqual(found['/dav/files/Mon espace/'][D + 'resourcetype'], 'collection')
        # Profondeur 0 : la ressource seule. Infinie : refusée, avec la raison que les clients savent lire.
        self.assertEqual(sorted(self.listed('camille', camille, '/dav/files/', depth='0')[1]), ['/dav/files/'])
        status, data = self.listed('camille', camille, '/dav/files/', depth='infinity')
        self.assertEqual(status, 403); self.assertIn(b'propfind-finite-depth', data)
        # Un dossier : fichiers et sous-dossiers, sans les dossiers internes ni les liens ; les fichiers à point se voient.
        status, found = self.listed('camille', camille, '/dav/files/Chantier école/')
        self.assertEqual(sorted(found), ['/dav/files/Chantier école/', '/dav/files/Chantier école/Plans/', '/dav/files/Chantier école/notes.txt'])
        notes = found['/dav/files/Chantier école/notes.txt']
        self.assertEqual((notes[D + 'getcontentlength'], notes[D + 'resourcetype'], notes[D + 'displayname'], notes[D + 'getcontenttype']), ('7', '', 'notes.txt', 'text/plain'))
        self.assertRegex(notes[D + 'getlastmodified'], r'^\w{3}, \d\d \w{3} \d{4} \d\d:\d\d:\d\d GMT$'); self.assertRegex(notes[D + 'getetag'], r'^"[0-9a-f]+-7"$')
        self.assertGreater(int(found['/dav/files/Chantier école/'][D + 'quota-available-bytes']), 0)
        self.assertEqual(sorted(self.listed('camille', camille, '/dav/files/Fichiers partagés/')[1]),
                         ['/dav/files/Fichiers partagés/', '/dav/files/Fichiers partagés/.cache/', '/dav/files/Fichiers partagés/public.txt'])
        self.assertEqual(sorted(self.listed('camille', camille, '/dav/files/Chantier école/Plans/')[1]), ['/dav/files/Chantier école/Plans/', '/dav/files/Chantier école/Plans/façade & toit.pdf'])
        self.assertEqual(sorted(self.listed('camille', camille, '/dav/files/Chantier école/notes.txt')[1]), ['/dav/files/Chantier école/notes.txt'])
        # Propriétés demandées une à une : celles que Nacre tient, et un refus net pour les autres ; noms seuls.
        ask = b'<?xml version="1.0"?><D:propfind xmlns:D="DAV:" xmlns:o="http://owncloud.org/ns"><D:prop><D:getetag/><D:getcontentlength/><o:checksums/><D:lockdiscovery/></D:prop></D:propfind>'
        status, headers, data = self.dav('PROPFIND', '/dav/files/Chantier école/notes.txt', 'camille', camille, ask, {'Depth': '0'})
        tree = ElementTree.fromstring(data)
        ok, missing = (next(p for p in tree.iter(D + 'propstat') if code in p.find(D + 'status').text) for code in (' 200 ', ' 404 '))
        self.assertEqual(sorted(c.tag for c in ok.find(D + 'prop')), [D + 'getcontentlength', D + 'getetag'])
        self.assertEqual(sorted(c.tag for c in missing.find(D + 'prop')), ['{DAV:}lockdiscovery', '{http://owncloud.org/ns}checksums'])
        names = b'<D:propfind xmlns:D="DAV:"><D:propname/></D:propfind>'
        self.assertIn(b'<D:getetag/>', self.dav('PROPFIND', '/dav/files/Chantier école/notes.txt', 'camille', camille, names, {'Depth': '0'})[2])
        # Une déclaration de type, donc des entités : refusée par l'analyseur lui-même, quel que soit l'encodage du corps.
        declared = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "bbbbbbbbbb">]><D:propfind xmlns:D="DAV:"><D:prop><D:getetag/></D:prop></D:propfind>'
        for hostile, expected in ((b'<!DOCTYPE x [<!ENTITY a "b">]><D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>', (400,)), (declared.encode('utf-16'), (400,)), (b'pas du xml', (400,)),
                                  (b'<D:propfind xmlns:D="DAV:"><D:prop><x:a xmlns:x="u&quot;>&lt;"/></D:prop></D:propfind>', (207,))):
            status, headers, data = self.dav('PROPFIND', '/dav/files/Chantier école/notes.txt', 'camille', camille, hostile, {'Depth': '0'})
            self.assertIn(status, expected, hostile[:24])
            if status == 207:
                ElementTree.fromstring(data)
        # Les espaces portent leur date dans la liste, comme lorsqu'on les interroge un à un.
        self.assertRegex(self.listed('camille', camille, '/dav/files/')[1]['/dav/files/Mon espace/'][D + 'getlastmodified'], r' GMT$')
        # Un nom illisible ou à caractère de contrôle (déposé par le partage réseau) n'empêche pas de lire le reste du dossier.
        os.close(os.open(os.fsencode(self.team_dir) + b'/caf\xe9.txt', os.O_CREAT | os.O_WRONLY, 0o660))
        (self.team_dir / 'cloche\x07.txt').write_text('x')
        status, found = self.listed('camille', camille, '/dav/files/Chantier école/')
        self.assertEqual((status, sorted(found)), (207, ['/dav/files/Chantier école/', '/dav/files/Chantier école/Plans/', '/dav/files/Chantier école/notes.txt']))
        self.assertEqual(self.post('camille', '/api/folder', {'area': self.space, 'name': 'cloche\x07'})[0], 400)
        os.unlink(os.fsencode(self.team_dir) + b'/caf\xe9.txt'); (self.team_dir / 'cloche\x07.txt').unlink()
        self.assertEqual(self.dav('PROPFIND', '/dav/files/', 'camille', camille, b'x' * (dav.BODY_MAX + 1), {'Depth': '0'})[0], 413)
        # Chacun ses espaces : lecteur de l'équipe, personne hors de l'équipe, compte en lecture seule, administrateur sans l'espace personnel d'un membre.
        zones = lambda who, secret: sorted(k for k in self.listed(who, secret, '/dav/files/')[1] if k != '/dav/files/')
        self.assertEqual(zones('bruno', bruno), ['/dav/files/Chantier école/', '/dav/files/Fichiers partagés/', '/dav/files/Mon espace/'])
        self.assertEqual(zones('dora', dora), ['/dav/files/Fichiers partagés/', '/dav/files/Mon espace/'])
        self.assertEqual(zones('lecteur', lecteur), ['/dav/files/Fichiers partagés/'])
        self.assertEqual(zones('admin', admin), ['/dav/files/Chantier école/', '/dav/files/Fichiers partagés/', '/dav/files/Mon espace/'])
        for who, secret in (('dora', dora), ('lecteur', lecteur)):
            self.assertEqual(self.listed(who, secret, '/dav/files/Chantier école/')[0], 404, who)
            self.assertEqual(self.dav('GET', '/dav/files/Chantier école/notes.txt', who, secret)[0], 404, who)
        # « Mon espace » est celui de qui demande : l'administrateur n'y trouve pas le journal du membre.
        self.assertEqual(self.dav('GET', '/dav/files/Mon espace/journal.md', 'camille', camille)[0:3:2], (200, b'personnel'))
        for who, secret in (('admin', admin), ('bruno', bruno)):
            self.assertEqual(self.dav('GET', '/dav/files/Mon espace/journal.md', who, secret)[0], 404, who)
        # Rien d'autre que les fichiers des espaces : ni sauvegardes, ni vidéos, ni dossiers internes, ni lien, ni sortie de l'espace.
        for path in ('/dav/files/Sauvegardes/', '/dav/files/Vidéos/', '/dav/files/sauvegardes/', '/dav/files/video/', '/dav/principals/', '/dav/calendars/', '/dav/autre',
                     '/dav/files/Fichiers partagés/lien.txt', '/dav/files/Chantier école/.nacre-versions/secret', '/dav/files/Chantier école/../' + self.mine[7:] + '/journal.md',
                     '/dav/files/Chantier école/%2e%2e/x', '/dav/files/Chantier école/Plans/..%2f..%2fnotes.txt', '/dav/files/' + self.mine + '/journal.md'):
            for who, secret in (('admin', admin), ('camille', camille)):
                status, headers, data = self.dav('GET', path, who, secret)
                self.assertIn(status, (403, 404, 405), (who, path)); self.assertNotIn(b'personnel', data); self.assertNotIn(b'interne', data)
                self.assertIn(self.listed(who, secret, path)[0], (403, 404), (who, path))
        # Un espace d'équipe nommé comme un espace de base ne prend jamais sa place : il porte une marque, les deux espaces de base gardent leur nom.
        made = {name: self.post('admin', '/api/spaces/space', {'name': name, 'members': {'camille': 'read'}})[1]['id'] for name in ('Archives', 'Fichiers partagés', 'Mon espace')}
        self.assertEqual(self.post('admin', '/api/spaces/space', {'name': 'archives', 'members': {}})[0], 409)
        names = sorted(k for k in self.listed('camille', camille, '/dav/files/')[1] if k != '/dav/files/')
        self.assertEqual(names, sorted(['/dav/files/Chantier école/', '/dav/files/Fichiers partagés/', '/dav/files/Mon espace/', '/dav/files/Archives/',
                                        f'/dav/files/Fichiers partagés ~{made["Fichiers partagés"][-4:]}/', f'/dav/files/Mon espace ~{made["Mon espace"][-4:]}/']))
        self.assertEqual(self.dav('GET', '/dav/files/Fichiers partagés/public.txt', 'camille', camille)[0:3:2], (200, b'commun'))
        self.assertEqual(self.dav('GET', '/dav/files/Mon espace/journal.md', 'camille', camille)[0:3:2], (200, b'personnel'))
        # Accès retiré : l'espace disparaît à la requête suivante, sans dossier vide à sa place.
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': self.space, 'name': 'Chantier école', 'members': {}})[0], 200)
        self.assertEqual(self.listed('camille', camille, '/dav/files/Chantier école/')[0], 404)
        self.assertEqual(self.dav('GET', '/dav/files/Chantier école/notes.txt', 'camille', camille)[0], 404)

    def test_files_are_read_whole_or_by_range_and_never_served_as_pages(self):
        self.team()
        content = bytes(range(256)) * 40
        (self.common / 'page <b>.html').write_bytes(b'<script>alert(1)</script>')
        (self.common / 'grand.bin').write_bytes(content)
        (self.common / 'Dossier').mkdir()
        password = self.device('camille')
        base = '/dav/files/Fichiers partagés/'
        status, headers, data = self.dav('GET', base + 'grand.bin', 'camille', password)
        self.assertEqual((status, data, headers['Content-Length'], headers['Accept-Ranges']), (200, content, str(len(content)), 'bytes'))
        tag = headers['ETag']
        self.assertRegex(tag, r'^"[0-9a-f]+-2800"$')
        # Une page n'est jamais rendue : pièce jointe, type non deviné par le navigateur.
        status, headers, data = self.dav('GET', base + 'page <b>.html', 'camille', password)
        self.assertEqual((status, headers['X-Content-Type-Options'], headers['Content-Disposition']), (200, 'nosniff', "attachment; filename*=UTF-8''page%20%3Cb%3E.html"))
        # HEAD : les mêmes en-têtes, sans contenu.
        status, headers, data = self.dav('HEAD', base + 'grand.bin', 'camille', password)
        self.assertEqual((status, headers['Content-Length'], headers['ETag'], data), (200, str(len(content)), tag, b''))
        # Plages : début, milieu, fin, au-delà ; une plage ne vaut que pour le fichier qu'on avait.
        for asked, expected, span in (('bytes=0-9', content[:10], 'bytes 0-9/10240'), ('bytes=100-', content[100:], 'bytes 100-10239/10240'), ('bytes=-5', content[-5:], 'bytes 10235-10239/10240'),
                                      ('bytes=10230-99999', content[10230:], 'bytes 10230-10239/10240')):
            status, headers, data = self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': asked})
            self.assertEqual((status, data, headers['Content-Range']), (206, expected, span), asked)
        status, headers, _ = self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': 'bytes=20000-'})
        self.assertEqual((status, headers['Content-Range']), (416, 'bytes */10240'))
        for odd in ('bytes=5-2', ):
            self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': odd})[0], 416)
        for ignored in ('octets=0-9', 'bytes=0-9,20-29', 'bytes=-', 'x'):
            self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': ignored})[0:3:2], (200, content), ignored)
        self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': 'bytes=0-9', 'If-Range': '"autre"'})[0:3:2], (200, content))
        self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': 'bytes=0-9', 'If-Range': tag})[0], 206)
        # Inchangé depuis la dernière lecture : rien n'est renvoyé. Par la marque du fichier (seule, en liste, faible) ou, pour les clients qui ne
        # connaissent que les dates, par sa date.
        status, headers, data = self.dav('GET', base + 'grand.bin', 'camille', password, headers={'If-None-Match': tag})
        self.assertEqual((status, data, headers['ETag']), (304, b'', tag))
        dated = headers['Last-Modified']
        for same in ({'If-None-Match': f'"autre", W/{tag}'}, {'If-None-Match': '*'}, {'If-Modified-Since': dated}):
            self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers=same)[0], 304, same)
        for changed in ({'If-None-Match': '"autre"'}, {'If-None-Match': '"autre"', 'If-Modified-Since': dated}, {'If-Modified-Since': 'Mon, 01 Jan 2001 00:00:00 GMT'}, {'If-Modified-Since': 'pas une date'}):
            self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers=changed)[0], 200, changed)
        self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers={'Range': 'bytes=0-9', 'If-Range': dated})[0], 206)
        os.utime(self.common / 'grand.bin', (1_700_000_000, 1_700_000_000))
        self.assertEqual(self.dav('GET', base + 'grand.bin', 'camille', password, headers={'If-None-Match': tag})[0], 200)
        # Un dossier ne se télécharge pas, un fichier absent se dit, une méthode d'écriture n'existe pas encore.
        for path in (base, base + 'Dossier', '/dav/', '/dav/files/'):
            status, headers, _ = self.dav('GET', path, 'camille', password)
            self.assertEqual((status, headers.get('Allow')), (405, 'OPTIONS, PROPFIND, GET, HEAD'), path)
        self.assertEqual(self.dav('GET', base + 'absent.txt', 'camille', password)[0], 404)
        status, headers, _ = self.dav('OPTIONS', '/dav/', 'camille', password)
        self.assertEqual((status, headers['DAV'], headers['Allow']), (200, '1', 'OPTIONS, PROPFIND, GET, HEAD'))
        for method in ('PUT', 'DELETE', 'MKCOL', 'MOVE', 'COPY', 'PROPPATCH', 'LOCK'):
            self.assertIn(self.dav(method, base + 'grand.bin', 'camille', password, b'x' if method == 'PUT' else None)[0], (405, 501), method)
        self.assertEqual((self.common / 'grand.bin').read_bytes(), content)
        # Le reste de la console ne change pas : HEAD hors de /dav/ n'existe toujours pas, GET de la page d'accueil répond.
        self.assertEqual(self.request('GET', '/')[0], 200)

    def test_changing_the_password_or_removing_double_authentication_removes_every_device(self):
        self.team()
        first, second = self.device('camille', 'Un'), self.device('camille', 'Deux')
        other = self.device('bruno')
        ok = lambda who, secret: self.dav('PROPFIND', '/dav/', who, secret, headers={'Depth': '0'})[0]
        self.assertEqual((ok('camille', first), ok('camille', second), ok('bruno', other)), (207, 207, 207))
        self.assertEqual(self.post('camille', '/api/account/password', {'current': PASSWORD, 'password': 'motdepasse motdepasse'})[0], 200)
        devices.FAILED.clear()
        self.assertEqual((ok('camille', first), ok('camille', second), ok('bruno', other)), (401, 401, 207))
        self.assertEqual(self.get('camille', '/api/account')[1]['devices'], [])
        self.assertIn(('camille', 'Appareils retirés', '2 · mot de passe changé'), self.audit())
        # Un administrateur voit combien d'appareils chacun a, et la remise à zéro de la double authentification les retire.
        people = {p['name']: p for p in self.get('admin', '/api/spaces')[1]['people']}
        self.assertEqual((people['bruno']['devices'], people['camille']['devices']), (1, 0))
        self.assertEqual(self.post('bruno', '/api/account/totp/start', {'password': PASSWORD})[0], 200)
        with app.database() as db:
            secret = totp.state(db, 'bruno')['pending']
        self.assertEqual(self.post('bruno', '/api/account/totp/confirm', {'code': totp.code(secret, int(time.time() // 30))})[0], 200)
        # Activer la double authentification ferme les autres sessions : les appareils partent avec elles.
        self.assertEqual(ok('bruno', other), 401)
        self.assertIn(('bruno', 'Appareils retirés', '1 · double authentification activée'), self.audit())
        other = self.post('bruno', '/api/account/devices/create', {'password': PASSWORD, 'name': 'Poste', 'code': totp.code(secret, int(time.time() // 30) + 1)})[1]['password']
        self.assertEqual(ok('bruno', other), 207)
        self.assertEqual(self.post('admin', '/api/spaces/totp-reset', {'name': 'bruno'})[0], 200)
        devices.FAILED.clear()
        self.assertEqual(ok('bruno', other), 401)
        self.assertIn(('admin', 'Appareils retirés', '1 · double authentification retirée (bruno)'), self.audit())
        # Un appareil retiré pendant qu'il fait sa première requête de l'heure ne revient pas : noter son dernier usage ne recrée rien.
        mine = self.device('dora', 'Tablette')
        ident = self.get('dora', '/api/account')[1]['devices'][0]['id']
        real = devices.spaces.get

        def read_then_revoked(db, key, default=None):
            found = real(db, key, default)
            if isinstance(key, str) and key.startswith('device:') and found:
                with app.database() as other_db:
                    other_db.execute('DELETE FROM settings WHERE key=?', (key,))
            return found
        with unittest.mock.patch.object(devices.spaces, 'get', side_effect=read_then_revoked):
            self.assertEqual(ok('dora', mine), 401)
        devices.FAILED.clear()
        self.assertEqual((ok('dora', mine), self.get('dora', '/api/account')[1]['devices']), (401, []))
        del ident


if __name__ == '__main__':
    unittest.main()
