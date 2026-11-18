"""Corbeille : retirer pour de bon, vider, durée de garde. Vrai serveur, dossier temporaire."""
import os
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import quote

import test_spaces
import spaces
import trash
import versions

app = test_spaces.app


class TrashTests(unittest.TestCase):
    setUp, tearDown, request = test_spaces.SpaceTests.setUp, test_spaces.SpaceTests.tearDown, test_spaces.SpaceTests.request
    people, get, post, home, audit, upload = (getattr(test_spaces.SpaceTests, name) for name in ('people', 'get', 'post', 'home', 'audit', 'upload'))

    def team(self):
        self.people(camille='member', bruno='member', dora='member', lecteur='viewer')
        self.space = self.post('admin', '/api/spaces/space', {'name': 'Chantier école', 'members': {'camille': 'write', 'bruno': 'read'}})[1]['id']
        self.team_dir = Path(app.ROOT) / 'data/espaces' / self.space[7:]
        self.mine = self.home('camille')
        self.mine_dir = Path(app.ROOT) / 'data/espaces' / self.mine[7:]
        self.common = Path(app.ROOT) / 'data/fichiers'

    def throw(self, who, area, path):
        self.assertEqual(self.post(who, '/api/trash', {'area': area, 'path': path})[0], 200, path)

    def listed(self, who):
        return {row['original']: row for row in self.get(who, '/api/trash')[1]}

    def replace(self, who, area, name, content):
        return self.post(who, f'/api/upload?area={area}&path=&name={quote(name)}&replace=1', raw=content)[0]

    def clear(self, who, area, **extra):
        """Vide la corbeille comme le fait la page : avec l'instant de ce qu'elle vient de montrer."""
        return self.post(who, '/api/trash/empty', {'area': area, 'confirm': True, 'until': self.get(who, '/api/trash/overview')[1]['at'], **extra})

    def blobs(self, folder):
        return len([n for n in os.listdir(folder / '.nacre-versions') if n != versions.INDEX])

    def kept(self, who, area, path):
        return [v['size'] for v in self.get(who, f'/api/files/versions?area={area}&path={quote(path)}')[1]['versions']]

    def test_erasing_for_good_belongs_to_whoever_answers_for_the_space(self):
        self.team()
        for name in ('a.txt', 'b.txt'):
            self.assertEqual(self.upload('camille', self.space, name)[0], 200)
            self.throw('camille', self.space, name)
        self.assertEqual(self.upload('camille', self.mine, 'perso.txt')[0], 200); self.throw('camille', self.mine, 'perso.txt')
        (self.common / 'commun.txt').write_text('commun'); self.throw('admin', 'fichiers', 'commun.txt')
        # Chacun voit ce qu'il peut restaurer ; retirer pour de bon n'est proposé qu'à qui répond de l'espace.
        rights = lambda who: {name: (row['restore'], row['erase']) for name, row in self.listed(who).items()}
        self.assertEqual(rights('camille'), {'a.txt': (True, False), 'b.txt': (True, False), 'perso.txt': (True, True)})
        self.assertEqual(rights('admin'), {'a.txt': (True, True), 'b.txt': (True, True), 'commun.txt': (True, True)})
        self.assertEqual((rights('bruno'), rights('dora'), rights('lecteur')), ({}, {}, {'commun.txt': (False, False)}))
        view = self.get('camille', '/api/trash/overview')[1]
        self.assertEqual((view['days'], view['manage'], sorted((a['name'], a['count'], a['erase']) for a in view['areas'])), (0, False, [('Chantier école', 2, False), ('Mon espace', 1, True)]))
        self.assertTrue(self.get('admin', '/api/trash/overview')[1]['manage'])
        ident = lambda who, name: self.listed(who)[name]['id']
        team_a, perso, commun = ident('camille', 'a.txt'), ident('camille', 'perso.txt'), ident('admin', 'commun.txt')
        # Écrire dans un espace d'équipe ne suffit pas à y effacer ; lire encore moins ; l'espace personnel d'un autre reste fermé, même à l'administrateur.
        self.assertEqual(self.post('camille', '/api/trash/delete', {'id': team_a, 'confirm': True})[0], 403)
        self.assertEqual(self.post('camille', '/api/trash/empty', {'area': self.space, 'confirm': True})[0], 403)
        for who, body, route in (('bruno', {'id': team_a, 'confirm': True}, 'delete'), ('dora', {'id': team_a, 'confirm': True}, 'delete'), ('bruno', {'area': self.space, 'confirm': True}, 'empty'),
                                 ('admin', {'id': perso, 'confirm': True}, 'delete'), ('admin', {'area': self.mine, 'confirm': True}, 'empty'), ('admin', {'id': 'f' * 32, 'confirm': True}, 'delete'),
                                 ('admin', {'id': 7, 'confirm': True}, 'delete'), ('admin', {'area': 'espace_' + '0' * 12, 'confirm': True}, 'empty'), ('admin', {'area': 7, 'confirm': True}, 'empty')):
            self.assertEqual(self.post(who, f'/api/trash/{route}', body)[0], 404, (who, body))
        for route, body in (('delete', {'id': commun, 'confirm': True}), ('empty', {'area': 'fichiers', 'confirm': True}), ('retention', {'days': 0})):
            self.assertEqual(self.post('lecteur', f'/api/trash/{route}', body)[0], 403, route)
        self.assertEqual(self.post('camille', '/api/trash/retention', {'days': 0})[0], 403)
        # Jamais sans confirmation explicite.
        for body in ({'id': team_a}, {'id': team_a, 'confirm': 'oui'}, {'id': team_a, 'confirm': 1}):
            self.assertEqual(self.post('admin', '/api/trash/delete', body)[0], 400, body)
        self.assertEqual(self.post('admin', '/api/trash/empty', {'area': self.space})[0], 400)
        self.assertEqual(len(os.listdir(self.team_dir / '.nacre-trash')), 2)
        # L'administrateur retire un élément de l'équipe ; la personne, ceux de son espace. L'autre élément reste restaurable.
        status, done = self.post('admin', '/api/trash/delete', {'id': team_a, 'confirm': True})
        self.assertEqual((status, done['items'], done['bytes']), (200, 1, 7))
        self.assertEqual(self.post('admin', '/api/trash/delete', {'id': team_a, 'confirm': True})[0], 404)
        self.assertEqual(self.post('admin', '/api/restore', {'id': team_a})[0], 404)
        self.assertEqual(self.post('camille', '/api/trash/delete', {'id': perso, 'confirm': True})[0], 200)
        self.assertEqual((sorted(self.listed('camille')), os.listdir(self.mine_dir / '.nacre-trash'), len(os.listdir(self.team_dir / '.nacre-trash'))), (['b.txt'], [], 1))
        self.assertEqual(self.post('camille', '/api/restore', {'id': ident('camille', 'b.txt')})[0], 200)
        self.assertEqual((self.team_dir / 'b.txt').read_bytes(), b'contenu')
        log = self.audit()
        self.assertIn(('admin', 'Retiré pour de bon de la corbeille', 'Chantier école : a.txt'), log)
        self.assertIn(('camille', 'Retiré pour de bon de la corbeille', 'espace personnel'), log)   # aucun nom d'un espace personnel au journal
        # La page et son script sont servis.
        status, raw = self.request('GET', '/trash.js')
        self.assertEqual(status, 200); self.assertIn('renderTrash', raw if isinstance(raw, str) else raw.decode())

    def test_emptying_erases_everything_listed_follows_no_link_and_leaves_the_rest_alone(self):
        self.team()
        outside = Path(app.ROOT) / 'hors-espace'; outside.mkdir(); (outside / 'précieux.txt').write_text('ne pas toucher')
        tree = self.team_dir / 'Chantier'
        (tree / 'Plans/Façade').mkdir(parents=True); (tree / 'Plans/Façade/plan.pdf').write_bytes(b'%PDF' * 100); (tree / 'note.txt').write_text('note')
        os.symlink(outside, tree / 'vers-dehors'); os.symlink(outside / 'précieux.txt', tree / 'lien.txt')
        locked = tree / 'Fermé'; locked.mkdir(); (locked / 'dedans.txt').write_text('x'); os.chmod(locked, 0o500)
        deep = self.team_dir / 'Profond'; here = deep
        for index in range(trash.DEPTH * 2 + 5):
            here = here / 'n'
        here.mkdir(parents=True); (here / 'fond.txt').write_text('au fond')
        for name in ('seul.txt', 'gardé.txt'):
            self.assertEqual(self.upload('camille', self.space, name, b'un')[0], 200)
        # Versions : celles du fichier jeté le suivent en corbeille et partent avec lui ; celles d'un fichier créé depuis sous le même nom restent.
        self.assertEqual(self.replace('camille', self.space, 'seul.txt', b'deux!'), 200)
        self.assertEqual(self.kept('camille', self.space, 'seul.txt'), [2])
        for name in ('Chantier', 'Profond', 'seul.txt'):
            self.throw('camille', self.space, name)
        time.sleep(.02)
        self.assertEqual(self.upload('camille', self.space, 'seul.txt', b'nouveau')[0], 200)
        self.assertEqual(self.replace('camille', self.space, 'seul.txt', b'nouveau bis'), 200)
        self.assertEqual(self.kept('camille', self.space, 'seul.txt'), [7])   # le nouveau fichier n'hérite pas des versions de celui qui est en corbeille
        # Ailleurs : la corbeille d'un autre espace, à laquelle ce vidage ne touche pas.
        self.assertEqual(self.upload('camille', self.mine, 'perso.txt')[0], 200); self.throw('camille', self.mine, 'perso.txt')
        (self.common / 'commun.txt').write_text('commun'); self.throw('admin', 'fichiers', 'commun.txt')
        # Restes : un effacement interrompu, et un élément que plus aucune ligne ne désigne (base restaurée d'une sauvegarde).
        bin_dir = self.team_dir / '.nacre-trash'
        (bin_dir / (trash.GONE + 'a' * 32)).mkdir(); (bin_dir / (trash.GONE + 'a' * 32) / 'reste.bin').write_bytes(b'r' * 50)
        (bin_dir / ('b' * 32)).write_bytes(b'orphelin')
        for body in ({'area': self.space, 'confirm': True}, {'area': self.space, 'confirm': True, 'until': 'hier'}, {'area': self.space, 'confirm': True, 'until': True},
                     {'area': self.space, 'confirm': True, 'until': time.time() + 86400}, {'area': self.space, 'confirm': True, 'until': -1}):
            self.assertEqual(self.post('admin', '/api/trash/empty', body)[0], 400, body)   # jamais sans dire ce qui a été montré
        self.assertEqual(len(self.listed('admin')), 4)
        status, done = self.clear('admin', self.space)
        self.assertEqual((status, done['ok'], done['removed'], done['failed'], done['later']), (200, True, 3, 0, 0))
        # L'élément sans ligne est trop récent pour être un reste : une mise en corbeille pourrait être en cours. Il part au vidage suivant, passé une heure.
        self.assertEqual(os.listdir(bin_dir), ['b' * 32])
        with unittest.mock.patch.object(trash, 'ORPHAN', -1):
            self.assertEqual(self.clear('admin', self.space)[1]['removed'], 0)
        self.assertEqual(os.listdir(bin_dir), [])
        self.assertEqual(done['bytes'], 400 + 4 + 1 + 7 + 5 + 50)   # plan, note, dedans, fond, seul.txt et le reste ; ni les liens ni leurs cibles
        self.assertEqual(((outside / 'précieux.txt').read_text(), sorted(p.name for p in outside.iterdir())), ('ne pas toucher', ['précieux.txt']))
        self.assertEqual((self.kept('camille', self.space, 'seul.txt'), (self.team_dir / 'seul.txt').read_bytes(), (self.team_dir / 'gardé.txt').read_bytes()), ([7], b'nouveau bis', b'un'))
        self.assertEqual(self.blobs(self.team_dir), 1)
        self.assertEqual((sorted(self.listed('camille')), sorted(self.listed('admin'))), (['perso.txt'], ['commun.txt']))
        self.assertIn(('admin', 'Corbeille vidée', 'Chantier école : 3 éléments'), self.audit())
        # Un élément qui ne part pas est dit, et compté d'après ce qui reste réellement.
        self.assertEqual(self.upload('camille', self.space, 'coincé.txt')[0], 200); self.throw('camille', self.space, 'coincé.txt')
        with unittest.mock.patch.object(trash, 'wipe', side_effect=OSError(5, 'panne')):
            status, done = self.clear('admin', self.space)
        self.assertEqual((status, done['ok'], done['failed']), (200, False, 1))
        self.assertEqual(self.listed('admin').keys() & {'coincé.txt'}, set())   # plus restaurable : jamais un élément à demi effacé remis en place
        # Plus aucune ligne, mais l'espace reste proposé au vidage tant qu'il garde ce reste : « Réessayer » a un bouton.
        self.assertEqual([(a['count'], a['leftovers'], a['erase']) for a in self.get('admin', '/api/trash/overview')[1]['areas'] if a['id'] == self.space], [(0, 1, True)])
        self.assertEqual([a for a in self.get('camille', '/api/trash/overview')[1]['areas'] if a['id'] == self.space], [])
        self.assertEqual(self.clear('admin', self.space)[1]['failed'], 0)
        self.assertEqual(os.listdir(bin_dir), [])
        # Retirer un seul élément qui ne part pas : dit, inscrit au journal, et fini par le vidage suivant ou par le passage de garde.
        self.assertEqual(self.upload('camille', self.space, 'têtu.txt')[0], 200); self.throw('camille', self.space, 'têtu.txt')
        with unittest.mock.patch.object(trash, 'wipe', side_effect=OSError(5, 'panne')):
            status, done = self.post('admin', '/api/trash/delete', {'id': self.listed('admin')['têtu.txt']['id'], 'confirm': True})
        self.assertEqual((status, done['ok'], done['failed'], len(os.listdir(bin_dir))), (200, False, 1, 1))
        self.assertIn(('admin', 'Retiré pour de bon de la corbeille', 'Chantier école : têtu.txt (effacement à finir)'), self.audit())
        self.assertEqual(self.clear('admin', self.space)[1]['failed'], 0)
        self.assertEqual(os.listdir(bin_dir), [])
        # Ce qui est jeté après l'affichage n'a pas été montré à qui confirme : il reste en corbeille.
        self.assertEqual(self.upload('camille', self.space, 'montré.txt')[0], 200); self.throw('camille', self.space, 'montré.txt')
        shown = self.get('admin', '/api/trash/overview')[1]['at']
        time.sleep(.02)
        self.assertEqual(self.upload('camille', self.space, 'jeté depuis.txt')[0], 200); self.throw('camille', self.space, 'jeté depuis.txt')
        status, done = self.post('admin', '/api/trash/empty', {'area': self.space, 'confirm': True, 'until': shown})
        self.assertEqual((done['ok'], done['removed'], done['failed'], done['later'], sorted(self.listed('admin').keys() & {'montré.txt', 'jeté depuis.txt'})), (True, 1, 0, 1, ['jeté depuis.txt']))
        self.assertEqual(self.post('camille', '/api/restore', {'id': self.listed('camille')['jeté depuis.txt']['id']})[0], 200)
        self.throw('camille', self.space, 'jeté depuis.txt'); self.assertEqual(self.clear('admin', self.space)[1]['removed'], 1)
        # Vidé de ses fichiers et de sa corbeille, l'espace se supprime : versions sans fichier et reste d'envoi partent avec lui.
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 409)
        for name in ('seul.txt', 'gardé.txt'):
            self.throw('camille', self.space, name)
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 409)
        self.assertEqual(self.clear('admin', self.space)[1]['removed'], 2)
        (self.team_dir / '.nacre-upload-abc').write_bytes(b'moitie')
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 409)   # trop récent : c'est peut-être un envoi en cours
        (self.team_dir / '.nacre-upload-dossier').mkdir()
        with unittest.mock.patch.object(spaces, 'LEFTOVER', -1):
            self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 409)   # un dossier caché n'est jamais un reste d'envoi
            (self.team_dir / '.nacre-upload-dossier').rmdir()
            self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': self.space})[0], 200)
        self.assertFalse(self.team_dir.exists())

    def test_nothing_is_erased_on_its_own_until_an_administrator_sets_a_keeping_time(self):
        self.team()
        for name in ('vieux.txt', 'récent.txt', 'revenu.txt'):
            self.assertEqual(self.upload('camille', self.space, name)[0], 200); self.throw('camille', self.space, name)
        self.assertEqual(self.upload('camille', self.mine, 'perso.txt')[0], 200); self.throw('camille', self.mine, 'perso.txt')
        now = time.time()
        with app.database() as db:
            db.execute("UPDATE trash SET ts=? WHERE original IN ('vieux.txt','perso.txt','revenu.txt')", (now - 40 * 86400,))
        # Sans réglage : rien, quel que soit l'âge.
        self.assertEqual((trash.sweep(app, now), len(self.listed('camille'))), (0, 4))
        for body in ({'days': 12}, {'days': '30'}, {'days': True}, {'days': -1}, {}, {'days': 30}, {'days': 30, 'confirm': 'oui'}):
            self.assertEqual(self.post('admin', '/api/trash/retention', body)[0], 400, body)
        self.assertEqual(self.post('admin', '/api/trash/retention', {'days': 90, 'confirm': True})[0], 200)
        self.assertEqual((trash.sweep(app, now), self.get('admin', '/api/trash/overview')[1]['days']), (0, 90))
        self.assertEqual(self.post('admin', '/api/trash/retention', {'days': 30, 'confirm': True})[0], 200)
        # Restauré juste avant le passage : il n'est plus à retirer.
        self.assertEqual(self.post('camille', '/api/restore', {'id': self.listed('camille')['revenu.txt']['id']})[0], 200)
        self.assertEqual(trash.sweep(app, now), 2)   # dans tous les espaces, y compris personnels, au nom du système
        self.assertEqual((sorted(self.listed('camille')), os.listdir(self.mine_dir / '.nacre-trash'), len(os.listdir(self.team_dir / '.nacre-trash')), (self.team_dir / 'revenu.txt').exists()),
                         (['récent.txt'], [], 1, True))
        self.assertEqual(trash.sweep(app, now), 0)
        log = self.audit()
        self.assertIn(('admin', 'Garde de la corbeille', '30 jours'), log)
        self.assertIn((trash.ACTOR, 'Corbeille : éléments anciens retirés', '2 éléments de plus de 30 jours'), log)   # des nombres, aucun nom
        # Revenir à « jamais » ne demande pas de confirmation, et arrête tout.
        self.assertEqual(self.post('admin', '/api/trash/retention', {'days': 0})[0], 200)
        with app.database() as db:
            db.execute('UPDATE trash SET ts=?', (now - 400 * 86400,))
        self.assertEqual((trash.sweep(app, now), sorted(self.listed('camille'))), (0, ['récent.txt']))
        self.assertIn(('admin', 'Garde de la corbeille', 'jamais vidée seule'), self.audit())
        # Un espace devenu illisible n'arrête pas le passage des autres.
        self.assertEqual(self.post('admin', '/api/trash/retention', {'days': 7, 'confirm': True})[0], 200)
        self.assertEqual(self.upload('camille', self.mine, 'autre.txt')[0], 200); self.throw('camille', self.mine, 'autre.txt')
        with app.database() as db:
            db.execute('UPDATE trash SET ts=?', (now - 400 * 86400,))
            # « espace_000… » se classe avant tout espace réel : il est tenté le premier, et son échec n'arrête pas la suite.
            db.execute("INSERT INTO trash(id,original,ts,area) VALUES(?,?,?,?)", ('c' * 32, 'x.txt', now - 400 * 86400, 'espace_' + '0' * 12))
        self.assertEqual(trash.sweep(app, now), 2)
        # Une ligne qui ne désigne plus rien part sans être comptée ; un effacement resté en route est fini par le passage.
        self.assertEqual(self.upload('camille', self.mine, 'fantôme.txt')[0], 200); self.throw('camille', self.mine, 'fantôme.txt')
        bin_dir = self.mine_dir / '.nacre-trash'
        os.rename(bin_dir / self.listed('camille')['fantôme.txt']['id'], self.mine_dir / 'fantôme.txt')
        (bin_dir / (trash.GONE + 'd' * 32)).write_bytes(b'reste')
        with app.database() as db:
            db.execute('UPDATE trash SET ts=?', (now - 400 * 86400,))
        self.assertEqual((trash.sweep(app, now), os.listdir(bin_dir), (self.mine_dir / 'fantôme.txt').exists(), 'fantôme.txt' in self.listed('camille')), (0, [], True, False))
        # Le premier passage n'a jamais lieu pendant le démarrage : il est remis à plus tard, dans son propre fil, puis il se répète.
        with unittest.mock.patch.object(trash.threading, 'Timer') as timer:
            trash.watch(app)
            self.assertEqual((timer.call_args[0][0], timer.call_args[0][1], timer.return_value.daemon), (trash.FIRST, trash.passage, True))
            with unittest.mock.patch.object(trash, 'sweep', side_effect=RuntimeError('panne')) as swept:
                trash.passage(app)
            self.assertEqual((swept.call_count, timer.call_args[0][0]), (1, trash.WATCH))
        # Après une récupération de l'installation, la base peut dater : la durée de garde attend qu'on la redemande.
        with app.database() as db:
            trash.disable_after_recovery(db)
        self.assertEqual((self.get('admin', '/api/trash/overview')[1]['days'], trash.sweep(app, now)), (0, 0))

    def test_versions_follow_their_file_into_the_trash_and_only_its_own_leave_with_it(self):
        self.team()
        put = lambda name, content, path='': self.assertEqual(self.post('camille', f'/api/upload?area={self.space}&path={quote(path)}&name={quote(name)}&replace=1', raw=content)[0], 200)
        kept = lambda path: self.kept('camille', self.space, path)
        rows = lambda name: [row['id'] for row in self.get('admin', '/api/trash')[1] if row['original'] == name]   # du plus récent au plus ancien
        erase = lambda ident: self.assertEqual(self.post('admin', '/api/trash/delete', {'id': ident, 'confirm': True})[0], 200)
        # Jeté, un fichier emporte ses versions : celui qui prend son nom n'en hérite pas, et le vidage ne touche pas aux siennes.
        put('rapport.txt', b'un'); put('rapport.txt', b'deux!')
        self.assertEqual(kept('rapport.txt'), [2])
        self.throw('camille', self.space, 'rapport.txt')
        self.assertEqual(kept('rapport.txt'), [])
        put('rapport-v2.txt', b'v2 a'); put('rapport-v2.txt', b'v2 bbb')
        self.assertEqual(self.post('camille', '/api/rename', {'area': self.space, 'path': 'rapport-v2.txt', 'name': 'rapport.txt'})[0], 200)
        self.assertEqual((kept('rapport.txt'), self.blobs(self.team_dir)), ([4], 2))
        self.assertEqual(self.clear('admin', self.space)[1]['removed'], 1)
        self.assertEqual((kept('rapport.txt'), self.blobs(self.team_dir), (self.team_dir / 'rapport.txt').read_bytes()), ([4], 1, b'v2 bbb'))
        # Deux éléments du même nom en corbeille : restaurer l'un lui rend ses versions, retirer l'autre n'emporte que les siennes.
        self.throw('camille', self.space, 'rapport.txt')
        time.sleep(.02)
        put('rapport.txt', b'troisieme'); put('rapport.txt', b'troisieme bis')
        self.throw('camille', self.space, 'rapport.txt')
        newer, older = rows('rapport.txt')
        self.assertEqual(self.post('camille', '/api/restore', {'id': older})[0], 200)
        self.assertEqual(((self.team_dir / 'rapport.txt').read_bytes(), kept('rapport.txt'), self.blobs(self.team_dir)), (b'v2 bbb', [4], 2))
        erase(newer)
        self.assertEqual((kept('rapport.txt'), self.blobs(self.team_dir)), ([4], 1))
        # L'inverse : retirer le plus récent, puis restaurer le plus ancien, qui revient avec ses versions.
        self.throw('camille', self.space, 'rapport.txt')
        time.sleep(.02)
        put('rapport.txt', b'quatre'); put('rapport.txt', b'quatre bis')
        self.throw('camille', self.space, 'rapport.txt')
        newer, older = rows('rapport.txt')
        erase(newer)
        self.assertEqual(self.post('camille', '/api/restore', {'id': older})[0], 200)
        self.assertEqual((kept('rapport.txt'), self.blobs(self.team_dir)), ([4], 1))
        # Un fichier jeté, puis le dossier qui le contenait : retirer le dossier n'emporte pas les versions du fichier encore restaurable.
        self.assertEqual(self.post('camille', '/api/folder', {'area': self.space, 'name': 'Dossier', 'path': ''})[0], 200)
        put('a.txt', b'a un', 'Dossier'); put('a.txt', b'a deux!', 'Dossier'); put('b.txt', b'b', 'Dossier'); put('b.txt', b'b deux', 'Dossier')
        self.assertEqual((kept('Dossier/a.txt'), kept('Dossier/b.txt'), self.blobs(self.team_dir)), ([4], [1], 3))
        self.throw('camille', self.space, 'Dossier/a.txt'); self.throw('camille', self.space, 'Dossier')
        self.assertEqual((kept('Dossier/a.txt'), kept('Dossier/b.txt')), ([], []))
        erase(rows('Dossier')[0])
        self.assertEqual(self.blobs(self.team_dir), 2)   # celle de b.txt est partie avec le dossier ; celle de a.txt attend
        self.assertEqual(self.post('camille', '/api/folder', {'area': self.space, 'name': 'Dossier', 'path': ''})[0], 200)
        self.assertEqual(self.post('camille', '/api/restore', {'id': rows('Dossier/a.txt')[0]})[0], 200)
        self.assertEqual(((self.team_dir / 'Dossier/a.txt').read_bytes(), kept('Dossier/a.txt'), kept('rapport.txt')), (b'a deux!', [4], [4]))
        # Un dossier jeté puis restauré retrouve les versions de ce qu'il contient.
        self.throw('camille', self.space, 'Dossier')
        self.assertEqual(kept('Dossier/a.txt'), [])
        self.assertEqual(self.post('camille', '/api/restore', {'id': rows('Dossier')[0]})[0], 200)
        self.assertEqual(kept('Dossier/a.txt'), [4])
        # Une ligne dont l'élément est revenu à sa place sans elle (base reprise d'une copie) : elle part seule, rien d'autre n'est touché.
        self.throw('camille', self.space, 'Dossier/a.txt')
        ghost = rows('Dossier/a.txt')[0]
        os.rename(self.team_dir / '.nacre-trash' / ghost, self.team_dir / 'Dossier/a.txt')
        before = self.blobs(self.team_dir)
        status, done = self.post('admin', '/api/trash/delete', {'id': ghost, 'confirm': True})
        self.assertEqual((status, done['items'], (self.team_dir / 'Dossier/a.txt').read_bytes(), self.blobs(self.team_dir), rows('Dossier/a.txt')), (200, 0, b'a deux!', before, []))
        # Aucun chemin d'utilisateur n'atteint la clé réservée aux versions en corbeille.
        for path in ('.nacre-trash/' + ghost, '.nacre-trash'):
            self.assertIn(self.get('camille', f'/api/files/versions?area={self.space}&path={quote(path)}')[0], (400, 403, 404), path)


if __name__ == '__main__':
    unittest.main()
