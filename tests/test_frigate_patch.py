"""Build guards; full runtime race/IPC tests run in the isolated Frigate image."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frigate'))
import patch_websocket as fix


class FrigatePatchTests(unittest.TestCase):
    def test_unknown_source_is_rejected_before_editing(self):
        for source in (b'', b'class NewImplementation: pass\n'):
            with self.assertRaisesRegex(RuntimeError, 'Unsupported Frigate'):
                fix.patched(source)

    def test_verified_handler_changes_only_expected_catch(self):
        source = ('def publish():\n    for ws in []:\n        if True:\n'
                  '            try:\n                ws.send("fixture")\n' + fix.BEFORE).encode()
        with patch.object(fix, 'UPSTREAM_SHA256', hashlib.sha256(source).hexdigest()):
            result = fix.patched(source)
        self.assertEqual(result.replace(fix.AFTER.encode(), fix.BEFORE.encode()), source)
        with self.assertRaisesRegex(RuntimeError, 'Unsupported Frigate'):
            fix.patched(result)

    def test_verified_but_missing_or_ambiguous_handler_fails(self):
        for source in (b'pass\n', (fix.BEFORE * 2).encode()):
            with patch.object(fix, 'UPSTREAM_SHA256', hashlib.sha256(source).hexdigest()):
                with self.assertRaisesRegex(RuntimeError, 'exactly once'):
                    fix.patched(source)
