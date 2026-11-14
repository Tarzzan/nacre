# Sécurité

## Statut

Nacre 0.5 est un prototype de laboratoire. Le serveur HTTP écoute sur loopback ; utiliser le tunnel SSH prévu. L’exposition directe à Internet, le durcissement multi-utilisateur et un audit indépendant ne sont pas validés.

## Signaler un problème

Dans ce dépôt privé, contacter le propriétaire via les canaux privés déjà convenus. Ne pas ouvrir d’issue contenant un mot de passe, une vidéo, une clé, une configuration personnelle ou une procédure exploitable avec des données réelles. Si GitHub propose « Report a vulnerability », utiliser ce parcours privé. Aucun délai contractuel de correction n’est annoncé.

## Secrets et données

`.env`, `state/`, `data/`, `.tools/`, clés SSH, bases de données, journaux, images de disques et archives d’installation doivent rester hors de Git. Les identifiants initiaux sont générés sur l’hôte et ne sont jamais ceux d’un exemple documentaire. Un dépôt privé ne rend pas acceptable l’ajout d’un secret.

Avant un push, lancer les contrôles du dépôt. Si un secret est commité, le révoquer ou le remplacer, puis traiter l’historique : supprimer seulement le fichier courant ne retire pas les anciennes versions.

## Modèle de confiance

Le helper root ne reçoit que des opérations fermées et vérifie ses ressources. Le compte de console conserve néanmoins des droits Docker élevés, équivalents à root sur l’hôte. Les sessions et CSRF ne compensent pas une compromission de ce compte. Le processus web ne demande à Docker qu’une liste fermée d’opérations. Un agent de services, installé par root, peut la tenir à sa place et permet de retirer cet accès au compte de la console ; un chemin plus étroit reste alors ouvert par les conteneurs. Le [plan de réduction](docs/SERVICE-AGENT.md) dit ce qui est fait et ce qui reste. Les détails sont dans [Architecture](docs/ARCHITECTURE.md).

Snapshots locaux, RAID et chiffrement répondent à des risques différents. Une copie sur un support distinct et un essai de restauration restent nécessaires pour qualifier un dispositif de protection.
