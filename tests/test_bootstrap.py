import importlib.util
from pathlib import Path
from types import SimpleNamespace
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'console'))
from install_service import install,unit_text
spec=importlib.util.spec_from_file_location('prepare_host',ROOT/'scripts/prepare_host.py')
host=importlib.util.module_from_spec(spec);sys.modules['prepare_host']=host;spec.loader.exec_module(host)


class BootstrapTests(unittest.TestCase):
    def plan(self,**kwargs):
        with patch.object(host.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1000,pw_shell='/bin/bash')),patch.object(host.shutil,'which',return_value=None):
            return host.make_plan(kwargs.get('user','nasuser'),kwargs.get('release',{'ID':'ubuntu','VERSION_ID':'24.04'}),kwargs.get('arch','aarch64'),kwargs.get('packages',set()))

    def test_fixed_packages_plan_and_already_prepared_host(self):
        plan=self.plan()
        self.assertIn('--no-remove',plan[1]);self.assertIn('docker-compose-v2',plan[1])
        self.assertEqual(plan[-1],['loginctl','enable-linger','nasuser'])
        repeat=self.plan(packages=set(host.PACKAGES))
        self.assertFalse(any(c[0]=='apt-get' for c in repeat))
        self.assertFalse(any('reboot' in c or 'remove' in c for c in plan))

    def test_unsupported_host_and_conflicting_docker_are_rejected(self):
        for change in ({'release':{'ID':'debian','VERSION_ID':'12'}},{'arch':'riscv64'},{'user':'--root'},{'packages':{'docker-ce'}},{'packages':{'podman-docker'}}):
            with self.assertRaises(ValueError):self.plan(**change)
        with patch.object(host.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=0,pw_shell='/bin/bash')):
            with self.assertRaises(ValueError):host.make_plan('root',{'ID':'ubuntu','VERSION_ID':'24.04'},'x86_64',set())

    def test_unit_quotes_paths_port_and_has_no_target_order_cycle(self):
        text=unit_text('/srv/Mon NAS % test',port=8877)
        self.assertIn('WorkingDirectory=/srv/Mon NAS %% test',text)
        self.assertIn('Environment=NAS_PORT=8877',text)
        self.assertNotIn('After=default.target',text)
        for port in (0,80,65536,True,'8766'):
            with self.assertRaises(ValueError):unit_text('/srv/nacre',port=port)
        with self.assertRaises(ValueError):unit_text('/srv/nacre\nother')

    def test_busy_port_preserves_existing_unit(self):
        with tempfile.TemporaryDirectory() as directory,patch('install_service.os.geteuid',return_value=1000),patch('install_service.Path.home',return_value=Path(directory)),patch('install_service.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            unit=Path(directory)/'.config/systemd/user/nacre-console.service';unit.parent.mkdir(parents=True)
            original=unit_text(ROOT);unit.write_text(original)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));sock.listen()
                with self.assertRaisesRegex(ValueError,'port est occupé'):install(ROOT,sock.getsockname()[1])
            self.assertEqual(unit.read_text(),original)

    def test_failed_start_restores_unit_and_disabled_state(self):
        with tempfile.TemporaryDirectory() as directory,patch('install_service.os.geteuid',return_value=1000),patch('install_service.Path.home',return_value=Path(directory)):
            unit=Path(directory)/'.config/systemd/user/nacre-console.service';unit.parent.mkdir(parents=True)
            original=unit_text(ROOT);unit.write_text(original)
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                if 'restart' in args:raise subprocess.CalledProcessError(1,args)
                return SimpleNamespace(returncode=1 if 'is-active' in args or 'is-enabled' in args else 0)
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            with patch('install_service.subprocess.run',side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):install(ROOT,port)
            self.assertEqual(unit.read_text(),original)
            self.assertIn(['systemctl','--user','disable','nacre-console.service'],calls)
            self.assertIn(['systemctl','--user','stop','nacre-console.service'],calls)

    def test_foreign_or_symlink_service_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory,patch('install_service.os.geteuid',return_value=1000),patch('install_service.Path.home',return_value=Path(directory)):
            unit=Path(directory)/'.config/systemd/user/nacre-console.service';unit.parent.mkdir(parents=True)
            unit.write_text(unit_text(str(ROOT)+'-other'))
            with self.assertRaisesRegex(ValueError,'autre installation'):install(ROOT)
            unit.unlink();target=Path(directory)/'other';target.write_text('private');unit.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'symbolique'):install(ROOT)
            self.assertEqual(target.read_text(),'private')

    def test_host_plan_does_not_execute_commands_and_failure_stops_permissions(self):
        import io
        from contextlib import ExitStack,redirect_stdout,redirect_stderr
        with ExitStack() as stack:
            for target,value in [('platform.freedesktop_os_release',{'ID':'ubuntu','VERSION_ID':'24.04'}),('platform.machine','aarch64'),('installed_packages',set()),('pwd.getpwnam',SimpleNamespace(pw_uid=1000,pw_shell='/bin/bash')),('shutil.which',None),('Path.is_dir',True)]:
                stack.enter_context(patch.object(host, target, return_value=value) if '.' not in target else patch('prepare_host.'+target,return_value=value))
            with patch.object(host.subprocess,'run') as run,patch.object(sys,'argv',['prepare_host.py','--user','nasuser']),redirect_stdout(io.StringIO()):
                host.main();run.assert_not_called()
            with patch.object(host.os,'geteuid',return_value=0),patch.object(host.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['apt-get','update'])) as run,patch.object(sys,'argv',['prepare_host.py','--user','nasuser','--apply']),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):host.main()
                self.assertEqual(run.call_count,1)
                self.assertEqual(run.call_args.args[0],['apt-get','update'])
