# Une déconnexion ne doit pas arrêter les communications vidéo

## Cause observée et limite du diagnostic

L’analyse complémentaire de l’incident du 11 novembre 2026 a retrouvé une exception non gérée dans le thread de communication interne de Frigate. La chaîne était :

```text
InterProcessCommunicator.read → dispatcher → WebSocketClient.publish
→ ws4py.send → RuntimeError: Cannot send on a terminated websocket
```

Le contrôle `ws.terminated` précède l’envoi. Une connexion peut se fermer entre ces deux opérations. L’image Frigate installée intercepte déjà plusieurs erreurs réseau, mais pas cette exception. Celle-ci peut donc sortir de la boucle de lecture IPC ; un producteur attendant sa réponse ne la reçoit plus. Un serveur HTTP accessible et un relais RTSP fonctionnel ne suffisent alors pas à garantir que les mesures et les images traitées progressent.

La trace et la reproduction établissent ce défaut. Elles ne prouvent pas qu’il était l’unique cause des ralentissements observés cette nuit-là, ni que tous les gels vidéo sont éliminés. La vérification de fraîcheur ajoutée en [alpha.16](VIDEO-FRESHNESS.md) reste nécessaire.

## Correction livrée en alpha.17

Nacre construit une image dérivée des bases officielles **Frigate 0.18.2**, épinglées par architecture et par SHA-256 dans `platform_config.py`. Le patch intercepte seulement le `RuntimeError` dont le message est exactement `Cannot send on a terminated websocket`. Les autres `RuntimeError` sont relancées. L’envoi continue vers les autres clients ; les filtres d’autorisation ne sont pas modifiés.

Le fichier amont `frigate/comms/ws.py` doit avoir l’empreinte :

```text
06deb021cd5f193c0177dad9837ea5f77b96256c05996d77aff563d5587f6cd2
```

Une autre implémentation, même proposée sous un nom de version similaire, bloque la construction. Cela concerne aussi une image personnalisée choisie dans `.env` : sa compatibilité doit être revue explicitement. Le patch ne s’applique pas silencieusement à une nouvelle version. Le code modifié est compilé avant la création de l’image et l’étiquette `org.nacre.frigate.patch=terminated-websocket-v1` permet de l’identifier.

Les composants amont conservent leurs licences et avis. Nacre distribue ici une recette de construction et son patch, pas une copie intégrale du module Frigate. Références : [Frigate](https://github.com/blakeblackshear/frigate), [ws4py](https://github.com/Lawouach/WebSocket-for-Python).

## Installation, réinstallation et reprise

**Services → Surveillance · Frigate → Installer** construit désormais l’image corrigée puis démarre le service. Un échec de construction arrête la tâche avant tout remplacement du conteneur en cours. Les fichiers de configuration et les enregistrements restent dans leurs volumes persistants.

Pour une installation existante mise à jour vers cette version, reconstruire et recréer le service vidéo :

```bash
docker compose build video
docker compose up -d --no-deps --no-build video
```

Cette opération interrompt brièvement la vidéo. Elle ne réinitialise pas la caméra. Le répertoire `frigate/` fait partie du code approuvé copié lors d’une reprise sur Linux neuf. Le démarrage après restauration reconstruit la vidéo tout en conservant l’image Samba restaurée.

Pour revenir à la version précédente, conserver son fichier Compose, son image et les copies privées de configuration avant l’intervention. Remettre l’ancien Compose puis recréer uniquement `video`. Aucune migration de la base Nacre ou Frigate n’est introduite par ce patch.

## Reproduction isolée

La CI construit réellement l’image sur **x86-64 et ARM64** et lance `frigate/check_websocket.py` dans un conteneur éphémère : réseau désactivé, système de fichiers en lecture seule, `/tmp` temporaire, aucun montage des données du NAS. Le seul montage contient le banc et le patch, en lecture seule.

Le banc utilise le code réel de Frigate et de ws4py. Il reconstruit en mémoire la méthode amont non corrigée, vérifie son empreinte, puis provoque une fermeture entre le contrôle et l’envoi avec un socket local synthétique. Il vérifie :

- l’échec du code original et la poursuite de l’envoi avec le correctif ;
- 100 requêtes/réponses IPC successives, un lecteur toujours vivant et la réception par un autre client ;
- les connexions déjà terminées et les exceptions réseau déjà tolérées ;
- la propagation d’une erreur différente ;
- le refus des messages inconnus et des messages caméra sans autorisation.

Les tests standard couvrent aussi le refus d’un source inattendu, l’échec de construction sans remplacement du service et la préservation de l’image Samba lors du démarrage après reprise. Il s’agit d’une régression ciblée, pas d’une qualification d’endurance ni d’une nouvelle recette complète de restauration.

## Retirer le patch

Lors d’une mise à jour de Frigate, examiner le traitement amont de cette course, rejouer le banc sur l’image candidate, puis retirer ou adapter explicitement le patch et ses empreintes. Ne pas simplement élargir la liste des sources acceptées pour faire passer la construction.
