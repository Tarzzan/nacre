"""Opérations de services : liste fermée, paramètres validés, lignes de commande fixes, et aucune autre porte vers Docker."""
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / 'console')]
import service_agent


class Problem(Exception):
    pass


class App:
    """Console réduite à ce que le catalogue utilise : deux exécuteurs, qui notent ce qu'on leur demande."""
    Problem = Problem
    ROOT = Path('/srv/nacre')

    def __init__(self):
        self.calls, self.answers = [], {}

    def compose(self, *args, **options):
        self.calls.append(('compose', args, options))
        return self.answers.get(args[:2], '')

    def command(self, args, **options):
        self.calls.append(('command', tuple(args), options))
        return self.answers.get('command', '')


class ServiceAgentTests(unittest.TestCase):
    def setUp(self):
        self.app = App()

    def ask(self, operation, **parameters):
        return service_agent.request(self.app, operation, **parameters)

    def last(self):
        return self.app.calls[-1]

    def test_every_operation_runs_one_fixed_command_line(self):
        validate = 'import json,sys;from frigate.config import FrigateConfig;FrigateConfig.model_validate(json.load(sys.stdin))'
        access = 'test -r "$1" && test -x "$1" && { [ "$2" = r ] || test -w "$1"; }'
        expected = [
            (('status', {}), ('compose', ('ps', '--all', '--format', 'json'), {'timeout': 3})),
            (('status', {'component': 'video', 'timeout': 10}), ('compose', ('ps', '--all', '--format', 'json', 'video'), {'timeout': 10})),
            (('control', {'name': 'fichiers', 'action': 'stop'}), ('compose', ('stop', 'fichiers'), {})),
            (('control', {'name': 'video', 'action': 'restart', 'timeout': 90}), ('compose', ('restart', 'video'), {'timeout': 90})),
            (('recreate_files', {}), ('compose', ('up', '-d', '--no-deps', '--force-recreate', 'fichiers'), {'timeout': 90})),
            (('build', {'component': 'video'}), ('compose', ('build', 'video'), {'timeout': 1800})),
            (('build', {'component': 'fichiers'}), ('compose', ('build', 'fichiers'), {'timeout': 1200})),
            (('start_component', {'component': 'fichiers'}), ('compose', ('up', '-d', '--no-deps', '--no-build', 'fichiers'), {'timeout': 180})),
            (('video_validate', {'document': {'cameras': {}}}), ('compose', ('exec', '-T', 'video', 'python3', '-c', validate), {'data': '{"cameras": {}}'})),
            (('video_validate', {'document': {}, 'timeout': 30}), ('compose', ('exec', '-T', 'video', 'python3', '-c', validate), {'data': '{}', 'timeout': 30})),
            (('samba_group', {}), ('compose', ('exec', '-T', 'fichiers', 'id', '-g', 'nas'), {})),
            (('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares/fichiers/Photos été', 'readonly': False}),
             ('compose', ('exec', '-T', '--user', '1001:100', 'fichiers', 'sh', '-c', access, 'sh', '/shares/fichiers/Photos été', 'rw'), {})),
            (('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares/video', 'readonly': True}),
             ('compose', ('exec', '-T', '--user', '1001:100', 'fichiers', 'sh', '-c', access, 'sh', '/shares/video', 'r'), {})),
            (('samba_identity', {'area': 'native_restore-0a1b'}), ('compose', ('exec', '-T', 'fichiers', 'stat', '-c', '%d:%i', '/shares/native_restore-0a1b'), {})),
            (('samba_config_check', {'name': '.smb-' + 'a' * 20 + '.conf'}), ('compose', ('exec', '-T', 'fichiers', 'testparm', '-s', '/etc/nas-autonome/.smb-' + 'a' * 20 + '.conf'), {})),
            (('samba_reload', {}), ('compose', ('exec', '-T', 'fichiers', 'smbcontrol', 'all', 'reload-config'), {})),
            (('samba_close', {'share': 'photos'}), ('compose', ('exec', '-T', 'fichiers', 'smbcontrol', 'all', 'close-share', 'photos'), {})),
            (('samba_ping', {}), ('compose', ('exec', '-T', 'fichiers', 'smbcontrol', 'smbd', 'ping'), {'timeout': 10})),
            (('samba_account', {'name': 'alice', 'uid': 1002}), ('compose', ('exec', '-T', 'fichiers', 'adduser', '-D', '-H', '-u', '1002', '-G', 'nas', 'alice'), {})),
            (('samba_enable', {'name': 'alice', 'enabled': False}), ('compose', ('exec', '-T', 'fichiers', 'smbpasswd', '-d', 'alice'), {})),
            (('samba_enable', {'name': 'alice', 'enabled': True}), ('compose', ('exec', '-T', 'fichiers', 'smbpasswd', '-e', 'alice'), {})),
        ]
        for (operation, parameters), call in expected:
            self.ask(operation, **parameters)
            self.assertEqual(self.last(), call, operation)
        self.assertEqual(len(self.app.calls), len(expected))
        # Le mot de passe voyage par l'entrée standard, jamais dans la ligne de commande.
        self.ask('samba_password', name='alice', password='un secret bien long')
        kind, args, options = self.last()
        self.assertEqual((args, options), (('exec', '-T', 'fichiers', 'smbpasswd', '-s', '-a', 'alice'), {'data': 'un secret bien long\nun secret bien long\n'}))
        self.assertNotIn('secret', ' '.join(args))
        # Le fichier de montages candidat est validé par Compose, avec la même description que l'installation.
        override = self.app.ROOT / 'state/samba' / ('.mounts-' + 'b' * 20 + '.json')
        self.ask('samba_mounts_check', override=override)
        kind, args, options = self.last()
        self.assertEqual((kind, args[:2], args[-2:]), ('command', ('docker', 'compose'), ('config', '--quiet')))
        self.assertIn('/srv/nacre/compose.yaml', args)
        self.assertEqual({name for name in service_agent.OPERATIONS}, {operation for (operation, _), _ in expected} | {'samba_password', 'samba_mounts_check', 'video_address', 'engine'})

    def test_video_address_gives_only_the_address_and_engine_only_three_answers(self):
        self.assertIsNone(self.ask('video_address'))
        self.assertEqual(self.app.calls, [('compose', ('ps', '-q', 'video'), {})])
        self.app.answers[('ps', '-q')] = 'abc123def456\n'
        self.app.answers['command'] = json.dumps([{'Config': {'Env': ['SECRET=1']}, 'NetworkSettings': {'Networks': {'nacre': {'IPAddress': '172.18.0.3'}}}}])
        self.assertEqual(self.ask('video_address'), '172.18.0.3')
        self.assertEqual(self.last(), ('command', ('docker', 'inspect', 'abc123def456'), {}))
        self.app.answers['command'] = json.dumps([{'NetworkSettings': {'Networks': {'nacre': {'IPAddress': ''}}}}])
        self.assertEqual(self.ask('video_address'), '')
        self.app.answers[('ps', '-q')] = '--help\n'
        with self.assertRaises(Problem):
            self.ask('video_address')
        import onboarding
        with patch.object(onboarding.shutil, 'which', return_value=None), patch.object(onboarding, 'probe') as probe:
            self.assertEqual(self.ask('engine'), {'docker': False, 'engine': False, 'compose': False})
            probe.assert_not_called()
        with patch.object(onboarding.shutil, 'which', return_value='/usr/bin/docker'), patch.object(onboarding, 'probe', side_effect=[True, False]) as probe:
            self.assertEqual(self.ask('engine'), {'docker': True, 'engine': True, 'compose': False})
            self.assertEqual([call.args[0] for call in probe.call_args_list], [['docker', 'info', '--format', '{{.ServerVersion}}'], ['docker', 'compose', 'version']])
        with patch.object(onboarding, 'probe', return_value=False) as probe:
            self.assertEqual(self.ask('engine', lookup=False)['compose'], False)
            self.assertEqual(probe.call_count, 1)

    def test_anything_outside_the_list_is_refused_before_any_command(self):
        long = 'x' * 20
        refused = [
            ('inconnue', {}), ('compose', {'args': ['run', 'alpine']}), ('request', {}), ('_require', {'condition': True}), (None, {}), (['status'], {}),
            ('status', {'component': 'autre'}), ('status', {'component': '--volumes'}), ('status', {'timeout': 0}), ('status', {'timeout': 3600}), ('status', {'extra': 1}),
            ('control', {'name': 'video', 'action': 'rm'}), ('control', {'name': 'video', 'action': 'down'}), ('control', {'name': 'console', 'action': 'stop'}),
            ('control', {'name': 'video'}), ('control', {'name': 'video', 'action': 'restart', 'timeout': '90'}), ('control', {'name': ['video'], 'action': 'stop'}),
            ('build', {'component': '.'}), ('build', {'component': 'video', 'timeout': 5}), ('start_component', {'component': 'video --privileged'}), ('recreate_files', {'name': 'video'}),
            ('video_validate', {'document': '{}'}), ('video_validate', {'document': {}, 'code': 'import os'}), ('video_validate', {'document': {}, 'timeout': 9999}),
            ('samba_access', {'uid': 0, 'group': '100', 'path': '/shares/fichiers', 'readonly': True}), ('samba_access', {'uid': '1001', 'group': '100', 'path': '/shares/fichiers', 'readonly': True}),
            ('samba_access', {'uid': 1001, 'group': '0;id', 'path': '/shares/fichiers', 'readonly': True}), ('samba_access', {'uid': 1001, 'group': '100', 'path': '/etc/shadow', 'readonly': True}),
            ('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares/fichiers/../../etc', 'readonly': True}), ('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares', 'readonly': True}),
            ('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares/fichiers/a\nb', 'readonly': True}), ('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares/fichiers//x', 'readonly': True}),
            ('samba_access', {'uid': 1001, 'group': '100', 'path': '/shares/fichiers', 'readonly': 'non'}),
            ('samba_identity', {'area': '../etc'}), ('samba_identity', {'area': 'a/b'}), ('samba_identity', {'area': ''}), ('samba_identity', {'area': '-x'}),
            ('samba_config_check', {'name': 'smb.conf'}), ('samba_config_check', {'name': '../.smb-' + 'a' * 20 + '.conf'}), ('samba_config_check', {'name': '.smb-' + long + '.conf'}),
            ('samba_mounts_check', {'override': '/tmp/.mounts-' + 'b' * 20 + '.json'}), ('samba_mounts_check', {'override': '/srv/nacre/state/samba/autre.json'}),
            ('samba_mounts_check', {'override': '/srv/nacre/state/samba/../../../etc/.mounts-' + 'b' * 20 + '.json'}),
            ('samba_close', {'share': '-a'}), ('samba_close', {'share': 'Photos'}), ('samba_close', {'share': 'a b'}), ('samba_close', {'share': ''}),
            ('samba_account', {'name': 'root;id', 'uid': 1002}), ('samba_account', {'name': 'alice', 'uid': 0}), ('samba_account', {'name': 'alice', 'uid': '1002'}), ('samba_account', {'name': '-G', 'uid': 1002}),
            ('samba_password', {'name': 'alice', 'password': 'court'}), ('samba_password', {'name': 'alice', 'password': 'une ligne\npuis une autre'}), ('samba_password', {'name': 'Alice', 'password': 'un secret bien long'}),
            ('samba_enable', {'name': 'alice', 'enabled': 1}), ('samba_enable', {'name': 'alice -x', 'enabled': True}),
            ('engine', {'lookup': True, 'args': ['docker', 'ps']}),
        ]
        for operation, parameters in refused:
            with self.assertRaises(Problem, msg=(operation, parameters)):
                self.ask(operation, **parameters)
        self.assertEqual(self.app.calls, [])

    def test_the_web_process_has_no_other_door_to_docker(self):
        """Hors du catalogue, aucun module de la console ne compose de ligne de commande Docker."""
        direct = re.compile(r"""\.compose\(|(?<![A-Za-z_.])compose\(|[\[(]\s*['"]docker['"]\s*,|compose_support""")
        # Hors processus web : outils que l'administrateur lance lui-même sur l'hôte, pour reprendre une installation.
        administrator = {'system_recovery.py'}
        found = {}
        for path in sorted((SOURCE / 'console').glob('*.py')):
            if path.name == 'service_agent.py' or path.name in administrator:
                continue
            lines = [line.strip() for line in path.read_text().splitlines() if direct.search(line)]
            if lines:
                found[path.name] = lines
        # Le serveur garde les deux exécuteurs que le catalogue appelle, et rien d'autre.
        self.assertEqual(found, {'server.py': ['def compose(*args, data=None, timeout=25):', 'from compose_support import arguments']})
        server = (SOURCE / 'console/server.py').read_text()
        self.assertEqual(len(re.findall(r'(?<![A-Za-z_.])command\(', server)), 2)   # sa définition, et son appel par compose()
        self.assertTrue(any(direct.search(line) for line in (SOURCE / 'console/system_recovery.py').read_text().splitlines()))


if __name__ == '__main__':
    unittest.main()
