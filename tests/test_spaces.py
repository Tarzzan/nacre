"""Personnes, groupes et espaces : droits appliqués à toutes les routes de fichiers. Vrai serveur, dossier temporaire."""
import json
import re
import unittest
from pathlib import Path
from urllib.parse import quote

import test_components_cameras as base
import spaces

app = base.server


class SpaceTests(unittest.TestCase):
    setUp = base.ComponentsCameraTests.setUp
    tearDown = base.ComponentsCameraTests.tearDown
    request = base.ComponentsCameraTests.request

    def people(self, **roles):
        self.sessions = {'admin': (self.token, self.csrf)}
        with app.database() as db:
            for name, role in roles.items():
                db.execute('INSERT INTO users(name,salt,hash,role) VALUES(?,?,?,?)', (name, '00', 'unused', role))
        for name in roles:
            self.sessions[name] = app.make_session(name)

    def get(self, who, path):
        status, data = self.request('GET', path, token=self.sessions[who][0])
        try:
            return status, json.loads(data)
        except (ValueError, TypeError):
            return status, data

    def post(self, who, path, body=None, raw=None):
        token, csrf = self.sessions[who]
        status, data = self.request('POST', path, body, token, csrf, raw=raw)
        return status, json.loads(data)

    def home(self, who):
        return next(a['id'] for a in self.get(who, '/api/areas')[1] if a['kind'] == 'personal')

    def upload(self, who, area, name, content=b'contenu', path=''):
        return self.post(who, f'/api/upload?area={area}&path={quote(path)}&name={quote(name)}', raw=content)

    def names(self, who, area, path=''):
        status, data = self.get(who, f'/api/files?area={area}&path={quote(path)}')
        return status, [item['name'] for item in data['items']] if status == 200 else data

    def audit(self):
        with app.database() as db:
            return [tuple(r) for r in db.execute('SELECT username,action,detail FROM audit ORDER BY id')]

    def test_member_owns_a_personal_space_closed_to_everyone_else(self):
        self.people(camille='member', bruno='member')
        status, areas = self.get('camille', '/api/areas')
        self.assertEqual(status, 200)
        self.assertEqual([(a['name'], a['kind'], a['writable']) for a in areas], [('Mon espace', 'personal', True), ('Fichiers partagés', 'local', False)])
        mine = areas[0]['id']
        self.assertRegex(mine, r'^espace_[a-f0-9]{12}$')
        # Le même espace à chaque ouverture, jamais un second.
        self.assertEqual(self.home('camille'), mine)
        self.assertEqual(self.post('camille', '/api/folder', {'area': mine, 'name': 'Impots-secrets'})[0], 200)
        self.assertEqual(self.upload('camille', mine, 'bulletin-secret.pdf', path='Impots-secrets')[0], 200)
        self.assertEqual(self.names('camille', mine, 'Impots-secrets'), (200, ['bulletin-secret.pdf']))
        self.assertEqual(self.request('GET', f'/api/download?area={mine}&path=Impots-secrets/bulletin-secret.pdf', token=self.sessions['camille'][0]), (200, b'contenu'))
        self.assertTrue((Path(app.ROOT) / 'data/espaces' / mine[7:] / 'Impots-secrets/bulletin-secret.pdf').is_file())
        # Ni un autre membre ni un administrateur ne l'ouvrent, par aucune route de fichiers.
        for who in ('bruno', 'admin'):
            for path in (f'/api/files?area={mine}', f'/api/download?area={mine}&path=Impots-secrets/bulletin-secret.pdf', f'/api/archive?area={mine}&name=Impots-secrets',
                         f'/api/files/search?q=bulletin&area={mine}', f'/api/files/usage?area={mine}'):
                self.assertEqual(self.get(who, path)[0], 403, (who, path))
            self.assertEqual(self.post(who, '/api/folder', {'area': mine, 'name': 'intrus'})[0], 403)
            self.assertEqual(self.upload(who, mine, 'intrus.txt')[0], 403)
            self.assertEqual(self.post(who, '/api/trash', {'area': mine, 'path': 'Impots-secrets'})[0], 403)
            self.assertNotIn(mine, [a['id'] for a in self.get(who, '/api/areas')[1]])
        # Ses fichiers n'apparaissent pas dans une recherche partout faite par un autre.
        self.assertEqual(self.get('admin', '/api/files/search?q=bulletin')[1]['items'], [])
        self.assertEqual(len(self.get('camille', '/api/files/search?q=bulletin')[1]['items']), 1)
        # Le journal commun ne livre aucun nom de son espace personnel.
        lines = [line for line in self.audit() if line[0] == 'camille']
        self.assertEqual([line[1:] for line in lines], [('Dossier créé', 'espace personnel'), ('Fichier déposé', 'espace personnel')])
        self.assertNotIn('secret', json.dumps(self.audit()))
        # L'espace commun reste en lecture pour un membre ; le reste du NAS lui est fermé.
        self.assertEqual(self.post('camille', '/api/folder', {'area': 'fichiers', 'name': 'x'})[0], 403)
        for area in ('video', 'sauvegardes', 'restaurations', 'native_abc', 'espace_000000000000', '../x'):
            self.assertIn(self.get('camille', f'/api/files?area={area}')[0], (400, 403), area)

    def test_member_reaches_only_file_and_account_routes(self):
        self.people(camille='member')
        source = (Path(app.__file__).parent / 'server.py').read_text()
        routes = sorted(set(re.findall(r"'(/api/[a-z0-9/_-]+)'", source)) - {'/api/login', '/api/update-health', '/api/public/'})
        self.assertGreater(len(routes), 80)
        for route in routes:
            if route not in spaces.MEMBER_READS:
                self.assertEqual(self.get('camille', route)[0], 403, route)
            if route not in spaces.MEMBER_WRITES:
                self.assertEqual(self.post('camille', route, {})[0], 403, route)
        for path in ('/api/cameras', '/api/camera/kept?camera=atelier', '/api/camera/snapshot?camera=atelier'):
            self.assertEqual(self.get('camille', path)[0], 403, path)
        status, data = self.get('camille', '/api/overview')
        self.assertEqual((status, data['events'], data['services'], data['camera']), (200, [], [], {}))
        self.assertEqual(self.get('camille', '/api/me')[1]['camera'], False)
        self.assertEqual(self.get('camille', '/api/account')[1], {'name': 'camille', 'role': 'member'})
        # La surveillance s'ouvre personne par personne, en lecture.
        self.assertEqual(self.post('admin', '/api/spaces/person', {'name': 'camille', 'camera': True})[0], 200)
        self.assertEqual(self.get('camille', '/api/cameras')[0], 200)
        self.assertEqual(self.get('camille', '/api/me')[1]['camera'], True)
        self.assertEqual(self.post('camille', '/api/camera/keep', {'camera': 'atelier', 'start': 1, 'end': 2})[0], 403)
        self.assertEqual(self.post('admin', '/api/spaces/person', {'name': 'camille', 'camera': 'oui'})[0], 400)
        self.assertEqual(self.post('admin', '/api/spaces/person', {'name': 'absente', 'camera': True})[0], 404)

    def test_team_space_follows_people_and_groups(self):
        self.people(camille='member', bruno='member', dora='member', lecteur='viewer')
        status, group = self.post('admin', '/api/spaces/group', {'name': '  Comptabilité ', 'members': ['camille']})
        self.assertEqual(status, 200)
        status, made = self.post('admin', '/api/spaces/space', {'name': 'Comptabilité', 'members': {'bruno': 'read', 'lecteur': 'write'}, 'groups': {group['id']: 'write'}})
        self.assertEqual(status, 200)
        team = made['id']
        self.assertEqual(self.upload('camille', team, 'bilan.xlsx')[0], 200)
        self.assertEqual(self.names('bruno', team), (200, ['bilan.xlsx']))
        self.assertEqual(self.upload('bruno', team, 'essai.txt')[0], 403)
        self.assertEqual(self.names('dora', team)[0], 403)
        self.assertEqual(self.names('admin', team), (200, ['bilan.xlsx']))
        # Un compte en lecture seule reste en lecture, quel que soit le niveau qu'on lui prête.
        self.assertEqual(self.names('lecteur', team), (200, ['bilan.xlsx']))
        self.assertEqual([a['writable'] for a in self.get('lecteur', '/api/areas')[1] if a['id'] == team], [False])
        listed = lambda who: [(a['name'], a['writable']) for a in self.get(who, '/api/areas')[1] if a['kind'] == 'team']
        self.assertEqual((listed('camille'), listed('bruno'), listed('dora')), ([('Comptabilité', True)], [('Comptabilité', False)], []))
        self.assertEqual(self.audit()[-1], ('camille', 'Fichier déposé', 'Comptabilité : /bilan.xlsx'))
        # Corbeille : visible de ceux qui écrivent dans l'espace, pas des autres.
        self.assertEqual(self.post('camille', '/api/trash', {'area': team, 'path': 'bilan.xlsx'})[0], 200)
        seen = lambda who: [r['original'] for r in self.get(who, '/api/trash')[1]]
        self.assertEqual((seen('camille'), seen('admin'), seen('bruno'), seen('dora'), seen('lecteur')), (['bilan.xlsx'], ['bilan.xlsx'], [], [], []))
        # Un espace qui contient encore quelque chose, corbeille comprise, ne se supprime pas.
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': team})[0], 409)
        identifier = self.get('camille', '/api/trash')[1][0]['id']
        self.assertEqual(self.post('bruno', '/api/restore', {'id': identifier})[0], 403)
        self.assertEqual(self.post('camille', '/api/restore', {'id': identifier})[0], 200)
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': team})[0], 409)
        # Sortie du groupe : l'accès tombe aussitôt.
        self.assertEqual(self.post('admin', '/api/spaces/group', {'id': group['id'], 'name': 'Comptabilité', 'members': ['dora']})[0], 200)
        self.assertEqual(self.names('camille', team)[0], 403)
        self.assertEqual(self.upload('dora', team, 'note.txt')[0], 200)
        # Suppression du groupe : il disparaît aussi des accès de l'espace.
        self.assertEqual(self.post('admin', '/api/spaces/group-delete', {'id': group['id']})[0], 200)
        self.assertEqual(self.names('dora', team)[0], 403)
        view = self.get('admin', '/api/spaces')[1]
        self.assertEqual((view['groups'], view['spaces'][0]['groups'], view['spaces'][0]['members']), ([], {}, {'bruno': 'read', 'lecteur': 'write'}))
        # Refus : doublon, inconnus, niveaux, noms.
        self.assertEqual(self.post('admin', '/api/spaces/space', {'name': 'comptabilité'})[0], 409)
        for body in ({'name': ''}, {'name': 'x' * 61}, {'name': 'A', 'members': {'absent': 'read'}}, {'name': 'A', 'members': {'bruno': 'manage'}},
                     {'name': 'A', 'groups': {'0' * 12: 'read'}}, {'name': 'A', 'members': []}, {'name': 7}):
            self.assertEqual(self.post('admin', '/api/spaces/space', body)[0], 400, body)
        self.assertEqual(self.post('admin', '/api/spaces/space', {'id': 'espace_' + '0' * 12, 'name': 'A'})[0], 404)
        self.assertEqual(self.post('admin', '/api/spaces/group', {'name': 'G', 'members': ['absent']})[0], 400)
        self.assertEqual(self.post('admin', '/api/spaces/inconnu', {})[0], 404)
        # Vidé, l'espace se supprime, et son dossier avec lui.
        for name in ('bilan.xlsx', 'note.txt'):
            (Path(app.ROOT) / 'data/espaces' / team[7:] / name).unlink()
        self.assertEqual(self.post('admin', '/api/spaces/space-delete', {'id': team})[0], 200)
        self.assertFalse((Path(app.ROOT) / 'data/espaces' / team[7:]).exists())
        self.assertEqual(self.names('bruno', team)[0], 403)

    def test_common_space_is_read_only_for_members_until_opened(self):
        self.people(camille='member', bruno='member')
        self.assertEqual(self.names('camille', 'fichiers')[0], 200)
        self.assertEqual(self.post('camille', '/api/folder', {'area': 'fichiers', 'name': 'Projets'})[0], 403)
        group = self.post('admin', '/api/spaces/group', {'name': 'Rédaction', 'members': ['camille']})[1]['id']
        self.assertEqual(self.post('admin', '/api/spaces/common', {'everyone': 'read', 'groups': {group: 'write'}})[0], 200)
        self.assertEqual(self.post('camille', '/api/folder', {'area': 'fichiers', 'name': 'Projets'})[0], 200)
        self.assertEqual(self.post('bruno', '/api/folder', {'area': 'fichiers', 'name': 'Autre'})[0], 403)
        self.assertEqual(self.post('admin', '/api/spaces/common', {'everyone': None, 'members': {'bruno': 'read'}})[0], 200)
        self.assertEqual(self.names('camille', 'fichiers')[0], 403)
        self.assertEqual(self.names('bruno', 'fichiers'), (200, ['Projets']))
        self.assertNotIn('fichiers', [a['id'] for a in self.get('camille', '/api/areas')[1]])
        self.assertEqual(self.post('admin', '/api/spaces/common', {'everyone': 'manage'})[0], 400)
        self.assertEqual(self.get('admin', '/api/spaces')[1]['common'], {'everyone': None, 'members': {'bruno': 'read'}, 'groups': {}})

    def test_personal_space_is_taken_over_only_after_the_account_is_disabled(self):
        self.people(camille='member')
        mine = self.home('camille')
        self.assertEqual(self.upload('camille', mine, 'contrat.pdf')[0], 200)
        self.assertEqual(self.get('admin', '/api/spaces')[1]['orphans'], [])
        self.assertEqual(self.post('admin', '/api/spaces/adopt', {'name': 'camille'})[0], 409)
        self.assertEqual(self.post('admin', '/api/user/update', {'name': 'camille', 'role': 'member', 'active': False})[0], 200)
        self.assertEqual(self.get('admin', '/api/spaces')[1]['orphans'], ['camille'])
        self.assertEqual(self.names('admin', mine)[0], 403)
        status, taken = self.post('admin', '/api/spaces/adopt', {'name': 'camille'})
        self.assertEqual((status, taken['id']), (200, mine))
        self.assertEqual(self.names('admin', mine), (200, ['contrat.pdf']))
        view = self.get('admin', '/api/spaces')[1]
        self.assertEqual([(s['name'], s['former']) for s in view['spaces']], [('Espace de camille', 'camille')])
        self.assertEqual(self.audit()[-1], ('admin', 'Espace personnel repris', 'camille → Espace de camille'))
        self.assertEqual(self.post('admin', '/api/spaces/adopt', {'name': 'camille'})[0], 404)
        self.assertEqual(self.post('admin', '/api/spaces/adopt', {'name': 'absente'})[0], 404)

    def test_reader_keeps_its_view_and_everyone_changes_their_own_password(self):
        self.people(lecteur='viewer', camille='member')
        self.assertEqual([(a['id'], a['writable']) for a in self.get('lecteur', '/api/areas')[1]], [('fichiers', False), ('video', False), ('sauvegardes', False)])
        self.assertEqual(self.get('lecteur', '/api/events')[0], 200)
        with app.database() as db:
            self.assertEqual(spaces.every(db, 'space:'), [])
            salt = '11' * 16
            db.execute('UPDATE users SET salt=?,hash=? WHERE name=?', (salt, app.password_hash('ancien-mot-de-passe', salt), 'camille'))
        other = app.make_session('camille')
        self.assertEqual(self.post('camille', '/api/account/password', {'current': 'faux', 'password': 'nouveau-mot-de-passe'})[0], 403)
        self.assertEqual(self.post('camille', '/api/account/password', {'current': 'ancien-mot-de-passe', 'password': 'court'})[0], 400)
        self.assertEqual(self.post('camille', '/api/account/password', {'current': 'ancien-mot-de-passe', 'password': 'nouveau-mot-de-passe'})[0], 200)
        self.assertEqual(self.request('GET', '/api/me', token=other[0])[0], 401)
        self.assertEqual(self.get('camille', '/api/me')[0], 200)
        self.assertEqual(self.request('POST', '/api/login', {'username': 'camille', 'password': 'nouveau-mot-de-passe'})[0], 200)
        self.assertEqual(self.post('lecteur', '/api/account/password', {'current': 'x', 'password': 'nouveau-mot-de-passe'})[0], 403)
        # Un rôle inconnu n'est pas créé, et « membre » l'est.
        self.assertEqual(self.post('admin', '/api/user', {'name': 'dora', 'password': 'mot-de-passe-long', 'role': 'member'})[0], 200)
        self.assertEqual(self.post('admin', '/api/user', {'name': 'eric', 'password': 'mot-de-passe-long', 'role': 'root'})[0], 400)

    def test_background_work_is_not_bound_by_a_session(self):
        self.people(camille='member')
        mine = self.home('camille')
        self.assertIsNone(app.actor())
        with app.folder(mine, write=True):
            pass
        self.assertEqual([a['id'] for a in app.file_areas(False)], ['fichiers', 'video', 'sauvegardes'])


if __name__ == '__main__':
    unittest.main()
