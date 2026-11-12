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

    def frigate(self, summary, segments, events=None):
        calls = []
        def video_get(path, **kwargs):
            calls.append(path)
            if path.startswith('/api/events'):
                return io.BytesIO(json.dumps([] if events is None else events).encode())
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
        self.assertEqual(calls, ['/api/entry/recordings/summary?timezone=America/Cayenne', f'/api/entry/recordings?after={start}&before={start + 86400}',
                                 f'/api/events?cameras=entry&after={start}&before={start + 86400}&limit=1001&include_thumbnails=0&sort=date_asc'])
        self.assertEqual((data['events'], data['events_more']), ([], False))
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

    def test_events_are_bounded_to_the_day_and_camera(self):
        self.configure(); now = time.time()
        yesterday = datetime.datetime.now(self.zone).date() - datetime.timedelta(days=1); start = self.midnight(yesterday)
        event = lambda offset, **more: {'id': f'{start + offset:.6f}-abc123', 'camera': 'entry', 'label': 'person', 'start_time': start + offset, 'end_time': start + offset + 12,
                                        'sub_label': None, 'thumbnail': 'private-fixture', 'data': {'top_score': 0.7734, 'score': 0.5, 'path_data': [[0.1, 0.2]]}, **more}
        events = [event(7200, label='car', sub_label=['Voisin', 0.9], data={'score': 0.61}), event(3600), event(9000, end_time=None, data={}, top_score=2),
                  event(100, camera='garage'), event(200, id='../../config'), event(300, id='1.5-ABC'), event(400, label=''), event(500, label=7), event(600, label='x' * 65),
                  event(-50), event(86400), event(700, start_time='x'), event(800, end_time='x'), event(900, end_time=start + 10), None, 'x']
        context, _ = self.frigate([{'day': yesterday.isoformat(), 'hours': [{'duration': 60}]}], [], events)
        with context:
            status, data = self.get('/api/camera/timeline?camera=entry&day=' + yesterday.isoformat())
        self.assertEqual(status, 200)
        self.assertEqual([(e['label'], e['start'] - start, e['end'] - e['start'], e['ongoing'], e['score'], e['sub_label']) for e in data['events'][:2]],
                         [('person', 900, 0, False, 77, None), ('person', 3600, 12, False, 77, None)])
        self.assertEqual([(e['label'], e['score'], e['sub_label'], e['ongoing']) for e in data['events'][2:]], [('car', 61, 'Voisin', False), ('person', None, None, True)])
        self.assertAlmostEqual(data['events'][3]['end'], now, delta=30)
        self.assertEqual(data['events'][1]['id'], f'{start + 3600:.6f}-abc123')
        self.assertEqual(set(data['events'][0]), {'id', 'label', 'sub_label', 'start', 'end', 'ongoing', 'score'})
        for private in ('private-fixture', 'path_data', 'garage', 'config'):
            self.assertNotIn(private, json.dumps(data['events']))
        # Au-delà du plafond, la journée reste lisible et l'excédent est signalé.
        context, _ = self.frigate([], [], [event(3600 + i) | {'id': f'{int(start) + i}.5-abc{i}'} for i in range(4)])
        with patch.object(playback, 'EVENT_MAX', 3), context:
            data = playback.timeline(app, 'entry', yesterday.isoformat())
        self.assertEqual((len(data['events']), data['events_more']), (3, True))

    def test_missing_events_do_not_break_the_timeline(self):
        self.configure()
        yesterday = datetime.datetime.now(self.zone).date() - datetime.timedelta(days=1); start = self.midnight(yesterday)
        segments = [{'start_time': start + 60, 'end_time': start + 120, 'objects': 1}]
        def failing(path, **kwargs):
            if path.startswith('/api/events'):
                raise app.Problem('La vidéo est temporairement indisponible.', 503)
            return io.BytesIO(json.dumps([] if '/summary' in path else segments).encode())
        with patch.object(app, 'video_get', side_effect=failing):
            status, data = self.get('/api/camera/timeline?camera=entry&day=' + yesterday.isoformat())
        self.assertEqual((status, data['events'], data['events_more'], data['intervals']), (200, None, False, [[start + 60, start + 120]]))
        for payload in ({'detail': 'private failure'}, 'x', 7):
            context, _ = self.frigate([], segments, payload)
            with context:
                data = playback.timeline(app, 'entry', yesterday.isoformat())
            self.assertEqual((data['events'], data['detections']), (None, [[start + 60, start + 120]]))

    def test_thumbnail_requires_an_event_of_the_camera(self):
        self.configure(); ident = '1794482122.153544-ee4mim'
        with patch.object(app, 'video_get') as video:
            for bad in ('', '../../config/config.yml', ident + '/snapshot.jpg', ident.upper(), 'abc', ident + '?x=1', '1' * 13 + '-a'):
                status, data = self.get('/api/camera/event-thumbnail?camera=entry&id=' + bad)
                self.assertEqual((status, data['error']), (400, 'Identifiant d’événement invalide.'), bad)
            self.assertEqual(self.get('/api/camera/event-thumbnail?camera=entry')[0], 400)
            self.assertEqual(self.get('/api/camera/event-thumbnail?camera=absent&id=' + ident)[0], 404)
            video.assert_not_called()
        self.assertEqual(self.request('GET', '/api/camera/event-thumbnail?camera=entry&id=' + ident)[0], 401)
        calls = []
        def video_get(path, **kwargs):
            calls.append(path)
            return io.BytesIO(b'synthetic-jpeg' if path.endswith('.jpg') else json.dumps(owner).encode())
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        reader, _ = app.make_session('reader')
        with patch.object(app, 'video_get', side_effect=video_get):
            for owner in ({'id': ident, 'camera': 'garage'}, {'id': 'autre', 'camera': 'entry'}, {'success': False}, [], 'x'):
                status, data = self.get('/api/camera/event-thumbnail?camera=entry&id=' + ident)
                self.assertEqual((status, data['error']), (404, 'Événement inconnu pour cette caméra.'))
            self.assertEqual(calls, [f'/api/events/{ident}'] * 5)
            owner = {'id': ident, 'camera': 'entry', 'thumbnail': 'private-fixture'}; calls.clear()
            conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
            conn.request('GET', '/api/camera/event-thumbnail?camera=entry&id=' + ident, headers={'Cookie': 'nas_session=' + reader})
            response = conn.getresponse(); body = response.read(); conn.close()
            self.assertEqual((response.status, response.getheader('Content-Type'), response.getheader('Cache-Control'), body), (200, 'image/jpeg', 'no-store', b'synthetic-jpeg'))
            self.assertEqual(calls, [f'/api/events/{ident}', f'/api/events/{ident}/thumbnail.jpg'])
        with patch.object(app, 'video_get', side_effect=app.Problem('La vidéo est temporairement indisponible.', 503)):
            self.assertEqual(self.get('/api/camera/event-thumbnail?camera=entry&id=' + ident)[0], 503)

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
