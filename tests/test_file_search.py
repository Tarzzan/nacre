"""Recherche de fichiers par nom : portée, droits, liens jamais suivis et bornes, sur un espace temporaire et un serveur HTTP local."""
import json
import unittest
from unittest.mock import patch
from urllib.parse import quote

import test_file_manager as manager

server = manager.server


class FileSearchTests(unittest.TestCase):
    setUp = manager.FileManagerTests.setUp
    tearDown = manager.FileManagerTests.tearDown
    call = manager.FileManagerTests.call
    reader = manager.FileManagerTests.reader

    def find(self, text, token=None, **scope):
        query = '/api/files/search?q=' + quote(text) + ''.join(f'&{key}={quote(value)}' for key, value in scope.items())
        status, _, data = self.call('GET', query, token=token)
        return status, json.loads(data)

    def found(self, text, **scope):
        status, value = self.find(text, **scope)
        self.assertEqual(status, 200, value)
        return [(item['area'], item['path'], item['name']) for item in value['items']]

    def tree(self):
        data = server.ROOT / 'data'
        self.files = data / 'fichiers'
        for folder in ('fichiers/Photos/Été 2026', 'fichiers/Factures', 'fichiers/.cache', 'video/extraits', 'sauvegardes', 'restaurations/ancien'):
            (data / folder).mkdir(parents=True, exist_ok=True)
        (self.files / 'Photos/Été 2026/plage été.jpg').write_text('image')
        (self.files / 'Photos/ete-notes.txt').write_text('notes')
        (self.files / 'Factures/facture ÉTÉ.pdf').write_text('pdf')
        (self.files / 'été.md').write_text('racine')
        (self.files / '.cache/été-caché.txt').write_text('interne')
        (self.files / 'Factures/.été-masqué').write_text('interne')
        (data / 'video/extraits/été au jardin.mp4').write_text('clip')
        (data / 'restaurations/ancien/été.md').write_text('copie')
        self.outside = server.ROOT / 'hors-espace'; self.outside.mkdir(); (self.outside / 'été-secret.txt').write_text('ne pas exposer')
        (self.files / 'lien été').symlink_to(self.outside, target_is_directory=True)

    def test_search_finds_names_everywhere_without_accents_case_links_or_hidden_files(self):
        self.tree()
        status, value = self.find('ETE')
        self.assertEqual(status, 200, value)
        # Le nom qui commence par la saisie d'abord, puis l'espace Fichiers avant les autres, du moins profond au plus profond.
        self.assertEqual([(i['area'], i['path'], i['name']) for i in value['items']],
                         [('fichiers', '', 'été.md'), ('fichiers', 'Photos', 'ete-notes.txt'), ('fichiers', 'Photos', 'Été 2026'), ('video', 'extraits', 'été au jardin.mp4'),
                          ('fichiers', '', 'lien été'), ('fichiers', 'Factures', 'facture ÉTÉ.pdf'), ('fichiers', 'Photos/Été 2026', 'plage été.jpg')])
        self.assertEqual((value['partial'], value['skipped'], value['query'], value['limit']), (None, [], 'ETE', 200))
        by_name = {item['name']: item for item in value['items']}
        self.assertEqual((by_name['Été 2026']['directory'], by_name['Été 2026']['link'], by_name['été.md']['size']), (True, False, 6))
        # Un lien est nommé, jamais suivi : rien de ce qui se trouve derrière n'apparaît. Les restaurations ne sont pas parcourues d'office.
        self.assertEqual((by_name['lien été']['link'], by_name['lien été']['directory']), (True, False))
        self.assertNotIn('secret', json.dumps(value)); self.assertNotIn('cach', json.dumps(value)); self.assertNotIn('restaurations', json.dumps(value))
        # Tous les mots saisis doivent figurer dans le nom, dans n'importe quel ordre.
        self.assertEqual(self.found('ete plage'), [('fichiers', 'Photos/Été 2026', 'plage été.jpg')])
        self.assertEqual(self.found('.PDF'), [('fichiers', 'Factures', 'facture ÉTÉ.pdf')])
        self.assertEqual(self.found('introuvable'), [])

    def test_search_scope_follows_the_area_the_folder_and_the_role(self):
        self.tree()
        self.assertEqual(self.found('été', area='fichiers', path='Photos'), [('fichiers', 'Photos', 'ete-notes.txt'), ('fichiers', 'Photos', 'Été 2026'), ('fichiers', 'Photos/Été 2026', 'plage été.jpg')])
        self.assertEqual(self.found('été', area='video'), [('video', 'extraits', 'été au jardin.mp4')])
        self.assertEqual(self.found('été', area='restaurations'), [('restaurations', 'ancien', 'été.md')])
        token, _ = self.reader()
        self.assertEqual(self.find('été', token=token, area='restaurations')[0], 403)
        self.assertEqual(self.find('été', token=token, area='native_volume')[0], 403)
        status, value = self.find('été', token=token)
        self.assertEqual((status, len(value['items'])), (200, 7)); self.assertNotIn('restaurations', json.dumps(value))
        for query, expected in (({'area': 'fichiers', 'path': '../hors-espace'}, 403), ({'area': 'fichiers', 'path': 'lien été'}, 404), ({'area': 'fichiers', 'path': 'absent'}, 404),
                                ({'area': 'fichiers', 'path': '.nacre-trash'}, 403), ({'area': 'ailleurs'}, 400), ({'path': 'Photos'}, 400)):
            self.assertEqual(self.find('été', **query)[0], expected, query)
        for text in ('', 'e', ' e ', 'x' * 81):
            self.assertEqual(self.find(text)[0], 400, text)
        status, _, _ = self.call('GET', '/api/files/search?q=ete', token='inconnu')
        self.assertEqual(status, 401)

    def test_filters_narrow_by_kind_recency_and_size_after_the_name(self):
        import os, time
        self.tree()
        (self.files / 'Photos/été-gros.bin').write_bytes(b'x' * 3000)
        old = time.time() - 40 * 86400
        for path in ('été.md', 'Photos/Été 2026'):
            os.utime(self.files / path, (old, old))
        names = lambda **scope: [name for _, _, name in self.found('été', **scope)]
        # Famille de type d'après l'extension, sans casse ; un lien n'appartient à aucune famille, un dossier à la sienne seulement.
        self.assertEqual(names(kind='image'), ['plage été.jpg'])
        self.assertEqual(names(kind='video'), ['été au jardin.mp4'])
        self.assertEqual(names(kind='document'), ['été.md', 'ete-notes.txt', 'facture ÉTÉ.pdf'])
        self.assertEqual(names(kind='folder'), ['Été 2026'])
        self.assertEqual(names(kind='archive'), [])
        # Modification récente : l'ancien fichier et l'ancien dossier sortent, mais le contenu du dossier reste parcouru.
        self.assertEqual(sorted(names(days='30')), sorted(['ete-notes.txt', 'été-gros.bin', 'été au jardin.mp4', 'lien été', 'facture ÉTÉ.pdf', 'plage été.jpg']))
        self.assertEqual(len(names(days='60')), 8)
        # Taille minimale : des fichiers seulement, jamais un dossier ni un lien.
        self.assertEqual(names(min_size='2048'), ['été-gros.bin'])
        self.assertEqual(names(min_size='3001'), [])
        # Les filtres se combinent, avec la portée.
        self.assertEqual(names(kind='document', days='30'), ['ete-notes.txt', 'facture ÉTÉ.pdf'])
        self.assertEqual(names(kind='document', days='30', area='fichiers', path='Photos'), ['ete-notes.txt'])
        status, value = self.find('été', kind='image', days='7', min_size='1')
        self.assertEqual((status, value['filters']), (200, {'kind': 'image', 'days': 7, 'min_size': 1}))
        self.assertEqual(self.find('été')[1]['filters'], {'kind': None, 'days': None, 'min_size': None})
        self.assertEqual(self.find('été', kind='', days='', min_size='')[1]['filters'], {'kind': None, 'days': None, 'min_size': None})
        for query in ({'kind': 'exe'}, {'kind': 'Image'}, {'kind': 'image,video'}, {'days': '0'}, {'days': '-1'}, {'days': 'abc'}, {'days': '1.5'}, {'days': '36501'},
                      {'days': '٣'}, {'min_size': '0'}, {'min_size': '1e3'}, {'min_size': str((1 << 50) + 1)}):
            self.assertEqual(self.find('été', **query)[0], 400, query)

    def test_search_stops_at_its_bounds_and_says_so(self):
        import file_search
        self.tree()
        for index in range(300):
            (self.files / 'Factures' / f'piece-{index:03}.txt').write_text('x')
        with patch.object(file_search, 'RESULTS', 3):
            status, value = self.find('piece')
            self.assertEqual((status, len(value['items']), value['partial'], value['limit']), (200, 3, 'results', 3))
        with patch.object(file_search, 'VISITED', 5):
            status, value = self.find('piece')
            self.assertEqual((status, value['partial'], value['visited']), (200, 'count', 6))
        with patch.object(file_search, 'SECONDS', -1):
            status, value = self.find('introuvable')
            self.assertEqual((status, value['partial'], value['items']), (200, 'time', [])); self.assertLess(value['visited'], 300)
        # Sans borne atteinte, tout est vu ; deux recherches à la fois au plus, la troisième est refusée sans rien parcourir.
        self.assertEqual(self.find('piece-2')[1]['partial'], None)
        self.assertTrue(file_search._slots.acquire(blocking=False)); self.assertTrue(file_search._slots.acquire(blocking=False))
        try:
            self.assertEqual(self.find('piece')[0], 429)
        finally:
            file_search._slots.release(); file_search._slots.release()
        self.assertEqual(self.find('piece-299')[0], 200)
        # Un espace indisponible n'empêche pas de chercher partout ; il est signalé.
        real = server.folder

        def broken(area, path='', write=False):
            if area == 'video':
                raise server.Problem('Volume ou restauration non disponible.', 503)
            return real(area, path, write)
        with patch.object(server, 'folder', broken):
            status, value = self.find('été')
            self.assertEqual((status, value['skipped'], len(value['items'])), (200, ['video'], 6))
            self.assertEqual(self.find('été', area='video')[0], 503)


if __name__ == '__main__':
    unittest.main()
