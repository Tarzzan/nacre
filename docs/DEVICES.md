# Appareils et WebDAV

Socle du programme « appareils et communication » : **ouvrir, synchroniser et sauvegarder ses fichiers depuis un outil ou une application**, sans passer par le navigateur. Lecture depuis 0.8.0-alpha.65, écriture depuis 0.8.0-alpha.66.

![Mes appareils, dans Mon compte](images/devices.jpg)

## Ce que cela donne

- Dans **Mon compte → Mes appareils**, chacun ajoute un appareil : Nacre produit un **mot de passe propre à cet appareil**, montré une seule fois.
- Avec ce mot de passe, un outil de synchronisation, un gestionnaire de fichiers ou une application **lit les fichiers de vos espaces** par WebDAV, à l’adresse de la console suivie de `/dav/`, et **les modifie** si vous lui en avez donné le droit.
- L’appareil ne saisit jamais votre mot de passe ni un code de double authentification, et **n’ouvre que des fichiers** : rien de l’administration, ni les sauvegardes, ni les vidéos.
- Un appareil **se retire d’un geste**, sans toucher aux autres. Changer son mot de passe, activer ou retirer sa double authentification les retire tous : ce qui change vos moyens de connexion écarte aussi ce qui s’en servait.
- **Deux niveaux** au choix à l’ajout : lire, ou lire et modifier. Un appareil qui modifie écrit là où vous écrivez vous-même, pas ailleurs.

## Ajouter un appareil

1. **Mon compte → Mes appareils** : donner un nom à l’appareil, choisir son accès (lire, ou lire et modifier), ressaisir son mot de passe (et un code, si la double authentification est active).
2. Reporter les trois réglages affichés : l’adresse, l’identifiant, le mot de passe. Le mot de passe se saisit avec ou sans tirets, en majuscules ou non.
3. **C’est noté** : il n’est plus affiché nulle part. Perdu, on retire l’appareil et on en ajoute un autre.

Vingt appareils au plus par personne.

## Ce qu’on y trouve

```
/dav/files/Mon espace/…
/dav/files/<nom d’un espace d’équipe>/…
/dav/files/Fichiers partagés/…
```

Les espaces sont ceux que la personne ouvre dans la console, sous leur nom. « Mon espace » est celui de qui se connecte. Renommer un espace change son adresse.

## Avec quels outils

| Outil | Réglage | Éprouvé |
| --- | --- | --- |
| **rclone** | type `webdav`, fournisseur `rclone`, adresse `…/dav/files` | Oui, version 1.75, sur le banc. Lecture : liste, copie d’un espace entier, contenus comparés un à un. Écriture : envoi d’un dossier, dates gardées, second envoi sans rien à transférer, modification, suppression, déplacement côté serveur, envoi en flux |
| Finder (Mac) | Aller → Se connecter au serveur | Non |
| Fichiers de GNOME | la même adresse en `davs://` | Non |
| Dolphin (KDE) | la même adresse en `webdavs://` (`davs://` sur les versions récentes) | Non |
| Cyberduck, WinSCP | WebDAV (HTTPS) | Non |
| Applications de téléphone (FolderSync, PhotoSync…) | WebDAV | Non |
| Explorateur de Windows | — | Déconseillé : son client WebDAV est limité et abandonné par Microsoft ; préférer un des outils ci-dessus |

Exemple avec rclone, pour copier un dossier du NAS vers l’ordinateur :

```bash
rclone config create nas webdav url=https://nas.local:8443/dav/files vendor=rclone user=camille pass=…
```

```bash
rclone copy "nas:Mon espace/Photos" ~/Photos-du-NAS
```

Et pour envoyer un dossier de l’ordinateur vers le NAS, avec un appareil qui a le droit de modifier :

```bash
rclone sync ~/Documents "nas:Mon espace/Documents"
```

`sync` rend l’arrivée identique au départ : ce qui n’est plus sur l’ordinateur part à la corbeille du NAS. Pour seulement ajouter, utiliser `copy`. Sans empreintes de contenu, rclone compare les tailles et les dates, à la seconde.

## Ce qui arrive à ce qu’un appareil modifie

- **Remplacer un fichier garde l’ancien contenu comme [version](VERSIONS.md)**, au nom de la personne. Un outil qui renvoie le même fichier plusieurs fois de suite n’en empile pas : une version est gardée à la première modification, puis au plus une toutes les dix minutes.
- **Supprimer envoie à la corbeille** de l’espace, d’où la console restaure.
- **Déplacer ou renommer** emmène les versions du fichier, dans le même espace. Une arrivée déjà occupée par un fichier est remplacée d’un coup, l’ancien contenu gardé comme version.
- Un fichier n’apparaît sous son nom qu’une fois **entièrement reçu** : un envoi coupé ne laisse rien, et ne touche pas à ce qui était là. Si la console est arrêtée en plein envoi, le morceau reçu reste caché dans le dossier ; il est retiré au bout d’un jour, au premier dépôt dans ce dossier.
- **Ce qu’une autre personne a enregistré pendant l’envoi n’est jamais perdu** : c’est le contenu réellement remplacé, et non celui d’avant l’envoi, qui rejoint les versions.
- Les dates données par l’outil sont gardées.
- Les fichiers dont le nom commence par un point sont admis (un outil de synchronisation en porte) ; les dossiers internes de Nacre restent hors d’atteinte.
- Au journal : une ligne par heure et par appareil, écrite dès la première opération puis tenue à jour, avec le nombre d’opérations et, parmi elles, de suppressions. Pas une ligne par fichier.

Par le réseau, l’outil doit reconnaître le certificat du NAS : installer d’abord l’[autorité locale](ACCESS.md#le-certificat) sur l’appareil.

## Ce qui protège vos fichiers

- **Aucun droit avant le mot de passe de l’appareil**, et aucun après un refus. Les droits sont ensuite ceux, vivants, de la personne : un accès retiré, un compte désactivé ou un rôle changé valent dès la requête suivante.
- Le mot de passe d’un appareil n’est gardé que sous forme d’empreinte. Il fait près de 120 bits : il ne se devine pas.
- **Dix refus en une minute** depuis une adresse, et elle n’obtient plus de réponse pendant une minute. Un mot de passe juste passe toujours : personne ne peut bloquer les appareils d’un compte en multipliant les refus à son nom. Ces refus ne consomment pas les tentatives de la connexion à la console.
- **Un navigateur est refusé** sans qu’on lui demande de mot de passe : les navigateurs actuels ne retiennent ainsi aucun mot de passe d’appareil pour l’adresse de la console.
- Aucun lien n’est suivi, les dossiers internes ne se voient pas, un fichier n’est jamais servi comme une page.
- **Une erreur n’est jamais déguisée en dossier vide** : un outil de synchronisation y lirait « tout a été supprimé ».
- Ajouter et retirer un appareil s’inscrit au journal. Un administrateur voit combien d’appareils a chacun, et peut tous les retirer.

## Limites

- **Pas de verrous** (WebDAV de classe 1) : le Finder de macOS ne monte l’espace qu’en lecture, et certains logiciels de bureautique ouvriront les fichiers en lecture seule.
- **Un dossier ne se copie pas d’un seul geste** côté serveur. rclone et Fichiers de GNOME copient alors son contenu fichier par fichier ; dans Cyberduck et WinSCP, dupliquer un dossier sur le NAS échoue.
- **La corbeille ne se vide pas seule tant qu’un administrateur n’a pas choisi une durée de garde** : un outil qui supprime beaucoup (`rclone sync`, `purge`) la remplit. Elle se vide dans **Fichiers → Corbeille**, et la [durée de garde](SPACES.md#la-corbeille) évite d’avoir à y penser. Un appareil ne vide jamais une corbeille.
- **La reprise d’un envoi interrompu n’existe pas** : un envoi partiel (`Content-Range`) est refusé plutôt que pris pour le fichier entier. Renvoyer le fichier.
- **Noms refusés à l’envoi** : ceux qui commencent ou finissent par une espace, portent une barre inverse ou un caractère de contrôle, dépassent 255 octets ou commencent par `.nacre-`. L’outil signale une erreur pour ces fichiers à chaque passage : les renommer sur l’ordinateur. Un fichier déjà présent sous un tel nom se déplace et se supprime normalement.
- Avec rclone, **une date ne se corrige pas seule** (`rclone touch` sur un fichier existant échoue) : le fichier est renvoyé.
- Les propriétés ne s’écrivent pas (`PROPPATCH`) : un outil qui en dépend pour les dates ne les gardera pas ; rclone, lui, les donne à l’envoi.
- La lecture d’un dossier s’arrête à 50 000 éléments.
- Un fichier dont le nom n’est pas lisible (ancien encodage) ou porte un caractère de contrôle n’apparaît pas : le renommer depuis la console.
- Deux espaces ne portent jamais la même adresse : un espace d’équipe nommé comme « Mon espace » ou « Fichiers partagés » reçoit une marque à la fin de son nom.
- Les lectures par un appareil ne s’inscrivent pas au journal, une par une : seuls l’ajout, le retrait et le dernier usage sont notés.
- Derrière un relais, tous les refus viennent de l’adresse du relais : la limite par adresse devient commune.
- Restaurer la base de Nacre depuis une sauvegarde fait revenir les appareils retirés depuis : les retirer de nouveau.
- **Seul rclone a été essayé.** Le reste du tableau repose sur le protocole, pas sur l’essai.

## Sous le capot

`console/devices.py` (mots de passe d’appareil, limite des refus), `console/dav.py` (OPTIONS, PROPFIND, GET avec plages et validation par marque ou par date, HEAD ; PUT avec ou sans longueur annoncée, MKCOL, DELETE, MOVE, COPY ; `store` écrit à côté puis échange, `sweep` retire les restes d’envois, `noted` tient le journal), bornes d’un appareil dans `spaces.level`. L’arborescence réserve `/dav/principals/`, `/dav/calendars/` et `/dav/addressbooks/` pour la suite. Réglages `device:<empreinte>` dans la table des réglages ; aucun changement de schéma.
