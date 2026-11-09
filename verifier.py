#!/usr/bin/env python3
"""Vérifications réelles des services du laboratoire, sans filmer la caméra."""
import json
from pathlib import Path
import subprocess
import sys

from lab import ROOT, camera_config, initial_config
from compose_support import arguments


def execute(service, command, data=None):
    result = subprocess.run(
        arguments(ROOT,'exec','-T',service,*command),
        cwd=ROOT, input=data, text=True, capture_output=True)
    if result.returncode:
        # Ne pas recopier les sorties : une erreur d'un outil peut contenir un secret.
        raise RuntimeError(f'Échec de la vérification du service {service} (code {result.returncode}).')
    return result.stdout.strip()


def main():
    config = initial_config()
    example = camera_config('192.168.1.32', 'compte-test', 'mot-de-passe-test')
    config['go2rtc'] = {'streams': example['streams']}
    config['cameras']['tapo'] = example['camera']
    program = '''
import json, sys, warnings
from frigate.config import FrigateConfig
import requests
warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
FrigateConfig.model_validate(json.load(sys.stdin))
r=requests.get("http://127.0.0.1:5000/api/version",timeout=10)
assert r.status_code==200
print("Frigate:",r.text)
r=requests.get("https://127.0.0.1:8971/api/config",verify=False,timeout=10)
assert r.status_code==401
print("Schéma caméra valide; API protégée (401 sans connexion).")
'''
    print(execute('video', ['python3', '-c', program], json.dumps(config)))
    samba = r'''
set -eu
umask 077
directory=$(mktemp -d)
marker=validation-nas-$(cat /proc/sys/kernel/random/uuid).txt
trap 'rm -rf "$directory"' EXIT
{
  printf 'username = nas\npassword = '
  cat /run/secrets/smb_password
} > "$directory/auth"
printf 'validation du partage SMB\n' > "$directory/source"
smbclient //127.0.0.1/fichiers -A "$directory/auth" -c "put $directory/source $marker; get $marker $directory/copied; del $marker" >/dev/null 2>&1
cmp "$directory/source" "$directory/copied"
if smbclient //127.0.0.1/fichiers -N -c ls >/dev/null 2>&1; then exit 2; fi
if smbclient //127.0.0.1/video -A "$directory/auth" -c "put $directory/source $marker" >/dev/null 2>&1; then
  echo 'Écriture vidéo autorisée à tort'; exit 3
fi
echo 'SMB: écriture/relecture vérifiées; accès anonyme refusé; partage vidéo en lecture seule.'
'''
    print(execute('fichiers', ['sh', '-c', samba]))
    print('Les contrôles du direct, du PTZ et des clips sont disponibles dans la console Nacre et dans VALIDATION.json.')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
