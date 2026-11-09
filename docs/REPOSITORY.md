# Gouvernance du dépôt

## Configuration initiale vérifiée

- Dépôt privé : [Tarzzan/nacre](https://github.com/Tarzzan/nacre).
- Branche principale : `main` ; contributions par branches et pull requests.
- Cinq contrôles requis : tests sur Ubuntu x86-64/ARM64 avec Python 3.11/3.12 et détection de secrets Gitleaks.
- Branche à jour exigée avant fusion ; push forcé et suppression de `main` interdits.
- Aucun nombre minimal de revue humaine n’est imposé pour ce dépôt actuellement maintenu par son propriétaire. Ajouter une revue obligatoire dès qu’un second mainteneur est disponible.
- Le propriétaire administrateur conserve la possibilité de contourner les règles. Ce choix permet la récupération du dépôt ; il ne doit pas devenir le parcours de contribution habituel.
- Fusion squash uniquement et suppression automatique de la branche fusionnée.
- Issues et modèles activés ; wiki désactivé pour garder la documentation dans les revues du code.

La [première exécution CI](https://github.com/Tarzzan/nacre/actions/runs/42718759998) a réussi sur les cinq jobs. Les résultats futurs doivent être consultés dans Actions, sans déduire leur état de ce relevé historique.

## Travail organisé

Trois jalons initialisent la [feuille de route](ROADMAP.md) :

- **0.6 — Fiabilité et reprise** : [reprise et migrations](https://github.com/Tarzzan/nacre/issues/1), [réduction des privilèges Docker](https://github.com/Tarzzan/nacre/issues/2).
- **0.7 — Cycle de vie du stockage** : [remplacement de disque et reconstruction RAID1](https://github.com/Tarzzan/nacre/issues/3).
- **0.8 — Protection et surveillance** : [rétention et programmation native](https://github.com/Tarzzan/nacre/issues/4), [compatibilité et plusieurs caméras](https://github.com/Tarzzan/nacre/issues/5).

Chaque issue contient un objectif, des cases de validation et les contraintes du laboratoire. Aucun calendrier artificiel n’a été fixé.

## Publication et licence

Le premier jalon publié est une préversion alpha. Il sert de point de référence récupérable du code, pas de promesse d’aptitude à la production. Une diffusion publique et le choix d’une licence demandent une décision explicite du propriétaire et une revue des composants redistribués.

Git conserve le code et sa documentation. Il ne sauvegarde ni les données du NAS, ni les clés de dépôts, ni les comptes de déploiement. Leur stratégie de reprise est un chantier distinct.
