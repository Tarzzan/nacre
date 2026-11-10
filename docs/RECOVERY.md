# Reprise de la base de console

Pour les données, clés et comptes Samba, suivre désormais la [reprise d’installation](SYSTEM-RECOVERY.md).

Cette première étape du jalon 0.6 protège **la base SQLite de Nacre** lors d’une évolution de son schéma. Elle ne reconstitue pas à elle seule un NAS après la perte de son disque.

## Au démarrage

1. La console lit la version de schéma (`PRAGMA user_version`). La première version explicite est 1 ; les installations 0.5 utilisent implicitement 0.
2. Une base plus récente que le code est refusée avant toute migration. Cette protection concerne les versions de code qui l’implémentent ; revenir au code 0.5 ne fournit pas cette garantie.
3. Un verrou de processus sérialise les migrations ; SQLite bloque les écritures concurrentes pendant leur application.
4. Si une base existante doit évoluer, SQLite crée une copie cohérente, transactions WAL validées incluses. Un contrôle d’intégrité, une empreinte SHA-256 et une synchronisation disque précèdent la migration.
5. Les changements de structure et la nouvelle version sont validés dans une même transaction. Une exception ou un arrêt brutal du processus ne valide pas un schéma à moitié modifié.

Les copies résident dans `state/console/migration-backups/`, répertoire 0700, avec fichiers 0600. Elles contiennent notamment des empreintes de mots de passe et des métadonnées privées. Elles ne sont pas chiffrées séparément et ne sont pas servies en téléchargement HTTP. Aucune purge automatique n’est ajoutée. Le manque d’espace ou l’échec de la copie empêchent la migration.

Cette atomicité concerne SQLite. Elle ne promet pas la récupération de toute panne du support, d’un contrôleur défectueux, de fichiers de configuration externes ou d’une opération Docker/native en cours.

## Examiner et préparer une copie

L’interface **Snapshots → Reprise de la console** affiche la version et les copies disponibles aux administrateurs. Le contrôle des empreintes se fait lors de la préparation, pas à chaque rafraîchissement de l’écran.

Sur le serveur, depuis le répertoire du code :

```bash
python3 console/recover_database.py list --database state/console/console.db
```

Créer un dossier privé de travail, puis sélectionner le nom exact obtenu dans la liste :

```bash
mkdir -m 700 reprise-privee
python3 console/recover_database.py prepare \
  --source state/console/migration-backups/schema-v0-IDENTIFIANT.sqlite3 \
  --output reprise-privee/console-recuperee.sqlite3
```

L’outil exige le fichier `.json` associé, vérifie l’empreinte et l’intégrité, puis crée un **nouveau fichier** sans remplacer un fichier existant. Il conserve les comptes et leurs mots de passe hachés, supprime les sessions et tickets, désactive les plans et marque les tâches en attente/en cours comme interrompues. Il exige au moins un administrateur actif. Une empreinte détecte une altération accidentelle ; elle ne remplace pas une signature indépendante si un attaquant peut modifier à la fois la copie et son manifest.

## Répéter la reprise dans une installation isolée

Dans une nouvelle racine de laboratoire, créer `state/console/` en 0700 et y préparer la copie directement sous le nom `console.db`. Démarrer le code avec `NAS_ROOT` pointant sur cette racine et un port local distinct (`NAS_PORT`). La console migre cette copie si nécessaire et conserve les comptes existants. Tester la connexion et la lecture du journal avant de considérer la base comme exploitable.

Le scénario `tests/integration_migrations_vm.py` rejoue exactement ce parcours dans QEMU : nouveau répertoire d’installation, compte administrateur conservé, connexion HTTP avec son ancien mot de passe et lecture d’un témoin d’audit. Il ne restaure pas les services SMB, la vidéo ou les volumes et ne doit jamais être présenté comme une reprise complète de l’hôte.

## Remise en service d’une installation réelle

L’outil ne remplace pas la base active. Une intervention d’administrateur reste nécessaire : arrêter la console **et ses workers** qui accèdent à SQLite, préserver l’ensemble original (base et éventuels fichiers WAL/SHM), préparer la copie hors de cet ensemble, contrôler la correspondance des configurations et clés, puis organiser une remise en service contrôlée. Ne pas échanger un fichier `.db` sous un processus actif ni ignorer ses fichiers WAL/SHM. Les tâches natives indépendantes demandent également un examen de leur état.

Une base restaurée contient des références à des chemins, corbeilles, dépôts et volumes de l’époque de sa capture. Ces références ne prouvent pas que les objets existent encore. Vérifier ces correspondances avant toute réactivation. Les anciens codes qui ne connaissent pas la version de schéma ne doivent pas servir à contourner un refus de démarrage.

## Inventaire des dépendances de reprise

| Ressource | Emplacement habituel | Copie de migration SQLite | Action nécessaire pour une reprise complète |
| --- | --- | --- | --- |
| Comptes web, sessions, journal, plans, catalogue de dépôts, profils | `state/console/console.db` | Oui ; sessions révoquées et plans désactivés à la préparation | Vérifier les références après récupération |
| Clés de dépôts restic | `state/console/keys/` et copie de récupération externe | **Non** | Conserver séparément, accès privé ; sans clé, dépôt inexploitable |
| Configuration SMB et catalogue d’utilisateurs | `state/console/smb.json`, `state/samba/` | **Non** | Sauvegarde cohérente avec le service |
| Mots de passe et identité Samba | Secret `state/smb_password`, volume Docker `samba-state` | **Non** | [Capture hors ligne et import dans un volume distinct](SYSTEM-RECOVERY.md) |
| Configuration et base Frigate | `state/frigate/` | **Non** | Capture séparée et cohérente, clés/accès caméra protégés |
| Données, vidéos, corbeilles et restaurations | `data/`, volumes gérés | **Non** | Sauvegardes de données sur support distinct et essais de restitution |
| Dépôts chiffrés restic | Destination choisie et sous-répertoire `.nacre-repos` | Références seulement | Conserver le dépôt et sa clé, vérifier son montage |
| Profil de déploiement | `.env`, unités systemd | **Non** | Reconstituer selon la machine cible ; ne pas appliquer aveuglément les anciens UID/chemins |
| Politique et catalogue natifs | `/etc/nacre-storage/policy.json`, `/var/lib/nacre-storage/catalog.db` | **Non** | Requalifier les identités matérielles ; jamais réinitialiser pour « retrouver » un volume |

La capture de configuration restic existante copie certains fichiers de configuration et les bases SQLite, mais elle ne constitue toujours pas cet ensemble complet. La fermeture de l’issue #1 dépend notamment de cette couverture, des clés et de la reprise des comptes SMB.
