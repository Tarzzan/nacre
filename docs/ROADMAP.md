# Feuille de route

Les versions futures sont des objectifs sans date promise. Chaque étape demande des preuves de fonctionnement et de récupération.

| Étape | Résultat attendu | Critères de sortie |
| --- | --- | --- |
| **0.5 — socle versionné** | Source, documentation illustrée, CI et bancs décrits | Import sans secrets ; CI verte ; état réel et limites documentés |
| **0.6 — fiabilité et reprise** | Sauvegarde de configuration complète, procédure de restauration sur hôte neuf, migrations maîtrisées | Reprise rejouée en VM ; panne injectée pendant migration ; ancien état récupérable |
| **0.7 — cycle de vie du stockage** | Remplacement RAID, reconstruction, import dégradé, événements de disque | Scénarios de panne/retrait/retour sur images ; identité du disque revalidée ; original préservé |
| **0.8 — protection et surveillance** | Programmation native, rétention explicite, parcours multi-caméra et alertes | Rétention simulée avant suppression ; restauration prouvée ; déconnexion caméra visible |
| **0.9 — portabilité et administration** | Matrice matérielle, installation reproductible, réduction des privilèges Docker | Installation sur hôtes neufs x86/ARM ; audit des droits ; procédures d’exploitation |
| **1.0 — cible à qualifier** | Version exploitable avec périmètre de support précis | Revue de sécurité, endurance, mises à jour et reprise éprouvées ; aucun défaut critique connu |
| **Après stabilisation** | Gestion de plusieurs NAS | Identités inter-hôtes, révocation, fonctionnement déconnecté et politiques de groupe spécifiés |

## Conservation des points natifs 0.8.0-alpha.39

Premier des quatre lots de l’issue 4 : règle par volume et simulation, sans suppression. La [programmation des captures](NATIVE-SNAPSHOT-POLICY.md#lot-2--programmation-des-captures) a suivi en alpha.40. [Lots suivants](NATIVE-SNAPSHOT-POLICY.md) : suppression explicite sur banc VM, conservation automatique.

## Bureau 0.8.0-alpha.26

Premier lot du cap « un bureau dans le navigateur » : coquille, sept applications à onglets, dock, widgets, affichage classique conservé. [Guide et limites](DESKTOP.md). Le [centre de notifications](DESKTOP.md#centre-de-notifications) a suivi en alpha.27. La [recherche globale](DESKTOP.md#recherche-globale) est arrivée en alpha.28. [Surveillance en application](DESKTOP.md#surveillance) a suivi en alpha.29. Le [gestionnaire de fichiers](DESKTOP.md#fichiers) est arrivé en alpha.30. Les [fenêtres multiples](DESKTOP.md#plusieurs-fenêtres) sont arrivées en alpha.31. Le [bureau personnalisable](DESKTOP.md#personnaliser-le-bureau) a clos le cap en alpha.32. La [recherche de fichiers par nom](DESKTOP.md#rechercher-un-fichier-par-son-nom) l’a prolongé en alpha.33, avec ses [filtres](DESKTOP.md#affiner-les-résultats) en alpha.36 la [recherche par critères, sans nom](DESKTOP.md#chercher-sans-nom-par-critères) en alpha.37 et le [poids des dossiers](DESKTOP.md#peser-les-dossiers) en alpha.38. Prolongements possibles : Surveillance en application (mur de caméras), plusieurs fenêtres, gestionnaire de fichiers, bureau personnalisable.

## Fuseau horaire 0.8.0-alpha.25

Proposition du fuseau aux administrateurs tant qu’il n’a jamais été choisi, champ à liste avec aperçu de l’heure, repli sur UTC pour un nom que le navigateur ignore. [Guide et limites](CONTROL-PANEL.md#fuseau-horaire-au-premier-accès). Restent ouverts : libellés de fuseaux en français, fuseau par compte.

## Copies de mise à jour 0.8.0-alpha.24

Liste des copies de retour arrière dans la page Mises à jour, conservation automatique des trois plus récentes, suppression manuelle des autres. [Guide et limites](BROWSER-UPDATES.md#copies-de-retour-arrière). Restent ouverts : nombre de copies réglable, retour à une copie depuis le navigateur après validation.

## Recherche d’événements 0.8.0-alpha.23

Recherche des événements d’une caméra sur une période de jours, par type d’objet, avec ouverture du résultat dans la relecture. [Guide et limites](RECORDING-PLAYBACK.md#rechercher-sur-plusieurs-jours). La [tranche horaire](RECORDING-PLAYBACK.md#ne-garder-quune-tranche-horaire) est arrivée en alpha.34, puis, avec la période, dans l’onglet Événements de toutes les caméras en alpha.35. Restent ouverts : recherche sur plusieurs caméras, par nom reconnu, filtre par zone.

## Détection et objets suivis 0.8.0-alpha.22

Carte Détection par caméra : activation, pause et choix des types suivis, appliqués sans redémarrer le service vidéo. [Guide et limites](CAMERA-DETECTION.md). Restent ouverts : seuils, zones et masques, réglage commun à plusieurs caméras, mesure de la charge avant activation.

## Événements dans la relecture 0.8.0-alpha.21

Vignettes des événements Frigate du jour, filtre par type d’objet avec repères sur la frise, lecture depuis une vignette. [Guide et limites](RECORDING-PLAYBACK.md). Choix des objets suivis livré en alpha.22, recherche sur plusieurs jours en alpha.23. Restent ouverts : filtre par zone, export de longues périodes, lecture synchronisée de plusieurs caméras, protection d’un passage et intégrité des fichiers vidéo.

## Relecture des enregistrements 0.8.0-alpha.20

Frise par jour civil, moments avec présence détectée, lecture enchaînée et extraits téléchargeables pour chaque caméra, en lecture seule de Frigate. [Guide et limites](RECORDING-PLAYBACK.md). Première fonction distribuée par paquet signé sur l’installation de développement. Vignettes et filtre par objet livrés en alpha.21.

## Mise à jour du logiciel 0.8.0-alpha.19

Import signé depuis le navigateur, superviseur indépendant, copie préalable et retour arrière avant validation, reprise après interruption. [Guide et limites](BROWSER-UPDATES.md). Restent ouverts : migrations de schéma réversibles, rotation de confiance, mises à jour des composants et qualification prolongée. Nettoyage des copies livré en alpha.24.

## Administration quotidienne 0.8.0-alpha.18

Panneau de configuration, préférences versionnées, accès regroupés et révocation des sessions de console. [Guide et périmètre](CONTROL-PANEL.md). Cette étape prépare le parcours d’administration du jalon 0.9. La réduction des privilèges Docker et la matrice matérielle restent ouvertes. Le premier parcours de mise à jour avec retour arrière arrive en alpha.19.

## Fraîcheur vidéo 0.8.0-alpha.16

Mesures Frigate datées, état périmé, surveillance du direct et absence de faux retour à la normale des alertes. [Incident, récupération et limites](VIDEO-FRESHNESS.md). La détection par image reste ouverte. Une exception WebSocket retrouvée dans les traces est corrigée et reproduite sur banc en [alpha.17](FRIGATE-WEBSOCKET.md).

## Vue d’ensemble des caméras 0.8.0-alpha.15

Inventaire sans vidéo, états de réception explicites et ouverture d’un direct à la fois. Réponses tardives écartées ; consultation lecteur et réglages administrateur séparés. [Guide et captures](CAMERA-OVERVIEW.md). La charge multi-caméra réelle, l’intégrité des enregistrements et l’endurance restent à qualifier.

## Aperçu des ouvertures 0.8.0-alpha.14

Projection en lecture seule du calendrier sur les sept prochains jours, exceptions et changements d’heure inclus. Affichage des offsets UTC, intervalles en cours et borne de consultation. [Guide](OPENING-PREVIEW.md). La prédiction des heures d’exécution et des durées reste hors périmètre.

## Plages multiples et exceptions 0.8.0-alpha.13

Plusieurs plages quotidiennes ou hebdomadaires ; fermeture ou remplacement d’une date civile, priorité sur la continuation de la veille, simulation et confirmation du calendrier exact. [Guide](DATE-EXCEPTIONS.md). Les calendriers de jours fériés, exceptions annuelles et quotas restent ouverts.

## Créneaux hebdomadaires 0.8.0-alpha.12

Plage indépendante par jour sélectionné, continuation rattachée au jour de départ, union des recouvrements et compatibilité du mode quotidien. Simulation et confirmation présentent le calendrier exact. [Guide](WEEKLY-WINDOWS.md). Les exceptions datées et plages multiples sont livrées dans alpha.13 ; les quotas restent ouverts.

## Créneau de nettoyage 0.8.0-alpha.11

Plage quotidienne enregistrée avec la règle, démarrage contrôlé sous verrou, report persistant et regroupement des captures en attente. Une tâche commencée va jusqu’au contrôle final. [Guide](MAINTENANCE-WINDOW.md). Les créneaux par jour de semaine sont livrés dans alpha.12 ; les quotas de stockage restent ouverts.

## Règles calendaires 0.8.0-alpha.10

Union des derniers points et des derniers jours, semaines ISO et mois contenant des captures réussies. Fuseau enregistré, motifs visibles dans la simulation et même sélection en mode automatique. Règles existantes préservées. [Guide](CALENDAR-RETENTION.md). Le créneau quotidien est livré dans alpha.11.

## Reprise du nettoyage 0.8.0-alpha.9

Simulation persistante, confirmation avec liste des points conservés, nettoyage seul et contrôle de structure. Résultats partiels explicites, sans rejeu et sans réactivation de règle. [Guide](REPOSITORY-CLEANUP.md). Les règles calendaires sont livrées dans alpha.10 ; le créneau quotidien est livré dans alpha.11.

## Rétention automatique 0.8.0-alpha.8

Activation par dépôt après simulation, déclenchement après les nouvelles captures réussies, déduplication persistante, désactivation versionnée et suspension sur incident avec alerte locale. Reprise de base/NAS neutralisant les règles. Les règles calendaires sont livrées dans alpha.10 ; le créneau quotidien est livré dans alpha.11. La reprise du nettoyage est livrée dans alpha.9. [Guide](AUTOMATIC-RETENTION.md).

## Rétention explicite 0.8.0-alpha.7

Simulation depuis Snapshots, conservation des derniers points réussis par groupe, points partiels/importés protégés et confirmation à usage unique. Suppression, nettoyage et contrôle de structure par tâche persistante ; interruption signalée sans rejeu. Dépôt chiffré temporaire et restauration témoin vérifiés. La rétention automatique, les règles calendaires et la reprise d’un nettoyage seul restent ouvertes. [Guide](BACKUP-RETENTION.md).

## Emails SMTP 0.8.0-alpha.6

Configuration web SMTP, chiffrement obligatoire, compte et secret protégés, expéditeur/destinataire et livraison via la file persistante. STARTTLS, TLS direct, refus, reprise après redémarrage et Message-ID stable vérifiés sur récepteur isolé. La délivrabilité chez un fournisseur réel, OAuth2 et les destinataires multiples restent ouverts. [Guide](SMTP-NOTIFICATIONS.md).

## Notifications externes 0.8.0-alpha.5

Configuration web de ntfy et webhook JSON, file persistante, filtres, reprise et suivi des livraisons. Parcours navigateur et réseau validés avec un récepteur isolé ; le push sur téléphone réel, les destinations multiples et l’observateur externe restent ouverts. [Guide](EXTERNAL-NOTIFICATIONS.md).

## Alertes locales 0.8.0-alpha.4

Collecte indépendante du navigateur, incidents persistants, prise en compte versionnée, historique et badge global. Couverture initiale des services connus, du débit caméra, des derniers résultats de sauvegarde et de l’espace du volume de Nacre. Les diagnostics d’intégrité vidéo et les alertes de tous les pools restent ouverts. La notification externe est ajoutée au jalon suivant. [Guide](LOCAL-ALERTS.md).

## Préparation et persistance 0.8.0-alpha.3

Plan/apply pour les prérequis Ubuntu 24.04 et installation du service utilisateur par `installer.py --service`. Retour après redémarrage et tâches systemd vérifiés sur VM ARM64 neuve. La préparation multi-distribution, une matrice matérielle étendue et la mise à jour transactionnelle restent ouvertes. [Recette](HOST-BOOTSTRAP.md).

## Avancement produit 0.8.0-alpha.1

Installation des composants applicatifs depuis Services ; ajout et correction Tapo/RTSP depuis Surveillance, sélection de caméra et ONVIF optionnel. Les tâches et secrets restent séparés. La préparation de Docker sur Linux, la politique du service natif, la qualification multi-caméra réelle et l’installation transactionnelle restent ouvertes.

## Premier démarrage 0.7.0-alpha.5

Le développement revient au parcours utilisateur : préparation de la console en une commande, assistant authentifié, capacités lisibles et préférences portables. Les fonctions existantes deviennent accessibles à partir d’un point de départ commun. À ce jalon, l’installation des composants, l’ajout de caméra entièrement web et la mise à jour transactionnelle restaient à développer. Les campagnes longues de qualification sont réservées à la stabilisation.

## Qualification du stockage 0.7.0-alpha.4

Reprise sur Ubuntu vierge x86-64 et ARM64, création d’un nouveau miroir Btrfs et remplacement d’un membre RAID1 validés sur disques images, avec redémarrage et contrôle des comptes. Trois coupures virtuelles pendant reconstruction sont ajoutées, avec correction de la reprise `read-auto`. Les écritures HTTP/SMB/locales pendant reconstruction et la reprise d’une vraie caméra sur Linux ARM64 vierge complètent ce parcours ; les fichiers privés root de Frigate sont désormais inclus dans le kit. Le jalon suivant combine trois coupures virtuelles avec des écritures actives et un journal de confirmations externe ; les dépôts web sont synchronisés avant succès. Le cycle 0.7 reste ouvert : import dégradé, hotplug matériel, perte des caches physiques lors d’une coupure électrique et autres combinaisons de systèmes de fichiers restent à qualifier.

## Priorités transverses

- Accessibilité clavier, contraste, erreurs compréhensibles et parcours mobiles.
- Journal d’activité orienté décision : problème, conséquence, action possible.
- Mesures d’endurance, interruption réseau, disque plein, redémarrage et données volumineuses.
- Inventaire des dépendances et décision de licence avant toute ouverture publique.
- Compatibilité annoncée par combinaison testée, sans promesse universelle.

## Règle de clôture

Une issue n’est terminée qu’avec comportement documenté, validation pertinente et limites restantes explicites. Une capture d’écran prouve une interface ; elle ne prouve ni la durabilité des données ni le comportement après panne.
