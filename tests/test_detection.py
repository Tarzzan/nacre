"""Détection par caméra sur Frigate simulé : aucune caméra, vidéo ou Docker."""
import copy
import json
import unittest
from unittest.mock import patch

import test_components_cameras as base
import detection

app = base.server
MODEL = {0: 'person', 1: 'bicycle', 2: 'car', 3: 'banana', 4: 'dog', 5: 'cat', 6: 'Bad Label!', 7: 7}


class DetectionTests(unittest.TestCase):
    setUp = base.ComponentsCameraTests.setUp
    tearDown = base.ComponentsCameraTests.tearDown
    request = base.ComponentsCameraTests.request

    def configure(self, tracked=('person',), enabled=True, saved=None):
        entry = {'friendly_name': 'Entrée', 'detect': {'enabled': False, 'fps': 5}, 'record': {'continuous': {'days': 2}},
                 'onvif': {'host': '192.168.50.20', 'password': 'private-fixture'}, 'ffmpeg': {'inputs': [{'path': 'rtsp://private-fixture'}]}}
        if saved is not None:
            entry.update(saved)
        app.private_write(self.config, json.dumps({'cameras': {'entry': entry}}))
        self.live = {'enabled': enabled, 'track': list(tracked), 'filters': {label: {} for label in tracked}}
        self.puts, self.commands = [], []

    def frigate(self, put=None, command=None, config=None):
        def video_json(path):
            self.assertEqual(path, '/api/config')
            if config is not None:
                return config
            return {'cameras': {'entry': {'detect': {'enabled': self.live['enabled']}, 'ffmpeg': {'inputs': [{'path': 'rtsp://private-fixture'}]},
                    'objects': {'track': list(self.live['track']), 'filters': copy.deepcopy(self.live['filters'])}}},
                    'detectors': {'cpu': {'type': 'cpu', 'model': {'labelmap': MODEL}}}}
        def video_put(path, payload):
            self.puts.append((path, payload))
            if put:
                return put(payload)
            objects = payload['config_data']['cameras']['entry']['objects']
            self.live['track'] = objects['track'];self.live['filters'].update(objects['filters'])
            return {'success': True}
        def video_command(topic, payload):
            self.commands.append((topic, payload))
            if command:
                return command()
            self.live['enabled'] = payload == 'ON'
        return (patch.object(app, 'video_json', side_effect=video_json), patch.object(app, 'video_put', side_effect=video_put),
                patch.object(app, 'video_command', side_effect=video_command), patch.object(app, 'compose', return_value=''),
                patch.object(detection.time, 'sleep'))

    def run_with(self, call, **kwargs):
        patches = self.frigate(**kwargs)
        mocks = [item.start() for item in patches]
        try:
            return call(mocks[3])
        finally:
            for item in patches:
                item.stop()

    def get(self, token=None, camera='entry'):
        status, data = self.request('GET', '/api/camera/detection?camera=' + camera, token=token or self.token)
        return status, json.loads(data)

    def post(self, body, token=None, csrf=None):
        status, data = self.request('POST', '/api/camera/detection', {'camera': 'entry', **body}, token or self.token, csrf or self.csrf)
        return status, json.loads(data)

    def saved(self):
        entry = json.loads(self.config.read_text())['cameras']['entry']
        return entry.get('objects', {}).get('track'), entry['detect']['enabled']

    def audit(self):
        with app.database() as db:
            return [(row['action'], row['detail']) for row in db.execute('SELECT action,detail FROM audit ORDER BY ts')]

    def test_state_is_the_applied_one_limited_to_known_labels_without_secrets(self):
        self.configure(tracked=('person', 'unicorn'))
        status, data = self.run_with(lambda _: self.get())
        self.assertEqual(status, 200)
        self.assertEqual(data, {'enabled': True, 'tracked': ['person', 'unicorn'], 'groups': [
            {'id': 'people', 'name': 'Personnes', 'labels': ['person']},
            {'id': 'vehicles', 'name': 'Véhicules', 'labels': ['car', 'bicycle']},
            {'id': 'animals', 'name': 'Animaux', 'labels': ['dog', 'cat']},
            {'id': 'others', 'name': 'Autres types déjà suivis', 'labels': ['unicorn']}]})
        self.assertNotIn('private-fixture', json.dumps(data))
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token, csrf = app.make_session('reader')
        self.assertEqual(self.run_with(lambda _: self.get(token))[0], 200)
        self.assertEqual(self.run_with(lambda _: self.post({'enabled': True, 'track': ['person']}, token, csrf))[0], 403)
        self.assertEqual(self.run_with(lambda _: self.get(camera='absente'))[0], 404)

    def test_malformed_or_missing_frigate_state_is_unavailable_not_invented(self):
        self.configure()
        for config in ([], {}, {'cameras': {'entry': {}}}, {'cameras': {'entry': {'detect': {'enabled': 'yes'}, 'objects': {'track': ['person']}}}},
                       {'cameras': {'entry': {'detect': {'enabled': True}, 'objects': {'track': 'person'}}}}):
            status, data = self.run_with(lambda _: self.get(), config=config)
            self.assertEqual(status, 503, config)
            self.assertIn('indisponible', data['error'])
        partial = {'cameras': {'entry': {'detect': {'enabled': False}, 'objects': {'track': ['person', 3]}}}, 'detectors': 'cpu'}
        self.assertEqual(self.run_with(lambda _: self.get(), config=partial)[1],
                         {'enabled': False, 'tracked': ['person'], 'groups': [{'id': 'people', 'name': 'Personnes', 'labels': ['person']}]})

    def test_apply_writes_the_file_and_asks_frigate_without_restart(self):
        self.configure()
        before = self.config.read_bytes()
        def call(compose):
            result = self.post({'enabled': True, 'track': ['dog', 'person', 'car']})
            return result, compose.call_args_list
        (status, data), composed = self.run_with(call)
        self.assertEqual(status, 200, data)
        self.assertIn('sans interruption', data['message'])
        self.assertEqual(self.saved(), (['person', 'car', 'dog'], True))
        self.assertEqual(len(composed), 1)
        self.assertEqual(composed[0].args[:3], ('exec', '-T', 'video'))
        self.assertNotIn('restart', [arg for item in composed for arg in item.args])
        path, payload = self.puts[0]
        self.assertEqual((path, len(self.puts)), ('/api/config/set', 1))
        self.assertEqual((payload['skip_save'], payload['requires_restart'], payload['update_topic']), (True, 0, 'config/cameras/entry/objects'))
        self.assertEqual(payload['config_data'], {'cameras': {'entry': {'objects': {'track': ['person', 'car', 'dog'], 'filters': {'person': {}, 'car': {}, 'dog': {}}}}}})
        self.assertEqual(self.commands, [])
        backup = app.STATE / 'config-avant-detection.yml'
        self.assertEqual((backup.read_bytes(), backup.stat().st_mode & 0o777, self.config.stat().st_mode & 0o777), (before, 0o600, 0o600))
        self.assertIn(('Détection réglée', 'entry : active ; person, car, dog'), self.audit())
        # Rejouer le même réglage ne réécrit rien et ne sollicite pas Frigate.
        stamp = self.config.stat().st_mtime_ns
        status, data = self.run_with(lambda _: self.post({'enabled': True, 'track': ['person', 'car', 'dog']}))
        self.assertEqual((status, len(self.puts), self.config.stat().st_mtime_ns), (200, 1, stamp))
        self.assertIn('Aucun changement', data['message'])

    def test_detection_switch_uses_the_frigate_command_and_keeps_objects_untouched(self):
        self.configure(enabled=False, saved={'objects': {'track': ['person']}})
        status, data = self.run_with(lambda _: self.post({'enabled': True, 'track': ['person']}))
        self.assertEqual(status, 200, data)
        self.assertEqual((self.commands, self.puts, self.saved()), ([('entry/detect/set', 'ON')], [], (['person'], True)))
        status, data = self.run_with(lambda _: self.post({'enabled': False, 'track': ['person']}))
        self.assertEqual((status, self.commands[-1], self.saved()), (200, ('entry/detect/set', 'OFF'), (['person'], False)))
        self.assertIn(('Détection réglée', 'entry : en pause ; person'), self.audit())

    def test_invalid_choices_change_nothing(self):
        self.configure()
        before = self.config.read_bytes()
        for body in ({'enabled': True, 'track': []}, {'enabled': True, 'track': 'person'}, {'enabled': 'ON', 'track': ['person']}, {'track': ['person']},
                     {'enabled': True, 'track': ['person', 'person']}, {'enabled': True, 'track': ['banana']}, {'enabled': True, 'track': ['truck']},
                     {'enabled': True, 'track': [['person']]}, {'enabled': True, 'track': ['person'] * 40}, {'enabled': True, 'track': ['person', 7]}):
            self.assertEqual(self.run_with(lambda _: self.post(body))[0], 400, body)
        self.assertEqual(self.request('POST', '/api/camera/detection', {'camera': 'entry', 'enabled': True, 'track': ['person']}, self.token)[0], 403)
        self.assertEqual((self.config.read_bytes(), self.puts, self.commands), (before, [], []))
        self.assertFalse((app.STATE / 'config-avant-detection.yml').exists())

    def test_refused_validation_or_live_update_keeps_the_previous_file(self):
        self.configure()
        before = self.config.read_bytes()
        patches = self.frigate()
        for item in patches:
            item.start()
        try:
            patches[3].stop()
            with patch.object(app, 'compose', side_effect=app.Problem('refus', 503)):
                status, data = self.post({'enabled': True, 'track': ['person', 'car']})
            patches[3].start()
        finally:
            for item in patches:
                item.stop()
        self.assertEqual((status, self.config.read_bytes(), self.puts), (503, before, []))
        self.assertIn('Rien n’a été modifié', data['error'])
        for put in (lambda payload: {'success': False, 'message': 'private detail'}, lambda payload: (_ for _ in ()).throw(app.Problem('indisponible', 503))):
            status, data = self.run_with(lambda _: self.post({'enabled': True, 'track': ['person', 'car']}), put=put)
            self.assertEqual((status, self.config.read_bytes()), (503, before))
            self.assertIn('configuration précédente est rétablie', data['error'])
            self.assertNotIn('private detail', json.dumps(data))
        self.assertEqual([action for action, _ in self.audit() if 'Détection' in action], [])

    def test_unconfirmed_application_is_reported_and_never_claimed(self):
        self.configure()
        status, data = self.run_with(lambda _: self.post({'enabled': True, 'track': ['person', 'car']}), put=lambda payload: {'success': True})
        self.assertEqual(status, 503)
        self.assertIn('n’est pas confirmée', data['error'])
        self.assertEqual(self.saved(), (['person', 'car'], True))
        self.assertIn('Détection enregistrée, application non confirmée', [action for action, _ in self.audit()])
        self.assertNotIn('Détection réglée', [action for action, _ in self.audit()])
        # Un type suivi sans son filtre n’est pas un réglage appliqué.
        self.configure()
        def without_filter(payload):
            self.live['track'] = payload['config_data']['cameras']['entry']['objects']['track']
            return {'success': True}
        self.assertEqual(self.run_with(lambda _: self.post({'enabled': True, 'track': ['person', 'car']}), put=without_filter)[0], 503)
        self.configure(enabled=False)
        status, data = self.run_with(lambda _: self.post({'enabled': True, 'track': ['person']}), command=lambda: (_ for _ in ()).throw(app.Problem('canal', 503)))
        self.assertEqual((status, self.saved()), (503, (['person'], True)))

    def test_running_task_blocks_the_change(self):
        self.configure()
        with app.database() as db:
            db.execute("INSERT INTO jobs(id,kind,status,username,ts,options) VALUES('j1','camera_add','running','admin',1,'{}')")
        before = self.config.read_bytes()
        self.assertEqual(self.run_with(lambda _: self.post({'enabled': True, 'track': ['person', 'car']}))[0], 409)
        self.assertEqual((self.config.read_bytes(), self.puts), (before, []))


if __name__ == '__main__':
    unittest.main()
