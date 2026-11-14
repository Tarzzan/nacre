# Recherche dans le contenu

Sixième brique de l’espace collaboratif : **retrouver un document par ce qu’il dit**, pas seulement par son nom. Depuis 0.8.0-alpha.63.

![Documents trouvés par leur texte](images/content-search.jpg)

## Ce que cela donne

- Dans **Fichiers**, tapez quelques mots dans le champ de recherche, puis **Dans le contenu des documents**. Nacre liste les documents dont le texte contient **tous** ces mots, les plus pertinents d’abord, chacun avec un extrait où les mots sont surlignés.
- La recherche rapide du bureau (**Ctrl+K**) propose la même chose : « Chercher … dans le contenu des documents ».
- Elle ne tient compte **ni des accents ni des majuscules**, et un mot trouve aussi ceux qu’il commence : `preau cou` trouve « Le préau sera coulé ».
- Un clic sélectionne un résultat et l’aperçoit ; un double clic l’ouvre dans son dossier. **Chercher ce nom à la place** relance la même saisie sur les noms de fichiers.
- La recherche par nom, par type, par date et par taille reste ce qu’elle était.

## Ce qui est lu

| Documents | Formats |
| --- | --- |
| Texte | `.txt`, `.md`, `.csv`, `.log`, `.json`, `.yaml`, `.ini`, `.conf`, `.tex`, `.rst`, `.srt` |
| Pages | `.html`, `.htm`, `.xml` |
| Bureautique | `.docx`, `.xlsx`, `.pptx`, `.odt`, `.ods`, `.odp` |
| PDF | `.pdf`, **si l’outil `pdftotext` est installé** sur le système (paquet `poppler-utils`) |

Le nom d’un document est toujours indexé : un fichier dont le texte n’a pas pu être lu reste trouvable par son nom.

## Ce qui protège vos documents

- **Chacun ne trouve que dans ses espaces.** L’index est commun, la réponse ne l’est jamais : un administrateur ne trouve rien dans l’espace personnel d’un membre, un membre rien dans une équipe dont il n’est pas. Un extrait obéit aux mêmes droits que le document.
- **Aucun document n’est interprété.** Nacre en tire le texte sans exécuter de macro, sans suivre de lien, sans développer d’entité déclarée par le fichier.
- **Des plafonds partout** : taille des fichiers lus, taille décompressée de chaque partie d’un document, texte gardé par document. Un fichier fait pour coûter cher est laissé de côté.
- L’outil des PDF reçoit le fichier sur son entrée, jamais son chemin, et tourne borné : vingt secondes de calcul, un gigaoctet de mémoire, soixante pages, aucune écriture de fichier.
- Ce que l’on tape ne devient jamais un opérateur de la recherche.
- Les extraits et les noms sont échappés ; seul le surlignage est ajouté, par la page.

## À savoir

- **Mise à jour.** L’index relit vos espaces quand on cherche, au plus toutes les deux minutes, et ne rouvre que les documents nouveaux ou changés. Pendant une lecture, la liste se complète d’elle-même. La toute première recherche lance la première lecture : les résultats arrivent à mesure.
- **Rien ne tourne quand personne ne cherche** : aucune lecture de fond au démarrage ni la nuit.
- Les cinquante documents les plus pertinents sont affichés ; au-delà, ajoutez un mot.
- Tous les mots doivent se trouver dans le document. Pas d’expression exacte entre guillemets ni d’opérateurs.

## Limites

- **PDF sans outil** : si `pdftotext` n’est pas installé, les PDF ne sont trouvés que par leur nom ; la page le dit. Un PDF repris plus tard, une fois l’outil installé, est lu sans qu’on y touche.
- **PDF numérisés** : une image de page n’a pas de texte. Pas de reconnaissance de caractères.
- Pas d’anciens formats Microsoft (`.doc`, `.xls`, `.ppt`), ni de courriels, ni d’archives.
- Dans un classeur Microsoft, ce sont les textes des cellules qui sont lus, pas les nombres.
- Fichier texte de plus de 2 Mio, document de plus de 64 Mio : non lu. Texte gardé : les 300 000 premiers caractères.
- Soixante premières pages d’un PDF.
- Un seul passage lit au plus 500 000 fichiers ; au-delà, la page le dit.
- Les versions gardées et la corbeille ne sont pas indexées.

## Sous le capot

`console/fulltext.py` et `console/library.py`. L’index est une base à part, `state/console/search.db` (SQLite, FTS5), **reconstructible** : la supprimer ne perd rien. Il contient le texte des documents : il se protège et se sauvegarde comme le reste de l’état de Nacre. Le schéma de la base de Nacre ne change pas.
