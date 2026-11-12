#!/usr/bin/env python3
"""Préparer les prérequis Ubuntu de Nacre ; affiche un plan sans --apply."""
import argparse
import os
from pathlib import Path
import platform
import pwd
import re
import shlex
import shutil
import subprocess

PACKAGES = ('ca-certificates', 'openssl', 'dbus-user-session', 'docker.io', 'docker-compose-v2', 'docker-buildx')
CONFLICTS = ('docker-ce', 'docker-ce-cli', 'containerd.io', 'podman-docker', 'docker-compose')


def installed_packages():
    result = subprocess.run(['dpkg-query', '-W', '-f=${Package} ${db:Status-Status}\n', *PACKAGES, *CONFLICTS],
                            capture_output=True, text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError('Inventaire des paquets indisponible.')
    return {line.split()[0] for line in result.stdout.splitlines() if line.endswith(' installed')}


def make_plan(username, release, architecture, packages):
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '24.04':
        raise ValueError('Préparation automatique limitée à Ubuntu 24.04. Utiliser la préparation manuelle sur ce système.')
    if architecture not in ('x86_64', 'aarch64'):
        raise ValueError('Architecture non prise en charge : x86-64 ou ARM64 requis.')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', username):
        raise ValueError('Nom de compte local non pris en charge.')
    account = pwd.getpwnam(username)
    if account.pw_uid < 1000 or account.pw_shell.endswith(('/nologin', '/false')):
        raise ValueError('Choisir un compte utilisateur non root disposant d’une session.')
    if set(CONFLICTS) & packages:
        raise ValueError('Une autre distribution Docker/Compose est installée. Elle est conservée ; préparer cet hôte manuellement.')
    if shutil.which('docker') and 'docker.io' not in packages:
        raise ValueError('Docker existe hors du paquet Ubuntu ; préparer cet hôte manuellement.')
    missing = [name for name in PACKAGES if name not in packages]
    commands = []
    if missing:
        commands += [['apt-get', 'update'], ['apt-get', 'install', '-y', '--no-remove', '--no-install-recommends', *missing]]
    commands += [['systemctl', 'enable', '--now', 'docker'],
                 ['usermod', '--append', '--groups', 'docker', username],
                 ['loginctl', 'enable-linger', username]]
    return commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True, help='Compte dédié existant qui exécutera Nacre.')
    parser.add_argument('--apply', action='store_true', help='Appliquer le plan avec les droits administrateur.')
    args = parser.parse_args()
    try:
        if not Path('/run/systemd/system').is_dir():
            raise ValueError('Un Linux démarré avec systemd est requis.')
        commands = make_plan(args.user, platform.freedesktop_os_release(), platform.machine(), installed_packages())
        print('Préparation Ubuntu 24.04 — paquets de la distribution, accès Docker et service utilisateur persistant.')
        print('Le groupe Docker donne un accès privilégié à l’hôte. Aucun disque ni port réseau Nacre n’est configuré.')
        for command in commands:
            print('  '+shlex.join(command), flush=True)
        if not args.apply:
            print('Plan uniquement. Ajouter --apply avec sudo pour l’exécuter.')
            return
        if os.geteuid() != 0:
            raise ValueError('--apply nécessite sudo ; Nacre lui-même doit ensuite être lancé sans sudo.')
        for command in commands:
            subprocess.run(command, check=True, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})
        print('Préparation terminée. Sous le compte choisi : python3 installer.py --service')
        print('Les nouveaux droits Docker nécessitent une nouvelle session complète. Un redémarrage planifié les applique aussi aux services utilisateur ; aucun redémarrage automatique.')
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\nLa préparation peut être partielle ; corriger la cause puis relancer. Aucun paquet n’est supprimé automatiquement.\n')


if __name__ == '__main__':
    main()
