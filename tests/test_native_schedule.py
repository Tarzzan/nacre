"""Programmation des captures natives : réglage, occurrences, plafond, refus et alerte, face à un service natif simulé."""
import json
import time
import unittest
from unittest.mock import patch

import test_file_manager as manager

server = manager.server


class NativeScheduleTests(unittest.TestCase):
    setUp = manager.FileManagerTests.setUp
    tearDown = manager.FileManagerTests.tearDown
    call = manager.FileManagerTests.call
    reader = manager.FileManagerTests.reader

    def native(self):
        self.calls, self.refuse, self.plans = [], {}, {}
        self.state = {'connected': True, 'volumes': [{'id': 'documents', 'name': 'Documents', 'family': 'btrfs', 'ready': True}, {'id': 'photos', 'name': 'Photos', 'family': 'lvm', 'ready': True}],
                      'points': [], 'actions': [], 'jobs': []}

        def fake(method, actor, body=None):
            self.calls.append((method, actor, dict(body or {})))
            if method == 'status':
                return self.state
            if method in self.refuse:
                raise server.Problem(self.refuse[method])
            if method == 'prepare':
                identifier = f'{len(self.plans) + 1:032x}'
                self.plans[identifier] = body['volume']
                return {'id': identifier, 'action': 'snapshot', 'volume': body['volume'], 'confirmation': 'CAPTURER ' + body['volume']}
            if method == 'commit':
                target = self.plans[body['plan']]
                if body['confirmation'] != 'CAPTURER ' + target:
                    raise server.Problem('Recopier exactement la confirmation du plan.')
                self.state['points'].append({'id': body['plan'], 'volume': target, 'created': time.time(), 'actor': actor, 'status': 'ready'})
                return {'ok': True, 'object': 'nacre_' + body['plan']}
            raise server.Problem('Méthode non autorisée.')
        patcher = patch.object(server, 'native_storage', side_effect=fake)
        patcher.start(); self.addCleanup(patcher.stop)

    def post(self, body, token=None):
        status, _, data = self.call('POST', '/api/storage/native-schedule', body, token=token)
        return status, json.loads(data)

    def listed(self):
        return {item['volume']: item for item in json.loads(self.call('GET', '/api/storage/native-schedule')[2])['schedules']}

    def run_due(self, volume='documents', late=1):
        """Avance l'horloge juste après la prochaine occurrence du volume et laisse le planificateur passer."""
        import native_schedule
        due = native_schedule.read(server, volume)['next_run']
        return native_schedule.tick(server, due + late), due

    def test_schedule_is_set_per_volume_and_needs_a_typed_confirmation_to_run(self):
        self.native()
        status, _, data = self.call('GET', '/api/storage/native-schedule'); value = json.loads(data)
        self.assertEqual((status, value['connected'], value['confirmation'], [(s['volume'], s['enabled'], s['time'], s['cap'], s['points'], s['next_run'], s['last']) for s in value['schedules']]),
                         (200, True, 'PROGRAMMER ', [('documents', False, '02:00', 30, 0, None, None), ('photos', False, '02:00', 30, 0, None, None)]))
        # Sans la confirmation exacte, rien n'est activé ; un brouillon désactivé n'en demande pas.
        body = {'volume': 'documents', 'enabled': True, 'time': '03:30', 'weekdays': [6, 0, 0], 'cap': 4}
        for confirmation in (None, 'PROGRAMMER', 'PROGRAMMER photos', 'programmer documents'):
            self.assertEqual(self.post({**body, 'confirmation': confirmation})[0], 400, confirmation)
        self.assertFalse(self.listed()['documents']['enabled'])
        self.assertEqual(self.post({**body, 'enabled': False})[0], 200)
        self.assertEqual((self.listed()['documents']['enabled'], self.listed()['documents']['time'], self.listed()['documents']['next_run']), (False, '03:30', None))
        status, value = self.post({**body, 'confirmation': 'PROGRAMMER documents'})
        self.assertEqual((status, value['enabled'], value['time'], value['weekdays'], value['cap'], value['last']), (200, True, '03:30', [0, 6], 4, None))
        self.assertGreater(value['next_run'], time.time()); self.assertLess(value['next_run'], time.time() + 8 * 86400)
        with server.database() as db:
            self.assertEqual(tuple(db.execute('SELECT action,detail FROM audit ORDER BY rowid DESC LIMIT 1').fetchone())[0], 'Programmation des captures natives activée')
        # Régler ne demande rien d'autre au service natif que son état, et ne capture rien.
        self.assertEqual({call[0] for call in self.calls}, {'status'}); self.assertEqual(self.state['points'], [])
        for change, expected in (({'time': '24:00'}, 400), ({'time': '3:30'}, 400), ({'weekdays': []}, 400), ({'weekdays': [7]}, 400), ({'weekdays': '0'}, 400), ({'cap': 0}, 400), ({'cap': 501}, 400),
                                 ({'cap': '4'}, 400), ({'enabled': 'oui'}, 400), ({'volume': 'ailleurs'}, 404), ({'volume': None}, 404)):
            self.assertEqual(self.post({**body, 'confirmation': 'PROGRAMMER documents', **change})[0], expected, change)
        token, _ = self.reader()
        self.assertEqual(self.call('GET', '/api/storage/native-schedule', token=token)[0], 403)
        self.assertEqual(self.call('POST', '/api/storage/native-schedule', body, csrf=False)[0], 403)
        self.state = {'connected': False, 'volumes': [], 'points': [], 'actions': [], 'jobs': []}
        self.assertEqual((json.loads(self.call('GET', '/api/storage/native-schedule')[2])['schedules'], self.post(body)[0]), ([], 503))

    def test_due_capture_goes_through_prepare_and_commit_once_and_is_marked_as_scheduled(self):
        import native_schedule
        self.native()
        self.post({'volume': 'documents', 'enabled': True, 'time': '03:30', 'cap': 2, 'confirmation': 'PROGRAMMER documents'})
        # Avant l'heure, rien ; à l'heure, une préparation puis une validation, sous le compte de la programmation.
        self.calls.clear(); self.assertEqual(native_schedule.tick(server, time.time()), []); self.assertEqual(self.calls, [])
        results, due = self.run_due()
        self.assertEqual(results, [('documents', 'done')])
        self.assertEqual([(method, actor) for method, actor, _ in self.calls], [('status', 'programmation'), ('prepare', 'programmation'), ('commit', 'programmation')])
        self.assertEqual(self.calls[1][2], {'action': 'snapshot', 'volume': 'documents'})
        item = self.listed()['documents']
        self.assertEqual((item['points'], item['last']['outcome'], item['last']['detail']), (1, 'done', 'Capture créée.')); self.assertGreater(item['next_run'], due)
        # L'occurrence est consommée : repasser au même instant ne capture pas une seconde fois.
        self.assertEqual(native_schedule.tick(server, due + 2), []); self.assertEqual(len(self.state['points']), 1)
        # Le point est noté comme programmé : la règle de conservation le traite, sans toucher aux captures manuelles.
        self.state['points'].append({'id': 'f' * 32, 'volume': 'documents', 'created': time.time() - 5, 'actor': 'admin', 'status': 'ready'})
        value = json.loads(self.call('POST', '/api/storage/native-retention-preview', {'volume': 'documents', 'keep_last': 1})[2])
        self.assertEqual(([p['manual'] for p in value['keep']], [(p['id'], p['manual']) for p in value['protected']]), ([False], [('f' * 32, True)]))
        with server.database() as db:
            self.assertEqual(tuple(db.execute("SELECT username,action FROM audit ORDER BY rowid DESC LIMIT 1").fetchone()), ('programmation', 'Capture native programmée'))
        # Plafond atteint : plus aucune capture, et c'est dit ; un point programmé disparu libère une place.
        self.assertEqual(self.run_due()[0], [('documents', 'done')])
        self.calls.clear(); self.assertEqual(self.run_due()[0], [('documents', 'capped')])
        self.assertEqual([method for method, _, _ in self.calls], ['status']); self.assertEqual(len(self.state['points']), 3)
        self.assertIn('Plafond de 2 points programmés atteint', self.listed()['documents']['last']['detail'])
        self.state['points'] = [point for point in self.state['points'] if point['id'] != f'{1:032x}']
        self.assertEqual(self.run_due()[0], [('documents', 'done')]); self.assertEqual(self.listed()['documents']['points'], 2)

    def test_occurrence_is_skipped_missed_or_refused_without_ever_being_replayed(self):
        import alerts, native_schedule
        self.native()
        self.post({'volume': 'documents', 'enabled': True, 'cap': 9, 'confirmation': 'PROGRAMMER documents'})
        keys = lambda: [c['key'] for c in alerts.collect(server)[0]['storage'] if c['key'].startswith('native-schedule:')]
        last = lambda volume='documents': self.listed()[volume]['last']
        self.assertEqual(keys(), [])
        # Opération en cours sur le volume, ou point en cours de création : sautée, pas mise en attente, et signalée.
        self.state['actions'] = [{'action': 'clone', 'volume': 'documents', 'status': 'running'}]
        self.assertEqual(self.run_due()[0], [('documents', 'skipped')]); self.assertEqual(self.state['points'], []); self.assertEqual(keys(), ['native-schedule:documents'])
        self.assertIn('occurrence sautée', last()['detail'])
        self.state['actions'] = [{'action': 'snapshot', 'volume': 'documents', 'status': 'queued'}]
        self.assertEqual(self.run_due()[0], [('documents', 'skipped')])
        self.state['actions'] = [{'action': 'clone', 'volume': 'photos', 'status': 'running'}, {'action': 'clone', 'volume': 'documents', 'status': 'done'}]
        self.state['points'] = [{'id': 'e' * 32, 'volume': 'documents', 'created': 1, 'status': 'creating'}]
        self.assertEqual(self.run_due()[0], [('documents', 'skipped')]); self.state['points'] = []; self.state['actions'] = []
        # Une copie de restauration LVM en cours retient les volumes LVM seulement : dans le même passage, l'autre volume est capturé.
        self.post({'volume': 'photos', 'enabled': True, 'cap': 9, 'confirmation': 'PROGRAMMER photos'})
        native_schedule.write(server, 'photos', {**native_schedule.read(server, 'photos'), 'next_run': native_schedule.read(server, 'documents')['next_run']})
        self.state['jobs'] = [{'id': 'j', 'status': 'running'}]
        self.assertEqual(dict(self.run_due()[0]), {'documents': 'done', 'photos': 'skipped'}); self.state['jobs'] = []
        self.assertEqual(([p['volume'] for p in self.state['points']], keys()), (['documents'], ['native-schedule:photos']))
        # Désactiver clôt l'alerte.
        self.assertEqual(self.post({'volume': 'photos', 'enabled': False})[0], 200); self.assertEqual(keys(), [])
        # Volume indisponible, refus à la préparation ou à la validation, service absent : jamais de second essai.
        self.state['volumes'][0].update(ready=False, reason='Identité modifiée')
        self.assertEqual(self.run_due()[0], [('documents', 'skipped')]); self.assertIn('Identité modifiée', last()['detail'])
        self.state['volumes'][0].update(ready=True)
        self.refuse = {'prepare': 'Capacité insuffisante.'}
        self.assertEqual(self.run_due()[0], [('documents', 'refused')]); self.assertEqual(last()['detail'], 'Capacité insuffisante.')
        self.refuse = {'commit': 'Identité modifiée ; préparer un nouveau plan.'}; self.calls.clear()
        self.assertEqual(self.run_due()[0], [('documents', 'refused')])
        self.assertEqual([method for method, _, _ in self.calls].count('commit'), 1); self.assertEqual(len(self.state['points']), 1)
        self.assertIn('rien n’est rejoué', last()['detail']); self.assertEqual(keys(), ['native-schedule:documents'])
        self.refuse = {}; self.state['connected'] = False
        self.assertEqual(self.run_due()[0], [('documents', 'skipped')]); self.state['connected'] = True
        with server.database() as db:
            self.assertEqual(tuple(db.execute("SELECT username,action FROM audit ORDER BY rowid DESC LIMIT 1").fetchone()), ('programmation', 'Capture native programmée non faite'))
        # Arrêt de la console : une occurrence trop ancienne est manquée, pas rattrapée, et ne lève pas d'alerte.
        results, due = self.run_due(late=native_schedule.GRACE + 60)
        self.assertEqual(results, [('documents', 'missed')]); self.assertEqual(len(self.state['points']), 1)
        self.assertGreater(native_schedule.read(server, 'documents')['next_run'], due + native_schedule.GRACE); self.assertEqual(keys(), [])
        # Dans la tolérance, l'occurrence a lieu ; un succès laisse le centre d'alertes vide.
        self.assertEqual(self.run_due(late=native_schedule.GRACE - 60)[0], [('documents', 'done')]); self.assertEqual((len(self.state['points']), keys()), (2, []))
        # Un réglage illisible ou une programmation désactivée ne lancent rien.
        with server.database() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('native-schedule:photos','pas du json') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        self.post({'volume': 'documents', 'enabled': False}); self.calls.clear()
        self.assertEqual(native_schedule.tick(server, time.time() + 30 * 86400), []); self.assertEqual(self.calls, [])
        self.assertEqual(self.listed()['photos']['enabled'], False)


if __name__ == '__main__':
    unittest.main()
