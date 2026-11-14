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

    def arguments(self, *args, override=None):
        return ['docker', 'compose', '-f', str(self.ROOT / 'compose.yaml'), '-f', str(override), *args]


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
        self.assertEqual(args[2:6], ('-f', '/srv/nacre/compose.yaml', '-f', str(override)))
        self.assertEqual({name for name in service_agent.OPERATIONS}, {operation for (operation, _), _ in expected} | {'samba_password', 'samba_mounts_check', 'video_address', 'engine', 'protection'})
        self.assertEqual(self.ask('protection'), {'agent': False, 'sources': [], 'protected': False, 'required': False})   # sans agent, rien à dire

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
            ('engine', {'lookup': True, 'args': ['docker', 'ps']}), ('engine', {'lookup': 'oui'}),
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
        self.assertEqual(found, {'server.py': ['def compose(*args, data=None, timeout=25):', 'from compose_support import arguments as described']})
        server = (SOURCE / 'console/server.py').read_text()
        self.assertEqual(len(re.findall(r'(?<![A-Za-z_.])command\(', server)), 2)   # sa définition, et son appel par compose()
        self.assertTrue(any(direct.search(line) for line in (SOURCE / 'console/system_recovery.py').read_text().splitlines()))


class Storage:
    """Docker simulé pour l'agent : note chaque commande, répond comme demandé."""
    def __init__(self):
        self.calls, self.code, self.out, self.slow = [], 0, '', False

    def __call__(self, args, **options):
        self.calls.append((list(args), options))
        if self.slow:
            raise service_agent.subprocess.TimeoutExpired(args, options.get('timeout'))
        return service_agent.subprocess.CompletedProcess(args, self.code, self.out, 'détail <privé>')


class AgentTests(unittest.TestCase):
    """L'agent de services : identité de l'appelant, description et montages vérifiés, même liste fermée."""

    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.runtime, self.approved, self.outside = base / 'installation', base / 'run', base / 'srv/nacre', base / 'ailleurs'
        for folder in (self.root / 'state/samba', self.root / 'state/console', self.runtime, self.approved / 'volume-a', self.outside):
            folder.mkdir(parents=True)
        self.description = base / 'compose.yaml'
        self.description.write_text('name: nas-autonome-lab\nservices:\n  video:\n    volumes:\n      - ./state/frigate:/config\n      - ./data/video:/media/frigate\n'
                                    '  fichiers:\n    volumes:\n      - ./data/fichiers:/shares/fichiers\n      - ./data/video:/shares/video:ro\n      - ./state/samba:/etc/nas-autonome:ro\n      - samba-state:/var/lib/samba\n')
        for folder in ('state/frigate', 'data/video', 'data/fichiers'):
            (self.root / folder).mkdir(parents=True)
        (self.root / '.env').write_text('NACRE_FRIGATE_IMAGE=ghcr.io/blakeblackshear/frigate:0.16.2\nNACRE_UID=1000\nNACRE_GID="1000"\nCOMPOSE_FILE=/tmp/piège.yaml\nDOCKER_HOST=tcp://ailleurs:2375\n')
        self.policy = {'version': 1, 'allowed_uid': 1000, 'root': str(self.root), 'mount_roots': [str(self.approved)]}
        self.docker = Storage()
        # La description doit appartenir à root : ici, le compte qui lance les essais en tient lieu.
        owner = service_agent.os.stat(self.description).st_uid
        real = service_agent.os.stat
        patcher = patch.object(service_agent.os, 'stat', side_effect=lambda path, *a, **k: type('Meta', (), {'st_uid': 0, 'st_mode': 0o100644})() if Path(path) == self.description else real(path, *a, **k))
        patcher.start(); self.addCleanup(patcher.stop)
        quiet = patch.object(service_agent, 'print', create=True)     # le journal root de l'agent n'a rien à faire dans la sortie des essais
        quiet.start(); self.addCleanup(quiet.stop)
        self.assertNotEqual(owner, -1)
        self.host = service_agent.Host(self.policy, self.description, self.runtime, self.docker)
        self.mounts_file = self.root / 'state/samba/volumes.compose.json'

    def ask(self, operation, uid=1000, **parameters):
        return service_agent.answer(self.host, uid, {'operation': operation, 'parameters': parameters})

    def mount(self, source, target='/shares/native_volume-a', **changes):
        return {'type': 'bind', 'source': str(source), 'target': target, 'read_only': False, 'bind': {'create_host_path': False}, **changes}

    def mounts(self, *items):
        self.mounts_file.write_text(json.dumps({'services': {'fichiers': {'volumes': list(items)}}}))

    def test_only_the_console_account_is_heard_and_only_the_closed_list(self):
        for uid in (0, 1001, 65534):
            self.assertEqual(self.ask('status', uid=uid), {'error': 'Identité du client système non autorisée.', 'status': 403})
        for message in ({'operation': 'inconnue'}, {'operation': 'control', 'parameters': {'name': 'video', 'action': 'rm'}}, {'operation': 'status', 'parameters': ['video']},
                        {'operation': 'status', 'parameters': {'component': '--volumes'}}, {'operation': 'compose', 'parameters': {'args': ['run', '--privileged', 'alpine']}}, {}):
            reply = service_agent.answer(self.host, 1000, message)
            self.assertEqual((sorted(reply), reply['status']), (['error', 'status'], 400), message)
        self.assertEqual(self.docker.calls, [])
        self.docker.out = '{"Service":"video"}\n'
        self.assertEqual(self.ask('status'), {'result': '{"Service":"video"}\n'})
        args, options = self.docker.calls[-1]
        # Sa propre description, le dossier de l'installation, le nom du projet, et un fichier de variables qu'il a filtré.
        self.assertEqual(args[:5], ['docker', 'compose', '--project-directory', str(self.root), '--project-name'])
        self.assertEqual((args[5], args[6], args[8:]), ('nas-autonome-lab', '--env-file', ['-f', str(self.description), 'ps', '--all', '--format', 'json']))
        self.assertEqual(Path(args[7]).read_text(), 'NACRE_FRIGATE_IMAGE=ghcr.io/blakeblackshear/frigate:0.16.2\nNACRE_GID=1000\nNACRE_UID=1000\n')
        self.assertEqual((Path(args[7]).parent, options['cwd'], options['timeout'], sorted(options['env'])), (self.runtime, self.root, 3, ['HOME', 'LC_ALL', 'PATH']))
        self.assertNotIn(str(self.root / 'compose.yaml'), args)
        # Un refus de Docker, un délai dépassé : mêmes sens que sans agent, et aucun détail brut vers la console.
        self.docker.code = 1
        self.assertEqual(self.ask('samba_reload'), {'error': 'Le service n’a pas accepté cette opération. Consulter son état.', 'status': 503})
        self.docker.code, self.docker.slow = 0, True
        self.assertEqual(self.ask('samba_reload'), {'error': 'Délai dépassé.', 'status': 503, 'kind': 'timeout'})
        self.docker.slow = False
        # Le mot de passe arrive à smbpasswd par l'entrée standard.
        self.ask('samba_password', name='alice', password='un secret bien long')
        args, options = self.docker.calls[-1]
        self.assertEqual((args[-7:], options['input']), (['exec', '-T', 'fichiers', 'smbpasswd', '-s', '-a', 'alice'], 'un secret bien long\nun secret bien long\n'))

    def test_share_mounts_must_point_inside_locations_approved_by_root(self):
        # Sans fichier de montages : rien d'ajouté. Avec un montage approuvé : la copie vérifiée de l'agent, pas le fichier de la console.
        self.assertIn('result', self.ask('recreate_files'))
        self.assertEqual(self.docker.calls[-1][0].count('-f'), 1)
        self.mounts(self.mount(self.approved / 'volume-a'))
        self.assertIn('result', self.ask('recreate_files'))
        args = self.docker.calls[-1][0]
        copy = Path(args[args.index('-f', args.index('-f') + 1) + 1])
        self.assertEqual((copy.parent, args[-5:]), (self.runtime, ['up', '-d', '--no-deps', '--force-recreate', 'fichiers']))
        self.assertEqual(json.loads(copy.read_text()), {'services': {'fichiers': {'volumes': [self.mount(service_agent.os.path.realpath(self.approved / 'volume-a'))]}}})
        self.assertNotIn(str(self.mounts_file), args)
        # Tout écart refuse l'opération entière, avant toute commande.
        (self.approved / 'lien').symlink_to(self.outside)
        before = len(self.docker.calls)
        bad = [self.mount(self.outside), self.mount('/'), self.mount('/etc'), self.mount(self.approved / 'lien'), self.mount(self.approved / 'absent'), self.mount(str(self.approved) + '/../ailleurs'),
               self.mount('relatif'), self.mount(self.approved / 'volume-a', target='/shares/fichiers'), self.mount(self.approved / 'volume-a', target='/etc'),
               self.mount(self.approved / 'volume-a', target='/shares/native_../x'), self.mount(self.approved / 'volume-a', type='volume'), self.mount(self.approved / 'volume-a', read_only='non'),
               self.mount(self.approved / 'volume-a', bind={'create_host_path': True}), {**self.mount(self.approved / 'volume-a'), 'privileged': True}, 'chaîne']
        for item in bad:
            self.mounts(item)
            self.assertEqual(self.ask('recreate_files'), {'error': 'Montage de partage non approuvé par la politique système.', 'status': 400}, item)
        for document in ({'services': {'fichiers': {'volumes': [], 'privileged': True}}}, {'services': {'fichiers': {'volumes': []}, 'autre': {'image': 'alpine'}}},
                         {'services': {'fichiers': {'volumes': []}}, 'volumes': {}}, [], 'x'):
            self.mounts_file.write_text(json.dumps(document))
            self.assertEqual(self.ask('status')['status'], 400, document)
        self.mounts_file.write_text('{illisible')
        self.assertEqual(self.ask('status')['status'], 400)
        self.mounts_file.unlink(); self.mounts_file.symlink_to('/etc/passwd')
        self.assertEqual(self.ask('status')['status'], 503)
        self.assertEqual(len(self.docker.calls), before)
        self.mounts_file.unlink()
        # Sans emplacement approuvé, aucun dossier supplémentaire n'entre dans le conteneur.
        self.host.policy = {**self.policy, 'mount_roots': []}
        self.mounts(self.mount(self.approved / 'volume-a'))
        self.assertEqual(self.ask('recreate_files')['status'], 400)
        # Le fichier candidat d'une modification de partages passe par le même contrôle.
        self.host.policy = self.policy
        self.mounts_file.unlink()
        candidate = self.root / 'state/samba' / ('.mounts-' + 'c' * 20 + '.json')
        candidate.write_text(json.dumps({'services': {'fichiers': {'volumes': [self.mount(self.outside)]}}}))
        self.assertEqual(self.ask('samba_mounts_check', override=str(candidate))['status'], 400)
        candidate.write_text(json.dumps({'services': {'fichiers': {'volumes': [self.mount(self.approved / 'volume-a')]}}}))
        self.assertIn('result', self.ask('samba_mounts_check', override=str(candidate)))
        self.assertEqual(self.docker.calls[-1][0][-2:], ['config', '--quiet'])

    def test_a_recovered_installation_is_read_strictly(self):
        (self.root / 'state/console/recovery-project.json').write_text(json.dumps({'project': 'nacre-recovered-' + 'a' * 24}))
        state = self.root / 'state/samba/recovery.compose.json'
        good = {'services': {'fichiers': {'image': 'sha256:' + 'b' * 64, 'hostname': 'nas-maison'}}, 'volumes': {'samba-state': {'external': True, 'name': 'nacre-recovered-samba'}}}
        state.write_text(json.dumps(good))
        self.assertIn('result', self.ask('status'))
        args = self.docker.calls[-1][0]
        self.assertEqual(args[5], 'nacre-recovered-' + 'a' * 24)
        self.assertEqual(json.loads(Path(args[args.index('-f', args.index('-f') + 1) + 1]).read_text()), good)
        before = len(self.docker.calls)
        for document in ({**good, 'services': {'fichiers': {**good['services']['fichiers'], 'privileged': True}}}, {**good, 'services': {**good['services'], 'autre': {}}},
                         {**good, 'volumes': {'samba-state': {'external': False, 'name': 'x'}}}, {'services': {'fichiers': {'image': 'alpine', 'hostname': 'x'}}, 'volumes': good['volumes']}, []):
            state.write_text(json.dumps(document))
            self.assertEqual(self.ask('status'), {'error': 'État Samba repris invalide.', 'status': 400}, document)
        state.write_text(json.dumps(good))
        (self.root / 'state/console/recovery-project.json').write_text(json.dumps({'project': 'autre-projet'}))
        self.assertEqual(self.ask('status'), {'error': 'Projet de reprise invalide.', 'status': 400})
        self.assertEqual(len(self.docker.calls), before)
        # Reprise commencée, état Samba pas encore préparé : aucun démarrage.
        (self.root / 'state/console/recovery-project.json').unlink(); state.unlink()
        (self.root / 'state/console/system-recovery-status.json').write_text('{}')
        self.assertEqual(self.ask('control', name='video', action='start')['status'], 400)
        self.assertIn('result', self.ask('control', name='video', action='stop'))

    def test_the_console_reaches_the_agent_through_its_socket_and_keeps_its_error_meanings(self):
        import threading
        path = str(self.runtime / 'control.sock')
        server = service_agent.AgentServer(path, service_agent.AgentHandler)
        server.host = self.host
        self.host.policy = {**self.policy, 'allowed_uid': service_agent.os.getuid()}
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        client, app = service_agent.AgentClient(path), App()
        self.assertTrue(service_agent.agent_present(path)); self.assertFalse(service_agent.agent_present(path + '.absent'))
        self.docker.out = 'sortie\n'
        self.assertEqual(client.request(app, 'samba_group', {}), 'sortie\n')
        self.assertEqual(client.request(app, 'samba_mounts_check', {'override': self.root / 'state/samba' / ('.mounts-' + 'd' * 20 + '.json')}), 'sortie\n')
        self.assertEqual(app.calls, [])                       # rien n'est exécuté du côté de la console
        with self.assertRaises(Problem) as refused:
            client.request(app, 'control', {'name': 'video', 'action': 'rm'})
        self.assertEqual(refused.exception.args, ('Opération de service non autorisée.', 400))
        self.docker.code = 1
        with self.assertRaises(Problem) as failed:
            client.request(app, 'samba_reload', {})
        self.assertEqual(failed.exception.args[1], 503)
        self.docker.code, self.docker.slow = 0, True
        with self.assertRaises(service_agent.subprocess.TimeoutExpired):
            client.request(app, 'samba_reload', {})
        self.docker.slow = False
        self.host.policy = {**self.policy, 'allowed_uid': service_agent.os.getuid() + 1}
        with self.assertRaises(Problem) as stranger:
            client.request(app, 'status', {})
        self.assertEqual(stranger.exception.args, ('Identité du client système non autorisée.', 403))
        with self.assertRaises(OSError):
            service_agent.AgentClient(path + '.absent').request(app, 'status', {})
        with self.assertRaises(Problem):
            client.request(app, 'video_validate', {'document': {'x': 'y' * service_agent.MAX_MESSAGE}})
        # Une demande mal formée est refusée sans rien exécuter.
        import socket
        calls = len(self.docker.calls)
        for raw in (b'pas du json\n', b'[]\n', b'{"operation":"status"}'):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as direct:
                direct.connect(path); direct.sendall(raw); direct.shutdown(socket.SHUT_WR)
                self.assertEqual(json.loads(direct.makefile('rb').readline())['error'], 'Requête système invalide.')
        self.assertEqual(len(self.docker.calls), calls)

    def test_installer_stages_the_agent_its_own_description_and_an_empty_policy(self):
        import install_services
        described = 'name: nas-autonome-lab\nservices:\n  video:\n    build:\n      context: ./frigate\n  fichiers:\n    build:\n      context: ./samba\n'
        (self.root / 'compose.yaml').write_text(described)
        for image, names in (('samba', ('Dockerfile', 'entrypoint.sh')), ('frigate', ('Dockerfile',))):
            (self.root / image / '__pycache__').mkdir(parents=True)
            for name in names:
                (self.root / image / name).write_text(image + ' ' + name)
        (self.root / 'samba/lien').symlink_to('/etc/passwd')
        target = Path(self.temp.name) / 'racine'
        prepared = install_services.stage(target, 1000, self.root)
        library = 'usr/local/lib/nacre-services/'
        self.assertEqual(sorted(prepared), ['etc/nacre-services/policy.json', 'etc/systemd/system/nacre-services.service', library + 'compose.yaml', library + 'frigate/Dockerfile',
                                            library + 'native_storage.py', library + 'samba/Dockerfile', library + 'samba/entrypoint.sh', library + 'service_agent.py'])
        # Les sources des images sont copiées, et la description de l'agent y renvoie : celles de l'installation ne servent plus.
        self.assertEqual((target / library / 'compose.yaml').read_text(), described.replace('./frigate', '/usr/local/lib/nacre-services/frigate').replace('./samba', '/usr/local/lib/nacre-services/samba'))
        self.assertEqual((target / library / 'samba/entrypoint.sh').read_text(), 'samba entrypoint.sh')
        # Montages protégés : préparés seulement sur demande, un par dossier où les conteneurs écrivent, au nom que systemd attend.
        self.assertFalse(any(name.endswith('.mount') for name in prepared))
        units = install_services.protections('/home/ubuntu/nacre-agent-lab')
        self.assertEqual(sorted(units), ['etc/systemd/system/home-ubuntu-nacre\\x2dagent\\x2dlab-data.mount', 'etc/systemd/system/home-ubuntu-nacre\\x2dagent\\x2dlab-state.mount'])
        self.assertIn('What=/home/ubuntu/nacre-agent-lab/data\nWhere=/home/ubuntu/nacre-agent-lab/data\nType=none\nOptions=bind,nosuid,nodev\n', units[sorted(units)[0]])
        self.assertEqual(install_services.unit_name('/srv/.caché/é'), 'srv-.cach\\xc3\\xa9-\\xc3\\xa9.mount')
        self.assertEqual(len([name for name in install_services.stage(target, 1000, self.root, protect=True) if name.endswith('.mount')]), 2)
        self.assertEqual(json.loads((target / 'etc/nacre-services/policy.json').read_text()), {'version': 1, 'allowed_uid': 1000, 'root': str(self.root.resolve()), 'mount_roots': []})
        self.assertEqual((target / 'usr/local/lib/nacre-services/service_agent.py').read_text(), (SOURCE / 'console/service_agent.py').read_text())
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/lib/nacre-services/service_agent.py\n', prepared['etc/systemd/system/nacre-services.service'])
        self.assertEqual((target / 'etc/nacre-services/policy.json').stat().st_mode & 0o777, 0o600)
        # Réinstaller met le code et la description à jour, jamais la politique.
        (target / 'etc/nacre-services/policy.json').write_text('{"gardée": true}')
        (self.root / 'compose.yaml').write_text(described + '# mise à jour\n')
        install_services.stage(target, 1000, self.root)
        self.assertEqual((target / 'etc/nacre-services/policy.json').read_text(), '{"gardée": true}')
        self.assertIn('# mise à jour', (target / 'usr/local/lib/nacre-services/compose.yaml').read_text())
        (self.root / 'compose.yaml').write_text('name: nas-autonome-lab\nservices: {}\n')
        with self.assertRaises(ValueError):
            install_services.stage(target, 1000, self.root)                     # description sans les sources attendues
        (self.root / 'compose.yaml').write_text(described)
        for uid, root in ((0, self.root), (1000, self.outside)):
            with self.assertRaises(ValueError):
                install_services.stage(target, uid, root)

    def test_folders_written_by_containers_are_checked_for_nosuid_and_nodev(self):
        flags = {}
        real = service_agent.os.statvfs
        patcher = patch.object(service_agent.os, 'statvfs', side_effect=lambda path: type('Flags', (), {'f_flag': flags[str(path)]})() if str(path) in flags else real(path))
        patcher.start(); self.addCleanup(patcher.stop)
        safe = service_agent.os.ST_NOSUID | service_agent.os.ST_NODEV
        written = [str(self.root / name) for name in ('state/frigate', 'data/video', 'data/fichiers')]
        flags.update({written[0]: safe, written[1]: service_agent.os.ST_NOSUID, written[2]: 0})
        # Seuls les dossiers où un conteneur écrit comptent : les montages en lecture seule et les volumes Docker n'en sont pas.
        reply = self.ask('protection')['result']
        self.assertEqual((reply['agent'], reply['protected'], reply['required']), (True, False, False))
        self.assertEqual(reply['sources'], [{'path': written[0], 'nosuid': True, 'nodev': True}, {'path': written[1], 'nosuid': True, 'nodev': False}, {'path': written[2], 'nosuid': False, 'nodev': False}])
        # Sans exigence dans la politique, l'agent le dit et démarre quand même ; avec, il refuse de démarrer tant qu'un dossier est exposé.
        self.assertIn('result', self.ask('control', name='video', action='restart'))
        self.host.policy = {**self.policy, 'require_protected_mounts': True}
        before = len(self.docker.calls)
        for operation, parameters in (('control', {'name': 'video', 'action': 'restart'}), ('control', {'name': 'video', 'action': 'start'}), ('recreate_files', {}), ('start_component', {'component': 'fichiers'})):
            reply = self.ask(operation, **parameters)
            self.assertEqual(reply['status'], 400, operation)
            self.assertIn(written[1] + ', ' + written[2], reply['error'])
            self.assertNotIn(written[0], reply['error'])
        self.assertEqual(len(self.docker.calls), before)
        for operation, parameters in (('status', {}), ('control', {'name': 'video', 'action': 'stop'}), ('samba_reload', {})):
            self.assertIn('result', self.ask(operation, **parameters), operation)       # lire et arrêter restent possibles
        flags.update(dict.fromkeys(written, safe))
        self.assertEqual(self.ask('protection')['result']['protected'], True)
        self.assertIn('result', self.ask('recreate_files'))
        # Un partage approuvé en écriture compte aussi ; en lecture seule, non. Un dossier absent n'est jamais « protégé ».
        flags[service_agent.os.path.realpath(self.approved / 'volume-a')] = 0
        self.mounts(self.mount(self.approved / 'volume-a'))
        self.assertEqual(self.ask('recreate_files')['status'], 400)
        self.mounts(self.mount(self.approved / 'volume-a', read_only=True))
        self.assertIn('result', self.ask('recreate_files'))
        flags[written[2]] = safe
        service_agent.shutil.rmtree(self.root / 'data/fichiers'); del flags[written[2]]
        reply = self.ask('protection')['result']
        self.assertEqual((reply['protected'], reply['sources'][-1]), (False, {'path': written[2], 'nosuid': False, 'nodev': False, 'missing': True}))
        # Une image fixée par root l'emporte sur celle que la console a écrite.
        self.host.policy = {**self.policy, 'frigate_image': 'ghcr.io/blakeblackshear/frigate:approuvee'}
        self.ask('status')
        arguments = self.docker.calls[-1][0]
        self.assertIn('NACRE_FRIGATE_IMAGE=ghcr.io/blakeblackshear/frigate:approuvee\n', Path(arguments[arguments.index('--env-file') + 1]).read_text())

    def test_policy_and_description_must_belong_to_root(self):
        with self.assertRaises(service_agent.AgentError):
            service_agent.read_policy(Path(self.temp.name) / 'policy.json')        # absente
        for policy in ({}, {**self.policy, 'version': 2}, {**self.policy, 'allowed_uid': 0}, {**self.policy, 'root': 'relatif'}, {**self.policy, 'root': '/srv/../etc'},
                       {**self.policy, 'mount_roots': ['/']}, {**self.policy, 'mount_roots': ['relatif']}, {**self.policy, 'mount_roots': '/srv'},
                       {**self.policy, 'require_protected_mounts': 'oui'}, {**self.policy, 'frigate_image': 'image; rm -rf /'}, {**self.policy, 'frigate_image': 7}):
            target = Path(self.temp.name) / 'policy.json'
            target.write_text(json.dumps(policy))
            with self.assertRaises(service_agent.AgentError, msg=policy):
                service_agent.read_policy(target)
        # Un dossier de /tmp, inscriptible par tous, n'est jamais un ancrage de confiance : même une politique bien formée y est refusée.
        target.write_text(json.dumps(self.policy))
        with self.assertRaises(service_agent.AgentError):
            service_agent.read_policy(target)
        self.description.write_text('services: {}\n')
        with self.assertRaises(service_agent.AgentError):
            service_agent.Host(self.policy, self.description, self.runtime, self.docker)


if __name__ == '__main__':
    unittest.main()
