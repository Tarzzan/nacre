#!/usr/bin/env python3
"""Installation utilisateur portable ; aucun dépôt et aucun plan ne sont créés."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def unit_text(root, executable=sys.executable):
    root=Path(root).resolve()
    def quote(value):
        if '\n' in str(value) or '\r' in str(value):
            raise ValueError('Chemin non pris en charge.')
        return json.dumps(str(value).replace('%','%%'),ensure_ascii=False)
    return f'''[Unit]
Description=Nacre - Console NAS locale
After=default.target

[Service]
Type=simple
WorkingDirectory={str(root).replace('%','%%')}
ExecStart=:{quote(executable)} {quote(root / 'console/server.py')}
Environment=NACRE_SYSTEMD_TASKS=1
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
MemoryMax=384M

[Install]
WantedBy=default.target
'''


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    from platform_config import configure
    configure(root)
    directory=Path.home()/'.config/systemd/user'
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'nacre-console.service'
    if path.exists():
        backup=path.with_suffix('.service.avant-nacre-v02')
        if not backup.exists():backup.write_text(path.read_text())
    content=unit_text(root)
    with tempfile.TemporaryDirectory() as directory:
        candidate=Path(directory)/'nacre-console.service'
        candidate.write_text(content)
        subprocess.run(['systemd-analyze','--user','verify',str(candidate)],check=True)
    path.write_text(content)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','nacre-console.service'],check=True)
    subprocess.run(['systemctl','--user','restart','nacre-console.service'],check=True)
    print('Console installée. Aucun dépôt et aucun plan de sauvegarde n’ont été configurés.')
