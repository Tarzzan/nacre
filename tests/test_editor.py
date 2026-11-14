"""Éditeur de texte : lecture, enregistrement d'un seul tenant, conflit signalé, versions regroupées, droits. Vrai serveur."""
import json
import os
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import quote

import test_spaces
import editor
import versions

app = test_spaces.app


class EditorTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home', 'audit'))

    def team(self):
        self.people(camille='member', bruno='member', dora='member')
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.folder = Path(app.ROOT) / 'data/espaces' / self.space[7:]
        editor.OPEN.clear()

    def read(self, who, path):
        return self.get(who, f'/api/files/text?area={self.space}&path={quote(path)}')

    def save(self, who, path, text, etag, **extra):
        return self.post(who, '/api/files/text-save', {'area': self.space, 'path': path, 'text': text, 'etag': etag, **extra})

    def kept(self, path):
        return [(v['size'], v['by']) for v in self.get('camille', f'/api/files/versions?area={self.space}&path={quote(path)}')[1]['versions']]

    def test_document_is_created_read_and_saved_and_a_change_made_elsewhere_is_never_overwritten_silently(self):
        self.team()
        status, made = self.post('camille', '/api/files/text-new', {'area': self.space, 'path': '', 'name': 'Compte rendu.md'})
        self.assertEqual((status, made['path']), (200, 'Compte rendu.md'))
        self.assertEqual(self.post('camille', '/api/files/text-new', {'area': self.space, 'path': '', 'name': 'Compte rendu.md'})[0], 409)
        for name in ('photo.jpg', '../x.md', '.cache.md', ''):
            self.assertEqual(self.post('camille', '/api/files/text-new', {'area': self.space, 'path': '', 'name': name})[0], 400, name)
        status, doc = self.read('camille', 'Compte rendu.md')
        self.assertEqual((status, doc['text'], doc['writable'], doc['markdown'], doc['others'], doc['name']), (200, '', True, True, [], 'Compte rendu.md'))
        status, done = self.save('camille', 'Compte rendu.md', '# Réunion\n\nDécisions : é, ü, 日本\n', doc['etag'])
        self.assertEqual(status, 200)
        self.assertEqual((self.folder / 'Compte rendu.md').read_text(), '# Réunion\n\nDécisions : é, ü, 日本\n')
        self.assertEqual(os.stat(self.folder / 'Compte rendu.md').st_mode & 0o777, 0o660)
        # Un long document passe : la limite des requêtes ordinaires ne vaut pas pour un enregistrement.
        long_text = 'Ligne accentuée — é\n' * 20000
        status, done = self.save('camille', 'Compte rendu.md', long_text, done['etag'])
        self.assertEqual((status, done['size']), (200, len(long_text.encode())))
        status, done = self.save('camille', 'Compte rendu.md', '# Réunion\n\nDécisions : é, ü, 日本\n', done['etag'])
        self.assertEqual(status, 200)
        self.assertEqual(self.read('camille', 'Compte rendu.md')[1]['etag'], done['etag'])
        # L'ancienne étiquette ne vaut plus : le fichier a changé, rien n'est enregistré sans le dire.
        status, data = self.save('camille', 'Compte rendu.md', 'écrasement', doc['etag'])
        self.assertEqual(status, 409); self.assertIn('a changé depuis', data['error'])
        (self.folder / 'Compte rendu.md').write_text('modifié par le réseau')
        os.utime(self.folder / 'Compte rendu.md', (time.time() + 5, time.time() + 5))
        self.assertEqual(self.save('camille', 'Compte rendu.md', 'ma version', done['etag'])[0], 409)
        self.assertEqual((self.folder / 'Compte rendu.md').read_text(), 'modifié par le réseau')
        # Enregistrer quand même : l'autre contenu part dans les versions, rien n'est perdu.
        self.assertEqual(self.save('camille', 'Compte rendu.md', 'ma version', done['etag'], force=True)[0], 200)
        self.assertEqual((self.folder / 'Compte rendu.md').read_text(), 'ma version')
        found = self.get('camille', f'/api/files/versions?area={self.space}&path={quote("Compte rendu.md")}')[1]['versions']
        contents = [self.request('GET', f'/api/files/version?area={self.space}&path={quote("Compte rendu.md")}&id={v["id"]}', token=self.sessions['camille'][0])[1] for v in found]
        self.assertIn(b'modifi\xc3\xa9 par le r\xc3\xa9seau', contents)
        self.assertEqual(sorted(n for n in os.listdir(self.folder) if n.startswith('.nacre-upload')), [])
        self.assertIn(('camille', 'Fichier enregistré depuis l’éditeur', 'Chantier : Compte rendu.md'), self.audit())
        self.assertIn(('camille', 'Document créé', 'Chantier : Compte rendu.md'), self.audit())

    def test_close_saves_by_the_same_person_share_one_version_and_others_get_their_own(self):
        self.team()
        (self.folder / 'notes.txt').write_text('origine')
        doc = self.read('camille', 'notes.txt')[1]
        now = time.time()
        tag = doc['etag']
        for index, moment in enumerate((now, now + 60, now + 300)):
            with unittest.mock.patch.object(editor.time, 'time', return_value=moment), unittest.mock.patch.object(versions.time, 'time', return_value=moment):
                status, done = self.save('camille', 'notes.txt', f'frappe {index}', tag)
            self.assertEqual(status, 200); tag = done['etag']
        # Trois enregistrements rapprochés : une seule version, le contenu d'avant la séance.
        self.assertEqual(self.kept('notes.txt'), [(7, 'camille')])
        # Plus de dix minutes après, ou par une autre personne : une nouvelle version.
        with unittest.mock.patch.object(editor.time, 'time', return_value=now + 2000), unittest.mock.patch.object(versions.time, 'time', return_value=now + 2000):
            tag = self.save('camille', 'notes.txt', 'plus tard', tag)[1]['etag']
        self.assertEqual(len(self.kept('notes.txt')), 2)
        self.assertEqual(self.post('admin', '/api/files/text-save', {'area': self.space, 'path': 'notes.txt', 'text': 'par un autre', 'etag': tag})[0], 200)
        self.assertEqual([by for _, by in self.kept('notes.txt')], ['admin', 'camille', 'camille'])
        # Une version gardée par un dépôt ne regroupe pas les enregistrements suivants.
        self.assertEqual((self.folder / 'notes.txt').read_text(), 'par un autre')

    def test_only_readable_text_opens_and_only_writers_save(self):
        self.team()
        (self.folder / 'image.txt').write_bytes(b'\xff\xd8\xff\xe0 pas du texte')
        (self.folder / 'nul.txt').write_bytes(b'a\x00b')
        (self.folder / 'gros.txt').write_bytes(b'x' * (editor.EDIT_MAX + 1))
        (self.folder / 'Dossier').mkdir(); os.symlink('/etc/hostname', self.folder / 'lien.txt')
        (self.folder / 'lisible.txt').write_text('bonjour')
        for name, expected in (('image.txt', 415), ('nul.txt', 415), ('gros.txt', 413), ('Dossier', 400), ('lien.txt', 403), ('absent.txt', 404), ('../x', 403)):
            self.assertEqual(self.read('camille', name)[0], expected, name)
        self.assertEqual(self.get('camille', f'/api/files/text?area={self.space}')[0], 400)
        # Lecteur : lit, n'enregistre pas ; hors de l'espace : rien.
        status, doc = self.read('bruno', 'lisible.txt')
        self.assertEqual((status, doc['text'], doc['writable']), (200, 'bonjour', False))
        self.assertEqual(self.save('bruno', 'lisible.txt', 'x', doc['etag'])[0], 403)
        self.assertEqual(self.post('bruno', '/api/files/text-new', {'area': self.space, 'path': '', 'name': 'a.md'})[0], 403)
        self.assertEqual(self.read('dora', 'lisible.txt')[0], 403)
        self.assertEqual(self.save('dora', 'lisible.txt', 'x', doc['etag'])[0], 403)
        for body in ({'text': 7}, {'text': 'a\x00b'}, {'text': 'x' * (editor.EDIT_MAX + 1)}):
            self.assertIn(self.post('camille', '/api/files/text-save', {'area': self.space, 'path': 'lisible.txt', 'etag': doc['etag'], **body})[0], (400, 413), list(body))
        self.assertEqual(self.save('camille', 'Dossier', 'x', 'x', force=True)[0], 400)
        self.assertEqual((self.folder / 'lisible.txt').read_text(), 'bonjour')
        # Espace personnel : rien de son contenu ni de ses noms au journal.
        mine = self.home('camille')
        self.assertEqual(self.post('camille', '/api/files/text-new', {'area': mine, 'path': '', 'name': 'journal-secret.md'})[0], 200)
        self.assertEqual(self.get('admin', f'/api/files/text?area={mine}&path=journal-secret.md')[0], 403)
        self.assertNotIn('secret', json.dumps(self.audit()))

    def test_presence_tells_who_else_has_the_document_open_and_forgets_them(self):
        self.team()
        (self.folder / 'plan.md').write_text('# Plan')
        body = {'area': self.space, 'path': 'plan.md'}
        self.assertEqual(self.post('camille', '/api/files/text-presence', body)[1], {'others': []})
        self.assertEqual(self.post('admin', '/api/files/text-presence', body)[1], {'others': ['camille']})
        self.assertEqual(self.read('camille', 'plan.md')[1]['others'], ['admin'])
        self.assertEqual(self.post('dora', '/api/files/text-presence', body)[0], 403)
        self.assertEqual(self.post('admin', '/api/files/text-presence', {**body, 'open': False})[1], {'others': ['camille']})
        self.assertEqual(self.read('camille', 'plan.md')[1]['others'], [])
        # Sans nouvelles depuis plus d'une minute et quart, une personne n'est plus annoncée.
        self.assertEqual(editor.others(self.space, 'plan.md', 'admin', time.time() + editor.PRESENCE + 1), [])
        self.assertEqual(editor.OPEN.get((self.space, 'plan.md')), {})

    def test_pdf_opens_inline_and_nothing_else_new_does(self):
        self.team()
        (self.folder / 'devis.pdf').write_bytes(b'%PDF-1.4 fictif')
        (self.folder / 'page.html').write_text('<script>alert(1)</script>')
        conn_status, data = self.request('GET', f'/api/download?area={self.space}&path=devis.pdf&inline=1', token=self.sessions['camille'][0])
        self.assertEqual((conn_status, data), (200, b'%PDF-1.4 fictif'))
        # Une page HTML ne s'affiche jamais telle quelle : elle se lit comme du texte dans l'éditeur.
        self.assertEqual(self.request('GET', f'/api/download?area={self.space}&path=page.html&inline=1', token=self.sessions['camille'][0])[0], 415)
        self.assertEqual(self.read('camille', 'page.html')[1]['text'], '<script>alert(1)</script>')


if __name__ == '__main__':
    unittest.main()
