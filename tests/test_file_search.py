"""Recherche de fichiers par nom ou par critères, et poids des dossiers : portée, droits, liens jamais suivis et bornes, sur un espace temporaire et un serveur HTTP local."""
import json
import time
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

    def test_criteria_alone_rank_the_biggest_or_the_latest_within_bounds(self):
        import file_search, os, time
        self.tree()
        for name, size in (('Photos/énorme.bin', 9000), ('Photos/Été 2026/moyen.jpg', 5000), ('Factures/petit.pdf', 700)):
            (self.files / name).write_bytes(b'x' * size)
        (server.ROOT / 'data/video/extraits/film.mp4').write_bytes(b'x' * 7000)
        (server.ROOT / 'data/restaurations/ancien/copie.bin').write_bytes(b'x' * 99000)
        now = time.time()
        for index, path in enumerate(('Photos/énorme.bin', 'Factures/petit.pdf', 'Photos/Été 2026', 'Photos')):
            os.utime(self.files / path, (now + 100 - index, now + 100 - index))
        # Sans nom : les plus gros fichiers d'abord, tous espaces confondus ; ni dossier, ni lien, ni caché, ni restauration.
        status, value = self.find('', sort='size')
        self.assertEqual(status, 200, value)
        self.assertEqual([(i['area'], i['name'], i['size']) for i in value['items']][:4],
                         [('fichiers', 'énorme.bin', 9000), ('video', 'film.mp4', 7000), ('fichiers', 'moyen.jpg', 5000), ('fichiers', 'petit.pdf', 700)])
        self.assertEqual((value['sort'], value['partial'], value['query'], value['matched']), ('size', None, '', len(value['items'])))
        self.assertFalse(any(i['directory'] or i['link'] for i in value['items'])); self.assertNotIn('rank', value['items'][0])
        self.assertNotIn('restaurations', json.dumps(value)); self.assertNotIn('cach', json.dumps(value))
        # Un critère suffit, et classe par taille ; des dossiers seuls sont classés par date, faute de taille propre.
        self.assertEqual([i['name'] for i in self.find('', kind='image')[1]['items']], ['moyen.jpg', 'plage été.jpg'])
        self.assertEqual(self.find('', min_size='6000')[1]['sort'], 'size')
        self.assertEqual([name for _, _, name in self.found('', min_size='6000')], ['énorme.bin', 'film.mp4'])
        status, value = self.find('', kind='folder')
        self.assertEqual((value['sort'], [i['name'] for i in value['items']][:2]), ('recent', ['Été 2026', 'Photos']))
        self.assertEqual(self.found('', kind='folder', sort='size'), [])
        # Les plus récents d'abord : dossiers compris.
        self.assertEqual([name for _, _, name in self.found('', sort='recent')][:4], ['énorme.bin', 'petit.pdf', 'Été 2026', 'Photos'])
        # La portée et les droits restent ceux de la recherche par nom.
        self.assertEqual(self.found('', sort='size', area='fichiers', path='Photos/Été 2026'), [('fichiers', 'Photos/Été 2026', 'moyen.jpg'), ('fichiers', 'Photos/Été 2026', 'plage été.jpg')])
        self.assertEqual(self.found('', sort='size', area='restaurations')[0], ('restaurations', 'ancien', 'copie.bin'))
        token, _ = self.reader()
        self.assertEqual(self.find('', token=token, sort='size', area='restaurations')[0], 403)
        self.assertEqual(self.find('', token=token, sort='size')[0], 200)
        # Avec un nom, le classement s'applique aux noms qui correspondent.
        (self.files / 'Factures/facture ÉTÉ.pdf').write_bytes(b'x' * 800)
        self.assertEqual([name for _, _, name in self.found('été', sort='size')][:2], ['facture ÉTÉ.pdf', 'été.md'])
        self.assertEqual(self.find('été')[1]['sort'], None)
        # Le classement lit tout et ne garde que les meilleurs : au-delà de la limite, le total rencontré est dit.
        with patch.object(file_search, 'RESULTS', 2):
            status, value = self.find('', sort='size')
            self.assertEqual(([i['name'] for i in value['items']], value['partial'], value['limit']), (['énorme.bin', 'film.mp4'], None, 2))
            self.assertGreater(value['matched'], 2)
        with patch.object(file_search, 'VISITED', 3):
            status, value = self.find('', sort='size')
            self.assertEqual((status, value['partial'], value['visited']), (200, 'count', 4))
        # Ni nom ni critère, un seul caractère avec un critère, un classement inconnu : refusés.
        for text, query in (('', {}), (' ', {}), ('', {'sort': ''}), ('e', {'sort': 'size'}), ('', {'sort': 'name'}), ('été', {'sort': 'Size'}), ('', {'sort': 'size', 'path': 'Photos'})):
            self.assertEqual(self.find(text, **query)[0], 400, (text, query))

    def weigh(self, token=None, **scope):
        status, _, data = self.call('GET', '/api/files/usage?' + '&'.join(f'{key}={quote(value)}' for key, value in scope.items()), token=token)
        return status, json.loads(data)

    def test_usage_weighs_every_folder_with_all_it_holds_and_says_what_it_could_not_finish(self):
        import file_search
        self.tree()
        for name, size in (('Photos/a.bin', 1000), ('Photos/Été 2026/b.bin', 2000), ('Photos/Été 2026/.cache.bin', 300), ('Factures/c.bin', 500), ('gros.bin', 4000),
                           ('.cache/d.bin', 70), ('.masqué.bin', 30)):
            (self.files / name).write_bytes(b'x' * size)
        (self.files / '.nacre-trash').mkdir(exist_ok=True); (self.files / '.nacre-trash/jeté.bin').write_bytes(b'x' * 600)
        (self.outside / 'énorme.bin').write_bytes(b'x' * 50000)
        status, value = self.weigh(area='fichiers')
        self.assertEqual(status, 200, value)
        rows = {i['name']: (i['directory'], i['size'], i['count'], i['state']) for i in value['items']}
        # Un dossier pèse tout ce qu'il contient, fichiers cachés compris ; un fichier pèse sa taille ; un lien n'est jamais suivi.
        self.assertEqual(rows['Photos'], (True, 1000 + 2000 + 300 + 5 + 5, 6, 'whole'))
        self.assertEqual(rows['Factures'], (True, 500 + 3 + 7, 3, 'whole'))
        self.assertEqual((rows['gros.bin'], rows['été.md']), ((False, 4000, 0, 'whole'), (False, 6, 0, 'whole')))
        link = next(i for i in value['items'] if i['name'] == 'lien été')
        self.assertEqual((link['link'], link['directory'], link['count']), (True, False, 0)); self.assertLess(link['size'], 200)
        # Du plus lourd au plus léger ; cachés et corbeille comptés ensemble, jamais nommés.
        self.assertEqual([i['name'] for i in value['items']][:3], ['gros.bin', 'Photos', 'Factures'])
        self.assertNotIn('cach', json.dumps(value)); self.assertNotIn('masqu', json.dumps(value)); self.assertNotIn('trash', json.dumps(value)); self.assertNotIn('jet', json.dumps(value))
        self.assertEqual(value['hidden'], {'size': 7 + 70 + 30 + 600, 'count': 6, 'state': 'whole'})
        self.assertEqual(value['total']['size'], sum(i['size'] for i in value['items']) + value['hidden']['size'])
        self.assertEqual((value['total']['state'], value['partial'], value['others'], value['limit'], value['area'], value['path']), ('whole', None, {'count': 0, 'size': 0}, 200, 'fichiers', ''))
        self.assertEqual(value['total']['count'], len(value['items']) + sum(i['count'] for i in value['items']) + value['hidden']['count'])
        # Depuis un sous-dossier ; l'espace par défaut est Fichiers.
        status, value = self.weigh(area='fichiers', path='Photos')
        self.assertEqual([(i['name'], i['size'], i['count']) for i in value['items']], [('Été 2026', 2305, 3), ('a.bin', 1000, 0), ('ete-notes.txt', 5, 0)])
        self.assertEqual((value['hidden'], value['total']), ({'size': 0, 'count': 0, 'state': 'whole'}, {'size': 3310, 'count': 6, 'state': 'whole'}))
        self.assertEqual(self.weigh()[1]['total']['size'], self.weigh(area='fichiers')[1]['total']['size'])
        # Droits et chemins : ceux du gestionnaire de fichiers.
        self.assertEqual(self.weigh(area='restaurations')[0], 200)
        token, _ = self.reader()
        self.assertEqual((self.weigh(token=token, area='restaurations')[0], self.weigh(token=token, area='native_volume')[0], self.weigh(token=token, area='fichiers')[0]), (403, 403, 200))
        for query, expected in (({'area': 'fichiers', 'path': '../hors-espace'}, 403), ({'area': 'fichiers', 'path': 'lien été'}, 404), ({'area': 'fichiers', 'path': 'absent'}, 404),
                                ({'area': 'fichiers', 'path': '.nacre-trash'}, 403), ({'area': 'ailleurs'}, 400)):
            self.assertEqual(self.weigh(**query)[0], expected, query)
        self.assertEqual(self.call('GET', '/api/files/usage?area=fichiers', token='inconnu')[0], 401)
        # Borne atteinte : le dossier en cours est un minimum, les suivants ne sont pas pesés, et le total le dit.
        with patch.object(file_search, 'VISITED', 8):
            status, value = self.weigh(area='fichiers')
            states = {i['name']: i['state'] for i in value['items'] if i['directory']}
            self.assertEqual((status, value['partial'], states, value['total']['state'], value['hidden']['state']), (200, 'count', {'Factures': 'partial', 'Photos': 'waiting'}, 'partial', 'partial'))
            self.assertEqual([i['name'] for i in value['items']][-1], 'Photos')
        with patch.object(file_search, 'SECONDS', -1):
            for index in range(300):
                (self.files / 'Factures' / f'piece-{index:03}.txt').write_text('x')
            status, value = self.weigh(area='fichiers')
            self.assertEqual((status, value['partial'], value['total']['state']), (200, 'time', 'partial'))
        # Au-delà de la limite, le reste est compté d'un bloc ; deux parcours à la fois au plus.
        with patch.object(file_search, 'RESULTS', 2):
            status, value = self.weigh(area='fichiers', path='Factures')
            self.assertEqual(([i['name'] for i in value['items']], value['others']), (['c.bin', 'facture ÉTÉ.pdf'], {'count': 300, 'size': 300}))
            self.assertEqual((value['total'], value['hidden']['size']), ({'size': 810, 'count': 303, 'state': 'whole'}, 7))
        self.assertTrue(file_search._slots.acquire(blocking=False)); self.assertTrue(file_search._slots.acquire(blocking=False))
        try:
            self.assertEqual(self.weigh(area='fichiers')[0], 429)
        finally:
            file_search._slots.release(); file_search._slots.release()
        self.assertEqual(self.weigh(area='fichiers')[0], 200)

    def test_weighing_a_whole_space_is_kept_so_spaces_can_be_compared_without_reading_the_disk(self):
        import file_search
        self.tree()
        (self.files / 'gros.bin').write_bytes(b'x' * 4000)

        def listed(token=None):
            status, _, data = self.call('GET', '/api/files/usage-spaces', token=token)
            self.assertEqual(status, 200)
            return {item['id']: item for item in json.loads(data)['spaces']}
        # Rien n'est gardé avant une pesée ; l'administrateur voit aussi les restaurations privées.
        before = listed()
        self.assertEqual({name: item['kept'] for name, item in before.items()}, dict.fromkeys(('fichiers', 'video', 'sauvegardes', 'restaurations'), None))
        self.assertEqual(before['fichiers']['name'], 'Fichiers partagés')
        # Peser un sous-dossier ne garde rien ; peser un espace entier garde son total, son décompte et l'heure.
        self.assertEqual(self.weigh(area='fichiers', path='Photos')[0], 200)
        self.assertIsNone(listed()['fichiers']['kept'])
        status, value = self.weigh(area='fichiers')
        kept = listed()['fichiers']['kept']
        self.assertEqual((status, kept['size'], kept['count'], kept['state']), (200, value['total']['size'], value['total']['count'], 'whole'))
        self.assertLess(abs(kept['at'] - time.time()), 30)
        self.assertEqual(self.weigh(area='video')[0], 200)
        self.assertEqual({name: item['kept'] is not None for name, item in listed().items()}, {'fichiers': True, 'video': True, 'sauvegardes': False, 'restaurations': False})
        # Une nouvelle pesée remplace l'ancienne ; arrêtée avant la fin, elle est gardée comme un minimum.
        (self.files / 'gros.bin').write_bytes(b'x' * 9000)
        self.assertEqual(self.weigh(area='fichiers')[0], 200)
        self.assertEqual(listed()['fichiers']['kept']['size'], kept['size'] + 5000)
        with patch.object(file_search, 'VISITED', 3):
            self.assertEqual(self.weigh(area='fichiers')[0], 200)
        self.assertEqual(listed()['fichiers']['kept']['state'], 'partial')
        # Un compte en lecture seule ne voit que ses espaces ; une valeur gardée illisible est ignorée.
        token, _ = self.reader()
        self.assertEqual(sorted(listed(token)), ['fichiers', 'sauvegardes', 'video'])
        with server.database() as db:
            db.execute("UPDATE settings SET value='{cassé' WHERE key='usage-kept:video'")
        self.assertIsNone(listed()['video']['kept'])

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
