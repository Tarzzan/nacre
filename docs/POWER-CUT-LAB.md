# Coupure pendant reconstruction et reprise ARM64

## Le défaut détecté et sa correction

Après un arrêt brutal pendant l’ajout d’un membre RAID1, Linux peut réassembler le miroir en `read-auto`. Les données sont montables, mais la reconstruction attend une écriture. Une console qui n’effectue que des lectures peut donc laisser cette reconstruction suspendue.

Nacre 0.7.0-alpha.2 vérifie au démarrage le journal de l’opération déjà autorisée, la politique, le montage, les UUID et les deux membres catalogués. Si l’ensemble est précisément en `read-auto`, dégradé d’un membre, sans synchronisation active, avec un membre `in_sync` et le remplaçant `spare`, le helper demande `mdadm --readwrite` sur cet ensemble. Les descripteurs et identités sont vérifiés avant cette demande, qui est comptée dans le catalogue.

Cette reprise exige `mount_on_start: true`. Elle ne lance aucun nouvel ajout, formatage ou assemblage forcé. Un état MD explicitement `readonly`, un membre manquant/inattendu, un catalogue incertain ou un journal incomplet n’autorise pas cette reprise. Une reconstruction déjà active continue sous le contrôle du noyau. L’état ne devient terminé qu’après vérification des deux membres synchronisés.

## Ce que le banc mesure

Le contrôleur attend une reconstruction active, avec un nombre de secteurs complétés strictement inférieur au total et un journal encore « en cours ». Il vise successivement 10 %, 40 % et 70 % ; les valeurs réellement observées sont consignées, sans supposer que la progression correspond exactement aux seuils.

À chaque seuil, QMP suspend les vCPU puis le contrôleur envoie **SIGKILL au processus QEMU identifié**. Il n’envoie ni arrêt de Linux ni arrêt propre des services. Les mêmes images sont ensuite rouvertes. Le disque retiré B reste conservé hors de la VM ; seul le survivant A et le remplaçant C reviennent. Les identifiants de démarrage permettent de distinguer les trois sessions interrompues.

Le disque C est limité à 16 Mio/s par QEMU pour laisser une fenêtre mesurable, y compris avant le démarrage des services de l’invité. Après la troisième coupure, le plafond est levé et le contrôleur attend la fin réelle. Cette limite appartient exclusivement au **banc**, pas au produit.

Contrôles finaux : UUID MD et Btrfs inchangés, membres A/C synchronisés, empreinte SHA-256 d’un fichier aléatoire de 64 Mio intacte, clone du snapshot antérieur identique, ancien plan refusé, une seule action de reconstruction. Une enveloppe d’audit réservée à la VM journalise les appels au binaire mdadm installé et les transmet sans changer leurs arguments : un seul `--add`, aucun `--create`/`--force` dans ces appels après injection, et les éventuelles reprises `--readwrite`. Cette instrumentation ne couvre pas le binaire embarqué dans l’initramfs.

**Portée de la preuve :** perte brutale d’une VM et de son noyau, disques virtuels de données ouverts avec `cache=none`. Le PC hébergeant les images reste alimenté. Le banc ne simule donc pas la perte du cache d’un contrôleur physique, les défauts électriques d’un disque, toutes les écritures applicatives concurrentes ou l’endurance sur de grands volumes.

## Rejouer en environnement isolé

Commencer par [VM-LAB.txt](../tests/VM-LAB.txt) et le scénario Linux vierge. Utiliser une VM exclusivement jetable avec trois images A/B/C, séries `NACRE-V08-A/B/C`, aucun périphérique bloc hôte, partage de dossiers ou socket Docker hôte. Prévoir au moins 8 Gio libres pour un banc local actif, plus les autres images conservées. Exporter les résultats avant le nettoyage.

Le lancement QEMU doit être consigné dans un tableau JSON de ses arguments, avec un nom commençant par `nacre-v09-`, un fichier PID et un socket QMP dans le répertoire du banc. Tous ses disques inscriptibles doivent être des fichiers ordinaires dans ce même répertoire. Le contrôleur refuse d’autres types de périphériques et vérifie le nom, le PID et le socket avant de tuer un processus. SSH écoute uniquement sur `127.0.0.1` ; sa clé est une clé de test séparée.

Après `integration_fresh_linux_vm.py`, copier les deux nouveaux scripts dans leurs environnements respectifs. Dans l’invité uniquement :

```bash
sudo env NACRE_VM_LAB=1 python3 /home/ubuntu/nacre-code/tests/integration_powercut_vm.py install-audit
```

Sur l’hôte du laboratoire, avec les chemins et le port de **ce banc** :

```bash
NACRE_VM_LAB_HOST=1 python3 tests/powercut_qemu_host.py \
  --command /banc/prive/commande-qemu.json \
  --key /banc/prive/cle-ssh-test \
  --known-hosts /banc/prive/known_hosts \
  --port 2297 \
  --result /banc/prive/coupures.json
```

Le contrôleur peut attendre la libération des verrous QEMU après SIGKILL. `--resume` reprend un contrôleur interrompu après une coupure déjà consignée ; il ne relance pas le plan Nacre. Ne pas l’utiliser sur une VM encore active. Une erreur de contrôle n’est jamais comptée comme une validation réussie.

Après réussite, exécuter dans l’invité `integration_fresh_linux_vm.py --after-reboot` pour vérifier console, montage et Samba. Arrêter la VM, fermer ses tunnels et retirer les images temporaires après collecte. Aucun test privilégié n’est exécuté par la CI ordinaire.

## Reprise ARM64 sans dépendance à la source

Deux VM ARM64 sont démarrées successivement depuis l’image officielle Ubuntu Minimal 24.04, sur KVM ARM64. La source crée des données synthétiques, des comptes, une archive historique et une sauvegarde chiffrée. Le scénario vérifie aussi SID Samba, compte désactivé, lecture seule, écritures autorisées et recréation du conteneur. Il exporte les attentes non secrètes dans `expectations.json`.

La source est arrêtée avant le démarrage de la cible. La cible ne reçoit que le code approuvé, la sauvegarde, sa clé de test externe et les archives historiques. Elle commence sans image/volume Docker ni catalogue natif. Le parcours retrouve les clés, le mot de passe web, les comptes Samba et leur SID, les propriétaires, les données externes et les fixtures Frigate, puis alimente un miroir Btrfs neuf. Les plans restent désactivés. Le banc de coupures est ensuite appliqué à cette cible.

Dans l’essai de développement, QEMU et ses dépendances Ubuntu ont été extraits dans un dossier utilisateur séparé sur l’hôte ARM64, sans installation de paquet système. Chaque VM utilise deux vCPU et 3 Gio de RAM, une seule à la fois. Aucun accès au Docker, aux périphériques de stockage ni aux dossiers de la console réelle n’est transmis à la VM.

Cette preuve concerne une reprise **ARM64 vers ARM64 avec mêmes UID/GID principaux**. Elle ne qualifie ni la migration x86→ARM, ni le démarrage réel de Frigate avec une caméra, ni les accélérateurs GPU, ACL/xattrs, RAID ext4 ou boîtiers NAS propriétaires.

Références : [états MD et progression dans le noyau Linux](https://cdn.kernel.org/doc/html/latest/admin-guide/md.html), [plateforme virtuelle ARM de QEMU](https://www.qemu.org/docs/master/system/arm/virt.html), [images officielles Ubuntu Minimal](https://cloud-images.ubuntu.com/minimal/releases/noble/release/). Résultats mesurés dans [VALIDATION.json](../VALIDATION.json).
