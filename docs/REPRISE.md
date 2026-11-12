# Note de reprise

Point d’entrée pour reprendre le développement sans relire tout l’historique. À mettre à jour à chaque livraison ; le détail reste dans le [changelog](../CHANGELOG.md), la [feuille de route](ROADMAP.md) et les guides.

## État livré

- **Version courante : 0.8.0-alpha.20** — [relecture des enregistrements par jour](RECORDING-PLAYBACK.md).
- Version précédente : 0.8.0-alpha.19 — [mises à jour signées depuis le navigateur](BROWSER-UPDATES.md).
- Schéma SQLite inchangé depuis alpha.19. Aucun module figé modifié par alpha.20 : la version est distribuable par paquet `.nacre-update`.
- Installation de développement : alpha.20 installée le 11 novembre 2026 par paquet signé, premier usage réel de ce parcours. Le détail et les mises à jour suivantes sont consignés dans [Déploiements](SPARK-DEPLOYMENT.md) ; vérifier la version réellement installée avant d’agir.

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
- **Vidéo.** Nacre lit l’API interne de Frigate ; il ne modifie la configuration que par les tâches de caméra. La relecture est en lecture seule. Frigate produit les extraits sans plages d’octets : la frise sert de déplacement.
- **Déployer.** Comparer d’abord les modules figés de l’installation à ceux du paquet, répéter la mise à jour sur une console temporaire de la version installée, puis importer le paquet de la release. Relever les empreintes des comptes et configurations avant et après.
- **Bancs.** Les essais d’interface utilisent une console réelle avec un service vidéo simulé et une mire synthétique. Aucune image de surveillance, session ou secret n’entre dans le dépôt.
- **Qualification.** Une suite complète par changement suffit. Les campagnes QEMU longues sont réservées aux changements de stockage ou de reprise.

## Limites ouvertes

- Fuseau : une installation dont les préférences n’ont jamais été enregistrées affiche des heures UTC, relecture comprise.
- Surveillance : pas de vignettes, de recherche par objet, d’export long ni de lecture multi-caméra synchronisée ; une seule caméra réelle observée.
- Mises à jour : pas de migration de schéma réversible, de rotation de la clé de confiance, de purge des copies locales ni de mise à jour des composants.
- Stockage : pas de programmation des snapshots natifs ([issue 4](https://github.com/Tarzzan/nacre/issues/4)) ; opérations privilégiées validées en VM seulement.
- Administration : pas de MFA ; accès à Docker encore large ([issue 2](https://github.com/Tarzzan/nacre/issues/2)).

## Prochaine étape recommandée

1. **Purge et consultation des copies de mise à jour** depuis le Panneau de configuration. Les copies s’accumulent dans `state/console/updates`. Le moteur étant figé, prévoir une installation accompagnée ou un module séparé qui ne touche pas au superviseur.
2. **Programmation des snapshots natifs** avec simulation de rétention (issue 4). Modules natifs figés : campagne en VM et installation accompagnée.
3. **Événements Frigate dans la relecture** : vignettes et filtre par type d’objet, à partir de l’API d’événements. Compatible avec un paquet web.

Le troisième prolonge directement alpha.20 et reste distribuable par le navigateur ; les deux premiers lèvent des limites plus structurantes.
