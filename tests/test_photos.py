"""Photos : index par date, vignettes relues dans les fichiers, envoi depuis un appareil. Vrai serveur, dossier temporaire."""
import http.client
import os
import random
import sqlite3
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import quote

import test_spaces
import exif_fixture as fixture
import library
import photos

app = test_spaces.app


class DescribeTests(unittest.TestCase):
    def test_camera_block_gives_date_orientation_and_the_place_of_its_thumbnail(self):
        raw = fixture.jpeg(date='2024:07:14 10:30:00', taken='2024:07:13 09:15:00', orient=6, model='Appareil <b>', thumb=fixture.TINY, size=(4000, 3000))
        found = photos.describe(raw)
        # La date de prise de vue l'emporte sur celle de l'enregistrement ; le nom de l'appareil perd ce qui ressemble à du balisage.
        self.assertEqual((found['taken'], found['orient'], found['width'], found['height'], found['model']), ('2024-07-13T09:15:00', 6, 4000, 3000, 'Appareil b'))
        self.assertEqual(raw[found['thumb_at']:found['thumb_at'] + found['thumb_len']], fixture.TINY)
        other = fixture.jpeg(date='2023:01:02 03:04:05', orient=3, thumb=fixture.TINY, order='>')
        found = photos.describe(other)
        self.assertEqual((found['taken'], found['orient'], found['width'], found['height']), ('2023-01-02T03:04:05', 3, 8, 8))
        self.assertEqual(other[found['thumb_at']:found['thumb_at'] + found['thumb_len']], fixture.TINY)
        # Sans bloc d'appareil : pas de date, dimensions lues quand le format les donne d'emblée.
        self.assertEqual(photos.describe(fixture.TINY), {**photos.empty(), 'width': 8, 'height': 8})
        self.assertEqual(photos.describe(fixture.png(640, 480)), {**photos.empty(), 'width': 640, 'height': 480})
        self.assertEqual(photos.describe(b'GIF89a\x10\x00\x20\x00'), {**photos.empty(), 'width': 16, 'height': 32})
        for odd in (b'', b'\xff', b'\xff\xd8\xff', b'pas une image', fixture.jpeg(taken='2024:13:45 99:99:99'), fixture.jpeg(taken='1850:01:01 00:00:00'), fixture.jpeg(orient=9)):
            found = photos.describe(odd)
            self.assertEqual((found['taken'], found['orient'], found['thumb_len']), (None, 1, 0), odd[:12])
        # Vignette annoncée hors du fichier, ou qui ne commence pas comme une image : écartée.
        cut = raw[:found['thumb_at'] + 20] if (found := photos.describe(raw))['thumb_len'] else raw
        self.assertEqual(photos.describe(cut)['thumb_len'], 0)
        self.assertEqual(photos.describe(fixture.jpeg(taken='2024:07:13 09:15:00', thumb=b'<script>alert(1)</script>'))['thumb_len'], 0)

    def test_damaged_files_never_raise_and_never_point_outside_themselves(self):
        raw, rng = fixture.jpeg(date='2024:07:14 10:30:00', taken='2024:07:13 09:15:00', orient=6, model='Banc', thumb=fixture.TINY, size=(4000, 3000)), random.Random(7)
        for _ in range(4000):
            damaged = bytearray(raw)
            for _ in range(rng.randint(1, 6)):
                damaged[rng.randrange(len(damaged))] = rng.randrange(256)
            if rng.random() < .3:
                del damaged[rng.randrange(len(damaged)):]
            found = photos.describe(bytes(damaged))
            self.assertIn(found['orient'], range(1, 9))
            if found['thumb_len']:
                self.assertLessEqual(found['thumb_at'] + found['thumb_len'], len(damaged))
                self.assertEqual(bytes(damaged[found['thumb_at']:found['thumb_at'] + 2]), b'\xff\xd8')
            if found['taken'] is not None:
                self.assertRegex(found['taken'], r'^(19|20|21)\d\d-\d\d-\d\dT\d\d:\d\d:\d\d$')


class PhotoTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home, upload = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home', 'upload'))

    def team(self):
        photos.SCAN.stop()
        photos.SCAN = library.Scanner(photos.work, fresh=0)   # chaque demande relit, pour que l'essai voie ses propres changements
        self.addCleanup(photos.SCAN.stop)
        self.people(camille='member', bruno='member', dora='member', lecteur='viewer')
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.team_dir = Path(app.ROOT) / 'data/espaces' / self.space[7:]
        self.mine = self.home('camille')
        self.mine_dir = Path(app.ROOT) / 'data/espaces' / self.mine[7:]
        self.common = Path(app.ROOT) / 'data/fichiers'
        self.mine_dir.mkdir(parents=True, exist_ok=True)

    def listed(self, who, extra=''):
        """Liste après un parcours complet : une première demande le lance, on l'attend, la seconde le lit sans en relancer."""
        photos.SCAN.fresh = 0
        self.get(who, '/api/photos' + extra)
        photos.SCAN.wait()
        photos.SCAN.fresh = 3600
        return self.get(who, '/api/photos' + extra)

    def raw(self, who, path):
        return self.request('GET', path, token=self.sessions[who][0])

    def test_gallery_gathers_by_date_only_what_the_person_may_read(self):
        self.team()
        shot = lambda taken, **more: fixture.jpeg(taken=taken, thumb=fixture.TINY, **more)
        (self.team_dir / 'Visites').mkdir()
        (self.team_dir / 'Visites/dalle.jpg').write_bytes(shot('2026:11:03 09:00:00', orient=6, model='Banc'))
        (self.team_dir / 'facade.JPG').write_bytes(shot('2026:10:20 16:30:00'))
        (self.mine_dir / 'famille.jpeg').write_bytes(shot('2026:11:10 12:00:00'))
        (self.common / 'plan.png').write_bytes(fixture.png(640, 480))
        os.utime(self.common / 'plan.png', (1_700_000_000, 1_700_000_000))   # 14 novembre 2023, date du fichier
        (self.common / 'notes.txt').write_text('pas une image')
        (self.common / '.cache').mkdir(); (self.common / '.cache/cachee.jpg').write_bytes(shot('2026:11:11 11:11:11'))
        (self.common / 'lien.jpg').symlink_to(self.mine_dir / 'famille.jpeg')
        status, data = self.listed('camille')
        self.assertEqual((status, data['scan']['error'], data['scan']['partial']), (200, None, None))
        self.assertEqual([(i['name'], i['taken'], i['dated'], i['thumb'], i['orient']) for i in data['items']],
                         [('famille.jpeg', '2026-11-10T12:00:00', True, True, 1), ('dalle.jpg', '2026-11-03T09:00:00', True, True, 6),
                          ('facade.JPG', '2026-10-20T16:30:00', True, True, 1), ('plan.png', '2023-11-14T22:13:20', False, False, 1)])
        self.assertEqual((data['total'], data['months'], data['next'], data['personal']), (4, [['2026-11', 2], ['2026-10', 1], ['2023-11', 1]], None, True))
        self.assertEqual([a['name'] for a in data['areas']], ['Mon espace', 'Chantier', 'Fichiers partagés'])
        self.assertEqual((data['items'][1]['area'], data['items'][1]['path'], data['items'][1]['model'], data['items'][3]['width']), (self.space, 'Visites/dalle.jpg', 'Banc', 640))
        self.assertEqual((data['scan']['running'], data['scan']['error'], data['scan']['partial']), (False, None, None))
        # Chacun ne reçoit que ses espaces : l'administrateur ne voit pas l'espace personnel d'un membre, un membre hors de l'équipe non plus.
        seen = lambda who: sorted(i['name'] for i in self.listed(who)[1]['items'])
        self.assertEqual(seen('bruno'), ['dalle.jpg', 'facade.JPG', 'plan.png'])
        self.assertEqual(seen('dora'), ['plan.png'])
        self.assertEqual(seen('lecteur'), ['plan.png'])
        self.assertEqual(seen('admin'), ['dalle.jpg', 'facade.JPG', 'plan.png'])
        self.assertEqual(self.listed('lecteur')[1]['personal'], False)
        self.assertEqual(self.request('GET', '/api/photos')[0], 401)
        # Un seul espace, à condition d'y avoir droit.
        self.assertEqual([i['name'] for i in self.listed('camille', f'?area={self.space}')[1]['items']], ['dalle.jpg', 'facade.JPG'])
        for who, area in (('dora', self.space), ('bruno', self.mine), ('admin', self.mine), ('camille', 'video'), ('camille', 'inconnu')):
            self.assertEqual(self.get(who, f'/api/photos?area={area}')[0], 403, (who, area))
        # Suite de la liste : page par page, sans trou ni doublon.
        with unittest.mock.patch.object(photos, 'PAGE', 2):
            first = self.listed('camille')[1]
            self.assertEqual(([i['name'] for i in first['items']], first['total']), (['famille.jpeg', 'dalle.jpg'], 4))
            second = self.get('camille', '/api/photos?before=' + quote(first['next']))[1]
            self.assertEqual(([i['name'] for i in second['items']], second['next'], 'total' in second), (['facade.JPG', 'plan.png'], None, False))
        for bad in ('x', '2026-11-10T12:00:00', '2026-11-10T12:00:00~x', "2026-11-10T12:00:00~1' OR 1=1"):
            self.assertEqual(self.get('camille', '/api/photos?before=' + quote(bad))[0], 400, bad)
        # L'index vit à part : la base de Nacre n'a pas changé de forme.
        self.assertTrue((Path(app.STATE) / 'photos.db').is_file())
        with app.database() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='photos'").fetchone())

    def test_a_new_index_is_shaped_once_when_page_and_scan_reach_it_together(self):
        self.team()
        (self.mine_dir / 'seule.jpg').write_bytes(fixture.jpeg(taken='2026:11:10 12:00:00'))
        import threading
        for attempt in range(12):
            photos.SCAN.wait()
            for extra in ('', '-wal', '-shm'):
                Path(str(Path(app.STATE) / 'photos.db') + extra).unlink(missing_ok=True)
            failures, start = [], threading.Barrier(6)

            def reach():
                start.wait()
                try:
                    with library.index(app, 'photos.db', photos.VERSION, photos.SCHEMA) as db:
                        db.execute('SELECT count(*) FROM photos').fetchone()
                except Exception as failure:
                    failures.append(repr(failure))
            threads = [threading.Thread(target=reach) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(failures, [], attempt)
        status, data = self.listed('camille')
        self.assertEqual((status, data['scan']['error'], [i['name'] for i in data['items']]), (200, None, ['seule.jpg']))

    def test_thumbnail_is_read_back_from_the_file_under_the_rights_of_the_person(self):
        self.team()
        (self.mine_dir / 'famille.jpg').write_bytes(fixture.jpeg(taken='2026:11:10 12:00:00', thumb=fixture.TINY))
        (self.team_dir / 'dalle.jpg').write_bytes(fixture.jpeg(taken='2026:11:03 09:00:00', thumb=fixture.TINY))
        (self.team_dir / 'sans.jpg').write_bytes(fixture.jpeg(taken='2026:11:02 09:00:00'))
        items = {i['name']: i for i in self.listed('camille')[1]['items']}
        url = lambda area, path, v='': f'/api/photos/thumb?area={area}&path={quote(path)}' + (f'&v={v}' if v else '')

        def fetch(who, address):
            conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
            conn.request('GET', address, headers={'Cookie': 'nas_session=' + self.sessions[who][0]})
            response = conn.getresponse()
            body = response.read()
            conn.close()
            return response.status, body, dict(response.getheaders())
        status, body, headers = fetch('camille', url(self.mine, 'famille.jpg', items['famille.jpg']['v']))
        self.assertEqual((status, body, headers['Content-Type'], headers['X-Content-Type-Options']), (200, fixture.TINY, 'image/jpeg', 'nosniff'))
        # Gardée par le navigateur de la personne, et de lui seul, quand l'adresse porte la date du fichier ; sinon jamais.
        self.assertEqual(headers['Cache-Control'], 'private, max-age=604800, immutable')
        self.assertEqual(fetch('camille', url(self.space, 'dalle.jpg'))[2]['Cache-Control'], 'no-store')
        self.assertEqual(fetch('camille', url(self.space, 'dalle.jpg', '1'))[2]['Cache-Control'], 'no-store')
        # Les droits de l'espace s'appliquent à la vignette comme au fichier.
        for who, area, path, expected in (('bruno', self.mine, 'famille.jpg', 403), ('admin', self.mine, 'famille.jpg', 403), ('dora', self.space, 'dalle.jpg', 403),
                                          ('bruno', self.space, 'dalle.jpg', 200), ('camille', self.space, 'sans.jpg', 404), ('camille', self.space, 'absent.jpg', 404),
                                          ('camille', self.space, '../' + self.mine[7:] + '/famille.jpg', 403), ('camille', self.space, '', 400)):
            self.assertEqual(self.raw(who, url(area, path))[0], expected, (who, path))
        self.assertEqual(self.request('GET', url(self.space, 'dalle.jpg'))[0], 401)
        # Fichier remplacé depuis le parcours : l'ancienne adresse de vignette ne vaut plus, rien d'autre n'est servi à sa place.
        (self.team_dir / 'dalle.jpg').write_bytes(b'x' * 4000)
        self.assertEqual(self.raw('camille', url(self.space, 'dalle.jpg'))[0], 404)

    def test_index_follows_changes_removals_and_deleted_spaces(self):
        self.team()
        (self.team_dir / 'a.jpg').write_bytes(fixture.jpeg(taken='2026:11:03 09:00:00', thumb=fixture.TINY))
        (self.team_dir / 'b.jpg').write_bytes(fixture.jpeg(taken='2026:11:04 09:00:00'))
        names = lambda who: [(i['name'], i['taken']) for i in self.listed(who)[1]['items']]
        self.assertEqual(names('camille'), [('b.jpg', '2026-11-04T09:00:00'), ('a.jpg', '2026-11-03T09:00:00')])
        # Image changée, image retirée, image ajoutée : le parcours suivant s'y accorde.
        (self.team_dir / 'a.jpg').write_bytes(fixture.jpeg(taken='2026:12:01 08:00:00'))
        (self.team_dir / 'b.jpg').unlink()
        (self.team_dir / 'c.png').write_bytes(fixture.png())
        os.utime(self.team_dir / 'c.png', (1_700_000_000, 1_700_000_000))
        self.assertEqual(names('camille'), [('a.jpg', '2026-12-01T08:00:00'), ('c.png', '2023-11-14T22:13:20')])
        # Un parcours ne relit pas ce qui n'a pas changé.
        opened = []
        real = photos.describe
        with unittest.mock.patch.object(photos, 'describe', side_effect=lambda head: opened.append(1) or real(head)):
            self.listed('camille')
        self.assertEqual(opened, [])
        # Espace supprimé : ses photos quittent l'index.
        (self.team_dir / 'a.jpg').unlink(); (self.team_dir / 'c.png').unlink()
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 200)
        with sqlite3.connect(Path(app.STATE) / 'photos.db') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM photos').fetchone()[0], 2)
        self.assertEqual(names('camille'), [])
        with sqlite3.connect(Path(app.STATE) / 'photos.db') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM photos').fetchone()[0], 0)
        # Index effacé ou d'une autre forme : il se reconstruit.
        (self.mine_dir / 'seule.jpg').write_bytes(fixture.jpeg(taken='2026:11:10 12:00:00'))
        self.assertEqual(names('camille'), [('seule.jpg', '2026-11-10T12:00:00')])
        photos.SCAN.wait()
        with sqlite3.connect(Path(app.STATE) / 'photos.db') as db:
            db.execute('DROP TABLE photos'); db.execute('CREATE TABLE autre(x)'); db.execute('PRAGMA user_version=99')
        self.assertEqual(names('camille'), [('seule.jpg', '2026-11-10T12:00:00')])
        # Actualiser : réservé à qui peut écrire quelque part ; un compte en lecture seule relit en ouvrant la page.
        self.assertEqual(self.post('camille', '/api/photos/refresh', {})[0], 200)
        self.assertEqual(self.post('lecteur', '/api/photos/refresh', {})[0], 403)

    def test_sending_from_a_device_files_by_month_and_never_duplicates(self):
        self.team()
        november, october = 1794000000000, 1791500000000     # 7 novembre 2026 et 9 octobre 2026, en millisecondes
        wanted = [{'name': 'IMG_0001.jpg', 'size': 159, 'modified': november}, {'name': 'IMG_0002.JPG', 'size': 20, 'modified': october},
                  {'name': 'clip.mov', 'size': 5, 'modified': november}, {'name': 'notes.txt', 'size': 3, 'modified': november}, {'name': 'IMG_0001.jpg', 'size': 159, 'modified': november}]
        status, made = self.post('camille', '/api/photos/plan', {'items': wanted})
        self.assertEqual(status, 200, made)
        self.assertEqual(made['area'], self.mine)
        self.assertEqual([(i['name'], i['state'], i.get('path'), i.get('as')) for i in made['items']],
                         [('IMG_0001.jpg', 'send', 'Photos/2026-11', 'IMG_0001.jpg'), ('IMG_0002.JPG', 'send', 'Photos/2026-10', 'IMG_0002.JPG'),
                          ('clip.mov', 'send', 'Photos/2026-11', 'clip.mov'), ('notes.txt', 'refused', None, None), ('IMG_0001.jpg', 'present', 'Photos/2026-11', 'IMG_0001.jpg')])
        self.assertTrue((self.mine_dir / 'Photos/2026-11').is_dir() and (self.mine_dir / 'Photos/2026-10').is_dir())
        # Rien n'est écrit par la préparation : l'envoi passe par le dépôt ordinaire, avec ses gardes.
        self.assertEqual(list((self.mine_dir / 'Photos/2026-11').iterdir()), [])
        self.assertEqual(self.upload('camille', self.mine, 'IMG_0001.jpg', fixture.TINY, 'Photos/2026-11')[0], 200)
        # Renvoyer la même pellicule : déjà là. Même nom, autre contenu : rangé à côté, puis reconnu à son tour.
        again = self.post('camille', '/api/photos/plan', {'items': [wanted[0], {'name': 'IMG_0001.jpg', 'size': 4000, 'modified': november}]})[1]['items']
        self.assertEqual([(i['state'], i.get('as')) for i in again], [('present', 'IMG_0001.jpg'), ('send', 'IMG_0001 (2).jpg')])
        self.assertEqual(self.upload('camille', self.mine, 'IMG_0001 (2).jpg', b'y' * 4000, 'Photos/2026-11')[0], 200)
        third = self.post('camille', '/api/photos/plan', {'items': [{'name': 'IMG_0001.jpg', 'size': 4000, 'modified': november}, {'name': 'IMG_0001.jpg', 'size': 77, 'modified': november}]})[1]['items']
        self.assertEqual([(i['state'], i.get('as')) for i in third], [('present', 'IMG_0001 (2).jpg'), ('send', 'IMG_0001 (3).jpg')])
        # La photo envoyée rejoint la galerie.
        self.assertEqual(sorted(i['path'] for i in self.listed('camille')[1]['items']), ['Photos/2026-11/IMG_0001 (2).jpg', 'Photos/2026-11/IMG_0001.jpg'])
        # Date fantaisiste : rangée au mois courant plutôt que dans un dossier absurde.
        odd = self.post('camille', '/api/photos/plan', {'items': [{'name': 'vieux.jpg', 'size': 1, 'modified': 0}, {'name': 'futur.jpg', 'size': 1, 'modified': 9e15}]})[1]['items']
        current = library.local(time.time(), library.zone(app))[:7]
        self.assertEqual([i['path'] for i in odd], [f'Photos/{current}'] * 2)
        for bad in ({}, {'items': []}, {'items': 'x'}, {'items': [{'name': 'a.jpg'}]}, {'items': [{'name': 'a.jpg', 'size': -1, 'modified': 1}]}, {'items': [{'name': 'a.jpg', 'size': True, 'modified': 1}]},
                    {'items': [{'name': '../a.jpg', 'size': 1, 'modified': november}]}, {'items': [{'name': '.cache.jpg', 'size': 1, 'modified': november}]},
                    {'items': [{'name': 'a.jpg', 'size': 1, 'modified': november}] * (photos.PLAN + 1)}):
            self.assertEqual(self.post('camille', '/api/photos/plan', bad)[0], 400, str(bad)[:60])
        # Un compte en lecture seule n'a pas d'espace où déposer ; un fichier nommé « Photos » n'est jamais écrasé.
        self.assertEqual(self.post('lecteur', '/api/photos/plan', {'items': [wanted[0]]})[0], 403)
        theirs = Path(app.ROOT) / 'data/espaces' / self.home('bruno')[7:]
        theirs.mkdir(parents=True, exist_ok=True); (theirs / 'Photos').write_text('un fichier')
        self.assertEqual(self.post('bruno', '/api/photos/plan', {'items': [wanted[0]]})[0], 409)
        self.assertEqual((theirs / 'Photos').read_text(), 'un fichier')


if __name__ == '__main__':
    unittest.main()
