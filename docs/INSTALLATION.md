# Installation et exploitation

## Préparer l’hôte

Linux x86-64 ou ARM64, Python 3.11+ et util-linux. Docker Engine et le plugin Compose (`docker compose`, v2 ou supérieur) sont requis pour Samba et Frigate, mais pas pour ouvrir la console et son assistant. Le compte dédié doit pouvoir exécuter Docker ; ce droit équivaut à un accès privilégié à l’hôte. Le service utilisateur demande systemd. SMART nécessite smartmontools et des permissions adaptées au périphérique.

Les images Docker et le runtime restic sont référencés dans le code. L’installation initiale nécessite Internet pour les récupérer. Aucune dépendance Python tierce n’est nécessaire à la suite de tests standard.

## Installer la console

Depuis le dépôt cloné :

```bash
python3 installer.py
```

`installer.py` prépare les fichiers privés, conserve la configuration existante et lance la console au premier plan. Dans un second terminal, `python3 lab.py acces` affiche les accès provisoires. Le premier administrateur choisit son mot de passe dans le navigateur. `--prepare-only` prépare les fichiers sans lancer le serveur. Voir le [parcours illustré](FIRST-RUN.md).

Dans **Services**, installer restic puis Samba et Frigate selon les besoins. Docker et Compose doivent d’abord être installés sur Linux et accessibles au compte dédié. Voir le [parcours web](COMPONENTS-CAMERAS.md) et la [recette complète sur Linux neuf](FRESH-WEB-INSTALL.md). Les commandes suivantes restent disponibles comme alternative :

```bash
python3 console/install_restic.py  # moteur de sauvegarde
python3 lab.py start              # services fichiers et vidéo
# Arrêter la console au premier plan avant de passer au service persistant.
python3 console/install_service.py
```

Le runtime restic est vérifié par SHA-256. L’installateur de service vérifie l’unité systemd utilisateur. Pour un démarrage sans session ouverte, l’administrateur de l’hôte doit configurer le maintien des services utilisateur (`loginctl enable-linger COMPTE`) conformément à sa politique.

## Accéder et configurer

- Console : `http://127.0.0.1:8766/`.
- Frigate : port local 8971 ; ses identifiants sont distincts de ceux de Nacre.
- SMB de laboratoire : port local 1445. Un déploiement réseau classique nécessite une configuration réseau dédiée ; il n’est pas exposé automatiquement au LAN.
- `python3 lab.py acces` : affiche les accès uniquement dans le terminal ; ne pas copier la sortie dans une issue.
- `python3 lab.py web` : produit un lien local à usage unique de courte durée ; ce lien est un secret.

Exemple de tunnel, en remplaçant l’hôte SSH :

```bash
ssh -N -L 8766:127.0.0.1:8766 votre-serveur
```

L’interface permet la gestion des partages, des plans et des réglages d’une caméra configurée. Pour ajouter une caméra, créer son compte local dans l’application constructeur puis utiliser **Surveillance → Ajouter une caméra**. La commande `python3 lab.py camera --ip ADRESSE_LOCALE` reste une alternative pour la caméra historique `tapo`. Les plans sont désactivés par défaut. Choisir une destination distincte des données pour se protéger d’une panne de leur support et conserver la clé de récupération hors du serveur.

## Activer les fonctions natives

Lire la section native du [guide détaillé](../LIRE-MOI.txt). Le service root est optionnel : générer d’abord son installation avec `console/install_native.py --stage`, puis faire revoir la politique par l’administrateur. Une politique vide n’autorise aucune initialisation. Les exemples ne doivent jamais être copiés avec des identités de disques approximatives.

Le provisionnement actuel utilise des disques entiers explicitement autorisés. La présence d’une confirmation ne rend pas une mauvaise sélection de disque réversible. Les bancs `integration_*_vm.py` sont strictement réservés à leurs VM de test.

## Données persistantes

Conserver `.env`, `state/`, `data/` et les volumes Docker nécessaires. Ils sont exclus de Git. Les dépôts chiffrés, leurs clés, les bases de comptes et les données vidéo ont des besoins de sauvegarde différents. Les snapshots ordinaires de configuration ne sauvegardent pas tout le passdb Samba. La [reprise hors ligne d’installation](SYSTEM-RECOVERY.md) inclut cet état et les clés ; elle ne constitue pas une image système.

## Mettre à jour

1. Lire le changelog et identifier les migrations.
2. Sauvegarder hors du répertoire de travail la configuration, les bases, les clés et les données nécessaires ; vérifier leur récupération.
3. Valider la version candidate sur une copie de laboratoire.
4. La version alpha.5 fait évoluer la base de 1 vers 2 avec copie préalable privée ; les comptes existants sont conservés et l’assistant n’est pas imposé. Le retour à un binaire de schéma 1 exige une reprise hors ligne de sa copie, pas une rétrogradation directe.
5. Mettre à jour le code vers un commit/tag identifié, puis redémarrer `nacre-console.service` avec `systemctl --user restart nacre-console.service`.
6. Vérifier l’accès, les tâches, les services et les chemins de données.

Un retour à l’ancien code ne garantit pas un retour arrière d’une migration de base. Les mises à jour du helper root demandent une installation et un redémarrage explicites. Un installateur transactionnel avec retour arrière reste à développer.

## Diagnostic

```bash
systemctl --user status nacre-console.service
journalctl --user -u nacre-console.service --since today
python3 lab.py status
```

`python3 verifier.py` vérifie Frigate et effectue un cycle SMB avec un fichier témoin temporaire. Ce n’est pas un test purement en lecture. Avant de partager un journal, retirer identifiants, adresses privées, chemins personnels et liens d’accès.
