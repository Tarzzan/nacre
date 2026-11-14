# Changelog

## 0.8.0-alpha.50 — Passages conservés : liste à jour aussitôt

Correctif d’alpha.49, trouvé en l’essayant sur une installation réelle. Le service vidéo garde ses réponses cinq secondes : juste après **Conserver** ou **Retirer**, la liste des passages pouvait montrer l’état d’avant, sans le passage tout juste conservé ou avec celui qu’on venait de retirer. La liste est désormais lue sans ce cache, et relue deux fois après une demande de conservation, le temps que la copie apparaisse. Rien n’était perdu ni gardé à tort : seul l’affichage retardait. Aucun changement de schéma ni de module figé. 365 tests Python, 141 JavaScript. [Guide](docs/RECORDING-PLAYBACK.md#conserver-un-extrait).

## 0.8.0-alpha.49 — Passages conservés et autonomie vidéo

Dans **Surveillance → Relecture**, **Conserver cet extrait** garde à part l’extrait en cours de lecture, avec un nom facultatif. Une carte **Passages conservés** les liste par caméra : lire, télécharger, retirer. Un passage conservé est une copie faite par le service vidéo : ni la durée de conservation ni un volume plein ne l’effacent, et il occupe de la place tant qu’on ne le retire pas. Dans **Réglages**, une carte **Stockage vidéo** donne l’autonomie : le temps d’enregistrement que l’espace libre représente au débit mesuré, et dit quand la durée de conservation réglée ne tient pas sur le volume. Quand le volume est plein, l’enregistrement continue en effaçant les plus anciens ; c’est le comportement du service vidéo, désormais écrit dans la console. Nacre ne lit ni n’écrit lui-même aucun fichier vidéo. Aucun changement de schéma ni de module figé. 365 tests Python, 141 JavaScript. [Guide](docs/RECORDING-PLAYBACK.md#conserver-un-extrait).

## 0.8.0-alpha.48 — Poids des espaces

Dans **Fichiers**, une vue met côte à côte le poids de chaque espace : contenu, poids, part parmi les espaces pesés, et date de la pesée. La dernière pesée d’un espace entier est désormais **gardée** : on la retrouve sans relire le disque, et **Peser**, **Repeser** ou **Peser tous les espaces** la met à jour à la demande. On y arrive par **Comparer les espaces**, dans le titre d’une pesée, ou par **Poids des espaces** dans la recherche globale. Un poids gardé est une photographie datée, il ne suit pas ce qui change ensuite, et seule la pesée d’un espace entier est gardée. Au passage, une pesée arrêtée avant la fin annonce toujours son total comme un minimum. Les pesées gardées vivent dans la table de réglages existante : aucun changement de schéma ni de module figé. 357 tests Python, 136 JavaScript. [Guide](docs/DESKTOP.md#comparer-les-espaces).

## 0.8.0-alpha.47 — Suite des événements

Dans **Surveillance → Événements**, la liste ne s’arrête plus aux soixante événements les plus récents de chaque caméra : **Afficher la suite** remonte plus loin dans la période, jusqu’à tout lister. La suite est demandée à la caméra qui borne la liste, sur la période exacte de la première réponse, et la liste ne grandit que par la fin : tant qu’une caméra a des événements non chargés, rien de plus ancien que son dernier événement chargé n’est montré, pour qu’aucun ne vienne s’intercaler après coup. Un refus du serveur est dit sans rien perdre de ce qui est affiché. Côté navigateur seulement : aucun changement du serveur, du schéma ni de module figé. 356 tests Python, 135 JavaScript. [Guide](docs/DESKTOP.md).

## 0.8.0-alpha.46 — Restaurations natives « à vérifier » relues

Une restauration native interrompue restait « à vérifier » sans fin : elle protégeait tous les points de son volume, bloquait leur suppression et faisait sauter chaque passage de la conservation automatique, sans recours depuis la console. Le service natif la **relit désormais de lui-même**, deux minutes au moins après son lancement, sans rien créer ni supprimer : copie présente, la restauration est terminée et garde sa destination ; copie absente, ou copie de fichiers LVM dont le processus a disparu, elle est en échec ; dans le doute, elle reste « à vérifier ». La suppression n’est alors plus bloquée. Le changement vit dans le point d’entrée du service (`native_service.py`) : il prend effet là où root réinstalle le service natif. Aucun changement de schéma ni de module figé. Prouvé sur banc VM avec de vraies restaurations Btrfs, ZFS et LVM interrompues. 356 tests Python, 134 JavaScript. [Détails](docs/NATIVE-SNAPSHOT-POLICY.md#une-restauration-restée--à-vérifier-).

## 0.8.0-alpha.45 — Dossiers de données protégés

Troisième lot de l’[issue 2](https://github.com/Tarzzan/nacre/issues/2), qui ferme le chemin laissé ouvert par alpha.44. Les conteneurs tournent en root et écrivent dans des dossiers de l’hôte : sans précaution, qui tient le compte de la console pouvait leur faire déposer un programme privilégié ou un fichier de périphérique dans un dossier partagé, puis s’en servir. **La démonstration a été faite sur le banc, puis la porte fermée** : remontés avec `nosuid` et `nodev`, ces dossiers ne confèrent plus aucun droit, sans redémarrer les conteneurs. `install_services.py --protect` prépare les deux montages pour root ; l’agent constate la protection de chaque dossier, l’accueil le dit, et la politique peut l’exiger (`require_protected_mounts`) : l’agent refuse alors de démarrer un service sur un dossier exposé. Les sources des images viennent désormais de la copie de l’agent, et root peut fixer l’image Frigate. Une vingtième opération, `protection`, rejoint la liste fermée. Toujours rien d’automatique : chaque machine attend les gestes de son administrateur, et la migration d’une installation en service reste le dernier lot. Aucun changement de schéma ni de module figé. 355 tests Python, 134 JavaScript. [Marche à suivre, preuves et limites](docs/SERVICE-AGENT.md).

## 0.8.0-alpha.44 — Agent de services

Deuxième lot de l’[issue 2](https://github.com/Tarzzan/nacre/issues/2). Les opérations Docker de la console peuvent désormais être tenues par un **agent de services** : un daemon root qui n’écoute que le compte de la console, sur un socket local, et n’exécute que la liste fermée d’alpha.43. Il ne se fie à rien de ce que ce compte peut écrire : il utilise sa propre copie de la description des services, ne retient que trois variables validées, et refuse tout montage de partage hors des emplacements approuvés par root. Quand l’agent est installé, la console passe par lui ; sinon rien ne change. **L’agent s’installe par root** (`console/install_services.py`), et c’est seulement une fois le compte de la console sorti du groupe `docker` que l’accès direct disparaît ; l’accueil dit laquelle des trois situations est en place. Prouvé sur banc VM avec un vrai Docker : compte sorti du groupe, seize opérations rejouées sans recréer le conteneur, description trafiquée ignorée, sept montages refusés. **Un chemin plus étroit reste ouvert** par les conteneurs, qui tournent en root et écrivent dans des dossiers de l’hôte : le [document de l’issue](docs/SERVICE-AGENT.md#ce-qui-reste-ouvert) le décrit, et les deux lots restants. Aucun changement de schéma ni de module figé. 354 tests Python, 134 JavaScript.

## 0.8.0-alpha.43 — Liste fermée des opérations Docker de la console

Premier lot de l’[issue 2](https://github.com/Tarzzan/nacre/issues/2), qui vise à réduire les privilèges de la console sur Docker. **Rien ne change à l’écran, et aucun privilège n’est encore retiré** : le compte de la console garde son accès à Docker. Ce lot pose le préalable. Tout ce que le processus web demande à Docker passe désormais par dix-neuf opérations nommées, dans un nouveau module (`service_agent.py`) : paramètres validés, ligne de commande fixe, aucune commande ni option libre. Un essai interdit à tout autre module de la console de composer une commande Docker. Le [document de l’issue](docs/SERVICE-AGENT.md) donne le modèle de menace, l’inventaire complet, ce que cette liste ne règle pas, et les deux lots suivants : un agent séparé qui vérifie qui lui parle, puis la migration réversible des installations. Aucun changement de schéma ni de module figé. 348 tests Python, 134 JavaScript.

## 0.8.0-alpha.42 — Conservation automatique des points natifs

Quatrième et dernier lot de l’[issue 4](https://github.com/Tarzzan/nacre/issues/4). Dans **Stockage → Volumes et snapshots**, **Automatique…** permet d’appliquer d’elle-même la règle enregistrée d’un volume après chaque capture programmée : les points programmés qu’elle ne garde plus sont supprimés par le service natif, sans autre confirmation. L’activer demande de recopier « AUTOMATISER » suivi du nom du volume, et de fixer un **maximum de points par passage** ; au-delà, rien n’est supprimé. **Une capture manuelle n’est jamais supprimée automatiquement.** Au premier refus ou arrêt, la conservation automatique **se suspend**, lève une alerte et attend d’être réactivée ; rien n’est rejoué. Enregistrer une autre règle la désactive. Une programmation arrivée à son plafond est libérée par le passage, et repart à l’occurrence suivante. Disponible seulement là où l’administrateur du système a accordé la suppression. Un nouveau module serveur (`native_auto.py`), qui utilise la table de réglages existante : aucun changement de schéma, de module figé ni du service natif. Prouvé sur banc VM avec de vrais volumes Btrfs, ZFS, LVM classique et LVM thin. 344 tests Python, 134 JavaScript. Mode d’emploi, preuves et limites : [docs/NATIVE-SNAPSHOT-POLICY.md](docs/NATIVE-SNAPSHOT-POLICY.md#lot-4--conservation-automatique).

## 0.8.0-alpha.41 — Suppression explicite des points natifs

Troisième lot de l’[issue 4](https://github.com/Tarzzan/nacre/issues/4). Dans **Stockage → Volumes et snapshots**, sous les points qu’une simulation ferait sortir, un bouton **Supprimer ces points…** ouvre une fenêtre qui les liste un par un et demande de recopier la phrase du service, par exemple « SUPPRIMER 3 POINTS DE documents ». La liste supprimée est exactement celle qui était affichée, cinquante points au plus par opération. Le service natif revérifie chaque point, refuse le plan entier au moindre doute (restauration en cours, copie ZFS dépendante, point LVM ouvert, identité modifiée), s’arrête au premier point qui résiste et ne rejoue jamais rien. **La suppression n’existe que là où l’administrateur du système l’a accordée** : le service natif doit être réinstallé par root, et sa politique porter `"deletion": true` ; ailleurs, la console le dit et garde règle et simulation. L’action vit dans un nouveau module, `native_service.py`, point d’entrée du service : aucun module figé ni schéma ne change, la console se met à jour par paquet signé. Prouvé sur banc VM avec de vrais volumes Btrfs, ZFS, LVM classique et LVM thin, coupures comprises. 339 tests Python, 133 JavaScript. Mode d’emploi, preuves et limites : [docs/NATIVE-SNAPSHOT-POLICY.md](docs/NATIVE-SNAPSHOT-POLICY.md#lot-3--suppression-explicite).

## 0.8.0-alpha.40 — Programmation des captures natives

Deuxième lot de l’[issue 4](https://github.com/Tarzzan/nacre/issues/4). Dans **Stockage → Volumes et snapshots**, chaque volume natif peut recevoir une **programmation** : une heure, des jours et un plafond de points. L’activer demande de recopier une phrase de confirmation. À l’heure dite, la console demande la capture au service natif par ses deux étapes habituelles ; le point créé est noté comme programmé, et la règle de conservation le distingue des captures manuelles. Une occurrence qui tombe pendant une autre opération est **sautée**, une occurrence manquée pendant un arrêt n’est **pas rattrapée**, et rien n’est jamais rejoué. Au plafond, la programmation s’arrête et lève une alerte : **elle ne supprime aucun point**. Un nouveau module serveur (`native_schedule.py`), qui utilise la table de réglages existante : aucun changement de schéma ni de module figé. Prouvé sur banc VM avec de vrais volumes Btrfs, ZFS et LVM. 328 tests Python et 132 JavaScript. [Guide et limites](docs/NATIVE-SNAPSHOT-POLICY.md#lot-2--programmation-des-captures).

## 0.8.0-alpha.39 — Conservation des points natifs : règle et simulation

Premier lot de la programmation des snapshots natifs ([issue 4](https://github.com/Tarzzan/nacre/issues/4)). Dans **Stockage → Volumes et snapshots**, chaque volume inscrit reçoit une **règle de conservation** : derniers points à garder, plus le dernier point de chaque jour, semaine ou mois ayant une capture. **Simuler** dit exactement quels points la règle garderait et pourquoi, lesquels sortiraient, et lesquels sont protégés : point à vérifier, restauration en cours sur le volume, capture manuelle. **Rien n’est supprimé** : le service natif ne sait pas supprimer un point, et ce lot ne lui envoie aucune commande. La suite (programmation des captures, suppression explicite, conservation automatique) est spécifiée dans le même document. Un nouveau module serveur (`native_retention.py`), qui utilise la table de réglages existante : aucun changement de schéma ni de module figé. 325 tests Python et 131 JavaScript. [Guide, limites et suite](docs/NATIVE-SNAPSHOT-POLICY.md).

## 0.8.0-alpha.38 — Poids des dossiers

**Fichiers** dit maintenant « quel dossier pèse le plus ? ». La pesée du dossier ouvert donne, pour chaque élément, **la taille de tout ce qu’il contient**, du plus lourd au plus léger, avec le nombre d’éléments et la part du total. On y arrive par **Peser ce dossier** dans le panneau d’un dossier sélectionné, par **Poids des dossiers** depuis la recherche par critères, ou par la recherche globale (Ctrl+K). Un double-clic sur un dossier le pèse à son tour ; **Peser le dossier parent** remonte. Les fichiers cachés et la corbeille sont comptés sur une ligne à part, sans être nommés. La pesée a les bornes de la recherche (quatre secondes, 200 000 éléments) : un dossier qu’elle n’a pas fini est donné comme un minimum, un dossier pas commencé est dit « non pesé ». Aucun changement de schéma ni de module figé. 323 tests Python et 130 JavaScript. [Guide et limites](docs/DESKTOP.md#peser-les-dossiers).

## 0.8.0-alpha.37 — Recherche de fichiers par critères, sans nom

**Fichiers** répond à « qu’est-ce qui prend de la place ? ». Le bouton **Par critères** de la barre d’outils lance une recherche sans nom dans le dossier ouvert et ses sous-dossiers : les **plus gros fichiers d’abord**, que les listes Type, Modifié et Taille resserrent ensuite (« les vidéos de plus de 1 Gio », « les documents modifiés depuis 7 jours »). Une quatrième liste, **Ordre**, classe aussi par modification la plus récente, et sert de la même façon à une recherche par nom. **Étendre à tout le NAS** relance la même recherche partout, et la recherche globale (Ctrl+K) propose **Les plus gros fichiers** pour tout le NAS. Un classement lit tout ce que les bornes de parcours permettent et n’affiche que les 200 premiers, en donnant le nombre de correspondances rencontrées. Aucun changement de schéma ni de module figé. 322 tests Python et 129 JavaScript. [Guide et limites](docs/DESKTOP.md#chercher-sans-nom-par-critères).

## 0.8.0-alpha.36 — Filtres de la recherche de fichiers

Les résultats d’une recherche par nom dans **Fichiers** s’affinent par trois listes : **Type** (dossiers, images, vidéos, sons, documents, archives), **Modifié** (depuis 24 heures, 7 jours, 30 jours, un an) et **Taille** (plus de 1 Mio, 100 Mio, 1 Gio). Un choix relance la même recherche, même nom et même portée ; les filtres se combinent et **Retirer les filtres** les enlève tous. Ils permettent aussi de dépasser le plafond de 200 résultats d’un nom très courant. Le type se déduit de l’extension, jamais du contenu ; date et taille ne sont lues que pour les éléments dont le nom correspond. Aucun changement de schéma ni de module figé. 321 tests Python et 128 JavaScript. [Guide et limites](docs/DESKTOP.md#affiner-les-résultats).

## 0.8.0-alpha.35 — Période et tranche horaire dans l’onglet Événements

L’onglet **Événements** de Surveillance, qui réunit toutes les caméras, reçoit les mêmes champs que la recherche d’une caméra : une **période** (les sept derniers jours par défaut) et une **tranche horaire** facultative. « Entre 22:00 et 06:00 » montre d’un coup ce que chaque caméra a vu la nuit. Un résumé donne le nombre d’événements comptés sur la période pour l’ensemble des caméras ; **Sept derniers jours** revient à l’affichage d’origine. Une période que le serveur refuse est expliquée une fois, sans mettre les caméras en cause. Aucun changement côté serveur, de schéma ni de module figé. 320 tests Python et 127 JavaScript. [Guide et limites](docs/DESKTOP.md#surveillance).

## 0.8.0-alpha.34 — Recherche d’événements par tranche horaire

La carte **Recherche d’événements** d’une caméra accepte une **tranche horaire** facultative, appliquée à chaque jour de la période : « entre 22:00 et 06:00 » ne garde que les nuits, « entre 08:00 et 18:00 » les journées. Une tranche dont la fin précède le début enjambe minuit. Le total, les compteurs par type et par jour ne portent alors que sur la tranche ; le type choisi et **Afficher la suite** la conservent. C’est l’heure de début de l’événement, dans le fuseau de la console, qui décide. Le filtre est appliqué par Nacre : rien ne change dans les demandes faites au service vidéo. Aucun changement de schéma ni de module figé. 320 tests Python et 126 JavaScript. [Guide et limites](docs/RECORDING-PLAYBACK.md#ne-garder-quune-tranche-horaire).

## 0.8.0-alpha.33 — Recherche de fichiers par nom

Le champ en haut de **Fichiers** filtre toujours le dossier ouvert pendant la saisie ; dès deux caractères, il propose aussi de **chercher ce nom dans les sous-dossiers ou dans tout le NAS**, et Entrée lance la recherche partout. Les résultats indiquent l’emplacement de chaque fichier ou dossier, s’aperçoivent et se téléchargent sur place, et un clic ouvre le dossier où ils se trouvent, l’élément sélectionné. La **recherche globale** (Ctrl+K) propose la même chose pour ce que l’on vient d’y taper. Accents et majuscules ne comptent pas ; les mots saisis peuvent figurer dans n’importe quel ordre. La recherche parcourt le NAS à la demande, sans index : elle ne suit aucun lien, ignore les fichiers cachés, ne lit pas le contenu, et s’arrête d’elle-même après quatre secondes, 200 000 éléments ou 200 résultats, en le disant. Un nouveau module serveur (`file_search.py`) : aucun changement de schéma ni de module figé. 318 tests Python et 125 JavaScript. [Guide et limites](docs/DESKTOP.md#rechercher-un-fichier-par-son-nom).

## 0.8.0-alpha.32 — Bureau personnalisable

Le bouton **Personnaliser** de la barre du bureau permet de choisir les widgets affichés, leur ordre et le fond parmi quatre. Deux widgets s’ajoutent au choix : Alertes et Tâches en cours. Ces préférences sont enregistrées **par compte** sur le NAS et se retrouvent sur tout navigateur ; un compte en lecture seule peut régler son propre bureau, et rien d’autre. Les **fenêtres ouvertes, leur place et leur taille** sont mémorisées par navigateur et reviennent au rechargement, sans changer la page demandée par l’adresse. Septième et dernier lot du cap « bureau dans le navigateur ». Un nouveau module serveur (`desk_prefs.py`), qui utilise la table de réglages existante : aucun changement de schéma ni de module figé. 315 tests Python et 122 JavaScript. [Guide et limites](docs/DESKTOP.md#personnaliser-le-bureau).

## 0.8.0-alpha.31 — Plusieurs fenêtres

Le bureau ouvre désormais **une fenêtre par application, plusieurs à la fois** : suivre un envoi de fichiers en regardant une caméra, garder le journal ouvert à côté des réglages. Chaque fenêtre se déplace, se redimensionne par son coin, s’agrandit, se réduit dans le dock et se ferme sans toucher aux autres ; un clic la met devant. Une page ouverte depuis une fenêtre (un lien du panneau de réglages, une alerte, un résultat de recherche) arrive dans la fenêtre de la bonne application. Sur téléphone, la fenêtre de devant occupe l’écran et le dock fait passer de l’une à l’autre. Chaque fenêtre héberge la console elle-même dans un cadre de même origine : les pages ne sont pas réécrites et gardent chacune leur état. La console accepte donc d’être encadrée par elle-même, et par elle seule. Aucun changement de schéma ni de module figé. 313 tests Python et 119 JavaScript. [Guide et limites](docs/DESKTOP.md#plusieurs-fenêtres).

## 0.8.0-alpha.30 — Gestionnaire de fichiers

Dans le bureau, Fichiers devient un vrai gestionnaire : arborescence des espaces et des dossiers à gauche, contenu au centre en liste triable ou en grille, aperçu à droite. La sélection multiple (cases, Ctrl, Maj, Ctrl+A) fait apparaître une barre d’actions : télécharger, renommer, déplacer, mettre en corbeille. On glisse des fichiers depuis l’ordinateur pour les envoyer, plusieurs à la fois, et une sélection vers un dossier pour la déplacer. L’aperçu montre les images, les vidéos et le début des textes sans quitter la page. Deux opérations nouvelles côté serveur : **déplacer** des éléments dans un même espace, sans jamais remplacer ni suivre un lien, et **télécharger une sélection en archive ZIP**, produite à la volée sans plafond de taille. L’affichage classique garde sa page. Aucun changement de schéma ni de module figé. 312 tests Python et 117 JavaScript. [Guide et limites](docs/DESKTOP.md#fichiers).

## 0.8.0-alpha.29 — Surveillance en application

Dans le bureau, Surveillance devient une application à quatre onglets au lieu d’une page longue. **Mur** : toutes les caméras côte à côte, en images fixes rafraîchies toutes les dix secondes ; un clic agrandit une caméra, ouvre son direct et son pilotage, les autres restant en images fixes. **Événements** : ceux de toutes les caméras sur sept jours, du plus récent au plus ancien, filtrables par caméra et par type ; un clic ouvre la relecture sur la bonne caméra, au bon moment. **Relecture** : la carte existante, complétée d’une frise commune avec une ligne par caméra pour le jour relu ; un clic sur une ligne lit cette caméra à cette heure. **Réglages** : détection, conservation et connexion de la caméra choisie. Les cartes de lecture, de recherche et de détection sont celles des versions précédentes, rangées autrement ; l’affichage classique garde sa page. Aucun changement côté serveur, de schéma ni de module figé. 308 tests Python et 112 JavaScript. [Guide et limites](docs/DESKTOP.md#surveillance).

## 0.8.0-alpha.28 — Recherche globale

La barre du bureau porte une **recherche**, ouverte aussi par Ctrl+K : quelques lettres suffisent pour ouvrir une application, un onglet, une caméra ou un espace de fichiers. Une vingtaine de réglages y sont nommés comme on les cherche (« fuseau horaire », « changer un mot de passe », « restaurer des fichiers »). Flèches et Entrée au clavier, Échap pour fermer. La recherche ne propose que ce que le compte peut ouvrir, ne modifie rien et ne cherche pas dans le contenu ni les noms des fichiers. Aucun changement côté serveur, de schéma ni de module figé. 308 tests Python et 107 JavaScript. [Guide et limites](docs/DESKTOP.md#recherche-globale).

## 0.8.0-alpha.27 — Centre de notifications

La barre du bureau porte une **cloche** : le nombre d’alertes à traiter, et à côté le nombre de tâches en cours. Elle ouvre un panneau unique, depuis n’importe quelle application : alertes avec leur bouton « Prendre en compte » et un accès direct à la page concernée, tâches en cours avec leur progression, puis les faits des dernières vingt-quatre heures (tâches terminées, échecs, retours à la normale). Une tâche vue en cours est annoncée quand elle se termine, où que l’on soit dans la console. Un compte en lecture seule voit les tâches, pas les alertes. L’affichage classique garde son bouton d’alertes. Aucun changement côté serveur, de schéma ni de module figé. 308 tests Python et 103 JavaScript. [Guide et limites](docs/DESKTOP.md#centre-de-notifications).

## 0.8.0-alpha.26 — Le Bureau

La console s’ouvre désormais sur un **bureau** : sept applications nommées par usage (Fichiers, Surveillance, Stockage, Protection, Partages et comptes, Réglages, Activité) à la place des treize rubriques du menu, un dock, et des widgets qui reprennent la vue d’ensemble. Une application s’ouvre dans une fenêtre que l’on déplace, agrandit, réduit ou ferme ; ses pages en sont les onglets, sans leur grand en-tête. Sur téléphone, l’application occupe l’écran et le dock devient la barre du bas. Les pages elles-mêmes ne changent pas. Le bouton **Classique** de la barre supérieure rend l’ancien menu, et **Bureau** y ramène ; le choix est mémorisé par navigateur. Aucun changement côté serveur, de schéma ni de module figé. 308 tests Python et 98 JavaScript. [Guide et limites](docs/DESKTOP.md).

## 0.8.0-alpha.25 — Fuseau horaire proposé au premier accès

Une installation dont le fuseau n’a jamais été choisi affichait toutes ses heures en UTC sans le dire. Tant que c’est le cas, un bandeau le signale aux administrateurs en haut de chaque page, avec l’heure de Nacre et celle du navigateur. Un clic adopte le fuseau du navigateur, ouvre le Panneau de configuration pour en choisir un autre, ou confirme UTC ; le choix est enregistré, inscrit au journal, et le bandeau ne revient pas. Le champ de fuseau du Panneau de configuration et de l’assistant propose la liste des fuseaux connus du serveur et affiche l’heure correspondante pendant la saisie. Un nom que le navigateur ne sait pas afficher est refusé avant l’enregistrement, et s’il est déjà en place l’affichage retombe sur UTC au lieu d’échouer. Aucun changement de schéma ni de module figé. 308 tests Python et 93 JavaScript. [Guide et limites](docs/CONTROL-PANEL.md#fuseau-horaire-au-premier-accès).

## 0.8.0-alpha.24 — Purge des copies de mise à jour

La page **Mises à jour** liste les **copies de retour arrière** : version copiée, date, version installée ensuite, taille, et place totale occupée sur le NAS. Nacre conserve les trois copies les plus récentes et supprime les plus anciennes au démarrage de la console, donc après chaque mise à jour réussie ; un paquet vérifié puis remplacé et un import interrompu sont effacés de la même façon. Un administrateur peut supprimer une copie ancienne après confirmation ; celle de la dernière mise à jour reste protégée. Rien n’est modifié pendant qu’une mise à jour est engagée, et les suppressions sont inscrites au journal. Module séparé du superviseur : aucun changement de schéma ni de module figé. 305 tests Python et 86 JavaScript. [Guide et limites](docs/BROWSER-UPDATES.md#copies-de-retour-arrière).

## 0.8.0-alpha.23 — Recherche d’événements sur plusieurs jours

La fiche d’une caméra comporte une carte **Recherche d’événements** : une période de jours, puis les événements Frigate de cette période en vignettes, du plus récent au plus ancien, regroupés par jour avec leur nombre. Un filtre par type d’objet porte sur toute la période ; les résultats se chargent par pages de soixante. Un clic ouvre le jour de l’événement dans la **Relecture** et lance la lecture cinq secondes avant. Un événement dont la vidéo n’est plus conservée reste visible et l’indique. Lecture seule de Frigate ; aucun changement de schéma ni de module figé. 299 tests Python et 84 JavaScript. [Guide et limites](docs/RECORDING-PLAYBACK.md#rechercher-sur-plusieurs-jours).

## 0.8.0-alpha.22 — Détection et objets suivis par caméra

La fiche d’une caméra comporte une carte **Détection** : état appliqué par Frigate et types d’objets suivis. Un administrateur active ou met en pause la détection et choisit les types parmi ceux que le modèle installé sait reconnaître (personnes, véhicules, animaux, objets). Le réglage est validé par Frigate, enregistré par Nacre avec copie de la configuration précédente, puis appliqué sans redémarrer le service vidéo : l’enregistrement continue. Nacre ne confirme qu’un réglage relu dans l’état de Frigate. Donne son utilité au filtre par type de la relecture. Aucun changement de schéma ni de module figé. 293 tests Python et 80 JavaScript. [Guide et limites](docs/CAMERA-DETECTION.md).

## 0.8.0-alpha.21 — Événements en vignettes dans la relecture

La carte **Relecture** d’une caméra présente les événements Frigate du jour choisi sous forme de vignettes : type d’objet, heure, durée et score. Un clic lance la lecture cinq secondes avant l’événement. Quand plusieurs types sont présents, un filtre par type d’objet masque les autres vignettes et repère les événements retenus sur la frise, sans interrompre la lecture en cours. Une vignette dont la vidéo n’est plus conservée reste visible et l’indique. Si le service ne fournit pas les événements, la frise et les moments détectés restent utilisables. Lecture seule de Frigate ; aucun changement de schéma ni de module figé. 285 tests Python et 77 JavaScript. [Guide et limites](docs/RECORDING-PLAYBACK.md).

## 0.8.0-alpha.20 — Relecture des enregistrements par jour

La fiche d’une caméra présente chaque jour conservé sur une frise de minuit à minuit, dans le fuseau du NAS : plages enregistrées, présence détectée par Frigate, périodes sans enregistrement et heures à venir. Lecture depuis un clic, une heure saisie ou un moment détecté ; extraits de cinq minutes enchaînés, retour de cinq minutes et téléchargement inscrit au journal. Un instant sans enregistrement renvoie à la plage suivante avec une explication. Lecture seule de l’inventaire Frigate, jours de 23 et 25 heures pris en compte, extraits accessibles sur toute la conservation réglable. La liste des derniers segments est remplacée. 282 tests Python et 74 JavaScript. [Guide et limites](docs/RECORDING-PLAYBACK.md).

## 0.8.0-alpha.19 — Mises à jour signées depuis le navigateur

Import et vérification d’un paquet signé, confirmation, suivi après reconnexion et superviseur indépendant. Copie préalable du code et de SQLite ; retour automatique si le contrôle de démarrage échoue, y compris après interruption du superviseur. Code, schéma et modules critiques vérifiés ; accès de maintenance pendant la validation. Paquets de code sans migration, service natif ni remplacement Samba/Frigate. [Parcours, preuves et limites](docs/BROWSER-UPDATES.md).

## 0.8.0-alpha.18 — Panneau de configuration du NAS

Point d’entrée pour l’administration quotidienne : identité et fuseau de la console, accès regroupés au stockage, aux partages, à la protection et à l’exploitation. Préférences versionnées contre les écrasements entre onglets. Décompte des sessions valides et révocation ciblée avec maintien de la session courante, sans changement des comptes SMB. 262 tests Python et 60 JavaScript. [Guide et parcours illustré](docs/CONTROL-PANEL.md).

## 0.8.0-alpha.17 — Préserver les communications Frigate après une déconnexion

Image Frigate dérivée de bases épinglées, avec correction ciblée de la course entre le contrôle WebSocket et l’envoi. Une fermeture ne tue plus le lecteur IPC dans le scénario reproduit ; les autres erreurs restent visibles. Construction intégrée au navigateur et aux reprises, refus d’un source amont inattendu. 254 tests Python, 53 JavaScript et cinq tests du moteur réel sur chaque architecture. [Cause, reproduction et limites](docs/FRIGATE-WEBSOCKET.md).

## 0.8.0-alpha.16 — Détecter les mesures vidéo figées

249 tests Python et 53 JavaScript réussis. Le débit positif ne suffit plus : l’état des caméras et les alertes vérifient l’horodatage Frigate. Mesures de plus de 90 secondes signalées comme périmées, horodatage absent ou incohérent inconnu. Contrôle du direct toutes les 15 secondes, retrait de l’image en cas de perte de confirmation et reprise explicite par Actualiser. [Diagnostic et limites](docs/VIDEO-FRESHNESS.md).

## 0.8.0-alpha.15 — Vue d’ensemble des caméras

246 tests Python et 50 JavaScript réussis. Inventaire multi-caméra avec réception mesurée, débit nul, pause et état inconnu distincts. Vue sans flux vidéo, ouverture explicite d’un seul direct, retour à la liste et protection contre les réponses tardives. Aucun changement de connexion, d’enregistrement ou de conservation. [Guide](docs/CAMERA-OVERVIEW.md).

## 0.8.0-alpha.14 — Aperçu des prochaines ouvertures

Aperçu en lecture seule des ouvertures de nettoyage sur les sept prochains jours depuis le formulaire, avec fuseau, exceptions, intervalles réunis et changements d’heure. Les résultats tardifs sont écartés après modification ou navigation ; aucun enregistrement, nettoyage ou activation.

242 tests Python et 43 JavaScript réussis. Déploiement de la version alpha.13 sur Spark avec copie privée de retour arrière et contrôles de continuité. [Aperçu du calendrier](docs/OPENING-PREVIEW.md) et [déploiement](docs/SPARK-DEPLOYMENT.md).

## 0.8.0-alpha.13 — Plusieurs plages et exceptions datées

Plages supplémentaires en mode quotidien ou hebdomadaire, ajout et retrait depuis le navigateur. Exceptions par date civile : aucun démarrage ou horaires de remplacement, prioritaires sur toute la journée et sur la continuation de la veille. Résumé des horaires et exceptions avant activation, paramètres figés dans la simulation et anciennes règles compatibles.

236 tests Python et 40 JavaScript réussis. Tests isolés des intervalles, dates, priorité, changements d’heure et reports ; nettoyage réel puis restauration exacte. [Guide et capture](docs/DATE-EXCEPTIONS.md).

## 0.8.0-alpha.12 — Créneaux par jour de la semaine

Choix entre une plage quotidienne et des horaires indépendants pour chaque jour sélectionné. Les plages nocturnes appartiennent au jour de départ, y compris du dimanche au lundi ; leurs recouvrements sont réunis. Anciennes règles quotidiennes conservées, jours et horaires figés par la simulation, résumé explicite avant activation et rechargement lors du changement de dépôt.

227 tests Python et 34 JavaScript réussis. Correction complémentaire : une réponse tardive de Snapshots ne remplace plus le formulaire de rétention après navigation. Tests isolés des jours locaux, frontières, changements d’heure, report persistant et restauration exacte après nettoyage réel. [Guide et capture](docs/WEEKLY-WINDOWS.md).

## 0.8.0-alpha.11 — Créneau du nettoyage automatique

Créneau quotidien par dépôt, dans le fuseau de la règle, y compris à cheval sur minuit. Captures en attente regroupées, démarrage revalidé après attente et juste avant la première suppression. Report persistant sans effet sur les points, reprise sans doublon et suivi dans le navigateur. Une opération commencée termine son contrôle même après la fermeture du créneau. Applications ponctuelles immédiates explicitement distinguées.

219 tests Python et 29 JavaScript réussis. Tests isolés sur limites horaires, changements d’heure, report, reprise, regroupement et restauration exacte après nettoyage réel. [Guide et preuve navigateur](docs/MAINTENANCE-WINDOW.md).

## 0.8.0-alpha.10 — Conservation par jour, semaine et mois

Règles calendaires combinables avec les derniers points, pour une application ponctuelle ou automatique. Dernier point de chaque période contenant une capture réussie, semaines ISO et fuseau explicite attaché à la règle. Motifs de conservation affichés dans la simulation. Les règles existantes gardent leur comportement ; catégories calendaires désactivées par défaut.

209 tests Python et 26 JavaScript. Essais sur dates synthétiques et dépôts chiffrés isolés : union des protections, frontières de jour et d’année, changement d’heure, conservation automatique et restauration d’une version historique. [Fonctionnement et preuves](docs/CALENDAR-RETENTION.md).

## 0.8.0-alpha.9 — Reprendre un nettoyage interrompu

Simulation persistante du nettoyage seul depuis le navigateur, confirmation à usage unique valable quinze minutes et revalidation du dépôt et des points. Aucun `forget` dans ce parcours : les snapshots présents sont conservés, puis la structure est contrôlée. Interruption signalée sans rejeu ; une règle suspendue reste suspendue. Historique rafraîchi sans écraser les formulaires.

200 tests Python et 23 JavaScript. Essais sur dépôts chiffrés isolés : interruption après suppression, simulation, nettoyage, contrôle intégral des données et restauration exacte. [Guide, preuve web et limites](docs/REPOSITORY-CLEANUP.md).

## 0.8.0-alpha.8 — Rétention après les sauvegardes réussies

Règle par dépôt activable depuis une simulation : après les prochaines captures réussies, sélection recalculée et nettoyage automatique par tâche persistante. Version de règle et identité du dépôt revalidées, doublons évités, désactivation des tâches en attente et suspension après incident. Alerte locale et réactivation après simulation ; règles et confirmations neutralisées lors d’une reprise de base ou de NAS. Aucun automatisme activé par défaut.

193 tests Python et 20 JavaScript. Banc web isolé avec redémarrage réel de console, nouvelle capture, nettoyage automatique unique et restauration exacte du fichier conservé. [Fonctionnement, preuves et limites](docs/AUTOMATIC-RETENTION.md).

## 0.8.0-alpha.7 — Rétention des sauvegardes depuis le navigateur

Depuis Snapshots, simulation des derniers points réussis à conserver par groupe, détail des suppressions et confirmation à usage unique. Protection des captures partielles/importées ou sans preuve locale de réussite, revalidation du dépôt et des points avant exécution. Tâche persistante de suppression, nettoyage restic et contrôle de structure ; une interruption est signalée sans rejeu automatique. Aucune rétention automatique activée.

180 tests Python et 18 JavaScript. Essais sur dépôts chiffrés temporaires, contrôle des données restic et restauration du fichier conservé. [Guide et limites](docs/BACKUP-RETENTION.md).

## 0.8.0-alpha.6 — Emails SMTP depuis le navigateur

Destination Email SMTP avec STARTTLS ou TLS direct obligatoire, compte facultatif pour relais autorisé, un expéditeur et un destinataire. Mot de passe conservé sans réaffichage, changement de serveur protégé, test et historique existants réutilisés. Le Message-ID reste stable lors des reprises ; une rupture de QUIT après DATA accepté conserve le succès.

170 tests Python et 16 JavaScript. Récepteur SMTP isolé chiffré, erreur 451, redémarrage réel et reprise avec même Message-ID, puis résolution. Aucun fournisseur ni boîte Internet utilisés. [Guide et captures](docs/SMTP-NOTIFICATIONS.md).

## 0.8.0-alpha.5 — Notifications externes configurables

Destination ntfy ou webhook JSON réglable depuis Alertes → Notifications : test manuel, activation, gravité minimale, retours à la normale et historique des livraisons. File transactionnelle persistante, tentatives espacées, relance explicite et protection des secrets. HTTPS vérifié ; redirections refusées. Les envois restent désactivés par défaut.

161 tests Python et 14 JavaScript. Récepteur isolé, erreur 503 puis reprise après redémarrage réel, identité conservée et résolution livrée dans l’ordre. Tests TLS locaux et formats ntfy/JSON ; aucun push réel ni service Internet sollicité. [Guide et captures](docs/EXTERNAL-NOTIFICATIONS.md).

## 0.8.0-alpha.4 — Alertes locales persistantes

Centre Alertes administrateur et compteur global : services connus indisponibles, caméra activée sans flux, dernières sauvegardes échouées ou incomplètes et volume de Nacre presque plein. Confirmation temporelle, prise en compte versionnée, récidive et historique des retours à la normale. Les contrôles inconnus ne résolvent pas les incidents ; aucune notification extérieure ni correction automatique.

146 tests Python et 11 JavaScript. Parcours navigateur sur sources simulées, prise en compte conservée après redémarrage réel de la console, puis résolutions enregistrées par le collecteur périodique. [Guide, captures et limites](docs/LOCAL-ALERTS.md).

## 0.8.0-alpha.3 — Préparation Ubuntu et service persistant

Plan puis préparation explicite des prérequis Ubuntu 24.04 : paquets de la distribution, accès Docker et maintien du gestionnaire utilisateur. Les distributions Docker externes sont conservées avec un refus avant modification. `installer.py --service` installe et démarre Nacre sans sudo, avec port local configurable, validation de l’unité et restitution après échec.

Banc ARM64 vierge : deux redémarrages, console active avant SSH, installation Samba depuis le navigateur via une tâche systemd, fichier relu après redémarrage avec empreinte identique. 136 tests Python et 9 JavaScript. [Parcours et limites](docs/HOST-BOOTSTRAP.md).

## 0.8.0-alpha.2 — Installation web sur Linux neuf

Samba et Frigate installés réellement par le navigateur dans une VM Ubuntu 24.04 ARM64 vierge, puis relancés avec conservation d’un fichier témoin. Lecture/écriture SMB3 vérifiée, écriture vidéo refusée, Frigate sain et API disponible. Docker reste un prérequis préparé sur Linux.

Le déploiement attend la réponse du démon Samba avant d’appliquer les partages. Le suivi nomme chaque composant et distingue le démarrage de Frigate d’un état sain ou dégradé. 129 tests Python et 9 JavaScript. [Parcours, capture et protocole](docs/FRESH-WEB-INSTALL.md).

## 0.8.0-alpha.1 — Composants et caméras dans le navigateur

Installation applicative de restic, Samba et Frigate par tâches persistantes. Ajout et correction de connexions Tapo/RTSP, ONVIF optionnel et sélection de caméra pour direct, clips et PTZ. Configuration validée par Frigate avant publication, copie privée préalable et erreurs explicites après redémarrage non confirmé. Docker et service natif restent des préparations Linux séparées.

Correction d’une soumission native GET lorsque le champ caméra `id` masquait l’identifiant du formulaire ; les formulaires sensibles utilisent désormais POST et le gestionnaire lit l’attribut DOM. 126 tests Python et 8 JavaScript ; restic installé réellement sur banc local et configurations validées par Frigate ARM64 isolé. [Guide, preuves et limites](docs/COMPONENTS-CAMERAS.md).

## 0.7.0-alpha.5 — Première configuration depuis le navigateur

Une commande prépare et ouvre la console sans Docker obligatoire. L’assistant authentifié sécurise le compte provisoire, présente les capacités accessibles et enregistre le nom du NAS et son fuseau. Le tableau de bord reste utilisable sans les services Docker. Les composants supplémentaires se configurent séparément.

Migration de base 1 → 2 avec copie préalable ; comptes existants conservés, assistant facultatif après mise à jour. 113 tests Python et 7 JavaScript ; parcours Chrome et affichage mobile vérifiés sur une instance isolée. [Guide et capture](docs/FIRST-RUN.md).

## 0.7.0-alpha.4 — Coupures pendant les écritures

Un dépôt web n’est confirmé qu’après synchronisation du fichier et de son nom sur le volume. Un échec avant publication ne laisse pas de nom final ; un échec de synchronisation du dossier conserve le fichier complet sans réponse de succès et sans écrasement lors d’une nouvelle tentative.

Banc ARM64 de trois coupures QEMU pendant reconstruction et écritures HTTP/locales/SMB avec FLUSH explicite. Les confirmations sont synchronisées dans un journal externe à la VM, puis toutes leurs empreintes sont contrôlées à chaque reprise. Un dépôt HTTP à moitié reçu doit rester non publié. 107 tests Python et 5 JavaScript ; protocole et résultats dans [la recette dédiée](docs/ACTIVE-WRITES-POWER-CUT.md). La perte des caches physiques reste hors qualification.

## 0.7.0-alpha.3 — Écritures en reconstruction et reprise caméra ARM64

Les volumes RAID1 vérifiés restent disponibles par HTTP et Samba pendant la reconstruction, y compris la transition MD `write-pending` observée à l’arrivée des écritures. Un état incertain, un membre inattendu et les restrictions de lecture seule conservent leurs contrôles.

La capture hors ligne prend en charge les fichiers privés root de Frigate, sans modifier leurs permissions. Le kit vidéo de format 2 archive et vérifie sa configuration ; sa préparation conserve les UID/GID et modes via un conteneur auxiliaire jamais démarré. Les kits de format 1 restent lisibles. La racine de chaque volume récupéré retrouve aussi ses propriétaires et permissions : les comptes Samba secondaires ne sont plus bloqués par le `0700` du dossier temporaire.

Recette ARM64 : 72 fichiers écrits pendant la reconstruction et contrôlés après redémarrage ; vraie caméra, capture chiffrée et reprise sur une VM vierge avec lecture des anciennes vidéos et nouveaux enregistrements. 104 tests Python et 5 JavaScript. Les coupures pendant des écritures actives et les caches matériels restent hors qualification. Voir [la recette complète](docs/CONCURRENT-IO-CAMERA.md).

## 0.7.0-alpha.2 — Coupure en reconstruction et reprise ARM64

Correction d’une reconstruction suspendue après coupure lorsque Linux réassemble le miroir en `read-auto`. Au démarrage, le helper ne réactive que l’opération déjà journalisée, avec les deux membres attendus et le montage vérifiés ; aucun nouvel ajout ni assemblage forcé. Un état MD explicitement `readonly` reste respecté.

Banc de trois arrêts brutaux QEMU pendant reconstruction, audit des commandes mdadm, contrôle des UUID, fichier de 64 Mio et snapshot antérieur. Reprise ARM64 sur une seconde VM vierge après arrêt de la source : données, clés, comptes web/Samba, SID, nouveau pool et contrôles après redémarrage. 94 tests Python et 5 JavaScript ; limites de la simulation de coupure documentées.

## 0.7.0-alpha.1 — Linux neuf et reconstruction RAID1

Reprise qualifiée sur Ubuntu vierge : données, clés historiques, comptes web/Samba, nouveau miroir Btrfs, raccordement des partages et redémarrage. Ajout du parcours navigateur de remplacement d’un membre RAID1 absent, avec disque vierge explicitement autorisé, plan à usage unique, journal préalable et vérification des deux membres synchronisés. Aucun rejeu automatique après interruption ; validation distincte du catalogue en cas de résultat ambigu.

Correction des droits du dossier parent des restitutions Btrfs nouvellement créé sous le service root. 90 tests Python et 5 JavaScript ; bancs privilégiés réservés à QEMU. La reconstruction préserve les données, un snapshot antérieur et la signature de l’ancien membre. Linux neuf ARM64, autres géométries RAID et perte électrique pendant reconstruction restent à qualifier.

## 0.6.0-alpha.3 — Connexion Chrome et sessions

Un cookie d’une autre application locale pouvait empêcher la reconnaissance du cookie Nacre après un mot de passe accepté. Lecture ciblée du jeton Nacre, avec refus des doublons et des formats invalides. L’interface vérifie la session avant d’ouvrir l’espace, conserve l’écran de connexion en cas d’expiration et ignore les réponses d’une ancienne session ; l’erreur `Cannot set properties of null` ne masque plus la cause initiale.

84 tests Python et 5 tests JavaScript, dont cookies tiers, expiration pendant navigation, réponse différée et cookie non transmis. Connexion rétablie dans Chrome avec la session existante, sans changement de mot de passe ni suppression des cookies tiers.


## 0.6.0-alpha.2 — Reprise d’installation, clés et Samba

Capture hors ligne chiffrée des données et de la configuration, avec clés restic, image et état persistant Samba. Préparation dans une nouvelle racine, UID conservés, sessions révoquées, plans désactivés et dépôts détachés jusqu’à vérification de leur identité. Import Samba dans un volume distinct, avec SID, mots de passe secondaires et comptes désactivés conservés. Export administratif du catalogue natif et reprise des fichiers externes vers des dossiers ordinaires.

État et aide dans Snapshots ; procédure complète illustrée. 82 tests ordinaires et reprise rejouée dans QEMU, y compris connexion HTTP avec l’ancien compte et recréation du conteneur Samba. Parcours actuel : même architecture et UID/GID principal, dépôt monté localement. La reconstruction de Linux, des pools et des snapshots natifs reste distincte.


## 0.6.0-alpha.1 — 2026-11-09

Première étape de fiabilité : schéma SQLite versionné, migration atomique et copie préalable cohérente vérifiée. Refus d’un schéma futur. Outil de préparation hors ligne d’une base récupérée, sans écrasement, avec révocation des sessions et désactivation des plans. État et aide disponibles dans Snapshots. Correction du bouton de restauration des snapshots, désactivé à tort en 0.5.

70 tests ordinaires ; arrêt brutal et reprise testés en VM, puis connexion HTTP à une installation neuve avec le compte conservé. La reprise complète du NAS, des clés externes et du passdb Samba reste à développer ; l’issue #1 reste ouverte.

## 0.5 — 2026-11-09

Gestion des fichiers sur volumes natifs, corbeille par volume, partages SMB contrôlés, sources et destinations restic natives, restauration multivolume et refus après disparition d’un montage. 58 tests ordinaires, essais QEMU et contrôle sur ARM64.

### Mise en dépôt

Premier import Git du travail existant. Ajout du README illustré, vision, architecture, installation, feuille de route, règles de contribution, contrôle des secrets et CI. Les sections ci-dessous sont rétrospectives : aucun historique Git antérieur n’est inventé.

## 0.4 — historique de développement

Provisionnement de disques entiers ext4/Btrfs et miroir RAID1, montage catalogué, restauration LVM ext4/XFS et navigation dans les restaurations. 50 tests ordinaires au jalon.

## 0.3 — historique de développement

Helper natif optionnel, plans à confirmation, profils matériels et snapshots Btrfs/ZFS/LVM. Banc privilégié QEMU. 41 tests ordinaires au jalon.

## 0.2 — historique de développement

Inventaire portable, restic chiffré, plans automatiques désactivés par défaut, restauration privée et retrait des plafonds applicatifs de taille. 30 tests ordinaires au jalon.

## Socle initial — historique de développement

Console locale, authentification, fichiers, SMB, comptes, services, Frigate et pilotage PTZ d’une Tapo C530WS.
