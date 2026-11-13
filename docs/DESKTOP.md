# Le Bureau

Depuis la version 0.8.0-alpha.26, Nacre s’ouvre sur un bureau, à la manière d’un système dans le navigateur. C’est la première étape d’un parcours en sept lots ; les pages de la console ne changent pas, seule leur organisation change.

![Bureau de Nacre sur le banc de démonstration](images/desktop-shell.jpg)

*Banc local à données synthétiques : l’application Fichiers ouverte, le dock en bas.*

## Ce que l’on trouve

| Élément | Rôle |
| --- | --- |
| **Barre supérieure** | Le nom du NAS, les alertes, l’heure, le compte. Un clic sur « nacre » affiche le bureau. |
| **Icônes et dock** | Les sept applications. Un trait sous une icône du dock signale l’application ouverte ou réduite. |
| **Widgets** | Stockage libre, services, surveillance, activité récente, mémoire. Un clic ouvre l’application concernée. |
| **Fenêtre** | Elle se déplace par sa barre de titre, s’agrandit (bouton ou double-clic), se réduit ou se ferme. |
| **Onglets** | Les pages de l’application. Rouvrir une application réduite ramène au dernier onglet consulté. |

## Les sept applications

| Application | Onglets | Rubriques d’origine |
| --- | --- | --- |
| **Fichiers** | Parcourir, Corbeille | Fichiers |
| **Surveillance** | Caméras | Surveillance |
| **Stockage** | Disques, Volumes et snapshots | Stockage, Volumes natifs |
| **Protection** | Sauvegardes, Points de restauration, Conservation | Sauvegardes, Snapshots, Rétention |
| **Partages et comptes** | Partages, Utilisateurs | Partages SMB, Utilisateurs |
| **Réglages** | Général, Services, Mises à jour, Notifications | Panneau de configuration, Services |
| **Activité** | Alertes, Journal | Alertes, Journal d’activité |

La vue d’ensemble est devenue le bureau lui-même. Un compte en lecture seule ne voit pas les onglets réservés aux administrateurs.

## Revenir à l’affichage classique

Le bouton **Classique** de la barre supérieure rend le menu à gauche tel qu’il était ; le bouton **Bureau** y ramène. Le choix est mémorisé dans le navigateur, pas sur le NAS : chaque poste garde le sien. L’assistant de première configuration utilise toujours l’affichage classique.

## Limites de cette étape

- **Une fenêtre à la fois.** Ouvrir une application remplace la précédente. Plusieurs fenêtres côte à côte demandent de rendre chaque page indépendante : c’est un lot ultérieur.
- **Pas encore de recherche globale ni de centre de notifications.** Les alertes gardent leur bouton dans la barre.
- **Widgets fixes**, non personnalisables, et sans image de caméra.
- **Position et taille de la fenêtre** oubliées au rechargement de la page ; la fenêtre ne se redimensionne pas à la souris.
- **Surveillance** reste une seule page longue ; la taille des textes n’a été relevée que pour les notes les plus petites.

## Validation

Cinq essais JavaScript : coquille et repères attendus par les pages, onglets selon le rôle, chaque page rangée dans une application et une seule, bascule vers l’affichage classique et retour, assistant toujours en classique, stockage du navigateur indisponible, fenêtre et onglets à chaque navigation, dernier onglet retrouvé depuis le dock, widgets échappés et réponses tardives ignorées. Les 93 essais existants passent sans modification dans les deux affichages.

Parcours navigateur sur le banc local, avec la politique de sécurité réelle de la console : ouverture des sept applications, déplacement, agrandissement, réduction et fermeture de la fenêtre, bascule vers l’affichage classique et retour, largeur de téléphone sans défilement horizontal.
