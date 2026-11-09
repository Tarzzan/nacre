"""Profil d’installation Linux, sans nom d’hôte ni identifiant utilisateur imposé."""
import os
from pathlib import Path
import platform
import re

IMAGES = {
    'amd64': 'ghcr.io/blakeblackshear/frigate:0.18.2@sha256:fd60f99ffd4eb6c42360ed4e14953e270586f239309ab3983e55b2e97ffac09a',
    'arm64': 'ghcr.io/blakeblackshear/frigate:0.18.2-standard-arm64@sha256:4a854373c0fd4a8f550518758e34b929be0b423085bb569bb232390d128fa4ef',
}


def profile(machine=None, uid=None, gid=None):
    arch = {'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(machine or platform.machine())
    if arch not in IMAGES:
        raise RuntimeError('Architecture vidéo non reconnue. Linux x86-64 et ARM64 sont pris en charge.')
    uid, gid = os.getuid() if uid is None else uid, os.getgid() if gid is None else gid
    if uid == 0 or gid == 0:
        raise RuntimeError('Installer la console sous un compte utilisateur dédié non root.')
    return {'NACRE_FRIGATE_IMAGE':IMAGES[arch], 'NACRE_UID':str(uid), 'NACRE_GID':str(gid)}


def configure(root):
    path = Path(root) / '.env'
    text = path.read_text() if path.exists() else ''
    existing = set(re.findall(r'^([A-Z_][A-Z_0-9]*)\s*=',text,re.M))
    values = profile()
    additions = ''.join(key+'='+value+'\n' for key,value in values.items() if key not in existing)
    if additions:
        descriptor = os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'a') as output:
            os.fchmod(output.fileno(),0o600)
            output.write(('\n' if text and not text.endswith('\n') else '')+additions)
    return values
