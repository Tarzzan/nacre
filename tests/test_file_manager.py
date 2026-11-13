"""Gestionnaire de fichiers : déplacement, archive et aperçu, sur un espace temporaire et un serveur HTTP local."""
import http.client
import io
import json
import os
import unittest
import zipfile
from urllib.parse import quote

import test_onboarding as base

server = base.server


class FileManagerTests(unittest.TestCase):
    setUp = base.OnboardingTests.setUp
    tearDown = base.OnboardingTests.tearDown

    def call(self, method, path, body=None, token=None, csrf=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=8)
        headers = {'Content-Type': 'application/json', 'Cookie': 'nas_session=' + (token or self.token)}
        if csrf is not False:
            headers['X-CSRF-Token'] = csrf or self.csrf
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse(); data = response.read(); connection.close()
        return response.status, dict(response.getheaders()), data

    def move(self, **body):
        status, _, data = self.call('POST', '/api/move', body)
        return status, json.loads(data)

    def tree(self):
        self.files = server.ROOT / 'data/fichiers'
        for folder in ('source/sous-dossier', 'cible', 'cible/occupe'):
            (self.files / folder).mkdir(parents=True)
        (self.files / 'source/a.txt').write_text('contenu a')
        (self.files / 'source/b.txt').write_text('contenu b')
        (self.files / 'source/sous-dossier/c.txt').write_text('contenu c')
        (self.files / 'source/.cache').write_text('interne')
        (self.files / 'cible/occupe/a.txt').write_text('déjà là')
        self.outside = server.ROOT / 'hors-espace'; self.outside.mkdir(); (self.outside / 'secret.txt').write_text('ne pas exposer')
        (self.files / 'source/lien').symlink_to(self.outside, target_is_directory=True)
        (self.files / 'lien-dossier').symlink_to(self.outside, target_is_directory=True)

    def reader(self):
        with server.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        return server.make_session('reader')

    def test_move_keeps_content_never_replaces_and_stays_inside_the_area(self):
        self.tree()
        status, value = self.move(path='source', names=['a.txt', 'sous-dossier'], target='cible')
        self.assertEqual(status, 200, value)
        self.assertEqual((self.files / 'cible/a.txt').read_text(), 'contenu a')
        self.assertEqual((self.files / 'cible/sous-dossier/c.txt').read_text(), 'contenu c')
        self.assertFalse((self.files / 'source/a.txt').exists())
        with server.database() as db:
            self.assertEqual(tuple(db.execute('SELECT username,action,detail FROM audit ORDER BY id DESC LIMIT 1').fetchone()), ('admin', 'Éléments déplacés', 'fichiers: /source → /cible · 2'))
        # Un nom déjà pris arrête tout avant le premier déplacement : rien n'est remplacé, rien n'est déplacé à moitié.
        (self.files / 'source/a.txt').write_text('second a')
        status, value = self.move(path='source', names=['b.txt', 'a.txt'], target='cible/occupe')
        self.assertEqual(status, 409); self.assertIn('a.txt', value['error'])
        self.assertEqual(((self.files / 'source/b.txt').read_text(), (self.files / 'cible/occupe/a.txt').read_text()), ('contenu b', 'déjà là'))
        # Vers la racine de l'espace, et un lien déplacé reste un lien : sa cible n'est ni suivie ni touchée.
        self.assertEqual(self.move(path='source', names=['b.txt', 'lien'], target='')[0], 200)
        self.assertTrue((self.files / 'lien').is_symlink()); self.assertEqual((self.outside / 'secret.txt').read_text(), 'ne pas exposer')
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ['secret.txt'])

    def test_move_refuses_invalid_selections_and_destinations_without_touching_anything(self):
        self.tree()
        before = sorted(str(p.relative_to(self.files)) for p in self.files.rglob('*'))
        cases = [({'path': 'source', 'names': ['a.txt'], 'target': 'source'}, 400), ({'path': '', 'names': ['source'], 'target': 'source/sous-dossier'}, 400),
                 ({'path': '', 'names': ['source'], 'target': 'source'}, 400), ({'path': 'source', 'names': ['absent.txt'], 'target': 'cible'}, 404),
                 ({'path': 'source', 'names': ['a.txt'], 'target': 'absent'}, 404), ({'path': 'source', 'names': ['a.txt'], 'target': '../hors-espace'}, 403),
                 ({'path': 'source', 'names': ['a.txt'], 'target': '.nacre-trash'}, 403), ({'path': 'source', 'names': ['../cible'], 'target': 'cible'}, 400),
                 ({'path': 'source', 'names': ['.cache'], 'target': 'cible'}, 400), ({'path': 'source', 'names': ['a.txt', 'a.txt'], 'target': 'cible'}, 400),
                 ({'path': 'source', 'names': [], 'target': 'cible'}, 400), ({'path': 'source', 'names': 'a.txt', 'target': 'cible'}, 400),
                 ({'path': 'source', 'names': ['x%d' % i for i in range(501)], 'target': 'cible'}, 400), ({'path': 'source', 'names': ['a.txt'], 'target': None}, 400),
                 ({'area': 'video', 'path': '', 'names': ['a.txt'], 'target': 'cible'}, 403), ({'area': 'ailleurs', 'path': '', 'names': ['a.txt'], 'target': 'cible'}, 400)]
        for body, expected in cases:
            self.assertEqual(self.move(**body)[0], expected, body)
        # Un lien symbolique ne peut servir ni de dossier de départ ni de destination.
        for body in ({'path': 'source', 'names': ['a.txt'], 'target': 'lien-dossier'}, {'path': 'lien-dossier', 'names': ['secret.txt'], 'target': 'cible'}):
            self.assertEqual(self.move(**body)[0], 404, body)
        self.assertEqual(sorted(str(p.relative_to(self.files)) for p in self.files.rglob('*')), before)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ['secret.txt'])
        token, csrf = self.reader()
        body = {'path': 'source', 'names': ['a.txt'], 'target': 'cible'}
        self.assertEqual(self.call('POST', '/api/move', body, token, csrf)[0], 403)
        self.assertEqual(self.call('POST', '/api/move', body, csrf=False)[0], 403)
        self.assertTrue((self.files / 'source/a.txt').exists())

    def test_archive_streams_the_selection_without_links_or_hidden_files(self):
        self.tree(); (self.files / 'source/vide').mkdir(); (self.files / 'source/é à.txt').write_text('accents')
        query = '/api/archive?path=source&' + '&'.join('name=' + quote(n) for n in ('a.txt', 'sous-dossier', 'lien', 'vide', 'é à.txt'))
        status, headers, data = self.call('GET', query)
        self.assertEqual(status, 200)
        self.assertEqual((headers['Content-Type'], headers['X-Content-Type-Options'], headers['Cache-Control']), ('application/zip', 'nosniff', 'no-store'))
        self.assertEqual(headers['Content-Disposition'], "attachment; filename*=UTF-8''source.zip")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(sorted(archive.namelist()), ['a.txt', 'sous-dossier/', 'sous-dossier/c.txt', 'vide/', 'é à.txt'])
            self.assertEqual((archive.read('a.txt'), archive.read('sous-dossier/c.txt'), archive.read('é à.txt')), (b'contenu a', b'contenu c', b'accents'))
        self.assertNotIn(b'ne pas exposer', data); self.assertNotIn(b'interne', data)
        with server.database() as db:
            self.assertEqual(tuple(db.execute('SELECT username,action,detail FROM audit ORDER BY id DESC LIMIT 1').fetchone()), ('admin', 'Archive téléchargée', 'fichiers: /source · 5'))
        # Un seul élément : l'archive porte son nom. Un compte en lecture seule peut télécharger, pas sortir de ses espaces.
        token, _ = self.reader()
        status, headers, data = self.call('GET', '/api/archive?path=&name=source', token=token)
        self.assertEqual((status, headers['Content-Disposition']), (200, "attachment; filename*=UTF-8''source.zip"))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('source/sous-dossier/c.txt', archive.namelist()); self.assertNotIn('source/.cache', archive.namelist())
            self.assertFalse(any(name.startswith('source/lien') for name in archive.namelist()))
        self.assertEqual(self.call('GET', '/api/archive?area=restaurations&path=&name=x', token=token)[0], 403)
        for bad, expected in (('/api/archive?path=source', 400), ('/api/archive?path=source&name=absent', 404), ('/api/archive?path=source&name=..', 400),
                              ('/api/archive?path=source&name=.cache', 400), ('/api/archive?path=source&name=a.txt&name=a.txt', 400),
                              ('/api/archive?path=../hors-espace&name=secret.txt', 403), ('/api/archive?path=lien-dossier&name=secret.txt', 404),
                              ('/api/archive?path=source&' + '&'.join('name=n%d' % i for i in range(501)), 400)):
            status, _, data = self.call('GET', bad)
            self.assertNotEqual(status, 200, bad); self.assertNotIn(b'ne pas exposer', data)
            if expected:
                self.assertEqual(status, expected, bad)

    def test_preview_serves_only_safe_types_and_a_bounded_text(self):
        self.tree()
        (self.files / 'long.txt').write_bytes(b'x' * (server.PREVIEW_TEXT + 500)); (self.files / 'photo.JPG').write_bytes(b'\xff\xd8image')
        (self.files / 'page.html').write_text('<script>alert(1)</script>'); (self.files / 'dessin.svg').write_text('<svg onload="alert(1)"/>')
        (self.files / 'clip.mp4').write_bytes(b'video' * 20000)
        status, headers, data = self.call('GET', '/api/download?path=long.txt&inline=1')
        self.assertEqual((status, len(data), headers['Content-Type'], headers['X-Content-Type-Options']), (200, server.PREVIEW_TEXT, 'text/plain; charset=utf-8', 'nosniff'))
        self.assertTrue(headers['Content-Disposition'].startswith('inline;'))
        status, headers, data = self.call('GET', '/api/download?path=photo.JPG&inline=1')
        self.assertEqual((status, headers['Content-Type'], data), (200, 'image/jpeg', b'\xff\xd8image'))
        status, headers, data = self.call('GET', '/api/download?path=clip.mp4&inline=1')
        self.assertEqual((status, headers['Content-Type'], len(data)), (200, 'video/mp4', 100000))
        # Ni page ni dessin vectoriel en aperçu : ils pourraient exécuter du script dans la console.
        for name in ('page.html', 'dessin.svg', 'source/a'):
            self.assertIn(self.call('GET', f'/api/download?path={name}&inline=1')[0], (404, 415), name)
        self.assertEqual(self.call('GET', '/api/download?path=page.html&inline=1')[0], 415)
        # Le téléchargement ordinaire reste entier et proposé à l'enregistrement.
        status, headers, data = self.call('GET', '/api/download?path=long.txt')
        self.assertEqual((status, len(data), headers['Content-Type']), (200, server.PREVIEW_TEXT + 500, 'application/octet-stream'))
        self.assertTrue(headers['Content-Disposition'].startswith('attachment;'))
        status, headers, data = self.call('GET', '/api/download?path=page.html')
        self.assertEqual((status, headers['Content-Type'], headers['X-Content-Type-Options']), (200, 'application/octet-stream', 'nosniff'))
        self.assertNotEqual(self.call('GET', '/api/download?path=lien-dossier/secret.txt&inline=1')[0], 200)


if __name__ == '__main__':
    unittest.main()
