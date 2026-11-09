"""Même description Compose pour l'installation, la console et les contrôles."""
from pathlib import Path


def arguments(root, *args, override=None):
    root=Path(root)
    candidate=Path(override) if override is not None else root/'state/samba/volumes.compose.json'
    result=['docker','compose','-f',str(root/'compose.yaml')]
    if candidate.exists():result+=['-f',str(candidate)]
    return [*result,*args]
