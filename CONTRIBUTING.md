# Contribuer

1. Décrire le problème dans une issue, avec résultat attendu et critères de validation.
2. Créer une branche courte : `feat/...`, `fix/...` ou `docs/...`.
3. Modifier le minimum cohérent, documenter les migrations et conserver les comportements validés.
4. Exécuter les contrôles de [validation](docs/VALIDATION.md). Réserver les opérations natives à une VM isolée.
5. Ouvrir une pull request avec preuves, limites et effets sur les données.
6. Attendre la CI et la revue avant fusion. Cette règle de travail doit être distinguée de son éventuelle application technique par GitHub.

Ne jamais tester un formatage, une suppression ou une reconstruction sur un disque réel pour valider une contribution. Les nouveaux adaptateurs doivent refuser l’identité ambiguë d’une ressource et traiter l’interruption comme un résultat à examiner.

Les captures sont réalisées sur données synthétiques. Les fichiers privés, sorties de `lab.py acces`, URLs d’accès temporaires et configurations caméra ne doivent pas entrer dans une PR.

La décision de licence reste au propriétaire. Ne pas copier de code propriétaire ni introduire une dépendance sans en documenter l’origine et les obligations.
