# Composants et provenance

Nacre assemble son code de console et des composants installés séparément. Les exécutables, images Docker et données de déploiement ne sont pas inclus dans Git.

| Composant | Usage | Référence primaire |
| --- | --- | --- |
| Python | Console, orchestration, tests | https://www.python.org/ |
| Docker / Compose | Services vidéo et fichiers | https://docs.docker.com/compose/ |
| Samba | Partages SMB | https://www.samba.org/ |
| Frigate | Vidéosurveillance | https://github.com/blakeblackshear/frigate |
| restic 0.19.1 | Sauvegardes chiffrées | https://github.com/restic/restic/releases/tag/v0.19.1 |
| util-linux, e2fsprogs, btrfs-progs | Inventaire, montages et FS | Paquets de la distribution cible |
| mdadm, LVM2, OpenZFS | RAID et snapshots optionnels | Paquets de la distribution cible |
| QEMU / Ubuntu | Banc d’intégration isolé | Voir `tests/VM-LAB.txt` |
| Gitleaks | Détection de secrets dans les sources | https://github.com/gitleaks/gitleaks |

Les versions et empreintes effectivement utilisées figurent dans `compose.yaml`, `platform_config.py`, `console/install_restic.py` et le rapport de validation. Les licences et avis de chaque composant restent applicables ; une revue de redistribution est nécessaire avant une image installable ou une diffusion publique. Ce document est un inventaire initial, pas un SBOM exhaustif.
