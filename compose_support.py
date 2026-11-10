"""Même description Compose pour l'installation, la console et les contrôles."""
from pathlib import Path
import json
import re


def arguments(root, *args, override=None):
    root=Path(root)
    candidate=Path(override) if override is not None else root/'state/samba/volumes.compose.json'
    result=['docker','compose']
    receipt=root/'state/console/system-recovery-status.json'
    if any(a in ('up','start','restart') for a in args) and receipt.exists() and not (root/'state/samba/recovery.compose.json').exists():
        raise ValueError('Préparer l’état Samba récupéré avant de démarrer les services.')
    recovery=root/'state/console/recovery-project.json'
    if recovery.exists():
        project=json.loads(recovery.read_text())['project']
        if not re.fullmatch(r'nacre-recovered-[a-f0-9]{24}',project):raise ValueError('Projet de reprise invalide.')
        result+=['--project-name',project]
    result+=['-f',str(root/'compose.yaml')]
    recovered=root/'state/samba/recovery.compose.json'
    if recovered.exists():result+=['-f',str(recovered)]
    if candidate.exists():result+=['-f',str(candidate)]
    return [*result,*args]
