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
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--service',action='store_true',help='Installer et démarrer la console comme service utilisateur persistant.')
    parser.add_argument('--port',type=int,default=8766,help='Port local de la console (1024–65535).')
    mode.add_argument('--prepare-only', action='store_true', help='Préparer sans lancer la console au premier plan.')
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    try:
        if not 1024 <= args.port <= 65535:
            raise RuntimeError("Port attendu entre 1024 et 65535.")
        if os.geteuid() == 0:
            raise RuntimeError("Lancer Nacre sous son compte dédié, sans sudo.")
        prepare(root)
        if args.service:
            from console.install_service import install
            install(root,args.port)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')
    print(f'Nacre est prêt. Accès local : http://127.0.0.1:{args.port}/', flush=True)
    print('Dans un second terminal, afficher le compte provisoire : python3 lab.py acces', flush=True)
    print(f'À distance : ssh -N -L {args.port}:127.0.0.1:{args.port} votre-serveur', flush=True)
    if not args.prepare_only and not args.service:
        os.environ['NAS_PORT']=str(args.port)
        os.execv(sys.executable, [sys.executable, str(root/'console/server.py')])


if __name__ == '__main__':
    main()
