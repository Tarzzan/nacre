# Note de reprise

Point d’entrée pour reprendre le développement sans relire tout l’historique. À mettre à jour à chaque livraison ; le détail reste dans le [changelog](../CHANGELOG.md), la [feuille de route](ROADMAP.md) et les guides.

## État livré

- **Version courante : 0.8.0-alpha.23** — [recherche d’événements sur plusieurs jours](RECORDING-PLAYBACK.md#rechercher-sur-plusieurs-jours) par type d’objet, depuis la fiche d’une caméra.
- Versions précédentes : 0.8.0-alpha.22 — [détection et objets suivis par caméra](CAMERA-DETECTION.md), appliqués sans redémarrer le service vidéo ; 0.8.0-alpha.21 — [événements en vignettes et filtre par type d’objet dans la relecture](RECORDING-PLAYBACK.md) ; 0.8.0-alpha.20 — relecture des enregistrements par jour ; 0.8.0-alpha.19 — [mises à jour signées depuis le navigateur](BROWSER-UPDATES.md).
- Schéma SQLite inchangé depuis alpha.19. Aucun module figé modifié d’alpha.20 à alpha.23 : ces versions sont distribuables par paquet `.nacre-update`.
- Installation de développement : alpha.22 installée le 12 novembre 2026 par paquet signé, après alpha.21 le matin même et alpha.20 la veille. La carte Détection y a été éprouvée sur la caméra réelle (ajout puis retrait d’un type, sans redémarrage) ; les types suivis y sont revenus aux seules personnes. Le détail et les mises à jour suivantes sont consignés dans [Déploiements](SPARK-DEPLOYMENT.md) ; vérifier la version réellement installée avant d’agir.

## Reprendre en cinq minutes

1. `git status`, `git log --oneline -5`, puis les PR et issues ouvertes.
2. Lire cette note, la [feuille de route](ROADMAP.md) et le guide de la fonction touchée.
3. Tests : `python -m unittest discover -s tests` avec `NAS_RESTIC_BIN` pointant sur `.tools/restic`, puis `node --test tests/test_frontend.js`. La CI rejoue les deux sur x86-64 et ARM64.
4. Travailler sur une branche, ouvrir une PR, attendre les contrôles requis, fusionner en squash.

## Décisions à connaître

- **Le premier titre du changelog est la version.** `console/release.py` la lit ; ajouter une entrée en tête change la version annoncée par la console.
- **Mises à jour web.** Un paquet ne peut pas modifier le schéma SQLite ni les modules figés listés dans `PINNED` de `console/update_engine.py`. Toute fonction qui y touche demande une installation accompagnée. Préférer un nouveau module et la table `settings` existante quand c’est possible.
- **Clé de signature.** Elle reste hors du dépôt et hors du NAS. Un paquet se construit depuis le commit exact validé par la CI, avec `scripts/build_update.py`.
- **Interface sans style en ligne.** La politique de sécurité (`style-src 'self'`) bloque les attributs `style`. Les positions calculées passent par des attributs SVG ou des classes. Les liens à comportement natif ne portent pas `data-action` : le gestionnaire global annule l’action par défaut.
- **Réponses tardives.** Chaque écran vérifie session, page et numéro de requête avant d’écrire dans la page. Les tests JavaScript couvrent ce point pour chaque vue.
- **Vidéo.** Nacre lit l’API interne de Frigate ; il reste le seul rédacteur de `config.yml`, par les tâches de caméra, les réglages et la carte Détection. Frigate 0.18.2 refuse d’enregistrer lui-même un fichier au format écrit par Nacre (`/api/config/set` sans `skip_save` échoue) : un réglage à chaud s’écrit donc dans le fichier par Nacre, puis s’applique par `skip_save` avec un filtre par type suivi, ou par une commande WebSocket que Frigate mémorise (détection). L’état affiché est celui relu dans `/api/config`. La relecture est en lecture seule. Frigate produit les extraits sans plages d’octets : la frise sert de déplacement. Les événements viennent de `/api/events` ; leur absence ne doit jamais casser la frise. Un filtre s’applique sur la page ouverte, sans reconstruire la carte, pour garder la lecture et les vignettes déjà chargées. La recherche sur plusieurs jours compte et pagine elle-même : le résumé d’événements de Frigate renvoie presque une ligne par événement, sans borne de dates, et son indicateur `has_clip` reste vrai après la suppression de la vidéo. La page suivante se demande par « avant cet instant » : deux objets vus sur la même image commençant au même instant, une page ne se termine jamais entre deux événements simultanés. L’indice « Vidéo non conservée » vient donc du résumé d’enregistrements par heure, et la relecture du jour reste seule à lire la vidéo.
- **Déployer.** Comparer d’abord les modules figés de l’installation à ceux du paquet, répéter la mise à jour sur une console temporaire de la version installée, puis importer le paquet de la release. Relever les empreintes des comptes et configurations avant et après.
- **Bancs.** Les essais d’interface utilisent une console réelle avec un service vidéo simulé et une mire synthétique. Aucune image de surveillance, session ou secret n’entre dans le dépôt.
- **Qualification.** Une suite complète par changement suffit. Les campagnes QEMU longues sont réservées aux changements de stockage ou de reprise.

## Limites ouvertes

- Fuseau : une installation dont les préférences n’ont jamais été enregistrées affiche des heures UTC, relecture comprise.
- Surveillance : recherche limitée à une caméra et au type d’objet (ni nom reconnu, ni tranche horaire) ; pas de filtre par zone, d’export long ni de lecture multi-caméra synchronisée ; une seule caméra réelle observée ; pas de réglage des seuils, zones et masques de détection.
- Mises à jour : pas de migration de schéma réversible, de rotation de la clé de confiance, de purge des copies locales ni de mise à jour des composants.
- Stockage : pas de programmation des snapshots natifs ([issue 4](https://github.com/Tarzzan/nacre/issues/4)) ; opérations privilégiées validées en VM seulement.
- Administration : pas de MFA ; accès à Docker encore large ([issue 2](https://github.com/Tarzzan/nacre/issues/2)).

## Prochaine étape recommandée

1. **Purge et consultation des copies de mise à jour** depuis le Panneau de configuration. Les copies s’accumulent dans `state/console/updates`. Le moteur étant figé, prévoir une installation accompagnée ou un module séparé qui ne touche pas au superviseur.
2. **Programmation des snapshots natifs** avec simulation de rétention (issue 4). Modules natifs figés : campagne en VM et installation accompagnée.
3. **Vue d’ensemble des événements récents de toutes les caméras** sur la page Surveillance : réutilise la recherche d’alpha.23, lecture seule de Frigate, distribuable par paquet. Utile surtout à partir de deux caméras.

Les deux premiers lèvent des limites structurantes mais demandent une installation accompagnée ; le troisième reste livrable par le navigateur.
