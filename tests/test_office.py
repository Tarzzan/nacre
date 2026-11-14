"""Suite bureautique : Nacre hôte WOPI. Vrai serveur Nacre ; la suite est un faux serveur qui annonce ses formats,
et l'essai joue son rôle en appelant les routes WOPI avec le jeton délivré."""
import http.client
import io
import json
import threading
import time
import unittest
import unittest.mock
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import test_spaces
import office

app = test_spaces.app
DISCOVERY = '<wopi-discovery><net-zone name="external-http">' + ''.join(
    f'<app name="x"><action ext="{ext}" name="{name}" urlsrc="http://suite.interne:9980/browser/abc123/cool.html?"/></app>'
    for ext, names in (('odt', ('edit', 'view')), ('docx', ('edit',)), ('ods', ('edit',)), ('pdf', ('view_comment',)), ('txt', ('edit',)), ('png', ('view',)))
    for name in names) + '</net-zone></wopi-discovery>'


class Suite(BaseHTTPRequestHandler):
    body = DISCOVERY.encode()

    def log_message(self, *args):
        pass

    def do_GET(self):
        ok = self.path == '/hosting/discovery'
        raw = type(self).body if ok else b'absent'
        self.send_response(200 if ok else 404); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)


class OfficeTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'audit'))

    def team(self, connect=True):
        self.people(camille='member', bruno='member', dora='member', lecteur='viewer')
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.folder = Path(app.ROOT) / 'data/espaces' / self.space[7:]
        Suite.body = DISCOVERY.encode()
        self.suite = ThreadingHTTPServer(('127.0.0.1', 0), Suite)
        threading.Thread(target=self.suite.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.suite.shutdown(), self.suite.server_close()))
        office.CACHE.clear(); office.TOKENS.clear(); office.FILES.clear(); office.WRITTEN.clear(); office.LOADED['done'] = False; office.ORIGIN['until'] = 0
        self.url, self.wopi_base = f'http://127.0.0.1:{self.suite.server_port}', f'http://127.0.0.1:{self.http.server_port}'
        if connect:
            status, data = self.post('admin', '/api/office/configure', {'enabled': True, 'url': 'http://bureau.exemple:9980', 'internal': self.url, 'wopi': self.wopi_base})
            self.assertEqual(status, 200, data)

    def opened(self, who, path):
        status, data = self.post(who, '/api/office/open', {'area': self.space, 'path': path})
        if status != 200:
            return status, data, None, None
        source = unquote(parse_qs(urlsplit(data['action']).query)['WOPISrc'][0])
        return status, data, urlsplit(source).path, data['token']

    def wopi(self, method, path, token, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        conn.request(method, f'{path}?access_token={quote(token)}', body, headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_suite_is_connected_only_when_it_answers_and_its_origin_alone_joins_the_page_policy(self):
        self.team(connect=False)
        status, state = self.get('admin', '/api/office')
        self.assertEqual((status, state['enabled'], state['formats'], state['default_wopi'].startswith('http://127.0.0.1:')), (200, False, [], True))
        good = {'enabled': True, 'url': 'http://bureau.exemple:9980', 'internal': self.url, 'wopi': self.wopi_base}
        for change in ({'url': 'bureau.exemple'}, {'url': 'http://bureau.exemple/chemin'}, {'url': 'ftp://x'}, {'wopi': ''}, {'internal': 'x y'}, {'enabled': 'oui'}, {'url': 'http://a b'}):
            self.assertEqual(self.post('admin', '/api/office/configure', {**good, **change})[0], 400, change)
        # Une suite qui ne répond pas, ou qui répond autre chose, n'est pas raccordée.
        self.assertEqual(self.post('admin', '/api/office/configure', {**good, 'internal': 'http://127.0.0.1:9'})[0], 503)
        for hostile in (b'<!DOCTYPE x [<!ENTITY a "b">]><wopi-discovery/>', b'pas du xml', b'<wopi-discovery/>'):
            Suite.body = hostile
            self.assertEqual(self.post('admin', '/api/office/configure', good)[0], 502, hostile[:20])
        self.assertEqual(self.get('admin', '/api/office')[1]['enabled'], False)
        self.assertTrue(self.headers('/')['Content-Security-Policy'].endswith("form-action 'self'"))
        Suite.body = DISCOVERY.encode()
        status, data = self.post('admin', '/api/office/configure', good)
        # Seuls les formats bureautiques sont proposés : le texte reste à l'éditeur intégré, l'image à l'aperçu.
        self.assertEqual((status, data['formats']), (200, ['docx', 'ods', 'odt']))
        self.assertTrue(self.headers('/')['Content-Security-Policy'].endswith("form-action 'self' http://bureau.exemple:9980"))
        self.assertEqual(self.get('camille', '/api/me')[1]['office'], ['docx', 'ods', 'odt'])
        self.assertEqual(self.audit()[-1], ('admin', 'Suite bureautique raccordée', 'http://bureau.exemple:9980'))
        for who in ('camille', 'lecteur'):
            self.assertEqual(self.get(who, '/api/office')[0], 403)
            self.assertEqual(self.post(who, '/api/office/configure', good)[0], 403)
        # Débranchée : plus de bouton, plus de cible de formulaire.
        self.assertEqual(self.post('admin', '/api/office/configure', {**good, 'enabled': False})[0], 200)
        self.assertEqual(self.get('camille', '/api/me')[1]['office'], [])
        self.assertTrue(self.headers('/')['Content-Security-Policy'].endswith("form-action 'self'"))

    def headers(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        conn.request('GET', path)
        response = conn.getresponse(); response.read(); conn.close()
        return dict(response.getheaders())

    def test_document_is_read_and_saved_by_the_suite_with_a_token_bound_to_one_file_and_one_person(self):
        self.team()
        (self.folder / 'devis.docx').write_bytes(b'contenu un')
        (self.folder / 'autre.odt').write_bytes(b'autre')
        status, data, path, token = self.opened('camille', 'devis.docx')
        self.assertEqual((status, data['write'], data['name']), (200, True, 'devis.docx'))
        # L'éditeur est demandé à l'adresse que voit le navigateur ; Nacre est désigné à l'adresse que voit la suite.
        self.assertTrue(data['action'].startswith('http://bureau.exemple:9980/browser/abc123/cool.html?WOPISrc='))
        self.assertTrue(unquote(data['action']).split('WOPISrc=')[1].startswith(self.wopi_base + '/wopi/files/'))
        self.assertAlmostEqual(data['ttl'] / 1000, time.time() + office.TOKEN_SECONDS, delta=30)
        status, raw = self.wopi('GET', path, token)
        info = json.loads(raw)
        self.assertEqual((status, info['BaseFileName'], info['Size'], info['UserId'], info['UserCanWrite'], info['UserFriendlyName']), (200, 'devis.docx', 10, 'camille', True, 'camille'))
        self.assertRegex(info['LastModifiedTime'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$')
        self.assertNotIn(self.space, raw.decode())
        self.assertEqual(self.wopi('GET', path + '/contents', token), (200, b'contenu un'))
        # Enregistrement : remplacement d'un seul tenant, ancienne version gardée au nom de la personne.
        status, raw = self.wopi('POST', path + '/contents', token, b'contenu deux', {'X-COOL-WOPI-Timestamp': info['LastModifiedTime']})
        self.assertEqual(status, 200)
        fresh = json.loads(raw)['LastModifiedTime']
        self.assertEqual((self.folder / 'devis.docx').read_bytes(), b'contenu deux')
        kept = self.get('camille', f'/api/files/versions?area={self.space}&path=devis.docx')[1]['versions']
        self.assertEqual([(v['size'], v['by']) for v in kept], [(10, 'camille')])
        # Les enregistrements suivants de la séance ne multiplient pas les versions.
        self.assertEqual(self.wopi('POST', path + '/contents', token, b'contenu trois', {'X-COOL-WOPI-Timestamp': fresh})[0], 200)
        self.assertEqual(len(self.get('camille', f'/api/files/versions?area={self.space}&path=devis.docx')[1]['versions']), 1)
        # Fichier changé ailleurs : la suite reçoit le code de conflit, rien n'est écrasé.
        status, raw = self.wopi('POST', path + '/contents', token, b'ecrasement', {'X-COOL-WOPI-Timestamp': fresh})
        self.assertEqual((status, json.loads(raw)['COOLStatusCode']), (409, 1010))
        self.assertEqual((self.folder / 'devis.docx').read_bytes(), b'contenu trois')
        # Contenu venu d'ailleurs, puis « Écraser » dans la suite (enregistrement sans horodatage) : il est gardé comme version.
        (self.folder / 'devis.docx').write_bytes(b'venu d ailleurs')
        self.assertEqual(self.wopi('POST', path + '/contents', token, b'contenu quatre')[0], 200)
        self.assertEqual((self.folder / 'devis.docx').read_bytes(), b'contenu quatre')
        kept = self.get('camille', f'/api/files/versions?area={self.space}&path=devis.docx')[1]['versions']
        self.assertEqual([v['size'] for v in kept], [15, 10])
        # Le jeton ne vaut que pour ce fichier ; un jeton inconnu, une autre route ou un autre fichier sont refusés.
        _, _, other_path, other_token = self.opened('camille', 'autre.odt')
        for bad_path, bad_token in ((other_path, token), (path, other_token), (path, 'x' * 43), (path, ''), ('/wopi/files/' + 'a' * 22, token)):
            self.assertEqual(self.wopi('GET', bad_path, bad_token)[0], 401)
        for odd in ('/wopi/files/', '/wopi/files/../x', path + '/autre', '/wopi/x'):
            self.assertEqual(self.wopi('GET', odd, token)[0], 404, odd)
        self.assertEqual(self.wopi('POST', path, token, b'x')[0], 404)
        self.assertEqual(sorted(n for n in (self.folder).iterdir() if n.name.startswith('.nacre-upload')), [])
        self.assertIn(('camille', 'Document ouvert dans la suite bureautique', 'Chantier : devis.docx'), self.audit())

    def test_rights_are_checked_again_at_every_call(self):
        self.team()
        (self.folder / 'plan.odt').write_bytes(b'plan')
        (self.folder / 'notes.txt').write_bytes(b'texte'); (self.folder / 'image.png').write_bytes(b'png'); (self.folder / 'Dossier.odt').mkdir()
        # Lecteur de l'espace, compte en lecture seule : ouverture en lecture, aucun enregistrement.
        for who in ('bruno',):
            status, data, path, token = self.opened(who, 'plan.odt')
            self.assertEqual((status, data['write']), (200, False))
            self.assertEqual(json.loads(self.wopi('GET', path, token)[1])['UserCanWrite'], False)
            self.assertEqual(self.wopi('POST', path + '/contents', token, b'x')[0], 403)
        self.assertEqual(self.opened('dora', 'plan.odt')[0], 403)
        for name, expected in (('notes.txt', 415), ('image.png', 415), ('Dossier.odt', 400), ('absent.odt', 404), ('../plan.odt', 403)):
            self.assertEqual(self.opened('camille', name)[0], expected, name)
        self.assertEqual((self.folder / 'plan.odt').read_bytes(), b'plan')
        # Écriture retirée en cours de séance : le même jeton ne permet plus d'enregistrer ; accès retiré : il ne permet plus rien.
        status, data, path, token = self.opened('camille', 'plan.odt')
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': self.space, 'name': 'Chantier', 'members': {'camille': 'read'}})[0], 200)
        self.assertEqual(json.loads(self.wopi('GET', path, token)[1])['UserCanWrite'], False)
        self.assertEqual(self.wopi('POST', path + '/contents', token, b'x')[0], 403)
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': self.space, 'name': 'Chantier', 'members': {}})[0], 200)
        self.assertEqual(self.wopi('GET', path + '/contents', token)[0], 401)
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': self.space, 'name': 'Chantier', 'members': {'camille': 'write'}})[0], 200)
        self.assertEqual(self.wopi('GET', path + '/contents', token)[0], 200)
        # Nacre redémarre (mise à jour) : le document ouvert continue de se lire et de s'enregistrer ; seule l'empreinte du jeton est notée.
        office.TOKENS.clear(); office.FILES.clear(); office.LOADED['done'] = False
        self.assertEqual(self.wopi('GET', path + '/contents', token)[0], 200)
        self.assertEqual(self.wopi('POST', path + '/contents', token, b'apres redemarrage')[0], 200)
        with app.database() as db:
            noted = db.execute("SELECT value FROM settings WHERE key='office:open'").fetchone()[0]
        self.assertNotIn(token, noted); self.assertIn('"tokens"', noted)
        (self.folder / 'plan.odt').write_bytes(b'plan')
        # Compte désactivé, jeton échu, suite débranchée : refus.
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': False})[0], 200)
        self.assertEqual(self.wopi('GET', path, token)[0], 401)
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': True})[0], 200)
        with unittest.mock.patch.object(office.time, 'time', return_value=time.time() + office.TOKEN_SECONDS + 5):
            self.assertEqual(self.wopi('GET', path, token)[0], 401)
        self.assertEqual(self.wopi('GET', path, token)[0], 200)
        self.assertEqual(self.post('admin', '/api/office/configure', {'enabled': False, 'url': 'http://bureau.exemple:9980', 'wopi': self.wopi_base})[0], 200)
        self.assertEqual(self.wopi('GET', path, token)[0], 401)
        self.sessions['camille'] = app.make_session('camille')
        self.assertEqual(self.opened('camille', 'plan.odt')[0], 409)
        # Débrancher oublie aussi les documents notés : un redémarrage ne les ranime pas.
        office.LOADED['done'] = False
        self.assertEqual(self.wopi('GET', path, token)[0], 401)
        with app.database() as db:
            self.assertEqual(json.loads(db.execute("SELECT value FROM settings WHERE key='office:open'").fetchone()[0]), {'tokens': {}, 'files': {}})

    def test_new_text_and_spreadsheet_are_valid_empty_documents(self):
        self.team()
        for name, kind in (('Lettre.odt', 'application/vnd.oasis.opendocument.text'), ('Budget.ods', 'application/vnd.oasis.opendocument.spreadsheet')):
            status, made = self.post('camille', '/api/office/new', {'area': self.space, 'path': '', 'name': name})
            self.assertEqual((status, made['path']), (200, name))
            with zipfile.ZipFile(self.folder / name) as archive:
                first = archive.infolist()[0]
                self.assertEqual((first.filename, first.compress_type, archive.read('mimetype').decode()), ('mimetype', zipfile.ZIP_STORED, kind))
                self.assertIn(b'office:document-content', archive.read('content.xml')); self.assertIn(kind.encode(), archive.read('META-INF/manifest.xml'))
            self.assertEqual(self.post('camille', '/api/office/new', {'area': self.space, 'path': '', 'name': name})[0], 409)
        for name in ('x.docx', 'x.exe', 'sans-extension', '../x.odt'):
            self.assertEqual(self.post('camille', '/api/office/new', {'area': self.space, 'path': '', 'name': name})[0], 400, name)
        self.assertEqual(self.post('bruno', '/api/office/new', {'area': self.space, 'path': '', 'name': 'y.odt'})[0], 403)
        self.assertEqual(self.opened('camille', 'Lettre.odt')[0], 200)


if __name__ == '__main__':
    unittest.main()
