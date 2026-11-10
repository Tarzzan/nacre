# Changelog

## 0.6.0-alpha.3 — Connexion Chrome et sessions

Un cookie d’une autre application locale pouvait empêcher la reconnaissance du cookie Nacre après un mot de passe accepté. Lecture ciblée du jeton Nacre, avec refus des doublons et des formats invalides. L’interface vérifie la session avant d’ouvrir l’espace, conserve l’écran de connexion en cas d’expiration et ignore les réponses d’une ancienne session ; l’erreur `Cannot set properties of null` ne masque plus la cause initiale.

84 tests Python et 5 tests JavaScript, dont cookies tiers, expiration pendant navigation, réponse différée et cookie non transmis. Connexion rétablie dans Chrome avec la session existante, sans changement de mot de passe ni suppression des cookies tiers.


## 0.6.0-alpha.2 — Reprise d’installation, clés et Samba

Capture hors ligne chiffrée des données et de la configuration, avec clés restic, image et état persistant Samba. Préparation dans une nouvelle racine, UID conservés, sessions révoquées, plans désactivés et dépôts détachés jusqu’à vérification de leur identité. Import Samba dans un volume distinct, avec SID, mots de passe secondaires et comptes désactivés conservés. Export administratif du catalogue natif et reprise des fichiers externes vers des dossiers ordinaires.

État et aide dans Snapshots ; procédure complète illustrée. 82 tests ordinaires et reprise rejouée dans QEMU, y compris connexion HTTP avec l’ancien compte et recréation du conteneur Samba. Parcours actuel : même architecture et UID/GID principal, dépôt monté localement. La reconstruction de Linux, des pools et des snapshots natifs reste distincte.


## 0.6.0-alpha.1 — 2026-11-09

Première étape de fiabilité : schéma SQLite versionné, migration atomique et copie préalable cohérente vérifiée. Refus d’un schéma futur. Outil de préparation hors ligne d’une base récupérée, sans écrasement, avec révocation des sessions et désactivation des plans. État et aide disponibles dans Snapshots. Correction du bouton de restauration des snapshots, désactivé à tort en 0.5.

70 tests ordinaires ; arrêt brutal et reprise testés en VM, puis connexion HTTP à une installation neuve avec le compte conservé. La reprise complète du NAS, des clés externes et du passdb Samba reste à développer ; l’issue #1 reste ouverte.

## 0.5 — 2026-11-09

Gestion des fichiers sur volumes natifs, corbeille par volume, partages SMB contrôlés, sources et destinations restic natives, restauration multivolume et refus après disparition d’un montage. 58 tests ordinaires, essais QEMU et contrôle sur ARM64.

### Mise en dépôt

Premier import Git du travail existant. Ajout du README illustré, vision, architecture, installation, feuille de route, règles de contribution, contrôle des secrets et CI. Les sections ci-dessous sont rétrospectives : aucun historique Git antérieur n’est inventé.

## 0.4 — historique de développement

Provisionnement de disques entiers ext4/Btrfs et miroir RAID1, montage catalogué, restauration LVM ext4/XFS et navigation dans les restaurations. 50 tests ordinaires au jalon.

## 0.3 — historique de développement

Helper natif optionnel, plans à confirmation, profils matériels et snapshots Btrfs/ZFS/LVM. Banc privilégié QEMU. 41 tests ordinaires au jalon.

## 0.2 — historique de développement

Inventaire portable, restic chiffré, plans automatiques désactivés par défaut, restauration privée et retrait des plafonds applicatifs de taille. 30 tests ordinaires au jalon.

## Socle initial — historique de développement

Console locale, authentification, fichiers, SMB, comptes, services, Frigate et pilotage PTZ d’une Tapo C530WS.
