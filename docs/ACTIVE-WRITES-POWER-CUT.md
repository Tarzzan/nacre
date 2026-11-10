# Coupures pendant des écritures et une reconstruction

> **0.7.0-alpha.4 · banc ARM64 QEMU/KVM, données synthétiques uniquement.**
> Cette recette combine les écritures concurrentes et les interruptions brutales qui avaient été qualifiées séparément aux jalons précédents.

## Ce qui est considéré comme confirmé

| Producteur | Confirmation retenue par le banc |
| :--- | :--- |
| HTTP Nacre | Réponse HTTP 200, après `fsync` du fichier, publication sans écrasement puis `fsync` du dossier |
| Local | Écriture temporaire, `fsync` du fichier, renommage puis `fsync` du dossier |
| SMB | Réponse à une requête SMB2 `FLUSH`, avec `strict sync=yes` vérifié sur le serveur |

Chaque fichier porte un nom unique et un contenu déterministe de 64 Kio, associé à une empreinte SHA-256. Les producteurs émettent une intention avant l’écriture et une confirmation seulement après l’opération ci-dessus. Le contrôleur reçoit ces événements via SSH et synchronise son journal **à l’extérieur de la VM**. Le fichier interne d’une VM coupée n’est donc pas utilisé comme preuve de ce qu’elle avait confirmé.

La réponse HTTP de Nacre attend désormais la synchronisation du contenu **et** de son nom. Une erreur avant publication laisse le nom final absent. Une erreur de synchronisation du dossier après publication conserve le fichier complet, sans réponse de succès ; une nouvelle tentative ne l’écrase pas. Ces trois comportements disposent de tests de régression. Les transferts restent traités par blocs, sans plafond applicatif de taille.

Pour SMB, la qualification porte sur un client qui demande explicitement `FLUSH`. Elle ne promet pas la même durabilité pour un client qui confirme seulement une écriture dans ses propres buffers ou ne demande aucune synchronisation. Aucune option globale de ralentissement des écritures Samba n’a été ajoutée au produit.

## Protocole de coupure

Une VM Ubuntu 24.04 ARM64 utilise trois images de 2 Gio, séries `NACRE-V08-A/B/C`. Le miroir Btrfs initial perd le membre B, puis Nacre reconstruit sur C. Le remplacement est limité à 8 Mio/s dans QEMU, uniquement pour laisser une fenêtre de mesure. Les disques de données sont ouverts avec `cache=none` ; aucun périphérique bloc de l’hôte n’est présenté à la VM.

À chacun des trois seuils de progression visés — 12 %, 42 %, 72 % — le contrôleur exige :

1. Une reconstruction active et incomplète, avec le journal de réparation toujours en cours.
2. Au moins cinq confirmations pour chaque producteur, et une confirmation de chacun datant de moins de cinq secondes.
3. Un dépôt HTTP supplémentaire de 2 Mio, dont seule la première moitié est envoyée. Le banc vérifie qu’un fichier temporaire serveur contient effectivement 1 Mio, puis garde la connexion ouverte sans envoyer la suite.

QMP suspend ensuite les vCPU et le contrôleur envoie SIGKILL au processus QEMU dont le nom, le PID et le socket ont été vérifiés. Aucun arrêt propre de Linux ou de ses services n’est demandé. Les confirmations déjà en transit dans le pipe SSH sont également conservées avant de fermer le journal de cette session.

Les mêmes images redémarrent, avec A/C uniquement. Avant de relancer les producteurs, le banc compare **toutes les confirmations cumulées**, leur taille et leur empreinte. Le nom final de chaque dépôt HTTP interrompu doit rester absent ; ses éventuels fragments internes ne doivent être ni listés ni téléchargeables par l’API. Ces fragments sont comptés, pas effacés silencieusement par la recette.

Après la troisième coupure, le plafond de débit du banc est levé. Le contrôle final attend les deux membres synchronisés, vérifie les UUID MD/Btrfs, un témoin aléatoire de 64 Mio, son snapshot antérieur, l’unicité de l’ajout mdadm et le refus de rejouer l’ancien plan.

## Reproduction

Préparer le banc Linux vierge décrit dans [FRESH-LINUX.md](FRESH-LINUX.md), puis installer l’audit mdadm de [POWER-CUT-LAB.md](POWER-CUT-LAB.md). Les chemins et fixtures sont ceux de ces recettes ; ne pas lancer ces scripts sur un NAS réel.

Dans la VM jetable, ajouter un environnement Python réservé au client de test :

```bash
python3 -m venv /home/ubuntu/nacre-fresh-test/venv
/home/ubuntu/nacre-fresh-test/venv/bin/pip install smbprotocol==1.15.0
```

Le script invité est [integration_active_writes_vm.py](../tests/integration_active_writes_vm.py). Le contrôleur [active_writes_qemu_host.py](../tests/active_writes_qemu_host.py) réutilise les phases de vérification de `integration_powercut_vm.py`. Il exige un nom de VM commençant par `nacre-v11-`, un répertoire de laboratoire privé, des images ordinaires, QMP et SSH limité à la boucle locale. Le runtime ARM64 utilisateur doit se trouver dans `runtime/root` sous ce répertoire, comme au banc précédent.

```bash
NACRE_VM_LAB_HOST=1 python3 tests/active_writes_qemu_host.py \
  --command /banc/prive/commande-qemu.json \
  --key /banc/prive/cle-ssh-test \
  --known-hosts /banc/prive/known_hosts \
  --port 2255 \
  --result /banc/prive/resultat.json
```

Le contrôleur accepte `--resume` uniquement après une coupure déjà vérifiée, invité revenu, sans événements de producteurs pour la session suivante. Il relit alors le journal externe et les contrôles précédents, sans rejouer l’ajout du disque. Ce mode a servi à reprendre le banc après correction d’une attente de démarrage Samba dans le client de test.

Les résultats synthétiques sont collectés avant arrêt de la VM et retrait des images, de la clé temporaire sur l’hôte et des fixtures. Les paquets du client SMB sont installés exclusivement dans la VM. Le banc n’utilise aucune caméra et ne redémarre aucun service de production.

## Résultats mesurés

Les trois coupures surviennent à **12,51 %, 43,77 % et 75,04 %**. Les **376 fichiers confirmés** totalisent **23,5 Mio** : 101 locaux, 96 HTTP et 179 SMB. Aucun fichier confirmé n’est absent ou corrompu après les reprises et la fin de reconstruction.

Les trois noms finaux HTTP incomplets sont absents. Trois fragments internes subsistent au dernier contrôle, non listés et non téléchargeables ; leur récupération d’espace automatique reste à concevoir. Le témoin de 64 Mio et son snapshot sont intacts, les UUID sont conservés et les deux membres sont synchronisés. L’audit compte un seul ajout et aucun ajout rejoué ; le noyau a repris cette reconstruction sans demande supplémentaire `--readwrite`.

## Interprétation

Les nombres de fichiers, octets et progressions **mesurés** figurent dans la section `active_writes_powercut_0_7_alpha4` de [VALIDATION.json](../VALIDATION.json). Le rapport distingue les confirmations de chaque session et les contrôles cumulés après chaque coupure.

Cette expérience détruit brutalement la VM et son noyau, mais laisse l’hôte QEMU sous tension. Elle ne simule pas la perte du cache physique d’un disque ou d’un contrôleur. Elle ne qualifie pas l’endurance, une panne multiple, tous les clients SMB ni toutes les combinaisons de systèmes de fichiers. Les essais de ce jalon portent sur ARM64 et Btrfs RAID1 ; la CI ordinaire couvre aussi x86-64, sans injection de coupure.

Références : [synchronisation Samba](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html), [client SMB2/3 amont](https://github.com/jborean93/smbprotocol), [fsync sous Linux](https://man7.org/linux/man-pages/man2/fsync.2.html), [états RAID MD](https://docs.kernel.org/admin-guide/md.html).
