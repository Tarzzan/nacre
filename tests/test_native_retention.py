"""Conservation des points natifs : règle par volume et simulation en lecture seule, face à un service natif simulé."""
import json
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import test_file_manager as manager

server = manager.server


def stamp(day, hour=12):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc).timestamp()


def point(index, created, status='ready', volume='documents'):
    return {'id': f'{index:032x}', 'volume': volume, 'family': 'btrfs', 'created': created, 'actor': 'admin', 'status': status, 'detail': ''}


class NativeRetentionTests(unittest.TestCase):
    setUp = manager.FileManagerTests.setUp
    tearDown = manager.FileManagerTests.tearDown
    call = manager.FileManagerTests.call
    reader = manager.FileManagerTests.reader

    def native(self, **changes):
        self.calls = []
        self.state = {'connected': True, 'volumes': [{'id': 'documents', 'name': 'Documents', 'family': 'btrfs', 'ready': True}, {'id': 'photos', 'name': 'Photos', 'family': 'zfs', 'ready': True}],
                      'points': [point(1, stamp(1)), point(2, stamp(2)), point(3, stamp(3)), point(4, stamp(3, 18)), point(5, stamp(9)), point(6, stamp(10)),
                                 point(7, stamp(5), 'uncertain'), point(8, stamp(6), 'creating'), point(9, stamp(7), 'invalid'), point(10, time.time() + 86400), point(11, stamp(4), volume='photos'),
                                 {'id': 'étranger', 'volume': 'documents', 'created': stamp(8), 'status': 'ready'}],
                      'actions': [], 'jobs': [], **changes}

        def fake(method, actor, body=None):
            self.calls.append(method)
            return self.state
        patcher = patch.object(server, 'native_storage', side_effect=fake)
        patcher.start(); self.addCleanup(patcher.stop)

    def post(self, path, body, token=None):
        status, _, data = self.call('POST', path, body, token=token)
        return status, json.loads(data)

    def test_simulation_says_exactly_which_points_a_rule_keeps_removes_and_protects(self):
        self.native()
        body = {'volume': 'documents', 'keep_last': 2, 'manual': True, 'calendar': {'daily': 4, 'weekly': 0, 'monthly': 0, 'timezone': 'UTC'}}
        status, value = self.post('/api/storage/native-retention-preview', body)
        self.assertEqual(status, 200, value)
        short = lambda points: [int(p['id'], 16) for p in points]
        # Deux derniers points, puis le dernier point de chacun des quatre derniers jours avec capture ; le reste sortirait, du plus ancien au plus récent.
        self.assertEqual((short(value['keep']), short(value['remove'])), ([6, 5, 4, 2], [1, 3]))
        self.assertEqual(value['keep'][0]['reasons'], ['Derniers points', 'Jour · 2026-11-10']); self.assertEqual(value['keep'][2]['reasons'], ['Jour · 2026-11-03'])
        # Protégés : états non sûrs et date future, jamais proposés ; un point d'un autre volume ou mal nommé n'apparaît pas.
        self.assertEqual({int(p['id'], 16): p['reason'].split('.')[0] for p in value['protected']},
                         {7: 'État à vérifier sur le stockage', 8: 'Création en cours', 9: 'Point absent, modifié ou saturé', 10: 'Date de création absente ou dans le futur'})
        self.assertNotIn('étranger', json.dumps(value)); self.assertNotIn(f'{11:032x}', json.dumps(value))
        self.assertEqual((value['volume'], value['name'], value['deletion'], value['busy'], value['rule']['keep_last']), ('documents', 'Documents', False, False, 2))
        # Rien n'est demandé au service natif en dehors de son état, rien n'est enregistré.
        self.assertEqual(set(self.calls), {'status'})
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'native-%'").fetchone()[0], 0)
        # Par défaut la règle ne porte que sur les captures programmées : une capture manuelle est protégée.
        status, value = self.post('/api/storage/native-retention-preview', {'volume': 'documents', 'keep_last': 1})
        self.assertEqual((value['keep'], value['remove'], len(value['protected'])), ([], [], 10))
        self.assertIn('Capture manuelle', value['protected'][1]['reason']); self.assertTrue(all(p['manual'] for p in value['protected']))
        # Les points créés par la programmation sont soumis à la règle, les manuels restent à part.
        with server.database() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('native-scheduled:documents',?)", (json.dumps([f'{i:032x}' for i in (1, 2, 3, 7)]),))
        status, value = self.post('/api/storage/native-retention-preview', {'volume': 'documents', 'keep_last': 1})
        self.assertEqual((short(value['keep']), short(value['remove']), [p['manual'] for p in value['keep']]), ([3], [1, 2], [False]))
        self.assertEqual(next(p for p in value['protected'] if int(p['id'], 16) == 7)['manual'], False)
        # Une restauration en cours ou incertaine sur le volume protège tous ses points ; ailleurs, elle ne change rien.
        self.state['actions'] = [{'action': 'clone', 'volume': 'documents', 'status': 'running'}]
        status, value = self.post('/api/storage/native-retention-preview', body)
        self.assertEqual((value['keep'], value['remove'], value['busy'], len(value['protected'])), ([], [], True, 10))
        self.assertIn('restauration est en cours', next(p for p in value['protected'] if int(p['id'], 16) == 1)['reason'])
        self.state['actions'] = [{'action': 'clone', 'volume': 'photos', 'status': 'uncertain'}, {'action': 'clone', 'volume': 'documents', 'status': 'done'}, {'action': 'snapshot', 'volume': 'documents', 'status': 'running'}]
        self.assertEqual(short(self.post('/api/storage/native-retention-preview', body)[1]['remove']), [1, 3])

    def test_rule_is_saved_per_volume_validated_and_reserved_to_administrators(self):
        self.native()
        status, _, data = self.call('GET', '/api/storage/native-retention'); value = json.loads(data)
        self.assertEqual((status, value['connected'], value['deletion'], [p['volume'] for p in value['policies']], [p['saved'] for p in value['policies']]), (200, True, False, ['documents', 'photos'], [False, False]))
        self.assertEqual((value['policies'][0]['keep_last'], value['policies'][0]['manual'], value['policies'][0]['calendar']['daily']), (7, False, 0))
        status, value = self.post('/api/storage/native-retention', {'volume': 'photos', 'keep_last': 12, 'manual': True, 'calendar': {'daily': 7, 'weekly': 4, 'monthly': 6, 'timezone': 'America/Cayenne'}})
        self.assertEqual((status, value['saved'], value['keep_last'], value['calendar']), (200, True, 12, {'daily': 7, 'weekly': 4, 'monthly': 6, 'timezone': 'America/Cayenne'}))
        saved = json.loads(self.call('GET', '/api/storage/native-retention')[2])['policies']
        self.assertEqual([(p['volume'], p['saved'], p['keep_last'], p['manual']) for p in saved], [('documents', False, 7, False), ('photos', True, 12, True)])
        with server.database() as db:
            self.assertIn('photos : 12 derniers points, 7 jours, 4 semaines, 6 mois ; captures manuelles comprises ; aucune suppression', db.execute('SELECT detail FROM audit ORDER BY rowid DESC LIMIT 1').fetchone()[0])
        self.assertEqual(set(self.calls), {'status'})
        # Une règle enregistrée devenue illisible ne casse pas la liste : la règle par défaut est proposée.
        with server.database() as db:
            db.execute("UPDATE settings SET value=? WHERE key='native-retention:photos'", ('{"keep_last":0}',))
        self.assertEqual([(p['saved'], p['keep_last']) for p in json.loads(self.call('GET', '/api/storage/native-retention')[2])['policies']], [(False, 7), (False, 7)])
        for body, expected in (({'volume': 'ailleurs', 'keep_last': 3}, 404), ({'volume': '../x', 'keep_last': 3}, 404), ({'keep_last': 3}, 404), ({'volume': 'documents', 'keep_last': 0}, 400),
                               ({'volume': 'documents', 'keep_last': 1001}, 400), ({'volume': 'documents', 'keep_last': '3'}, 400), ({'volume': 'documents', 'keep_last': True}, 400),
                               ({'volume': 'documents', 'manual': 'oui'}, 400), ({'volume': 'documents', 'calendar': {'daily': -1}}, 400), ({'volume': 'documents', 'calendar': {'timezone': 'Mars/Olympus'}}, 400),
                               ({'volume': 'documents', 'calendar': {'yearly': 1}}, 400), ({'volume': 'documents', 'calendar': []}, 400)):
            for path in ('/api/storage/native-retention', '/api/storage/native-retention-preview'):
                self.assertEqual(self.post(path, body)[0], expected, (path, body))
        token, _ = self.reader()
        self.assertEqual(self.call('GET', '/api/storage/native-retention', token=token)[0], 403)
        self.assertEqual(self.call('POST', '/api/storage/native-retention-preview', {'volume': 'documents'}, csrf=False)[0], 403)
        # Sans service natif : la liste est vide et le dit, règle et simulation sont refusées.
        self.state = {'connected': False, 'volumes': [], 'points': [], 'actions': [], 'jobs': []}
        value = json.loads(self.call('GET', '/api/storage/native-retention')[2])
        self.assertEqual((value['connected'], value['policies']), (False, []))
        self.assertEqual((self.post('/api/storage/native-retention', {'volume': 'documents'})[0], self.post('/api/storage/native-retention-preview', {'volume': 'documents'})[0]), (503, 503))


if __name__ == '__main__':
    unittest.main()
