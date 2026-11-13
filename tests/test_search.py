"""Recherche d'événements sur plusieurs jours, sur un Frigate simulé : aucune caméra, vidéo ou Docker."""
import datetime
import io
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_playback as base
import playback

app = base.app


class SearchTests(unittest.TestCase):
    setUp = base.PlaybackTests.setUp
    tearDown = base.PlaybackTests.tearDown
    request = base.PlaybackTests.request
    configure = base.PlaybackTests.configure
    midnight = base.PlaybackTests.midnight
    get = base.PlaybackTests.get

    def day(self, offset):
        return datetime.datetime.now(self.zone).date() - datetime.timedelta(days=offset)

    def event(self, offset, seconds, label='person', **more):
        start = self.midnight(self.day(offset)) + seconds
        return {'id': f'{start:.6f}-abc123', 'camera': 'entry', 'label': label, 'start_time': start, 'end_time': start + 12, 'sub_label': None,
                'thumbnail': 'private-fixture', 'has_clip': True, 'data': {'top_score': 0.81, 'path_data': [[0.1, 0.2]]}, **more}

    def frigate(self, events, summary=None):
        """Applique les filtres que Nacre demande à Frigate : bornes strictes, types, tri décroissant, limite."""
        calls = []
        def video_get(path, **kwargs):
            calls.append(path)
            url = urlsplit(path); query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path != '/api/events':
                if summary is None:
                    raise app.Problem('La vidéo est temporairement indisponible.', 503)
                return io.BytesIO(json.dumps(summary).encode())
            self.assertEqual((query['cameras'], query['sort'], query['include_thumbnails']), ('entry', 'date_desc', '0'))
            labels = query.get('labels', 'all').split(',')
            found = [e for e in events if isinstance(e, dict) and isinstance(e.get('start_time'), (int, float))
                     and float(query['after']) < e['start_time'] < float(query['before']) and (labels == ['all'] or e.get('label') in labels)]
            found.sort(key=lambda e: -e['start_time'])
            rest = [e for e in events if not isinstance(e, dict) or not isinstance(e.get('start_time'), (int, float))]
            return io.BytesIO(json.dumps((rest + found)[:int(query['limit'])]).encode())
        return patch.object(app, 'video_get', side_effect=video_get), calls

    def test_period_counts_types_days_and_recorded_hours(self):
        self.configure(); before = self.config.read_bytes()
        events = [self.event(0, 60), self.event(1, 3 * 3600 + 5, 'car', sub_label=['Voisin', 0.9]), self.event(1, 9 * 3600), self.event(3, 7200, 'dog'),
                  self.event(6, 100), self.event(7, 100), self.event(2, 50, camera='garage'), self.event(2, 60, id='../../config'), self.event(2, 70, label=''), None, 'x']
        summary = [{'day': self.day(1).isoformat(), 'hours': [{'hour': '03', 'duration': 3600}, {'hour': '09', 'duration': 0}]},
                   {'day': self.day(0).isoformat(), 'hours': [{'hour': '00', 'duration': 120}]}]
        context, calls = self.frigate(events, summary)
        with context:
            status, data = self.get('/api/camera/search?camera=entry')
        self.assertEqual(status, 200)
        # Sept jours civils par défaut, aujourd'hui compris : l'événement d'il y a sept jours est hors période.
        self.assertEqual((data['from'], data['to'], data['today'], data['label'], data['next']), (self.day(6).isoformat(), self.day(0).isoformat(), self.day(0).isoformat(), '', None))
        self.assertEqual([(e['label'], e['day'], e['recorded'], e['sub_label'], e['score']) for e in data['events']],
                         [('person', self.day(0).isoformat(), True, None, 81), ('person', self.day(1).isoformat(), False, None, 81),
                          ('car', self.day(1).isoformat(), True, 'Voisin', 81), ('dog', self.day(3).isoformat(), False, None, 81), ('person', self.day(6).isoformat(), False, None, 81)])
        self.assertEqual(data['facets'], {'total': 5, 'matched': 5, 'more': False,
                         'types': [{'label': 'person', 'count': 3}, {'label': 'car', 'count': 1}, {'label': 'dog', 'count': 1}],
                         'days': [{'day': self.day(0).isoformat(), 'count': 1}, {'day': self.day(1).isoformat(), 'count': 2}, {'day': self.day(3).isoformat(), 'count': 1}, {'day': self.day(6).isoformat(), 'count': 1}]})
        self.assertEqual(set(data['events'][0]), {'id', 'label', 'sub_label', 'start', 'end', 'ongoing', 'score', 'day', 'recorded'})
        for private in ('private-fixture', 'path_data', 'garage', 'config', 'has_clip'):
            self.assertNotIn(private, json.dumps(data))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.config.read_bytes(), before)
        # Un type choisi garde les compteurs de tous les types et ne compte les jours que pour lui.
        with context:
            status, data = self.get(f'/api/camera/search?camera=entry&from={self.day(3).isoformat()}&to={self.day(1).isoformat()}&label=person')
        self.assertEqual((status, [e['label'] for e in data['events']], data['facets']['total'], data['facets']['matched'], data['facets']['days']),
                         (200, ['person'], 3, 1, [{'day': self.day(1).isoformat(), 'count': 1}]))
        self.assertEqual([t['label'] for t in data['facets']['types']], ['car', 'dog', 'person'])

    def test_pages_follow_each_other_without_gap_or_repeat(self):
        self.configure()
        events = [self.event(i % 5, 3600 + i * 37, 'car' if i % 3 == 0 else 'person') for i in range(23)]
        context, calls = self.frigate(events, [])
        for label, expected in (('', 23), ('car', 8)):
            seen, cursor, facets = [], None, None
            with patch.object(playback, 'SEARCH_PAGE', 5), context:
                for _ in range(8):
                    data = playback.search(app, 'entry', {'label': label} | ({} if cursor is None else {'before': str(cursor)}))
                    self.assertLessEqual(len(data['events']), 5)
                    self.assertEqual(data['facets'] is None, cursor is not None)
                    facets = facets or data['facets']; seen += data['events']; cursor = data['next']
                    if cursor is None:
                        break
            self.assertEqual(len(seen), expected)
            self.assertEqual([e['start'] for e in seen], sorted({e['start'] for e in seen}, reverse=True))
            self.assertEqual((facets['total'], facets['matched']), (23, expected))
            # Sans résumé d'enregistrements exploitable pour ces heures, les événements sont annoncés sans vidéo.
            self.assertTrue(all(e['recorded'] is False for e in seen))
        # Les pages suivantes filtrent dans Frigate, sans relire toute la période.
        self.assertTrue(any('labels=car' in c and f'limit=6' in c for c in calls))

    def test_simultaneous_events_are_never_split_between_two_pages(self):
        self.configure()
        # Deux objets vus sur la même image partagent leur instant de début : Frigate les distingue par l'identifiant seul.
        events = []
        for i in range(9):
            for suffix in ('aaa111', 'bbb222') if i % 2 else ('aaa111',):
                item = self.event(1, 3600 + i * 60); item['id'] = f"{item['start_time']:.6f}-{suffix}"; events.append(item)
        context, _ = self.frigate(events, [])
        for size in (2, 3, 4, 5):
            seen, cursor = [], None
            with patch.object(playback, 'SEARCH_PAGE', size), context:
                for _ in range(20):
                    data = playback.search(app, 'entry', {} if cursor is None else {'before': str(cursor)})
                    seen += data['events']; cursor = data['next']
                    if cursor is None:
                        break
            self.assertEqual((len(seen), len({e['id'] for e in seen})), (13, 13), size)
        with patch.object(playback, 'SEARCH_PAGE', 3), patch.object(playback, 'SEARCH_COUNTED', 4), context:
            seen, cursor = [], None
            for _ in range(20):
                data = playback.search(app, 'entry', {} if cursor is None else {'before': str(cursor)})
                seen += data['events']; cursor = data['next']
                if cursor is None:
                    break
        self.assertEqual(len({e['id'] for e in seen}), 13)

    def test_counting_is_capped_and_the_rest_stays_reachable(self):
        self.configure()
        events = [self.event(1, 3600 + i * 60, 'car' if i < 4 else 'person') for i in range(12)]
        context, _ = self.frigate(events)
        with patch.object(playback, 'SEARCH_PAGE', 5), patch.object(playback, 'SEARCH_COUNTED', 6), context:
            first = playback.search(app, 'entry', {'label': 'car'})
            # Les six plus récents sont tous des personnes : aucune voiture comptée, mais la suite est proposée.
            self.assertEqual((first['events'], first['facets']['total'], first['facets']['matched'], first['facets']['more']), ([], 6, 0, True))
            self.assertIsNotNone(first['next'])
            following = playback.search(app, 'entry', {'label': 'car', 'before': str(first['next'])})
        self.assertEqual(([e['label'] for e in following['events']], following['next']), (['car'] * 4, None))
        # Résumé d'enregistrements indisponible : pas d'indice, la relecture du jour tranchera.
        self.assertTrue(all(e['recorded'] is True for e in following['events']))

    def test_time_slot_keeps_events_started_in_it_on_every_day_and_across_midnight(self):
        self.configure(); hour = 3600
        events = [self.event(1, 30 * 60), self.event(1, 22 * hour), self.event(1, 3 * hour + 5, 'car'), self.event(1, 9 * hour), self.event(2, 22 * hour - 1),
                  self.event(2, 6 * hour), self.event(3, 6 * hour - 60, 'dog'), self.event(4, 12 * hour, 'car')]
        context, calls = self.frigate(events, [])
        night = '/api/camera/search?camera=entry&time_from=22:00&time_to=06:00'
        with context:
            status, data = self.get(night)
        # La nuit enjambe minuit : 22:00 compris, 06:00 exclu, chaque jour de la période.
        self.assertEqual(status, 200, data)
        self.assertEqual([(e['label'], e['day'], round(e['start'] - self.midnight(self.day(int((self.day(0) - datetime.date.fromisoformat(e['day'])).days))))) for e in data['events']],
                         [('person', self.day(1).isoformat(), 22 * hour), ('car', self.day(1).isoformat(), 3 * hour + 5), ('person', self.day(1).isoformat(), 30 * 60), ('dog', self.day(3).isoformat(), 6 * hour - 60)])
        self.assertEqual((data['hours'], data['next']), ({'from': '22:00', 'to': '06:00'}, None))
        # Les compteurs ne portent que sur la tranche : types et jours.
        self.assertEqual(data['facets'], {'total': 4, 'matched': 4, 'more': False, 'types': [{'label': 'person', 'count': 2}, {'label': 'car', 'count': 1}, {'label': 'dog', 'count': 1}],
                                          'days': [{'day': self.day(1).isoformat(), 'count': 3}, {'day': self.day(3).isoformat(), 'count': 1}]})
        with context:
            status, typed = self.get(night + '&label=car')
            self.assertEqual((status, [e['label'] for e in typed['events']], typed['facets']['total'], typed['facets']['matched']), (200, ['car'], 4, 1))
            # La tranche complémentaire, sans enjamber minuit, garde tout le reste et rien d'autre.
            status, day = self.get('/api/camera/search?camera=entry&time_from=06:00&time_to=22:00')
            self.assertEqual((status, len(day['events']), day['facets']['total'], day['hours']), (200, 4, 4, {'from': '06:00', 'to': '22:00'}))
            self.assertEqual({e['id'] for e in day['events']} & {e['id'] for e in data['events']}, set())
            status, whole = self.get('/api/camera/search?camera=entry')
            self.assertEqual((status, len(whole['events']), whole['hours']), (200, 8, None))
        # Frigate n'est jamais interrogé par heure : le filtre est appliqué par Nacre, dans son fuseau.
        self.assertFalse(any('time_' in call for call in calls))
        with patch.object(app, 'video_get') as video:
            for query in ('time_from=22:00', 'time_to=06:00', 'time_from=22:00&time_to=22:00', 'time_from=24:00&time_to=06:00', 'time_from=6:00&time_to=22:00',
                          'time_from=22h&time_to=06h', 'time_from=22:00&time_to=06:60', 'time_from=22:00%0A&time_to=06:00'):
                status, refused = self.get('/api/camera/search?camera=entry&' + query)
                self.assertEqual(status, 400, query); self.assertIn('Tranche horaire invalide', refused['error'])
            video.assert_not_called()

    def test_time_slot_pages_follow_each_other_even_when_frigate_pages_hold_nothing_of_it(self):
        self.configure(); hour = 3600
        # Par jour : vingt événements de nuit (01:00) et trente de jour (10:00), sur quatre jours.
        events = [self.event(d, hour + i * 20, 'car' if i % 4 == 0 else 'person') for d in range(1, 5) for i in range(20)] + [self.event(d, 10 * hour + i * 20) for d in range(1, 5) for i in range(30)]
        context, calls = self.frigate(events, [])
        for counted, label, expected in ((10000, '', 80), (25, '', 80), (25, 'car', 20)):
            seen, cursor, first = [], None, None
            with patch.object(playback, 'SEARCH_PAGE', 7), patch.object(playback, 'SEARCH_COUNTED', counted), context:
                for _ in range(60):
                    data = playback.search(app, 'entry', {'time_from': '00:30', 'time_to': '05:00', 'label': label} | ({} if cursor is None else {'before': str(cursor)}))
                    self.assertLessEqual(len(data['events']), 7); self.assertEqual(data['hours'], {'from': '00:30', 'to': '05:00'})
                    first = first or data; seen += data['events']; cursor = data['next']
                    if cursor is None:
                        break
            self.assertIsNone(cursor, (counted, label))
            self.assertEqual(len(seen), expected, (counted, label))
            self.assertEqual([e['start'] for e in seen], sorted({e['start'] for e in seen}, reverse=True))
            self.assertTrue(all(label in ('', e['label']) for e in seen))
            # Compteurs plafonnés : seuls les événements lus sont comptés, et c'est annoncé.
            self.assertEqual((first['facets']['more'], first['facets']['total']), (False, 80) if counted == 10000 else (True, 0))

    def test_invalid_requests_are_refused_before_frigate(self):
        self.configure(); today, old = self.day(0), self.day(playback.HISTORY_DAYS + 1)
        with patch.object(app, 'video_get') as video:
            for query, message in ((f'from={today}&to={self.day(2)}', 'Période invalide : le début suit la fin.'), ('from=2026-13-40', 'Date invalide. Format attendu : AAAA-MM-JJ.'),
                                   ('to=demain', 'Date invalide. Format attendu : AAAA-MM-JJ.'), (f'to={self.day(-1)}', 'Date hors de la période consultable.'),
                                   (f'from={old}', 'Date hors de la période consultable.'), ('label=Person', 'Type d’objet invalide.'), ('label=car,person', 'Type d’objet invalide.'),
                                   ('label=x%26cameras%3Dgarage', 'Type d’objet invalide.'), ('before=abc', 'Position de recherche invalide.'), ('before=nan', 'Position de recherche invalide.'),
                                   ('before=1', 'Position de recherche invalide.'), (f'before={time.time() + 3600}', 'Position de recherche invalide.')):
                status, data = self.get('/api/camera/search?camera=entry&' + query)
                self.assertEqual((status, data['error']), (400, message), query)
            self.assertEqual(self.get('/api/camera/search?camera=absent')[0], 404)
            video.assert_not_called()
        self.assertEqual(self.request('GET', '/api/camera/search?camera=entry')[0], 401)

    def test_viewers_can_search_and_an_unavailable_service_is_reported(self):
        self.configure()
        with app.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        reader, _ = app.make_session('reader')
        context, _ = self.frigate([self.event(0, 60)], [])
        with context:
            status, data = self.get('/api/camera/search?camera=entry', token=reader)
        self.assertEqual((status, len(data['events'])), (200, 1))
        with patch.object(app, 'video_get', side_effect=app.Problem('La vidéo est temporairement indisponible.', 503)):
            status, data = self.get('/api/camera/search?camera=entry')
        self.assertEqual((status, data['error']), (503, playback.SEARCH_UNAVAILABLE))
        for payload in ({'detail': 'private failure'}, 'x', 7):
            with patch.object(app, 'video_get', side_effect=lambda path, **kwargs: io.BytesIO(json.dumps(payload).encode())):
                status, data = self.get('/api/camera/search?camera=entry')
            self.assertEqual((status, data['error']), (503, playback.SEARCH_UNAVAILABLE))
            self.assertNotIn('private', json.dumps(data))


if __name__ == '__main__':
    unittest.main()
