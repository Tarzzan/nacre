"""Passages conservés et autonomie vidéo sur un Frigate simulé : aucune caméra, vidéo ou Docker."""
import datetime
import io
import json
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_components_cameras as base
import kept
import onboarding

app = base.server


class Reply(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'video/mp4'}


class Frigate:
    """Exports, dossier des fichiers et mesures de stockage, tels que Frigate 0.18 les présente."""
    def __init__(self):
        self.exports, self.files, self.posts, self.gets = [], [], [], []
        self.answer = None
        self.stale = [{'id': 'entry_stale', 'camera': 'entry', 'name': 'réponse périmée', 'date': 1700000000, 'in_progress': False, 'video_path': '/media/frigate/exports/entry_stale.mp4'}]
        self.disk = {'total': 1000000.0, 'used': 400000.0, 'free': 600000.0, 'mount_type': 'ext4'}
        self.usage = {'entry': {'usage': 48000.0, 'bandwidth': 1000.0}}

    def video_get(self, path, **kwargs):
        self.gets.append(path)
        if path.startswith('/api/exports'):
            # Comme le vrai : sans contournement, la liste d'avant le dernier changement peut être resservie.
            return Reply(json.dumps(self.exports if kwargs.get('headers', {}).get('X-Cache-Bypass') == '1' else self.stale).encode())
        if path == '/exports/':
            return Reply(json.dumps(self.files).encode())
        if path == '/api/recordings/storage':
            return Reply(json.dumps(self.usage).encode())
        if path == '/api/stats':
            return Reply(json.dumps({'service': {'storage': {kept.RECORDINGS: self.disk}}}).encode())
        if path.startswith('/exports/'):
            return Reply(b'video')
        raise app.Problem('La vidéo est temporairement indisponible.', 503)

    def video_json(self, path):
        return json.load(self.video_get(path))

    def video_post(self, path, payload, timeout=15):
        self.posts.append((path, payload))
        if self.answer:
            return self.answer
        if path == '/api/exports/delete':
            self.exports = [e for e in self.exports if e['id'] not in payload['ids']]
            return 200, {'success': True}
        camera, first = path.split('/')[3], int(path.split('/')[5])
        ident = f'{camera}_{len(self.exports)}abc'
        self.exports.append({'id': ident, 'camera': camera, 'name': payload['name'], 'date': first, 'in_progress': True,
                             'video_path': f'/media/frigate/exports/{ident}.mp4', 'thumb_path': '/media/frigate/clips/export/private-fixture.webp'})
        return 202, {'success': True, 'message': 'Export queued.', 'export_id': ident, 'status': 'queued'}

    def finish(self, size=5000):
        for e in self.exports:
            e['in_progress'] = False
        self.files = [{'name': e['video_path'].rsplit('/', 1)[-1], 'type': 'file', 'size': size} for e in self.exports]


class KeptTests(unittest.TestCase):
    setUp = base.ComponentsCameraTests.setUp
    tearDown = base.ComponentsCameraTests.tearDown
    request = base.ComponentsCameraTests.request
    post = base.ComponentsCameraTests.post

    def configure(self, cameras=None):
        cameras = cameras or {'entry': {'friendly_name': 'Entrée', 'record': {'continuous': {'days': 2}}, 'ffmpeg': {'inputs': [{'path': 'rtsp://private-fixture'}]}}}
        app.private_write(self.config, json.dumps({'cameras': cameras}))
        with app.database() as db:
            onboarding.write(db, {'phase': 'complete', 'name': 'Banc', 'timezone': 'America/Cayenne', 'existing': False})
        self.zone = ZoneInfo('America/Cayenne')
        self.frigate = Frigate()
        for name in ('video_get', 'video_json', 'video_post'):
            patcher = patch.object(app, name, side_effect=getattr(self.frigate, name))
            patcher.start(); self.addCleanup(patcher.stop)

    def get(self, path, token=None):
        status, data = self.request('GET', path, token=token or self.token)
        return status, json.loads(data)

    def send(self, path, body):
        status, data = self.post(path, body)
        return status, json.loads(data)

    def audit(self):
        with app.database() as db:
            return [tuple(r) for r in db.execute('SELECT action,detail FROM audit ORDER BY id')]

    def test_extract_is_kept_listed_and_removed(self):
        self.configure(); before = self.config.read_bytes()
        start = int(time.time()) - 3600
        status, data = self.send('/api/camera/keep', {'camera': 'entry', 'start': start + .4, 'end': start + 120.2, 'name': '  Livraison   colis '})
        self.assertEqual((status, data), (200, {'ok': True, 'id': 'entry_0abc'}))
        # Arrondi vers l'extérieur : la copie couvre au moins l'extrait vu ; le nom porte l'intervalle.
        self.assertEqual(self.frigate.posts, [(f'/api/export/entry/start/{start}/end/{start + 121}', {'name': f'{start}-{start + 121} Livraison colis'})])
        stamp = datetime.datetime.fromtimestamp(start, self.zone)
        self.assertEqual(self.audit()[-1], ('Extrait vidéo conservé', f'entry · {stamp:%Y-%m-%d %H:%M:%S} · 121 s · Livraison colis'))
        status, data = self.get('/api/camera/kept?camera=entry')
        self.assertEqual(status, 200)
        self.assertEqual(data['items'], [{'id': 'entry_0abc', 'start': start, 'end': start + 121, 'name': 'Livraison colis', 'pending': True, 'size': None, 'day': stamp.date().isoformat()}])
        self.assertEqual((data['camera'], data['timezone'], data['size'], data['more'], data['keep_max'], data['name_max']), ('entry', 'America/Cayenne', 0, False, 300, 60))
        for private in ('video_path', 'thumb_path', 'private-fixture', '/media/'):
            self.assertNotIn(private, json.dumps(data))
        # Le même extrait n'est pas gardé deux fois ; une copie en cours ne se retire pas.
        self.assertEqual(self.send('/api/camera/keep', {'camera': 'entry', 'start': start, 'end': start + 121})[0], 409)
        self.assertEqual(self.send('/api/camera/unkeep', {'camera': 'entry', 'id': 'entry_0abc', 'confirm': True})[0], 409)
        self.frigate.finish()
        data = self.get('/api/camera/kept?camera=entry')[1]
        self.assertEqual((data['items'][0]['pending'], data['items'][0]['size'], data['size']), (False, 5000, 5000))
        self.assertEqual(self.send('/api/camera/unkeep', {'camera': 'entry', 'id': 'entry_0abc'})[0], 400)
        self.assertEqual(len(self.frigate.posts), 1)
        self.assertEqual(self.send('/api/camera/unkeep', {'camera': 'entry', 'id': 'entry_0abc', 'confirm': True}), (200, {'ok': True}))
        self.assertEqual(self.frigate.posts[-1], ('/api/exports/delete', {'ids': ['entry_0abc']}))
        self.assertEqual(self.audit()[-1], ('Passage conservé retiré', f'entry · {stamp:%Y-%m-%d %H:%M:%S} · Livraison colis'))
        self.assertEqual(self.get('/api/camera/kept?camera=entry')[1]['items'], [])
        self.assertEqual(self.send('/api/camera/unkeep', {'camera': 'entry', 'id': 'entry_0abc', 'confirm': True})[0], 404)
        self.assertEqual(before, self.config.read_bytes())

    def test_invalid_requests_reach_nothing(self):
        self.configure(); now = time.time()
        bad = [{'start': now - 500, 'end': now - 100}, {'start': now - 100, 'end': now - 200}, {'start': now - 100, 'end': now - 100},
               {'start': now + 30, 'end': now + 200}, {'start': now - 40 * 86400, 'end': now - 40 * 86400 + 60}, {'start': 'x', 'end': now},
               {'start': True, 'end': 2}, {'start': now - 100}, {'start': now - 100, 'end': now - 50, 'name': 'x' * 61},
               {'start': now - 100, 'end': now - 50, 'name': 'a\x00b'}, {'start': now - 100, 'end': now - 50, 'name': 7}]
        for body in bad:
            self.assertEqual(self.send('/api/camera/keep', {'camera': 'entry', **body})[0], 400, body)
        self.assertEqual(self.send('/api/camera/keep', {'camera': 'absente', 'start': now - 100, 'end': now - 50})[0], 404)
        self.assertEqual(self.send('/api/camera/keep', {'camera': '../x', 'start': now - 100, 'end': now - 50})[0], 400)
        self.assertEqual(self.send('/api/camera/unkeep', {'camera': 'entry', 'id': '../../x', 'confirm': True})[0], 400)
        self.assertEqual(self.frigate.posts, [])
        self.assertEqual(self.audit(), [])

    def test_video_service_refusals_are_explained(self):
        self.configure(); now = time.time(); body = {'camera': 'entry', 'start': now - 100, 'end': now - 50}
        for answer, expected, text in (((400, {'success': False, 'message': 'No recordings found for time range'}), 409, 'plus enregistrée'),
                                       ((503, {'success': False}), 503, 'Réessayez'), ((500, {}), 502, 'Rien n’a été gardé'),
                                       ((200, {'success': False}), 502, 'Rien n’a été gardé'), ((200, []), 502, 'Rien n’a été gardé')):
            self.frigate.answer = answer
            status, data = self.send('/api/camera/keep', body)
            self.assertEqual(status, expected, answer); self.assertIn(text, data['error'])
        self.assertEqual(self.audit(), [])
        self.frigate.exports = [{'id': 'entry_1', 'camera': 'entry', 'name': '1700000000-1700000060', 'date': 1700000000, 'in_progress': False, 'video_path': '/media/frigate/exports/entry_1.mp4'}]
        self.frigate.answer = (404, {'success': False})
        status, data = self.send('/api/camera/unkeep', {'camera': 'entry', 'id': 'entry_1', 'confirm': True})
        self.assertEqual(status, 502); self.assertIn('toujours conservé', data['error'])
        self.assertEqual(self.audit(), [])

    def test_viewer_reads_but_does_not_keep(self):
        self.configure(); now = time.time()
        self.assertEqual(self.request('GET', '/api/camera/kept?camera=entry')[0], 401)
        self.assertEqual(self.request('GET', '/api/cameras/storage')[0], 401)
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token, csrf = app.make_session('reader')
        self.assertEqual(self.get('/api/camera/kept?camera=entry', token)[0], 200)
        self.assertEqual(self.get('/api/cameras/storage', token)[0], 200)
        self.assertEqual(self.request('POST', '/api/camera/keep', {'camera': 'entry', 'start': now - 100, 'end': now - 50}, token, csrf)[0], 403)
        self.assertEqual(self.request('POST', '/api/camera/unkeep', {'camera': 'entry', 'id': 'x', 'confirm': True}, token, csrf)[0], 403)
        self.assertEqual(self.request('POST', '/api/camera/keep', {'camera': 'entry', 'start': now - 100, 'end': now - 50}, self.token)[0], 403)
        self.assertEqual(self.frigate.posts, [])

    def test_foreign_and_hostile_exports(self):
        self.configure()
        self.frigate.exports = [
            {'id': 'entry_a', 'camera': 'entry', 'name': 'Export fait ailleurs', 'date': 1700000500, 'in_progress': False, 'video_path': '/media/frigate/exports/entry_a.mp4'},
            {'id': 'entry_b', 'camera': 'entry', 'name': '1700000000-1700000060 Portail', 'date': 1, 'in_progress': False, 'video_path': '/media/frigate/exports/../../etc/passwd'},
            {'id': 'other_c', 'camera': 'other', 'name': '1700000000-1700000060', 'date': 1700000000, 'in_progress': False, 'video_path': '/media/frigate/exports/other_c.mp4'},
            {'id': '../x', 'camera': 'entry', 'name': 'x', 'date': 1700000000}, {'id': 'entry_d', 'camera': 'entry', 'name': '1700000060-1700000000', 'date': 'x'},
            {'id': 'entry_e', 'camera': 'entry', 'name': None, 'date': 1700000900.5, 'video_path': 7}, None, 'x']
        self.frigate.files = [{'name': 'entry_a.mp4', 'size': 1200}, {'name': 'passwd', 'size': 9}, {'name': 'x', 'size': -4}, {'name': 3, 'size': 3}, None]
        status, data = self.get('/api/camera/kept?camera=entry')
        self.assertEqual(status, 200)
        self.assertEqual([(e['id'], e['start'], e['end'], e['name'], e['size'], e['pending']) for e in data['items']],
                         [('entry_e', 1700000900.5, None, '', None, True), ('entry_a', 1700000500, None, 'Export fait ailleurs', 1200, False), ('entry_b', 1700000000, 1700000060, 'Portail', None, False)])
        # Un chemin qui sort du dossier des exports n'est jamais demandé au service vidéo.
        self.assertEqual(self.request('GET', '/api/camera/kept-video?camera=entry&id=entry_b', token=self.token)[0], 409)
        self.assertEqual(self.request('GET', '/api/camera/kept-video?camera=entry&id=entry_e', token=self.token)[0], 409)
        self.assertEqual(self.request('GET', '/api/camera/kept-video?camera=entry&id=other_c', token=self.token)[0], 404)
        self.assertEqual(self.request('GET', '/api/camera/kept-video?camera=entry&id=..%2Fx', token=self.token)[0], 400)
        self.assertFalse([p for p in self.frigate.gets if p.startswith('/exports/') and p != '/exports/'])
        self.frigate.exports = {'detail': 'x'}
        self.assertEqual(self.get('/api/camera/kept?camera=entry')[0], 503)

    def test_kept_video_is_relayed_and_downloads_are_logged(self):
        self.configure()
        self.frigate.exports = [{'id': 'entry_a', 'camera': 'entry', 'name': '1700000000-1700000060', 'date': 1700000000, 'in_progress': False, 'video_path': '/media/frigate/exports/entry_20231114_a.mp4'}]
        status, data = self.request('GET', '/api/camera/kept-video?camera=entry&id=entry_a', token=self.token)
        self.assertEqual((status, data), (200, b'video'))
        self.assertEqual(self.frigate.gets[-1], '/exports/entry_20231114_a.mp4')
        self.assertEqual(self.audit(), [])
        self.assertEqual(self.request('GET', '/api/camera/kept-video?camera=entry&id=entry_a&download=1', token=self.token)[0], 200)
        stamp = datetime.datetime.fromtimestamp(1700000000, self.zone)
        self.assertEqual(self.audit(), [('Téléchargement d’un passage conservé', f'nacre-entry-conserve-{stamp:%Y%m%d-%H%M%S}.mp4')])

    def test_camera_cannot_exceed_its_kept_limit(self):
        self.configure(); now = int(time.time())
        with patch.object(kept, 'KEPT_MAX', 2):
            for index in range(2):
                self.assertEqual(self.send('/api/camera/keep', {'camera': 'entry', 'start': now - 1000 + index * 100, 'end': now - 950 + index * 100})[0], 200)
            status, data = self.send('/api/camera/keep', {'camera': 'entry', 'start': now - 500, 'end': now - 450})
            self.assertEqual(status, 409); self.assertIn('Retirez-en', data['error'])
            self.assertEqual(len(self.frigate.posts), 2)

    def test_storage_autonomy(self):
        self.configure({'entry': {'friendly_name': 'Entrée', 'record': {'continuous': {'days': 2}}},
                        'yard': {'record': {'continuous': {'days': 30}}}, 'paused': {'enabled': False}})
        self.frigate.usage = {'entry': {'usage': 48000.0, 'bandwidth': 1000.0}, 'yard': {'usage': 12000.0, 'bandwidth': 500.0}, 'paused': {'usage': 100.0, 'bandwidth': 300.0}}
        self.frigate.files = [{'name': 'entry_a.mp4', 'size': 1200}, {'name': 'yard_b.mp4', 'size': 800}]
        mib = 1024 ** 2
        status, data = self.get('/api/cameras/storage')
        self.assertEqual(status, 200)
        # Débit : 1 500 Mio/h, caméra en pause exclue. Durée réglée : 2 j et 30 j, soit 408 000 Mio à terme pour 60 100 déjà pris.
        self.assertEqual((data['available'], data['state'], data['total'], data['free'], data['rate'], data['hours']), (True, 'ample', 1000000 * mib, 600000 * mib, 1500 * mib, 400.0))
        self.assertEqual((data['recorded'], data['needed'], data['reach_days'], data['kept']), (60100 * mib, 408000 * mib, None, {'count': 2, 'size': 2000}))
        self.assertEqual([(c['id'], c['name'], c['rate'], c['days']) for c in data['cameras']], [('entry', 'Entrée', 1000 * mib, 2), ('yard', 'yard', 500 * mib, 30), ('paused', 'paused', 0, 1)])
        self.assertNotIn('rtsp', json.dumps(data))
        # La durée réglée ne tient pas : (60 100 + 300 000) / 36 000 par jour = 10 jours atteints.
        self.frigate.disk = {'total': 1000000.0, 'used': 700000.0, 'free': 300000.0}
        data = self.get('/api/cameras/storage')[1]
        self.assertEqual((data['state'], data['hours'], data['reach_days']), ('short', 200.0, 10.0))
        self.frigate.disk = {'total': 1000000.0, 'used': 999000.0, 'free': 1000.0}
        data = self.get('/api/cameras/storage')[1]
        self.assertEqual((data['state'], data['hours']), ('full', 0.7))
        # Un volume saturé oscille sous deux heures et quelques : il reste « plein » sur toute cette plage.
        self.frigate.disk = {'total': 1000000.0, 'used': 996000.0, 'free': 4000.0}
        self.assertEqual(self.get('/api/cameras/storage')[1]['state'], 'full')
        self.frigate.disk = {'total': 1000000.0, 'used': 995000.0, 'free': 5000.0}
        self.assertEqual(self.get('/api/cameras/storage')[1]['state'], 'short')
        self.frigate.usage = {}
        data = self.get('/api/cameras/storage')[1]
        self.assertEqual((data['state'], data['rate'], data['hours'], data['needed']), ('unknown', None, None, None))
        for disk in ({'total': 0, 'free': 0}, {'total': 10.0, 'free': 20.0}, {'total': 'x', 'free': 1.0}, {'total': float('inf'), 'free': 1.0}, None):
            self.frigate.disk = disk
            self.assertEqual(self.get('/api/cameras/storage')[1], {'available': False}, disk)

    def test_storage_incident_opens_with_margin_and_closes_only_when_filled(self):
        self.configure({'entry': {'record': {'continuous': {'days': 10}}}})
        # 1 000 Mio/h pendant 10 jours : 240 000 Mio à terme, dont 40 000 déjà pris.
        self.frigate.usage = {'entry': {'usage': 40000.0, 'bandwidth': 1000.0}}
        def measured(free, active=False):
            self.frigate.disk = {'total': 1000000.0, 'free': float(free)}
            return kept.conditions(app, active=active)
        self.assertEqual(measured(600000), [])
        # Manque de 5 % : pas d'incident ouvert pour si peu, mais un incident ouvert ne se referme pas encore.
        self.assertEqual(measured(188000), [])
        self.assertEqual([c[0::4] for c in measured(188000, active=True)], [('video:storage', 'warning')])
        self.assertEqual(measured(200000, active=True), [])
        found = measured(150000)
        self.assertEqual([(c[0], c[3], c[4], c[5]) for c in found], [('video:storage', 'camera', 'warning', 'short')])
        self.assertIn('ne tient pas', found[0][1]); self.assertIn('Stockage vidéo', found[0][2])
        found = measured(2500)
        self.assertEqual([(c[0], c[4], c[5]) for c in found], [('video:storage', 'critical', 'full')])
        self.assertIn('passages conservés ne sont pas touchés', found[0][2])
        # Mesure absente ou débit inconnu : rien n'est déduit, ni incident ni retour à la normale.
        self.frigate.usage = {}
        self.assertIsNone(measured(2500))
        self.frigate.disk = None
        self.assertIsNone(kept.conditions(app))
        # Des mesures déjà lues ne sont pas redemandées, et les passages conservés ne sont pas pesés pour une alerte.
        self.frigate.usage = {'entry': {'usage': 40000.0, 'bandwidth': 1000.0}}; self.frigate.gets.clear()
        stats = {'service': {'storage': {kept.RECORDINGS: {'total': 1000000.0, 'free': 600000.0}}}}
        self.assertEqual(kept.conditions(app, stats), [])
        self.assertEqual(self.frigate.gets, ['/api/recordings/storage'])


if __name__ == '__main__':
    unittest.main()
