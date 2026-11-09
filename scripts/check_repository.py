#!/usr/bin/env python3
"""Contrôle des chemins suivis ; complément au scanner de secrets."""
from pathlib import PurePosixPath
import subprocess
import sys

files = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
forbidden = {'state', 'data', '.tools', '.venv', '__pycache__', 'work'}
suffixes = ('.pem', '.key', '.db', '.sqlite', '.sqlite3', '.qcow2', '.raw', '.img', '.iso', '.log', '.tar.gz', '.zip')
bad = []
for name in filter(None, files):
    path = PurePosixPath(name)
    if forbidden.intersection(path.parts) or path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example') or path.name.endswith(suffixes) or path.name.startswith(('id_rsa', 'id_ed25519')):
        bad.append(name)
if bad:
    print('Fichiers de déploiement interdits dans Git :', *bad, sep='\n')
    sys.exit(1)
print('Contrôle des chemins suivis : OK')
