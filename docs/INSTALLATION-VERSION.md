# Identifier la version de la console

La console affiche la version déclarée dans le `CHANGELOG.md` du **code installé**, dans le pied de la barre latérale et sur la vue d’ensemble. Le serveur la transmet avec la session ; aucun numéro de version produit n’est recopié dans le JavaScript. Le répertoire des données (`NAS_ROOT`) ne détermine pas cette version. Si le fichier est absent ou illisible, l’interface affiche « version non identifiée ».

Ce numéro identifie la version déclarée de la distribution. Il ne prouve pas que les fichiers n’ont pas été modifiés : une vérification d’empreintes reste nécessaire pour attester leur correspondance à une publication.

Une console de test locale et une installation sur un NAS peuvent utiliser des versions différentes. Publier une release GitHub ou actualiser la console de test ne met pas automatiquement à jour un autre hôte.

Le 10 novembre 2026, le texte historique `Nacre 0.6-dev` a été trouvé dans l’interface de Spark. Les 22 fichiers de code comparés (console Python, JavaScript, CSS, HTML et `lab.py`) correspondaient exactement à `v0.7.0-alpha.1`. Seul le libellé a été corrigé avec copie de retour arrière, sans redémarrer la console, Samba ou Frigate. Cela ne constitue pas un déploiement des fonctions 0.8 sur Spark.
