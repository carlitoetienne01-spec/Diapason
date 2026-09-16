# Les conversations du chat — le serveur est la source de vérité

Jusqu'au 16 septembre 2026, l'historique des discussions vivait **uniquement**
dans le `localStorage` du bundle React (clé `diapason-conversations`). Or le
`localStorage` est cloisonné par origine web : la fenêtre principale charge
le bundle empaqueté (`tauri://localhost`), le mini-panneau de la réglette le
charge depuis le serveur (`http://127.0.0.1:8000`). Deux origines, deux
silos — une conversation commencée dans le mini-panneau n'existait pas dans
la fenêtre, et réciproquement.

Depuis, le serveur garde l'historique dans `~/.diapason/conversations.db`
(`server/conversations_store.py`), et chaque vue le synchronise
(`frontend/src/lib/convSync.ts`). Le `localStorage` reste le cache de
travail synchrone de chaque vue et son secours hors-ligne.

## Le contrat (camelCase anglais sur le fil, comme partout)

| Route | Rôle |
|---|---|
| `GET /v1/conversations?since=<seq>` | `{conversations, deleted, seq}` : tout ce qui a été **écrit** après le numéro `seq`, tombales comprises |
| `PUT /v1/conversations/{id}` | fusionne la copie envoyée avec la copie stockée ; rend `{conversation}` (la copie stockée) ou `{deleted, deletedAt}` |
| `DELETE /v1/conversations/{id}` | pose une pierre tombale (`deletedAt` serveur), idempotent, purgée après 30 jours |

Montées sur l'app **localhost** seulement — jamais sur la sous-app `lan` : ce
sont des transcriptions privées. Exemptées du limiteur de débit, pas de la
clé.

## Trois règles qui ne se négocient pas

1. **Le curseur est un numéro d'écriture, jamais une heure.** Chaque
   écriture serveur prend un `seq` monotone (compteur à part, jamais
   `MAX(seq)` — la purge des tombales ferait reculer ce dernier). Un client
   qui a vu `seq = N` demande `since=N` et reçoit tout ce qui est arrivé
   après, quelle que soit l'heure (`updatedAt`) que porte le contenu. Un
   premier jet filtrait sur l'heure du contenu : une poussée en retard restait
   invisible à jamais.
2. **La fusion se fait au grain du message, pas de la conversation.**
   `fusionner_conversations` (Python) et `fusionnerConversations`
   (TypeScript) appliquent la **même** règle : union des messages par
   identité (`id`, sinon `role@timestamp`), la version la plus complète par
   message (le contenu ne fait que croître pendant un flux), métadonnées de
   l'écriture la plus récente, ordre total explicite sur égalité. Elle est
   commutative et idempotente : quel que soit l'ordre des poussées, toutes les
   vues convergent. L'instantané `tests/contract/fusion_conversations.json`
   (généré par `scripts/gen_fusion_fixture.py`) est vérifié par les deux
   suites — **régénère-le dans le même commit** que tout changement de la
   règle.
3. **Toute mutation du store date son écriture.** `choisirAPousser` ne pousse
   que ce dont `updatedAt` dépasse la version connue du serveur ; un
   renommage ou une épingle non datés ne partaient jamais, puis se faisaient
   écraser.

## Ce que le moteur fait, et pourquoi

- Tire au démarrage, toutes les 10 s et au `focus` ; pousse 1200 ms après la
  dernière modification (pendant un flux, chaque bout de texte modifie) et
  tout de suite quand la fenêtre se cache. Une poussée demandée pendant
  qu'une autre est en vol est rejouée juste après.
- La conversation qui **reçoit un flux** (`streamState.conversationId`, pas
  `activeId` — on peut changer de conversation pendant qu'une réponse
  arrive) est exclue de toute fusion tant que le flux dure, et le curseur
  n'avance pas tant qu'une exclue n'a pas été appliquée.
- Un refus permanent du serveur (4xx hors 401/429) met la conversation en
  quarantaine pour la session, sans bloquer les autres ; un 5xx ou une panne
  réseau se réessaie au tick suivant, un seul `console.warn` à la panne, un
  au rétablissement.
- `store.ts` n'importe jamais le moteur : `saveConversations` et
  `deleteConversation` émettent des `CustomEvent` window que le moteur
  écoute.

Sous pytest, `tests/conftest.py` redirige le magasin de tout `create_app`
vers un répertoire jetable (portée session) : la base réelle ne doit jamais
être ouverte par un test.
