"""Conservation automatique des points natifs : activation, passages après capture programmée, garde-fous et suspension."""
import json
import sqlite3
import time
import unittest
from unittest.mock import patch

import test_file_manager as manager

server = manager.server


class NativeAutoTests(unittest.TestCase):
    setUp = manager.FileManagerTests.setUp
    tearDown = manager.FileManagerTests.tearDown
    call = manager.FileManagerTests.call
    reader = manager.FileManagerTests.reader

    def native(self):
        """Service natif simulé : captures et suppressions sur des points en mémoire."""
        self.calls, self.refuse, self.plans, self.partial, self.serial = [], {}, {}, None, 0
        self.state = {'connected': True, 'deletion': True, 'volumes': [{'id': 'documents', 'name': 'Documents', 'family': 'btrfs', 'ready': True}],
                      'points': [{'id': 'e' * 32, 'volume': 'documents', 'created': time.time() - 86400, 'actor': 'admin', 'status': 'ready'}], 'actions': [], 'jobs': []}

        def fake(method, actor, body=None):
            body = dict(body or {})
            self.calls.append((method, actor, body))
            if method == 'status':
                if 'status' in self.refuse:
                    raise server.Problem(self.refuse['status'], 503)
                return self.state
            if (method, body.get('action')) in self.refuse or method in self.refuse:
                raise server.Problem(self.refuse.get((method, body.get('action'))) or self.refuse[method])
            if method == 'prepare':
                self.serial += 1
                identifier = f'{self.serial:032x}'
                self.plans[identifier] = body
                if body['action'] == 'delete':
                    return {'id': identifier, 'action': 'delete', 'volume': body['volume'], 'confirmation': f'SUPPRIMER {len(body["points"])} POINTS DE {body["volume"]}',
                            'points': [{'id': point, 'created': 1} for point in body['points']]}
                return {'id': identifier, 'action': 'snapshot', 'volume': body['volume'], 'confirmation': 'CAPTURER ' + body['volume']}
            if method == 'commit':
                plan = self.plans.pop(body['plan'])
                if plan['action'] == 'delete':
                    if body['confirmation'] != f'SUPPRIMER {len(plan["points"])} POINTS DE {plan["volume"]}':
                        raise server.Problem('Recopier exactement la confirmation du plan.')
                    done = plan['points'] if self.partial is None else plan['points'][:self.partial]
                    self.state['points'] = [point for point in self.state['points'] if point['id'] not in done]
                    return {'ok': len(done) == len(plan['points']), 'deleted': done, 'uncertain': [], 'kept': plan['points'][len(done):],
                            'reason': '' if len(done) == len(plan['points']) else 'Le système a refusé la suppression d’un point, qui reste intact.'}
                self.state['points'].append({'id': body['plan'], 'volume': plan['volume'], 'created': time.time() - 3600 + self.serial, 'actor': actor, 'status': 'ready'})
                return {'ok': True, 'object': 'nacre_' + body['plan']}
            raise server.Problem('Méthode non autorisée.')
        patcher = patch.object(server, 'native_storage', side_effect=fake)
        patcher.start(); self.addCleanup(patcher.stop)

    def post(self, path, body, **more):
        status, _, data = self.call('POST', '/api/storage/' + path, body, **more)
        return status, json.loads(data)

    def auto(self):
        return json.loads(self.call('GET', '/api/storage/native-retention')[2])['policies'][0]['auto']

    def enable(self, cap=5):
        return self.post('native-auto', {'volume': 'documents', 'enabled': True, 'cap': cap, 'confirmation': 'AUTOMATISER documents'})

    def capture(self):
        """Laisse passer la prochaine occurrence programmée ; rend son résultat."""
        import native_schedule
        due = native_schedule.read(server, 'documents')['next_run']
        return native_schedule.tick(server, due + 1)

    def deletions(self):
        return [(actor, body) for method, actor, body in self.calls if method == 'prepare' and body.get('action') == 'delete']

    def ready(self):
        return sorted(point['id'] for point in self.state['points'])

    def journal(self):
        with server.database() as db:
            return [tuple(row) for row in db.execute("SELECT username,action,detail FROM audit WHERE action LIKE 'Conservation automatique%' ORDER BY rowid")]

    def prepare(self, keep=2, cap=30):
        self.native()
        self.assertEqual(self.post('native-schedule', {'volume': 'documents', 'enabled': True, 'cap': cap, 'confirmation': 'PROGRAMMER documents'})[0], 200)
        self.assertEqual(self.post('native-retention', {'volume': 'documents', 'keep_last': keep})[0], 200)

    def test_activation_needs_the_grant_a_saved_rule_a_maximum_and_the_typed_phrase(self):
        self.native()
        self.assertEqual((self.auto()['enabled'], self.auto()['pending']), (False, None))
        self.assertEqual(self.enable()[0], 409)                                  # règle non enregistrée
        self.assertEqual(self.post('native-retention', {'volume': 'documents', 'keep_last': 2})[0], 200)
        self.state['deletion'] = False
        self.assertEqual(self.enable()[0], 409)                                  # suppression non accordée
        self.state['deletion'] = True
        for body in ({}, {'cap': 0}, {'cap': 51}, {'cap': 2.5}, {'cap': '5'}, {'cap': 5, 'confirmation': 'AUTOMATISER'}, {'cap': 5, 'confirmation': 'AUTOMATISER photos'}, {'cap': 5, 'enabled': 'oui'}):
            self.assertEqual(self.post('native-auto', {'volume': 'documents', 'enabled': True, 'confirmation': 'AUTOMATISER documents', **body})[0], 400, body)
        self.assertEqual(self.post('native-auto', {'volume': 'inconnu', 'enabled': True, 'cap': 5, 'confirmation': 'AUTOMATISER inconnu'})[0], 404)
        token, csrf = self.reader()
        self.assertEqual(self.call('POST', '/api/storage/native-auto', {'volume': 'documents', 'enabled': False}, token=token, csrf=csrf)[0], 403)
        self.assertEqual(self.auto()['enabled'], False)
        status, value = self.enable(7)
        self.assertEqual((status, value['enabled'], value['cap'], value['reason'], value['last'], value['pending']), (200, True, 7, '', None, 0))
        listing = json.loads(self.call('GET', '/api/storage/native-retention')[2])
        self.assertEqual((listing['auto_phrase'], listing['auto_floor'], listing['batch'], listing['policies'][0]['auto']['enabled']), ('AUTOMATISER ', 5, 50, True))
        self.assertEqual(self.post('native-auto', {'volume': 'documents', 'enabled': False})[1]['enabled'], False)
        self.assertEqual([action for _, action, _ in self.journal()], ['Conservation automatique activée', 'Conservation automatique désactivée'])
        self.assertEqual(self.deletions(), [])

    def test_each_scheduled_capture_applies_the_rule_to_scheduled_points_only(self):
        self.prepare()
        self.enable()
        for expected in (0, 0, 1, 1):
            before = len(self.deletions())
            self.assertEqual(self.capture(), [('documents', 'done')])
            self.assertEqual(len(self.deletions()) - before, expected)
        # Deux derniers points programmés gardés ; la capture manuelle n'a jamais été proposée, même la plus ancienne.
        self.assertEqual(len(self.ready()), 3)
        self.assertIn('e' * 32, self.ready())
        actor, body = self.deletions()[-1]
        self.assertEqual((actor, body['volume'], len(body['points'])), ('programmation', 'documents', 1))
        self.assertNotIn('e' * 32, [point for _, each in self.deletions() for point in each['points']])
        with server.database() as db:
            marks = json.loads(db.execute("SELECT value FROM settings WHERE key='native-scheduled:documents'").fetchone()['value'])
        self.assertEqual(sorted(marks), [point for point in self.ready() if point != 'e' * 32])
        state = self.auto()
        self.assertEqual((state['enabled'], state['last']['outcome'], state['last']['deleted'], state['last']['detail'], state['pending']), (True, 'done', 1, '1 point supprimé.', 0))
        self.assertEqual([entry[1:] for entry in self.journal()[1:]], [('Conservation automatique appliquée', 'documents : 1 point supprimé.')] * 2)
        # Une règle enregistrée avec les captures manuelles ne change rien au passage automatique.
        self.assertEqual(self.post('native-retention', {'volume': 'documents', 'keep_last': 2, 'manual': True})[1]['auto_stopped'], False)
        self.capture()
        self.assertIn('e' * 32, self.ready())
        # Désactivée : la capture a lieu, plus aucune suppression.
        self.post('native-auto', {'volume': 'documents', 'enabled': False})
        before = len(self.deletions())
        self.capture()
        self.assertEqual((len(self.deletions()), len(self.ready())), (before, 4))

    def test_a_pass_is_skipped_without_suspending_when_nothing_can_be_judged(self):
        self.prepare(keep=1)
        self.enable()
        self.capture()
        self.state['actions'] = [{'volume': 'documents', 'action': 'clone', 'status': 'uncertain'}]
        self.capture()
        state = self.auto()
        self.assertEqual((state['enabled'], state['last']['outcome'], 'restauration' in state['last']['detail'], self.deletions()), (True, 'skipped', True, []))
        self.state['actions'] = []
        import native_auto
        self.refuse['status'] = 'Le service de stockage natif n’est pas activé sur ce matériel.'
        self.assertEqual(native_auto.run(server, 'documents'), 'skipped')
        self.refuse.clear()
        self.assertEqual((native_auto.read(server, 'documents')['enabled'], native_auto.conditions(server)), (True, []))
        self.capture()
        self.assertEqual(len(self.deletions()), 1)
        self.assertEqual(len(self.deletions()[0][1]['points']), 2)

    def test_refusals_and_limits_suspend_until_an_administrator_enables_again(self):
        import native_auto
        self.prepare(keep=1)
        self.enable(cap=1)
        self.capture()
        # Plus de points sortants que le maximum : rien n'est demandé au service, et l'alerte se lève.
        self.post('native-auto', {'volume': 'documents', 'enabled': False})
        self.capture(); self.capture()
        self.assertEqual(self.enable(cap=1)[1]['pending'], 2)
        self.capture()
        state = self.auto()
        self.assertEqual((state['enabled'], state['last']['outcome'], state['reason']), (False, 'suspended', '3 points sortiraient, plus que le maximum de 1 par passage : rien n’a été supprimé.'))
        self.assertEqual((self.deletions(), len(self.ready())), ([], 5))
        self.assertEqual([(key, title) for key, title, *_ in native_auto.conditions(server)], [('native-auto:documents', 'Conservation automatique suspendue')])
        import alerts
        keys = lambda: [c['key'] for c in alerts.collect(server)[0]['storage'] if c['key'].startswith('native-auto:')]
        self.assertEqual(keys(), ['native-auto:documents'])
        # Suspendue, elle ne fait plus rien ; réactivée, l'alerte tombe.
        self.capture()
        self.assertEqual(self.deletions(), [])
        self.assertEqual(self.enable(cap=10)[1]['reason'], '')
        self.assertEqual((native_auto.conditions(server), keys()), ([], []))
        # Refus à la préparation, puis suppression interrompue : suspension, et ce qui a été supprimé est compté.
        self.refuse[('prepare', 'delete')] = 'Une restauration est en cours ou à vérifier sur ce volume : aucun point ne peut être supprimé.'
        self.capture()
        self.assertEqual((self.auto()['enabled'], self.auto()['reason'].endswith('aucun point ne peut être supprimé. Rien n’a été supprimé.')), (False, True))
        self.refuse.clear(); self.enable(cap=10); self.partial = 2
        count = len(self.ready())
        self.capture()
        state = self.auto()
        self.assertEqual((state['enabled'], state['last']['deleted'], state['reason'].startswith('2 points supprimés sur ')), (False, 2, True))
        self.assertEqual(len(self.ready()), count + 1 - 2)
        self.partial = None
        # Accord de suppression retiré sur le matériel ; validation refusée.
        self.enable(cap=10); self.state['deletion'] = False
        self.capture()
        self.assertEqual(self.auto()['reason'], 'Le service natif n’accorde plus la suppression de points.')
        self.state['deletion'] = True; self.enable(cap=10); self.refuse['commit'] = 'Plan expiré, déjà exécuté ou appartenant à un autre compte.'
        self.assertEqual(native_auto.run(server, 'documents'), 'suspended')
        self.assertTrue(self.auto()['reason'].endswith('rien n’est rejoué.'))
        self.assertEqual([action for _, action, _ in self.journal()].count('Conservation automatique suspendue'), 5)

    def test_a_capped_schedule_is_freed_and_a_changed_rule_or_a_recovery_stops_automation(self):
        import native_auto
        self.prepare(keep=1, cap=2)
        self.capture(); self.capture()
        self.assertEqual(self.capture(), [('documents', 'capped')])
        self.enable()
        # Au plafond : pas de capture, mais le passage automatique libère la place pour la suivante.
        self.assertEqual(self.capture(), [('documents', 'capped')])
        self.assertEqual((len(self.deletions()), len(self.ready())), (1, 2))
        self.assertEqual(self.capture(), [('documents', 'done')])
        # Une autre règle enregistrée arrête la conservation automatique, sans alerte ; la même règle ne change rien.
        self.assertEqual(self.post('native-retention', {'volume': 'documents', 'keep_last': 1})[1]['auto_stopped'], False)
        status, value = self.post('native-retention', {'volume': 'documents', 'keep_last': 3})
        self.assertEqual((status, value['auto_stopped'], value['auto']['enabled'], native_auto.conditions(server)), (200, True, False, []))
        self.assertEqual(self.journal()[-1][1:], ('Conservation automatique désactivée', 'documents : règle modifiée, à réactiver'))
        # Après une récupération de l'installation, toute conservation automatique attend une réactivation.
        self.enable()
        with server.database() as db:
            native_auto.disable_after_recovery(db)
        state = self.auto()
        self.assertEqual((state['enabled'], state['reason'].startswith('Installation récupérée')), (False, True))
        native_auto.disable_after_recovery(sqlite3.connect(':memory:'))


if __name__ == '__main__':
    unittest.main()
