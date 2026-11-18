# Espaces par le partage réseau (SMB) : cadrage

Rien de ce qui suit n’est encore livré. Cette page fixe le modèle, ce qui est prouvé, et ce qui attend une décision du propriétaire. Elle fait suite au [socle « appareils »](DEVICES.md).

## Le point de départ, à ne pas perdre de vue

- **Le partage réseau n’écoute aujourd’hui que la machine elle-même** (`127.0.0.1:1445` dans `compose.yaml`). Aucun autre poste ne l’atteint, et Windows ne sait pas utiliser ce port. Exposer les espaces n’a d’effet visible qu’une fois un port ouvert sur le réseau local : c’est un geste d’administrateur, jamais un effet de mise à jour.
- **Une mise à jour par paquet ne change ni `compose.yaml` ni l’image Samba.** Tout passe par ce que le code écrit : `state/samba/smb.conf`, `users.tsv`, le fichier de surcharge, et la liste fermée d’opérations.
- **Sous agent de services, rien de tout cela ne passe** sans geste de root : l’agent refuse tout montage hors des volumes natifs et toute clé autre que les montages dans la surcharge. L’ordre entre ce programme et la migration vers l’agent doit être choisi.
- Les comptes du partage réseau sont aujourd’hui distincts des personnes de la console.

## Le modèle retenu

- **Un partage par espace**, dans le fichier unique rendu par `smb_storage.render` : `valid users` = les personnes qui ont un droit, `read only = yes`, `write list` = celles qui écrivent, `access based share enum = yes`. Calculé depuis les droits de la console, à chaque changement.
- **Tout sous le compte de la console** (`force user = nas`) : `data/espaces` n’est traversable que par lui, et ce que SMB écrit lui appartient. L’isolement entre espaces repose donc sur le rendu seul.
- **Noms de partage en minuscules sans accent** (`[a-z][a-z0-9_-]{1,31}`, la règle de la liste fermée), stables au renommage de l’espace.
- **Un mot de passe de partage réseau par personne**, produit par Nacre, montré une fois, sous son identifiant. Samba n’en garde qu’une empreinte NT, sans sel : seul un mot de passe aléatoire long la rend sans valeur. Le mot de passe du compte n’est jamais réutilisé.
- **Révocation** : écrire, recharger, puis **fermer le partage changé**. Un compte désactivé voit aussi ses partages fermés.
- **Fermé par défaut**, deux gestes d’administrateur distincts : servir les espaces en SMB, puis publier le port sur le réseau local.

## Ce qui est prouvé

Sur le vrai Samba de l’image du dépôt (4.22), par un banc isolé et rejouable, `python3 tests/integration_spaces_smb.py` :

- chacun ne **voit** et n’**ouvre** que ses espaces ; un lecteur lit sans écrire ; l’espace personnel d’un autre est refusé ; l’anonyme n’ouvre rien ;
- les dossiers internes ne se voient pas, ne se lisent pas, et un nom `.nacre-…` ne se crée pas ;
- ce que SMB écrit appartient au compte de la console, en 0660 ;
- **un rechargement seul ne révoque rien** ; fermer le partage coupe la connexion ouverte, qui ne revient pas ; une écriture retirée ne passe plus ;
- **désactiver un compte ne coupe pas sa session ouverte** : il faut aussi fermer ses partages ;
- « fermer ce qui est refusé » (`close-denied-share`) coupe aussi les ayants droit quand le partage force un compte : pas plus fin que fermer le partage ;
- les mots de passe survivent à une recréation du conteneur, par le volume de `/var/lib/samba`.

Lu dans la documentation, non rejoué ici : la surcharge Compose **ajoute** un port et un montage sans retirer ceux de `compose.yaml`.

## Ce que SMB contourne, et qu’il faudra dire

- **La double authentification** : un mot de passe de partage réseau suffit.
- **Les versions et la corbeille** : par SMB, écraser ne garde rien et supprimer est définitif. D’où un premier lot **en lecture seule**.
- **Le journal, les index Photos et Recherche, « dernier usage »** : la console ne voit pas ce qui passe par SMB.
- **Console arrêtée ou en mise à jour**, Samba continue avec les droits du dernier rendu : « un accès retiré tombe aussitôt » ne vaut que console en marche.

## Découpage

Ordre de grandeur : **huit à quatorze versions**, selon quatre études relues chacune par un contradicteur. Rien d’utilisable depuis un autre poste avant le lot 3.

| Lot | Contenu | Effet |
| --- | --- | --- |
| 0 | Banc rejouable et ce cadrage | Fait. Aucun effet produit. |
| 1 | Mot de passe de partage réseau par personne ; espaces servis **en lecture**, sur le port local seulement ; fermé par défaut | Prouvable, pas encore utile hors de la machine |
| 2 | Révocation de bout en bout : chaque changement de droit, de rôle, de compte | — |
| 3 | **Publier le port sur le réseau local** : adresse privée choisie, durcissement posé en même temps, retour arrière | Premier usage réel depuis un poste |
| 4 | Écriture par SMB, avec ses limites dites, ou corbeille adoptée | — |
| 5 | Installations sous agent de services (installation accompagnée) | — |

## Décisions qui reviennent au propriétaire

1. **Ouvrir le partage sur le réseau local** de l’installation en service, et sur quelle adresse. Rien n’y sera ouvert sans ce geste.
2. **Un administrateur par SMB** : tous les espaces d’équipe comme dans la console, sans second facteur ; ou seulement ceux où il est nommé ; ou pas d’accès SMB pour les administrateurs.
3. **Écriture par SMB** en sachant que supprimer y est définitif et qu’écraser ne garde pas de version, ou lecture seule tant que la corbeille n’y est pas branchée.
4. **Chiffrement exigé** (postes récents seulement, débit moindre sur petit matériel) ou seulement proposé.
5. **Ordre** entre ce programme et la migration vers l’agent de services.

Les rendus complets du cadrage, avec leurs sources, ne sont pas dans le dépôt.
