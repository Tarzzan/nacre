# Réduire les privilèges de la console sur Docker

Ce document répond à l’[issue 2](https://github.com/Tarzzan/nacre/issues/2). Il dit ce que la console peut faire par Docker, ce que cela expose, ce qui est fait et ce qui reste. Trois lots sont livrés : la liste fermée des opérations (0.8.0-alpha.43), l’agent de services qui la tient à la place de la console (alpha.44), et la protection des dossiers où les conteneurs écrivent (alpha.45). **Rien de cela ne s’applique tout seul** : chaque machine attend trois gestes de son administrateur, et aucune installation en service ne les a encore reçus.

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

Ces vingt opérations sont les seules. Elles vivent dans `console/service_agent.py` ; un essai vérifie qu’aucun autre module de la console ne compose de commande Docker.

| Opération | Commande exécutée | Ce qui varie | Demandée par |
| --- | --- | --- | --- |
| `status` | `compose ps --all --format json` | Un des deux services, ou aucun | Tableau de bord, alertes, installation |
| `video_address` | `compose ps -q video`, puis `docker inspect` | Rien ; seule l’adresse du conteneur est rendue | Accès à Frigate |
| `control` | `compose start`, `stop` ou `restart` | Service : `video` ou `fichiers` | Services, caméras |
| `recreate_files` | `compose up -d --no-deps --force-recreate fichiers` | Rien | Partages |
| `engine` | `docker info`, `docker compose version` | Rien | Accueil, installation |
| `protection` | Aucune : lit les options de montage des dossiers où les conteneurs écrivent | Rien | Accueil |
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

## L’agent de services

Un daemon root, sur le modèle du service de stockage natif. Il écoute sur un socket local réservé au compte de la console, vérifie l’identité de l’appelant à chaque demande, et n’exécute que les opérations de l’inventaire. Quand son socket existe, la console lui envoie tout ; sinon elle continue comme avant et pilote Docker elle-même.

**Ce que l’agent ne croit pas.** Le compte de la console peut écrire dans le dossier de l’installation, puisque les mises à jour par le navigateur y posent le code. L’agent ne se fie donc à rien de ce qui s’y trouve pour décider des droits d’un conteneur :

| Entrée | Écrite par | Ce que fait l’agent |
| --- | --- | --- |
| Description des services (`compose.yaml`) | La console, à chaque mise à jour | Il utilise **sa propre copie**, posée par root à l’installation. Celle de l’installation est ignorée. |
| Sources des images (`samba/`, `frigate/`) | La console, à chaque mise à jour | Sa propre copie aussi : la description de l’agent y renvoie. |
| Variables (`.env`) | La console | Il n’en retient que trois, validées une à une : image Frigate, numéros de compte et de groupe. Le reste est ignoré. Si la politique fixe l’image Frigate (`frigate_image`), c’est elle qui sert. |
| Montages des partages | La console | Chaque dossier doit se trouver, liens résolus, **dans un emplacement approuvé par root** dans la politique. Forme stricte ; au moindre écart, l’opération entière est refusée. |
| État d’une installation reprise | L’outil de reprise | Relu dans sa forme exacte : image par empreinte, nom de machine, volume externe. |
| Nom du projet | — | Fixé par la description de l’agent, ou par le nom d’une reprise au format attendu. |

Les fichiers vérifiés sont réécrits dans le dossier de l’agent, que la console ne peut pas modifier, et ce sont ces copies que Docker reçoit.

### Les dossiers où les conteneurs écrivent

Les deux conteneurs tournent en root à l’intérieur, et écrivent dans des dossiers de l’hôte : les fichiers partagés, les enregistrements, la configuration de Frigate. Qui tient le compte de la console peut agir sur ce qu’ils exécutent, ne serait-ce que par la configuration de Frigate, qu’il écrit par conception. Sans précaution, il peut alors leur faire déposer dans un dossier partagé un programme marqué pour s’exécuter en root, ou un fichier de périphérique ouvrant le disque système, puis s’en servir depuis l’hôte. Ce chemin a été démontré sur le banc avant d’être fermé.

La parade est sur l’hôte : remonter ces dossiers sur eux-mêmes avec les options `nosuid` et `nodev`. Ce que les conteneurs y déposent ne confère alors plus aucun droit. Rien n’est redémarré, et les conteneurs en marche continuent de servir.

- `install_services.py --protect` prépare les deux montages, pour `data` et `state` ; root les active.
- L’agent **constate** la protection de chaque dossier concerné, et l’accueil le dit.
- Avec `"require_protected_mounts": true` dans la politique, l’agent **refuse de démarrer ou de recréer** un service tant qu’un dossier où il écrit est exposé, partages approuvés compris. Lire l’état et arrêter restent possibles.

Les volumes créés par Nacre sont déjà montés ainsi.

### Installer l’agent

Les gestes de l’administrateur du système, sur chaque machine. **Les faire depuis un code de confiance** : au moment de l’installation, root copie la description des services et les sources des images depuis le dossier de l’installation, et s’y fie donc une fois.

1. **Poser l’agent et préparer la protection des dossiers** :
   `sudo python3 console/install_services.py --install --protect --uid UID_CONSOLE`
   Cela écrit le code de l’agent, sa copie de la description des services et des sources des images, son unité systemd, deux unités de montage, et, si elle n’existe pas, une politique `/etc/nacre-services/policy.json` sans emplacement approuvé. Aucun conteneur, compte ni groupe n’est touché, et rien n’est encore monté.
2. **Protéger les dossiers de données** : activer les deux unités de montage que la commande a nommées, par `sudo systemctl enable --now` suivi de leurs noms.
3. **Régler la politique**, relue à chaque demande :
   - `mount_roots` : dossiers parents des partages natifs, s’il y en a. Sans emplacement approuvé, aucun dossier supplémentaire n’entre dans le conteneur de fichiers.
   - `require_protected_mounts` : `true` pour que l’agent refuse de démarrer un service sur un dossier exposé.
   - `frigate_image` : facultatif, pour fixer l’image Frigate.
4. **Démarrer l’agent** : `sudo systemctl enable --now nacre-services`. La console passe par lui dès que son socket existe.

À ce stade le compte de la console a encore son accès direct, et l’accueil le dit. Le lui retirer, `sudo gpasswd -d COMPTE docker` puis redémarrage de la console, fait partie de la migration du lot 4 : elle n’est pas encore qualifiée sur une installation en service.

**Revenir en arrière** : `sudo systemctl disable --now nacre-services`, remettre le compte dans le groupe s’il en était sorti, et désactiver les unités de montage si on le souhaite. La console reprend la main sur Docker.

**Après une mise à jour qui change la description des services ou les sources des images**, rejouer le premier geste : tant que root ne l’a pas fait, l’agent garde les anciennes.

### Prouvé sur banc VM

`tests/integration_service_agent_vm.py`, dans une VM jetable avec un vrai Docker et le service de fichiers :

- avant l’agent, la console pilote Docker elle-même ; après, **le compte de la console est sorti du groupe `docker`** et ne peut plus lui parler ;
- seize opérations rejouées par l’agent : état, comptes et mots de passe Samba, contrôles, redémarrage, arrêt, démarrage ;
- **le conteneur n’est pas recréé** par le passage à l’agent : même identifiant avant et après ;
- root refusé par l’agent, comme tout autre compte que celui de la console ; huit demandes hors liste refusées ;
- description des services trafiquée par le compte de la console (`privileged`, espace de processus de l’hôte) et variables piégées : le conteneur recréé par l’agent n’en porte aucune trace ;
- sept montages refusés (racine, `/etc`, dossier personnel, lien qui s’évade, remontée de chemin, emplacement non approuvé) et un montage approuvé, vérifié dans le conteneur ;
- agent arrêté : la console n’a plus aucun accès et le dit comme une indisponibilité ; agent relancé : elle reprend ;
- **le chemin par les conteneurs, démontré puis fermé** : avant protection, le compte de la console obtient les droits de root par un programme que le conteneur a marqué dans le dossier partagé, et lit le disque système par un fichier de périphérique ; après activation des deux montages, ni l’un ni l’autre, sans redémarrer le conteneur, y compris pour ce qu’il dépose ensuite ;
- protection exigée par la politique : un partage approuvé mais posé sur un dossier exposé n’est plus monté ;
- source d’image trafiquée par le compte de la console : l’image reconstruite par l’agent n’en porte aucune trace.

## Ce qui reste ouvert

- **Aucune installation en service n’est migrée.** Les gestes ci-dessus sont prouvés sur une installation d’essai avec le service de fichiers. Sortir le compte de la console du groupe `docker` sur une machine qui sert, avec la vidéo, et pouvoir revenir en arrière sans coupure, c’est le lot 4.
- **La vidéo n’a pas été exercée par l’agent sur un vrai Docker** : l’image Frigate est trop lourde pour le banc. Ses opérations sont les mêmes commandes, essayées face à un Docker simulé.
- **Les conteneurs tournent toujours en root à l’intérieur.** Protégés par `nosuid` et `nodev`, leurs dossiers ne donnent plus de droits sur l’hôte ; une faille du noyau ou de Docker lui-même reste hors de portée de ce plan.
- **Le contenu de l’image Frigate de base** n’est approuvé que si root la fixe dans la politique.
- **Un partage natif posé sur un dossier exposé** n’est refusé que si la politique l’exige.
- Une mise à jour de la description des services ou des sources des images ne prend effet qu’après un geste de root.
- Sur une installation reprise, l’agent relit l’état de reprise ; ce cas n’est essayé que face à un Docker simulé.

## Lots

| Lot | Contenu | Distribution | État |
| --- | --- | --- | --- |
| 1 | Modèle de menace, inventaire, liste fermée d’opérations dans la console | Paquet signé | Livré en alpha.43 |
| 2 | Agent séparé : identité de l’appelant, description des services et montages vérifiés, essais de refus | Paquet signé pour la console ; agent installé par root ; banc VM | Livré en alpha.44 |
| 3 | Conteneurs sans pouvoir sur l’hôte : dossiers de données sans programmes privilégiés ni périphériques, sources des images tenues par root | Paquet signé pour la console ; montages activés par root ; banc VM | Livré en alpha.45 |
| 4 | Migration réversible d’une installation existante ; continuité de la vidéo et des partages prouvée | Geste de root sur chaque machine ; banc VM | À faire |

Critères de l’issue : modèle de menace et inventaire, remplis ; contrôle d’identité et protocole fermé, remplis ; essais de refus, remplis en VM pour les partages, la continuité de la vidéo restant à prouver ; migration réversible, à faire au lot 4.
