"""Version déclarée par le code installé, indépendante du répertoire des données."""
from pathlib import Path
import re


def version():
    try:
        changelog=(Path(__file__).resolve().parents[1]/'CHANGELOG.md').read_text(encoding='utf-8')
    except (OSError,UnicodeError):return 'version non identifiée'
    match=re.search(r'^## (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)\s+—',changelog,re.M)
    return match[1] if match else 'version non identifiée'
