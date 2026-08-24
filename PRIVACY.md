# Politique de confidentialité — Diapason

*Dernière mise à jour : 24 août 2026*

Diapason est un assistant personnel qui tourne **sur la machine de son
utilisateur**. Il n'y a pas de serveur Diapason, pas de compte Diapason, et
aucune donnée d'utilisateur ne nous parvient : nous n'en recevons aucune, donc
nous n'en conservons, n'en partageons et n'en vendons aucune.

## Où vivent les données

Tout est stocké localement, dans le dossier `~/.diapason/` de l'utilisateur :
conversations, mémoire, index de recherche, réglages, jetons d'accès. Rien de
tout cela n'est téléversé.

## Le modèle et la voix restent sur la machine

La compréhension du langage (Ollama), la reconnaissance vocale (Whisper), la
synthèse vocale (Kokoro) et la description d'écran s'exécutent localement. Les
paroles, les captures d'écran et les conversations ne quittent pas l'ordinateur.

## Les données Google

Quand l'utilisateur connecte lui-même ses comptes Google, Diapason lit, **depuis
sa propre machine et avec ses propres identifiants OAuth**, ce qu'il a autorisé :

- **Gmail** (`gmail.modify`) — lire ses messages pour les indexer et les
  rechercher ; archiver ou mettre à la corbeille uniquement sur sa demande
  explicite.
- **Google Calendar** (`calendar`) — lire ses événements ; en créer ou y
  répondre uniquement sur sa demande explicite.
- **Google Contacts** (`contacts.readonly`) — lire ses contacts pour retrouver
  une personne par son nom.
- **Google Drive** (`drive.readonly`) — lire ses documents pour les indexer.
- **Google Tasks** (`tasks.readonly`) — lire ses tâches.

Ces données sont écrites dans l'index local de recherche et **ne sont transmises
à personne**. Elles ne servent ni à entraîner un modèle, ni à de la publicité,
ni à aucun traitement hors de la machine. Les échanges réseau ont lieu
exclusivement entre l'ordinateur de l'utilisateur et les serveurs de Google.

## Suppression et révocation

- Révoquer l'accès à tout moment :
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- Supprimer les jetons locaux : effacer `~/.diapason/connectors/`.
- Supprimer les données indexées : effacer `~/.diapason/knowledge.db`.
- Tout supprimer : effacer le dossier `~/.diapason/`.

## Le verrou local

Le réglage `[privacy] local_only` bloque, quand il est actif, **toute** sortie
réseau des connecteurs — la promesse est appliquée sur tous les chemins, pas
seulement sur certains.

## Contact

Questions : ouvrir une issue sur
[github.com/carlitoetienne01-spec/Diapason](https://github.com/carlitoetienne01-spec/Diapason/issues).
