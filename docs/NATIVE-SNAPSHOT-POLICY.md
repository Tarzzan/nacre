# Conservation et programmation des points natifs

Ce document répond à l’[issue 4](https://github.com/Tarzzan/nacre/issues/4) : il dit ce qui existe, ce que chaque lot apporte, et les règles que les lots suivants devront respecter. Les deux premiers lots sont livrés, en 0.8.0-alpha.39 et 0.8.0-alpha.40. Pour le troisième, l’action du service natif est codée et prouvée sur banc VM, sans être distribuée. Le quatrième est spécifié et n’est pas codé.

## Point de départ

Le service natif sait **créer** un point (Btrfs, ZFS, LVM) et le **restaurer** dans une nouvelle destination. Il ne sait **pas supprimer** un point. Les points s’accumulent donc jusqu’à une intervention manuelle sur le stockage.

Deux conséquences guident le découpage :

- **Supprimer demande une nouvelle action du service natif.** Ses modules sont figés : cette action ne peut pas être distribuée par paquet. Elle demande une campagne sur banc VM et une installation accompagnée.
- **Tout le reste se fait dans la console**, sans toucher au service natif, et se distribue par paquet signé.

| Lot | Contenu | Distribution | État |
| --- | --- | --- | --- |
| 1 | Règle de conservation par volume et simulation | Paquet signé | Livré en alpha.39 |
| 2 | Programmation des captures, avec plafond | Paquet signé | Livré en alpha.40 |
| 3 | Suppression explicite des points sortants | Installation accompagnée, banc VM | Service codé et prouvé en VM ; ni distribué, ni relié à la console |
| 4 | Conservation appliquée automatiquement | Après le lot 3 | Spécifié |

## Lot 1 — Règle et simulation

Dans **Stockage → Volumes et snapshots**, la carte **Conservation des points natifs** liste les volumes inscrits avec leur règle. **Régler et simuler** ouvre la règle d’un volume.

![Règle de conservation et simulation sur le banc de démonstration](images/native-retention.jpg)

Une règle dit ce qu’il faut garder :

| Champ | Effet |
| --- | --- |
| **Derniers points à garder** | Les points les plus récents, de 1 à 1 000. Le plus récent est donc toujours gardé. |
| **Jours, semaines, mois avec capture** | En plus, le dernier point de chacune des dernières périodes qui contiennent une capture. 0 désactive la période. |
| **Appliquer aussi la règle aux captures manuelles** | Sans cette case, une capture faite à la main n’est jamais proposée à la suppression. |

**Simuler** répartit les points présents en trois listes :

- **Gardés par la règle**, avec le ou les motifs de chacun ;
- **Sortiraient** : exactement les points que la règle ne garde pas, du plus ancien au plus récent ;
- **Protégés hors règle**, avec la raison.

Sont toujours protégés : un point en cours de création, à vérifier ou invalide ; un point dont la date est absente ou dans le futur ; tous les points d’un volume sur lequel une restauration est en cours ou à vérifier ; une capture manuelle, tant que la case n’est pas cochée.

**Enregistrer la règle** la conserve pour le volume. Elle ne déclenche rien.

Ce qu’il faut savoir :

- **Rien n’est supprimé.** La simulation lit l’état du service natif et calcule ; aucune commande n’est envoyée au stockage. Enregistrer une règle est inscrit au journal, avec la mention « aucune suppression ».
- **La simulation ne s’enregistre pas** et ne vaut que pour les points présents à l’instant indiqué.
- **Les périodes se comptent dans le fuseau de la console** au moment où la règle est enregistrée ; les semaines vont du lundi au dimanche.
- **Seuls les points créés par la [programmation](#lot-2--programmation-des-captures) sont « programmés »** ; tous les autres sont des captures manuelles, que la simulation ne propose de sortir que si la case est cochée.
- **Réservé aux administrateurs**, comme toute la page.
- **Sans service natif, la carte n’apparaît pas.**

La règle vit dans la table de réglages existante, une clé par volume : aucun changement de schéma.

## Lot 2 — Programmation des captures

Dans la même page, la carte **Programmation des captures** liste les volumes inscrits. **Programmer…** ouvre le réglage d’un volume.

![Programmation des captures sur le banc de démonstration](images/native-schedule.jpg)

| Réglage | Effet |
| --- | --- |
| **Heure** et **Jours** | Une capture par jour choisi, à cette heure, dans le fuseau de la console. |
| **Plafond de points programmés** | De 1 à 500, 30 par défaut. Atteint, la programmation s’arrête et le signale. |
| **Activer la programmation** | Demande de recopier « PROGRAMMER » suivi du nom du volume. Cette phrase vaut accord durable pour les captures de ce volume. |

Chaque ligne montre la programmation, le nombre de points programmés présents, la prochaine occurrence, et la dernière avec son résultat.

**Ce que fait une occurrence.** À l’heure dite, la console demande la capture au service natif par ses deux étapes habituelles, préparation puis validation, sous le compte « programmation ». Le service revérifie identité, politique et capacité, comme pour une capture faite à la main. Le point créé est noté comme programmé : la [règle de conservation](#lot-1--règle-et-simulation) le traite, sans toucher aux captures manuelles.

**Quand une occurrence ne crée pas de point :**

| Résultat | Cause | Suite |
| --- | --- | --- |
| **Occurrence sautée** | Une capture, une restauration ou une copie est en cours sur le volume ; le volume ou le service natif est indisponible. | Rien n’est mis en attente. Alerte. |
| **Capture refusée** | Le service natif a refusé la préparation ou la validation, par exemple faute de capacité. | Rien n’est réessayé. Alerte. |
| **Plafond atteint** | Le volume porte déjà autant de points programmés que le plafond. | Aucune capture tant qu’un point n’est pas retiré ou le plafond relevé. Alerte. |
| **Occurrence manquée** | La console était arrêtée à l’heure dite, depuis plus de quinze minutes. | Aucun rattrapage. Pas d’alerte : la suivante a lieu à son heure. |

L’alerte apparaît dans le centre de notifications et se clôt à la prochaine capture réussie, ou quand la programmation est réglée de nouveau ou désactivée. Chaque occurrence est inscrite au journal.

Ce qu’il faut savoir :

- **Jamais de suppression.** La programmation ne retire aucun point, même au plafond. Tant que le lot 3 n’existe pas, retirer un point reste une intervention manuelle sur le stockage.
- **Une occurrence n’a lieu qu’une fois.** Elle est consommée avant d’être tentée : une réponse perdue ou un redémarrage ne la rejouent pas.
- **Changement d’heure.** Une heure locale qui n’existe pas le jour du passage à l’heure d’été est sautée ; une heure qui existe deux fois ne déclenche qu’une capture.
- **Une capture par jour au plus par volume** : pas encore d’intervalle en heures.
- **LVM classique** : chaque point réserve de la place dans le groupe de volumes. Choisir un plafond que le groupe peut porter ; sinon le service refuse la capture et l’alerte le dit.
- **Si la note des points programmés est perdue**, par exemple après une restauration de la base de la console, ces points redeviennent des captures manuelles, donc protégées.
- **Désactiver** arrête les captures et conserve tous les points.

La programmation vit dans la table de réglages existante, une clé par volume : aucun changement de schéma ni de module figé.

**Prouvé sur banc VM**, avec de vrais volumes Btrfs, ZFS, LVM classique et LVM thin et le vrai service natif : une capture programmée par famille, présente sur le stockage et en lecture seule ; plafond atteint, occurrence manquée et programmation désactivée sans aucune capture ; plan déjà validé refusé. Voir [la validation](VALIDATION.md).

## Lot 3 — Suppression explicite

**État.** L’action du service natif existe et a passé sa campagne sur banc VM. Elle n’est dans aucune version, et la console ne la propose pas : il reste le bouton, sa confirmation, puis l’installation accompagnée.

**Accord de root.** Le service refuse toute suppression tant que la politique `/etc/nacre-storage/policy.json` ne porte pas `"deletion": true`. Mettre le service à jour ne donne donc pas ce pouvoir à la console : root l’accorde, machine par machine, et peut le retirer.

L’action suit le modèle des actions existantes :

1. **Préparation.** La console envoie le volume et la liste exacte des points sortants d’une simulation, cinquante au plus. Le service vérifie chaque point : il appartient au volume, il est prêt, son identité est inchangée. Il refuse si une restauration est en cours ou à vérifier sur le volume ; pour ZFS, si une copie dépend du point ou s’il est retenu ; pour LVM, si le point est ouvert ou n’est pas issu du volume. Un seul refus annule le plan entier.
2. **Plan.** Le service renvoie la liste, valable deux minutes, et la phrase à recopier, qui nomme le nombre de points et le volume : « SUPPRIMER 3 POINTS DE documents ».
3. **Validation.** Tout le plan est revérifié avant le premier effet. Puis, point par point : le point est marqué et inscrit au journal, supprimé, son absence est relue sur le stockage, et il est retiré du catalogue. La commande n’est jamais récursive ni forcée.

**Arrêt en cours de liste.** Au premier point que le système refuse de supprimer, l’opération s’arrête : ce point reste prêt, les suivants ne sont pas touchés. Il en va de même après quarante-cinq secondes. La réponse dit ce qui a été supprimé et ce qui reste.

**Interruption.** Un point marqué dont la suppression n’est pas confirmée passe « à vérifier ». Rien n’est rejoué. À la lecture d’état suivante, le service relit le stockage : le point est là, identité intacte, il redevient prêt ; son absence est prouvée, il quitte le catalogue ; sinon il reste à vérifier.

**Refus.** Politique sans accord de suppression ; plan expiré, déjà utilisé, d’un autre compte ; phrase inexacte ; politique ou identité modifiée depuis la préparation ; point devenu protégé entre-temps.

**Prouvé sur banc VM** (`tests/integration_native_delete_vm.py`), avec de vrais volumes Btrfs, ZFS, LVM classique et LVM thin et le vrai service, joint par son socket sous le compte non privilégié :

- refus sans accord dans la politique ;
- deux points supprimés par volume : exactement ceux-là disparaissent du stockage, les autres points et les fichiers du volume sont intacts ;
- plan rejoué, autre compte et phrase inexacte refusés ;
- plan entier refusé pour un point d’un autre volume, un point inconnu, un point ZFS dont dépend une copie, un point ZFS retenu ;
- politique modifiée après le plan : refus ;
- coupure juste avant et juste après la commande de suppression, pour chaque famille : « à vérifier » au redémarrage, rien de rejoué, puis point intact redevenu prêt dans un cas, point absent retiré du catalogue dans l’autre ;
- point remplacé par un autre objet de même nom après le plan : refus, l’objet de remplacement n’est pas supprimé ;
- point LVM pendant une vraie restauration : refus ; copie terminée et vérifiée, point monté ailleurs : refus ; point refermé : suppression acceptée.

Au total, treize points supprimés, exactement ceux annoncés. Ces preuves ne se font jamais sur une installation en service.

**Limites connues :**

- **Coupure de courant de la machine entière** : non essayée. Seul l’arrêt brutal du service autour de la commande l’a été.
- **Thin pool saturé** : non essayé. La suppression ne demande pas de capacité libre, mais ce cas n’a pas été reproduit.
- **Une restauration restée « à vérifier »** interdit toute suppression sur son volume, et rien ne permet encore de la lever depuis la console.
- **Un point invalide**, par exemple une réserve LVM saturée, n’est pas supprimable par le service : il reste une intervention manuelle sur le stockage.

## Lot 4 — Conservation automatique

Après le lot 3 seulement, et sur demande explicite par volume : la règle enregistrée est appliquée après une capture programmée réussie, par la même action de suppression, dans la limite de ce que la dernière simulation affichée a montré. Désactivée d’office après une interruption ou un refus, comme la rétention automatique des sauvegardes.

## Ce qui ne change pas

- **Aucune suppression implicite** : ni la règle, ni la simulation, ni la programmation ne suppriment un point. Aucune version ne propose encore la suppression.
- **Un point natif n’est pas une sauvegarde** : il vit sur le même support que les données.
- **Les opérations natives ne se valident que sur banc VM** ; aucune donnée ni clé d’une installation en service n’y entre.
