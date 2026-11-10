# Validation

## Coupure et reprise ARM64 — 0.7.0-alpha.2

94 tests Python, sans test ignoré avec restic vérifié, et 5 tests JavaScript. Les nouveaux refus couvrent membres absents/inattendus/défaillants, retrait de politique, catalogue modifié, journal absent, état incertain et MD explicitement `readonly`. Le test positif vérifie une demande `--readwrite` journalisée sans nouvel ajout.

Le banc [POWER-CUT-LAB.md](POWER-CUT-LAB.md) interrompt trois fois QEMU pendant une reconstruction active et incomplète. Les contrôles finaux comparent les UUID, les deux membres, le SHA-256 d’un fichier aléatoire de 64 Mio et celui de son snapshot. L’audit mdadm côté système invité ne doit compter qu’un seul `--add`. Le défaut `read-auto` observé après coupure a été corrigé ; la répétition finale utilise le correctif dès le départ.

La reprise ARM64 utilise deux VM Ubuntu 24.04 vierges successives sous KVM ARM64 : source arrêtée, cible sans images/volumes Docker ni catalogue natif. Clés historiques, comptes web/Samba, SID, UID et données sont contrôlés, puis un nouveau miroir est créé et soumis aux coupures. La connexion web et les droits Samba sont revérifiés après redémarrage. Frigate reste une fixture de configuration/base/octets vidéo, sans caméra réelle.

Les données chiffrées, clés et disques du banc restent hors de Git. Les résultats structurés distinguent coupure virtuelle et perte électrique matérielle : le cache du contrôleur physique et les écritures applicatives concurrentes ne sont pas qualifiés.

## Linux neuf et RAID1 — 0.7.0-alpha.1

90 tests Python, sans test ignoré avec restic vérifié, et 5 tests JavaScript. Six tests isolés couvrent les refus de reconstruction, les changements d’identité/politique, l’opérateur et la confirmation, l’état incomplet, l’échec sans rejeu et la validation du catalogue après contrôle physique.

Un Ubuntu 24.04 x86-64 vierge, sans ancienne image ni volume Docker, reçoit uniquement une sauvegarde synthétique et le code approuvé. La source est une VM séparée arrêtée. Le banc retrouve les clés et comptes, crée un miroir Btrfs sur deux images de 2 Gio, copie les fichiers avec leurs UID et vérifie HTTP/SMB. Il retire ensuite le membre B, reconstruit sur C, redémarre le helper sans rejeu, compare les empreintes et lit un clone du snapshot antérieur. Un redémarrage de Linux vérifie à nouveau le pool, la connexion web et les comptes Samba. Aucun périphérique bloc hôte n’est exposé à QEMU.

Les scripts sont `integration_fresh_linux_vm.py` et `integration_mirror_repair_vm.py`. La reprise implique une copie intermédiaire et un raccordement administratif des partages ; elle n’est pas un installateur universel. La vidéo utilise des fixtures, sans démarrage de Frigate. À ce jalon, les coupures pendant reconstruction, ARM64 intégral et reconstruction ext4 restaient à qualifier ; voir la preuve 0.7.0-alpha.2 ci-dessus pour les deux premiers parcours.

## Connexion 0.6.0-alpha.3

84 tests Python et 5 tests JavaScript. Les régressions isolées reproduisent un cookie tiers qui perturbe le parseur, refusent les cookies de session ambigus, vérifient l’expiration pendant la navigation et les réponses tardives d’une ancienne session. La connexion Chrome a été rétablie sur l’installation existante sans effacement des cookies ni modification d’identifiants.

## Reprise d’installation 0.6.0-alpha.2

82 tests ordinaires. Le scénario `integration_system_recovery_vm.py` vérifie séparément une perte simulée, une nouvelle racine, les UID des fichiers, les clés retrouvées, le dépôt historique déchiffré, les comptes web/Samba, le SID, le compte désactivé et la lecture seule, puis la persistance après recréation du conteneur Samba. L’export natif est testé avec une politique vide dans cette VM ; aucune reconstruction de disques n’est revendiquée. Configuration et base Frigate utilisent des fixtures synthétiques.

## Référence 0.6 alpha

70 tests ordinaires incluent désormais migration transactionnelle, copie WAL, refus de version future, erreur de copie, arrêt SIGKILL, reprise sans écrasement, révocation de sessions et démarrages concurrents. Le scénario `integration_migrations_vm.py` valide séparément la reprise de la base dans une nouvelle installation et la connexion HTTP avec le compte conservé. Les preuves sont consignées dans `VALIDATION.json`.

## Référence historique 0.5

Le [rapport structuré](../VALIDATION.json) consigne la validation de développement du 9 novembre 2026 : 58 tests ordinaires réussis sur x86-64 et ARM64, plus des essais QEMU et matériels distincts. Il s’agit d’un relevé historique, pas d’un statut CI calculé en direct.

## Rejouer les tests ordinaires

```bash
python3 console/install_restic.py
NAS_RESTIC_BIN="$PWD/.tools/restic" python3 -m unittest discover -s tests -v
node --check console/static/app.js
node --check console/static/native.js
node --test tests/test_frontend.js
```

Sans `NAS_RESTIC_BIN`, le test de dépôt réel est ignoré : cela ne constitue pas la validation complète annoncée. Le runtime installé est contrôlé par SHA-256. Prévoir de l’espace temporaire pour les essais de transfert et d’archive volumineux.

## CI GitHub

La CI teste Linux x86-64 et ARM64 avec Python 3.11 et 3.12, vérifie le JavaScript, la présence de données interdites parmi les fichiers suivis et les secrets avec Gitleaks. Les actions sont épinglées à des commits. Aucun accès à une caméra, serveur NAS ou secret de production n’est requis.

## Banc privilégié

Suivre [VM-LAB.txt](../tests/VM-LAB.txt). Les scripts `integration_*_vm.py` utilisent exclusivement des disques images et des fixtures nommées dans QEMU. Ils ne font pas partie de la découverte unittest. Ne jamais les utiliser comme test de santé d’un NAS réel.

La validation native couvre Btrfs, ZFS, LVM, copie ext4/XFS, provisionnement disque entier/RAID1, redémarrage, perte réelle d’un montage, droits SMB et capture/restauration multivolume. Le remplacement RAID1 Btrfs est qualifié par le banc 0.7 ci-dessus ; le hotplug matériel complet et l’endurance longue restent à qualifier.

## Captures

Les captures de `docs/images/` proviennent de bancs virtuels 0.5/0.6/0.7 : données synthétiques, compte de laboratoire et aucun flux vidéo personnel. Elles illustrent une version précise et doivent être actualisées lors d’une modification significative de l’interface.

## Limites des preuves

Une suite verte ne démontre pas la compatibilité de tous les NAS, les performances sur tout matériel ou la récupération après chaque panne possible. Tout changement de backend natif doit ajouter un scénario d’échec significatif, pas seulement un test qui reproduit son implémentation.
