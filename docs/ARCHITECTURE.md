# Architecture et frontières de confiance

## Composants

| Composant | Responsabilité | Persistance |
| --- | --- | --- |
| `console/server.py` | HTTP, sessions, rôles, API et fichiers | `state/console/console.db` |
| `console/static/` | Interface navigateur | Aucune donnée métier embarquée |
| `console/protection.py` | Dépôts restic, plans et orchestration | SQLite, clés privées et dépôts |
| `console/smb_storage.py` | Configuration SMB, montages contrôlés et surveillance | `state/samba/`, configuration privée |
| `console/native_storage.py` | Daemon root à méthodes fermées | Politique root et catalogue système |
| `console/provisioning.py` | Création de FS et miroir sur disques autorisés | Catalogue natif |
| `compose.yaml`, `samba/`, `frigate/` | Frigate et Samba conteneurisés | Bind mounts et volumes Docker |
| `lab.py` | Initialisation et commandes locales | Configuration d’installation |

## Autorisations

Le serveur web utilise sessions HttpOnly/SameSite Strict, rôles côté serveur et CSRF. Les accès aux fichiers utilisent des descripteurs et refusent les liens symboliques. Les restaurations privées et ressources natives sont réservées à l’administration.

Le helper natif contrôle l’UID via socket Unix, sa politique root et les identités des ressources. Il ne fournit pas de terminal ou de commande arbitraire. Les plans sont temporaires, consommables une fois et revérifiés à l’exécution.

**Limite importante :** le compte de console peut piloter Docker. Cette capacité donne des pouvoirs élevés sur l’hôte, même si le processus HTTP n’est pas root. Réduire cette surface avec un agent à commandes fermées fait partie de la feuille de route. `NoNewPrivileges` ne neutralise pas les droits du socket Docker.

## Stockage et disparition des volumes

Les volumes gérés sont validés par le catalogue, l’UUID et leur montage. Les écritures HTTP épinglent leurs descripteurs ; les transferts sont finalisés sans écrasement silencieux. Les corbeilles natives résident dans `.nacre-trash` sur le même système de fichiers.

Les bind mounts SMB ne créent pas de dossier hôte de repli. Le contrôleur vérifie l’identité montée dans le conteneur, puis active le partage. Sa boucle de cinq secondes réconcilie les volumes absents/revenus ; une indisponibilité de Docker peut retarder la fermeture des connexions déjà ouvertes.

## Protection

Restic produit des captures chiffrées de fichiers, sans gel simultané des applications. Les snapshots natifs sont propres à Btrfs, ZFS ou LVM et ne remplacent pas une copie sur un autre support. Les restaurations créent un nouvel emplacement ; aucun rollback destructif n’est exposé.

Les workers durables et leur état sont distincts de l’onglet navigateur. Les copies LVM utilisent une unité systemd avec namespace de montage privé. Les états partiels, interrompus et inconnus restent distincts du succès.

## Évolutions structurantes

Agent de services moins privilégié ; journal d’audit exportable et résistant à l’altération ; mise à jour transactionnelle ; authentification renforcée ; supervision inter-hôtes. Ces éléments sont des objectifs, pas des garanties de la version 0.5.
