"""Versions d'un fichier : gardées au remplacement, remises en place, bornées, soumises aux droits de l'espace. Vrai serveur."""
import json
import os
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import quote

import test_spaces
import versions

app = test_spaces.app


class VersionTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home, audit = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home', 'audit'))

    def team(self):
        self.people(camille='member', bruno='member', dora='member')
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.folder = Path(app.ROOT) / 'data/espaces' / self.space[7:]

    def put(self, who, name, content, path='', replace=False, area=None):
        status, data = self.post(who, f'/api/upload?area={area or self.space}&path={quote(path)}&name={quote(name)}' + ('&replace=1' if replace else ''), raw=content)
        return status, data

    def listed(self, who, path, area=None):
        status, data = self.get(who, f'/api/files/versions?area={area or self.space}&path={quote(path)}')
        return status, data.get('versions', data) if isinstance(data, dict) else data

    def fetch(self, who, path, ident, area=None):
        return self.request('GET', f'/api/files/version?area={area or self.space}&path={quote(path)}&id={ident}', token=self.sessions[who][0])

    def test_replacing_keeps_the_previous_content_and_restoring_can_be_undone(self):
        self.team()
        self.assertEqual(self.put('camille', 'devis.txt', b'version 1')[0], 200)
        self.assertEqual(self.listed('camille', 'devis.txt'), (200, []))
        # Sans demande explicite, rien n'est remplacé.
        status, data = self.put('camille', 'devis.txt', b'version 2')
        self.assertEqual(status, 409); self.assertIn('Aucun fichier n’a été remplacé', data['error'])
        self.assertEqual((self.folder / 'devis.txt').read_bytes(), b'version 1')
        status, data = self.put('camille', 'devis.txt', b'version 2', replace=True)
        self.assertEqual((status, data['replaced']), (200, True))
        self.assertEqual(self.put('bruno', 'devis.txt', b'intrus', replace=True)[0], 403)
        self.assertEqual(self.put('camille', 'devis.txt', b'version 3', replace=True)[0], 200)
        self.assertEqual((self.folder / 'devis.txt').read_bytes(), b'version 3')
        status, found = self.listed('camille', 'devis.txt')
        self.assertEqual([(v['size'], v['by']) for v in found], [(9, 'camille'), (9, 'camille')])
        self.assertEqual([self.fetch('camille', 'devis.txt', v['id'])[1] for v in found], [b'version 2', b'version 1'])
        # Un lecteur de l'espace consulte les versions mais ne les remet pas en place.
        self.assertEqual(self.fetch('bruno', 'devis.txt', found[0]['id'])[0], 200)
        self.assertEqual(self.post('bruno', '/api/files/version-restore', {'area': self.space, 'path': 'devis.txt', 'id': found[1]['id']})[0], 403)
        # Remise en place : le contenu actuel devient une version, donc le retour se défait.
        self.assertEqual(self.post('camille', '/api/files/version-restore', {'area': self.space, 'path': 'devis.txt', 'id': found[1]['id']})[0], 200)
        self.assertEqual((self.folder / 'devis.txt').read_bytes(), b'version 1')
        after = self.listed('camille', 'devis.txt')[1]
        self.assertEqual(sorted(self.fetch('camille', 'devis.txt', v['id'])[1] for v in after), [b'version 2', b'version 3'])
        self.assertEqual(self.post('camille', '/api/files/version-restore', {'area': self.space, 'path': 'devis.txt', 'id': after[0]['id']})[0], 200)
        self.assertEqual((self.folder / 'devis.txt').read_bytes(), b'version 3')
        actions = [line[1] for line in self.audit() if line[0] == 'camille']
        self.assertEqual(actions.count('Fichier remplacé'), 2); self.assertEqual(actions.count('Version remise en place'), 2)
        self.assertIn(('camille', 'Version remise en place', 'Chantier : devis.txt'), self.audit())
        # Rien d'interne n'apparaît dans le dossier, et aucun fichier temporaire ne traîne.
        self.assertEqual(self.get('camille', f'/api/files?area={self.space}')[1]['items'][0]['name'], 'devis.txt')
        self.assertEqual(sorted(os.listdir(self.folder)), ['.nacre-versions', 'devis.txt'])
        self.assertEqual(os.stat(self.folder / '.nacre-versions').st_mode & 0o777, 0o700)

    def test_only_the_last_versions_are_kept_and_one_can_be_removed(self):
        self.team()
        self.put('camille', 'notes.txt', b'0')
        with unittest.mock.patch.object(versions, 'KEEP', 3):
            for index in range(1, 6):
                self.assertEqual(self.put('camille', 'notes.txt', str(index).encode(), replace=True)[0], 200)
            found = self.listed('camille', 'notes.txt')[1]
            self.assertEqual([self.fetch('camille', 'notes.txt', v['id'])[1] for v in found], [b'4', b'3', b'2'])
            self.assertEqual(len([n for n in os.listdir(self.folder / '.nacre-versions') if n != 'index.json']), 3)
        ident = found[1]['id']
        self.assertEqual(self.post('camille', '/api/files/version-delete', {'area': self.space, 'path': 'notes.txt', 'id': ident})[0], 400)
        self.assertEqual(self.post('bruno', '/api/files/version-delete', {'area': self.space, 'path': 'notes.txt', 'id': ident, 'confirm': True})[0], 403)
        self.assertEqual(self.post('camille', '/api/files/version-delete', {'area': self.space, 'path': 'notes.txt', 'id': ident, 'confirm': True})[0], 200)
        self.assertEqual([self.fetch('camille', 'notes.txt', v['id'])[1] for v in self.listed('camille', 'notes.txt')[1]], [b'4', b'2'])
        self.assertEqual(self.fetch('camille', 'notes.txt', ident)[0], 404)
        self.assertEqual((self.folder / 'notes.txt').read_bytes(), b'5')
        for bad in ('x' * 24, '../index.json', 'index.json', ''):
            self.assertEqual(self.fetch('camille', 'notes.txt', bad)[0], 404, bad)
            self.assertEqual(self.post('camille', '/api/files/version-restore', {'area': self.space, 'path': 'notes.txt', 'id': bad})[0], 404, bad)
        # La version d'un fichier ne se demande pas sous le nom d'un autre.
        self.put('camille', 'autre.txt', b'a')
        self.assertEqual(self.fetch('camille', 'autre.txt', found[0]['id'])[0], 404)

    def test_versions_follow_a_rename_and_a_move_and_stay_within_the_space_rights(self):
        self.team()
        self.assertEqual(self.post('camille', '/api/folder', {'area': self.space, 'name': 'Plans'})[0], 200)
        self.put('camille', 'plan.txt', b'avant', path='Plans')
        self.put('camille', 'plan.txt', b'apres', path='Plans', replace=True)
        self.assertEqual(self.post('camille', '/api/rename', {'area': self.space, 'path': 'Plans/plan.txt', 'name': 'plan-final.txt'})[0], 200)
        self.assertEqual(len(self.listed('camille', 'Plans/plan-final.txt')[1]), 1)
        self.assertEqual(self.listed('camille', 'Plans/plan.txt')[1], [])
        # Dossier renommé, puis fichier déplacé : les versions suivent.
        self.assertEqual(self.post('camille', '/api/rename', {'area': self.space, 'path': 'Plans', 'name': 'Archives'})[0], 200)
        self.assertEqual(len(self.listed('camille', 'Archives/plan-final.txt')[1]), 1)
        self.assertEqual(self.post('camille', '/api/move', {'area': self.space, 'path': 'Archives', 'names': ['plan-final.txt'], 'target': ''})[0], 200)
        found = self.listed('camille', 'plan-final.txt')[1]
        self.assertEqual(self.fetch('camille', 'plan-final.txt', found[0]['id'])[1], b'avant')
        # Hors de l'espace : ni liste, ni contenu, ni remise en place.
        self.assertEqual(self.listed('dora', 'plan-final.txt')[0], 403)
        self.assertEqual(self.fetch('dora', 'plan-final.txt', found[0]['id'])[0], 403)
        self.assertEqual(self.post('dora', '/api/files/version-restore', {'area': self.space, 'path': 'plan-final.txt', 'id': found[0]['id']})[0], 403)
        # Espace personnel : versions fermées à l'administrateur comme le reste, et sans nom au journal.
        mine = self.home('camille')
        self.put('camille', 'secret-journal.txt', b'un', area=mine)
        self.put('camille', 'secret-journal.txt', b'deux', area=mine, replace=True)
        self.assertEqual(len(self.listed('camille', 'secret-journal.txt', area=mine)[1]), 1)
        self.assertEqual(self.listed('admin', 'secret-journal.txt', area=mine)[0], 403)
        self.assertNotIn('secret', json.dumps(self.audit()))

    def test_common_space_keeps_versions_outside_the_shared_folder_and_refuses_odd_targets(self):
        self.team()
        shared = Path(app.ROOT) / 'data/fichiers'
        self.assertEqual(self.put('admin', 'notice.txt', b'un', area='fichiers')[0], 200)
        self.assertEqual(self.put('admin', 'notice.txt', b'deux', area='fichiers', replace=True)[0], 200)
        # Les versions de l'espace commun ne sont pas dans le dossier partagé en SMB.
        self.assertEqual(os.listdir(shared), ['notice.txt'])
        self.assertTrue((Path(app.ROOT) / 'data/.versions/index.json').is_file())
        found = self.listed('admin', 'notice.txt', area='fichiers')[1]
        self.assertEqual(self.fetch('admin', 'notice.txt', found[0]['id'], area='fichiers')[1], b'un')
        self.assertEqual(self.listed('camille', 'notice.txt', area='fichiers')[0], 200)   # lecture de l'espace commun
        self.assertEqual(self.post('camille', '/api/files/version-restore', {'area': 'fichiers', 'path': 'notice.txt', 'id': found[0]['id']})[0], 403)
        # Un dossier ou un lien n'est jamais remplacé par un fichier.
        (shared / 'Dossier').mkdir(); os.symlink('/etc/hostname', shared / 'lien')
        for name in ('Dossier', 'lien'):
            status, data = self.put('admin', name, b'x', area='fichiers', replace=True)
            self.assertEqual(status, 409, name); self.assertIn('pas remplacé', data['error'])
        self.assertTrue((shared / 'Dossier').is_dir()); self.assertTrue((shared / 'lien').is_symlink())
        self.assertEqual(sorted(n for n in os.listdir(shared) if n.startswith('.nacre-upload')), [])
        # Si la version ne peut pas être rangée, l'ancien contenu reste à côté sous un nom visible.
        with unittest.mock.patch.object(versions, 'keep', side_effect=OSError('disque plein')):
            self.assertEqual(self.put('admin', 'notice.txt', b'trois', area='fichiers', replace=True)[0], 200)
        rescued = [n for n in os.listdir(shared) if n.startswith('notice.txt.avant-remplacement-')]
        self.assertEqual((len(rescued), (shared / rescued[0]).read_bytes(), (shared / 'notice.txt').read_bytes()), (1, b'deux', b'trois'))

    def test_a_refused_upload_does_not_poison_the_connection(self):
        """Un dépôt refusé avant lecture laisse son contenu sur la connexion : elle est fermée, jamais réutilisée de travers."""
        import http.client
        self.team()
        self.put('camille', 'notes.txt', b'un')
        token, csrf = self.sessions['camille']
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        headers = {'Cookie': 'nas_session=' + token, 'X-CSRF-Token': csrf, 'Content-Type': 'application/octet-stream'}
        conn.request('POST', f'/api/upload?area={self.space}&path=&name=notes.txt', b'GET /api/areas HTTP/1.1\r\nHost: x\r\n\r\n' * 3, headers)
        response = conn.getresponse()
        self.assertEqual((response.status, json.loads(response.read())['error']), (409, 'Ce nom existe déjà. Aucun fichier n’a été remplacé.'))
        try:
            conn.request('GET', '/api/me', headers={'Cookie': 'nas_session=' + token})
            again = conn.getresponse()
            self.assertEqual((again.status, json.loads(again.read())['name']), (200, 'camille'))
        except (http.client.HTTPException, OSError):
            pass   # connexion fermée par le serveur : c'est le comportement voulu
        finally:
            conn.close()
        self.assertEqual((self.folder / 'notes.txt').read_bytes(), b'un')


if __name__ == '__main__':
    unittest.main()
