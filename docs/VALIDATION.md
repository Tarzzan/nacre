# Validation

## Rétention — 0.8.0-alpha.7

180 tests Python et 18 JavaScript. Les nouveaux cas couvrent la sélection conservatrice, les groupes, la confirmation à usage unique, l’auteur et l’expiration, les contrôles administrateur/CSRF, les changements de dépôt, l’annulation et les résultats partiels. Restic réel : simulation sans suppression, oubli d’un ancien point, nettoyage, `check --read-data` et restauration du contenu conservé. Une interruption pendant le nettoyage et un worker disparu sont signalés sans rejeu.

Banc web local distinct : simulation et fenêtre de confirmation vérifiées dans le navigateur, application par l’API authentifiée sur cinq versions synthétiques, trois suppressions et deux points conservés, restauration de la cinquième version et résultat vérifié dans l’interface. Aucun accès à Spark, caméra réelle ou disque de production pour ces essais. [Guide et captures](BACKUP-RETENTION.md).

## Emails SMTP — 0.8.0-alpha.6

170 tests Python et 16 JavaScript. Récepteur SMTP loopback avec TLS éphémère : STARTTLS, TLS direct, authentification après chiffrement, certificat non approuvé refusé, refus 535/550, erreur 451 et reprise. Parcours navigateur avec redémarrage réel de la console, Message-ID conservé et résolution livrée après l’incident. Aucune boîte ou infrastructure de messagerie extérieure utilisée. [Guide et preuves](SMTP-NOTIFICATIONS.md).

## Notifications externes — 0.8.0-alpha.5

161 tests Python et 14 JavaScript. Récepteur HTTP loopback, configuration et tests depuis le navigateur, erreur 503 avant reprise après redémarrage réel, identifiant conservé et résolution livrée après l’incident. TLS local : certificat non approuvé refusé, confiance explicite de test acceptée. Aucune destination Internet, notification de téléphone ou caméra réelle sollicitée. [Guide et limites](EXTERNAL-NOTIFICATIONS.md).

## Alertes locales — 0.8.0-alpha.4

146 tests Python et 11 JavaScript. Sources simulées sur banc HTTP local : trois incidents, prise en compte caméra depuis le navigateur, persistance après redémarrage du processus, clôture périodique de deux incidents après retour simulé. Tests de contrôles inconnus, confirmations, version périmée, regroupement de sauvegardes, accès administrateur et absence de secrets. [Protocole et captures](LOCAL-ALERTS.md). Aucun nouveau test de panne matérielle ou caméra réelle.

## Préparation Ubuntu et service persistant — 0.8.0-alpha.3

136 tests Python et 9 JavaScript. Préparation des paquets Ubuntu sur une VM ARM64 vierge, service Nacre actif avant la connexion SSH après deux redémarrages, Docker accessible au gestionnaire utilisateur, installation Samba par tâche systemd depuis le navigateur et fichier témoin relu par SMB3 après redémarrage. [Protocole et limites](HOST-BOOTSTRAP.md). Aucun nouveau test Frigate ou caméra dans ce banc.

## Installation web sur Linux neuf — 0.8.0-alpha.2

129 tests Python et 9 JavaScript. Déploiement réel depuis le navigateur dans une VM Ubuntu 24.04 ARM64 sans images ni conteneurs préexistants : Samba 4.22.10, Frigate 0.18.2 sain, lecture/écriture SMB3, refus d’écriture sur la vidéo, nouvelles demandes web conservant le fichier témoin. Docker 29.9.3 et Compose 5.7.0 préparés dans l’invité ; aucun service de production modifié. [Recette et capture](FRESH-WEB-INSTALL.md).

## Composants et caméras — 0.8.0-alpha.1

126 tests Python, 8 JavaScript. Installation réelle de restic depuis le navigateur dans une instance isolée, suivi après actualisation, ajout refusé proprement sans Frigate, sélection de deux fixtures et correction de connexion. Deux configurations de deux caméras validées par Frigate 0.18.2 ARM64 dans un conteneur sans réseau ni montage de production. Les commandes de déploiement Samba/Frigate sont simulées dans les tests, sans nouveau déploiement intégral ni mesure multi-caméra réelle. [Détail et captures](COMPONENTS-CAMERAS.md).

## Première configuration — 0.7.0-alpha.5

113 tests Python et 7 JavaScript. Les nouveaux cas couvrent autorisations et CSRF, rotation du mot de passe et révocation, reprise de l’assistant, préférences, composants manquants, migration 1 → 2 conservant les comptes, redirection initiale et réponse tardive après navigation. Parcours réel Chrome et vue mobile sur installation locale distincte ; démarrage CLI répété sans outils externes dans PATH. [Procédure et limites](FIRST-RUN.md). Aucun nouvel essai privilégié ni accès à la caméra.

## Coupures pendant écritures — 0.7.0-alpha.4

107 tests Python sans test ignoré avec restic vérifié, et 5 tests JavaScript. Trois nouveaux cas vérifient l’ordre des synchronisations HTTP, le refus de confirmer une erreur de synchronisation du fichier et la conservation sans écrasement d’un fichier publié dont la synchronisation du dossier a échoué.

Le [banc de coupures avec écritures](ACTIVE-WRITES-POWER-CUT.md) conserve les confirmations dans un journal externe synchronisé, utilise SMB2 FLUSH avec `strict sync=yes`, et impose un dépôt HTTP réellement reçu à moitié avant chaque arrêt brutal. Les contrôles après reprise sont cumulatifs. Les noms finaux incomplets restent absents et les fragments internes sont inaccessibles par l’API. Les UUID, le témoin de 64 Mio, le snapshot antérieur et l’unicité de la réparation sont revérifiés en fin de reconstruction. Les nombres mesurés sont dans `VALIDATION.json`.

Le système invité est ARM64/Btrfs RAID1 ; l’hôte QEMU reste alimenté. Ces essais ne couvrent pas la perte du cache physique, tous les clients SMB, les erreurs matérielles multiples ou l’endurance. Les validations précédentes ci-dessous restent historiques.

## Écritures et caméra ARM64 — 0.7.0-alpha.3

104 tests Python sans test ignoré avec restic vérifié, et 5 JavaScript. Les régressions ajoutées contrôlent la publication du miroir en reconstruction, `write-pending`, la lecture seule, les refus d’identités/journaux incohérents, les montages du conteneur vidéo, les archives, l’arrêt du conteneur auxiliaire après erreur de copie et la restitution des propriétaires/modes de la racine des volumes.

Le [banc ARM64](CONCURRENT-IO-CAMERA.md) vérifie 24 écritures locales, 24 dépôts HTTP authentifiés et 24 transferts Samba pendant la reconstruction. Les 72 empreintes sont conservées après reconstruction et redémarrage normal ; le snapshot antérieur reste inchangé. Les premiers essais ont détecté les refus HTTP liés à `write-pending`, corrigés avant la répétition finale.

La vidéo est testée avec un générateur, puis une Tapo C530WS réelle en flux secondaire. Une seconde VM ARM64 vierge récupère le point chiffré après arrêt de la source. Les deux anciens segments sont retrouvés avec les mêmes empreintes et métadonnées, le clip est décodé via l’API web authentifiée et de nouveaux enregistrements apparaissent, puis les contrôles vidéo sont répétés après redémarrage. Les fichiers root privés de Frigate conservent leurs empreintes, UID/GID et modes. Les comptes Samba, SID, clé historique et les 72 fichiers du pool sont également contrôlés sur la cible.

Aucune image réelle, clé ou archive de reprise n’est publiée. Le banc ne qualifie pas une coupure simultanée aux écritures, la charge multi-caméra, le GPU, la rétention longue ni les caches physiques. Les preuves antérieures ci-dessous restent datées de leur propre version.

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
