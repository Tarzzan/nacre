#!/usr/bin/env python3
"""Banc de la migration d'une installation EN SERVICE vers l'agent de services, et du retour arrière.

UNIQUEMENT dans la VM QEMU jetable du banc de l'agent (Docker, image Samba, compte ubuntu dans le groupe docker).
Pendant toute la campagne, une session SMB reste ouverte et écrit dans le partage, et un processus « console » reste
en vie sous le compte ubuntu : le banc vérifie que la migration ne coupe ni l'une ni l'autre, que le conteneur n'est
jamais recréé, et que chaque geste se défait.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import integration_service_agent_vm as base

RESULTS = Path('/home/ubuntu/service-migration-results.json')
ROOT, CONTAINER, POLICY, run = base.ROOT, base.CONTAINER, base.POLICY, base.run


def resident():
    """Processus de longue durée sous le compte de la console, comme le serveur web : garde les groupes qu'il avait en démarrant."""
    assert os.geteuid() == 1000
    os.environ['NAS_ROOT'] = str(ROOT)
    sys.path[:0] = [str(ROOT), str(ROOT / 'console')]
    import server
    for line in sys.stdin:
        if line.strip() == 'direct':
            answer = subprocess.run(['docker', 'ps', '-q'], capture_output=True).returncode == 0
        else:
            try:
                answer = bool(server.service_op('status'))
            except (server.Problem, OSError, subprocess.TimeoutExpired):
                answer = False
        print(json.dumps(answer), flush=True)


class Resident:
    def __init__(self):
        self.process = subprocess.Popen(['runuser', '-u', 'ubuntu', '--', 'env', 'NACRE_VM_LAB=1', 'python3', str(Path(__file__).resolve()), 'resident'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def ask(self, question):
        self.process.stdin.write(question + '\n')
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def stop(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


class Session:
    """Une seule session SMB, ouverte avant la migration et jamais rouverte : chaque écriture prouve qu'elle tient encore."""
    def __init__(self):
        password = (ROOT / 'state/smb_password').read_text().strip()
        self.process = subprocess.Popen(['docker', 'exec', '-i', CONTAINER, 'smbclient', '//127.0.0.1/fichiers', '-U', 'nas%' + password],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.count = 0

    def write(self, label):
        """Dépose un fichier par la session ouverte ; il doit apparaître sur l'hôte."""
        name = f'continuite-{self.count:02d}-{label}.txt'
        self.process.stdin.write(f'put /etc/hostname {name}\n')
        self.process.stdin.flush()
        for _ in range(50):
            if (ROOT / 'data/fichiers' / name).exists():
                self.count += 1
                return True
            time.sleep(.1)
        raise AssertionError('Session SMB interrompue à l’étape : ' + label)

    def close(self):
        output, _ = self.process.communicate('quit\n', timeout=20)
        assert self.process.returncode == 0 and 'NT_STATUS' not in output, output[-400:]
        return self.count


def flags(path):
    value = os.statvfs(path).f_flag
    return bool(value & os.ST_NOSUID and value & os.ST_NODEV)


def main():
    out = {}
    identity = base.prepare()
    started = base.inspect()['State']['StartedAt']
    session, console = Session(), Resident()
    session.write('avant')
    assert console.ask('direct') is True and console.ask('services') is True

    def unchanged(step):
        state = base.inspect()
        assert state['Id'] == identity and state['State']['StartedAt'] == started and state['State']['Running'], 'Conteneur recréé ou redémarré à l’étape : ' + step
        session.write(step)

    # 1. Poser l'agent et préparer la protection : rien ne bouge encore.
    from install_services import protections, stage
    stage('/', 1000, ROOT, protect=True)
    run('systemctl', 'daemon-reload')
    units = [Path(name).name for name in protections(ROOT)]
    unchanged('agent-pose')
    # 2. Protéger les dossiers de données, console et service en marche.
    run('systemctl', 'enable', '--now', *units)
    assert flags(ROOT / 'data/fichiers') and flags(ROOT / 'state/frigate')
    unchanged('dossiers-proteges')
    assert console.ask('services') is True
    # 3. Exiger la protection, puis démarrer l'agent : la console en marche passe par lui dès que son socket existe.
    POLICY.write_text(json.dumps({**json.loads(POLICY.read_text()), 'require_protected_mounts': True}))
    run('systemctl', 'enable', '--now', 'nacre-services.service')
    for _ in range(50):
        if Path('/run/nacre-services/control.sock').exists():
            break
        time.sleep(.1)
    assert console.ask('services') is True and console.ask('direct') is True     # accès encore double
    unchanged('agent-demarre')
    # 4. Sortir le compte du groupe docker. Un processus déjà lancé garde ses groupes : la console doit être relancée.
    run('gpasswd', '-d', 'ubuntu', 'docker')
    out['running_console_keeps_access_until_restart'] = console.ask('direct')
    assert out['running_console_keeps_access_until_restart'] is True
    console.stop()
    console = Resident()
    assert console.ask('direct') is False and console.ask('services') is True
    unchanged('compte-sorti-du-groupe')
    replies = base.ask(['samba_reload', {}], ['samba_group', {}], ['protection', {}], ['engine', {}])
    assert all('result' in reply for reply in replies) and replies[2]['result']['protected'] is True and replies[2]['result']['required'] is True, replies
    unchanged('operations-par-l-agent')
    out['migrated'] = {'same_container': True, 'smb_session_kept': True, 'console_without_docker': True, 'folders_protected': True}

    # 5. Retour arrière, dans l'ordre inverse : la console reprend la main, toujours sans coupure.
    run('systemctl', 'disable', '--now', 'nacre-services.service')
    assert console.ask('services') is False       # ni agent, ni accès direct : indisponible, mais le service de fichiers tourne
    unchanged('agent-arrete')
    run('gpasswd', '-a', 'ubuntu', 'docker')
    console.stop()
    console = Resident()
    assert console.ask('direct') is True and console.ask('services') is True
    unchanged('compte-revenu-dans-le-groupe')
    released = subprocess.run(['systemctl', 'disable', '--now', *units], capture_output=True, text=True)
    out['mounts_released_live'] = released.returncode == 0 and not flags(ROOT / 'data/fichiers')
    unchanged('retour-arriere-termine')
    assert 'result' in base.one('samba_reload')
    out['rolled_back'] = {'same_container': True, 'smb_session_kept': True, 'console_drives_docker_again': True}

    console.stop()
    out['smb_writes_through_one_session'] = session.close()
    assert out['smb_writes_through_one_session'] == 9
    assert base.inspect()['Id'] == identity
    RESULTS.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    base.guard()
    resident() if sys.argv[1:2] == ['resident'] else main()
