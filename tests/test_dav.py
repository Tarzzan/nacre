"""Appareils et WebDAV en lecture : un mot de passe par appareil, aucun droit avant lui, les droits de la personne après."""
import base64
import http.client
import os
import socket
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
            self.assertEqual((status, headers.get('Allow')), (405, 'OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE, MKCOL, MOVE, COPY'), path)
        self.assertEqual(self.dav('GET', base + 'absent.txt', 'camille', password)[0], 404)
        status, headers, _ = self.dav('OPTIONS', '/dav/', 'camille', password)
        self.assertEqual((status, headers['DAV'], headers['Allow']), (200, '1', 'OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE, MKCOL, MOVE, COPY'))
        # Un appareil en lecture n'écrit pas ; les verrous et les propriétés à écrire n'existent pas encore.
        for method in ('PUT', 'DELETE', 'MKCOL', 'MOVE', 'COPY'):
            self.assertEqual(self.dav(method, base + 'grand.bin', 'camille', password, b'x' if method == 'PUT' else None, {'Destination': base + 'autre.bin'})[0], 403, method)
        for method in ('PROPPATCH', 'LOCK', 'UNLOCK'):
            self.assertEqual(self.dav(method, base + 'grand.bin', 'camille', password)[0], 405, method)
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

    def writer(self, who='camille', name='Portable'):
        return self.device(who, name, write=True)

    def leftovers(self):
        return sorted(str(p.relative_to(app.ROOT)) for p in Path(app.ROOT, 'data').rglob('.nacre-upload-*'))

    def versions(self, who, area, path):
        return self.get(who, f'/api/files/versions?area={area}&path={quote(path)}')[1]['versions']

    def test_a_device_writes_only_where_its_person_may_and_only_if_it_was_given_writing(self):
        self.team()
        (self.team_dir / 'notes.txt').write_text('équipe')
        reader, writer = self.device('camille', 'Liseuse'), self.writer()
        base, mine = '/dav/files/Chantier école/', '/dav/files/Mon espace/'
        # Appareil en lecture : aucune écriture, quelle qu'elle soit, et rien n'est créé.
        for method, path, extra in (('PUT', base + 'neuf.txt', {}), ('MKCOL', base + 'Dossier', {}), ('DELETE', base + 'notes.txt', {}),
                                    ('MOVE', base + 'notes.txt', {'Destination': base + 'autre.txt'}), ('COPY', base + 'notes.txt', {'Destination': base + 'copie.txt'})):
            status, _, _ = self.dav(method, path, 'camille', reader, b'x' if method == 'PUT' else None, extra)
            self.assertEqual(status, 403, method)
        self.assertEqual(sorted(p.name for p in self.team_dir.iterdir() if not p.name.startswith('.nacre-')), ['notes.txt'])
        # Appareil en écriture : là où la personne écrit. Lecteur d'une équipe, compte en lecture seule, espace commun en lecture : refus.
        self.assertEqual(self.dav('PUT', base + 'neuf.txt', 'camille', writer, b'bonjour')[0], 201)
        self.assertEqual(self.dav('PUT', mine + 'journal.md', 'camille', writer, b'personnel')[0], 201)
        self.assertEqual(self.dav('PUT', '/dav/files/Fichiers partagés/x.txt', 'camille', writer, b'x')[0], 403)
        bruno, lecteur = self.writer('bruno'), self.writer('lecteur')
        self.assertEqual(self.dav('PUT', base + 'de-bruno.txt', 'bruno', bruno, b'x')[0], 403)
        self.assertEqual(self.dav('PUT', '/dav/files/Fichiers partagés/x.txt', 'lecteur', lecteur, b'x')[0], 403)
        self.assertEqual(self.dav('DELETE', base + 'neuf.txt', 'bruno', bruno)[0], 403)
        self.assertEqual(self.dav('PUT', '/dav/files/Mon espace/chez-camille.txt', 'bruno', bruno, b'x')[0], 201)   # le sien, pas celui de camille
        self.assertFalse((self.mine_dir / 'chez-camille.txt').exists())
        # Ni la racine, ni la liste des espaces, ni un espace ne se créent, ne se retirent ou ne se renomment d'ici.
        for method, path, extra in (('PUT', '/dav/x.txt', {}), ('PUT', '/dav/files/x.txt', {}), ('MKCOL', '/dav/files/Nouvel espace', {}), ('DELETE', '/dav/files/Chantier école', {}),
                                    ('DELETE', '/dav/files/', {}), ('MOVE', '/dav/files/Chantier école', {'Destination': '/dav/files/Autre'}),
                                    ('MOVE', base + 'neuf.txt', {'Destination': '/dav/files/Autre'}), ('COPY', base + 'neuf.txt', {'Destination': '/dav/principals/x'})):
            self.assertEqual(self.dav(method, path, 'camille', writer, b'x' if method == 'PUT' else None, extra)[0], 403, (method, path))
        self.assertTrue(self.team_dir.is_dir())
        # Sans mot de passe d'appareil : rien, et le contenu envoyé n'est pas lu.
        for method in ('PUT', 'MKCOL', 'DELETE', 'MOVE', 'COPY'):
            self.assertEqual(self.dav(method, base + 'intrus.txt', body=b'x' if method == 'PUT' else None)[0], 401, method)
        self.assertFalse((self.team_dir / 'intrus.txt').exists())
        status, headers, _ = self.dav('OPTIONS', '/dav/', 'camille', writer)
        self.assertEqual(headers['Allow'], 'OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE, MKCOL, MOVE, COPY')
        self.assertEqual(self.leftovers(), [])
        self.assertIn(('camille', 'Fichiers modifiés par un appareil', 'Portable · 1 opération'), self.audit())

    def test_a_put_replaces_in_one_go_keeps_the_old_content_as_a_version_and_honours_conditions(self):
        self.team()
        writer = self.writer()
        base = '/dav/files/Chantier école/'
        status, headers, _ = self.dav('PUT', base + 'devis.txt', 'camille', writer, b'contenu un', {'X-OC-Mtime': '1700000000'})
        self.assertEqual((status, headers.get('X-OC-Mtime')), (201, 'accepted'))
        target = self.team_dir / 'devis.txt'
        self.assertEqual((target.read_bytes(), int(target.stat().st_mtime), target.stat().st_mode & 0o777), (b'contenu un', 1700000000, 0o660))
        first = headers['ETag']
        self.assertEqual(self.dav('HEAD', base + 'devis.txt', 'camille', writer)[1]['ETag'], first)
        # Remplacement : l'ancien contenu devient une version, au nom de la personne ; le même appareil qui renvoie aussitôt n'en empile pas d'autres.
        status, headers, _ = self.dav('PUT', base + 'devis.txt', 'camille', writer, b'contenu deux')
        self.assertEqual((status, target.read_bytes()), (204, b'contenu deux'))
        self.assertEqual([(v['size'], v['by']) for v in self.versions('camille', self.space, 'devis.txt')], [(10, 'camille')])
        self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'contenu trois')[0], 204)
        self.assertEqual(len(self.versions('camille', self.space, 'devis.txt')), 1)
        # Un contenu venu d'ailleurs entre-temps est gardé, lui.
        target.write_bytes(b'venu d ailleurs')
        self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'contenu quatre')[0], 204)
        self.assertEqual([v['size'] for v in self.versions('camille', self.space, 'devis.txt')], [15, 10])
        # Conditions du client : ne créer que si rien n'existe ; ne remplacer que la version qu'il connaît.
        current = self.dav('HEAD', base + 'devis.txt', 'camille', writer)[1]['ETag']
        self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'x', {'If-None-Match': '*'})[0], 412)
        self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'x', {'If-Match': first})[0], 412)
        self.assertEqual(self.dav('PUT', base + 'absent.txt', 'camille', writer, b'x', {'If-Match': first})[0], 412)
        self.assertEqual(target.read_bytes(), b'contenu quatre')
        self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'contenu cinq', {'If-Match': current})[0], 204)
        self.assertEqual(self.dav('PUT', base + 'neuf.txt', 'camille', writer, b'x', {'If-None-Match': '*'})[0], 201)
        # Envoi « en morceaux », sans longueur annoncée : même résultat.
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        basic = {'Authorization': 'Basic ' + base64.b64encode(f'camille:{writer}'.encode()).decode()}
        conn.request('PUT', quote(base + 'flux.bin'), iter([b'abc', b'', b'defgh', b'i' * 70000]), basic, encode_chunked=True)
        response = conn.getresponse(); response.read()
        self.assertEqual(response.status, 201)
        conn.request('PROPFIND', '/dav/', None, {**basic, 'Depth': '0'})   # la connexion reste utilisable : le corps a été lu en entier
        again = conn.getresponse(); again.read(); conn.close()
        self.assertEqual((again.status, (self.team_dir / 'flux.bin').read_bytes()), (207, b'abcdefgh' + b'i' * 70000))
        # Noms : les fichiers à point sont admis (un outil en porte), jamais les dossiers internes ni un nom illisible.
        self.assertEqual(self.dav('PUT', base + '.gitignore', 'camille', writer, b'*.tmp')[0], 201)
        for name in ('.nacre-versions/x', '.nacre-upload-abc', 'a\x07b.txt', ' espace.txt', '..'):
            self.assertIn(self.dav('PUT', base + name, 'camille', writer, b'x')[0], (403, 404), name)
        # Dossier parent absent : conflit. Sur un dossier : refus. Envoi ambigu ou sans longueur : refus.
        self.assertEqual(self.dav('PUT', base + 'Absent/x.txt', 'camille', writer, b'x')[0], 409)
        (self.team_dir / 'Dossier').mkdir()
        self.assertEqual(self.dav('PUT', base + 'Dossier', 'camille', writer, b'x')[0], 405)
        def raw_put(name, extra, body):
            sock = socket.create_connection(('127.0.0.1', self.http.server_port), timeout=5)
            sock.sendall((f'PUT {quote(base + name)} HTTP/1.1\r\nHost: 127.0.0.1:{self.http.server_port}\r\nAuthorization: {basic["Authorization"]}\r\n{extra}\r\n').encode() + body)
            answer = sock.recv(4096); sock.close()
            return answer[:12]
        self.assertEqual(raw_put('ambigu.txt', 'Content-Length: 1\r\nTransfer-Encoding: chunked\r\n', b'x'), b'HTTP/1.1 400')
        self.assertEqual(raw_put('illisible.txt', 'Transfer-Encoding: chunked\r\n', b'zz\r\nabc\r\n0\r\n\r\n'), b'HTTP/1.1 400')
        self.assertEqual(raw_put('autre.txt', 'Transfer-Encoding: gzip\r\n', b'x'), b'HTTP/1.1 400')
        self.assertEqual(raw_put('sans.txt', '', b''), b'HTTP/1.1 411')
        self.assertFalse(any((self.team_dir / n).exists() for n in ('ambigu.txt', 'illisible.txt', 'autre.txt', 'sans.txt')))
        # Volume plein : dit, et rien ne reste. Envoi coupé en route : rien ne reste non plus, l'ancien contenu est intact.
        with unittest.mock.patch.object(app, 'available_bytes', return_value=3):
            self.assertEqual(self.dav('PUT', base + 'trop.bin', 'camille', writer, b'x' * 100)[0], 507)
        raw = socket.create_connection(('127.0.0.1', self.http.server_port), timeout=5)
        raw.sendall((f'PUT {quote(base + "devis.txt")} HTTP/1.1\r\nHost: 127.0.0.1:{self.http.server_port}\r\nAuthorization: {basic["Authorization"]}\r\n'
                     'Content-Length: 1000\r\n\r\n').encode() + b'partiel')
        raw.shutdown(socket.SHUT_WR); raw.recv(4096); raw.close()
        time.sleep(.2)
        self.assertEqual((target.read_bytes(), (self.team_dir / 'trop.bin').exists()), (b'contenu cinq', False))
        self.assertEqual(self.leftovers(), [])

    def test_the_go_ahead_for_a_large_send_comes_only_after_the_rights_are_checked(self):
        self.team()
        writer = self.writer()

        def attempt(password):
            raw = socket.create_connection(('127.0.0.1', self.http.server_port), timeout=5)
            auth = base64.b64encode(f'camille:{password}'.encode()).decode()
            raw.sendall((f'PUT {quote("/dav/files/Chantier école/gros.bin")} HTTP/1.1\r\nHost: 127.0.0.1:{self.http.server_port}\r\nAuthorization: Basic {auth}\r\n'
                         'Content-Length: 5\r\nExpect: 100-continue\r\n\r\n').encode())
            first = raw.recv(4096)
            if first.startswith(b'HTTP/1.1 100'):
                raw.sendall(b'abcde')
                first += raw.recv(4096)
            raw.close()
            return first
        refused = attempt('faux-faux-faux-faux-faux-faux')
        self.assertTrue(refused.startswith(b'HTTP/1.1 401'), refused[:40])
        self.assertFalse((self.team_dir / 'gros.bin').exists())
        accepted = attempt(writer)
        self.assertTrue(accepted.startswith(b'HTTP/1.1 100'), accepted[:40]); self.assertIn(b'HTTP/1.1 201', accepted)
        self.assertEqual((self.team_dir / 'gros.bin').read_bytes(), b'abcde')

    def test_folders_deletions_moves_and_copies_follow_the_rules_of_the_console(self):
        self.team()
        writer = self.writer()
        base, mine = '/dav/files/Chantier école/', '/dav/files/Mon espace/'
        self.assertEqual(self.dav('MKCOL', base + 'Plans', 'camille', writer)[0], 201)
        self.assertEqual((self.team_dir / 'Plans').stat().st_mode & 0o7777, 0o2770)
        self.assertEqual(self.dav('MKCOL', base + 'Plans', 'camille', writer)[0], 405)
        self.assertEqual(self.dav('MKCOL', base + 'Absent/Sous', 'camille', writer)[0], 409)
        self.assertEqual(self.dav('MKCOL', base + 'Avec corps', 'camille', writer, b'<x/>')[0], 415)
        for name, data in (('a.txt', b'un'), ('b.txt', b'deux'), ('Plans/facade.pdf', b'%PDF')):
            self.assertEqual(self.dav('PUT', base + name, 'camille', writer, data, {'X-OC-Mtime': '1700000000'})[0], 201)
        # Supprimer envoie à la corbeille de l'espace, d'où la console restaure ; un dossier part entier.
        self.assertEqual(self.dav('DELETE', base + 'a.txt', 'camille', writer)[0], 204)
        self.assertEqual(self.dav('DELETE', base + 'a.txt', 'camille', writer)[0], 404)
        self.assertEqual(self.dav('DELETE', base + 'Plans', 'camille', writer)[0], 204)
        trash = self.get('camille', f'/api/trash?area={self.space}')[1]
        trash = trash['items'] if isinstance(trash, dict) else trash
        self.assertEqual(sorted(item['original'] for item in trash), ['Plans', 'a.txt'])
        back = next(item['id'] for item in trash if item['original'] == 'Plans')
        self.assertEqual(self.post('camille', '/api/restore', {'id': back})[0], 200)
        self.assertEqual((self.team_dir / 'Plans/facade.pdf').read_bytes(), b'%PDF')
        # Déplacer : renommer sur place, changer de dossier, changer d'espace ; les versions suivent le fichier dans son espace.
        self.assertEqual(self.dav('PUT', base + 'b.txt', 'camille', writer, b'deux bis')[0], 204)
        self.assertEqual(self.dav('MOVE', base + 'b.txt', 'camille', writer, headers={'Destination': quote(base + 'Plans/b renommé.txt')})[0], 201)
        self.assertEqual(((self.team_dir / 'b.txt').exists(), (self.team_dir / 'Plans/b renommé.txt').read_bytes()), (False, b'deux bis'))
        self.assertEqual([v['size'] for v in self.versions('camille', self.space, 'Plans/b renommé.txt')], [4])
        host = f'http://127.0.0.1:{self.http.server_port}'
        self.assertEqual(self.dav('MOVE', base + 'Plans/facade.pdf', 'camille', writer, headers={'Destination': host + quote(mine + 'facade.pdf')})[0], 201)
        self.assertEqual((self.mine_dir / 'facade.pdf').read_bytes(), b'%PDF')
        # Arrivée occupée : refusée si le client le demande ; sinon remplacée d'un coup, l'ancien contenu gardé comme version.
        self.assertEqual(self.dav('PUT', base + 'c.txt', 'camille', writer, b'neuf')[0], 201)
        self.assertEqual(self.dav('MOVE', base + 'c.txt', 'camille', writer, headers={'Destination': quote(base + 'Plans/b renommé.txt'), 'Overwrite': 'F'})[0], 412)
        self.assertEqual(self.dav('MOVE', base + 'c.txt', 'camille', writer, headers={'Destination': quote(base + 'Plans/b renommé.txt')})[0], 204)
        self.assertEqual((self.team_dir / 'Plans/b renommé.txt').read_bytes(), b'neuf')
        self.assertEqual([v['size'] for v in self.versions('camille', self.space, 'Plans/b renommé.txt')], [8, 4])
        # Copier un fichier : même contenu, même date ; un dossier ne se copie pas d'un geste.
        self.assertEqual(self.dav('COPY', mine + 'facade.pdf', 'camille', writer, headers={'Destination': quote(base + 'copie.pdf')})[0], 201)
        copy = self.team_dir / 'copie.pdf'
        self.assertEqual((copy.read_bytes(), int(copy.stat().st_mtime), (self.mine_dir / 'facade.pdf').exists()), (b'%PDF', 1700000000, True))
        self.assertEqual(self.dav('COPY', mine + 'facade.pdf', 'camille', writer, headers={'Destination': quote(base + 'copie.pdf'), 'Overwrite': 'F'})[0], 412)
        self.assertEqual(self.dav('COPY', base + 'Plans', 'camille', writer, headers={'Destination': quote(base + 'Plans 2')})[0], 403)
        # Refus : dans lui-même, sur lui-même, vers un autre hôte, hors des espaces, sans arrivée, source absente, espace où l'on ne fait que lire.
        for headers, expected in (({'Destination': quote(base + 'Plans/Dedans')}, 409), ({'Destination': quote(base + 'Plans')}, 403), ({'Destination': 'http://ailleurs.exemple' + quote(base + 'X')}, 502),
                                  ({'Destination': '/api/files'}, 403), ({}, 400), ({'Destination': quote('/dav/files/Fichiers partagés/Plans')}, 403)):
            self.assertEqual(self.dav('MOVE', base + 'Plans', 'camille', writer, headers=headers)[0], expected, headers)
        self.assertEqual(self.dav('MOVE', base + 'absent.txt', 'camille', writer, headers={'Destination': quote(base + 'x.txt')})[0], 404)
        (self.common / 'public.txt').write_text('commun')
        self.assertEqual(self.dav('MOVE', '/dav/files/Fichiers partagés/public.txt', 'camille', writer, headers={'Destination': quote(mine + 'pris.txt')})[0], 403)
        self.assertEqual(self.dav('COPY', '/dav/files/Fichiers partagés/public.txt', 'camille', writer, headers={'Destination': quote(mine + 'copie.txt')})[0], 201)   # lire suffit pour copier
        self.assertTrue((self.common / 'public.txt').exists() and (self.team_dir / 'Plans').is_dir())
        self.assertEqual(self.leftovers(), [])

    def raw(self, method, path, password, extra='', body=b'', who='camille'):
        """Requête écrite à la main, pour ce que http.client ne sait pas envoyer. Rend la connexion et le début de la réponse."""
        sock = socket.create_connection(('127.0.0.1', self.http.server_port), timeout=5)
        auth = base64.b64encode(f'{who}:{password}'.encode()).decode()
        sock.sendall(f'{method} {quote(path)} HTTP/1.1\r\nHost: 127.0.0.1:{self.http.server_port}\r\nAuthorization: Basic {auth}\r\n{extra}\r\n'.encode() + body)
        return sock

    def test_what_someone_else_saved_during_a_send_is_never_lost_even_in_a_burst(self):
        self.team()
        writer = self.writer()
        base, target = '/dav/files/Chantier école/', self.team_dir / 'devis.txt'

        def slow(name, body, meanwhile):
            """Envoi suspendu à mi-chemin : `meanwhile` a lieu pendant que le fichier arrive."""
            sock = self.raw('PUT', base + name, writer, f'Content-Length: {len(body)}\r\n', body[:2])
            for _ in range(100):
                if self.leftovers():
                    break
                time.sleep(.02)
            self.assertEqual(len(self.leftovers()), 1)
            meanwhile()
            sock.sendall(body[2:])
            answer = sock.recv(4096); sock.close()
            return answer[:12]
        for body in (b'v1', b'v2 appareil'):
            self.assertIn(self.dav('PUT', base + 'devis.txt', 'camille', writer, body)[0], (201, 204))
        self.assertEqual([v['size'] for v in self.versions('camille', self.space, 'devis.txt')], [2])

        # L'appareil renvoie son fichier coup sur coup (aucune version ne serait gardée), mais un collègue enregistre le sien
        # pendant l'envoi, comme le fait le partage réseau : écrire à côté puis renommer. Son travail rejoint les versions.
        def colleague():
            (self.team_dir / 'devis.tmp').write_bytes(b'TRAVAIL DU COLLEGUE, 30 octets')
            os.rename(self.team_dir / 'devis.tmp', target)
        self.assertEqual(slow('devis.txt', b'v3 appareil!', colleague), b'HTTP/1.1 204')
        self.assertEqual(target.read_bytes(), b'v3 appareil!')
        self.assertEqual([v['size'] for v in self.versions('camille', self.space, 'devis.txt')], [30, 2])
        # Sans personne entre-temps, le renvoi coup sur coup ne remplit toujours pas les versions.
        self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'v4')[0], 204)
        self.assertEqual([v['size'] for v in self.versions('camille', self.space, 'devis.txt')], [30, 2])

        # Le fichier est devenu un dossier pendant l'envoi : le dossier reste visible sous un autre nom, rien ne reste caché.
        def folder():
            target.unlink(); target.mkdir(); (target / 'facade.pdf').write_bytes(b'%PDF')
        self.assertEqual(slow('devis.txt', b'v5 appareil', folder), b'HTTP/1.1 204')
        self.assertEqual(target.read_bytes(), b'v5 appareil')
        aside = [p for p in self.team_dir.iterdir() if p.name.startswith('devis.txt.avant-remplacement-')]
        self.assertEqual([(p.is_dir(), (p / 'facade.pdf').read_bytes()) for p in aside], [(True, b'%PDF')])
        self.assertEqual(self.leftovers(), [])

        # Version rangée mais index non écrit (volume plein) : le dépôt est fait, il est dit fait, rien ne reste caché.
        import versions
        time.sleep(.01)
        with unittest.mock.patch.object(dav, 'SAME', 0), unittest.mock.patch.object(versions, 'save', side_effect=OSError(28, 'plein')):
            self.assertEqual(self.dav('PUT', base + 'devis.txt', 'camille', writer, b'v6')[0], 204)
        self.assertEqual((target.read_bytes(), self.leftovers()), (b'v6', []))

    def test_tools_are_answered_the_way_they_expect(self):
        self.team()
        writer = self.writer()
        base, mine, port = '/dav/files/Chantier école/', '/dav/files/Mon espace/', self.http.server_port
        put = lambda path, body, headers=None: self.dav('PUT', path, 'camille', writer, body, headers)
        move = lambda path, to, **more: self.dav('MOVE', path, 'camille', writer, headers={'Destination': to, **more})[0]
        # Reprise d'envoi : un fragment n'est jamais pris pour le fichier entier.
        self.assertEqual(put(base + 'a.txt', b'entier')[0], 201)
        self.assertEqual(put(base + 'a.txt', b'ier', {'Content-Range': 'bytes 3-5/6'})[0], 400)
        self.assertEqual(put(base + 'neuf.txt', b'ier', {'Content-Range': 'bytes 0-2/3'})[0], 400)
        self.assertEqual(((self.team_dir / 'a.txt').read_bytes(), (self.team_dir / 'neuf.txt').exists()), (b'entier', False))
        # Arrivée d'un déplacement : l'identifiant joint par l'outil et le port retiré par un relais ne changent rien ; un autre hôte, si.
        self.assertEqual(move(base + 'a.txt', f'http://camille@127.0.0.1:{port}' + quote(base + 'b.txt')), 201)
        self.assertEqual(move(base + 'b.txt', 'https://127.0.0.1' + quote(base + 'c.txt')), 201)
        self.assertEqual(move(base + 'c.txt', f'http://ailleurs.exemple:{port}' + quote(base + 'd.txt')), 502)
        self.assertEqual((self.team_dir / 'c.txt').read_bytes(), b'entier')
        # Un nom que Nacre ne donnerait pas, déposé par le partage réseau : refusé à la création, mais il se déplace et se supprime.
        (self.team_dir / 'fin ').write_bytes(b'x'); (self.team_dir / ' début').write_bytes(b'y')
        self.assertEqual(put(base + 'autre ', b'z')[0], 403)
        self.assertEqual(move(base + 'c.txt', quote(base + 'arrivée ')), 403)
        self.assertEqual(move(base + 'fin ', quote(base + 'fin')), 201)
        self.assertEqual(self.dav('DELETE', base + ' début', 'camille', writer)[0], 204)
        self.assertEqual(sorted(p.name for p in self.team_dir.iterdir() if not p.name.startswith('.')), ['c.txt', 'fin'])
        (self.team_dir / '.nacre-versions').mkdir(exist_ok=True)
        for path in (base + '.nacre-versions', base + '.nacre-trash', base + '..', base + 'x/../c.txt'):
            self.assertIn(self.dav('DELETE', path, 'camille', writer)[0], (403, 404), path)
            self.assertIn(move(path, quote(base + 'pris')), (403, 404), path)
        self.assertTrue((self.team_dir / '.nacre-versions').is_dir() and (self.team_dir / 'c.txt').exists())
        # « Créer s'il manque » sur ce qui existe déjà : 405, comme pour tout dossier présent. Un espace ne se crée pas par ici.
        for path in ('/dav/', '/dav/files/', '/dav/files/Chantier école', '/dav/files/Mon espace/'):
            self.assertEqual(self.dav('MKCOL', path, 'camille', writer)[0], 405, path)
        self.assertEqual(self.dav('MKCOL', '/dav/files/Nouvel espace', 'camille', writer)[0], 403)
        # Un élément ne prend pas la place du dossier qui le contient.
        self.assertEqual(self.dav('MKCOL', base + 'Plans', 'camille', writer)[0], 201)
        for name in ('a.txt', 'b.txt'):
            self.assertEqual(put(base + 'Plans/' + name, b'plan')[0], 201)
        self.assertEqual(move(base + 'Plans/a.txt', quote(base + 'Plans')), 409)
        self.assertEqual(sorted(p.name for p in (self.team_dir / 'Plans').iterdir()), ['a.txt', 'b.txt'])
        # Remplacement d'un espace à l'autre : l'ancien contenu de l'arrivée rejoint les versions de son espace, sans passer par l'autre.
        self.assertEqual(put(mine + 'note.txt', b'perso')[0], 201)
        self.assertEqual(put(base + 'note.txt', b'equipe')[0], 201)
        self.assertEqual(move(base + 'note.txt', quote(mine + 'note.txt')), 204)
        self.assertEqual(((self.mine_dir / 'note.txt').read_bytes(), (self.team_dir / 'note.txt').exists()), (b'equipe', False))
        self.assertEqual([v['size'] for v in self.versions('camille', self.mine, 'note.txt')], [5])
        # Dossier sur dossier : l'ancien part à la corbeille, le nouveau prend sa place ; arrivée impossible, rien ne bouge.
        self.assertEqual(self.dav('MKCOL', base + 'Plans 2', 'camille', writer)[0], 201)
        self.assertEqual(put(base + 'Plans 2/c.txt', b'autre')[0], 201)
        self.assertEqual(move(base + 'Plans', quote(base + 'Plans 2')), 204)
        self.assertEqual((sorted(p.name for p in (self.team_dir / 'Plans 2').iterdir()), (self.team_dir / 'Plans').exists()), (['a.txt', 'b.txt'], False))
        trash = self.get('camille', f'/api/trash?area={self.space}')[1]
        self.assertIn('Plans 2', [item['original'] for item in (trash['items'] if isinstance(trash, dict) else trash)])
        with unittest.mock.patch.object(dav, 'discard', side_effect=OSError(5, 'panne')):
            self.assertEqual(put(base + 'occupant', b'fichier')[0], 201)
            self.assertEqual(move(base + 'Plans 2', quote(base + 'occupant')), 503)
        self.assertEqual(((self.team_dir / 'Plans 2').is_dir(), (self.team_dir / 'occupant').read_bytes()), (True, b'fichier'))
        # Date d'avant 1970 gardée : sans cela l'outil renverrait le fichier à chaque passage.
        status, headers, _ = put(base + 'ancien.txt', b'vieux', {'X-OC-Mtime': '-86400'})
        self.assertEqual((status, headers.get('X-OC-Mtime'), int((self.team_dir / 'ancien.txt').stat().st_mtime)), (201, 'accepted', -86400))
        # Tailles de morceaux : des chiffres hexadécimaux, rien qu'un autre lecteur comprendrait autrement.
        for size in (b'+1', b'0x1', b'1_0', b'-1', b''):
            sock = self.raw('PUT', base + 'morceaux.txt', writer, 'Transfer-Encoding: chunked\r\n', size + b'\r\nabcdefghijklmnop\r\n0\r\n\r\n')
            self.assertEqual(sock.recv(4096)[:12], b'HTTP/1.1 400', size); sock.close()
        sock = self.raw('PUT', base + 'morceaux.txt', writer, 'Transfer-Encoding: chunked\r\n', b'A;x=1\r\nabcdefghij\r\n0\r\n\r\n')
        self.assertEqual(sock.recv(4096)[:12], b'HTTP/1.1 201'); sock.close()
        self.assertEqual((self.team_dir / 'morceaux.txt').read_bytes(), b'abcdefghij')
        # Un outil qui attend le feu vert avant tout corps le reçoit aussi pour une liste, une fois reconnu ; et il ne déborde pas sur la requête suivante.
        body = b'<?xml version="1.0"?><propfind xmlns="DAV:"><allprop/></propfind>'
        sock = self.raw('PROPFIND', base, writer, f'Depth: 0\r\nContent-Length: {len(body)}\r\nExpect: 100-continue\r\n')
        self.assertEqual(sock.recv(4096)[:12], b'HTTP/1.1 100')
        sock.sendall(body)
        self.assertEqual(sock.recv(4096)[:12], b'HTTP/1.1 207'); sock.close()
        sock = self.raw('PROPFIND', base, 'faux-faux-faux-faux-faux-faux', f'Depth: 0\r\nContent-Length: {len(body)}\r\nExpect: 100-continue\r\n')
        self.assertEqual(sock.recv(4096)[:12], b'HTTP/1.1 401'); sock.close()
        self.assertEqual(self.leftovers(), [])

    def test_the_journal_follows_what_the_device_did_and_stale_leftovers_are_swept(self):
        self.team()
        writer = self.writer()
        base = '/dav/files/Chantier école/'
        for name in ('a.txt', 'b.txt', 'c.txt'):
            self.assertEqual(self.dav('PUT', base + name, 'camille', writer, b'x')[0], 201)
        self.assertEqual(self.dav('PUT', base + ' refusé', 'camille', writer, b'x')[0], 403)
        for name in ('a.txt', 'b.txt'):
            self.assertEqual(self.dav('DELETE', base + name, 'camille', writer)[0], 204)
        # Une ligne dès la première opération, puis la même ligne tenue à jour : le compte est celui de ce qui a été fait.
        lines = lambda: [detail for who, action, detail in self.audit() if action == 'Fichiers modifiés par un appareil']
        self.assertEqual(len(lines()), 1)
        dav.settle(app)
        self.assertEqual(lines(), ['Portable · 5 opérations, dont 2 suppressions'])
        # Restes d'un envoi interrompu par l'arrêt de la console : retirés au bout d'un jour, à l'occasion d'un dépôt. Un envoi
        # en cours, même daté du passé par l'outil, et un dossier ne sont jamais pris pour des restes.
        stale, folder = self.team_dir / '.nacre-upload-reste', self.team_dir / '.nacre-upload-dossier'
        stale.write_bytes(b'moitie'); os.utime(stale, (1, 1)); folder.mkdir(); (folder / 'x').write_bytes(b'x')
        fd = os.open(self.team_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(dav.sweep(fd, ('essai', 'un')), 0)
            self.assertTrue(stale.exists())
            self.assertEqual(dav.sweep(fd, ('essai', 'un'), now=time.time() + 2 * dav.STALE), 1)
            self.assertEqual(dav.sweep(fd, ('essai', 'un'), now=time.time() + 2 * dav.STALE), 0)   # une fois par jour et par dossier
        finally:
            os.close(fd)
        self.assertEqual((stale.exists(), (folder / 'x').exists(), (self.team_dir / 'c.txt').exists()), (False, True, True))


if __name__ == '__main__':
    unittest.main()
