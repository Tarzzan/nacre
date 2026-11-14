#!/usr/bin/env python3
"""Banc de l'agent de services, UNIQUEMENT dans une VM QEMU jetable dotée de Docker et de l'image Samba du banc.

Crée une installation Nacre d'essai dans l'invité, la fait d'abord piloter Docker directement, puis installe l'agent,
RETIRE le compte ubuntu du groupe docker de l'invité, et rejoue les opérations par le socket du vrai agent. Vérifie sur
Docker lui-même ce que l'agent a fait et ce qu'il a refusé. Ne jamais lancer hors de cette VM.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path('/home/ubuntu/nacre-agent-lab')
RESULTS = Path('/home/ubuntu/service-agent-results.json')
POLICY = Path('/etc/nacre-services/policy.json')
APPROVED = Path('/srv/nacre-agent-lab')
CONTAINER = 'nas-autonome-lab-fichiers-1'


def run(*args, **options):
    return subprocess.check_output(args, text=True, **options).strip()


def guard():
    assert os.environ.get('NACRE_VM_LAB') == '1', 'Banc VM explicitement requis'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU', 'Bochs')


def console(requests):
    """Côté console, sous le compte non privilégié : chaque demande passe par service_op, comme dans le processus web."""
    assert os.geteuid() == 1000
    os.environ['NAS_ROOT'] = str(ROOT)
    sys.path[:0] = [str(ROOT), str(ROOT / 'console')]
    import server
    out = []
    for operation, parameters in requests:
        if operation == 'initialize':
            server.initialize()
            out.append({'result': 'ok'})
            continue
        try:
            out.append({'result': server.service_op(operation, **parameters)})
        except server.Problem as problem:
            out.append({'error': problem.message, 'status': problem.status})
        except subprocess.TimeoutExpired:
            out.append({'error': 'délai', 'status': 0})
        except OSError as error:
            out.append({'error': type(error).__name__, 'status': -1})
    print(json.dumps(out))


def ask(*requests):
    """Lance la partie console sous ubuntu, avec les groupes que ce compte a MAINTENANT."""
    raw = run('runuser', '-u', 'ubuntu', '--', 'env', 'NACRE_VM_LAB=1', 'python3', str(Path(__file__).resolve()), 'console', json.dumps(requests))
    return json.loads(raw.splitlines()[-1])


def one(operation, **parameters):
    return ask([operation, parameters])[0]


def inspect():
    return json.loads(run('docker', 'inspect', CONTAINER))[0]


def running():
    for _ in range(60):
        try:
            if inspect()['State']['Running'] and 'PONG' in run('docker', 'exec', CONTAINER, 'smbcontrol', 'smbd', 'ping'):
                return True
        except subprocess.CalledProcessError:
            pass
        time.sleep(.5)
    return False


def main():
    assert os.geteuid() == 0
    sys.path.insert(0, str(SOURCE / 'console'))
    out = {}
    assert 'docker' in run('id', '-nG', 'ubuntu').split(), 'Le banc part d’un compte ubuntu membre du groupe docker'
    # Installation d'essai, propre à ce banc : sources copiées, état initialisé par la console elle-même.
    subprocess.run(['docker', 'rm', '-f', CONTAINER], capture_output=True)
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir()
    for name in ['console', 'samba', 'frigate', 'compose.yaml', 'CHANGELOG.md', *sorted(path.name for path in SOURCE.glob('*.py'))]:
        (shutil.copytree if (SOURCE / name).is_dir() else shutil.copy)(SOURCE / name, ROOT / name)
    run('chown', '-R', 'ubuntu:ubuntu', str(ROOT))
    run('runuser', '-u', 'ubuntu', '--', 'python3', str(ROOT / 'lab.py'), 'init', cwd=ROOT)
    assert ask(['initialize', {}])[0] == {'result': 'ok'}

    # 1. Avant l'agent : le compte de la console pilote Docker lui-même.
    assert not Path('/run/nacre-services/control.sock').exists()
    first = one('start_component', component='fichiers')
    if 'error' in first:   # image du banc absente ou périmée : la reconstruire demande le réseau de l'invité
        assert 'result' in one('build', component='fichiers'), 'Image Samba indisponible'
        assert 'result' in one('start_component', component='fichiers')
    assert running()
    direct = [json.loads(line) for line in one('status')['result'].splitlines()]
    assert [(item['Service'], item['State']) for item in direct] == [('fichiers', 'running')], direct
    identity = inspect()['Id']
    out['direct_before'] = True

    # 2. L'agent s'installe et démarre ; le compte ubuntu QUITTE le groupe docker.
    from install_services import stage
    stage('/', 1000, ROOT)
    assert json.loads(POLICY.read_text()) == {'version': 1, 'allowed_uid': 1000, 'root': str(ROOT), 'mount_roots': []}
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'nacre-services.service')
    for _ in range(50):
        if Path('/run/nacre-services/control.sock').exists():
            break
        time.sleep(.1)
    run('gpasswd', '-d', 'ubuntu', 'docker')
    assert subprocess.run(['runuser', '-u', 'ubuntu', '--', 'docker', 'ps'], capture_output=True).returncode != 0, 'ubuntu parle encore à Docker'
    out['console_account_without_docker'] = True

    # 3. Les mêmes opérations, par l'agent, sans recréer le conteneur.
    replies = ask(['status', {}], ['engine', {}], ['samba_group', {}], ['samba_ping', {}], ['video_address', {}], ['samba_identity', {'area': 'fichiers'}],
                  ['samba_account', {'name': 'banc-agent', 'uid': 1500}], ['samba_password', {'name': 'banc-agent', 'password': 'mot de passe du banc'}],
                  ['samba_enable', {'name': 'banc-agent', 'enabled': False}], ['samba_enable', {'name': 'banc-agent', 'enabled': True}], ['samba_reload', {}],
                  ['samba_access', {'uid': 1000, 'group': '1000', 'path': '/shares/fichiers', 'readonly': False}])
    assert all('result' in reply for reply in replies), replies
    assert [json.loads(line)['State'] for line in replies[0]['result'].splitlines()] == ['running']
    assert replies[1]['result'] == {'docker': True, 'engine': True, 'compose': True} and replies[2]['result'].strip().isdecimal() and 'PONG' in replies[3]['result'] and replies[4]['result'] is None
    assert 'banc-agent' in run('docker', 'exec', CONTAINER, 'pdbedit', '-L')
    assert inspect()['Id'] == identity, 'Conteneur recréé par un simple passage à l’agent'
    assert 'result' in one('start_component', component='fichiers')
    out['same_container_after_agent'] = inspect()['Id'] == identity
    assert 'result' in one('control', name='fichiers', action='restart') and running()
    assert inspect()['Id'] == identity
    assert 'result' in one('control', name='fichiers', action='stop') and not inspect()['State']['Running']
    assert 'result' in one('control', name='fichiers', action='start') and running()
    out['operations_through_agent'] = len(replies) + 4

    # 4. Refus : autre compte, opération ou paramètre hors liste. Rien n'est exécuté.
    import service_agent

    class App:
        Problem = type('Problem', (Exception,), {})
    try:
        service_agent.AgentClient().request(App, 'status', {})
    except App.Problem as problem:
        out['refused_other_account'] = problem.args[0]
    else:
        raise AssertionError('root accepté par l’agent')
    refusals = ask(['inconnue', {}], ['control', {'name': 'fichiers', 'action': 'rm'}], ['control', {'name': 'fichiers', 'action': 'stop', 'extra': '--volumes'}],
                   ['status', {'component': '--all'}], ['samba_close', {'share': '-x'}], ['samba_access', {'uid': 1000, 'group': '1000', 'path': '/etc/shadow', 'readonly': True}],
                   ['samba_account', {'name': 'x; id', 'uid': 1501}], ['samba_identity', {'area': '../../etc'}])
    assert all(reply.get('status') == 400 for reply in refusals), refusals
    assert inspect()['State']['Running']
    out['refused_requests'] = len(refusals)

    # 5. La console ne peut plus détourner ni la description des services, ni les variables, ni les montages.
    description = ROOT / 'compose.yaml'
    description.write_text(description.read_text().replace('  fichiers:\n', '  fichiers:\n    privileged: true\n    pid: host\n', 1))
    with (ROOT / '.env').open('a') as env:
        env.write('COMPOSE_FILE=/home/ubuntu/piege.yaml\nCOMPOSE_PROJECT_NAME=piege\n')
    Path('/home/ubuntu/piege.yaml').write_text('services:\n  fichiers:\n    privileged: true\n')
    assert 'result' in one('recreate_files') and running()
    state = inspect()
    assert state['Id'] != identity and state['HostConfig']['Privileged'] is False and state['HostConfig']['PidMode'] in ('', 'private'), state['HostConfig']
    assert state['Config']['Labels']['com.docker.compose.project'] == 'nas-autonome-lab'
    out['tampered_description_ignored'] = True
    mounts = ROOT / 'state/samba/volumes.compose.json'

    def demand(source, target='/shares/native_banc'):
        mounts.write_text(json.dumps({'services': {'fichiers': {'volumes': [{'type': 'bind', 'source': str(source), 'target': target, 'read_only': False, 'bind': {'create_host_path': False}}]}}}))
        run('chown', 'ubuntu:ubuntu', str(mounts))
        return one('recreate_files')
    APPROVED.mkdir(exist_ok=True)
    (APPROVED / 'volume').mkdir(exist_ok=True)
    (APPROVED / 'volume/temoin.txt').write_text('approuvé\n')
    before = inspect()['Id']
    for source in ('/', '/etc', '/home/ubuntu', str(APPROVED / 'volume')):   # aucun emplacement approuvé pour l'instant
        assert demand(source) == {'error': 'Montage de partage non approuvé par la politique système.', 'status': 400}, source
    assert one('status')['status'] == 400 and inspect()['Id'] == before and inspect()['State']['Running']
    POLICY.write_text(json.dumps({**json.loads(POLICY.read_text()), 'mount_roots': [str(APPROVED)]}))
    (APPROVED / 'evasion').symlink_to('/etc')
    for source in ('/etc', str(APPROVED / 'evasion'), str(APPROVED) + '/../../etc'):
        assert demand(source)['status'] == 400, source
    assert 'result' in demand(APPROVED / 'volume') and running()
    binds = {mount['Destination']: mount for mount in inspect()['Mounts']}
    assert binds['/shares/native_banc']['Source'] == str(APPROVED / 'volume') and run('docker', 'exec', CONTAINER, 'cat', '/shares/native_banc/temoin.txt') == 'approuvé'
    assert '/etc' not in [mount['Source'] for mount in inspect()['Mounts']]
    out['mounts'] = {'refused': 7, 'approved': 1}
    mounts.unlink()
    assert 'result' in one('recreate_files') and running()

    # 6. Agent arrêté : la console n'a plus aucun accès, et le dit comme une indisponibilité.
    run('systemctl', 'stop', 'nacre-services.service')
    stopped = one('status')
    assert 'error' in stopped and inspect()['State']['Running'], stopped
    out['without_agent_no_access'] = stopped
    run('systemctl', 'start', 'nacre-services.service')
    for _ in range(50):
        if 'result' in one('status'):
            break
        time.sleep(.2)
    assert 'result' in one('samba_ping')
    assert run('systemctl', 'is-active', 'nacre-services.service') == 'active'
    RESULTS.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    guard()
    console(json.loads(sys.argv[2])) if sys.argv[1:2] == ['console'] else main()
