"""Liens de partage : création par qui écrit, lecture sans compte bornée à la cible, extinction. Vrai serveur."""
import http.client
import json
import os
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import quote

import test_spaces
import links
import spaces

app = test_spaces.app


class LinkTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home, upload, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home', 'upload', 'audit'))

    def team(self):
        self.people(camille='member', bruno='member', lecteur='viewer')
        status, made = self.post('admin', '/api/spaces/space', {'name': 'Chantier', 'members': {'camille': 'write', 'bruno': 'read'}})
        self.assertEqual(status, 200)
        self.space = made['id']
        self.assertEqual(self.post('camille', '/api/folder', {'area': self.space, 'name': 'Plans'})[0], 200)
        self.assertEqual(self.post('camille', '/api/folder', {'area': self.space, 'path': 'Plans', 'name': 'Etage'})[0], 200)
        self.assertEqual(self.upload('camille', self.space, 'devis.pdf', b'devis')[0], 200)
        self.assertEqual(self.upload('camille', self.space, 'facade.png', b'image', path='Plans')[0], 200)
        self.assertEqual(self.upload('camille', self.space, 'niveau1.txt', b'niveau', path='Plans/Etage')[0], 200)
        self.assertEqual(self.upload('camille', self.space, 'autre.txt', b'ailleurs')[0], 200)
        (Path(app.ROOT) / 'data/espaces' / self.space[7:] / 'Plans/.cache').write_bytes(b'interne')

    def visit(self, path, method='GET', body=None, cookie=None):
        """Requête sans compte : (code, en-têtes, contenu)."""
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        headers = {'Content-Type': 'application/json'}
        if cookie:
            headers['Cookie'] = cookie
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def share(self, who, path, days=7, password=''):
        status, made = self.post(who, '/api/links/create', {'area': self.space, 'path': path, 'days': days, 'password': password})
        self.assertEqual(status, 200, made)
        return made['url'][3:]

    def test_file_link_is_read_without_an_account_until_revoked(self):
        self.team()
        status, made = self.post('camille', '/api/links/create', {'area': self.space, 'path': 'devis.pdf', 'days': 7})
        self.assertEqual((status, made['name']), (200, 'devis.pdf'))
        self.assertRegex(made['url'], r'^/p/[A-Za-z0-9_-]{43}$')
        self.assertAlmostEqual(made['expires'], time.time() + 7 * 86400, delta=30)
        token = made['url'][3:]
        # Le jeton n'est écrit nulle part : seule son empreinte l'est.
        with app.database() as db:
            stored = json.dumps([tuple(r) for r in db.execute('SELECT key,value FROM settings')])
        self.assertNotIn(token, stored); self.assertIn(links.digest(token), stored)
        status, headers, page = self.visit('/p/' + token)
        self.assertEqual(status, 200); self.assertIn(b'/public.js', page); self.assertNotIn(token.encode(), page)
        status, _, data = self.visit('/api/public/' + token)
        info = json.loads(data)
        self.assertEqual((status, info['name'], info['directory'], info['protected'], info['locked'], info['size']), (200, 'devis.pdf', False, False, False, 5))
        self.assertNotIn('area', info); self.assertNotIn(self.space, data.decode())
        self.assertEqual(self.visit(f'/api/public/{token}/download')[::2], (200, b'devis'))
        # Un lien de fichier ne désigne que ce fichier.
        for path in ('autre.txt', '../autre.txt', 'Plans'):
            self.assertIn(self.visit(f'/api/public/{token}/download?path={quote(path)}')[0], (403, 404), path)
        self.assertEqual(self.visit(f'/api/public/{token}/archive')[0], 404)
        listed = self.get('camille', '/api/links')[1]
        self.assertEqual([(l['name'], l['space'], l['by'], l['expired'], l['protected'], l['uses']) for l in listed['links']], [('devis.pdf', 'Chantier', 'camille', False, False, 1)])
        self.assertEqual(self.audit()[-2:], [('camille', 'Lien de partage créé', 'Chantier : devis.pdf · 7 jour(s)'), ('lien', 'Lien de partage utilisé', 'Chantier : devis.pdf')])
        # Révoqué : le lien répond comme s'il n'avait jamais existé, et un jeton inconnu répond de même.
        self.assertEqual(self.post('camille', '/api/links/revoke', {'id': listed['links'][0]['id']})[0], 200)
        gone = self.visit('/api/public/' + token)
        self.assertEqual((gone[0], json.loads(gone[2])['error']), (404, links.GONE))
        self.assertEqual(self.visit('/api/public/' + 'x' * 43)[::2], gone[::2])
        self.assertEqual(self.visit(f'/api/public/{token}/download')[0], 404)
        self.assertEqual(self.get('camille', '/api/links')[1]['links'], [])
        for bad in ('/api/public/', '/api/public/court', f'/api/public/{token}/autre', f'/api/public/{token}/download/x'):
            self.assertEqual(self.visit(bad)[0], 404, bad)

    def test_folder_link_stays_inside_its_folder(self):
        self.team()
        token = self.share('camille', 'Plans', days=1)
        info = json.loads(self.visit('/api/public/' + token)[2])
        self.assertEqual((info['name'], info['directory'], info['path']), ('Plans', True, ''))
        self.assertEqual([(i['name'], i['directory']) for i in info['items']], [('Etage', True), ('facade.png', False)])
        inner = json.loads(self.visit(f'/api/public/{token}?path=Etage')[2])
        self.assertEqual((inner['path'], [i['name'] for i in inner['items']]), ('Etage', ['niveau1.txt']))
        self.assertEqual(self.visit(f'/api/public/{token}/download?path=Etage/niveau1.txt')[::2], (200, b'niveau'))
        self.assertEqual(self.visit(f'/api/public/{token}/download?path=facade.png')[::2], (200, b'image'))
        status, headers, archive = self.visit(f'/api/public/{token}/archive')
        self.assertEqual((status, archive[:2]), (200, b'PK')); self.assertIn(b'Plans/Etage/niveau1.txt', archive); self.assertNotIn(b'devis', archive)
        # Rien hors du dossier, aucun fichier caché, aucun dossier interne.
        for path in ('../devis.pdf', '..', 'Etage/../../devis.pdf', '/etc/passwd', '.cache', 'Etage/.x', '.nacre-trash', 'absent.txt', 'Etage/absent'):
            for action in ('', '/download'):
                self.assertIn(self.visit(f'/api/public/{token}{action}?path={quote(path)}')[0], (400, 403, 404), (action, path))
        self.assertEqual(self.visit(f'/api/public/{token}/download?path=Etage')[0], 400)
        # Le visiteur n'a pas de session : la console lui reste fermée.
        self.assertEqual(self.visit('/api/areas')[0], 401)
        self.assertEqual(self.visit(f'/api/files?area={self.space}')[0], 401)
        self.assertEqual(self.visit('/api/public/' + token, method='POST', body={})[0], 404)

    def test_password_protects_a_link_and_attempts_are_limited(self):
        self.team()
        token = self.share('camille', 'devis.pdf', password='mot-de-passe-du-lien')
        info = json.loads(self.visit('/api/public/' + token)[2])
        self.assertEqual((info['protected'], info['locked'], 'size' in info), (True, True, False))
        self.assertEqual(self.visit(f'/api/public/{token}/download')[0], 403)
        self.assertEqual(self.visit(f'/api/public/{token}/unlock', 'POST', {'password': 'faux'})[0], 403)
        self.assertEqual(self.visit(f'/api/public/{token}/unlock', 'POST', {})[0], 403)
        status, headers, _ = self.visit(f'/api/public/{token}/unlock', 'POST', {'password': 'mot-de-passe-du-lien'})
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie']
        self.assertRegex(cookie, r'^nacre_link=[A-Za-z0-9_-]{43}; HttpOnly; SameSite=Strict; Path=/api/public/; Max-Age=3600$')
        proof = cookie.split(';')[0]
        self.assertEqual(json.loads(self.visit('/api/public/' + token, cookie=proof)[2])['locked'], False)
        self.assertEqual(self.visit(f'/api/public/{token}/download', cookie=proof)[::2], (200, b'devis'))
        # La preuve d'un lien n'ouvre pas un autre lien protégé.
        other = self.share('camille', 'autre.txt', password='un-autre-mot-de-passe')
        self.assertEqual(self.visit(f'/api/public/{other}/download', cookie=proof)[0], 403)
        self.assertEqual(self.visit(f'/api/public/{token}/download', cookie='nacre_link=' + 'x' * 43)[0], 403)
        with app.database() as db:
            self.assertNotIn('mot-de-passe-du-lien', json.dumps([tuple(r) for r in db.execute('SELECT value FROM settings')]))
        self.assertTrue(self.get('camille', '/api/links')[1]['links'][-1]['protected'])
        codes = [self.visit(f'/api/public/{token}/unlock', 'POST', {'password': 'faux'})[0] for _ in range(9)]
        self.assertEqual((codes[0], codes[-1]), (403, 429))

    def test_only_who_writes_creates_and_only_valid_targets_are_shared(self):
        self.team()
        body = {'area': self.space, 'path': 'devis.pdf', 'days': 7}
        self.assertEqual(self.post('bruno', '/api/links/create', body)[0], 403)
        self.assertEqual(self.post('lecteur', '/api/links/create', body)[0], 403)
        self.assertEqual(self.get('lecteur', '/api/links')[0], 403)
        os.symlink('/etc/passwd', Path(app.ROOT) / 'data/espaces' / self.space[7:] / 'raccourci')
        for change, expected in (({'area': 'video'}, 403), ({'area': 'sauvegardes'}, 403), ({'area': 'espace_' + '0' * 12}, 403), ({'area': 7}, 403), ({'path': ''}, 400), ({'path': '../x'}, 403),
                                 ({'path': 'absent.txt'}, 404), ({'path': 'raccourci'}, 400), ({'days': 5}, 400), ({'days': True}, 400), ({'days': '7'}, 400), ({'password': 'court'}, 400), ({'password': 7}, 400)):
            status, data = self.post('camille', '/api/links/create', {**body, **change})
            self.assertEqual(status, expected, (change, data))
        self.assertEqual(self.get('camille', '/api/links')[1]['links'], [])
        # L'administrateur partage dans l'espace commun ; un membre n'y écrit pas par défaut, donc n'y partage pas.
        (Path(app.ROOT) / 'data/fichiers/notice.txt').write_bytes(b'notice')
        common = {'area': 'fichiers', 'path': 'notice.txt', 'days': 30}
        self.assertEqual(self.post('camille', '/api/links/create', common)[0], 403)
        status, made = self.post('admin', '/api/links/create', common)
        self.assertEqual(status, 200)
        self.assertEqual(self.visit(f'/api/public/{made["url"][3:]}/download')[::2], (200, b'notice'))
        with unittest.mock.patch.object(links, 'PER_PERSON', 1):
            self.assertEqual(self.post('admin', '/api/links/create', common)[0], 409)

    def test_link_dies_with_its_term_its_target_or_its_author_access(self):
        self.team()
        token = self.share('camille', 'devis.pdf')
        alive = lambda: self.visit('/api/public/' + token)[0]
        self.assertEqual(alive(), 200)
        # L'auteur perd l'accès à l'espace : ses liens s'éteignent, et se rallument s'il le retrouve.
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': self.space, 'name': 'Chantier', 'members': {'bruno': 'read'}})[0], 200)
        self.assertEqual(alive(), 404)
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': self.space, 'name': 'Chantier', 'members': {'camille': 'read'}})[0], 200)
        self.assertEqual(alive(), 200)
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': False})[0], 200)
        self.assertEqual(alive(), 404)
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': True})[0], 200)
        self.sessions['camille'] = app.make_session('camille')
        self.assertEqual(alive(), 200)
        # La cible disparaît : même refus.
        (Path(app.ROOT) / 'data/espaces' / self.space[7:] / 'devis.pdf').rename(Path(app.ROOT) / 'data/espaces' / self.space[7:] / 'devis-v2.pdf')
        self.assertEqual(alive(), 404)
        (Path(app.ROOT) / 'data/espaces' / self.space[7:] / 'devis-v2.pdf').rename(Path(app.ROOT) / 'data/espaces' / self.space[7:] / 'devis.pdf')
        # L'échéance passe : le lien reste listé « échu » trente jours, puis disparaît.
        key = 'link:' + links.digest(token)
        def age(seconds):
            with app.database() as db:
                doc = spaces.get(db, key); doc['expires'] = time.time() - seconds; spaces.put(db, key, doc)
        age(5)
        self.assertEqual(alive(), 404)
        self.assertEqual([l['expired'] for l in self.get('camille', '/api/links')[1]['links']], [True])
        age(31 * 86400)
        self.assertEqual(self.get('camille', '/api/links')[1]['links'], [])
        with app.database() as db:
            self.assertIsNone(spaces.get(db, key))

    def test_each_person_manages_their_links_and_personal_names_stay_private(self):
        self.team()
        mine = self.home('camille')
        self.assertEqual(self.upload('camille', mine, 'bulletin-secret.pdf')[0], 200)
        status, made = self.post('camille', '/api/links/create', {'area': mine, 'path': 'bulletin-secret.pdf', 'days': 1})
        self.assertEqual(status, 200)
        self.share('camille', 'devis.pdf')
        own = self.get('camille', '/api/links')[1]['links']
        self.assertEqual(sorted((l['name'], l['space']) for l in own), [('bulletin-secret.pdf', 'Espace personnel'), ('devis.pdf', 'Chantier')])
        self.assertEqual(self.get('bruno', '/api/links')[1]['links'], [])
        everyone = self.get('admin', '/api/links')[1]['links']
        self.assertEqual(sorted((l['name'], l['path'], l['space'], l['by']) for l in everyone), [('devis.pdf', 'devis.pdf', 'Chantier', 'camille'), ('espace personnel', '', 'Espace personnel', 'camille')])
        self.assertNotIn('secret', json.dumps(everyone)); self.assertNotIn('secret', json.dumps(self.audit()))
        self.assertEqual(self.visit(f'/api/public/{made["url"][3:]}/download')[0], 200)
        self.assertNotIn('secret', json.dumps(self.audit()))
        # Un membre ne révoque que les siens ; un administrateur les révoque tous.
        target = next(l['id'] for l in own if l['name'] == 'devis.pdf')
        self.assertEqual(self.post('bruno', '/api/links/revoke', {'id': target})[0], 404)
        self.assertEqual(self.post('bruno', '/api/links/revoke', {'id': 7})[0], 400)
        self.assertEqual(self.post('admin', '/api/links/revoke', {'id': target})[0], 200)
        self.assertEqual(len(self.get('camille', '/api/links')[1]['links']), 1)


if __name__ == '__main__':
    unittest.main()
