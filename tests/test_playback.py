"""Relecture par jour sur inventaire Frigate simulé : aucune caméra, vidéo ou Docker."""
import datetime
import http.client
import io
import json
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_components_cameras as base
import onboarding
import playback

app = base.server


class PlaybackTests(unittest.TestCase):
    setUp = base.ComponentsCameraTests.setUp
    tearDown = base.ComponentsCameraTests.tearDown
    request = base.ComponentsCameraTests.request

    def configure(self, timezone='America/Cayenne'):
        config = {'cameras': {'entry': {'friendly_name': 'Entrée', 'record': {'continuous': {'days': 2}},
                  'onvif': {'host': '192.168.50.20', 'password': 'private-fixture'}, 'ffmpeg': {'inputs': [{'path': 'rtsp://private-fixture'}]}}}}
        app.private_write(self.config, json.dumps(config))
        with app.database() as db:
            onboarding.write(db, {'phase': 'complete', 'name': 'Banc', 'timezone': timezone, 'existing': False})
        self.zone = ZoneInfo(timezone)

    def midnight(self, day):
        return datetime.datetime(day.year, day.month, day.day, tzinfo=self.zone).timestamp()

    def frigate(self, summary, segments):
        calls = []
        def video_get(path, **kwargs):
            calls.append(path)
            return io.BytesIO(json.dumps(summary if '/summary' in path else segments).encode())
        return patch.object(app, 'video_get', side_effect=video_get), calls

    def get(self, path, token=None):
        status, data = self.request('GET', path, token=token or self.token)
        return status, json.loads(data)

    def test_day_is_merged_clipped_and_read_only(self):
        self.configure(); before = self.config.read_bytes()
        today = datetime.datetime.now(self.zone).date(); yesterday = today - datetime.timedelta(days=1)
        start = self.midnight(yesterday)
        segments = [{'start_time': start - 4, 'end_time': start + 6, 'objects': 0}]
        segments += [{'start_time': start + 6 + i * 10, 'end_time': start + 16 + i * 10, 'objects': 2 if 3 <= i < 6 else 0, 'motion_heatmap': {'1': 2}} for i in range(12)]
        segments += [{'start_time': start + 7200, 'end_time': start + 7260, 'objects': 0}, {'start_time': start + 7261.5, 'end_time': start + 7300, 'objects': True}]
        segments += [None, {'start_time': 'x', 'end_time': 3}, {'start_time': start + 50, 'end_time': float('nan')}, {'start_time': start + 90, 'end_time': start + 80}]
        summary = [{'day': yesterday.isoformat(), 'hours': [{'hour': '00', 'duration': 126}, {'hour': '02', 'duration': 98.5}, {'hour': '03', 'duration': -4}, 'x']},
                   {'day': 'private-fixture', 'hours': [{'duration': 5}]}, {'day': '2020-01-01', 'hours': []}, None]
        context, calls = self.frigate(summary, json.loads(json.dumps(segments).replace('NaN', '"nan"')))
        with context:
            status, data = self.get('/api/camera/timeline?camera=entry')
        self.assertEqual(status, 200)
        self.assertEqual(calls, ['/api/entry/recordings/summary?timezone=America/Cayenne', f'/api/entry/recordings?after={start}&before={start + 86400}'])
        self.assertEqual((data['day'], data['today'], data['timezone']), (yesterday.isoformat(), today.isoformat(), 'America/Cayenne'))
        self.assertEqual(data['days'], [{'day': yesterday.isoformat(), 'recorded': 224}])
        # Le segment à cheval sur minuit est borné au jour ; un écart de 1,5 s ne crée pas de trou.
        self.assertEqual(data['intervals'], [[start, start + 126], [start + 7200, start + 7300]])
        self.assertEqual(data['detections'], [[start + 36, start + 66]])
        self.assertEqual((data['recorded'], data['detected'], data['segments'], data['clip_max']), (226, 30, 15, 300))
        self.assertEqual(len(data['hours']), 24)
        self.assertEqual([(h['label'], h['recorded'], h['detected']) for h in data['hours'][:3]], [('00:00', 126, 30), ('01:00', 0, 0), ('02:00', 100, 0)])
        self.assertEqual(before, self.config.read_bytes())
        for private in ('private-fixture', 'rtsp://', '192.168.50.20', 'motion_heatmap'):
            self.assertNotIn(private, json.dumps(data))
        with app.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action LIKE 'Téléchargement%'").fetchone()[0], 0)

    def test_today_stops_at_now_and_empty_camera_stays_explicit(self):
        self.configure()
        context, calls = self.frigate([], [])
        with context:
            status, data = self.get('/api/camera/timeline?camera=entry')
        today = datetime.datetime.now(self.zone).date()
        self.assertEqual((status, data['day'], data['days'], data['intervals'], data['recorded']), (200, today.isoformat(), [], [], 0))
        after, before = (float(v) for v in calls[1].split('after=')[1].split('&before='))
        self.assertEqual(after, self.midnight(today)); self.assertLessEqual(before, time.time())
        self.assertLess(data['now'], data['end'])

    def test_daylight_saving_days_keep_true_hours(self):
        self.configure('Europe/Paris')
        for day, count, labels in (('2026-10-25', 25, ['01:00', '02:00', '02:00', '03:00']), ('2026-03-29', 23, ['01:00', '03:00', '04:00', '05:00'])):
            context, _ = self.frigate([], [])
            with context:
                data = playback.timeline(app, 'entry', day, now=datetime.datetime(2026, 11, 1, tzinfo=self.zone).timestamp())
            self.assertEqual(len(data['hours']), count)
            self.assertEqual([h['label'] for h in data['hours'][1:5]], labels)
            self.assertEqual(data['end'] - data['start'], count * 3600)
            self.assertEqual(data['hours'][-1]['end'], data['end'])

    def test_unknown_timezone_falls_back_to_utc(self):
        self.configure(); self.zone = datetime.timezone.utc
        with app.database() as db:
            onboarding.write(db, {'phase': 'complete', 'name': 'Banc', 'timezone': 'Mars/Olympus', 'existing': False})
        context, calls = self.frigate([], [])
        with context:
            data = playback.timeline(app, 'entry')
        self.assertEqual(data['timezone'], 'UTC'); self.assertIn('timezone=UTC', calls[0])

    def test_dates_are_validated_before_querying_video(self):
        self.configure()
        tomorrow = (datetime.datetime.now(self.zone).date() + datetime.timedelta(days=1)).isoformat()
        with patch.object(app, 'video_get') as video:
            for day, message in (('hier', 'Date invalide'), ('2026-13-01', 'Date invalide'), ('2026-02-30', 'Date invalide'), ('2026-1-1', 'Date invalide'),
                                 (tomorrow, 'hors de la période'), ('2001-01-01', 'hors de la période')):
                status, data = self.get('/api/camera/timeline?camera=entry&day=' + day)
                self.assertEqual(status, 400, day); self.assertIn(message, data['error'])
            self.assertEqual(self.get('/api/camera/timeline?camera=absent')[0], 404)
            self.assertEqual(self.get('/api/camera/timeline?camera=../etc')[0], 400)
            video.assert_not_called()

    def test_video_failures_are_reported_without_private_details(self):
        self.configure()
        with patch.object(app, 'video_get', side_effect=app.Problem('La vidéo est temporairement indisponible.', 503)):
            status, data = self.get('/api/camera/timeline?camera=entry')
            self.assertEqual((status, data['error']), (503, 'La vidéo est temporairement indisponible.'))
        with patch.object(app, 'video_get', side_effect=lambda path, **kwargs: io.BytesIO(b'<html>private failure')):
            status, data = self.get('/api/camera/timeline?camera=entry')
            self.assertEqual(status, 502); self.assertNotIn('private', data['error'])
        with patch.object(playback, 'MAX_BYTES', 64), patch.object(app, 'video_get', side_effect=lambda path, **kwargs: io.BytesIO(b'[' + b' ' * 80 + b']')):
            status, data = self.get('/api/camera/timeline?camera=entry')
            self.assertEqual(status, 502); self.assertIn('trop volumineux', data['error'])
        # Des formes inattendues ne deviennent ni des enregistrements ni une erreur serveur.
        for summary, segments in (({}, {}), ('x', 'x'), ([{'day': '2026-11-01'}], [[1, 2]])):
            context, _ = self.frigate(summary, segments)
            with context:
                status, data = self.get('/api/camera/timeline?camera=entry')
            self.assertEqual((status, data['days'], data['intervals']), (200, [], []))

    def test_viewer_reads_but_anonymous_does_not(self):
        self.configure()
        self.assertEqual(self.request('GET', '/api/camera/timeline?camera=entry')[0], 401)
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token, _ = app.make_session('reader')
        context, _ = self.frigate([], [])
        with context:
            self.assertEqual(self.get('/api/camera/timeline?camera=entry', token)[0], 200)

    def clip(self, query):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        conn.request('GET', '/api/camera/clip?camera=entry&' + query, headers={'Cookie': 'nas_session=' + self.token})
        response = conn.getresponse(); body = response.read(); conn.close()
        return response.status, response.getheader('Content-Disposition'), body

    def test_clip_bounds_download_name_and_audit(self):
        self.configure(); now = time.time(); start = int(now) - 7200
        class Upstream(io.BytesIO):
            status = 200; headers = {'Content-Type': 'video/mp4'}
        paths = []
        def video_get(path, **kwargs):
            paths.append(path); return Upstream(b'synthetic-video')
        with patch.object(app, 'video_get', side_effect=video_get):
            self.assertEqual(self.clip(f'start={start}&end={start + 300}'), (200, None, b'synthetic-video'))
            status, disposition, body = self.clip(f'start={start}&end={start + 30}&download=1')
            stamp = datetime.datetime.fromtimestamp(start, self.zone).strftime('%Y%m%d-%H%M%S')
            self.assertEqual((status, disposition, body), (200, f'attachment; filename="nacre-entry-{stamp}.mp4"', b'synthetic-video'))
            # Les anciens enregistrements restent lisibles jusqu'à la borne de conservation réglable.
            self.assertEqual(self.clip(f'start={now - 20 * 86400}&end={now - 20 * 86400 + 60}')[0], 200)
            count = len(paths)
            for query in (f'start={start}&end={start + 301}', f'start={start}&end={start}', f'start={start + 10}&end={start}', f'start={start}&end=nan',
                          f'start=inf&end=inf', f'start={now - 32 * 86400}&end={now - 32 * 86400 + 10}', f'start={now + 30}&end={now + 120}', 'start=abc&end=1', 'end=5'):
                self.assertEqual(self.clip(query)[0], 400, query)
            self.assertEqual(len(paths), count)
        self.assertEqual(paths[0], f'/api/entry/start/{float(start)}/end/{float(start + 300)}/clip.mp4')
        with app.database() as db:
            rows = [tuple(r) for r in db.execute("SELECT username,detail FROM audit WHERE action='Téléchargement d’extrait vidéo'")]
        self.assertEqual(rows, [('admin', f'nacre-entry-{stamp}.mp4')])


if __name__ == '__main__':
    unittest.main()
