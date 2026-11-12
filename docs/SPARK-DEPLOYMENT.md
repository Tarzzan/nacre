# Déploiements de la console sur Spark

## 12 novembre 2026 — alpha.21

L’installation alpha.20 a reçu le paquet `nacre-0.8.0-alpha.21.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.21), construit depuis le commit [`8d603df`](https://github.com/Tarzzan/nacre/commit/8d603df60f4fab492fa8b03d220a4c09717ce225) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md) qu’alpha.20.

Avant l’import : neuf modules figés identiques entre Spark et le paquet, aucune tâche active, répétition de la mise à jour alpha.20 → alpha.21 sur une console et son superviseur en répertoire temporaire. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé à la route d’import par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 8 h 49 min 24 s et la validation à 8 h 49 min 59 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configuration Samba et configuration Frigate identiques avant et après ; seul l’horodatage du collecteur d’alertes a changé dans les réglages, sans alerte active. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé. Samba a répondu à `smbcontrol smbd ping`.

Les [événements de la relecture](RECORDING-PLAYBACK.md) ont été contrôlés sur la caméra réelle : 47 événements le jour même, 115 la veille, 183 l’avant-veille, 92 le 9 novembre, tous rattachés à une plage conservée. Seul le 9 novembre compte deux types (personnes et un enregistrement manuel) : le filtre y apparaît, réduit la liste à une vignette et place un repère sur la frise. Un événement a été lu sans erreur en 2880 × 1620, sans message de reprise. Douze vignettes ont été chargées par la page en 175 × 175 ; un identifiant inconnu est refusé. Aucune image de surveillance n’a été capturée ni publiée.

Limite de ce contrôle : le navigateur de pilotage ne dessinait pas la page, son panneau étant masqué. Le chargement des vignettes au défilement n’a donc pas été observé sur Spark ; il l’a été sur le banc simulé, et les vignettes de Spark ont été chargées en le forçant. Sur cette caméra, Frigate ne suit que les personnes : le filtre par type reste absent des jours ordinaires.

Les copies de retour arrière occupent désormais 3 Mo pour deux mises à jour dans `state/console/updates/`, toujours sans purge automatique. Le fuseau de la console n’est toujours pas réglé (heures UTC). Aucune panne n’a été injectée sur Spark.

## 11 novembre 2026 — alpha.20, première mise à jour par paquet signé

![Mise à jour réussie sur Spark](images/spark-alpha20-update.jpg)

L’installation alpha.19 a reçu le paquet `nacre-0.8.0-alpha.20.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.20), construit depuis le commit [`82b65ea`](https://github.com/Tarzzan/nacre/commit/82b65ea21e885eafb80c8ef06179b9073111ee3b) après validation CI x86-64/ARM64. C’est le premier usage réel du [parcours de mise à jour](BROWSER-UPDATES.md) : aucun script de déploiement accompagné n’a servi.

Avant l’import, les neuf modules figés de Spark ont été comparés à ceux du paquet (identiques), et la même mise à jour a été répétée sur une console alpha.19 et son superviseur dans un répertoire temporaire. Sur Spark, le paquet a été envoyé à la route d’import de la page Mises à jour par une session administrateur temporaire, refermée ensuite ; le navigateur de pilotage ne pouvait pas sélectionner un fichier local. La signature a été vérifiée par Spark, puis l’installation confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie** et au rechargement, session conservée.

Le superviseur a enregistré la préparation à 23 h 51 min 17 s et la validation à 23 h 51 min 53 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, configuration Samba et configuration Frigate identiques avant et après ; seul l’horodatage du collecteur d’alertes a changé dans les réglages, sans alerte active. Les conteneurs Samba et Frigate gardent leurs identifiants et heures de démarrage ; le service systemd n’a pas été relancé, le superviseur ayant remplacé la console lui-même. Samba a répondu à `smbcontrol smbd ping`.

La [relecture](RECORDING-PLAYBACK.md) a ensuite été contrôlée sur la caméra réelle : quatre jours proposés, journée en cours en une plage avec sept moments détectés, jour ancien réduit à 127 passages conservés. Un extrait du jour et un extrait de l’avant-veille ont été lus sans erreur en 2880 × 1620. Aucune image de surveillance n’a été capturée ni publiée.

Deux observations pour l’exploitation : le fuseau de la console de Spark n’a jamais été réglé, la relecture y affiche donc des heures UTC tant qu’il n’est pas choisi dans le Panneau de configuration ; les copies de retour arrière (code et base précédents, 1,5 Mo) restent dans `state/console/updates/`, sans purge automatique. Aucune panne n’a été injectée sur Spark : le retour arrière automatique reste prouvé sur bancs isolés uniquement.

## 11 novembre 2026 — alpha.13

![Services sur Spark après mise à jour](images/spark-alpha13-services.jpg)

L’installation alpha.6 a reçu les 46 fichiers de console et modules associés du commit [`b52d6c8`](https://github.com/Tarzzan/nacre/commit/b52d6c8f7af77de067e35076f52bc1ee63105507), après validation CI x86-64/ARM64. Empreintes du paquet et des fichiers contrôlées ; code Python compilé avant remplacement.

La console a été seule relancée. Comptes, empreintes des mots de passe, clés, configurations, dépôts, plans et profils de stockage comparés avant/après ; identités et dates de démarrage de Samba et Frigate inchangées. Schéma SQLite 2 conservé et `quick_check` réussi. Neuf routes authentifiées contrôlées, dont la liste des règles de rétention. Aucune tâche active, aucun plan activé et aucune règle de rétention préexistante au moment de cette mise à jour. Notifications externes désactivées.

Samba a répondu au contrôle `smbcontrol smbd ping` ; Frigate a signalé une caméra recevant des images. Le navigateur a affiché alpha.13. L’intervalle mesuré entre arrêt de console terminé et fin des contrôles du script est de 0,63 seconde, sans mesure d’interruption vidéo ni redémarrage de ses conteneurs.

Les copies privées de retour arrière restent sur Spark dans `.updates/alpha13-20261111/` : ancien code, copie cohérente SQLite, fichiers ajoutés, manifeste et résultat. Le script prévoit un retour au code précédent si les contrôles échouent. Comme le schéma reste 2, la base vivante est conservée lors de ce retour pour éviter d’effacer d’éventuelles écritures après relance ; la copie privée reste disponible pour une reprise manuelle contrôlée. Cette branche d’échec n’a pas été déclenchée en production.

Ce document conserve les observations de chaque déploiement ; les notes des versions publiées complètent cette chronologie. Les essais de panne restent isolés.

## 10 novembre 2026 — alpha.6

Le 10 novembre 2026, l’installation existante de Spark (Linux ARM64, Python 3.12.3) est passée de **0.7.0-alpha.1** à **0.8.0-alpha.6**. Le code déployé est le commit [`c453124`](https://github.com/Tarzzan/nacre/commit/c45312410406fb871588fea3ac6bf34978454ae6), qui inclut le correctif d’affichage ajouté après le tag alpha.6.

La version de Spark a été vérifiée par son API authentifiée et dans le navigateur. Le port local **8766** donne accès à Spark via le tunnel SSH existant ; **8768** reste une console de test distincte.

![Notifications sur Spark après mise à jour, envois désactivés](images/spark-alpha6-notifications.jpg)

## Résultats observés

| Contrôle | Résultat |
| --- | --- |
| Sources installées | 40 fichiers, empreintes SHA-256 conformes au commit déployé |
| Base SQLite | Schéma 1 → 2 ; `quick_check` réussi |
| Comptes, droits, empreintes des mots de passe | Identiques avant et après |
| Clés de sauvegarde et configurations contrôlées | Empreintes identiques |
| Dépôts, plans et profils de stockage | Enregistrements identiques |
| Tâches actives / plans activés au déploiement | 0 / 0 |
| Samba et Frigate | Identifiants de conteneurs et dates de démarrage identiques |
| Samba après déploiement | Réponse au contrôle `smbcontrol smbd ping` |
| Caméra existante | Une caméra dans les statistiques Frigate ; réception d’images positive |
| Accès web | Huit routes authentifiées contrôlées ; vues Notifications et Services vérifiées |
| Notifications externes | Désactivées, aucune destination ni livraison en attente |

Les huit routes sont `/api/me`, `/api/notifications`, `/api/setup`, `/api/alerts`, `/api/smb`, `/api/storage`, `/api/protection/plans` et `/api/protection/migrations`. La session temporaire utilisée pour ces contrôles a été supprimée après vérification.

Seule la console a été arrêtée et relancée. La durée mesurée entre son arrêt terminé et la fin des contrôles du script est de 0,82 seconde ; ce chiffre ne mesure pas une interruption vidéo. Aucun disque, pool, compte ou destination de sauvegarde n’a été créé. Le fichier Compose existant et les configurations privées ont été conservés.

## Préparation et retour arrière

Les 11 tests de migration SQLite ont été exécutés sur des bases temporaires locales et ont réussi. Le commit produit disposait également d’une [CI réussie](https://github.com/Tarzzan/nacre/actions/runs/42820854577) avant son installation.

Un paquet limité aux sources de la console, aux modules Python nécessaires et au changelog a été préparé depuis Git. Son empreinte a été vérifiée sur Spark, puis les fichiers Python ont été compilés avant de remplacer le code installé. Un verrou exclusif a protégé la copie de base et le remplacement des sources pendant l’arrêt de la console.

Dans le répertoire privé `.updates/alpha6-20261110/` de l’installation restent :

- `before-code.tar.gz` : versions précédentes des fichiers remplacés ;
- `before.sqlite3` : copie cohérente de la base avant migration ;
- `added.json` : fichiers introduits par la mise à jour ;
- `manifest.json` : commit et empreintes du paquet ;
- `result.json` : résultat synthétique des contrôles.

Ces copies restent sur Spark. La base contient des informations privées et ne doit pas être publiée. Un retour au code précédent exige aussi le retour à son schéma de base, avec console et tâches arrêtées. Il faut examiner les changements intervenus depuis la mise à jour avant de restaurer cette copie : elle ne contient pas les opérations ultérieures.

Le script de déploiement prévoyait un retour au code et à la base précédents en cas d’échec de ses contrôles. Cette branche de retour arrière n’a pas été déclenchée sur Spark ; aucun échec n’a été injecté sur l’installation réelle.

## Portée

Ce compte rendu atteste la mise à jour de la console et la continuité des services observée. Il ne constitue pas une nouvelle qualification destructive des pools, un test de remise d’email externe ou une installation de l’agent de stockage privilégié. Cet agent n’était pas actif sur Spark. Les essais de coupure et de reconstruction restent documentés dans les laboratoires isolés.
