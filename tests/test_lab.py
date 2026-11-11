import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import camera_config, initialize, private_write
import lab


class ConfigurationTests(unittest.TestCase):
    def test_recovered_samba_image_is_not_rebuilt_when_preparing_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'state/samba').mkdir(parents=True)
            (root/'state/samba/recovery.compose.json').write_text('{}')
            with patch.object(lab,'ROOT',root),patch.object(lab,'initialize'),patch.object(lab,'compose') as compose,patch.object(sys,'argv',['lab.py','start']):
                lab.main()
            self.assertEqual([call.args for call in compose.call_args_list],[('build','video'),('up','-d','--no-build')])

    def test_special_characters_in_credentials_round_trip(self):
        user, password = 'test@user', ':/@%#? $é'
        config = camera_config('192.168.1.32', user, password)
        stream = urlsplit(config['streams']['tapo'][0])
        self.assertEqual(unquote(stream.username), user)
        self.assertEqual(unquote(stream.password), password)
        self.assertEqual(stream.hostname, '192.168.1.32')
        self.assertEqual(stream.path, '/stream1')

    def test_ip_and_control_characters_rejected(self):
        for ip in ('localhost/attack', '192.168.1.999', 'example.org'):
            with self.assertRaises(ValueError):
                camera_config(ip, 'user', 'password')
        with self.assertRaises(ValueError):
            camera_config('192.168.1.32', 'user', 'pass\nword')

    def test_init_preserves_config_and_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize(root)
            path = root / 'state/frigate/config.yml'
            password = (root / 'state/smb_password').read_text()
            private_write(path, '{"cameras": {"test": {}}}')
            initialize(root)
            self.assertIn('test', json.loads(path.read_text())['cameras'])
            self.assertEqual(password, (root / 'state/smb_password').read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / 'state').stat().st_mode), 0o700)


if __name__ == '__main__':
    unittest.main()
