# Changelog

## 0.8.0-alpha.2 — Installation web sur Linux neuf

Samba et Frigate installés réellement par le navigateur dans une VM Ubuntu 24.04 ARM64 vierge, puis relancés avec conservation d’un fichier témoin. Lecture/écriture SMB3 vérifiée, écriture vidéo refusée, Frigate sain et API disponible. Docker reste un prérequis préparé sur Linux.

Le déploiement attend la réponse du démon Samba avant d’appliquer les partages. Le suivi nomme chaque composant et distingue le démarrage de Frigate d’un état sain ou dégradé. 129 tests Python et 9 JavaScript. [Parcours, capture et protocole](docs/FRESH-WEB-INSTALL.md).

## 0.8.0-alpha.1 — Composants et caméras dans le navigateur

Installation applicative de restic, Samba et Frigate par tâches persistantes. Ajout et correction de connexions Tapo/RTSP, ONVIF optionnel et sélection de caméra pour direct, clips et PTZ. Configuration validée par Frigate avant publication, copie privée préalable et erreurs explicites après redémarrage non confirmé. Docker et service natif restent des préparations Linux séparées.

Correction d’une soumission native GET lorsque le champ caméra `id` masquait l’identifiant du formulaire ; les formulaires sensibles utilisent désormais POST et le gestionnaire lit l’attribut DOM. 126 tests Python et 8 JavaScript ; restic installé réellement sur banc local et configurations validées par Frigate ARM64 isolé. [Guide, preuves et limites](docs/COMPONENTS-CAMERAS.md).

## 0.7.0-alpha.5 — Première configuration depuis le navigateur

Une commande prépare et ouvre la console sans Docker obligatoire. L’assistant authentifié sécurise le compte provisoire, présente les capacités accessibles et enregistre le nom du NAS et son fuseau. Le tableau de bord reste utilisable sans les services Docker. Les composants supplémentaires se configurent séparément.

Migration de base 1 → 2 avec copie préalable ; comptes existants conservés, assistant facultatif après mise à jour. 113 tests Python et 7 JavaScript ; parcours Chrome et affichage mobile vérifiés sur une instance isolée. [Guide et capture](docs/FIRST-RUN.md).

## 0.7.0-alpha.4 — Coupures pendant les écritures

Un dépôt web n’est confirmé qu’après synchronisation du fichier et de son nom sur le volume. Un échec avant publication ne laisse pas de nom final ; un échec de synchronisation du dossier conserve le fichier complet sans réponse de succès et sans écrasement lors d’une nouvelle tentative.

Banc ARM64 de trois coupures QEMU pendant reconstruction et écritures HTTP/locales/SMB avec FLUSH explicite. Les confirmations sont synchronisées dans un journal externe à la VM, puis toutes leurs empreintes sont contrôlées à chaque reprise. Un dépôt HTTP à moitié reçu doit rester non publié. 107 tests Python et 5 JavaScript ; protocole et résultats dans [la recette dédiée](docs/ACTIVE-WRITES-POWER-CUT.md). La perte des caches physiques reste hors qualification.

## 0.7.0-alpha.3 — Écritures en reconstruction et reprise caméra ARM64

Les volumes RAID1 vérifiés restent disponibles par HTTP et Samba pendant la reconstruction, y compris la transition MD `write-pending` observée à l’arrivée des écritures. Un état incertain, un membre inattendu et les restrictions de lecture seule conservent leurs contrôles.

La capture hors ligne prend en charge les fichiers privés root de Frigate, sans modifier leurs permissions. Le kit vidéo de format 2 archive et vérifie sa configuration ; sa préparation conserve les UID/GID et modes via un conteneur auxiliaire jamais démarré. Les kits de format 1 restent lisibles. La racine de chaque volume récupéré retrouve aussi ses propriétaires et permissions : les comptes Samba secondaires ne sont plus bloqués par le `0700` du dossier temporaire.

Recette ARM64 : 72 fichiers écrits pendant la reconstruction et contrôlés après redémarrage ; vraie caméra, capture chiffrée et reprise sur une VM vierge avec lecture des anciennes vidéos et nouveaux enregistrements. 104 tests Python et 5 JavaScript. Les coupures pendant des écritures actives et les caches matériels restent hors qualification. Voir [la recette complète](docs/CONCURRENT-IO-CAMERA.md).

## 0.7.0-alpha.2 — Coupure en reconstruction et reprise ARM64

Correction d’une reconstruction suspendue après coupure lorsque Linux réassemble le miroir en `read-auto`. Au démarrage, le helper ne réactive que l’opération déjà journalisée, avec les deux membres attendus et le montage vérifiés ; aucun nouvel ajout ni assemblage forcé. Un état MD explicitement `readonly` reste respecté.

Banc de trois arrêts brutaux QEMU pendant reconstruction, audit des commandes mdadm, contrôle des UUID, fichier de 64 Mio et snapshot antérieur. Reprise ARM64 sur une seconde VM vierge après arrêt de la source : données, clés, comptes web/Samba, SID, nouveau pool et contrôles après redémarrage. 94 tests Python et 5 JavaScript ; limites de la simulation de coupure documentées.

## 0.7.0-alpha.1 — Linux neuf et reconstruction RAID1

Reprise qualifiée sur Ubuntu vierge : données, clés historiques, comptes web/Samba, nouveau miroir Btrfs, raccordement des partages et redémarrage. Ajout du parcours navigateur de remplacement d’un membre RAID1 absent, avec disque vierge explicitement autorisé, plan à usage unique, journal préalable et vérification des deux membres synchronisés. Aucun rejeu automatique après interruption ; validation distincte du catalogue en cas de résultat ambigu.

Correction des droits du dossier parent des restitutions Btrfs nouvellement créé sous le service root. 90 tests Python et 5 JavaScript ; bancs privilégiés réservés à QEMU. La reconstruction préserve les données, un snapshot antérieur et la signature de l’ancien membre. Linux neuf ARM64, autres géométries RAID et perte électrique pendant reconstruction restent à qualifier.

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
