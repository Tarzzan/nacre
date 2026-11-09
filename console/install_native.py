#!/usr/bin/env python3
"""Préparer ou installer le service système optionnel ; jamais de formatage."""
import argparse
import json
import os
from pathlib import Path
import shutil
import secrets
import stat
import subprocess


UNIT = '''[Unit]
Description=Nacre - snapshots natifs autorises
After=local-fs.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -I /usr/local/lib/nacre-storage/native_storage.py
User=root
UMask=0077
RuntimeDirectory=nacre-storage
RuntimeDirectoryMode=0755
StateDirectory=nacre-storage
StateDirectoryMode=0700
Restart=on-failure
NoNewPrivileges=yes
# Les montages doivent être visibles dans le namespace de l'hôte.
PrivateMounts=no
RestrictAddressFamilies=AF_UNIX AF_NETLINK
LockPersonality=yes
RestrictRealtime=yes

[Install]
WantedBy=multi-user.target
'''


def stage(target, uid):
    if uid <= 0:
        raise ValueError('Utiliser l’UID du compte non root exécutant la console.')
    target = Path(target)
    files = {'usr/local/lib/nacre-storage/native_storage.py': Path(__file__).with_name('native_storage.py').read_text(),
             'etc/nacre-storage/policy.json': json.dumps({'version': 1, 'allowed_uid': uid, 'volumes': []}, indent=2) + '\n',
             'etc/systemd/system/nacre-storage.service': UNIT}
    for name in ('provisioning.py','native_restore.py'):
        files['usr/local/lib/nacre-storage/'+name]=Path(__file__).with_name(name).read_text()
    for name, content in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if target == Path('/'):
            if os.geteuid()!=0:raise ValueError('Installation système réservée à root.')
            from native_storage import trusted_directory, NativeError
            with trusted_directory(path.parent) as parent:
                meta=os.fstat(parent)
                if meta.st_uid!=0 or meta.st_mode&0o022:raise NativeError('Répertoire d’installation non protégé par root.')
                try:
                    fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=parent)
                except FileNotFoundError:fd=None
                if fd is not None:
                    try:
                        meta=os.fstat(fd)
                        if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=0 or meta.st_mode&0o022 or meta.st_nlink!=1:
                            raise NativeError('Fichier d’installation existant non protégé.')
                    finally:os.close(fd)
                    if name.endswith('policy.json'):continue
                temporary='.nacre-install-'+secrets.token_hex(12)
                fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                try:
                    with os.fdopen(fd,'w') as output:
                        output.write(content);output.flush();os.fsync(output.fileno())
                        os.fchmod(output.fileno(),0o600 if name.endswith('policy.json') else 0o644)
                    os.replace(temporary,path.name,src_dir_fd=parent,dst_dir_fd=parent)
                finally:
                    try:os.unlink(temporary,dir_fd=parent)
                    except FileNotFoundError:pass
            continue
        # Une politique existante ne doit jamais être écrasée par une mise à jour.
        if name.endswith('policy.json') and path.exists():
            continue
        path.write_text(content)
        path.chmod(0o600 if name.endswith('policy.json') else 0o644)
    return files


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', type=int, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--stage', type=Path, help='Préparer les fichiers dans ce dossier, sans installation système.')
    selection.add_argument('--install', action='store_true', help='Installation explicite comme root ; service non activé.')
    args = parser.parse_args()
    if args.install and os.geteuid() != 0:
        parser.error('--install nécessite root sur le matériel cible.')
    stage(args.stage if args.stage else '/', args.uid)
    if args.install:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print('Fichiers préparés. Aucun volume inscrit ; aucune opération de stockage exécutée. Le service reste à activer explicitement.')
