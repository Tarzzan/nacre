# Validation

## Fuseau horaire proposé au premier accès — 0.8.0-alpha.25

308 tests Python et 93 JavaScript. Trois essais Python sur HTTP et base temporaires : l’indicateur n’est vrai que pour un administrateur d’une console terminée, encore en UTC et jamais enregistrée (absence d’état, état d’origine, assistant en cours, fuseau déjà choisi, révision enregistrée) ; « Garder UTC » s’enregistre, s’inscrit au journal et un second onglet resté sur la proposition est refusé ; la liste proposée commence par UTC, ne contient que des noms géographiques triés et tout nom proposé est accepté ; les fichiers techniques de la base de fuseaux sont refusés par le panneau comme par l’assistant, sans modifier l’état. Sept essais JavaScript : repli sur UTC d’un fuseau inconnu du navigateur pour les dates, l’horloge et la relecture ; bandeau absent pour un lecteur, une console réglée, un assistant en cours ; aucune suggestion pour un navigateur en UTC, un nom illisible ou piégé ; un seul enregistrement malgré deux clics ; fuseau refusé par le serveur retiré de la proposition ; réglage fait ailleurs adopté ; réponse tardive ou session expirée sans effet ; champ à liste réduit aux noms affichables, aperçu de l’heure, nom inconnu arrêté avant tout envoi.

Sur le banc local (console réelle, données synthétiques, mode « fuseau jamais choisi ») : bandeau présent sur chaque page, 448 fuseaux proposés dans le champ, adoption du fuseau du navigateur avec journal redessiné de 13 h 47 à 10 h 47 et ligne de journal, « Garder UTC » confirmé par le serveur, largeur de téléphone sans défilement horizontal. Le fuseau système du serveur n’est pas utilisé comme indice : relevé en lecture seule sur l’installation de développement, il ne correspond pas au lieu.

## Purge des copies de mise à jour — 0.8.0-alpha.24

305 tests Python et 86 JavaScript. Cinq essais Python sur un répertoire temporaire : inventaire trié avec tailles, règle des trois copies les plus récentes, dossier désigné par l’état du superviseur conservé qu’il soit ancien, en attente ou issu d’un échec, refus pendant chaque phase d’une mise à jour et pendant une préparation, identifiants hors répertoire et liens symboliques sans effet, fichiers du superviseur intacts, suppression interrompue rattrapée par la règle. Un essai avec console et superviseur réels : quatre copies fictives, démarrage, deux imports successifs, installation réussie, puis liste, suppression par un administrateur, refus sans confirmation, sans jeton, pour un lecteur et pour la copie courante, journal relu. Deux essais JavaScript : carte échappée, copie courante sans bouton, confirmation avant envoi. Parcours navigateur sur le banc local avec trois copies synthétiques, en largeur d’ordinateur et de téléphone. Répétition isolée et installation réelle : voir [Déploiements](SPARK-DEPLOYMENT.md).

## Recherche d’événements sur plusieurs jours — 0.8.0-alpha.23

299 tests Python et 84 JavaScript. Six essais Python sur un service vidéo simulé qui applique lui-même bornes, types, tri et limite : période par défaut de sept jours civils, compteurs par type et par jour, pages successives sans trou ni doublon, plafond de comptage, indice de vidéo conservée à l’heure près, refus avant toute requête vidéo, lecture seule vérifiée sur le fichier de configuration. Quatre essais JavaScript sur la carte, les pages, les réponses tardives et l’ouverture d’un résultat dans la relecture. Parcours navigateur sur banc local : quinze jours, 112 événements, pagination, filtre et lecture, en largeur d’ordinateur et de téléphone. Avant d’écrire le code, lecture des routes d’événements de Frigate 0.18.2 et mesure sur l’installation de développement, en lecture seule : 525 événements sur quatre jours lus en 8 ms, résumé d’enregistrements détaillé par heure, indicateur `has_clip` resté vrai après la suppression de la vidéo, donc non utilisé. Avant la fusion, le code de recherche a été exécuté en lecture seule contre ces événements réels, sans rien installer : 527 événements lus en neuf pages, sans doublon. Cet essai a montré que deux objets vus sur la même image partagent leur instant de début (quatre cas) et qu’un événement pouvait être sauté entre deux pages ; une page ne se termine plus entre deux événements simultanés, et un test le vérifie. [Guide et limites](RECORDING-PLAYBACK.md#rechercher-sur-plusieurs-jours).

## Détection et objets suivis — 0.8.0-alpha.22

293 tests Python et 80 JavaScript. Huit essais Python sur service vidéo simulé : état limité aux types connus, réponses malformées, fichier écrit avec copie privée et sans redémarrage, filtre par défaut de chaque type, bascule de la détection, refus sans modification, fichier rétabli si Frigate n’applique pas, application non confirmée jamais annoncée. Trois essais JavaScript sur la carte, son absence et le formulaire. Parcours navigateur sur banc local, en largeur d’ordinateur et de téléphone. Lecture du code de Frigate et répétitions hors service dans son conteneur, sur copie temporaire. Essai du code réel de Nacre contre un second Frigate 0.18.2 temporaire, sans réseau ni caméra : ajout, retrait, pause, reprise, réglage rejoué, seuils par défaut identiques à ceux d’un démarrage, état retrouvé après redémarrage de ce moteur d’essai. Cet essai a révélé qu’un filtre vide est ignoré par Frigate ; corrigé avant toute mise en service. [Détail et limites](CAMERA-DETECTION.md).

## Événements dans la relecture — 0.8.0-alpha.21

285 tests Python et 77 JavaScript. Trois essais Python supplémentaires sur événements simulés : bornage au jour et à la caméra, entrées malformées, plafond signalé, relecture maintenue sans événements, vignette refusée pour un identifiant invalide ou une autre caméra. Trois essais JavaScript : vignettes sans style en ligne, valeurs échappées, filtre appliqué sans reconstruire la carte, repli sur les moments détectés. Parcours navigateur sur banc local à vignettes synthétiques, en largeur d’ordinateur et de téléphone. Sur l’installation de développement, lectures seules de l’API d’événements de Frigate pour en mesurer la forme ; aucune image rapatriée. [Détail et limites](RECORDING-PLAYBACK.md).

## Relecture des enregistrements — 0.8.0-alpha.20

282 tests Python et 74 JavaScript. Huit essais Python sur inventaire Frigate simulé : fusion et bornage des segments, réponses malformées ou trop volumineuses, changements d’heure, dates refusées avant toute requête vidéo, droits, bornes des extraits et trace des téléchargements. Sept essais JavaScript sur la frise, la saisie d’heure et les réponses tardives. Parcours navigateur sur banc local à service vidéo simulé et mire synthétique ; aucune image réelle publiée. Sur l’installation de développement, lectures seules de l’API Frigate pour mesurer les formats et le poids d’un extrait. [Détail et limites](RECORDING-PLAYBACK.md).

## Mises à jour signées — 0.8.0-alpha.19

274 tests Python et 67 JavaScript. Douze nouveaux essais Python sur consoles et superviseurs réels en répertoires temporaires : réussite, candidat altérant la base puis échouant, copie interrompue, arrêt brutal du superviseur pendant la vérification, signature et chemins invalides, modification après préparation, tâche active, expiration, espace insuffisant, cache Python obsolète malgré taille et horodatage identiques, autorisations et maintenance. Régressions de reprise complète et d’unité portable actualisées. Sept nouveaux essais JavaScript sur navigation, échappement, perte de réponse, refus, reconnexion, retour arrière et expiration.

Parcours navigateur isolé : import signé → confirmation → nouvelle version → recharge ; second paquet avec échec volontaire au démarrage → restauration automatique → console précédente avec session conservée. Copies du code et de la base contrôlées, fichier témoin et clé synthétique préservés. [Guide et captures](BROWSER-UPDATES.md). Aucun arrêt de caméra, disque ou conteneur de production dans ces essais ; pas de simulation de panne électrique matérielle ni de qualification d’endurance.

## Panneau de configuration — 0.8.0-alpha.18

262 tests Python et 60 JavaScript. Comptes et sessions synthétiques dans des bases temporaires ; conflits de préférences, contrôle des droits, révocation ciblée et session courante préservée. Parcours navigateur sur banc séparé, sans mutation des préférences ni comptes du NAS réel. [Guide et limites](CONTROL-PANEL.md).

## Déconnexion Frigate — 0.8.0-alpha.17

254 tests Python et 53 JavaScript. Banc du moteur réel : cinq tests sur image dérivée x86-64 et ARM64, dont le témoin amont défaillant et 100 échanges IPC après déconnexions. Réseau coupé, aucun montage de données NAS, aucune panne injectée dans la caméra réelle. Les quatre matrices Python habituelles et le scanner de secrets restent requis. [Procédure et limites](FRIGATE-WEBSOCKET.md).

## Fraîcheur vidéo — 0.8.0-alpha.16

249 tests Python et 53 JavaScript réussis. Échantillons anciens ou mal datés refusés, débit positif ancien non assimilé à un flux reçu, alerte préservée. Moniteur de direct testé sur réponses tardives, panne HTTP et requêtes concurrentes. Banc navigateur avec mire et statistiques figées ; récupération réelle du service vidéo contrôlée séparément sur Spark. [Diagnostic et limites](VIDEO-FRESHNESS.md).

## Vue d’ensemble des caméras — 0.8.0-alpha.15

246 tests Python et 50 JavaScript réussis. États distincts pour débit positif, débit nul, pause et mesure inconnue ; erreurs et mesures invalides sans faux diagnostic de panne. Consultation HTTP authentifiée en lecture seule, secrets exclus. Réponses tardives, direct unique, retour à la liste et droits lecteur testés. Parcours navigateur sur quatre caméras fictives avec mire locale et rétablissement simulé du flux. Aucune caméra réelle ni service Docker sollicités par ce banc. [Guide et captures](CAMERA-OVERVIEW.md).

## Aperçu des ouvertures — 0.8.0-alpha.14

242 tests Python et 43 JavaScript réussis. Intervalles en cours, union des recouvrements, borne de sept jours, exceptions et transitions d’heure. API administrateur avec CSRF, sans accès au dépôt ni modification de la base métier. Interface vérifiée contre les réponses tardives après édition ou navigation, avec fuseau explicite et distinction entre absence d’ouverture et limitation désactivée. [Guide](OPENING-PREVIEW.md).

## Plages multiples et exceptions — 0.8.0-alpha.13

236 tests Python et 40 JavaScript réussis. Validation des intervalles fermés, recouvrements, priorité sur la continuation de la veille, dates locales, passage d’année et changements d’heure. Refus des dates et plages invalides avant accès au dépôt. Restic isolé : exception prioritaire, fermeture avant suppression, reprise au second créneau, contrôle intégral et restauration exacte. Formulaire testé pour transmission, ajout/retrait, réinitialisation par dépôt, échappement et invalidation. Banc web après redémarrage : l’exception bloque les horaires habituels puis ouvre une tâche unique pour deux captures ; quatre points avant, deux après et dernier contenu restauré à l’identique. [Guide et preuve navigateur](DATE-EXCEPTIONS.md).

## Créneaux hebdomadaires — 0.8.0-alpha.12

227 tests Python et 34 JavaScript réussis. Régression navigateur : une actualisation de Snapshots terminant après la navigation ne peut plus remplacer le formulaire de rétention. Tests isolés des jours locaux, plages nocturnes du dimanche au lundi, chevauchements et changements d’heure. Compatibilité quotidienne, refus avant accès au dépôt, paramètres figés dans la simulation et reprise du même identifiant seulement au prochain jour autorisé. Dépôt restic réel : attente hors jour, continuation nocturne, nettoyage, contrôle intégral et restauration exacte. Banc web sur horloge réelle après redémarrage : deux captures regroupées en une tâche à l’ouverture du jour choisi, quatre points avant puis deux après, restauration exacte. [Guide et preuve navigateur](WEEKLY-WINDOWS.md).

## Créneau automatique — 0.8.0-alpha.11

219 tests Python et 29 JavaScript réussis. Bornes incluses/exclues, passage à minuit, fuseau, heure manquante/répétée, paramètres de simulation figés, report après attente, reprise du même identifiant, désactivation et reprise hors ligne. Regroupement des captures, réussite tardive non perdue et distribution concurrente sans doublon. Parcours réel : fermeture avant la première suppression sans effet, fermeture après lancement sans interruption du nettoyage, contrôle intégral et restauration exacte.

Banc web sur horloge réelle : quatre points intacts hors créneau, deux captures en attente conservées après redémarrage de console, une seule tâche à l’ouverture, deux points conservés et restauration exacte de la dernière version. Les tests restent isolés. [Fonctionnement et parcours navigateur](MAINTENANCE-WINDOW.md).

## Conservation calendaire — 0.8.0-alpha.10

209 tests Python et 26 JavaScript réussis. Sélection par union, périodes vides ignorées, groupes séparés, captures protégées exclues du comptage, frontière de minuit avec fuseau, année ISO et heure répétée au changement d’heure. Valeurs invalides refusées avant accès au dépôt ; ancienne règle sans calendrier conservée, paramètres de simulation persistés à l’activation et neutralisés à la reprise. Formulaire, motifs échappés et invalidation de simulation vérifiés en JavaScript.

Dépôt restic réel : conservation de mois historiques, suppression ponctuelle, capture déclenchant la règle automatique, contrôle intégral des données et restauration exacte d’un fichier historique. [Guide et preuve navigateur](CALENDAR-RETENTION.md).

## Nettoyage seul — 0.8.0-alpha.9

200 tests Python et 23 JavaScript réussis. Tests isolés : simulation échouée sans confirmation réutilisable, auteur et consentement, jeton à usage unique, expiration, dépôt remplacé, points modifiés, annulation avant exécution, interruption pendant nettoyage, contrôle final échoué et worker disparu. Les reprises de base et de NAS invalident aussi ces confirmations.

Restic réel : interruption provoquée après `forget`, nouvelle simulation sans modifier les points, `prune` seul, contrôle `check --read-data` et restauration exacte. Tests JavaScript : échappement des données, consentement, réponse tardive après navigation et rafraîchissement de l’historique préservant le formulaire. [Parcours navigateur et limites](REPOSITORY-CLEANUP.md).

## Rétention automatique — 0.8.0-alpha.8

193 tests Python et 20 JavaScript. Activation après simulation, historique et captures non réussies exclus, confirmations versionnées, déduplication avec passages concurrents, désactivation, contrôle de l’auteur et du dépôt, suspension après erreur/worker disparu, reprise entre publication de l’échec et suspension, alerte locale et neutralisation des règles dans les deux procédures de reprise.

Restic réel sur dépôts temporaires : nouvelle capture réussie, nettoyage automatique, `check --read-data` et restauration exacte ; interruption de `prune` conservant le succès de la sauvegarde et suspendant la règle. Banc web séparé : simulation/confirmation inspectées, activation par API, redémarrage réel de console, quatrième version synthétique, une tâche automatique supprimant deux anciennes versions, deux points restants et restauration du dernier contenu. Résultat vérifié dans le navigateur. Aucun accès à Spark. [Guide et captures](AUTOMATIC-RETENTION.md).

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
