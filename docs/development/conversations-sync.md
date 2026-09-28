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
(`frontend/src/lib/convSync.ts`). Chaque vue garde une copie de travail en
mémoire ; le `localStorage` est son point de reprise et son secours hors ligne.

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
   écraser. La date progresse d'au moins 1 ms dans une conversation, même
   lorsque deux mutations arrivent pendant la même milliseconde.

## Rendu et sauvegarde (19 septembre 2026)

- `cacheConversations.ts` charge le JSON une fois. Les écritures produisent
  des copies des seuls objets modifiés ; les anciens messages gardent leur
  identité. Ne jamais modifier une valeur obtenue par `loadConversations()`.
  Les sauvegardes réseau déjà en vol restent ainsi des instantanés stables.
- Le premier texte est publié immédiatement, puis les rafales sont regroupées
  par `cadenceFlux.ts` sur 80 ms au plus lorsque la boucle de la vue s'exécute
  normalement. Une publication de fin garantit le dernier fragment ; aucune
  dépendance à `requestAnimationFrame` ne retient le texte hors écran.
- Pendant un flux, un point de reprise local est écrit toutes les 1 000 ms
  au plus lorsque les minuteurs s'exécutent normalement. C'est un délai fixe,
  pas un debounce repoussé par chaque fragment. Les autres mutations, la fin
  du flux, `pagehide`, `beforeunload` et le passage hors écran vident la copie
  en attente. Un arrêt brutal peut perdre le texte depuis le dernier point
  réellement écrit ; les minuteurs des vues suspendues ne garantissent pas
  une borne d'une seconde. Le serveur peut aussi détenir une copie plus récente.
- Une panne de stockage conserve la copie récente en mémoire et signale la
  panne une fois. Le moteur peut encore la pousser au serveur. Le retour au
  premier plan et le tick de synchronisation réessaient l'écriture locale.
- Exporter, importer et effacer passent par ce cache, jamais directement par
  l'ancien JSON sur disque. Une réponse audio tardive cible l'identifiant du
  message, sans bloquer le bouton Envoyer ni modifier la réponse suivante.

## Ce que le moteur fait, et pourquoi

- Tire au démarrage, toutes les 10 s lorsque la vue est visible, au `focus`,
  au retour du réseau et à la réouverture du mini-panneau. Les GET simultanés
  partagent la même requête. Hors écran, le tick ne fait que réessayer les
  écritures en attente. Les événements `storage` fusionnent aussi les copies
  d'une même origine ; entre les deux origines, le serveur reste le relais.
- Pousse 1200 ms après la dernière modification, immédiatement à la fin d'un
  flux, quand la fenêtre se cache et à `pagehide`. Une fermeture brutale ne
  garantit pas l'achèvement HTTP : le point de reprise local et les tombales
  en attente permettent de réessayer au prochain lancement. Une poussée
  demandée pendant qu'une autre est en vol est rejouée juste après.
- La conversation qui **reçoit un flux** (`streamState.conversationId`, pas
  `activeId` — on peut changer de conversation pendant qu'une réponse
  arrive) est exclue de toute fusion tant que le flux dure, et le curseur
  n'avance pas tant qu'une exclue n'a pas été appliquée. Un autre fil consulté
  pendant ce flux continue, lui, de recevoir les modifications distantes.
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

## Le téléphone synchronise sans clé, par le cookie (28 septembre 2026)

**Le défaut.** `tirerUneFois` et `pousser` sortaient sur `if (!getApiKey())
return;` — deux gardes du 16 septembre, écrites avant le téléphone. Dans la
WebView du téléphone, `getApiKey()` vaut toujours `''` : la passerelle du
tailnet (`server/passerelle_tailnet.py`) authentifie par le cookie `HttpOnly`
de la session d'appareil (`diapason_appareil`) et **refuse** la clé locale.
Le journal complet ne portait donc aucun `GET` ni `PUT /v1/conversations`
venu du téléphone, alors que `tests/contract/tailnet_portee.json` classe les
trois routes `session` (permises). Les discussions tapées au téléphone ne
vivaient que dans le `localStorage` de sa WebView (une troisième origine,
`https://<Mac>.<tailnet>.ts.net`) ; celles du Mac n'y arrivaient jamais.

**La règle.** Une requête de synchronisation part si
`serveurJoignable(getApiKey(), serviParLeTailnet())` : une clé, OU le bundle
servi par la passerelle (le pont natif, ou l'en-tête
`X-Diapason-Passerelle: tailnet` vu sur une réponse — `lib/tailnet.ts`). Au
téléphone, `apiFetch` part sans en-tête `Authorization` et le navigateur
joint le cookie de même origine, comme à tout autre appel du bundle ; les
`PUT` et `DELETE` portent l'`Origin` que la passerelle exige des écritures.
Hors de la passerelle et sans clé, rien ne part : la garantie du 16
septembre (pas de faux « synchronisé ») tient toujours.

**Le premier tick du téléphone.** Son état de synchronisation n'a jamais
servi (curseur 0, carte vide) : le `GET` sans `since` tire tout ce que le Mac
détient et le fusionne au grain du message ; la poussée qui suit envoie
chaque conversation locale non vierge que la carte ne connaît pas — celles
tapées au téléphone depuis le 26 septembre compris — et les suppressions
faites au téléphone partent en `DELETE`. Rien de neuf dans la règle de
fusion : c'est la même union, commutative et idempotente.

**Un 401 servi par le tailnet = session d'appareil perdue** (expirée à 12 h,
fermée ou révoquée depuis le Mac) : `sessionPerdue(401, true)`, qu'il tombe
sur le `GET`, un `PUT` ou un `DELETE`. Le moteur le dit une fois dans la
console, puis ses ticks et ses poussées se taisent ; chaque reprise (`focus`,
retour au premier plan, retour du réseau, réouverture du panneau) sonde UNE
fois — un 401 par retour, jamais au tick. Il ne vide RIEN : `localStorage`,
carte, curseur et file des suppressions restent tels quels, et rien n'est mis
en quarantaine. Au Mac, un 401 reste transitoire (la clé n'est pas encore
injectée) et se réessaie au tick, comme avant.

**La synchronisation reste muette jusqu'au prochain chargement de la page.**
Une session morte ne revit pas sous une page ouverte : la coquille en rouvre
une par une NAVIGATION — au démarrage à froid, sur le 401 du document, ou au
retour au premier plan passé 6 h — qui remet ce module à zéro ; avant 6 h,
elle reprend le même cookie sans rien faire (`deciderOuverture`, dépôt
`diapason_mobile`). Rien n'est perdu : les discussions restent dans la
WebView et partent avec la page suivante. (Corrigé le 28/09/2026 après
revue : ce paragraphe disait que la coquille rouvre une session « à la
reprise », ce qu'elle ne fait qu'après 6 h.)

**Une tombale refusée n'est pas jetée.** Un `DELETE` refusé pour de bon ne
retire l'id de la file que si le serveur ne peut pas l'ADRESSER (404, 422 :
`idNonAdressable`). Tout autre refus — un 403 de la passerelle, « Origine
refusée » — garde la tombale en file, mise de côté pour la session : jetée,
la conversation supprimée revenait au tirage suivant.

Tenu par `lib/convSync.telephone.test.ts` (le moteur entier sans clé : tirer,
pousser, supprimer, curseur ; un 401 sur le `GET`, puis page cachée sur le
`DELETE` et sur le `PUT` ; un 403 et un 404 sur le `DELETE`) et
`lib/convSync.test.ts` (les fonctions pures). Dix-sept mutations, dix-sept
tests qui échouent.
