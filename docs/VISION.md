# Nacre — vision et cadrage

## La demande, reformulée

> Structurer Nacre comme un produit logiciel indépendant, documenté et vérifiable, qui unifie le stockage, la protection des données et la vidéosurveillance dans une console web. Construire une base portable sur Linux x86-64 et ARM64, avec des opérations sensibles explicites, des restaurations démontrées et une compatibilité matérielle publiée. Faire évoluer ce socle vers une plateforme administrable sur plusieurs machines, sans dépendance obligatoire à un cloud.

## Pour qui et pour quoi

Le premier utilisateur est le propriétaire d’un petit serveur ou d’un NAS compatible Linux : particulier avancé, atelier ou petite organisation. Il doit comprendre où résident ses données, qui peut y accéder, comment elles sont protégées et comment les récupérer.

Trois parcours structurent le produit : **stocker et partager**, **protéger et restaurer**, **surveiller et retrouver un événement**. Les fonctions techniques sont rattachées à ces parcours ; un tableau de bord doit montrer les problèmes qui demandent une décision.

## Principes

1. **La restauration fait partie de la sauvegarde.** Une fonction de protection est validée par la lecture des données restaurées.
2. **Le matériel est une capacité détectée.** Pas d’hypothèse implicite sur un GPU, un contrôleur ou un fabricant.
3. **Une opération sensible a un plan.** Identité des ressources, effet attendu, confirmation et compte rendu vérifiable.
4. **Une absence n’est pas un succès.** Volume disparu, tâche partielle ou diagnostic inconnu restent visibles.
5. **Le navigateur est le poste de commande.** Les tâches durables continuent sans onglet ouvert.
6. **La portabilité se prouve.** Une matrice de tests et de matériels remplace une promesse universelle.

## Ambition progressive

La priorité immédiate est la fiabilité : historique Git, tests reproductibles, récupération après panne, séparation des privilèges et procédure de mise à jour. Viennent ensuite la réparation du stockage et une expérience de configuration cohérente. La gestion de plusieurs NAS devient pertinente après stabilisation de ce socle.

Pistes futures, non implémentées : inventaire fédéré de plusieurs hôtes, politiques de protection par groupe, alertes exploitables, ajout guidé de caméras, export de configuration et assistant de reprise après sinistre. Leur conception doit définir authentification inter-hôtes, gestion des clés, révocation et fonctionnement hors connexion.

## Critères de réussite

- Un utilisateur peut expliquer la destination et la portée de sa sauvegarde.
- Une restauration sur un hôte neuf est documentée et rejouable.
- Une coupure à chaque étape sensible produit un état exploitable, sans succès supposé.
- Les architectures annoncées passent les tests ; les matériels non testés sont identifiés.
- Aucun secret de déploiement ni donnée utilisateur n’entre dans l’historique source.

## Périmètre assumé

Nacre n’est actuellement ni une distribution Linux installable, ni un firmware de remplacement universel pour boîtiers propriétaires. Le projet assemble son propre code et des composants tiers ; il ne redistribue pas DSM/QTS ou Surveillance Station. Les calendriers et fonctions envisagés restent soumis à leur validation technique.
