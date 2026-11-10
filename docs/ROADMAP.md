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

## Notifications externes 0.8.0-alpha.5

Configuration web de ntfy et webhook JSON, file persistante, filtres, reprise et suivi des livraisons. Parcours navigateur et réseau validés avec un récepteur isolé ; le push sur téléphone réel, SMTP, les destinations multiples et l’observateur externe restent ouverts. [Guide](EXTERNAL-NOTIFICATIONS.md).

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
