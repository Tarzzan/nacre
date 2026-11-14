# Déploiements de la console sur Spark

## 14 novembre 2026 — alpha.51, alerte du volume vidéo

L’installation alpha.50 a reçu le paquet `nacre-0.8.0-alpha.51.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.51), construit depuis le commit [`b800419`](https://github.com/Tarzzan/nacre/commit/b8004198895f99727c0f368b6c966f26f5ba912b) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, aucun incident actif, répétition isolée alpha.50 → alpha.51 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 14 h 48 min 26 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté en lecture seule, en nombres seulement : la surveillance interroge désormais Frigate sur son volume à chaque passage (six lectures en quatre minutes) ; le domaine « stockage vidéo » est vérifié, aucun incident ouvert ni en attente, ce qui est attendu avec environ 68 jours d’autonomie. **L’ouverture de l’incident n’a pas été exercée ici** : il aurait fallu remplir le volume ou changer la durée de conservation, ce qui redémarre le service vidéo. Elle est prouvée sur mesures simulées.

## 14 novembre 2026 — alpha.50, passages conservés : liste à jour aussitôt

L’installation alpha.49 a reçu le paquet `nacre-0.8.0-alpha.50.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.50), construit depuis le commit [`edabf87`](https://github.com/Tarzzan/nacre/commit/edabf875173e4c9d6d0a92e48e3530c2be880dd5) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.49 → alpha.50 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 14 h 13 min 11 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté sur les données réelles, en nombres seulement, par le même essai qu’en alpha.49 : un extrait de dix secondes conservé à travers Nacre, prêt à la deuxième lecture de la liste pour 4,8 Mio, puis retiré ; **la liste lue aussitôt après le retrait est vide**, là où alpha.49 montrait encore le passage. Aucun passage n’est resté ; les deux gestes sont au journal. Aucune image n’a été affichée.

## 14 novembre 2026 — alpha.49, passages conservés et autonomie vidéo

L’installation alpha.48 a reçu le paquet `nacre-0.8.0-alpha.49.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.49), construit depuis le commit [`90bafaf`](https://github.com/Tarzzan/nacre/commit/90bafaf01dc64e3a4c72f5a2ab5c318153f3d782) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.48 → alpha.49 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 13 h 48 min 46 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté sur les données réelles, en nombres seulement. Stockage vidéo : état « espace suffisant », 2 789 Gio libres sur 3 755, débit de 40,9 Gio par jour, 41,7 Gio d’enregistrements, autonomie d’environ 68 jours, aucun passage conservé. Conservation, à travers Nacre : un extrait de dix secondes conservé avec un nom, copie prête en moins de deux secondes pour 5,6 Mio, relue par plage d’octets (réponse partielle, type vidéo), puis retirée ; les deux gestes sont au journal. Aucune image n’a été affichée.

**Défaut trouvé par cet essai** : le retrait était fait, mais la liste le montrait encore. Frigate garde ses réponses cinq secondes, ce que le banc ne simulait pas. Rien n’était gardé à tort ; corrigé en alpha.50.

## 14 novembre 2026 — alpha.48, poids des espaces

L’installation alpha.47 a reçu le paquet `nacre-0.8.0-alpha.48.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.48), construit depuis le commit [`1d9279e`](https://github.com/Tarzzan/nacre/commit/1d9279eaa4f120b3fb0f1a137ad57cb51103796b) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.47 → alpha.48 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 4 h 36 min 46 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté sur les données réelles, en nombres seulement : quatre espaces, aucun pesé avant ; l’espace Vidéos pesé en entier en 0,06 seconde ; sa pesée ensuite gardée, 40 Gio pour 11 722 éléments, complète ; les trois autres espaces toujours « non pesés ». Aucun nom de fichier n’a été relevé. Cette pesée gardée est le seul réglage écrit par le contrôle ; elle se remplace à la prochaine pesée de l’espace.

## 14 novembre 2026 — alpha.47, suite des événements

L’installation alpha.46 a reçu le paquet `nacre-0.8.0-alpha.47.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.47), construit depuis le commit [`7587cf8`](https://github.com/Tarzzan/nacre/commit/7587cf8470b46405a1b4ec7636a43749769ff6a6) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.46 → alpha.47 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 4 h 20 min 33 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté en lecture seule, en nombres seulement : 774 événements sur les sept derniers jours pour la caméra, 60 dans la première page et une suite annoncée, 60 dans la deuxième et une suite encore ; le script de l’onglet Événements servi porte le bouton de [suite](DESKTOP.md). Aucun événement ni vignette n’a été ouvert ou affiché, et le bouton lui-même n’a pas été actionné ici : son comportement est prouvé sur le banc.

## 14 novembre 2026 — alpha.46, restaurations natives « à vérifier » relues

L’installation alpha.45 a reçu le paquet `nacre-0.8.0-alpha.46.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.46), construit depuis le commit [`deb0895`](https://github.com/Tarzzan/nacre/commit/deb0895663929d02b5c1de0e68f95437ae710d6f) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.45 → alpha.46 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 4 h 12 min 17 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Cette installation n’a pas de service natif : la [relecture des restaurations](NATIVE-SNAPSHOT-POLICY.md#une-restauration-restée--à-vérifier-) n’y a rien à relire, et sa preuve vient du banc VM.

## 14 novembre 2026 — alpha.45, dossiers de données protégés

L’installation alpha.44 a reçu le paquet `nacre-0.8.0-alpha.45.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.45), construit depuis le commit [`f5f48de`](https://github.com/Tarzzan/nacre/commit/f5f48de246c56eb7798b81ce8db080082d76d6ac) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.44 → alpha.45 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 3 h 48 min 19 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

**Aucun geste de root n’a été fait sur cette machine** : ni agent de services, ni montage protégé, ni changement de groupe. Son compte pilote toujours Docker directement, ce que l’accueil rapporte. Constaté en lecture seule après la mise à jour : les deux services en marche, Docker et Compose détectés, une image de la caméra servie sans être conservée. La [migration](SERVICE-AGENT.md#migrer-une-installation-en-service-et-revenir-en-arrière) attend son propriétaire : la console y tourne sous un compte qui sert aussi à autre chose.

## 14 novembre 2026 — alpha.44, agent de services

L’installation alpha.43 a reçu le paquet `nacre-0.8.0-alpha.44.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.44), construit depuis le commit [`5681768`](https://github.com/Tarzzan/nacre/commit/5681768c01e3ac5edf24dde685ca4bbe70b8dff2) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.43 → alpha.44 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 3 h 31 min, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

**L’agent de services n’est pas installé sur cette machine**, et rien n’y a été fait en root : son compte pilote toujours Docker directement, ce que l’accueil rapporte (« accès direct »). Constaté en lecture seule après la mise à jour : les deux services en marche, Docker et Compose détectés, une image de la caméra servie sans être conservée. L’[installation de l’agent](SERVICE-AGENT.md#installer-lagent) ici relève de la migration, dernier lot de l’issue 2.

## 14 novembre 2026 — alpha.43, liste fermée des opérations Docker

L’installation alpha.42 a reçu le paquet `nacre-0.8.0-alpha.43.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.43), construit depuis le commit [`7069e9d`](https://github.com/Tarzzan/nacre/commit/7069e9d0b909f854aa424505905878d8c213ee31) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.42 → alpha.43 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**.

Validation enregistrée à 3 h 14 min 21 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Ici, la [liste fermée](SERVICE-AGENT.md) s’exerce sur un vrai Docker. Constaté en lecture seule après la mise à jour : l’état des services rend les deux conteneurs en marche (opération `status`) ; l’accueil trouve Docker et Compose (opération `engine`) ; une image de la caméra est servie, 200 et 157 Kio, sans être conservée (opération `video_address`). Aucune opération qui modifie les partages, les comptes ou les conteneurs n’a été lancée. Cette installation n’a pas d’agent de services : son compte pilote toujours Docker directement.

## 14 novembre 2026 — alpha.42, conservation automatique des points natifs

L’installation alpha.41 a reçu le paquet `nacre-0.8.0-alpha.42.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.42), construit depuis le commit [`4f2f873`](https://github.com/Tarzzan/nacre/commit/4f2f873a11970f3ff66a8448de3df4b7c3cc2b29) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.41 → alpha.42 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 2 h 32 min 18 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Cette installation n’a pas de service natif : la [conservation automatique](NATIVE-SNAPSHOT-POLICY.md#lot-4--conservation-automatique) n’y a rien à appliquer, et sa preuve sur de vrais volumes vient du banc VM, pas d’ici. Constaté dans le navigateur : la page Volumes et snapshots s’affiche comme avant, douze cartes, sans carte de conservation ni bouton « Automatique… » ; aucun réglage natif n’est enregistré.

## 14 novembre 2026 — alpha.41, suppression explicite des points natifs

L’installation alpha.40 a reçu le paquet `nacre-0.8.0-alpha.41.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.41), construit depuis le commit [`f555ef1`](https://github.com/Tarzzan/nacre/commit/f555ef1dc1b7ad690a82ec2b8bfaa0710f5aa7a4) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.40 → alpha.41 réussie. Fichier importé identique à celui de la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 2 h 03 min 39 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Cette installation n’a pas de service natif : la [suppression des points](NATIVE-SNAPSHOT-POLICY.md#lot-3--suppression-explicite) n’y a rien à supprimer, et sa preuve sur de vrais volumes vient du banc VM, pas d’ici. Constaté dans le navigateur : la page Volumes et snapshots s’affiche comme avant, douze cartes, sans les cartes de programmation et de conservation, donc sans aucun bouton de suppression.

## 13 novembre 2026 — alpha.40, programmation des captures natives

L’installation alpha.39 a reçu le paquet `nacre-0.8.0-alpha.40.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.40), construit depuis le commit [`5e40bd6`](https://github.com/Tarzzan/nacre/commit/5e40bd616d0a11c2d7286630e0fe10e9777dcfd8) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.39 → alpha.40 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 22 h 33 min 53 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Cette installation n’a pas de service natif : la [programmation des captures](NATIVE-SNAPSHOT-POLICY.md#lot-2--programmation-des-captures) n’y a rien à programmer, et sa preuve sur de vrais volumes vient du banc VM, pas d’ici. Constaté dans le navigateur : la page Volumes et snapshots s’affiche comme avant, sans les cartes de programmation et de conservation ; la liste des programmations répond « service non connecté, aucune programmation » ; aucun réglage natif n’est enregistré, aucune ligne du compte « programmation » au journal, aucune alerte de programmation.

## 13 novembre 2026 — alpha.39, conservation des points natifs

L’installation alpha.38 a reçu le paquet `nacre-0.8.0-alpha.39.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.39), construit depuis le commit [`d58349a`](https://github.com/Tarzzan/nacre/commit/d58349a1a973d1745dd13726ea202669d9fd6947) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.38 → alpha.39 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 21 h 49 min 04 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Cette installation n’a pas de service natif : la [conservation des points natifs](NATIVE-SNAPSHOT-POLICY.md) n’y a donc rien à montrer, et rien n’y est prouvé sur un vrai volume. Constaté dans le navigateur : la page Volumes et snapshots s’affiche comme avant, sans la carte de conservation ; la liste des règles répond « service non connecté, aucune règle » ; une simulation est refusée faute de service natif ; aucune règle n’a été enregistrée.

## 13 novembre 2026 — alpha.38, poids des dossiers

L’installation alpha.37 a reçu le paquet `nacre-0.8.0-alpha.38.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.38), construit depuis le commit [`2d1e600`](https://github.com/Tarzzan/nacre/commit/2d1e6007e0a139b9d581470ef4d3dfb218acd992) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.37 → alpha.38 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 21 h 25 min 09 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur, sur les fichiers réels et en lecture seule, pour le [poids des dossiers](DESKTOP.md#peser-les-dossiers) : l’espace Vidéos est pesé en entier, 3 dossiers pour 11 609 éléments et 41 Gio, en moins de 0,1 seconde, le plus lourd représentant 99 % du total ; lignes du plus lourd au plus léger, total égal à la somme des lignes ; les espaces vides répondent zéro ; un espace inconnu et un chemin hors espace sont refusés. Depuis la recherche globale, **Poids des dossiers** ouvre la pesée du dossier ouvert, et un double-clic pèse le sous-dossier. Seuls des nombres ont été relevés : aucun nom de fichier, aucun fichier ouvert.

## 13 novembre 2026 — alpha.37, recherche de fichiers par critères

L’installation alpha.36 a reçu le paquet `nacre-0.8.0-alpha.37.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.37), construit depuis le commit [`d652273`](https://github.com/Tarzzan/nacre/commit/d652273c5a789600e5d8da814b5fcd04e464be5f) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.36 → alpha.37 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 21 h 01 min 58 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur, sur les fichiers réels et en lecture seule, pour la [recherche par critères](DESKTOP.md#chercher-sans-nom-par-critères) dans tout le NAS : les plus gros fichiers d’abord, 200 affichés sur 11 289 correspondances, tailles décroissantes, aucun dossier ni lien, après un parcours entier de 11 468 éléments ; les plus récents d’abord, 200 sur 11 468, dates décroissantes, dossiers compris ; type Images, 200 sur 1 260 ; type Dossiers, 179 classés par date ; vidéos de plus de 1 Gio, aucune ; une demande sans nom ni critère et un classement inconnu sont refusés. Chaque réponse en 0,1 seconde environ. Le bouton **Par critères** puis **Étendre à tout le NAS** donnent les mêmes nombres dans la fenêtre Fichiers. Seuls des nombres ont été relevés : aucun nom de fichier, aucun fichier ouvert.

## 13 novembre 2026 — alpha.36, filtres de la recherche de fichiers

L’installation alpha.35 a reçu le paquet `nacre-0.8.0-alpha.36.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.36), construit depuis le commit [`afab96e`](https://github.com/Tarzzan/nacre/commit/afab96e0b21c838858206af4b76d43eaf85c3b62) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.35 → alpha.36 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 18 h 43 min 58 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur, sur les fichiers réels et en lecture seule, pour une même recherche par nom et ses [filtres](DESKTOP.md#affiner-les-résultats) : le type Images ne garde rien après un parcours entier de 11 611 éléments ; le type Vidéos garde 200 résultats, tous de cette famille et sans dossier ; avec « depuis 24 heures », 200 résultats tous modifiés dans ce délai, trouvés en allant plus loin dans le parcours (3 131 éléments vus au lieu de 1 472) ; avec « plus de 1 Mio », aucun résultat plus petit ; un type inconnu est refusé. Chaque réponse en moins de 0,1 seconde.

Limites de ce contrôle : seuls des nombres ont été relevés, aucun nom de fichier réel n’a été affiché ni conservé ; les listes de l’interface n’ont été manipulées que sur le banc, la recherche du serveur étant interrogée directement ici. Le fuseau de la console n’est toujours pas choisi.

## 13 novembre 2026 — alpha.35, période et tranche horaire dans l’onglet Événements

L’installation alpha.34 a reçu le paquet `nacre-0.8.0-alpha.35.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.35), construit depuis le commit [`5911dfd`](https://github.com/Tarzzan/nacre/commit/5911dfd2959fed339ae1acb4e5731e4250cc963a) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.34 → alpha.35 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 18 h 21 min 05 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur, dans l’[onglet Événements](DESKTOP.md#surveillance), sur les événements réels et en lecture seule : 752 événements sur sept jours par défaut ; 66 entre 22:00 et 06:00, les soixante listés ayant tous leur heure de début dans la tranche ; **Sept derniers jours** ramène aux 752.

Limites de ce contrôle : seuls des nombres et des heures ont été relevés, aucune capture d’écran n’a été prise et aucun événement n’a été ouvert. Une seule caméra réelle : l’addition sur plusieurs caméras n’a été vérifiée que sur le banc. Le fuseau de la console n’étant toujours pas choisi, les heures de cette installation restent en UTC.

## 13 novembre 2026 — alpha.34, recherche d’événements par tranche horaire

L’installation alpha.33 a reçu le paquet `nacre-0.8.0-alpha.34.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.34), construit depuis le commit [`2040ec2`](https://github.com/Tarzzan/nacre/commit/2040ec23219be36a9b869eea0213d55316509795) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.33 → alpha.34 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 17 h 47 min 50 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur, sur les événements réels de la caméra et en lecture seule : 732 événements sur sept jours, dont 66 [entre 22:00 et 06:00](RECORDING-PLAYBACK.md#ne-garder-quune-tranche-horaire) et 666 entre 06:00 et 22:00, soit le compte entier sans recouvrement ; les soixante premiers résultats de la nuit ont tous leur heure de début dans la tranche ; une tranche à moitié remplie est refusée.

Limites de ce contrôle : seuls des nombres et des heures ont été relevés, aucune vignette ni vidéo n’a été ouverte. Le fuseau de la console n’étant toujours pas choisi, ces heures sont en UTC sur cette installation : « 22:00 à 06:00 » y désigne 19 h à 3 h, heure de Guyane, tant que le fuseau n’est pas réglé. Le plafond de dix mille événements n’a été atteint que dans les essais.

## 13 novembre 2026 — alpha.33, recherche de fichiers par nom

L’installation alpha.32 a reçu le paquet `nacre-0.8.0-alpha.33.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.33), construit depuis le commit [`de7e615`](https://github.com/Tarzzan/nacre/commit/de7e615c98dc8cd1aa6ee5a406a4f78e51455c82) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.32 → alpha.33 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée depuis la fenêtre Réglages du bureau et suivie jusqu’à **Mise à jour réussie**, session conservée.

Validation enregistrée à 17 h 23 min 36 s, heure de Guyane ; la copie de retour arrière la plus ancienne a été purgée au démarrage. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur, sur les données réelles et en lecture seule : une [recherche par nom](DESKTOP.md#rechercher-un-fichier-par-son-nom) dans tout le NAS a parcouru 11 408 éléments en 0,15 seconde, en entier, sans espace écarté ; une recherche large s’est arrêtée à 200 résultats en l’annonçant ; le champ de Fichiers porte la recherche.

Limites de ce contrôle : seuls des nombres ont été relevés, aucun nom de fichier réel n’a été affiché ni conservé ; aucun résultat n’a été ouvert, prévisualisé ni téléchargé. Les bornes de durée et de volume n’ont été atteintes que sur le banc et dans les essais : cette installation est trop petite pour les approcher. Le fuseau de la console n’est toujours pas choisi.

## 13 novembre 2026 — alpha.32, bureau personnalisable

L’installation alpha.31 a reçu le paquet `nacre-0.8.0-alpha.32.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.32), construit depuis le commit [`46e4c40`](https://github.com/Tarzzan/nacre/commit/46e4c402b9122a8100e4316d216c9d9e8110282f) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.31 → alpha.32 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée.

Première mise à jour confirmée depuis une fenêtre du bureau : la page Mises à jour, ouverte dans la fenêtre Réglages, a suivi l’installation jusqu’à **Mise à jour réussie**, session conservée, et son bouton **Recharger Nacre** a rechargé le bureau entier.

Préparation enregistrée à 14 h 27 min 34 s, validation à 14 h 27 min 59 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur : le bouton et le panneau [Personnaliser](DESKTOP.md#personnaliser-le-bureau) sont présents ; les préférences lues sont celles d’origine.

Limites de ce contrôle : aucune préférence de bureau n’a été enregistrée sur cette installation, le choix étant laissé à son administrateur ; les réglages du panneau et la restauration des fenêtres n’ont été exercés que sur le banc. Le fuseau de la console n’est toujours pas choisi.

## 13 novembre 2026 — alpha.31, plusieurs fenêtres

L’installation alpha.30 a reçu le paquet `nacre-0.8.0-alpha.31.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.31), construit depuis le commit [`754d574`](https://github.com/Tarzzan/nacre/commit/754d574f9ecb8d53eab80119f84ae4431df5b20a) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.30 → alpha.31 réussie. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée et suivie dans le navigateur, session conservée.

Préparation enregistrée à 14 h 08 min 57 s, validation à 14 h 09 min 22 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur : [deux applications ouvertes ensemble](DESKTOP.md#plusieurs-fenêtres), Fichiers et Activité, chacune dans sa fenêtre avec ses données réelles ; la console annonce qu’elle n’accepte d’être encadrée que par elle-même (`frame-ancestors 'self'`, `SAMEORIGIN`).

Limites de ce contrôle : aucun réglage ni fichier n’a été modifié ; le déplacement et le redimensionnement des fenêtres n’ont été exercés que sur le banc.

## 13 novembre 2026 — alpha.30, gestionnaire de fichiers

L’installation alpha.29 a reçu le paquet `nacre-0.8.0-alpha.30.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.30), construit depuis le commit [`9674a31`](https://github.com/Tarzzan/nacre/commit/9674a312894f0a90703272760853b3a7a29901ff) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques, aucune tâche active, répétition isolée alpha.29 → alpha.30 réussie. Le tunnel local vers la console était tombé et a été rétabli avant l’import. Fichier importé téléchargé depuis la release, empreinte contrôlée ; session administrateur temporaire refermée ; installation confirmée et suivie dans le navigateur, session conservée.

Préparation enregistrée à 13 h 47 min 03 s, validation à 13 h 47 min 33 s, heure de Guyane. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configurations Samba et Frigate identiques avant et après ; conteneurs inchangés ; service systemd non relancé.

Constaté dans le navigateur : le [gestionnaire de fichiers](DESKTOP.md#fichiers) s’affiche sur les espaces réels, avec ses actions d’écriture pour l’administrateur ; les nouvelles routes répondent (archive sans sélection refusée, aperçu d’un fichier absent introuvable).

Limites de ce contrôle : aucun fichier réel n’a été ouvert, prévisualisé, déplacé, archivé ni téléchargé. Ces gestes n’ont été exercés que sur le banc et sur espace temporaire.

## 13 novembre 2026 — alpha.29, le Bureau

L’installation alpha.25 a reçu le paquet `nacre-0.8.0-alpha.29.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.29), construit depuis le commit [`2f6903f`](https://github.com/Tarzzan/nacre/commit/2f6903feb60d7632996ab9ee7da271fbc96c2269) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md). Cette mise à jour apporte d’un coup les quatre lots du [Bureau](DESKTOP.md), d’alpha.26 à alpha.29.

Avant l’import : neuf modules figés identiques entre l’installation et le paquet, aucune tâche active. La mise à jour alpha.25 → alpha.29 a été répétée sur une console et son superviseur en répertoire temporaire. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 12 h 18 min 10 s et la validation à 12 h 18 min 35 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configuration Samba et configuration Frigate identiques avant et après. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé. Trois copies de retour arrière restent après la purge automatique.

Constaté dans le navigateur après rechargement, sans capture d’image :

- Le bureau s’affiche : sept applications, dock, widgets alimentés par les mesures réelles (stockage, deux services en ligne, réception de la caméra), cloche sans alerte, recherche dans la barre.
- **Surveillance → Mur** : une tuile pour la caméra, dernière image reçue, aucun direct ouvert.
- **Événements** : soixante événements du jour, tous du type suivi.
- **Relecture** : la carte du jour ; pas de frise commune, l’installation n’ayant qu’une caméra.
- **Réglages** : détection active, type suivi et conservation relus.

Limites de ce contrôle : aucun clic n’a modifié l’installation. L’agrandissement d’une caméra, la prise en compte d’une alerte et la frise commune n’ont été exercés que sur le banc. Le fuseau n’étant toujours pas choisi, son bandeau reste affiché et les heures restent en UTC. Aucune panne n’a été injectée.

## 13 novembre 2026 — alpha.25

L’installation alpha.24 a reçu le paquet `nacre-0.8.0-alpha.25.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.25), construit depuis le commit [`9088038`](https://github.com/Tarzzan/nacre/commit/9088038d9602b6190d87e4e6be2378ec2d244bf2), par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Validation du commit : les quatorze contrôles de la PR 53 sont verts sur x86-64 et ARM64, et le commit fusionné a exactement le même arbre de fichiers que le commit contrôlé. La CI de `main` n’a pas tourné sur ce commit : GitHub a refusé de démarrer les tâches pour une raison de facturation du compte. Aucun test n’a échoué ; la suite complète a aussi été rejouée localement sur ce code (308 tests).

Avant la fusion, le nouveau module de préférences a été exécuté en lecture seule sur la base réelle de Spark, sans rien y installer ni y écrire : console reconnue comme jamais réglée (aucune préférence enregistrée), 449 fuseaux proposés, noms techniques refusés. Le fuseau système de Spark a été relevé au passage : il ne correspond pas au lieu, ce qui a écarté l’idée de s’en servir comme proposition.

Avant l’import : neuf modules figés identiques entre Spark et le paquet, aucune tâche active. La mise à jour alpha.24 → alpha.25 a été répétée sur une console et son superviseur en répertoire temporaire, sans préférences enregistrées comme sur Spark : fuseau proposé après la mise à jour, nom technique refusé, choix enregistré, second onglet refusé. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 11 h 08 min 47 s et la validation à 11 h 09 min 11 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configuration Samba et configuration Frigate identiques avant et après. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé.

Constaté dans le navigateur après rechargement :

- Le [bandeau du fuseau](CONTROL-PANEL.md#fuseau-horaire-au-premier-accès) s’affiche en haut de chaque page et propose le fuseau du navigateur, America/Cayenne, avec les deux heures côte à côte.
- La purge des copies s’est appliquée une seconde fois d’elle-même : la copie d’alpha.21 a été supprimée et inscrite au journal, trois copies restent.

Limites de ce contrôle : aucun des trois boutons du bandeau n’a été cliqué sur Spark. Le choix du fuseau est laissé à l’administrateur ; il a été exercé sur le banc et dans la répétition isolée. Tant qu’il n’est pas fait, les heures de Spark restent en UTC. Aucune panne n’a été injectée sur Spark.

## 12 novembre 2026 — alpha.24

L’installation alpha.23 a reçu le paquet `nacre-0.8.0-alpha.24.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.24), construit depuis le commit [`6ea9e74`](https://github.com/Tarzzan/nacre/commit/6ea9e74c8a8f26268bb9fb879c5eecd87b9d2cda) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant la fusion, l’inventaire des copies a été exécuté en lecture seule sur le répertoire réel des mises à jour de Spark, sans rien y installer ni y écrire : quatre copies décrites avec leurs versions, dates et tailles, 5,3 Mo au total.

Avant l’import : neuf modules figés identiques entre Spark et le paquet, aucune tâche active. La mise à jour alpha.23 → alpha.24 a été répétée sur une console et son superviseur en répertoire temporaire, avec quatre copies fictives déjà présentes : trois dossiers après la mise à jour, deux anciennes copies supprimées et inscrites au journal, copie courante refusée à la suppression. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 21 h 24 min 35 s et la validation à 21 h 24 min 57 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configuration Samba et configuration Frigate identiques avant et après. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé. Samba a répondu à `smbcontrol smbd ping` ; les journaux de Frigate ne comptent aucune erreur sur les vingt minutes encadrant la mise à jour.

La [purge des copies](BROWSER-UPDATES.md#copies-de-retour-arrière) s’est appliquée d’elle-même au démarrage de la nouvelle console, à 21 h 24 min 57 s :

- Cinq copies existaient après l’installation : celles prises avant alpha.20, alpha.21, alpha.22, alpha.23 et alpha.24.
- Les deux plus anciennes ont été supprimées. Le journal de la console porte une ligne « Anciennes copies de mise à jour supprimées » qui nomme les versions alpha.19 et alpha.20.
- Trois copies restent : alpha.23 (dernière mise à jour, sans bouton de suppression), alpha.22 et alpha.21. Le répertoire des mises à jour occupe 4,1 Mo, superviseur compris.
- Le superviseur, sa clé de vérification, son inventaire et ses verrous sont intacts ; l’installation suivante reste possible.
- La page **Mises à jour** affiche ces trois copies avec leurs dates et tailles.

Limites de ce contrôle : la suppression manuelle d’une copie n’a pas été déclenchée sur Spark ; elle l’a été sur le banc et dans la répétition isolée. Les copies de Spark n’ont pas servi à une reprise. Les dates de la carte sont en UTC, le fuseau de la console n’étant toujours pas réglé. Aucune panne n’a été injectée sur Spark.

## 12 novembre 2026 — alpha.23

L’installation alpha.22 a reçu le paquet `nacre-0.8.0-alpha.23.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.23), construit depuis le commit [`6578550`](https://github.com/Tarzzan/nacre/commit/65785505d7dfd79a48edb0b3a9d6460e6fcf1408) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant la fusion, le code de recherche a été exécuté en lecture seule contre les événements réels de Spark, sans rien y installer ni y écrire : 527 événements lus en neuf pages. Cet essai a montré que deux objets vus sur la même image partagent leur instant de début (quatre cas sur cette caméra) et qu’un événement pouvait être sauté entre deux pages ; le défaut a été corrigé et couvert par un test avant la fusion.

Avant l’import : neuf modules figés identiques entre Spark et le paquet, aucune tâche active, répétition de la mise à jour alpha.22 → alpha.23 sur une console et son superviseur en répertoire temporaire. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 19 h 25 min 41 s et la validation à 19 h 26 min 15 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configuration Samba et configuration Frigate identiques avant et après. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé. Samba a répondu à `smbcontrol smbd ping` ; les journaux de Frigate ne comptent aucune erreur sur les quarante minutes encadrant la mise à jour.

La [recherche d’événements](RECORDING-PLAYBACK.md#rechercher-sur-plusieurs-jours) a ensuite été contrôlée sur la caméra réelle, depuis le navigateur :

- Période proposée : les sept derniers jours. Aucune requête de recherche avant le clic.
- 532 événements sur quatre jours (142, 115, 183 et 92), lus en neuf pages : 532 vignettes distinctes, aucun doublon ni manque par rapport aux compteurs par jour.
- Deux types présents : le filtre **Enregistrement manuel** réduit la liste à son seul événement, du 9 novembre ; **Personne** en garde 532 sur 533, un événement étant survenu entre-temps.
- Recherche réduite à une seule journée : 92 événements annoncés pour le 9 novembre.
- Un résultat du 9 novembre a ouvert ce jour dans la relecture, alors réglée sur le 12, et la lecture a démarré cinq secondes avant l’événement, sans erreur. Les résultats sont restés affichés.

Limites de ce contrôle : sur cette installation, toutes les heures portant un événement gardent encore de la vidéo. L’indication **Vidéo non conservée** et le message d’un passage disparu n’ont donc été observés que sur le banc simulé. Le plafond de comptage (dix mille événements) n’est pas atteignable ici. Frigate ne suivant que les personnes, le filtre n’a que deux types à proposer. Aucune image de surveillance n’a été capturée ni publiée.

Les copies de retour arrière occupent 6,1 Mo pour quatre mises à jour dans `state/console/updates/`, toujours sans purge automatique. Le fuseau de la console n’est toujours pas réglé (heures UTC). Aucune panne n’a été injectée sur Spark.

## 12 novembre 2026 — alpha.22

L’installation alpha.21 a reçu le paquet `nacre-0.8.0-alpha.22.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.22), construit depuis le commit [`55050b7`](https://github.com/Tarzzan/nacre/commit/55050b75f69cf9a428945392409f6d0826965e96) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md).

Avant l’import : neuf modules figés identiques entre Spark et le paquet, aucune tâche active, répétition de la mise à jour alpha.21 → alpha.22 sur une console et son superviseur en répertoire temporaire. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 10 h 41 min 40 s et la validation à 10 h 42 min 15 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés et configuration Samba identiques avant et après. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé. Samba a répondu à `smbcontrol smbd ping`.

La carte [Détection](CAMERA-DETECTION.md) a ensuite été éprouvée sur la caméra réelle, depuis le navigateur :

- État lu : détection active, personnes suivies, dix-neuf types proposés d’après le modèle installé.
- **Voiture** ajoutée puis retirée, par deux réglages confirmés en 9 secondes chacun, validation par Frigate comprise. Entre les deux, Frigate annonçait bien les deux types, chacun avec son filtre aux seuils par défaut.
- Un troisième envoi du réglage déjà appliqué a répondu **Aucun changement**.
- Frigate n’a pas redémarré (même heure de démarrage, état sain). Dans les dix minutes suivant le premier réglage, l’enregistrement est resté continu (66 segments, aucun trou) et les journaux de Frigate ne comptent aucune erreur. Sur quatorze relevés en sept minutes, la caméra est restée à 5 images par seconde, sans image ignorée, et le détecteur est resté sollicité.
- Les deux réglages figurent au journal d’activité.

La configuration Frigate a donc changé, et seulement ainsi : le fichier indique désormais la détection active et les personnes suivies. Avant, il indiquait la détection désactivée alors qu’elle était active par la seule mémoire d’état de Frigate ; le fichier et l’état appliqué concordent maintenant. Nacre ne garde qu’une copie, celle d’avant le dernier réglage : la configuration d’avant le premier n’y figure plus, le second l’ayant remplacée. Les types suivis sont revenus à leur état d’origine : le choix de ce que la caméra doit suivre reste à faire par son propriétaire.

Limites de ce contrôle : aucune voiture n’étant passée pendant les trente secondes de suivi, la reconnaissance d’un nouveau type n’a pas été observée. Personne n’est passé non plus dans les dix minutes suivantes : la scène était calme depuis vingt-cinq minutes avant eux. Un événement « personne » a été créé à 11 h 05, heure de Guyane, vingt-deux minutes après le dernier réglage : le suivi continuait. La bascule de la détection (pause puis reprise) n’a pas été exercée sur Spark pour ne pas suspendre la détection en service ; elle l’a été sur un second Frigate temporaire, sans réseau ni caméra, lancé puis retiré de Spark avant la fusion. Aucune image de surveillance n’a été capturée ni publiée.

Les copies de retour arrière occupent 4,6 Mo pour trois mises à jour dans `state/console/updates/`, toujours sans purge automatique. Le fuseau de la console n’est toujours pas réglé (heures UTC). Aucune panne n’a été injectée sur Spark.

## 12 novembre 2026 — alpha.21

L’installation alpha.20 a reçu le paquet `nacre-0.8.0-alpha.21.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.21), construit depuis le commit [`8d603df`](https://github.com/Tarzzan/nacre/commit/8d603df60f4fab492fa8b03d220a4c09717ce225) après validation CI x86-64/ARM64, par le même [parcours de mise à jour](BROWSER-UPDATES.md) qu’alpha.20.

Avant l’import : neuf modules figés identiques entre Spark et le paquet, aucune tâche active, répétition de la mise à jour alpha.20 → alpha.21 sur une console et son superviseur en répertoire temporaire. Le fichier importé est celui téléchargé depuis la release, empreinte contrôlée. Il a été envoyé à la route d’import par une session administrateur temporaire, refermée ensuite ; l’installation a été confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie**, session conservée.

Le superviseur a enregistré la préparation à 8 h 49 min 24 s et la validation à 8 h 49 min 59 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, clés, configuration Samba et configuration Frigate identiques avant et après ; seul l’horodatage du collecteur d’alertes a changé dans les réglages, sans alerte active. Conteneurs Samba et Frigate inchangés (identifiants et heures de démarrage), service systemd non relancé. Samba a répondu à `smbcontrol smbd ping`.

Les [événements de la relecture](RECORDING-PLAYBACK.md) ont été contrôlés sur la caméra réelle : 47 événements le jour même, 115 la veille, 183 l’avant-veille, 92 le 9 novembre, tous rattachés à une plage conservée. Seul le 9 novembre compte deux types (personnes et un enregistrement manuel) : le filtre y apparaît, réduit la liste à une vignette et place un repère sur la frise. Un événement a été lu sans erreur en 2880 × 1620, sans message de reprise. Douze vignettes ont été chargées par la page en 175 × 175 ; un identifiant inconnu est refusé. Aucune image de surveillance n’a été capturée ni publiée.

Limite de ce contrôle : le navigateur de pilotage ne dessinait pas la page, son panneau étant masqué. Le chargement des vignettes au défilement n’a donc pas été observé sur Spark ; il l’a été sur le banc simulé, et les vignettes de Spark ont été chargées en le forçant. Sur cette caméra, Frigate ne suit que les personnes : le filtre par type reste absent des jours ordinaires.

Les copies de retour arrière occupent désormais 3 Mo pour deux mises à jour dans `state/console/updates/`, toujours sans purge automatique. Le fuseau de la console n’est toujours pas réglé (heures UTC). Aucune panne n’a été injectée sur Spark.

## 11 novembre 2026 — alpha.20, première mise à jour par paquet signé

![Mise à jour réussie sur Spark](images/spark-alpha20-update.jpg)

L’installation alpha.19 a reçu le paquet `nacre-0.8.0-alpha.20.nacre-update` de la [version publiée](https://github.com/Tarzzan/nacre/releases/tag/v0.8.0-alpha.20), construit depuis le commit [`82b65ea`](https://github.com/Tarzzan/nacre/commit/82b65ea21e885eafb80c8ef06179b9073111ee3b) après validation CI x86-64/ARM64. C’est le premier usage réel du [parcours de mise à jour](BROWSER-UPDATES.md) : aucun script de déploiement accompagné n’a servi.

Avant l’import, les neuf modules figés de Spark ont été comparés à ceux du paquet (identiques), et la même mise à jour a été répétée sur une console alpha.19 et son superviseur dans un répertoire temporaire. Sur Spark, le paquet a été envoyé à la route d’import de la page Mises à jour par une session administrateur temporaire, refermée ensuite ; le navigateur de pilotage ne pouvait pas sélectionner un fichier local. La signature a été vérifiée par Spark, puis l’installation confirmée et suivie dans le navigateur jusqu’à **Mise à jour réussie** et au rechargement, session conservée.

Le superviseur a enregistré la préparation à 23 h 51 min 17 s et la validation à 23 h 51 min 53 s, heure de Guyane, confirmation humaine comprise. Schéma SQLite 2 conservé et `quick_check` réussi. Comptes, configuration Samba et configuration Frigate identiques avant et après ; seul l’horodatage du collecteur d’alertes a changé dans les réglages, sans alerte active. Les conteneurs Samba et Frigate gardent leurs identifiants et heures de démarrage ; le service systemd n’a pas été relancé, le superviseur ayant remplacé la console lui-même. Samba a répondu à `smbcontrol smbd ping`.

La [relecture](RECORDING-PLAYBACK.md) a ensuite été contrôlée sur la caméra réelle : quatre jours proposés, journée en cours en une plage avec sept moments détectés, jour ancien réduit à 127 passages conservés. Un extrait du jour et un extrait de l’avant-veille ont été lus sans erreur en 2880 × 1620. Aucune image de surveillance n’a été capturée ni publiée.

Deux observations pour l’exploitation : le fuseau de la console de Spark n’a jamais été réglé, la relecture y affiche donc des heures UTC tant qu’il n’est pas choisi dans le Panneau de configuration ; les copies de retour arrière (code et base précédents, 1,5 Mo) restent dans `state/console/updates/`, sans purge automatique. Aucune panne n’a été injectée sur Spark : le retour arrière automatique reste prouvé sur bancs isolés uniquement.

## 11 novembre 2026 — alpha.13

![Services sur Spark après mise à jour](images/spark-alpha13-services.jpg)

L’installation alpha.6 a reçu les 46 fichiers de console et modules associés du commit [`b52d6c8`](https://github.com/Tarzzan/nacre/commit/b52d6c8f7af77de067e35076f52bc1ee63105507), après validation CI x86-64/ARM64. Empreintes du paquet et des fichiers contrôlées ; code Python compilé avant remplacement.

La console a été seule relancée. Comptes, empreintes des mots de passe, clés, configurations, dépôts, plans et profils de stockage comparés avant/après ; identités et dates de démarrage de Samba et Frigate inchangées. Schéma SQLite 2 conservé et `quick_check` réussi. Neuf routes authentifiées contrôlées, dont la liste des règles de rétention. Aucune tâche active, aucun plan activé et aucune règle de rétention préexistante au moment de cette mise à jour. Notifications externes désactivées.

Samba a répondu au contrôle `smbcontrol smbd ping` ; Frigate a signalé une caméra recevant des images. Le navigateur a affiché alpha.13. L’intervalle mesuré entre arrêt de console terminé et fin des contrôles du script est de 0,63 seconde, sans mesure d’interruption vidéo ni redémarrage de ses conteneurs.

Les copies privées de retour arrière restent sur Spark dans `.updates/alpha13-20261111/` : ancien code, copie cohérente SQLite, fichiers ajoutés, manifeste et résultat. Le script prévoit un retour au code précédent si les contrôles échouent. Comme le schéma reste 2, la base vivante est conservée lors de ce retour pour éviter d’effacer d’éventuelles écritures après relance ; la copie privée reste disponible pour une reprise manuelle contrôlée. Cette branche d’échec n’a pas été déclenchée en production.

Ce document conserve les observations de chaque déploiement ; les notes des versions publiées complètent cette chronologie. Les essais de panne restent isolés.

## 10 novembre 2026 — alpha.6

Le 10 novembre 2026, l’installation existante de Spark (Linux ARM64, Python 3.12.3) est passée de **0.7.0-alpha.1** à **0.8.0-alpha.6**. Le code déployé est le commit [`c453124`](https://github.com/Tarzzan/nacre/commit/c45312410406fb871588fea3ac6bf34978454ae6), qui inclut le correctif d’affichage ajouté après le tag alpha.6.

La version de Spark a été vérifiée par son API authentifiée et dans le navigateur. Le port local **8766** donne accès à Spark via le tunnel SSH existant ; **8768** reste une console de test distincte.

![Notifications sur Spark après mise à jour, envois désactivés](images/spark-alpha6-notifications.jpg)

## Résultats observés

| Contrôle | Résultat |
| --- | --- |
| Sources installées | 40 fichiers, empreintes SHA-256 conformes au commit déployé |
| Base SQLite | Schéma 1 → 2 ; `quick_check` réussi |
| Comptes, droits, empreintes des mots de passe | Identiques avant et après |
| Clés de sauvegarde et configurations contrôlées | Empreintes identiques |
| Dépôts, plans et profils de stockage | Enregistrements identiques |
| Tâches actives / plans activés au déploiement | 0 / 0 |
| Samba et Frigate | Identifiants de conteneurs et dates de démarrage identiques |
| Samba après déploiement | Réponse au contrôle `smbcontrol smbd ping` |
| Caméra existante | Une caméra dans les statistiques Frigate ; réception d’images positive |
| Accès web | Huit routes authentifiées contrôlées ; vues Notifications et Services vérifiées |
| Notifications externes | Désactivées, aucune destination ni livraison en attente |

Les huit routes sont `/api/me`, `/api/notifications`, `/api/setup`, `/api/alerts`, `/api/smb`, `/api/storage`, `/api/protection/plans` et `/api/protection/migrations`. La session temporaire utilisée pour ces contrôles a été supprimée après vérification.

Seule la console a été arrêtée et relancée. La durée mesurée entre son arrêt terminé et la fin des contrôles du script est de 0,82 seconde ; ce chiffre ne mesure pas une interruption vidéo. Aucun disque, pool, compte ou destination de sauvegarde n’a été créé. Le fichier Compose existant et les configurations privées ont été conservés.

## Préparation et retour arrière

Les 11 tests de migration SQLite ont été exécutés sur des bases temporaires locales et ont réussi. Le commit produit disposait également d’une [CI réussie](https://github.com/Tarzzan/nacre/actions/runs/42820854577) avant son installation.

Un paquet limité aux sources de la console, aux modules Python nécessaires et au changelog a été préparé depuis Git. Son empreinte a été vérifiée sur Spark, puis les fichiers Python ont été compilés avant de remplacer le code installé. Un verrou exclusif a protégé la copie de base et le remplacement des sources pendant l’arrêt de la console.

Dans le répertoire privé `.updates/alpha6-20261110/` de l’installation restent :

- `before-code.tar.gz` : versions précédentes des fichiers remplacés ;
- `before.sqlite3` : copie cohérente de la base avant migration ;
- `added.json` : fichiers introduits par la mise à jour ;
- `manifest.json` : commit et empreintes du paquet ;
- `result.json` : résultat synthétique des contrôles.

Ces copies restent sur Spark. La base contient des informations privées et ne doit pas être publiée. Un retour au code précédent exige aussi le retour à son schéma de base, avec console et tâches arrêtées. Il faut examiner les changements intervenus depuis la mise à jour avant de restaurer cette copie : elle ne contient pas les opérations ultérieures.

Le script de déploiement prévoyait un retour au code et à la base précédents en cas d’échec de ses contrôles. Cette branche de retour arrière n’a pas été déclenchée sur Spark ; aucun échec n’a été injecté sur l’installation réelle.

## Portée

Ce compte rendu atteste la mise à jour de la console et la continuité des services observée. Il ne constitue pas une nouvelle qualification destructive des pools, un test de remise d’email externe ou une installation de l’agent de stockage privilégié. Cet agent n’était pas actif sur Spark. Les essais de coupure et de reconstruction restent documentés dans les laboratoires isolés.
