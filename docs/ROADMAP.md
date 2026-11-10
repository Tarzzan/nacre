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

## Avancement 0.7.0-alpha.2

Reprise sur Ubuntu vierge x86-64 et ARM64, création d’un nouveau miroir Btrfs et remplacement d’un membre RAID1 validés sur disques images, avec redémarrage et contrôle des comptes. Trois coupures virtuelles pendant reconstruction sont ajoutées, avec correction de la reprise `read-auto`. Le cycle 0.7 reste ouvert : import dégradé, hotplug matériel, perte des caches physiques lors d’une coupure électrique et autres combinaisons de systèmes de fichiers restent à qualifier.

## Priorités transverses

- Accessibilité clavier, contraste, erreurs compréhensibles et parcours mobiles.
- Journal d’activité orienté décision : problème, conséquence, action possible.
- Mesures d’endurance, interruption réseau, disque plein, redémarrage et données volumineuses.
- Inventaire des dépendances et décision de licence avant toute ouverture publique.
- Compatibilité annoncée par combinaison testée, sans promesse universelle.

## Règle de clôture

Une issue n’est terminée qu’avec comportement documenté, validation pertinente et limites restantes explicites. Une capture d’écran prouve une interface ; elle ne prouve ni la durabilité des données ni le comportement après panne.
