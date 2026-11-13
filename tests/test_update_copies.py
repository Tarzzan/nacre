"""Copies de retour arrière des mises à jour : inventaire, règle automatique et suppression, sur un répertoire temporaire."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'console'))
import update_engine as engine
import update_copies as copies


def identifier(index):
    return f'{index:024x}'


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / 'nas'
        self.area = engine.area(self.root); self.area.mkdir(parents=True, mode=0o700)
        self.now = time.time()
        for name in ('runtime.py', 'trust.pub', 'baseline.json', 'heartbeat.json', 'child.json', 'supervisor.lock'):
            (self.area / name).write_text('{}')

    def tearDown(self):
        self.temp.cleanup()

    def folder(self, index, previous='1.0.0-alpha.1', version='1.0.0-alpha.2', age=0, copied=True, payload=1000):
        folder = self.area / identifier(index); (folder / 'before/console').mkdir(parents=True); (folder / 'code/console').mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps({'version': version, 'files': {}}))
        (folder / 'code/console/server.py').write_bytes(b'c' * payload)
        if copied:
            (folder / 'before/console/server.py').write_bytes(b'b' * payload); (folder / 'before.sqlite3').write_bytes(b'd' * payload)
            (folder / 'before.json').write_text(json.dumps({'version': previous, 'files': {}}))
        stamp = self.now - age
        os.utime(folder / ('before.json' if copied else '.'), (stamp, stamp))
        return folder

    def state(self, phase='succeeded', index=None):
        engine.save(self.area / 'status.json', {'phase': phase, **({'id': identifier(index)} if index is not None else {})})

    def names(self):
        return sorted(p.name for p in self.area.iterdir() if p.is_dir() and not p.is_symlink())

    def test_listing_orders_sizes_and_ignores_everything_else(self):
        self.folder(1, '0.8.0-alpha.20', '0.8.0-alpha.21', age=300); self.folder(2, '0.8.0-alpha.21', '0.8.0-alpha.22', age=200, payload=2000)
        self.folder(3, version='0.8.0-alpha.23', age=100, copied=False)
        damaged = self.folder(4, age=50); (damaged / 'manifest.json').write_text('<script>'); (damaged / 'before.json').write_text(json.dumps({'version': '../../etc'}))
        outside = Path(self.temp.name) / 'outside'; outside.mkdir(); (outside / 'witness').write_bytes(b'w' * 5000)
        (self.area / identifier(9)).symlink_to(outside, target_is_directory=True)
        (self.area / 'bytecode-0123').mkdir(); (self.area / ('g' * 24)).mkdir(); (self.area / identifier(8)).write_text('fichier')
        self.state('succeeded', 2)
        data = copies.listing(self.root)
        self.assertEqual([(i['id'], i['kind'], i['previous'], i['version'], i['current']) for i in data['items']],
                         [(identifier(4), 'copy', None, None, False), (identifier(3), 'prepared', None, '0.8.0-alpha.23', False),
                          (identifier(2), 'copy', '0.8.0-alpha.21', '0.8.0-alpha.22', True), (identifier(1), 'copy', '0.8.0-alpha.20', '0.8.0-alpha.21', False)])
        sizes = {i['id']: i['bytes'] for i in data['items']}
        self.assertEqual(sizes[identifier(2)], 6000 + len((self.area / identifier(2) / 'manifest.json').read_bytes()) + len((self.area / identifier(2) / 'before.json').read_bytes()))
        self.assertEqual((data['keep'], data['bytes']), (3, sum(sizes.values())))
        self.assertLess(data['bytes'], 5000 * 4)
        self.assertEqual(set(data['items'][0]), {'id', 'kind', 'version', 'previous', 'created', 'bytes', 'current'})
        # Sans répertoire de mises à jour : rien à lister et rien n'est créé.
        shutil.rmtree(self.area)
        self.assertEqual(copies.listing(self.root), {'keep': 3, 'bytes': 0, 'items': []})
        self.assertFalse(self.area.exists())

    def test_automatic_rule_keeps_recent_copies_and_the_current_folder(self):
        for index in range(1, 7):
            self.folder(index, f'1.0.0-alpha.{index}', f'1.0.0-alpha.{index + 1}', age=1000 - index * 100)
        self.folder(7, age=950, copied=False); self.folder(8, age=10, copied=False)
        stale = self.area / ('upload-' + 'a' * 24); stale.write_bytes(b'x'); os.utime(stale, (self.now - 7200, self.now - 7200))
        fresh = self.area / ('upload-' + 'b' * 24); fresh.write_bytes(b'x')
        outside = Path(self.temp.name) / 'outside'; outside.mkdir(); (outside / 'witness').write_text('gardé')
        (self.area / identifier(99)).symlink_to(outside, target_is_directory=True); (self.area / 'bytecode-0123').mkdir()
        others = {p.name: p.read_bytes() for p in self.area.iterdir() if p.is_file() and not p.name.startswith('upload-')}
        self.state('succeeded', 6)
        removed = copies.retain(self.root)
        self.assertEqual(sorted(i['id'] for i in removed), [identifier(i) for i in (1, 2, 3, 7, 8)])
        self.assertEqual(self.names(), [identifier(4), identifier(5), identifier(6), 'bytecode-0123'])
        self.assertEqual((stale.exists(), fresh.exists(), (outside / 'witness').read_text(), (self.area / identifier(99)).is_symlink()), (False, True, 'gardé', True))
        self.assertEqual({p.name: p.read_bytes() for p in self.area.iterdir() if p.is_file() and p.name not in (fresh.name, 'status.json', 'request.lock')},
                         {k: v for k, v in others.items() if k != 'status.json'})
        self.assertEqual(copies.retain(self.root), [])
        # Le dossier que l'état désigne reste, même ancien ou jamais installé : le superviseur peut encore en avoir besoin.
        self.folder(7, age=5000)
        for phase, current in (('rolled_back', 7), ('failed', 7), ('prepared', 8)):
            if current == 8:
                self.folder(8, age=1, copied=False)
            self.state(phase, current)
            self.assertNotIn(identifier(current), [i['id'] for i in copies.retain(self.root)])
            self.assertIn(identifier(current), self.names())

    def test_nothing_changes_while_an_update_is_engaged_or_being_prepared(self):
        for index in range(1, 6):
            self.folder(index, age=1000 - index * 100)
        before = self.names()
        for phase in sorted(engine.ACTIVE):
            self.state(phase, 5)
            with self.assertRaisesRegex(engine.UpdateError, 'Mise à jour en cours'):
                copies.retain(self.root)
            with self.assertRaisesRegex(engine.UpdateError, 'Mise à jour en cours'):
                copies.delete(self.root, identifier(1))
        self.state('succeeded', 5)
        with engine.guard(self.root):
            for action in (lambda: copies.retain(self.root), lambda: copies.delete(self.root, identifier(1))):
                with self.assertRaisesRegex(engine.UpdateError, 'déjà en cours'):
                    action()
            calls = []
            with patch.object(copies.time, 'sleep'):
                self.assertEqual(copies.tidy(SimpleNamespace(ROOT=self.root, audit=lambda *a: calls.append(a))), [])
            self.assertEqual(calls, [])
        self.assertEqual(self.names(), before)

    def test_manual_deletion_is_limited_to_known_folders_other_than_the_current_one(self):
        for index in (1, 2, 3):
            self.folder(index, f'1.0.0-alpha.{index}', f'1.0.0-alpha.{index + 1}', age=400 - index * 100)
        outside = Path(self.temp.name) / 'outside'; outside.mkdir(); (outside / 'witness').write_text('gardé')
        (self.area / identifier(9)).symlink_to(outside, target_is_directory=True)
        self.state('succeeded', 3)
        with self.assertRaisesRegex(engine.UpdateError, 'conservée jusqu’à la suivante'):
            copies.delete(self.root, identifier(3))
        for bad in (identifier(9), identifier(4), '../' + identifier(1), identifier(1) + '/before', 'status.json', 'runtime.py', '', None, 7, ['x'], 'ABCDEF' * 4, 'abcdef' * 4 + '\n'):
            with self.assertRaisesRegex(engine.UpdateError, 'introuvable'):
                copies.delete(self.root, bad)
        self.assertEqual((self.names(), (outside / 'witness').read_text()), ([identifier(1), identifier(2), identifier(3)], 'gardé'))
        item = copies.delete(self.root, identifier(1))
        self.assertEqual((item['previous'], item['version'], copies.label(item)), ('1.0.0-alpha.1', '1.0.0-alpha.2', 'Nacre 1.0.0-alpha.1, avant 1.0.0-alpha.2'))
        self.assertEqual(self.names(), [identifier(2), identifier(3)])
        # Suppression interrompue : le reste n'est plus présenté comme une copie et la règle automatique l'efface.
        with patch.object(copies.shutil, 'rmtree', side_effect=OSError('interrompu')):
            with self.assertRaisesRegex(engine.UpdateError, 'Suppression impossible'):
                copies.delete(self.root, identifier(2))
        self.assertEqual([(i['id'], i['kind']) for i in copies.listing(self.root)['items'] if not i['current']], [(identifier(2), 'prepared')])
        self.assertEqual([i['id'] for i in copies.retain(self.root)], [identifier(2)])
        self.assertEqual(self.names(), [identifier(3)])

    def test_tidy_reports_removed_copies_once_and_never_fails_its_caller(self):
        calls = []; app = SimpleNamespace(ROOT=self.root, audit=lambda *a: calls.append(a))
        for index in range(1, 6):
            self.folder(index, f'1.0.0-alpha.{index}', f'1.0.0-alpha.{index + 1}', age=1000 - index * 100)
        self.folder(6, copied=False, age=2000); self.state('succeeded', 5)
        self.assertEqual(len(copies.tidy(app)), 3)
        self.assertEqual(calls, [('console', 'Anciennes copies de mise à jour supprimées', 'Nacre 1.0.0-alpha.2, avant 1.0.0-alpha.3 ; Nacre 1.0.0-alpha.1, avant 1.0.0-alpha.2')])
        self.assertEqual((copies.tidy(app), len(calls)), ([], 1))
        # Un paquet abandonné seul ne mérite pas une ligne de journal.
        self.folder(7, copied=False); copies.tidy(app); self.assertEqual((len(calls), self.names()), (1, [identifier(3), identifier(4), identifier(5)]))
        (self.area / 'status.json').write_text('{illisible')
        self.assertEqual(copies.tidy(app), [])
        shutil.rmtree(self.area)
        self.assertEqual(copies.tidy(app), []); self.assertFalse(self.area.exists())


if __name__ == '__main__':
    unittest.main()
