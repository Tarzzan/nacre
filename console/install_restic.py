#!/usr/bin/env python3
"""Installer le runtime versionné officiel dans le projet, sur Linux ARM64 ou x86-64."""
import bz2
import hashlib
import os
from pathlib import Path
import platform
import tempfile
from urllib.request import urlopen

VERSION = '0.19.1'
CHECKSUMS = {
    'amd64': 'f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c',
    'arm64': 'a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465',
}


def install(root):
    if platform.system() != 'Linux':
        raise RuntimeError('Cet installateur cible les NAS Linux.')
    architecture = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if architecture not in CHECKSUMS:
        raise RuntimeError('Installer manuellement un runtime restic compatible avec cette architecture.')
    directory = Path(root) / '.tools'
    directory.mkdir(mode=0o700, exist_ok=True, parents=True)
    name = f'restic_{VERSION}_linux_{architecture}.bz2'
    with tempfile.TemporaryFile() as archive:
        checksum = hashlib.sha256()
        with urlopen(f'https://github.com/restic/restic/releases/download/v{VERSION}/{name}', timeout=60) as response:
            while data := response.read(1024**2):
                checksum.update(data)
                archive.write(data)
        if checksum.hexdigest() != CHECKSUMS[architecture]:
            raise RuntimeError('Le contrôle SHA-256 du runtime a échoué.')
        archive.seek(0)
        fd, temporary = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, 'wb') as output, bz2.BZ2File(archive) as source:
                while data := source.read(1024**2):
                    output.write(data)
                os.fchmod(output.fileno(), 0o755)
            os.replace(temporary, directory / 'restic')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return directory / 'restic'


if __name__ == '__main__':
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    print('Runtime officiel vérifié :', install(target))
