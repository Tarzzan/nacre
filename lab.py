#!/usr/bin/env python3
"""Gestion du laboratoire uniquement, sans administration des disques de l'hôte."""
import argparse
from datetime import datetime, timezone
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote
from compose_support import arguments as compose_arguments

ROOT = Path(__file__).resolve().parent


def private_write(path, text):
    """Remplacement atomique; aucune fenêtre avec un fichier lisible par tous."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.nas-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def camera_config(ip, username, password):
    address = str(ipaddress.IPv4Address(ip))
    if not username or not password or any(c in username + password for c in '\r\n\x00'):
        raise ValueError('Identifiants vides ou caractères de contrôle non acceptés.')
    base = f'rtsp://{quote(username, safe="")}:{quote(password, safe="")}@{address}:554'
    return {
        'streams': {'tapo': [base + '/stream1'], 'tapo_sub': [base + '/stream2']},
        'camera': {
            'ffmpeg': {'inputs': [
                {'path': 'rtsp://127.0.0.1:8554/tapo', 'input_args': 'preset-rtsp-restream', 'roles': ['record']},
                {'path': 'rtsp://127.0.0.1:8554/tapo_sub', 'input_args': 'preset-rtsp-restream', 'roles': ['detect']},
            ]},
            'detect': {'enabled': False, 'fps': 5},
            'record': {'enabled': True, 'continuous': {'days': 1}},
        },
    }


def initial_config():
    return {'mqtt': {'enabled': False}, 'auth': {'enabled': True},
            'detect': {'enabled': False}, 'cameras': {}}


def initialize(root=ROOT):
    from platform_config import configure
    configure(root)
    state = root / 'state'
    state.mkdir(mode=0o700, exist_ok=True)
    (state / 'frigate').mkdir(mode=0o700, exist_ok=True)
    (state / 'samba').mkdir(mode=0o700, exist_ok=True)
    for directory in ('data/fichiers', 'data/video'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / 'data/fichiers').chmod(0o770)
    password = state / 'smb_password'
    if not password.exists():
        private_write(password, secrets.token_urlsafe(24) + '\n')
    config = state / 'frigate/config.yml'
    if not config.exists():
        private_write(config, json.dumps(initial_config(), indent=2) + '\n')


def compose(*args):
    subprocess.run(compose_arguments(ROOT,*args),
                   cwd=ROOT, check=True)


def load_config(path):
    text = Path(path).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Frigate normalise et migre le JSON initial en YAML au premier démarrage.
        # Utiliser son parseur installé, en conservant le résultat dans un pipe privé.
        result = subprocess.run(
            compose_arguments(ROOT, 'exec', '-T',
             'video', 'python3', '-c',
             'import json,sys,yaml; print(json.dumps(yaml.safe_load(sys.stdin.read())))'),
            cwd=ROOT, input=text, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Lecture YAML impossible. Démarrer le service vidéo avant de configurer la caméra.')
        return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('init', 'start', 'stop', 'status', 'acces', 'web'):
        sub.add_parser(name)
    add = sub.add_parser('camera', help='Saisir localement le compte caméra Tapo')
    add.add_argument('--ip', default='192.168.1.32')
    args = parser.parse_args()
    if args.action == 'init':
        initialize()
        print('Laboratoire initialisé. Aucun identifiant affiché.')
    elif args.action == 'camera':
        initialize()
        ipaddress.IPv4Address(args.ip)
        username = input('Identifiant du compte caméra LOCAL Tapo : ').strip()
        password = getpass.getpass('Mot de passe caméra (saisie masquée) : ')
        camera = camera_config(args.ip, username, password)
        path = ROOT / 'state/frigate/config.yml'
        config = load_config(path)
        config.setdefault('go2rtc', {}).setdefault('streams', {}).update(camera['streams'])
        config.setdefault('cameras', {})['tapo'] = camera['camera']
        backup = path.with_name('config-avant-camera.json')
        private_write(backup, path.read_text())
        private_write(path, json.dumps(config, indent=2) + '\n')
        print('Configuration enregistrée avec permissions 0600. Redémarrage vidéo…')
        compose('restart', 'video')
    elif args.action == 'start':
        initialize()
        (ROOT/'state/console').mkdir(parents=True,exist_ok=True,mode=0o700)
        private_write(ROOT/'state/console/smb-intent.json',json.dumps({'enabled':True}))
        shares = None
        if (ROOT/'state/console/smb.json').exists():
            from console import server
            shares = server.shares()
            shares.prepare_start(server.smb_state())
        compose('up', '-d', '--no-build' if (ROOT/'state/samba/recovery.compose.json').exists() else '--build')
        if shares:
            shares.apply(server.smb_state())
    elif args.action == 'stop':
        (ROOT/'state/console').mkdir(parents=True,exist_ok=True,mode=0o700)
        private_write(ROOT/'state/console/smb-intent.json',json.dumps({'enabled':False}))
        compose('stop')
    elif args.action == 'web':
        subprocess.run([sys.executable, str(ROOT / 'console/server.py'), 'ticket'], check=True)
    elif args.action == 'acces':
        print('Identifiants affichés uniquement dans ce terminal. Ne pas partager cette sortie.')
        print('SMB — utilisateur : nas ; mot de passe :', (ROOT / 'state/smb_password').read_text().strip())
        console_access = ROOT / 'state/console/acces.txt'
        if console_access.exists():
            print('\n' + console_access.read_text())
        result = subprocess.run(compose_arguments(ROOT,'logs','--no-log-prefix','video'),
                                cwd=ROOT, capture_output=True, text=True, check=True)
        passwords = re.findall(r'\*\*\*\s+Password:\s+(\S+)', result.stdout)
        if passwords:
            print('Frigate — utilisateur : admin ; mot de passe INITIAL :', passwords[-1])
            print('Changer ce mot de passe dans les paramètres Frigate après connexion.')
        else:
            print('Mot de passe initial absent des journaux. Utiliser le mot de passe déjà défini dans Frigate.')
    elif args.action == 'status':
        compose('ps')
        usage = shutil.disk_usage(ROOT)
        print(f'Espace libre du volume hôte : {usage.free / 1024**4:.2f} Tio')
        files = list((ROOT / 'data/video/recordings').rglob('*.mp4'))
        print(f'Segments vidéo : {len(files)}')
        if files:
            latest = max(files, key=lambda p: p.stat().st_mtime)
            print('Dernière écriture UTC :', datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc).isoformat())


if __name__ == '__main__':
    sys.path.insert(0,str(Path(__file__).parent/'console'))
    from installation_lock import held
    with held(ROOT):
        main()
