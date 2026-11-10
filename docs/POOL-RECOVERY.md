# Reconstruire un miroir RAID1

> **0.7.0-alpha.1 · miroir créé et catalogué par Nacre, deux membres, métadonnées mdadm 1.2.**
> La qualification réelle porte sur Btrfs dans QEMU x86-64. Ce parcours conserve le système de fichiers et ses snapshots ; il recopie le membre sain vers un disque de remplacement.

## Conditions avant ouverture du plan

Le volume doit être monté avec son UUID attendu, dégradé d’un seul membre et sans synchronisation en cours. Le membre défaillant doit déjà avoir quitté l’ensemble MD. Nacre ne le marque pas en panne et ne le retire pas automatiquement : cette intervention relève du diagnostic matériel de l’administrateur.

Le seul membre présent doit être le survivant identifié dans le catalogue. Le remplacement doit être distinct, vierge, sans partition, signature, montage ni détenteur, de capacité au moins égale au membre absent et explicitement autorisé par la politique root (chemin persistant, série, capacité, initialisation autorisée). Conserver l’autorisation du membre précédent jusqu’à la préparation ; son identité est encore nécessaire au contrôle du catalogue. Garder physiquement le disque retiré hors service après remplacement.

Conserver une sauvegarde indépendante avant intervention. Un miroir protège contre certaines pannes de disque, pas contre une suppression ou une corruption logique. Ne pas lancer d’autres commandes mdadm concurrentes pendant ce parcours.

## Depuis le navigateur

1. Ouvrir **Stockage natif**, actualiser et repérer le volume dégradé dans **Volumes créés par Nacre**.
2. Choisir **Reconstruire…**, sélectionner le membre absent et le nouveau disque. La préparation contrôle les identités sans ajouter de membre.
3. Relire la série et les effets, puis recopier la confirmation `RECONSTRUIRE <volume> AVEC <disque>`. Le plan est lié à l’opérateur, valable deux minutes et utilisable une seule fois.
4. Actualiser pour suivre la synchronisation. « Commande acceptée » signifie que le noyau poursuit le travail ; l’action n’est terminée que lorsque les deux membres attendus sont synchronisés et le miroir non dégradé.
5. Vérifier fichiers témoins, accès, snapshot et redémarrage. Conserver l’ancien support sans l’effacer jusqu’à clôture de l’intervention.

Les identités, la politique, le catalogue et l’état MD sont revérifiés à l’exécution. Le journal est enregistré avant l’ajout. Le nouveau disque est ouvert et verrouillé ; le service garde aussi ouverts les périphériques du survivant et du miroir pendant la commande. Ces contrôles ne constituent pas une exclusion des autres administrateurs root.

## Après une interruption

Un redémarrage du service ne rejoue pas l’ajout du disque. Le noyau poursuit une reconstruction déjà engagée ; Nacre vérifie l’état physique avant de marquer l’action terminée. Un résultat de commande ambigu produit **À vérifier**.

Après diagnostic, **Vérifier la reconstruction** peut remettre le catalogue en état disponible uniquement si le volume et les deux membres attendus sont déjà synchronisés. Ce plan exige une confirmation `VALIDER <volume>` et ne lance aucune commande d’ajout, de formatage ou d’assemblage. S’ils ne sont pas synchronisés, le refus est conservé : ne pas modifier la base SQLite pour contourner le contrôle.

Le remontage au démarrage exige `mount_on_start: true` dans la politique. Il utilise les identités et UUID catalogués, sans assemblage forcé ni formatage. Un échec doit être diagnostiqué avant de rouvrir les partages.

## Périmètre qualifié

Le banc injecte la perte d’un membre sur trois images de disques synthétiques, remplace B par C, redémarre le service, attend la synchronisation et contrôle les empreintes. Il restitue aussi un snapshot Btrfs créé avant la panne, puis redémarre Linux et revérifie pool, console et Samba. L’ancien membre conserve sa signature RAID ; aucune commande d’effacement n’est exécutée.

Ne sont pas qualifiés : perte électrique au milieu de la reconstruction, import d’un RAID étranger ou totalement absent, reconstruction ARM64 sur matériel, réparation ZFS/LVM/RAID5/RAID6, changements de géométrie, hotplug matériel et endurance. Le mécanisme ne reformate pas le système de fichiers ; le scénario de reconstruction avec ext4 reste à qualifier séparément.

Pour repartir d’une sauvegarde sur de nouveaux disques, suivre [FRESH-LINUX.md](FRESH-LINUX.md). Les anciens snapshots d’un pool perdu ne renaissent pas à partir d’une simple copie de fichiers.

Références techniques : [noyau Linux — état et synchronisation MD](https://cdn.kernel.org/doc/html/latest/admin-guide/md.html), [manuel amont mdadm](https://kernel.googlesource.com/pub/scm/utils/mdadm/mdadm/+/69818a5c75ba5982e9d866f94239a2f5975f988e/mdadm.8.in).
