# Changelog

## 0.8.0-alpha.16 — Détecter les mesures vidéo figées

249 tests Python et 53 JavaScript réussis. Le débit positif ne suffit plus : l’état des caméras et les alertes vérifient l’horodatage Frigate. Mesures de plus de 90 secondes signalées comme périmées, horodatage absent ou incohérent inconnu. Contrôle du direct toutes les 15 secondes, retrait de l’image en cas de perte de confirmation et reprise explicite par Actualiser. [Diagnostic et limites](docs/VIDEO-FRESHNESS.md).

## 0.8.0-alpha.15 — Vue d’ensemble des caméras

246 tests Python et 50 JavaScript réussis. Inventaire multi-caméra avec réception mesurée, débit nul, pause et état inconnu distincts. Vue sans flux vidéo, ouverture explicite d’un seul direct, retour à la liste et protection contre les réponses tardives. Aucun changement de connexion, d’enregistrement ou de conservation. [Guide](docs/CAMERA-OVERVIEW.md).

## 0.8.0-alpha.14 — Aperçu des prochaines ouvertures

Aperçu en lecture seule des ouvertures de nettoyage sur les sept prochains jours depuis le formulaire, avec fuseau, exceptions, intervalles réunis et changements d’heure. Les résultats tardifs sont écartés après modification ou navigation ; aucun enregistrement, nettoyage ou activation.

242 tests Python et 43 JavaScript réussis. Déploiement de la version alpha.13 sur Spark avec copie privée de retour arrière et contrôles de continuité. [Aperçu du calendrier](docs/OPENING-PREVIEW.md) et [déploiement](docs/SPARK-DEPLOYMENT.md).

## 0.8.0-alpha.13 — Plusieurs plages et exceptions datées

Plages supplémentaires en mode quotidien ou hebdomadaire, ajout et retrait depuis le navigateur. Exceptions par date civile : aucun démarrage ou horaires de remplacement, prioritaires sur toute la journée et sur la continuation de la veille. Résumé des horaires et exceptions avant activation, paramètres figés dans la simulation et anciennes règles compatibles.

236 tests Python et 40 JavaScript réussis. Tests isolés des intervalles, dates, priorité, changements d’heure et reports ; nettoyage réel puis restauration exacte. [Guide et capture](docs/DATE-EXCEPTIONS.md).

## 0.8.0-alpha.12 — Créneaux par jour de la semaine

Choix entre une plage quotidienne et des horaires indépendants pour chaque jour sélectionné. Les plages nocturnes appartiennent au jour de départ, y compris du dimanche au lundi ; leurs recouvrements sont réunis. Anciennes règles quotidiennes conservées, jours et horaires figés par la simulation, résumé explicite avant activation et rechargement lors du changement de dépôt.

227 tests Python et 34 JavaScript réussis. Correction complémentaire : une réponse tardive de Snapshots ne remplace plus le formulaire de rétention après navigation. Tests isolés des jours locaux, frontières, changements d’heure, report persistant et restauration exacte après nettoyage réel. [Guide et capture](docs/WEEKLY-WINDOWS.md).

## 0.8.0-alpha.11 — Créneau du nettoyage automatique

Créneau quotidien par dépôt, dans le fuseau de la règle, y compris à cheval sur minuit. Captures en attente regroupées, démarrage revalidé après attente et juste avant la première suppression. Report persistant sans effet sur les points, reprise sans doublon et suivi dans le navigateur. Une opération commencée termine son contrôle même après la fermeture du créneau. Applications ponctuelles immédiates explicitement distinguées.

219 tests Python et 29 JavaScript réussis. Tests isolés sur limites horaires, changements d’heure, report, reprise, regroupement et restauration exacte après nettoyage réel. [Guide et preuve navigateur](docs/MAINTENANCE-WINDOW.md).

## 0.8.0-alpha.10 — Conservation par jour, semaine et mois

Règles calendaires combinables avec les derniers points, pour une application ponctuelle ou automatique. Dernier point de chaque période contenant une capture réussie, semaines ISO et fuseau explicite attaché à la règle. Motifs de conservation affichés dans la simulation. Les règles existantes gardent leur comportement ; catégories calendaires désactivées par défaut.

209 tests Python et 26 JavaScript. Essais sur dates synthétiques et dépôts chiffrés isolés : union des protections, frontières de jour et d’année, changement d’heure, conservation automatique et restauration d’une version historique. [Fonctionnement et preuves](docs/CALENDAR-RETENTION.md).

## 0.8.0-alpha.9 — Reprendre un nettoyage interrompu

Simulation persistante du nettoyage seul depuis le navigateur, confirmation à usage unique valable quinze minutes et revalidation du dépôt et des points. Aucun `forget` dans ce parcours : les snapshots présents sont conservés, puis la structure est contrôlée. Interruption signalée sans rejeu ; une règle suspendue reste suspendue. Historique rafraîchi sans écraser les formulaires.

200 tests Python et 23 JavaScript. Essais sur dépôts chiffrés isolés : interruption après suppression, simulation, nettoyage, contrôle intégral des données et restauration exacte. [Guide, preuve web et limites](docs/REPOSITORY-CLEANUP.md).

## 0.8.0-alpha.8 — Rétention après les sauvegardes réussies

Règle par dépôt activable depuis une simulation : après les prochaines captures réussies, sélection recalculée et nettoyage automatique par tâche persistante. Version de règle et identité du dépôt revalidées, doublons évités, désactivation des tâches en attente et suspension après incident. Alerte locale et réactivation après simulation ; règles et confirmations neutralisées lors d’une reprise de base ou de NAS. Aucun automatisme activé par défaut.

193 tests Python et 20 JavaScript. Banc web isolé avec redémarrage réel de console, nouvelle capture, nettoyage automatique unique et restauration exacte du fichier conservé. [Fonctionnement, preuves et limites](docs/AUTOMATIC-RETENTION.md).

## 0.8.0-alpha.7 — Rétention des sauvegardes depuis le navigateur

Depuis Snapshots, simulation des derniers points réussis à conserver par groupe, détail des suppressions et confirmation à usage unique. Protection des captures partielles/importées ou sans preuve locale de réussite, revalidation du dépôt et des points avant exécution. Tâche persistante de suppression, nettoyage restic et contrôle de structure ; une interruption est signalée sans rejeu automatique. Aucune rétention automatique activée.

180 tests Python et 18 JavaScript. Essais sur dépôts chiffrés temporaires, contrôle des données restic et restauration du fichier conservé. [Guide et limites](docs/BACKUP-RETENTION.md).

## 0.8.0-alpha.6 — Emails SMTP depuis le navigateur

Destination Email SMTP avec STARTTLS ou TLS direct obligatoire, compte facultatif pour relais autorisé, un expéditeur et un destinataire. Mot de passe conservé sans réaffichage, changement de serveur protégé, test et historique existants réutilisés. Le Message-ID reste stable lors des reprises ; une rupture de QUIT après DATA accepté conserve le succès.

170 tests Python et 16 JavaScript. Récepteur SMTP isolé chiffré, erreur 451, redémarrage réel et reprise avec même Message-ID, puis résolution. Aucun fournisseur ni boîte Internet utilisés. [Guide et captures](docs/SMTP-NOTIFICATIONS.md).

## 0.8.0-alpha.5 — Notifications externes configurables

Destination ntfy ou webhook JSON réglable depuis Alertes → Notifications : test manuel, activation, gravité minimale, retours à la normale et historique des livraisons. File transactionnelle persistante, tentatives espacées, relance explicite et protection des secrets. HTTPS vérifié ; redirections refusées. Les envois restent désactivés par défaut.

161 tests Python et 14 JavaScript. Récepteur isolé, erreur 503 puis reprise après redémarrage réel, identité conservée et résolution livrée dans l’ordre. Tests TLS locaux et formats ntfy/JSON ; aucun push réel ni service Internet sollicité. [Guide et captures](docs/EXTERNAL-NOTIFICATIONS.md).

## 0.8.0-alpha.4 — Alertes locales persistantes

Centre Alertes administrateur et compteur global : services connus indisponibles, caméra activée sans flux, dernières sauvegardes échouées ou incomplètes et volume de Nacre presque plein. Confirmation temporelle, prise en compte versionnée, récidive et historique des retours à la normale. Les contrôles inconnus ne résolvent pas les incidents ; aucune notification extérieure ni correction automatique.

146 tests Python et 11 JavaScript. Parcours navigateur sur sources simulées, prise en compte conservée après redémarrage réel de la console, puis résolutions enregistrées par le collecteur périodique. [Guide, captures et limites](docs/LOCAL-ALERTS.md).

## 0.8.0-alpha.3 — Préparation Ubuntu et service persistant

Plan puis préparation explicite des prérequis Ubuntu 24.04 : paquets de la distribution, accès Docker et maintien du gestionnaire utilisateur. Les distributions Docker externes sont conservées avec un refus avant modification. `installer.py --service` installe et démarre Nacre sans sudo, avec port local configurable, validation de l’unité et restitution après échec.

Banc ARM64 vierge : deux redémarrages, console active avant SSH, installation Samba depuis le navigateur via une tâche systemd, fichier relu après redémarrage avec empreinte identique. 136 tests Python et 9 JavaScript. [Parcours et limites](docs/HOST-BOOTSTRAP.md).

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
