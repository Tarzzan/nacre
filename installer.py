#!/usr/bin/env python3
"""Préparer Nacre et ouvrir son assistant local, sans démarrer de conteneur."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys


def prepare(root):
    if platform.system() != 'Linux' or sys.version_info < (3, 11):
        raise RuntimeError('Nacre nécessite Linux et Python 3.11 ou plus récent.')
    from lab import initialize
    initialize(root)
    subprocess.run([sys.executable, str(root/'console/server.py'), 'init'],
                   env={**os.environ, 'NAS_ROOT': str(root)}, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true', help='Préparer sans lancer la console au premier plan.')
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    try:
        prepare(root)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')
    print('Nacre est prêt. Accès local : http://127.0.0.1:8766/', flush=True)
    print('Dans un second terminal, afficher le compte provisoire : python3 lab.py acces', flush=True)
    print('À distance : ssh -N -L 8766:127.0.0.1:8766 votre-serveur', flush=True)
    if not args.prepare_only:
        os.execv(sys.executable, [sys.executable, str(root/'console/server.py')])


if __name__ == '__main__':
    main()
