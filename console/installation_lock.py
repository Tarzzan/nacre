"""Exclusion entre activité Nacre et reprise hors ligne."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


def acquire(root, exclusive=False):
    directory=Path(root)/'state/console'
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(directory/'installation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:fcntl.flock(fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise RuntimeError('Installation occupée : arrêter la console et ses tâches avant une reprise hors ligne.') from None
    return fd


@contextmanager
def held(root, exclusive=False):
    fd=acquire(root,exclusive)
    try:yield
    finally:os.close(fd)
