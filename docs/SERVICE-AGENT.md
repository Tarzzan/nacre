# Réduire les privilèges de la console sur Docker

Ce document répond à l’[issue 2](https://github.com/Tarzzan/nacre/issues/2). Il dit ce que la console peut faire aujourd’hui par Docker, ce que cela expose, la cible, et où en est chaque lot. Le premier lot est livré en 0.8.0-alpha.43 ; **il ne retire encore aucun privilège** : il ferme et documente ce que le processus web demande à Docker, ce qui est le préalable à tout le reste.

## Modèle de menace

**Situation de départ.** La console tourne sous un compte ordinaire, qui pilote Docker parce qu’il appartient au groupe `docker`. Ce groupe donne accès au socket de Docker, et ce socket vaut les droits de root sur la machine : quiconque peut lancer un conteneur peut y monter le disque système.

**Ce que cela expose.** Une faille dans le processus web suffit à prendre la machine entière. Les protections existantes n’y changent rien : sessions, jeton anti-CSRF, accès réservé aux administrateurs et service lancé sans nouveaux privilèges protègent l’accès à la console, pas ce qu’un attaquant ferait une fois dans son processus.

**Qui on considère.**

| Attaquant | Peut aujourd’hui | Cible |
| --- | --- | --- |
| Visiteur du réseau local, sans compte | Rien sans faille dans la console | Inchangé |
| Compte en lecture seule | Lire ses espaces | Inchangé |
| Administrateur de la console | Piloter les deux services, les partages, les caméras | Inchangé : c’est son rôle |
| Code exécuté dans le processus web (faille, dépendance, paquet malveillant signé à tort) | **Tout, par Docker : root sur l’hôte** | Seulement les opérations de la liste ci-dessous |

**Hors périmètre.** L’administrateur du système, root, et quiconque a un accès physique. Le service de stockage natif a déjà son propre agent root à opérations fermées ; il n’est pas concerné.

## Inventaire : ce que le processus web demande à Docker

Depuis alpha.43, ces dix-neuf opérations sont les seules. Elles vivent dans `console/service_agent.py` ; un essai vérifie qu’aucun autre module de la console ne compose de commande Docker.

| Opération | Commande exécutée | Ce qui varie | Demandée par |
| --- | --- | --- | --- |
| `status` | `compose ps --all --format json` | Un des deux services, ou aucun | Tableau de bord, alertes, installation |
| `video_address` | `compose ps -q video`, puis `docker inspect` | Rien ; seule l’adresse du conteneur est rendue | Accès à Frigate |
| `control` | `compose start`, `stop` ou `restart` | Service : `video` ou `fichiers` | Services, caméras |
| `recreate_files` | `compose up -d --no-deps --force-recreate fichiers` | Rien | Partages |
| `engine` | `docker info`, `docker compose version` | Rien | Accueil, installation |
| `build` | `compose build` | Service | Installation des composants |
| `start_component` | `compose up -d --no-deps --no-build` | Service | Installation des composants |
| `video_validate` | `compose exec video python3 -c …` | La configuration, par l’entrée standard ; le programme est fixe | Caméras, détection |
| `samba_group` | `compose exec fichiers id -g nas` | Rien | Partages |
| `samba_access` | `compose exec --user … fichiers sh -c …` | Compte, groupe, dossier sous `/shares`, lecture ou écriture ; le script est fixe | Partages |
| `samba_identity` | `compose exec fichiers stat -c %d:%i` | Nom d’un espace sous `/shares` | Partages |
| `samba_mounts_check` | `compose config --quiet` | Un fichier candidat du dossier Samba de la console | Partages |
| `samba_config_check` | `compose exec fichiers testparm -s` | Un fichier candidat du dossier Samba de la console | Partages |
| `samba_reload` | `compose exec fichiers smbcontrol all reload-config` | Rien | Partages |
| `samba_close` | `compose exec fichiers smbcontrol all close-share` | Nom d’un partage | Partages |
| `samba_ping` | `compose exec fichiers smbcontrol smbd ping` | Rien | Installation |
| `samba_account` | `compose exec fichiers adduser …` | Nom du compte, numéro | Comptes |
| `samba_password` | `compose exec fichiers smbpasswd -s -a` | Nom du compte ; le mot de passe passe par l’entrée standard | Comptes |
| `samba_enable` | `compose exec fichiers smbpasswd -e` ou `-d` | Nom du compte | Comptes |

Chaque paramètre est validé avant toute commande : service parmi deux, action parmi trois, noms par motif, numéros entiers, chemins sans remontée. Une opération inconnue, un paramètre en trop ou hors motif sont refusés sans rien exécuter.

**Hors processus web.** `lab.py` et `console/system_recovery.py` composent aussi des commandes Docker, pour installer, arrêter ou reprendre une installation. L’administrateur les lance lui-même sur la machine ; ils ne sont pas joignables depuis le navigateur.

## Ce que la liste fermée ne règle pas

La liste borne ce que la console *demande*. Elle ne borne pas ce que le compte de la console *peut* : tant qu’il est dans le groupe `docker`, un attaquant dans le processus web ignore la liste et parle à Docker directement. Trois dépendances restent à couper, et elles structurent les lots suivants :

1. **Le compte.** L’accès à Docker doit quitter le compte de la console pour un agent séparé, qui n’accepte que ces opérations et vérifie qui lui parle.
2. **La description des services.** `compose.yaml` et les sources des images sont dans le dossier de l’installation, que la console peut écrire, puisque les mises à jour par le navigateur y installent le code. Un agent qui exécuterait ces fichiers tels quels rendrait root par un autre chemin : il doit n’accepter qu’une description vérifiée, par exemple contre le manifeste signé de la version installée.
3. **Les montages des partages.** La console écrit le fichier qui dit quels dossiers de l’hôte entrent dans le conteneur de fichiers. L’agent doit le confronter à une liste d’emplacements approuvée par root, comme le fait déjà la politique du stockage natif.

## Cible

Un **agent de services** : un petit daemon, sous un compte dédié qui seul appartient au groupe `docker`. Il écoute sur un socket local réservé au compte de la console, vérifie l’identité de l’appelant, et n’exécute que les opérations de l’inventaire, avec une description des services et des montages qu’il a lui-même vérifiés. Le compte de la console sort du groupe `docker`. Sans agent installé, la console continue comme aujourd’hui et le signale.

## Lots

| Lot | Contenu | Distribution | État |
| --- | --- | --- | --- |
| 1 | Modèle de menace, inventaire, liste fermée d’opérations dans la console | Paquet signé | Livré en alpha.43 |
| 2 | Agent séparé : identité de l’appelant, description des services et montages vérifiés, essais de refus | Paquet signé pour la console ; agent installé par root ; banc VM | À faire |
| 3 | Migration réversible d’une installation existante ; continuité de la vidéo et des partages prouvée | Geste de root sur chaque machine ; banc VM | À faire |

Critères de l’issue : le premier, modèle de menace et inventaire, est rempli. Le deuxième l’est pour le protocole fermé, pas pour le contrôle d’identité, qui vient avec l’agent. Les deux derniers attendent les lots 2 et 3.
