# Validation

## Poids des espaces — 0.8.0-alpha.48

357 tests Python et 136 JavaScript. Un essai Python : rien de gardé avant une pesée ; sous-dossier pesé, rien de gardé ; espace entier pesé, total, décompte et heure gardés ; nouvelle pesée qui remplace l’ancienne ; pesée arrêtée gardée comme un minimum ; compte en lecture seule limité à ses espaces ; valeur gardée illisible ignorée. Un essai JavaScript : vue ouverte depuis une pesée sans rien peser, lignes pesées et non pesées, part entre espaces pesés, espace inconnu écarté ; peser un espace puis relire ; minimum affiché « au moins » ; refus dit et suite poursuivie ; « tous » à la suite ; « Détail » ; ouverture directe depuis la recherche globale. Sur le banc local, avec le vrai serveur : quatre espaces non pesés, un pesé puis tous, parts et dates affichées, sans débordement.

## Suite des événements — 0.8.0-alpha.47

356 tests Python et 135 JavaScript. Un essai JavaScript : liste arrêtée au dernier événement chargé de la caméra qui a une suite ; filtre sur une caméra sans suite, liste complète, sur celle qui en a une, bouton conservé ; refus du serveur dit sans rien changer à l’affichage ; suite demandée à la caméra qui borne la liste, sur la période exacte de la première réponse, jusqu’à épuisement ; ordre du plus récent au plus ancien, aucun doublon ; plus rien à demander, aucun appel ; nouvelle recherche repartie de la première page. Sur le banc local, avec le vrai serveur et des pages raccourcies à huit événements : huit affichés, puis quarante-six après un clic, dans l’ordre et sans doublon, bouton disparu et mention « tous les événements de la période sont listés ».

## Restaurations natives « à vérifier » relues — 0.8.0-alpha.46

356 tests Python et 134 JavaScript. Un essai Python du service face à un stockage simulé : restauration trop récente, emplacement de restauration changé, copie encore montée ou nom non géré, elle reste « à vérifier » et bloque la suppression ; copie ZFS présente et non montée, terminée avec sa destination ; copie absente, échec ; copie LVM dont le processus a disparu, tâche close en échec, tâche en cours laissée intacte ; aucune commande de création ni de suppression pendant la relecture ; suppression de nouveau acceptée ensuite.

**Banc VM** (`tests/integration_native_review_vm.py`, VM isolée du banc natif) : service réinstallé depuis les sources. Restaurations Btrfs et ZFS coupées juste avant puis juste après la création de la copie, service arrêté ; au redémarrage, quatre restaurations « à vérifier » et suppression refusée sur leur volume ; une fois leur délai passé, échec pour les deux copies absentes, terminée avec destination pour les deux présentes, copie Btrfs lisible et publiée, copie ZFS non montée, inventaire du stockage inchangé par la relecture ; suppression acceptée, sauf le point dont dépend la copie ZFS reconnue. Restauration LVM classique : copie tuée en route, « à vérifier » après trente secondes, puis échec, dossier partiel privé et non publié, points supprimables. Non prouvé : coupure de courant de la machine entière.
## Migration vers l’agent de services — banc seul, sans nouvelle version

**Banc VM** (`tests/integration_service_migration_vm.py`, même VM jetable que l’agent) : installation d’essai en service, une session SMB ouverte avant le premier geste et un processus tenant lieu de console en marche. Agent posé, dossiers protégés, protection exigée, agent démarré, compte sorti du groupe `docker` : neuf écritures par la même session SMB, conteneur de fichiers jamais recréé ni redémarré (même identifiant, même heure de démarrage). Le processus resté en marche garde son accès direct après la sortie du groupe et le perd une fois relancé. Retour arrière dans l’ordre inverse : agent arrêté, compte remis dans le groupe, montages démontés à chaud, la console pilote de nouveau Docker, toujours sans coupure. Non prouvé : la vidéo, et une machine réelle.

## Dossiers de données protégés — 0.8.0-alpha.45

355 tests Python et 134 JavaScript. Un essai Python de plus pour l’agent : seuls les dossiers où un conteneur écrit sont examinés, pas les montages en lecture seule ni les volumes Docker ; sans exigence, l’agent rapporte et démarre ; avec, démarrage, redémarrage et recréation refusés tant qu’un dossier est exposé, lecture d’état et arrêt toujours permis ; partage approuvé en écriture compté, en lecture seule non ; dossier absent jamais « protégé » ; image Frigate fixée par root. L’essai de l’installateur couvre la copie des sources des images, la description qui y renvoie, et les deux unités de montage au nom que systemd attend.

**Banc VM** (`tests/integration_service_agent_vm.py`, même VM jetable) : **avant protection**, un programme que le conteneur a marqué dans le dossier partagé donne les droits de root au compte de la console, et un fichier de périphérique créé par le conteneur lui laisse lire le disque système ; **après** activation des deux montages préparés par l’installateur, les trois dossiers sont vus `nosuid` et `nodev` par l’agent, le même programme tourne sans privilège, le périphérique ne s’ouvre plus, le conteneur n’a pas été redémarré, et ce qu’il dépose ensuite ne vaut rien non plus ; protection exigée : partage approuvé sur un dossier exposé refusé ; source d’image trafiquée par le compte de la console sans effet sur l’image reconstruite. Non prouvé : ces mêmes gestes sur une installation en service et avec la vidéo.

## Agent de services — 0.8.0-alpha.44

354 tests Python et 134 JavaScript. Six essais Python de l’agent face à un Docker simulé : seul le compte de la console est entendu, root compris parmi les refusés ; ligne Compose de l’agent, avec sa description, le nom du projet et un fichier de variables réduit à trois clés ; refus de Docker et délai dépassé rendus avec le même sens que sans agent ; montages de partages confrontés aux emplacements approuvés, quinze formes refusées (racine, lien qui s’évade, remontée, cible hors partages, clé en trop) ; installation reprise relue dans sa forme exacte ; demandes et réponses par un vrai socket, demandes mal formées refusées sans rien exécuter ; installateur qui pose le code, la description et une politique vide, sans jamais écraser une politique existante ; politique et description refusées si elles n’appartiennent pas à root.

**Banc VM** (`tests/integration_service_agent_vm.py`, VM QEMU jetable, Docker 24 et image Samba du banc) : installation d’essai pilotée d’abord directement, puis agent installé par `install_services.py`, démarré par systemd, et compte de la console retiré du groupe `docker` de l’invité. Seize opérations rejouées par l’agent, conteneur de fichiers jamais recréé par le changement de pilote ; root et huit demandes hors liste refusés ; description des services et variables trafiquées par le compte de la console sans effet sur le conteneur recréé ; sept montages refusés, un approuvé et vérifié dans le conteneur ; agent arrêté puis relancé. Non prouvé : la vidéo par l’agent sur un vrai Docker ; la migration d’une installation en service.

## Liste fermée des opérations Docker — 0.8.0-alpha.43

348 tests Python et 134 JavaScript. Quatre essais Python du catalogue : ligne de commande exacte de chacune des dix-neuf opérations ; mot de passe transmis par l’entrée standard, jamais dans la commande ; seule l’adresse du conteneur vidéo rendue ; cinquante-sept demandes refusées sans aucune commande exécutée (opération inconnue, paramètre en trop, service ou action hors liste, option glissée dans un nom, remontée de chemin, fichier hors du dossier de la console, programme fourni par l’appelant) ; contrôle statique qu’aucun autre module de la console ne compose de commande Docker. Les essais existants des partages, des caméras, de la détection, des alertes, de l’accueil et de l’installation passent sans modification : mêmes commandes qu’avant. Aucun banc VM pour ce lot, qui ne change ni les droits ni le déploiement.

## Conservation automatique des points natifs — 0.8.0-alpha.42

344 tests Python et 134 JavaScript. Cinq essais Python face à un service natif simulé, à travers la vraie boucle de programmation : activation refusée sans règle enregistrée, sans accord de suppression, sans maximum valide, sans la phrase, et pour un compte non administrateur ; règle appliquée après chaque capture programmée aux seuls points programmés, capture manuelle jamais proposée même quand la règle enregistrée la vise ; note des points programmés nettoyée ; passage sauté sans suspension pendant une restauration ou quand le service ne répond pas ; suspension et alerte au-delà du maximum, au refus du plan, à la suppression interrompue, à l’accord retiré et à la validation refusée ; alerte close à la réactivation ; programmation au plafond libérée ; autre règle enregistrée qui désactive sans alerte ; désactivation après récupération de l’installation. Un essai JavaScript : état par volume, fenêtre, maximum proposé, phrase, envoi, refus, cas sans règle ou sans accord. Sur le banc local, avec le vrai serveur et un service natif simulé : conservation activée depuis la fenêtre, capture fictive créée seule à l’heure dite, sept points fictifs supprimés dans la foulée, trois points programmés gardés, capture manuelle intacte, état et journal des opérations à jour.

**Banc VM** (`tests/integration_native_auto_vm.py`, même VM isolée que les bancs précédents) : service natif réinstallé depuis les sources, suppression accordée dans la politique de l’invité, console sous son compte non privilégié contre le vrai socket. Pour Btrfs, ZFS, LVM classique et LVM thin : quatre captures programmées, règle « 2 derniers » appliquée après chacune, les deux plus anciens points programmés disparus du stockage, point manuel intact, points restants en lecture seule. Programmation au plafond libérée par le passage puis capture suivante réussie ; maximum dépassé : rien de supprimé, suspension ; accord retiré par root : capture faite, aucune suppression, suspension. Non prouvé : déclenchement par l’horloge sur plusieurs jours, passage sauté pendant une vraie restauration, alerte vue à l’écran.

## Suppression explicite des points natifs — 0.8.0-alpha.41

339 tests Python et 133 JavaScript. Dix essais Python du service face à un stockage simulé : accord de la politique exigé à la préparation comme à la validation ; liste exacte supprimée une seule fois ; plan lié au compte et à la phrase, jamais rejoué ; un point refusé annule le plan (autre volume, inconnu, non prêt, doublon, plus de cinquante) ; changement après le plan (objet remplacé, politique, expiration, point ouvert) ; restauration en cours ou à vérifier, copie ZFS dépendante ; commande refusée qui laisse la suite intacte ; suppression non confirmée puis accordée à l’état réel ; service interrompu ; durée maximale ; service installé sur le nouveau point d’entrée, module figé inchangé. Un essai Python de la console : liste affichée exigée, plan demandé pour cette liste, phrase transmise, bilan, journal, note des points programmés nettoyée, tranches de cinquante, refus rendus tels quels, action générique fermée à la suppression, comptes non administrateurs. Un essai JavaScript : bouton sous les points sortants, fenêtre et phrase, bouton inactif tant que la phrase diffère, bilan complet ou interrompu, refus à la préparation et à la validation, plus de cinquante points, point unique, suppression non accordée. Sur le banc local, avec le vrai serveur et un service natif simulé : trois points fictifs supprimés depuis la fenêtre, bilan affiché, simulation recalculée, trois lignes au journal des opérations ; l’arrêt en cours de liste et le refus n’y ont pas été rejoués à la main.

**Banc VM** (`tests/integration_native_delete_vm.py`, VM QEMU isolée repartie de l’état du banc natif, noyau 6.8, btrfs-progs 6.6.3, ZFS 2.2.2, LVM 2.03.16) : service natif réinstallé depuis les sources par `install_native.py` et joint par son socket sous le compte non privilégié. Refus sans accord dans la politique ; deux points supprimés par volume pour Btrfs, ZFS, LVM classique et LVM thin, les autres points et les fichiers intacts ; plan rejoué, autre compte et phrase inexacte refusés ; clone et retenue ZFS ; politique modifiée ; coupure avant et après la commande pour chaque famille, rien de rejoué, catalogue accordé au stockage à la lecture suivante ; objet remplacé sous le même nom non supprimé ; point LVM refusé pendant une vraie restauration puis une fois monté, accepté une fois refermé ; chaîne complète depuis la console. Quatorze points supprimés, exactement ceux annoncés. Non prouvé : coupure de courant de la machine entière, thin pool saturé.

## Programmation des captures natives — 0.8.0-alpha.40

328 tests Python et 132 JavaScript. Trois essais Python face à un service natif simulé : réglage par volume, confirmation exigée pour activer, onze réglages mal formés refusés, accès réservé aux administrateurs ; occurrence à l’heure passant par une préparation et une validation sous le compte de la programmation, jamais deux fois ; point noté comme programmé et traité par la règle de conservation ; plafond ; occurrence sautée pendant une opération, une création ou une copie LVM ; volume ou service indisponible ; refus à la préparation et à la validation sans second essai ; occurrence manquée sans rattrapage ni alerte ; alerte levée puis close. Un essai JavaScript : ligne par volume, fenêtre de réglage, phrase à recopier, envoi, refus affiché. Sur le banc local, avec le vrai serveur et un service natif simulé : programmation refusée sans la phrase, activée avec, capture fictive créée seule à l’heure dite, puis arrêt au plafond.

**Banc VM** (`tests/integration_native_schedule_vm.py`, VM QEMU isolée repartie de l’état du banc natif, noyau 6.8, btrfs-progs 6.6.3, ZFS 2.2.2, LVM 2.03.16) : service natif réinstallé depuis les sources, puis console exécutée sous son compte non privilégié contre le vrai socket. Une capture programmée par famille — Btrfs, ZFS, LVM classique, LVM thin — retrouvée sur le stockage et en lecture seule ; un plan déjà validé refusé ; plafond atteint sur les quatre volumes sans aucune capture ; occurrence manquée sans capture ; seconde capture Btrfs sous un plafond relevé ; simulation de conservation qui garde le dernier point programmé, sort le premier et protège le point manuel antérieur ; programmation désactivée sans capture. Cinq points créés au total, exactement ceux annoncés.

Non prouvé : le déclenchement par l’horloge sur plusieurs jours et le changement d’heure n’ont pas été attendus en temps réel, seulement calculés ; l’occurrence sautée pendant une vraie restauration n’a été vérifiée que face au service simulé ; l’installation de développement n’a pas de service natif.

## Conservation des points natifs, règle et simulation — 0.8.0-alpha.39

325 tests Python et 131 JavaScript. Deux essais Python face à un service natif simulé : répartition exacte des points entre gardés (avec motifs), sortants et protégés ; états non sûrs, date future, autre volume et identifiant mal formé ; captures manuelles protégées par défaut, points programmés soumis à la règle ; restauration en cours qui protège tout le volume ; rien demandé au service natif en dehors de son état et rien enregistré par une simulation ; règle enregistrée par volume et inscrite au journal ; règle illisible remplacée par la règle proposée ; vingt-quatre demandes mal formées refusées ; accès réservé aux administrateurs ; service natif absent. Un essai JavaScript : une ligne par volume, formulaire, simulation et ses trois listes, saisie non entière, refus affiché, réponse tardive ignorée, enregistrement, actualisation périodique suspendue pendant la saisie, carte absente sans volume. Sur le banc, avec le vrai serveur et un service natif simulé : onze points fictifs, règle « 3 derniers, 4 jours, 2 semaines, 2 mois » donnant 6 gardés, 2 protégés et 3 sortants ; règle enregistrée et relue.

Non prouvé : rien n’a été exécuté sur un vrai volume natif, et ce lot n’en a pas besoin puisqu’il ne fait que lire l’état du service. L’installation de développement n’a pas de service natif : la carte n’y apparaît pas.

## Poids des dossiers — 0.8.0-alpha.38

323 tests Python et 130 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Recherche de fichiers par critères, sans nom — 0.8.0-alpha.37

322 tests Python et 129 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Filtres de la recherche de fichiers — 0.8.0-alpha.36

321 tests Python et 128 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Période et tranche horaire dans l’onglet Événements — 0.8.0-alpha.35

320 tests Python et 127 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Recherche d’événements par tranche horaire — 0.8.0-alpha.34

320 tests Python et 126 JavaScript. Détail dans le [guide de la relecture](RECORDING-PLAYBACK.md#validation).

## Recherche de fichiers par nom — 0.8.0-alpha.33

318 tests Python et 125 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Bureau personnalisable — 0.8.0-alpha.32

315 tests Python et 122 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Plusieurs fenêtres — 0.8.0-alpha.31

313 tests Python et 119 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Gestionnaire de fichiers — 0.8.0-alpha.30

312 tests Python et 117 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Surveillance en application — 0.8.0-alpha.29

308 tests Python et 112 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Recherche globale — 0.8.0-alpha.28

308 tests Python et 107 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Centre de notifications — 0.8.0-alpha.27

308 tests Python et 103 JavaScript. Détail dans le [guide du Bureau](DESKTOP.md#validation).

## Le Bureau — 0.8.0-alpha.26

308 tests Python et 98 JavaScript. Le détail des essais et du parcours navigateur est dans le [guide du Bureau](DESKTOP.md#validation).

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
