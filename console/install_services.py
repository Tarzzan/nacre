#!/usr/bin/env python3
"""Préparer ou installer l'agent de services. Ne touche ni aux conteneurs, ni aux comptes, ni aux groupes du système."""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess

UNIT = '''[Unit]
Description=Nacre - agent de services a operations fermees
After=docker.service local-fs.target
Wants=docker.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -I /usr/local/lib/nacre-services/service_agent.py
User=root
UMask=0077
RuntimeDirectory=nacre-services
RuntimeDirectoryMode=0755
Restart=on-failure
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX AF_NETLINK AF_INET AF_INET6
LockPersonality=yes
RestrictRealtime=yes

[Install]
WantedBy=multi-user.target
'''


def files(uid, root):
    """Ce que l'agent exécute et ce à quoi il se fie : son code, sa copie de la description des services, sa politique."""
    if uid <= 0:
        raise ValueError('Utiliser l’UID du compte non root exécutant la console.')
    root = Path(root).resolve()
    here = Path(__file__).resolve().parent
    description = root / 'compose.yaml'
    if not description.is_file():
        raise ValueError('Installation introuvable : compose.yaml absent de ' + str(root) + '.')
    return {'usr/local/lib/nacre-services/service_agent.py': (here / 'service_agent.py').read_text(),
            'usr/local/lib/nacre-services/native_storage.py': (here / 'native_storage.py').read_text(),
            'usr/local/lib/nacre-services/compose.yaml': description.read_text(),
            'etc/nacre-services/policy.json': json.dumps({'version': 1, 'allowed_uid': uid, 'root': str(root), 'mount_roots': []}, indent=2) + '\n',
            'etc/systemd/system/nacre-services.service': UNIT}


def stage(target, uid, root):
    target = Path(target)
    prepared = files(uid, root)
    for name, content in prepared.items():
        path = target / name
        policy = name.endswith('policy.json')
        if target != Path('/'):
            path.parent.mkdir(parents=True, exist_ok=True)
            # Une politique existante n'est jamais écrasée : elle porte les emplacements approuvés par root.
            if policy and path.exists():
                continue
            path.write_text(content)
            path.chmod(0o600 if policy else 0o644)
            continue
        if os.geteuid() != 0:
            raise ValueError('Installation système réservée à root.')
        from native_storage import NativeError, trusted_directory
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        with trusted_directory(path.parent) as parent:
            meta = os.fstat(parent)
            if meta.st_uid != 0 or meta.st_mode & 0o022:
                raise NativeError('Répertoire d’installation non protégé par root.')
            try:
                existing = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if not stat.S_ISREG(existing.st_mode) or existing.st_uid != 0 or existing.st_mode & 0o022 or existing.st_nlink != 1:
                    raise NativeError('Fichier d’installation existant non protégé.')
                if policy:
                    continue
            temporary = '.nacre-install-' + secrets.token_hex(12)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'w') as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                    os.fchmod(output.fileno(), 0o600 if policy else 0o644)
                os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
    return prepared


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', type=int, required=True, help='UID du compte de la console.')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='Dossier de l’installation servie par l’agent.')
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--stage', type=Path, help='Préparer les fichiers dans ce dossier, sans installation système.')
    selection.add_argument('--install', action='store_true', help='Installation explicite comme root ; agent non activé.')
    args = parser.parse_args()
    if args.install and os.geteuid() != 0:
        parser.error('--install nécessite root sur le matériel cible.')
    stage(args.stage if args.stage else '/', args.uid, args.root)
    if args.install:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print('Fichiers préparés. L’agent reste à activer explicitement ; aucun conteneur, compte ni groupe n’a été modifié.')
