"""Préférences du bureau par compte : lecture tolérante, écriture stricte, sur base et serveur HTTP temporaires."""
import json
import unittest

import test_onboarding as base
import desk_prefs

server = base.server


class DeskPreferenceTests(unittest.TestCase):
    setUp = base.OnboardingTests.setUp
    tearDown = base.OnboardingTests.tearDown
    request = base.OnboardingTests.request

    def reader(self):
        with server.database() as db:
            db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        return server.make_session('reader')

    def get(self, token=None):
        status, raw = self.request('GET', '/api/desk', token=token or self.token)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)

    def stored(self):
        with server.database() as db:
            return {row[0]: row[1] for row in db.execute("SELECT key,value FROM settings WHERE key LIKE 'desk:%'")}

    def test_each_account_keeps_its_own_desktop_and_a_reader_can_only_write_this(self):
        default = {'widgets': list(desk_prefs.DEFAULT), 'background': 'nacre', 'catalog': list(desk_prefs.WIDGETS), 'backgrounds': list(desk_prefs.BACKGROUNDS)}
        self.assertEqual(self.get(), default); self.assertEqual(self.stored(), {})
        self.assertEqual(self.request('GET', '/api/desk')[0], 401)
        choice = {'widgets': ['tasks', 'storage'], 'background': 'lagon'}
        status, raw = self.request('POST', '/api/desk', choice, self.token, self.csrf)
        self.assertEqual(status, 200, raw); self.assertEqual(json.loads(raw), {**default, **choice})
        self.assertEqual(self.get(), {**default, **choice})
        self.assertEqual(self.stored(), {'desk:admin': json.dumps(choice)})
        # Aucune ligne de journal pour un réglage d'affichage.
        with server.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action LIKE '%ureau%'").fetchone()[0], 0)
        token, csrf = self.reader()
        self.assertEqual(self.get(token), default)
        own = {'widgets': [], 'background': 'ardoise'}
        self.assertEqual(self.request('POST', '/api/desk', own, token, csrf)[0], 200)
        self.assertEqual((self.get(token)['widgets'], self.get(token)['background'], self.get()['background']), ([], 'ardoise', 'lagon'))
        self.assertEqual(self.request('POST', '/api/desk', own, token)[0], 403)
        self.assertEqual(self.request('POST', '/api/desk', own, token, csrf, 'https://other.invalid')[0], 403)
        # L'exception ne vaut que pour cette route : un lecteur n'écrit toujours rien d'autre.
        for route, body in (('/api/folder', {'name': 'x'}), ('/api/move', {'path': '', 'names': ['x'], 'target': 'y'}), ('/api/control-panel/configure', {})):
            self.assertEqual(self.request('POST', route, body, token, csrf)[0], 403, route)

    def test_invalid_choices_are_refused_and_damaged_values_fall_back_to_the_default(self):
        before = {'widgets': ['memory'], 'background': 'sable'}
        self.assertEqual(self.request('POST', '/api/desk', before, self.token, self.csrf)[0], 200)
        for body in ({'widgets': ['storage', 'storage'], 'background': 'nacre'}, {'widgets': ['unknown'], 'background': 'nacre'}, {'widgets': 'storage', 'background': 'nacre'},
                     {'widgets': [1], 'background': 'nacre'}, {'widgets': list(desk_prefs.WIDGETS) + ['storage'], 'background': 'nacre'}, {'widgets': [], 'background': 'rose'},
                     {'widgets': [], 'background': None}, {'widgets': []}, {'background': 'nacre'}, {'widgets': [], 'background': 'nacre', 'script': '<script>'}, {}):
            status, raw = self.request('POST', '/api/desk', body, self.token, self.csrf)
            self.assertEqual(status, 400, body)
        self.assertEqual(self.stored(), {'desk:admin': json.dumps(before)})
        for value, expected in (('{illisible', (list(desk_prefs.DEFAULT), 'nacre')), ('[]', (list(desk_prefs.DEFAULT), 'nacre')),
                                (json.dumps({'widgets': ['tasks', 'x', 'tasks', 7], 'background': '<b>'}), (['tasks'], 'nacre')), (json.dumps({'widgets': 'memory'}), (list(desk_prefs.DEFAULT), 'nacre'))):
            with server.database() as db:
                db.execute("UPDATE settings SET value=? WHERE key='desk:admin'", (value,))
            answer = self.get()
            self.assertEqual((answer['widgets'], answer['background']), expected, value)


if __name__ == '__main__':
    unittest.main()
