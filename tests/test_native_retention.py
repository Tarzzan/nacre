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


    def test_deletion_starts_from_the_displayed_simulation_and_goes_through_the_service_plan(self):
        self.native(deletion=True)
        sent, answer = [], {'ok': True, 'deleted': [], 'uncertain': [], 'kept': [], 'reason': ''}

        def fake(method, actor, body=None):
            sent.append((method, actor, body))
            if method == 'prepare':
                if body['points'] == ['refus']:
                    raise server.Problem('Une restauration est en cours ou à vérifier sur ce volume : aucun point ne peut être supprimé.')
                return {'id': 'c' * 32, 'expires': 1, 'action': 'delete', 'volume': body['volume'], 'confirmation': f'SUPPRIMER {len(body["points"])} POINTS DE documents',
                        'points': [{'id': identifier, 'created': 5} for identifier in body['points']], 'effect': 'Supprimer.', 'notes': ['Note.']}
            if method == 'commit':
                return answer
            return self.state
        server.native_storage.side_effect = fake
        rule = {'volume': 'documents', 'keep_last': 2, 'manual': True, 'calendar': {'daily': 0, 'weekly': 0, 'monthly': 0, 'timezone': 'UTC'}}
        ids = [f'{index:032x}' for index in (1, 2, 3, 4)]
        with server.database() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('native-scheduled:documents',?)", (json.dumps([ids[0], ids[1], f'{6:032x}']),))
        status, preview = self.post('/api/storage/native-retention-preview', rule)
        self.assertEqual((status, preview['deletion'], [item['id'] for item in preview['remove']]), (200, True, ids))
        self.assertEqual(json.loads(self.call('GET', '/api/storage/native-retention')[2])['deletion'], True)
        # La liste affichée doit être celle que la console recalcule : sinon rien n'est demandé au service.
        for expected in (None, [], ids[:3], list(reversed(ids)), ids + ['f' * 32]):
            status, value = self.post('/api/storage/native-prune-prepare', {**rule, 'expected': expected})
            self.assertEqual((status, 'Simuler de nouveau' in value['error']), (409, True), expected)
        self.assertEqual([method for method, _, _ in sent if method != 'status'], [])
        status, plan = self.post('/api/storage/native-prune-prepare', {**rule, 'expected': ids})
        self.assertEqual((status, plan['id'], plan['confirmation'], plan['name'], plan['remaining']), (200, 'c' * 32, 'SUPPRIMER 4 POINTS DE documents', 'Documents', 0))
        self.assertEqual([(item['id'], item['manual']) for item in plan['points']], [(ids[0], False), (ids[1], False), (ids[2], True), (ids[3], True)])
        self.assertEqual(sent[-1], ('prepare', 'admin', {'action': 'delete', 'volume': 'documents', 'points': ids}))
        # Validation : phrase transmise telle quelle, bilan rendu, journal tenu, note des points programmés nettoyée.
        for bad in ({}, {'plan': 'c' * 32}, {'plan': 'x', 'confirmation': 'SUPPRIMER 4 POINTS DE documents'}, {'plan': 'c' * 32, 'confirmation': 'CAPTURER documents'}):
            self.assertEqual(self.post('/api/storage/native-prune', {'volume': 'documents', **bad})[0], 400, bad)
        self.assertEqual(self.post('/api/storage/native-prune', {'volume': 'inconnu', 'plan': 'c' * 32, 'confirmation': 'SUPPRIMER 4 POINTS DE documents'})[0], 404)
        self.assertNotIn('commit', [method for method, _, _ in sent])
        answer.update(deleted=ids[:1], kept=ids[2:], uncertain=ids[1:2], ok=False, reason='La suppression d’un point n’est pas confirmée : vérifier le stockage.')
        status, value = self.post('/api/storage/native-prune', {'volume': 'documents', 'plan': 'c' * 32, 'confirmation': 'SUPPRIMER 4 POINTS DE documents'})
        self.assertEqual((status, value['ok'], value['deleted'], value['uncertain'], value['kept'], value['name']), (200, False, ids[:1], ids[1:2], ids[2:], 'Documents'))
        self.assertEqual(sent[-1], ('commit', 'admin', {'plan': 'c' * 32, 'confirmation': 'SUPPRIMER 4 POINTS DE documents'}))
        answer.update(deleted=ids[1:], kept=[], uncertain=[], ok=True, reason='')
        self.assertEqual(self.post('/api/storage/native-prune', {'volume': 'documents', 'plan': 'c' * 32, 'confirmation': 'SUPPRIMER 4 POINTS DE documents'})[1]['ok'], True)
        with server.database() as db:
            journal = [tuple(row) for row in db.execute("SELECT action,detail FROM audit WHERE action LIKE '%oints natifs%' ORDER BY rowid")]
            marks = json.loads(db.execute("SELECT value FROM settings WHERE key='native-scheduled:documents'").fetchone()['value'])
        self.assertEqual(journal, [('Suppression de points natifs interrompue', 'documents : 1 supprimé, 1 à vérifier, 2 non touchés ; La suppression d’un point n’est pas confirmée : vérifier le stockage.'),
                                   ('Points natifs supprimés', 'documents : 3 supprimés')])
        self.assertEqual(marks, [f'{6:032x}'])
        # Plus de cinquante points sortants : les cinquante plus anciens, le reste annoncé.
        self.state['points'] = [point(100 + index, stamp(1) + index) for index in range(60)]
        many = [f'{100 + index:032x}' for index in range(58)]
        status, plan = self.post('/api/storage/native-prune-prepare', {**rule, 'expected': many})
        self.assertEqual((status, len(plan['points']), plan['remaining'], sent[-1][2]['points']), (200, 50, 8, many[:50]))
        # Refus du service rendu tel quel ; rien à supprimer ; suppression non accordée ; action générique fermée ; comptes non administrateurs.
        self.state['points'] = [point(1, stamp(1)), point(2, stamp(2)), point(3, stamp(3))]
        with patch.object(server, 'native_storage', side_effect=lambda method, actor, body=None: fake(method, actor, {**body, 'points': ['refus']} if method == 'prepare' else body)):
            status, value = self.post('/api/storage/native-prune-prepare', {**rule, 'expected': ids[:1]})
        self.assertEqual((status, 'restauration' in value['error']), (400, True))
        self.assertEqual(self.post('/api/storage/native-prune-prepare', {**rule, 'keep_last': 5, 'expected': []})[0], 400)
        self.state['deletion'] = False
        self.assertEqual(self.post('/api/storage/native-prune-prepare', {**rule, 'expected': ids[:1]})[0], 409)
        before = len(sent)
        status, value = self.post('/api/storage/native-prepare', {'action': 'delete', 'volume': 'documents', 'points': ids[:1]})
        self.assertEqual((status, 'simulation' in value['error'], len(sent)), (400, True, before))
        token, csrf = self.reader()
        for path in ('/api/storage/native-prune-prepare', '/api/storage/native-prune'):
            self.assertEqual(self.call('POST', path, {**rule, 'expected': ids[:1]}, token=token, csrf=csrf)[0], 403)


if __name__ == '__main__':
    unittest.main()
