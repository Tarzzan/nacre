# Éditeur de documents

Quatrième brique de l’espace collaboratif : écrire et modifier un document sans quitter Nacre. Elle arrive en deux temps.

| Temps | Contenu | État |
| --- | --- | --- |
| Éditeur intégré | Texte et Markdown, dans la fenêtre Fichiers | Depuis 0.8.0-alpha.60 |
| Suite bureautique | Traitement de texte, tableur et présentations, par une brique en conteneur | À venir |

## Éditeur intégré

![Un document Markdown dans l’éditeur](images/editor-markdown.jpg)

*Banc local : compte et document fictifs.*

### Écrire

- **Nouveau document**, dans les outils de Fichiers : un nom en `.md` pour un document mis en forme, en `.txt` pour du texte simple. Il s’ouvre aussitôt.
- **Modifier**, dans l’aperçu d’un fichier texte : il s’ouvre dans la fenêtre, à la place de la liste.
- **Enregistrer**, ou Ctrl+S. **Fichiers**, en haut à gauche, referme le document.

Un document **Markdown** s’affiche en deux colonnes : le texte à gauche, son rendu à droite, qui suit la frappe. Titres, gras, italique, listes, cases à cocher, citations, tableaux, liens et code sont rendus.

### Ce qui protège votre travail

- **Chaque enregistrement garde l’ancien contenu** comme [version](VERSIONS.md). Vos enregistrements rapprochés, dans les dix minutes, n’en font qu’une : ils ne chassent pas les versions plus anciennes.
- **Un fichier modifié ailleurs n’est jamais écrasé en silence.** Si le fichier a changé depuis que vous l’avez ouvert, par une autre personne ou par le réseau, Nacre le dit ; « enregistrer mon contenu » range l’autre contenu parmi les versions.
- **« Aussi ouvert par… »** : une bannière nomme les autres personnes qui ont le même document ouvert. C’est une information, pas un verrou.
- **Fermer avec des modifications** demande confirmation.

### À savoir

- **Ce qui s’ouvre** : les fichiers texte lisibles (UTF-8) jusqu’à 2 Mio — notes, Markdown, CSV, JSON, YAML, fichiers de configuration, journaux. Le reste se télécharge.
- **Le texte n’est jamais interprété** : une page HTML s’ouvre comme du texte, et l’aperçu Markdown échappe tout ce qu’il affiche. Seuls les liens en `http` ou `https` deviennent cliquables.
- **Un PDF s’ouvre dans un nouvel onglet** du navigateur, depuis son aperçu.
- **Mêmes droits que l’espace** : qui lit l’espace lit le document ; qui y écrit l’enregistre.
- **Dans le bureau seulement** : l’affichage classique garde sa liste de fichiers simple.

### Limites

- **Pas de coédition en temps réel** : deux personnes ne voient pas la frappe de l’autre. Le dernier à enregistrer l’emporte, l’autre contenu reste dans les versions.
- **Markdown essentiel** : pas d’images, de notes de bas de page ni de formules.
- **Pas de documents bureautiques** (Word, Excel, PowerPoint, OpenDocument) : c’est l’objet de la suite bureautique, à venir.

### Sous le capot

`console/editor.py` et `console/static/editor.js`. L’enregistrement écrit à côté puis échange les deux noms d’un coup ; une étiquette (date et taille du fichier) détecte un changement fait ailleurs. Le rendu Markdown est écrit pour Nacre, sans dépendance. Aucun changement de schéma.
