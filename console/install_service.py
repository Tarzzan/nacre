#!/usr/bin/env python3
"""Installation utilisateur portable ; aucun dépôt et aucun plan ne sont créés."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import socket
import time
import re
if __package__:
    from .update_engine import provision
else:
    from update_engine import provision


def unit_text(root, executable=sys.executable, port=8766):
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("Port utilisateur attendu entre 1024 et 65535.")
    root=Path(root).resolve()
    def quote(value):
        if '\n' in str(value) or '\r' in str(value):
            raise ValueError('Chemin non pris en charge.')
        return json.dumps(str(value).replace('%','%%'),ensure_ascii=False)
    return f'''[Unit]
Description=Nacre - Console NAS locale

[Service]
Type=simple
WorkingDirectory={str(root).replace('%','%%')}
ExecStart=:{quote(executable)} {quote(root / 'state/console/updates/runtime.py')} {quote(root)} {port}
Environment=NACRE_SYSTEMD_TASKS=1
Environment=NAS_PORT={port}
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
MemoryMax=384M

[Install]
WantedBy=default.target
'''


def install(root, port=8766):
    if os.geteuid() == 0:
        raise ValueError('Installer le service sous le compte Nacre, sans sudo.')
    root=Path(root).resolve()
    content=unit_text(root, port=port)
    directory=Path.home()/'.config/systemd/user'
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'nacre-console.service'
    if path.is_symlink():
        raise ValueError('Le fichier de service est un lien symbolique ; installation refusée.')
    previous=path.read_text() if path.exists() else None
    if previous and ('WorkingDirectory='+str(root).replace('%','%%')) not in previous.splitlines():
        raise ValueError('Un service Nacre utilise une autre installation. Arrêter et déplacer ce service explicitement.')
    active=subprocess.run(['systemctl','--user','is-active','--quiet','nacre-console.service']).returncode == 0
    enabled=subprocess.run(['systemctl','--user','is-enabled','--quiet','nacre-console.service']).returncode == 0
    match=re.search(r'^Environment=NAS_PORT=(\d+)$',previous or '',re.M)
    old_port=int(match[1]) if match else 8766
    if not active or old_port != port:
        with socket.socket() as sock:
            try:sock.bind(('127.0.0.1',port))
            except OSError:raise ValueError('Le port est occupé. Arrêter la console au premier plan ou choisir --port.') from None
    with tempfile.TemporaryDirectory() as temporary:
        candidate=Path(temporary)/'nacre-console.service'
        candidate.write_text(content)
        subprocess.run(['systemd-analyze','--user','verify',str(candidate)],check=True)
    provision(root)
    from lab import private_write
    if previous:
        backup=path.with_suffix('.service.avant-nacre')
        if not backup.exists():private_write(backup,previous)
    private_write(path,content)
    try:
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','enable','nacre-console.service'],check=True)
        subprocess.run(['systemctl','--user','restart','nacre-console.service'],check=True)
        # Confirmer l'écoute locale, puis vérifier que le service reste actif.
        for attempt in range(50):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2):break
            except OSError:
                if attempt==49:raise RuntimeError('La console ne répond pas sur son port local.') from None
                time.sleep(.2)
        subprocess.run(['systemctl','--user','is-active','--quiet','nacre-console.service'],check=True)
    except Exception:
        if not active:subprocess.run(['systemctl','--user','stop','nacre-console.service'],check=False)
        if not enabled:subprocess.run(['systemctl','--user','disable','nacre-console.service'],check=False)
        if previous is not None:private_write(path,previous)
        else:path.unlink(missing_ok=True)
        subprocess.run(['systemctl','--user','daemon-reload'],check=False)
        if active:subprocess.run(['systemctl','--user','restart','nacre-console.service'],check=False)
        raise
    print('Service Nacre actif. Aucun dépôt ni plan de sauvegarde configuré.')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    from platform_config import configure
    try:
        configure(root)
        install(root,args.port)
    except (ValueError,RuntimeError,OSError,subprocess.CalledProcessError) as error:
        parser.exit(1,str(error)+'\n')
