# Relire les enregistrements par jour

Depuis **0.8.0-alpha.20**, la fiche d’une caméra dans **Surveillance** comporte une carte **Relecture**. Elle remplace la liste des derniers segments : tous les enregistrements encore conservés par Frigate deviennent accessibles depuis le navigateur, jour par jour. Depuis **0.8.0-alpha.21**, les événements du jour y apparaissent en vignettes, avec un filtre par type d’objet.

![Événements filtrés sur le banc simulé](images/playback-events.jpg)

Les vignettes de cette capture sont des pictogrammes générés pour le banc ; aucune image de caméra n’est publiée.

## Utilisation

1. Ouvrir **Surveillance**, puis une caméra.
2. Choisir le **jour** dans la liste. Seuls les jours pour lesquels Frigate annonce des enregistrements sont proposés, avec leur durée conservée. Les flèches passent au jour enregistré voisin. Le jour choisi est gardé quand on change de caméra.
3. Lire la **frise** de minuit à minuit : vert pour ce qui est enregistré, orange pour une présence détectée, gris pour ce qui n’est pas conservé, blanc pour les heures à venir du jour en cours.
4. Lancer la lecture, au choix :
   - cliquer sur la frise à l’instant voulu ;
   - saisir une heure dans **Lire à partir de**, puis **Lire** ;
   - cliquer sur la vignette d’un **événement** (la lecture commence cinq secondes avant) ;
   - à défaut d’événements, choisir une ligne de **Moments avec présence détectée**.
5. Sous **Événements**, choisir un type d’objet pour ne garder que ses vignettes. Des repères sombres marquent alors ces événements en haut de la frise. Le filtre ne coupe pas la lecture en cours et reste appliqué en changeant de jour ; il est ignoré les jours où ce type n’apparaît pas. Les boutons de filtre ne s’affichent que si au moins deux types sont présents ce jour-là.
6. Utiliser **5 min avant**, **Suite** ou **Télécharger cet extrait**. La lecture enchaîne seule l’extrait suivant jusqu’à la fin des enregistrements du jour.

Un clic ou une heure dans une période sans enregistrement ne produit pas d’erreur : Nacre l’annonce et reprend au début de la plage suivante. Après la dernière plage, il indique qu’il n’y a plus rien à lire ce jour-là.

## Ce que montrent les indications

| Indication | Origine et portée |
| --- | --- |
| **Enregistré** | Segments présents dans l’inventaire de Frigate pour ce jour. Deux segments séparés de moins de trois secondes forment une même plage. |
| **Événements** | Objets suivis par Frigate ayant commencé ce jour-là, du plus ancien au plus récent : vignette, type, nom reconnu s’il existe, heure de début, durée et meilleur score. Un événement est rattaché au jour où il commence. Les types courants sont traduits ; un type inconnu est affiché tel que Frigate le nomme. |
| **Vidéo non conservée** | L’événement ne recoupe aucune plage enregistrée : la vignette reste, la lecture est désactivée. |
| **Présence détectée** | Segments pour lesquels le suivi d’objets de Frigate compte au moins un objet actif. Ce n’est ni une alarme ni une liste exhaustive ; rien n’apparaît si la détection est désactivée. |
| **Rien de conservé** | Aucun segment dans l’inventaire. Nacre ne dit pas pourquoi : caméra coupée, service arrêté ou segment supprimé par la conservation. |
| **Sans enregistrement** | Les trois premières périodes vides entre deux plages, puis leur nombre. |
| **Heures du NAS** | Le fuseau réglé dans le Panneau de configuration. Les jours de 23 ou 25 heures suivent le changement d’heure ; une heure répétée désigne sa première occurrence. |

Au-delà de la durée de conservation continue, Frigate ne garde que certains passages. Un jour ancien affiche donc normalement quelques plages courtes, et non une journée interrompue par des pannes.

## Périmètre et limites

- **Types d’objets.** Nacre montre ce que Frigate suit. Une installation qui ne suit que les personnes n’affiche qu’un type, donc pas de filtre ; le choix des objets suivis reste un réglage de Frigate que Nacre ne modifie pas.
- **Volume.** Mille événements au plus sont présentés par jour ; au-delà, la carte le signale. Les vignettes sont chargées à mesure du défilement et ne sont pas mises en cache par le navigateur.
- **Vignettes.** Ce sont celles que Frigate produit (175 × 175 pixels sur l’installation mesurée). Chaque demande vérifie que l’événement appartient à la caméra consultée. Les instantanés en pleine résolution ne sont pas proposés.
- **Lecture seule.** Aucune configuration, tâche ou vidéo n’est écrite. Frigate n’est ni redémarré ni reconfiguré. Un téléchargement est inscrit au journal d’activité avec le compte et le nom du fichier.
- **Extraits de cinq minutes au plus**, produits à la demande par Frigate dans la qualité enregistrée. Sur la caméra mesurée, cinq minutes représentent environ 120 Mo. Ce volume transite par la console ; aucun plafond de taille n’est ajouté.
- **Déplacement dans un extrait.** Frigate diffuse l’extrait sans plages d’octets : le curseur du lecteur ne permet pas toujours d’avancer dans la partie non encore reçue. La frise et l’heure saisie servent de déplacement.
- **Fin d’extrait.** Un extrait s’arrête à la fin de sa plage. S’il manque un segment à l’intérieur, la vidéo obtenue est plus courte que l’intervalle annoncé.
- **Jour en cours.** La frise reflète l’inventaire au chargement. **Actualiser** relit les enregistrements récents.
- **Période consultable.** Dates jusqu’à 400 jours en arrière pour la frise, extraits jusqu’à 31 jours : la conservation réglable s’arrête à 30 jours.
- **Comptes en lecture seule.** Ils consultent et téléchargent les extraits, comme ils consultaient déjà les clips. Les réglages et le pilotage restent réservés aux administrateurs.
- **Non couvert.** Recherche sur plusieurs jours, filtre par zone ou par score, export de longues périodes, lecture synchronisée de plusieurs caméras, protection d’un passage contre la suppression et contrôle d’intégrité des fichiers vidéo.

## Erreurs affichées

| Message | Signification |
| --- | --- |
| Enregistrements temporairement indisponibles | Le service vidéo n’a pas répondu ou a renvoyé une réponse inexploitable. Aucun enregistrement n’est inventé. |
| Date hors de la période consultable | Jour futur ou trop ancien. Le choix est oublié à l’actualisation suivante. |
| Cette heure n’existe pas ce jour-là | Saisie invalide, ou heure sautée par un passage à l’heure d’été. |
| Événements indisponibles | Le service vidéo n’a pas fourni la liste des événements. La frise et les moments détectés restent utilisables. |
| Vignette indisponible | Frigate ne fournit plus l’image de cet événement. La lecture reste possible si la vidéo est conservée. |
| Extrait indisponible | Frigate n’a pas fourni la plage demandée, par exemple si elle vient d’être supprimée par la conservation. |

## Validation

Huit tests Python sur inventaire simulé : fusion des segments, bornage au jour civil, réponses malformées ou trop volumineuses, jours de 23 et 25 heures, fuseau inconnu, dates refusées avant toute requête vidéo, droits, bornes des extraits, nom du fichier téléchargé et trace au journal. Sept tests JavaScript : déplacement dans les plages et les trous, heure saisie lors des changements d’heure, frise sans style en ligne, valeurs échappées, réponses tardives écartées après un autre choix.

Parcours navigateur sur un banc local : console réelle, service vidéo simulé, mire générée localement, trois jours dont un avec un trou et un ne gardant que des passages. Clic dans un trou, heure saisie, moment détecté, enchaînement automatique, retour de cinq minutes, changement de jour, téléchargement et date refusée y ont été contrôlés. Aucune image réelle n’est publiée.

Événements (alpha.21) : trois tests Python supplémentaires sur le bornage au jour et à la caméra, les entrées malformées, le plafond, la relecture maintenue quand les événements manquent, et la vignette refusée pour un identifiant invalide ou une autre caméra. Trois tests JavaScript sur les vignettes, l’échappement, le filtre appliqué sans reconstruire la carte et le repli sur les moments détectés. Parcours navigateur sur le banc avec vignettes synthétiques, en largeur d’ordinateur et de téléphone.

Sur l’installation de développement, seules des lectures de l’API de Frigate ont servi à mesurer le format des réponses, le poids d’un extrait, l’absence de plages d’octets, puis la forme des événements et la taille des vignettes. Ces mesures concernent une caméra et une version de Frigate ; elles ne qualifient ni d’autres modèles ni une charge multi-caméra.
