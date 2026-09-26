# Diapason mobile — Succès devient Diapason

Décidé le 25/09/2026 par Carlito, question par question. Ce document est le
point d'entrée du chantier : ce qui a été décidé, pourquoi, ce qu'on a trouvé
en regardant, et dans quel ordre on avance. Ce qui est fait y est **barré**,
pas effacé.

## 1. Ce qu'on a trouvé avant de décider

L'inventaire du 25/09/2026, fait en lecture seule sur les deux dépôts, a
contredit la documentation sur quatre points :

1. **Il existait deux Succès aux données séparées.** L'app Flutter
   synchronisait sa Life OS avec le site PHP (`carlitoportfolio.com/
   lifeos-api.php`, blob `lifeos_v1` de 13 clés) et son assistant « L'Entité »
   passait par `assistant-api.php`. Le Succès du bureau vit dans
   `~/.diapason/succes.db`, derrière 100 routes `/v1/succes`. Le Dart n'en
   appelait **aucune**, alors que le document du client mobile (aujourd'hui
   `docs/client-mobile.md`) disait « 73 routes, ce que l'application mobile
   appelle ».
2. **Le lien téléphone ↔ Mac était probablement rompu depuis fin août.** Le
   Dart vise le port 8000 par défaut ; depuis le 26 août (49d45ae), 8000
   n'écoute plus que 127.0.0.1 et le réseau local n'a que les 9 portes du
   maillage sur 8001. Le téléphone a été vu pour la dernière fois le 18 août.
3. **La télécommande était refusée depuis le 25 août** (921acb9) : elle envoie
   `desktop.open` sans confirmation, que le contrôle n°10 exige désormais.
4. **Hors de la maison, rien ne marchait**, et `app_config.dart` portait en
   clair un mot de passe admin et un jeton de synchronisation.

Et un ordre de grandeur : le bureau pèse ~85 000 lignes de React. Tout
réécrire en Dart aurait pris des mois et laissé deux copies à maintenir.

## 2. Les décisions

| Sujet | Décision |
|---|---|
| Architecture | **Hybride** : coquille Flutter native (notifications, appairage, caméra, micro, verrou) + le vrai bundle React dans une WebView. Précédent : le mini-panneau charge déjà ce bundle à 340 px. |
| Réseau | **Partout via Tailscale** (Mac et téléphone). Le téléphone prouve son identité par une **clé d'appareil délivrée à l'appairage, révocable** — jamais par une copie de la clé d'API locale, secret partagé et extractible. |
| Données | Celles du Mac. **Import unique** des 13 clés Life OS du site PHP, puis l'app n'utilise plus le PHP. |
| Renommage | **Absolument tout.** Nom affiché « Diapason », identifiant `com.diapason.mobile` (variante `com.diapason.mobile.dev`, « Diapason dev »), paquet Dart `diapason_mobile`. Dans Diapason, le domaine interne `succes` devient **`vie`** : `/v1/vie`, `src/diapason/vie/`, `~/.diapason/vie.db`, `frontend/src/features/vie/`. À l'écran, le groupe de navigation « Succès » s'intitule **« Diapason »**. |
| Dossier | `~/Desktop/Porfolio/Succes` déménage vers **`~/Projets/diapason_mobile`**. |
| Logo | Icône : la tuile noire (`assets/branding/diapason-icon-1024.png`), identique au Dock. Écran de lancement et premier plan de l'icône adaptative Android : le diapason seul (`assets/branding/diapason-logo-source.png`) sur fond noir. |
| L'Entité | Remplacée par la Discussion Diapason. |
| Thème | Nocturne, neumorphisme et écrans de démo disparaissent ; les 7 apparences du bureau. |
| Plateformes | Android d'abord ; les squelettes web, macOS, Windows et Linux de l'app Flutter sont retirés. |
| Voix | Celle du Mac (Whisper + Kokoro, micro du téléphone par WebSocket), armée à la main, coupée seule (§78). |
| Fonctions propres au Mac | Pilotées à distance depuis le téléphone, jamais exécutées dessus. |
| Ajouts mobiles | Appareil photo → piles de photos ; « Partager vers Diapason » ; notifications (rappels, approbations) ; verrou biométrique. |
| Nettoyage | Firebase retiré ; secrets en clair retirés. |
| Portfolio | Outil personnel : pas de mode démo. Sans Mac joignable, l'app le dit. |

## 3. L'ordre

### Phase 1 — Fondations

**1a. Côté mobile** (ne touche Diapason que pour les chemins) — **fait le
25/09/2026**, onze commits de `9bcd5a2` à `2bb080b` dans `diapason_mobile` :

- ~~déménager le dépôt vers `~/Projets/diapason_mobile` et corriger les chemins
  codés en dur dans Diapason (`scripts/gen_canonical_vectors.py`,
  `tests/contract/test_succes_client_contract.py`,
  `tests/contract/test_mesh_client_contract.py`) ; le test des vecteurs
  **échoue** si le dépôt manque hors CI, au lieu de se sauter en silence~~ ;
- ~~identifiant, paquet Dart, libellés, logo, écran de lancement~~ ;
- ~~retirer Firebase (son `google-services.json` ne déclare que l'ancien
  identifiant : le garder casserait la construction), les secrets en clair
  (sortis vers un fichier local non suivi, lu à la construction : la
  synchronisation PHP doit survivre jusqu'à l'import de la phase 3, sinon ce
  que le téléphone écrit entre-temps serait perdu), les trois démos, le code
  mort et les plateformes inutiles~~.

Ce que la phase 1a a appris, et qui reste vrai :

- **Les secrets quittent le dépôt, pas l'APK.** Ils sont dans
  `config/secrets.json` (ignoré), compilés dans chaque construction faite par
  `tool/flutter_avec_secrets.sh`, et présents dans les 15 commits de
  `cfc5869` à `88a92b6`. Seule une **rotation côté site** les protège ; à
  faire une fois l'import de la phase 3 passé.
- **Sans jeton, l'app envoyait quand même tout l'état au site** en cochant une
  habitude, en affichant « tes données ne partent pas ». La garde vit
  désormais dans `NetClient._send`, avant tout envoi ; un jeton refusé
  (401/403) arrête la synchronisation et le dit, au lieu de rendre l'app
  muette.
- **`_bootstrapFromServer` remplace l'état local par celui du site.** Ce qui a
  été écrit pendant une synchronisation non configurée ou refusée est écrasé
  au premier lancement qui a le bon jeton. Non corrigé : ce code part en
  phase 3.
- Gradle hors de `flutter` exige
  `JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"`.
  Les variantes release et profile demandent des artefacts absents du cache
  hors ligne ; un `flutter build` sans `--no-pub` interroge pub.dev.

L'Entité et Nocturne restent jusqu'à la phase 3 : les retirer avant que la
Discussion Diapason n'arrive laisserait le téléphone sans assistant.

**Changer l'identifiant crée une AUTRE app.** L'ancienne « Succès » et la
nouvelle « Diapason » coexistent sur le téléphone ; l'appairage est à refaire,
et l'ancien « Mon téléphone » est à oublier depuis la page Appareils.
**Avant de désinstaller l'ancienne, s'assurer qu'elle a synchronisé avec le
site PHP.**

**1b. Côté Diapason : `succes` → `vie`** — **commitée le 25/09/2026** dans
la branche `chantier/vie`, étapes 1 à 13 et 14b du plan du §4 (les étapes
14a, 14c et 14d attendent leur condition). Ce que l'inventaire avait relevé
et qui ne devait pas casser en silence :

- ~~le fichier `~/.diapason/succes.db` se renomme au démarrage, avec ses
  `-wal`/`-shm`, jamais pendant qu'une connexion est ouverte~~ (étapes 5 et 6) ;
- ~~les **identifiants d'outils** `succes_*` sont enregistrés dans des agents
  sauvegardés : un agent dont la liste cite un outil disparu en perd un, sans
  erreur. Il faut des alias ou une migration de ces listes~~ (étape 7 : alias) ;
- ~~le schéma `success://` voyage dans des commandes **signées** (`app.navigate`)
  et est codé en dur dans `executor.py`, `mesh_tools.py`, `gestes_routes.py`,
  `features/mesh/routes.ts` et le Dart : période où les deux sont acceptés~~
  (étape 12 : les récepteurs acceptent les deux ; les émetteurs attendent
  l'étape 14a).
  `diapason://` est exclu : déclaré dans `tauri.conf.json`, c'est l'espace
  des liens profonds du système (l'OAuth, lui, passe par
  `127.0.0.1:8789/callback`, pas par ce schéma — une première version de ce
  document disait le contraire) ;
- ~~les routes `/v1/succes/sync/pair` et `/exchange` servent la synchro entre
  instances Diapason : un pair plus ancien (pc-bureau) les appelle encore~~
  (pc-bureau ne sert plus que de CI ; l'invité appelle `/v1/vie/sync/*`) ;
- ~~les clés `localStorage` et les routes React `/succes/*`, la réglette
  (`lib.rs`, `reglette.html`)~~ (étapes 8 à 10) ;
- ~~l'instantané `tests/contract/succes_api_surface.json` et son générateur~~
  (étape 4 : gardé pour l'alias, plus `vie_api_surface.json`) ;
- ~~CLAUDE.md (§1, §4) puis AGENTS.md, le document du client mobile~~
  (étapes 3, 4 et 13) ; la mémoire reste à la session qui met le renommage
  en service.

### Phase 2 — Joindre le Mac, phase 3 — La WebView

Détaillées plus bas, au §4.

### Phase 4 — La voix

~~Aucune coupure automatique n'existe aujourd'hui pour `/v1/voice/live`
(déduit par la conception, à revérifier) : §78 l'exige avant d'ouvrir la voix
au téléphone.~~ *Revérifié le 26/09/2026 : vrai — ni délai sans parole, ni
durée maximale, côté serveur comme côté client ; seul un WebSocket fermé
proprement arrêtait la séance. Fait le même jour, branche `chantier/phases45`,
six commits de `9a59c808` au commit qui barre ces lignes :*

1. *La coupure vit côté SERVEUR (`speech/realtime/bridge.py`) : 120 s sans
   parole, 600 s au plus. La parole = une phrase finale de l'utilisateur, la
   voix de l'assistant jusqu'à la fin de sa LECTURE, un outil, une
   interruption, un texte tapé ; jamais une trame de micro ni un partiel
   (la télévision). 120 laisse 30 s après le désengagement de 90 s pour
   rappeler Diapason par son nom et couvre les 45 s de la cloche vocale ; 600
   est le plafond du mode gestes. Un WebSocket perdu sans fermeture tombe
   sous la même règle. Le serveur envoie `{"type": "closed", "reason":
   "inactivity" | "maxDuration"}` puis ferme en 1000 ; le bundle coupe le
   micro (le voyant d'Android s'éteint) et dit pourquoi, en fr et en en.
   **Elle s'applique aussi au bureau** : une orbe ouverte sur le Mac se tait
   après deux minutes de silence (§78 ne distingue pas les appareils).*
2. *Le fil de ToolExecutor hérite du contexte (`contextvars.copy_context`) :
   l'outil permis au téléphone gardait le plafond pour lui, pas pour ce
   qu'il lançait.*
3. *La séance née du téléphone RESTE du téléphone : la marque est lue à la
   construction de `LocalVoiceSession`. Trousse bornée à
   `OUTILS_DU_TELEPHONE` (vide = outils coupés), chemin rapide
   (`execute_voice_action`, hors de ToolExecutor : « ouvre Safari » ouvrait
   Safari sur le Mac) sauté, perceptions du Mac (app au premier plan, page de
   Diapason, partage d'écran, main tenue) retirées du tour, prompt du
   téléphone (`TOOL_ORAL_HINT_TELEPHONE`), fournisseurs distants refusés par
   la fabrique, exécuteur qui repose la marque dans son fil.*
4. *La dictée du téléphone (`POST /v1/dictation/finalize`, ouverte en phase
   2) EXÉCUTAIT les ordres dictés sur le Mac par `execute_voice_action` :
   depuis le téléphone, une dictée reste du texte, et `execute_voice_action`
   refuse sous la marque.*
5. *La santé de la voix, la lecture des instructions et la sonde d'Ollama au
   démarrage passaient en ligne dans du code async (jusqu'à 1,5 s de boucle
   gelée) : `asyncio.to_thread`.*
6. *`WS /v1/voice/live` et `GET /v1/voice/live/health` classées `session`
   (la famille `/v1/voice/` reste refusée) ; au téléphone, la santé ne
   promet que la voix locale. Le bundle ne retient plus la santé et n'a
   plus la garde « la voix n'est pas encore ouverte au téléphone » ; la
   relève toutes les 5 s reste coupée au téléphone.*

*La preuve passe par la VRAIE passerelle et une vraie session d'appareil
(`TestLaVoixDuTelephone`, `TestLaDicteeDuTelephone`) : le modèle demande
`clipboard_read`, l'outil rend `ok=false` et l'espion ne s'exécute pas ;
`?provider=gemini` est refusé ; une séance muette est coupée avec son motif.
**Reste le banc sur le téléphone** (plus bas, « Le banc de la voix »), une
fois `chantier/phases45` fusionnée : rien de ceci n'a été vu sur l'appareil.*

### Phase 5 — Photo, partage, notifications, verrou

### Phase 6 — Télécommande des fonctions du Mac

## 4. Les plans détaillés (conception du 25/09/2026)

Conçus en lecture seule par quatre lecteurs et une synthèse qui a revérifié
dans le code les affirmations porteuses. Chaque étape est un commit, avec le
défaut qu'elle évite en silence et sa preuve.

### Décisions de la conception (25/09/2026, suite)

Tranchées par Carlito : le nom public du Mac est **atelier** ; **pc-bureau ne
sert plus que de CI** — aucune compatibilité n'est gardée pour lui, et l'étape
14 n'attend donc ni sa mise à jour ni la bascule de l'invité de synchro ;
`~/.diapason/SOUL.md` et `~/.diapason/lacite/synchroniser.py` sont mis à jour
par la session qui met le renommage en service, diff montré.

Découlent des décisions de la première ronde (« absolument tout », « toutes les
fonctionnalités ») : les tables SQLite se renomment (première migration de
schéma du projet : sauvegarde `conn.backup()` juste avant, migration
idempotente, comptes par table identiques avant/après) ; le schéma du maillage
devient `vie://` ; les classes CSS, les clés `localStorage`, le dossier des
photos et le format d'export suivent ; le groupe de navigation reçoit un vrai
titre « Diapason » et les surtitres des pages disent « Diapason » ; les pages
d'administration sont **adaptées** au téléphone dès la phase 3.

Tranchées par défaut, parce qu'elles suivent la recommandation sans rien
retirer : si `succes.db` et `vie.db` ont toutes deux des données, 503 clair
jusqu'à décision ; HTTPS par `tailscale serve` vers la passerelle
`127.0.0.1:8002` ; confirmation de la télécommande sur le téléphone ; actions
sur le Mac depuis la Discussion du téléphone refusées jusqu'à la phase 6 ; le
téléphone peut approuver les confirmations d'outils ; session de 12 h
renouvelée à la reprise ; ACL Tailscale par défaut et expiration de 180 jours
gardée pour la clé du téléphone (désactivée pour le Mac) ; le téléphone passe
toujours par https, même à la maison ; les 5 réglages du site sans équivalent
sont ignorés et nommés dans le résumé d'import ; l'apparence du téléphone est
indépendante de celle du Mac.

Reste ouverte, pour la phase 5 : sans push, une approbation n'arrive qu'app
ouverte ou au mieux toutes les 15 min — acceptable, ou service de premier plan
Android avec sa notification permanente ?

### Ce que le sondage a vérifié (25/09/2026, lecture seule)

Avant de rédiger les trois plans, j'ai revérifié dans le code et sur la machine les affirmations dont ils dépendent. **VU** signifie constaté, **DÉDUIT** signifie tiré de la lecture du code sans l'avoir exécuté.

- **Les écoutes.** VU avec `lsof` : le processus 66629 écoute sur `127.0.0.1:8000` et `*:8001`. C'est bien ce que demande `com.diapason.serve.plist` (`--host 127.0.0.1 --port 8000 --lan-host 0.0.0.0 --lan-port 8001`). Tailscale n'est pas installé : il n'y a ni `/Applications/Tailscale.app`, ni commande `tailscale`, ni adresse en 100.x. uvicorn 0.52.1 démarre avec `proxy_headers=True`, et `forwarded_allow_ips` n'est pas renseigné, ce qui le fait se fier par défaut à 127.0.0.1. `serve.py:260` et `:263` ne changent rien à cela. `_host_actions_allowed` (`server/routes.py:260-272`) accorde le pilotage du bureau à toute adresse de boucle locale. `middleware.py:49-51` envoie `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
- **Où sont gardés les identifiants d'outils.** VU : aucun des 2 agents de `agents.db` (`managed_agents.config_json`) ne cite un `succes_`. `permission_memory` compte 0 ligne. `pending_actions` compte 3 lignes (1 exécutée, 2 expirées) et aucune ne cite un `succes_`. Il n'y a pas de `ROUTINES.json`, et `config.toml` n'en cite aucun. En revanche, **`~/.diapason/SOUL.md` nomme quatre outils au modèle, aux lignes 34-37** (`succes_tasks`, `succes_workspace`, `succes_continuity`, `succes_finances`). Enfin, `agents/executor.py:320` écarte sans rien dire un nom que `ToolRegistry.contains` ne reconnaît pas.
- **`success://` et `verify_command`.** VU : `verify_command` (`mesh/commands.py:318`) ne regarde jamais le schéma. Le contrôle 8 se limite à valider la forme des arguments, et `route` n'y est qu'une chaîne de 300 caractères au plus (`mesh/tools.py:127`). Quatre endroits émettent ce schéma : `mesh/executor.py:179` et `:202`, `tools/mesh_tools.py:476`, `server/gestes_routes.py:734`. Deux le reçoivent : `features/mesh/routes.ts:36` et `mesh_routes.dart:58-59`. **Le récepteur du bureau répond faux.** `executor.py::_navigate` rend `{"ok": True, "userSafeMessage": "Écran ouvert : …"}` dès que la route est mise en file, sans l'avoir validée (§100).
- **`diapason://`.** VU : `tauri.conf.json:69-73` déclare bien ce schéma dans la configuration `deep-link`. Mais le plugin `tauri-plugin-deep-link` ne figure pas dans `Cargo.toml`, et `parseDeepLink` (`lib/deep-link.ts`) n'est importé par aucun fichier. L'OAuth passe par `http://127.0.0.1:8789/callback` (`connectors/oauth.py:44-46`). **La phrase de la phase 1b selon laquelle « `diapason://` est déjà le lien profond OAuth de Tauri » est donc fausse.** Le schéma reste pourtant à exclure pour les routes du maillage, parce que c'est l'espace des liens profonds du système.
- **`/v1/succes/import/legacy`.** VU : la route appelle `SuccesSyncStore.import_legacy_snapshot`. Les étages `store.py:1549`, `workspace.py:1957` et `continuity.py:933` s'y enchaînent. Les coches d'habitude ne sont importées que pour les clés présentes dans `habitLogsAt` (boucle `for key, value in logs_at.items()`, `workspace.py` vers la ligne 2089). Une note au titre vide est sautée sans être comptée (vers la ligne 2031). `succes_imports` compte 0 ligne.
  - **Le plantage des citations au démarrage est DÉDUIT, non exécuté.** Le constructeur `SuccesContinuityStore.__init__` appelle `materialize_continuity_archives()` (`continuity.py:98`), qui rejoue tous les imports. `_load_quote` exclut les lignes supprimées, puis `create_quote` fait un `INSERT` simple sur une clé primaire (`continuity.py:675`). `_transaction` relance l'`IntegrityError` telle quelle, et seule `SuccesError` est rattrapée. Une citation importée puis supprimée ferait donc lever l'erreur dans `get_store()` à chaque démarrage, et toutes les routes `/v1/succes` répondraient 500.
- **Ce qui s'exécute sur le disque.** VU : Diapason est installé en mode éditable (`direct_url.json`). `com.diapason.tick` (toutes les 900 s), `com.diapason.briefing` et `com.diapason.consolidation` lancent `diapason.cli` depuis l'arbre de travail. Ils exécutent donc un commit dès qu'il est posé, alors que le serveur garde l'ancien code jusqu'à son `kickstart`.
- **La base et les photos.** VU : `succes.db` pèse 311 570 432 octets, sans `-wal` au moment de l'inspection. Les 62 photos ont toutes un `file_path` absolu qui contient `/succes-photos/`. `succes_sync_peers` compte 0 ligne. `tests/contract/succes_api_surface.json` liste 100 routes, alors que CLAUDE.md §1 en annonce 73. `~/.diapason/lacite/synchroniser.py:21` appelle `http://127.0.0.1:8000/v1/succes`.
- **Côté mobile.** VU au commit `2bb080b` :
  - `MeshStore.normalizeBase` ajoute `:8000` à toute adresse sans port, https compris ;
  - `mesh_api.dart:155` signe `'requiresConfirmation': false` ;
  - `mesh_pairing_screen.dart:241` écrit lui-même « … est ouvert sur l'ordinateur » ;
  - `ipaddress.ip_address('100.100.1.1').is_private` vaut `False`, si bien que `mesh/transport.py:86` classe une adresse Tailscale comme publique.
- **Le chantier en cours.** VU : `server/app.py` (+166 lignes) et `src-tauri/src/lib.rs` (+319) ne sont toujours pas commités. Les plans ci-dessous ne touchent pas `app.py`. `lib.rs` n'est modifié qu'une fois ce chantier commité.

### Plan de la phase 1b — `succes` devient `vie`

L'ordre suit une règle : **accepter le nouveau nom avant de l'émettre, et ne retirer l'ancien qu'une fois qu'on a vérifié que plus rien ne l'utilise.** Chaque étape correspond à un commit, sauf mention contraire.

> **État au 25/09/2026.** Les étapes barrées sont commitées dans la branche `chantier/vie`, avec leurs preuves automatiques (tests, instantanés, `grep`). Les preuves **sur le Mac** ou **à la main** — `kickstart` puis les comptes de la vraie base, les photos affichées, les 8 icônes de la réglette après `install-desktop.sh`, le briefing lancé à la main — restent à la session qui met le renommage en service, avec `SOUL.md`, `lacite/synchroniser.py` et la mémoire. Barré veut dire commité, pas encore en service.

~~**0. Préalable (pas un commit).**~~ *Levé : `server/app.py`, `compte/*` et `lib.rs` étaient commités (`c829781` à `30ffd51`) avant le premier commit de la 1b.* Attendre que la session des comptes ait commité `server/app.py`, `compte/*` et `lib.rs`, puis relire `git status`. Les points de contact sont `lib.rs:5117` (`__diapNoms`), la docstring de `compte/collections/__init__.py:6`, qui cite `succes/sync.py`, et la clé `compte.synchro.resteIci` de `messages.ts`. Le nom de collection du domaine (« vie ») doit être arrêté avant qu'une collection de ce domaine n'entre dans la liste blanche de `compte/collections/`.
*Risque silencieux :* un commit « vie » emporterait du code des comptes, ou l'un des deux diffs de `lib.rs` écraserait l'autre.
*Preuve :* `git status --short` ne montre rien sur ces chemins.

~~**1. « Le bureau disait "Écran ouvert" pour une route qu'il ne connaît pas ».**~~ *Commité le 25/09/2026 (`22b0926`).* `mesh/executor.py::_navigate` et `_show_resource` valident la route contre la même table que `routes.ts` (`today`, `tasks`, `projects`, `habits`, `notes`) et rendent `UNSUPPORTED` pour une route inconnue. Un test inter-langages lit les clés de `PATHS` dans `routes.ts` et celles de `_views` dans `mesh_routes.dart`, puis les compare à la table Python.
*Risque silencieux :* sans ce garde-fou, toute la bascule de schéma de l'étape 10 peut produire un faux SUCCESS sur un bureau en retard.
*Preuve :* `app.navigate` avec `success://reglages` rend `status == UNSUPPORTED` ; retirer une clé de `routes.ts` fait échouer le test inter-langages.

~~**2. « Un outil retiré d'une liste disparaissait sans un mot ».**~~ *Commité le 25/09/2026 (`8915efb`).* Un test-fusible vérifie qu'une fois `diapason.tools` chargé, chaque nom cité par les listes suivantes satisfait `ToolRegistry.contains` :
- `_TROUSSE_ASSISTANT` (`server/routes.py:63-68`) ;
- `DEFAULT_VOICE_TOOL_IDS` et la table de chargement vocale (`speech/realtime/tools.py:57-75` et `:183-196`) ;
- `_GROUPES` et `_LECTURES` (`trousse_chat.py:58-122`) ;
- les noms en gras de `oral_prompt.py:64-67`.

*Risque silencieux :* sans ce test, une liste renommée à moitié à l'étape 7 retire un outil à la voix ou à un agent sans que rien ne le signale.
*Preuve :* retirer une entrée de la table vocale fait échouer le test.

~~**3. « Le domaine s'appelait encore Succès dans le code Python ».**~~ *Commité le 25/09/2026 (`5c5457f`).* C'est un déplacement mécanique, sans aucun changement de comportement.
- `git mv src/diapason/succes src/diapason/vie` (18 fichiers) et `tests/succes → tests/vie` (18) ;
- `tools/succes_*.py → tools/vie_*.py` (seuls les noms de modules changent) et les classes `Succes*` → `Vie*` ;
- les imports paresseux : `api_routes.py:1082`, `heartbeat/briefing.py:234`, `tools/reminders_calendar.py:36`, `editeur_visuel.py:16-17`, les chaînes de modules de `speech/realtime/tools.py:183-196`, `pyproject.toml`, `tests/privacy/outbound_manifest.txt`, l'import de `scripts/gen_succes_surface.py` ;
- CLAUDE.md §1 (`vie/`, et 100 routes au lieu de 73), puis `scripts/gen_agents_md.py`.

Ne changent pas dans ce commit : `succes.db`, `succes-photos`, les tables, `/v1/succes`, les identifiants d'outils et `success://`. Les variables `succes` au sens de « réussite » ne bougent jamais : `actualite.py`, `gestes_spatiaux.py`, `mesh_tools.py:503`, `agentic_stream.py`, et `teinte="succes"` dans `Pageur.tsx`. Si un alias de module devient nécessaire, il s'écrit en affectation (`_X = X`), jamais en `import … as`.
*Risque silencieux :* un import paresseux oublié ne casse qu'à 7 h 00 (briefing) ou dans l'outil vocal, qui disparaît alors en silence.
*Preuve :*
- tout le bloc Python du §2 de CLAUDE.md ;
- `.venv/bin/python scripts/gen_succes_surface.py && git diff --exit-code tests/contract/` (les 100 routes à l'identique) ;
- `grep -rn 'diapason\.succes' src tests` vide ;
- `.venv/bin/python -m diapason.cli heartbeat briefing --silencieux` lancé à la main rend un briefing non vide ;
- `tests/test_agents_md.py`.

~~**4. « Le serveur ne répondait qu'à /v1/succes ».**~~ *Commité le 25/09/2026 (`fea8c4e`).*
- **Routes.** Le routeur perd son préfixe figé (`vie/routes.py:37`) et `api_routes.py:1085` le monte deux fois : sous `/v1/vie` (dans le schéma OpenAPI) et sous `/v1/succes` (`include_in_schema=False`). Un compteur journalise les accès à l'ancien préfixe, parce que c'est lui qui dira quand retirer l'alias.
- **Middleware.** `auth_middleware.py:87` exempte de clé `/v1/vie/sync/pair` et `/exchange`. `:317` exempte du limiteur `/v1/vie/`, **avec la barre finale**, `/sync/` excepté.
- **Contexte.** `desktop/contexte_app.py:37-45` accepte `/succes/*` et `/vie/*`.
- **Synchro.** ~~Côté invité, `sync.py:565` et `:626` continuent d'émettre `/v1/succes/sync/*`, que les hôtes anciens comme les nouveaux acceptent.~~ Fait autrement : l'invité appelle `/v1/vie/sync/*` dès `fea8c4e` (voir 14b).
- **Instantanés.** On garde `succes_api_surface.json`, dont le cliquet reste vert grâce à l'alias, et on ajoute `scripts/gen_vie_surface.py` → `tests/contract/vie_api_surface.json`. La table du §4 de CLAUDE.md et AGENTS.md changent dans ce même commit.

*Risque silencieux :*
- oublier l'exemption du limiteur, et l'autosave prend des 429 que le cache masque ;
- oublier `pair` et `exchange`, et l'appairage échoue en 401 ;
- oublier le contexte, et chaque page devient « n'existe pas sur les autres appareils » (`mesh_tools.py:466-472`).

*Preuve :*
- `test_auth_middleware` paramétré sur les deux préfixes : 60 requêtes rapides sur `/v1/vie/tasks` sans 429, et le 429 conservé sur `/sync/*` ;
- `test_app_lan.py:51` étendu : les deux préfixes restent fermés sur 8001 ;
- les deux instantanés sont égaux au préfixe près, et l'OpenAPI ne contient aucun `operationId` en double ;
- `poser_contexte('/succes/tasks')` et `poser_contexte('/vie/tasks')` donnent la même route courte ;
- après `kickstart`, `/v1/vie/tasks` et `/v1/succes/tasks` rendent la même liste.

~~**5. « succes.db changeait de nom sans ses photos ».**~~ *Commité le 25/09/2026 (`7eecc67`).*
- **Le résolveur.** Une seule fonction, `chemin_base_vie(data_dir, *, migrer)` (`vie/emplacement.py`), est utilisée par le chemin par défaut du store et par `mesh/identity.py:250`, qui lit les deux noms.
- **Qui migre.** **Seul `diapason serve` migre**, dans `cli/serve.py`, avant `create_app` et avant toute construction de store, et hors du lifespan d'`app.py`. `tick`, `briefing`, `consolidation` et la CLI prennent `vie.db` s'il existe, sinon `succes.db`. Ils ne créent `vie.db` que si aucun des deux fichiers n'existe. `_connect` ouvre en `file:…?mode=rw` quand la base est censée exister.
- **La migration**, sous verrou `~/.diapason/.vie-migration.lock` (`fcntl`, ou `msvcrt` sur pc-bureau) :
  1. `PRAGMA wal_checkpoint(TRUNCATE)` puis `journal_mode=DELETE`. Cette bascule exige d'être la seule connexion, elle sert donc de test d'exclusivité. Un « locked » reporte la migration au démarrage suivant, avec un WARNING dans le journal.
  2. Sauvegarde par `conn.backup()` vers `backups/succes.db.avant-vie-AAAAMMJJ`.
  3. Vérifier que ni `-wal` ni `-shm` ne restent.
  4. `os.replace` vers `vie.db`. Sous Windows, 3 essais, puis on garde `succes.db` pour cette exécution.
  5. `succes-photos → vie-photos`, et les 62 × 2 chemins réécrits **en chemins relatifs** au dossier de données, résolus à la lecture (`photos.py:241-255`, `:341`, `:432`, `:531`, `:670`, `:818`). Si la réécriture échoue, le dossier reprend son ancien nom.
- **Si les deux bases existent.** Si l'une est vide de données, elle est mise de côté dans `backups/…fantome-<horodatage>`. Si les deux ont des données, les routes vie rendent 503 « Deux bases de vie existent » jusqu'à décision.
- **Les tables** se renomment à l'étape 6, pas ici.

*Risque silencieux :*
- une migration lancée par `tick` pendant que l'ancien serveur tourne laisse ce dernier recréer une `succes.db` vide, avec un nouveau `device_id`, et les écritures se coupent en deux bases ;
- sans réécriture des chemins, les 62 aperçus deviennent `""` (`_data_url`) ;
- le singleton `_store` créé avant la migration garderait l'ancien chemin.

*Preuve :* tests dans un `DIAPASON_HOME` temporaire.
- Une transaction restée dans le `-wal` se retrouve dans `vie.db`.
- Une seconde connexion ouverte reporte la migration et laisse `succes.db` intacte.
- La migration est idempotente.
- Avec deux bases non vides : 503, et aucun fichier ne bouge.
- Trois photos à chemins absolus : `photo_content` réussit après migration.
- `migrer=False` avec seulement `succes.db` rend `succes.db` et ne crée rien.
- Deux processus (`multiprocessing`) donnent une seule migration.
- Sur le Mac, après coup : 1 679 tâches, 57 notes, 62 lignes de photos — **45 actives**, chacune lisible par `/v1/vie/photos/{id}/contenu`, et **17 supprimées** (`deleted_at_ms`) dont les fichiers manquaient déjà avant la migration (contre-épreuve du 25/09/2026 sur une copie : 17 manquants avant, les mêmes après, 90 fichiers déplacés, aucun perdu) — et `ls ~/.diapason | grep succes` ne montre que les sauvegardes. Attendre « 62 photos avec leur fichier » ferait conclure à un défaut qui n'en est pas un.

~~**6. « Les tables portaient encore le préfixe succes_ ».**~~ *Commité le 25/09/2026 (`38a587d`).* Décidé : on renomme (« absolument tout »). 26 tables renommées par `ALTER TABLE … RENAME` dans une transaction, `user_version` 3 → 4, environ 340 références SQL dans `src/` et 107 dans `tests/`. Ce serait la première migration de schéma du projet.
*Risque silencieux :* une requête oubliée sur un chemin rare (pierres tombales, imports) ne lève « no such table » que des semaines plus tard.
*Preuve :* les comptes par table sont identiques avant et après, sur une copie de la vraie base et sur une sauvegarde restaurée.

~~**7. « Un agent qui citait succes_tasks perdait l'outil sans un mot ».**~~ *Commité le 25/09/2026 (`6a538ab`).*
- **Identifiants canoniques :** `vie_tasks`, `vie_workspace`, `vie_continuity`, `vie_finances`, `vie_delete_task`, `vie_delete_item`, `vie_delete_continuity`.
- **Alias.** Une table `ALIAS_OUTILS` (7 entrées) est appliquée par `nom_canonique()` à chaque nom venu du disque, du réseau ou du modèle : `agents/executor.py:320`, `server/routes.py:188`, `agent_manager_routes.py:424`, `system/builder.py` (vers la ligne 458), `list_voice_tool_ids`, les outils demandés par la trame vocale, `ToolExecutor.execute` (`_stubs.py:298-303`) et les clés de permission.
- **Ordre et visibilité.** Sur la trame vocale, on traduit **puis** on intersecte avec le plafond : restreindre, jamais élargir. Les alias n'apparaissent dans aucun schéma envoyé au modèle.
- **Libellés pour le modèle.** Les 12 descriptions qui disent « Succès » deviennent « tâches privées de Diapason », et `category="succes"` devient `"vie"`.
- **Écarts silencieux.** Les quatre endroits qui écartent un nom inconnu sans rien dire le journalisent désormais en WARNING.

*Risque silencieux :* un alias appliqué après le plafond rejoue le défaut `DEFAULT_VOICE_TOOL_IDS`. Un alias exposé au catalogue montre deux outils identiques au 9b, qui hésite. Enfin, `SOUL.md` continue de désigner les anciens noms.
*Preuve :*
- un agent configuré `["succes_tasks", …]` se construit avec 4 outils ;
- `ToolExecutor.execute(name='succes_tasks')` ne rend pas « Unknown tool » ;
- la trame `succes_tasks,mesh_send` ne donne que `vie_tasks` ;
- le test-fusible de l'étape 2 reste vert.

~~**8. « Les réglages des pages Succès auraient été oubliés, et 1,7 Mo de cache orphelin aurait rempli le quota ».**~~ *Commité le 25/09/2026 (`890f745`).* Les trois clés sont renommées dans le même commit que la fonction pure `migrerStockage(store)`, appelée à l'amorçage, donc une fois par origine (`tauri://localhost` et `http://127.0.0.1:8000`) :
- `diapason-succes-ui-prefs` (`uiPrefs.ts:8`) et `diapason-succes-habit-reminder-fired` (`habitReminders.ts:12`) sont copiées vers leur nouveau nom si celui-ci est absent, puis retirées ;
- toutes les clés `diapason-succes-cache:*` (`cacheSucces.ts:61`) sont **supprimées**.

La classe `succes-page-break` reste lue (`notePages.ts:29`, `notes_resume.py:25`).
*Risque silencieux :* le budget de 4,2 Mo du nouveau cache s'ajoute à 1 692 006 octets d'anciens caches et dépasse les 5 Mo de WebKit. `saveSettings`, qui n'est pas protégé par un `try`, perd alors les réglages d'apparence. Sans la copie, les rappels d'habitude du jour repartent.
*Preuve :* vitest avec un faux `Storage` :
- les préférences sont recopiées à l'identique ;
- un second passage ne change rien ;
- une valeur neuve n'est pas écrasée ;
- avec 3,5 Mo d'anciens caches et un quota simulé de 5 Mo, l'écriture des caches de tâches et de notes, puis `setItem('diapason-settings')`, ne lèvent pas.

~~**9. « Les pages vivaient sous /succes ».**~~ *Commité le 25/09/2026 (`7391428`).*
- **Déplacements.** `git mv frontend/src/features/succes features/vie` (102 fichiers) et `pages/Succes*` → `Vie*`.
- **Client.** `api.ts` passe ses 96 littéraux à `/v1/vie`, ce que le serveur accepte depuis l'étape 4.
- **Routes.** `App.tsx:422-431` sert les routes `vie/*`, plus `succes/*` qui redirige vers `/vie/*` par la fonction pure `cheminHerite()`, en gardant la requête et l'ancre. `features/mesh/routes.ts` (`PATHS`) et `Sidebar.tsx` suivent.
- **Vocabulaire.** Les clés i18n `nav.succes*` deviennent `nav.vie*`, les classes `.succes-*` d'`index.css` deviennent `.vie-*` en même temps que les TSX, et la catégorie de journal `'succes'` devient `'vie'`.

*Risque silencieux :* la réglette compilée dans l'app installée ouvre `127.0.0.1:8000/succes/tasks` ; sans redirection, le mini-panneau affiche un module vide. Des classes CSS renommées à moitié défont la mise en page des notes sans aucune erreur.
*Preuve :*
- `cheminHerite('/succes/tasks?x=1#a')` rend `/vie/tasks?x=1#a` ;
- `npx tsc --noEmit && npx vitest run && npm run build` ;
- à la main, **avant** de reconstruire Diapason.app : chaque icône de la réglette ouvre la bonne page.

~~**10. « La réglette ouvrait encore /succes ».**~~ *Commité le 25/09/2026 (`a3694e7`).* `reglette.html:270-277` et `__diapNoms` (`lib.rs:5117`) passent à `/vie/*`, en gardant les clés `/succes/*` tant que les redirections existent. Un vitest lit ces deux fichiers et vérifie que chaque route appartient à la liste exportée qu'`App.tsx` utilise.
*Risque silencieux :* la pastille du mini-panneau affiche « Diapason » au lieu du nom de la page. Et si `lib.rs` est édité avant le commit de l'autre session, c'est un conflit.
*Preuve :* `cd frontend/src-tauri && cargo check && cargo test`, puis `./scripts/install-desktop.sh` et les 8 icônes cliquées une à une.

~~**11. « Succès s'affichait encore à l'écran ».**~~ *Commité le 25/09/2026 (`24f44fd`).*
- **Frontend :** les 9 surtitres et `api.ts:146`, `habitReminders.ts:102`, `SuccesDashboardPage.tsx:65`, `messages.ts:1288` et `:2792`.
- **Python :** `vie/routes.py:321`, `:529`, `:542` et `:552`, `relay.py:75`, `cli/serve.py:296`, `serve_service_cmd.py:47`, les 5 messages d'outils, et `executor.py:211`, où « Succès est au premier plan. » devient « Diapason est au premier plan. ».
- **Tests :** les phrases factices « affiché sur Succès » (`test_handoff`, `test_gestes_routes`, `test_geste_deposer`).

*Risque silencieux :* une clé `nav.succes` que rien ne lit (VU dans `Sidebar.tsx:372-375`) reste une promesse morte (§5), selon la réponse à la question du titre de groupe.
*Preuve :* `grep -rn 'Succès' frontend/src src/diapason` est vide hors commentaires et hors le sens « réussite », et les suites passent.

~~**12. « success:// n'était compris que sous ce nom ».**~~ *Commité le 25/09/2026 (`f74f5a9`, et `352e18c` dans `diapason_mobile`).* Décidé : le nouveau schéma est `vie://`.
- **Récepteurs.** Ils acceptent les deux schémas : `routes.ts:36` (`^(?:success|vie)://`), `mesh_routes.dart:58` et la table Python de l'étape 1. `diapason://` reste refusé (`routes.test.ts:49`).
- **Émetteurs.** Ils ne changent pas dans ce commit. Ils changeront ensuite (étape 14a), cible par cible, selon une capacité déclarée (`app.navigate.vie`) : `app_version` n'est pas fiable, puisqu'il est vide pour le téléphone et resté à 1.0.0 pour pc-bureau.
- **Contrat.** `COMMAND_VERSION`, `PULL_VERSION`, `_POLL_FIELDS` et `_ACK_FIELDS` restent intouchés, car le schéma n'est qu'une valeur.

*Risque silencieux :* émettre le nouveau schéma avant tous les récepteurs donne « route inconnue » sur le téléphone, et un faux SUCCESS sur un bureau privé de l'étape 1.
*Preuve :* vitest et `flutter test` sur le tableau schémas × types, avec le même `path`. `test_les_vecteurs_livres_correspondent_a_l_implementation` reste vert sans régénérer les vecteurs.

~~**13. « La doc parlait encore de Succès ».**~~ *Commité le 25/09/2026 (le commit qui barre cette ligne).*
- **Dans le dépôt :** `git mv` du document du client mobile vers `docs/client-mobile.md`, CLAUDE.md:245 puis AGENTS.md, `CAPABILITY_MATRIX.md`, `spatial-mesh/README.md`, `GESTES.md`, `architecture/device-mesh*.md`, `deployment/launchd.md`, `user-guide/*`, `reconstruire-le-bureau.md`, le commentaire de `deploy/launchd/com.diapason.serve.plist:10` et `deploy/windows/*`.
- **Dans ce document :** corriger la phrase fausse sur `diapason://` et barrer les points de 1b.
- **Ce qu'on ne réécrit pas :** `INITIAL_AUDIT.md` (on y barre), les `mesures-performances-*.json` et `diagnostic-performances-2026-09-19.md`.
- **Hors dépôt :** la mémoire (`succes-api-locale.md`, `etudes-la-cite.md`, …), et, avec l'accord de Carlito, `~/.diapason/SOUL.md:34-37` et `~/.diapason/lacite/synchroniser.py:21`.

*Risque silencieux :* un lien mort dans CLAUDE.md envoie une session parallèle lire un fichier disparu. Une mémoire qui cite `/v1/succes` fait écrire du code contre un alias voué au retrait.
*Preuve :* `tests/test_agents_md.py`, et un `grep -rn` de l'ancien nom du fichier, vide.

**14. Retraits, un commit chacun, chacun à sa condition.**
- (a) Les émetteurs passent au nouveau schéma quand l'APK et Diapason.app reconstruites l'acceptent. *Condition vérifiée à la main, pas déduite du code* : une commande signée `vie://tasks` envoyée au bureau installé (après `install-desktop.sh`) et au téléphone (après `tool/flutter_avec_secrets.sh`), et l'écran des tâches effectivement ouvert sur chacun. Contre-épreuve du 25/09/2026 : entre le kickstart et la reconstruction, le récepteur Python accepte déjà `vie://` et répond « Écran ouvert », alors que la fenêtre installée ne connaît que `success://` — le faux SUCCESS que l'étape 1 avait supprimé.
- ~~(b) L'invité de synchro passe à `/v1/vie/sync/*` une fois pc-bureau à jour.~~ *Fait dès l'étape 4 (`fea8c4e`) : pc-bureau ne sert plus que de CI, aucun hôte ancien n'était à ménager. Le 25/09/2026, un cliquet (`TestLInviteNAppellePlusLAlias`, `tests/vie/test_vie_sync.py`) exige que l'appairage et l'échange passent par `/v1/vie/sync/*` sans toucher le compteur de l'alias.*
- (c) L'alias `/v1/succes` est retiré quand trois conditions sont réunies : `synchroniser.py` corrigé, app reconstruite et service worker renouvelé ; pc-bureau à jour ; et le compteur de l'étape 4 à zéro depuis N jours. Le cliquet `succes_api_surface.json` est alors retiré volontairement.
- (d) Les redirections `succes/*` et les clés `/succes` de `__diapNoms` sont retirées.

Les alias d'outils et la lecture de `succes.db` par le résolveur restent : ils ne coûtent rien et protègent la restauration d'une sauvegarde.
*Risque silencieux :* un retrait trop tôt casse un client hors de vue (le script `lacite`, un bundle en cache, pc-bureau vu pour la dernière fois le 29 août), en 404 dans un outil qui ne l'affiche pas.
*Preuve :* le compteur d'accès, et une requête sur `mesh.db` qui ne trouve aucun appareil de confiance sans la capacité voulue.

---

### Plan de la phase 2 — Joindre le Mac

Le choix recommandé est **`tailscale serve` vers un troisième socket du même processus, `127.0.0.1:8002`, derrière une passerelle ASGI**. On ne pointe jamais serve vers 8000.

Ce n'est pas l'adresse IP qui distingue le téléphone du Mac. Tailscale donne le même utilisateur aux deux appareils, et tout processus local peut forger `X-Forwarded-For`, auquel uvicorn fait confiance depuis 127.0.0.1. C'est le **socket d'arrivée** (`scope["server"]`), que le client ne choisit pas, plus une **session d'appareil**.

Un point est à vérifier sur la machine, faute d'avoir pu le faire : quels en-têtes `tailscale serve` pose réellement. Le plan est conçu pour ne pas en dépendre. L'autre voie, écouter directement sur l'adresse 100.x avec `tailscale cert`, a été écartée : le renouvellement du certificat tous les 90 jours et l'ordre de démarrage face à launchd seraient à notre charge.

**0. Tailscale posé, rien d'autre (fait par Carlito, aucun code).** DÉDUIT : puisque 8001 écoute sur `0.0.0.0`, ses 9 portes (`_PORTES_LAN`, `app.py:737-749`) deviennent joignables par le tailnet. Elles sont signées en Ed25519 et chiffrées par WireGuard.
*Risque silencieux :* un `tailscale serve 8000` lancé « pour essayer » exposerait toute l'API locale. Le téléphone y arriverait de 127.0.0.1 et hériterait du pilotage du Mac (`routes.py:260`).
*Preuve :* en données mobiles, `http://<nom>:8001/` rend un 404 JSON, et `tailscale funnel status` est vide.

~~**1. « Rien ne représentait une session d'appareil ».**~~ *Commité le 26/09/2026 (branche `chantier/phase2`, `7b96aaf` ; tests renforcés par `09be227` après contre-épreuve), avec `tests/mesh/test_sessions.py`. Deux ajouts au plan : `revoke()` efface aussi les sessions et tickets de l'appareil, dans la même transaction (la jointure sur `TRUSTED` reste le vrai verrou, et un test l'éprouve sans passer par `revoke()`) ; `close_device_sessions()` et `list_sessions()` existent déjà pour l'étape 9, qui n'aura plus qu'à les exposer. La dernière activité (`last_used_at_ms`) n'est réécrite qu'une fois par minute, pour ne pas faire de chaque GET une écriture sur `mesh.db`.* On crée `mesh/sessions.py` (en anglais, comme le reste de `mesh/`) et, dans le `_SCHEMA` de `DeviceRegistry`, deux tables :
- `mesh_sessions` : `session_hash` sha256, `device_id` avec `REFERENCES mesh_devices ON DELETE CASCADE`, et des dates en millisecondes entières ;
- `mesh_session_tickets` : à usage unique, valables 60 s, avec la garde `UPDATE … WHERE redeemed IS NULL`.

`verify_session()` exige `TRUSTED` à **chaque** appel. Il n'y a pas de migration, puisque la table se crée à l'ouverture.
*Risque silencieux :* un cache de validité rendrait une révocation sans effet. Oublier `PRAGMA foreign_keys=ON` laisserait des sessions orphelines, qu'un réappairage sous le même identifiant retrouverait.
*Preuve :* la session est refusée juste après `revoke()` ; `forget()` efface ses lignes ; le jeton en clair est introuvable dans la base ; deux échanges concurrents du même ticket ne donnent qu'un seul gagnant.

**2. « Aucune enveloppe ne permettait d'ouvrir une session ».** *~~Côté Python, commité le 26/09/2026 (branche `chantier/phase2`, `4017bbe` ; la forme exacte — une clé en trop refusée — éprouvée par `09be227`) : `build_session_request` et `verify_session_request` dans `mesh/sessions.py`, avec `tests/mesh/test_session_request.py`. Champs signés, dans cet ordre de liste : `version` (propre à cette enveloppe, `SESSION_REQUEST_VERSION = 1`), `purpose`, `ownerId`, `deviceId`, `audience`, `issuedAtMs`, `expiresAtMs`, `nonce` ; l'ensemble des clés doit être exactement celui-là plus `signature`.~~ ~~**Reste pour la partie mobile : le vecteur de `scripts/gen_canonical_vectors.py`**, qui vient avec le Dart, dans le même commit, sinon le test de contrat contre `diapason_mobile` casserait.~~ *Fait le 26/09/2026 (`e9e60cb`, et `f8945ff` dans `diapason_mobile`) : un 15e vecteur, NOMMÉ `enveloppe-de-session`, construit par le vrai `build_session_request` ; pytest exige ses clés = `SESSION_REQUEST_FIELDS` et le reconstruit, le Dart exige que `MeshApi.enveloppeDeSession()` rende ces clés et ces octets.* `POST /v1/appareil/session` (étape 3) lit cette enveloppe depuis `c838184`.* C'est un type d'enveloppe distinct de celui des commandes : `purpose: "webview-session"`, `audience` = identifiant du Mac, validité de 60 s au plus, nonce consommé dans `mesh_nonces`, et seulement des entiers et des chaînes. On ajoute un vecteur à `scripts/gen_canonical_vectors.py` et on régénère `diapason_mobile/test/mesh/canonical_vectors.json` en même temps, dans les deux dépôts.
*Risque silencieux :* un flottant rend toutes les signatures invalides (`1e-07` contre `1e-7`). Réutiliser l'enveloppe des commandes ferait accepter un ordre comme une ouverture de session.
*Preuve :* sont refusés le rejeu, une audience étrangère, un appareil révoqué, une expiration trop lointaine et un flottant. `git diff` ne touche aucune des quatre constantes du §4.

~~**3. « Une requête venue du tailnet aurait hérité des droits de la boucle locale ».**~~ *Commité le 26/09/2026 (branche `chantier/phase2`, `c838184`) : `server/passerelle_tailnet.py`, le classement dans `server/portee_tailnet.py`, l'instantané `tests/contract/tailnet_portee.json` (410 clés alors ; 412 depuis l'étape 9 et la contre-épreuve : 12 ouvertes, 171 sous session, 229 refusées) et son générateur `scripts/gen_tailnet_portee.py`. Écarts au plan : la voix (`/v1/voice/*`) est REFUSÉE, pas sous session — §78 exige sa coupure automatique avant de l'ouvrir au téléphone (phase 4) ; l'alias `/v1/succes` et la synchronisation `/v1/vie/sync/*` sont refusés ; le marquage vaut aussi pour les portes sans session (`diapason.tailnet`, `client = tailnet`), et `_host_actions_allowed` refuse sur ce marqueur, avant même `allow_remote`. L'Origin est comparée à `https://<Host>` ET à `[tailnet] adresse` : si `tailscale serve` réécrit Host (non vérifié), l'adresse posée suffit. Une origine `null` n'est admise que sur `/v1/appareil/ouvrir` (loadRequest d'Android). Le jeton de session est retiré du `Cookie` transmis à l'application, comme `X-Forwarded-*` et `Tailscale-*`. La clé `[tailnet] adresse` (étape 9) est introduite ici, puisque la passerelle la lit la première.*

*Corrigé après contre-épreuve (26/09/2026) — **le refus des routes de l'écran était décoratif** : la Discussion, ouverte au téléphone, portait `screen_read_text`, `screen_describe`, `screen_snap` et `clipboard_read` sans confirmation, plus `open_anything`, `app_install`, `file_trash`, `mail_send`… sous une cloche que le téléphone peut approuver lui-même (`566381d`). Le plafond descend jusqu'à l'exécuteur d'outils : `core/origine_telephone.py`, une variable de contexte que SEULE la passerelle pose, et `OUTILS_DU_TELEPHONE`, liste d'autorisation de 16 outils de données (heure, calcul, agenda en lecture, les 7 outils de vie, mémoire, profil, savoir, web). `ToolExecutor.execute` refuse le reste (et publie `CAPABILITY_DENIED`, capacité « tailnet »), l'enveloppe de chaque `BaseTool` aussi. Le chat du téléphone ne reçoit ni les schémas refusés, ni le cliché du bureau (onglet et fenêtre au premier plan du Mac), ni la page ouverte dans Diapason, ni la main du mode gestes. Douze routes qui créent, modifient ou lancent un agent sont refusées (un agent tourne ensuite dans un `threading.Thread` ou au battement suivant, hors du plafond). Les tests des défenses de la passerelle ont été renforcés (`1a52f23`) : onze mutants survivaient.* Nouveau fichier `server/passerelle_tailnet.py`, qui enveloppe l'app principale sans toucher `app.py`.
- **Portes sans session :** `/health`, les 9 portes LAN, `POST /v1/appareil/session` et `POST /v1/appareil/ouvrir`. Cette dernière pose le cookie `diapason_appareil` (`HttpOnly; Secure; SameSite=Strict`, 12 h), puis répond 303.
- **Tout le reste exige le cookie.** Une clé locale reçue ici est refusée.
- **Marquage.** La passerelle pose `scope['diapason.appareil']`, remplace `client` par `appareil:<id>` et force `scheme='https'`.
- **Origine.** Elle est contrôlée pour les WebSockets et pour tout ce qui n'est pas un GET.
- **Liste refusée, en 403 français :** le plan de contrôle du maillage (dont `POST /v1/mesh/commands`), les écritures de `/v1/config`, les secrets, `/v1/account`, `/v1/gestures/*`, et les actions sur le Mac tant que Carlito n'en a pas décidé autrement. Aussi `GET /v1/mesh/inbox` (sa lecture VIDE la boîte du Mac) et `POST /v1/context/view` (il dit ce que l'écran du Mac affiche) : ajoutés le 26/09/2026, après que la WebView du téléphone eut monté les deux hôtes du Mac — le bundle ne les monte plus au téléphone (`lib/hotesDuMac.ts`), la passerelle le garantit contre un bundle ancien.
- **En-têtes réécrits :** `microphone=(self)`, `camera=(self)` et `connect-src 'self' wss://<hôte>`.
- **WebSocket.** Elle est fermée en 1008 à l'expiration de la session ou à la révocation, avec un contrôle toutes les 30 s au plus.
- **Ailleurs.** `AuthMiddleware` et `websocket_authorized` acceptent le marqueur, et `_host_actions_allowed` le refuse explicitement.
- **Contrat.** Un instantané `tests/contract/tailnet_portee.json` force à classer chaque route.

*Risque silencieux :* une route ajoutée plus tard par une autre session serait exposée au téléphone sans décision ; l'instantané empêche ce cas. `_host_actions_allowed` n'est aujourd'hui protégé que par hasard, par la `ValueError` sur `appareil:…`.
*Preuve :*
- `/v1/models` : 401 sans cookie, 401 avec la clé locale, 200 avec le cookie ;
- `/v1/voice/live` : 1008 sans cookie ;
- `POST /v1/mesh/pairings` : 403 ;
- `action_mode=auto` : aucune action sur le Mac ;
- 8000 garde `microphone=()` ;
- la suite existante passe inchangée.

~~**4. « Le serveur n'avait que deux sockets ».**~~ *Commité le 26/09/2026 (branche `chantier/phase2`, `ff80768`). `_servir_deux_sockets` devient `_servir_les_sockets(prises)` ; `_prises()` construit la liste, et la prise du tailnet n'a AUCUNE option d'hôte (`_HOTE_DU_TAILNET = "127.0.0.1"`). `--tailnet-port` refuse aussi le `--lan-port` par défaut (8001) même sans `--lan-host`. Banc réel du 26/09/2026 (`serve --port 18410 --lan-host 127.0.0.1 --lan-port 18411 --tailnet-port 18412`, foyer de test, moteur factice) : `lsof` montre les trois sockets sur 127.0.0.1 ; une seule tâche de battement du maillage et une seule du compte ; jumelage par le socket tailnet (`join_fleet`), session ouverte (303, cookie `HttpOnly; Max-Age=43200; Path=/; SameSite=strict; Secure`), `/v1/models` 401 / 401 avec la clé / 200 avec le cookie, `POST /v1/mesh/pairings` 403, `/v1/voice/live` refusée à la poignée de main (HTTP 403, le 1008 d'avant l'accept), `action_mode=auto` → `lightning: null` ; une commande `notifications.show` livrée à 18412 rend SUCCESS et apparaît dans `/v1/mesh/inbox` lue sur 18410 ; SIGTERM arrête les trois sockets et le processus. Non vu : la page 401 de `/` (le foyer de banc n'a pas de bundle construit : 404).*

*Corrigé après contre-épreuve (26/09/2026) : un port secondaire (tailnet ou maillage) déjà tenu faisait mourir TOUT le serveur en code 3, API locale comprise, en boucle sous launchd — il est désormais écarté en le disant, et `serve-service install` avertit (`d7f2097`) ; un WebSocket `/v1/agents/events` tenu par le téléphone retenait l'arrêt jusqu'au SIGKILL — le handler entend la déconnexion, et la prise du tailnet a `timeout_graceful_shutdown = 5 s` (`4655deb`, banc réel : plus de 10 s bloqué avant, 0,35 s après) ; un refus d'argument qui régresserait faisait pendre la suite (`7f8e587`).* `diapason serve --tailnet-port 8002` et `serve-service install --tailnet` :
- `_servir_deux_sockets` (`serve.py:237`) est généralisé à N sockets ;
- 8002 écoute sur `127.0.0.1` seulement, avec `lifespan="off"` et `proxy_headers=False` ;
- un port égal à `--port` ou à `--lan-port` est refusé.

Le piège `proxy_headers` d'uvicorn entre au §5 de CLAUDE.md, puis dans AGENTS.md.
*Risque silencieux :* sans `lifespan="off"`, il y a deux battements du maillage, deux tâches de synchronisation du compte, et une double fermeture du magasin des conversations. Écouter sur `0.0.0.0` exposerait la passerelle en HTTP clair.
*Preuve :* le banc à événement `arret` est étendu à 3 sockets. `lsof -iTCP:8002 -sTCP:LISTEN` montre 127.0.0.1. Une commande reçue sur 8002 apparaît dans `/v1/mesh/inbox` lu sur 8000.

**5. (Carlito) `tailscale serve --bg 8002`.** Aucun code.
*Preuve :* en données mobiles, `https://<nom>.<tailnet>.ts.net/health` rend 200 ; `/` rend la page 401 « Ouvre Diapason depuis l'app » ; le serveur arrêté donne 502 ; `tailscale funnel status` est vide.

~~**6. « L'appairage visait un port qui n'écoute plus le réseau » (dépôt mobile).**~~ *Commité le 26/09/2026 dans `diapason_mobile` : `20c5c9c` (`normalizeBase` ; un nom en `.ts.net` tapé sans schéma passe par https ; `host.address` n'est plus gardé du tout), `c71d3e5` (clair refusé ; la variante dev, debug ET profile, a sa copie qui permet localhost et 10.0.2.2), `216142b` (échecs distingués : « Mac injoignable. Vérifie qu'il est allumé et que Tailscale est actif sur le téléphone. », « Diapason est arrêté sur le Mac », « Appareil non reconnu par le Mac » suivi de la phrase du Mac), `f8945ff` (`openSession()` et `MeshSessionTicket.requeteOuverture()`, le formulaire que la WebView postera à l'étape 7 de la phase 3). Preuve de bout en bout, `test/mesh/live_session.dart` contre un `diapason serve` de banc à trois sockets (passerelle en http, sans relais https) : appairage par la passerelle, ticket, 303 et `Set-Cookie` HttpOnly/Secure/SameSite=strict/Max-Age=43200, `/v1/models` 401 sans le cookie et 200 avec, ticket rejoué 401. **Non vu** : l'appairage en données mobiles sur le vrai téléphone (étape 10). **Ce que la configuration réseau ne couvre pas** : `package:http` et dart:io ne la lisent pas (aucun contrôle « Insecure HTTP » dans le SDK Dart installé) ; seule la WebView y obéit.* *~~Couvert~~ le 26/09/2026 après contre-épreuve (`f6a1b52` dans `diapason_mobile`) : `refusDuTransport` refuse, avant tout envoi, toute adresse http hors de la variante dev (et, dans elle, hors de localhost, 127.0.0.1 et 10.0.2.2) — appairage, session native, import, rappels ; l'appairage sonde `/health` avant de dépenser l'invitation, et un 404 (le socket du réseau local) se dit « ce n'est pas la passerelle ».*
- `normalizeBase` : n'ajoute rien à une adresse https, et ajoute `:8001` à une adresse http sans port.
- `network_security_config.xml` : plus de trafic en clair dans la configuration de base ; `localhost` et `10.0.2.2` seulement dans la variante dev.
- `MeshApi.openSession()` signe l'échange et rend le ticket.
- Les échecs sont distingués : délai ou nom introuvable → « Mac injoignable » ; 502 → « Diapason est arrêté sur le Mac » ; 401 ou 403 → « appareil non reconnu ».

*Risque silencieux :* avec un `:8000` ajouté à une adresse https, l'appairage échoue sur un délai affiché comme « réseau », alors que l'adresse est juste.
*Preuve :* `normalizeBase('https://x.ts.net') == 'https://x.ts.net'` et `normalizeBase('192.168.0.12') == 'http://192.168.0.12:8001'` ; le vecteur de session est vérifié ; l'appairage réussit en données mobiles.

~~**7. « La télécommande était refusée, et le téléphone annonçait un succès qu'il avait écrit lui-même ».**~~ *Commité le 26/09/2026 (`0e5df84` dans `diapason_mobile`, et le commit qui barre cette ligne) : `commander(confirmer: …)` pose la question sur le téléphone avant tout envoi et rend un `ResultatTelecommande` dont le message est celui du Mac. La preuve Python lit `diapason_mobile/test/mesh/telecommande_signee.json`, deux ordres signés par le vrai `MeshApi.enveloppeDeCommande` (`tests/contract/test_telecommande_du_telephone.py`).* On change la valeur de `mesh_api.dart:155`, sans ajouter de champ : `requiresConfirmation: true`, après un dialogue de confirmation SUR LE TÉLÉPHONE (décidé). `mesh_pairing_screen.dart:241` affiche toujours le `userSafeMessage` du Mac, et `MeshController.commander` le rend.
*Risque silencieux :* `true` sans dialogue ferait du contrôle n°10 une formalité.
*Preuve :* en Python, une enveloppe `desktop.open` signée par le téléphone avec `true` passe le contrôle n°10, et avec `false` elle rend `DENIED`. En Dart, le texte affiché est égal au `userSafeMessage` simulé, y compris quand c'est un échec.

~~**8. (Facultatif, si pc-bureau rejoint le tailnet) « Le maillage tenait une adresse Tailscale pour publique ».**~~ *Commité le 26/09/2026 (branche `chantier/phase2`, `c400701`). L'IPv6 de Tailscale (`fd7a:115c:a1e0::/48`) était déjà privée pour Python (dans `fc00::/7`). Resserré après contre-épreuve (`0726116`) : le /10 est aussi le NAT des opérateurs, et `join.py` lit la même fonction. Une adresse du /10 n'est privée que si le noyau la route par l'interface du tailnet (Tailscale n'installe qu'une route /32 par pair : le téléphone part de 100.90.245.46, 100.100.1.1 part de 192.168.0.104 par en0).* `mesh/transport.py:86` reconnaît `100.64.0.0/10` comme privé.
*Risque silencieux :* sans ce changement, un envoi poussé du Mac vers le PC par Tailscale est refusé en mode `local_only`.
*Preuve :* `address_is_private('100.100.1.1')` rend `True` quand le noyau la route par le tailnet (`False` sinon, depuis `0726116`), et `8.8.8.8` reste public.

~~**9. « La page Appareils ne montrait pas les sessions ouvertes ».**~~ *~~Côté serveur, commité le 26/09/2026 (branche `chantier/phase2`, `9cf3de7`) : `GET /v1/mesh/devices/{device_id}/sessions` (`sessions`, `count`, `lastUsedAtMs` — jamais le jeton) et `POST /v1/mesh/devices/{device_id}/sessions/close` (`closed`), derrière la clé locale, refusés par la passerelle comme toute la famille `/v1/mesh/` ; `POST /v1/mesh/pairings` rend `tailnetAddress`, lu dans `[tailnet] adresse` (null tant que Carlito ne l'a pas posée ; `load_config` est en cache : la clé vaut au redémarrage suivant du serveur). `mesh_api_surface.json` et `tailnet_portee.json` régénérés dans ce commit.~~ ~~**Reste la page Appareils (frontend) et son vitest**~~ — fait le 26/09/2026 (branche `chantier/mobile`, `43c5841e`) : chaque appareil non retiré dit « N sessions ouvertes · dernière activité il y a 3 min » (le `count` et le `lastUsedAtMs` du serveur, à la minute près comme lui), « Fermer ses sessions » n'existe que s'il en a, et la phrase rendue après le clic vient du `closed` du serveur (« 1 session fermée : … devra se reconnecter. », « Aucune session n'était ouverte pour … » s'il n'en a fermé aucune) ; l'invitation montre `tailnetAddress` à côté du code, avec son bouton Copier, et distingue la clé non posée (`null`) d'un serveur qui ne connaît pas le champ. Fonctions pures dans `features/mesh/sessions.ts`, 16 vitest. Vu à l'écran (instance de test, 18500, deux appareils appairés, sessions ouvertes par `DeviceSessions`) à 1280 px et à 340 px en `?compact` sans défilement horizontal ; la fermeture a rendu « 1 session fermée » et la ligne est repassée à « Aucune session ouverte. ».* Pour chaque appareil : ses sessions, sa dernière activité, et un bouton « Fermer ses sessions » distinct de la révocation. L'adresse à saisir vient d'une clé `[tailnet] adresse`, posée par Carlito et jamais devinée. `tests/contract/mesh_api_surface.json` est régénéré dans ce même commit.
*Risque silencieux :* un instantané régénéré plus tard par une autre session, qui ne saurait pas pourquoi il a bougé.
*Preuve :* un vitest sur une fonction pure de formatage (aucun test de composant). Fermer les sessions depuis le Mac fait répondre 401 à la requête suivante.

**10. Banc sur le vrai téléphone, puis la doc.** *Le pas-à-pas est plus bas, dans « Ce que Carlito fait lui-même » → « Le banc sur le téléphone » ; la voix y est vérifiée REFUSÉE (phase 4), la dictée à sa place.* Wi-Fi coupé, on vérifie dans l'ordre : l'appairage, le bundle, le flux du chat jeton par jeton, la poignée de main `/v1/voice/live` avec l'invite micro et le voyant Android, la révocation qui coupe HTTP et WebSocket en 30 s au plus, et le Mac en veille, que l'app doit dire injoignable. Le tableau daté va ici ; `CAPABILITY_MATRIX.md` est mis à jour.
*Risque silencieux :* déclarer la phase livrée sur la foi des tests ASGI. Ni le passage du SSE à travers serve, ni la CSP `wss` dans la WebView Android, ni le micro ne se vérifient ailleurs que sur l'appareil.
*Preuve :* le tableau des mesures, daté, dans ce document.

~~Pour la phase 4 : aucune coupure automatique n'existe aujourd'hui pour `/v1/voice/live` (DÉDUIT par un lecteur, non revérifié). §78 l'exige avant d'ouvrir la voix au téléphone.~~ *Revérifié et fait le 26/09/2026 : voir la phase 4 au §3.*

#### Les contre-épreuves du côté Diapason (26/09/2026)

Quinze constats sur les étapes 1 à 4, 8 et 9. Chacun a été revérifié avant d'être traité ; un correctif porte le test qui l'aurait attrapé, et ce test échoue sans lui.

| # | Constat | Verdict | Commit |
|---|---|---|---|
| 1 | La Discussion du téléphone lisait l'écran et le presse-papiers du Mac | corrigé (plafond d'outils, perception retirée du prompt, agents refusés) | `566381d` |
| 2 | 100.64.0.0/10 est aussi le NAT des opérateurs | corrigé (route du noyau exigée) | `0726116` |
| 3 | Aucun vrai WebSocket éprouvé avec une session | tests ajoutés | `1a52f23` |
| 4 | « 30 s au plus » figé par rien | tests ajoutés | `1a52f23` |
| 5 | Le test d'Origin réussissait pour une mauvaise raison | test remplacé, deux cas ajoutés | `1a52f23` |
| 6 | Les `asyncio.to_thread` retirables sans échec (§5) | tests de battement ajoutés | `1a52f23` |
| 7 | Des tests écrivaient dans le vrai `~/.diapason` | corrigé (foyer jetable) | `71c67dd` |
| 8 | Le contrôle TRUSTED de `redeem_ticket` non éprouvé seul | test ajouté | `09be227` |
| 9 | « Fermer » sans effacer les tickets passait | test ajouté | `09be227` |
| 10 | Une clé en trop dans l'enveloppe non éprouvée | test ajouté | `09be227` |
| 11 | Plafond de corps, `sessionId`, flux HTTP, 404/405 sans test | tests ajoutés | `09be227`, `1a52f23` |
| 12 | Un refus d'argument régressé faisait pendre la suite | corrigé | `7f8e587` |
| 13 | Un port du tailnet pris faisait tomber l'API locale | corrigé | `d7f2097` |
| 14 | `/v1/agents/events` bloquait l'arrêt du serveur | corrigé | `4655deb` |
| 15 | Le bundle interroge sans relâche des routes refusées | corrigé (signal « servi par le tailnet », lectures refusées jamais envoyées) | le commit qui barre le point 4 ci-dessous |

**À dire à Carlito (constat 7)** : le vrai `~/.diapason/mesh.db` porte déjà `mesh_sessions` et `mesh_session_tickets`, vides (lu en `immutable=1`, 26/09/2026). Seule cette branche les déclare : un test l'a lancée contre le vrai foyer (`tests/cli/test_mesh_send.py` le faisait encore). Elles sont additives et sans effet sur le serveur en service ; rien n'a été touché.

#### Ce qui reste de la phase 2 — la partie mobile

Tout ceci attend que l'autre chantier ait fini dans `diapason_mobile`, et la page Appareils que le chantier du bundle ait libéré le frontend.

1. ~~**Le vecteur commun de l'enveloppe de session** (étape 2) : un cas dans `scripts/gen_canonical_vectors.py`, régénéré dans `diapason_mobile/test/mesh/canonical_vectors.json` **dans le même commit que le Dart qui le vérifie**. Seulement des entiers et des chaînes.~~ *Fait le 26/09/2026, même thème des deux côtés (`e9e60cb` ici, `f8945ff` là-bas) : deux dépôts, deux commits.*
2. ~~**Le Dart** (étapes 6 et 7) : `normalizeBase` (rien d'ajouté à une adresse https, `:8001` à une adresse http sans port), `network_security_config.xml` sans trafic en clair hors variante dev, `MeshApi.openSession()` (signe l'enveloppe, rend le ticket, poste le ticket vers `/v1/appareil/ouvrir`), les échecs distingués (injoignable / 502 / 401-403), `requiresConfirmation: true` après un dialogue sur le téléphone, et le `userSafeMessage` du Mac toujours affiché. Le jumelage par la passerelle rend encore `host.address` = l'adresse du LAN : le Dart doit l'ignorer et garder `https://atelier.tail6efbba.ts.net`, que `tailnetAddress` rend une fois `[tailnet] adresse` posée.~~ *Fait le 26/09/2026 (voir les étapes 6 et 7). Écart : `openSession()` rend le ticket sans le poster — c'est la WebView qui poste `/v1/appareil/ouvrir` (étape 7 de la phase 3), pour que le cookie soit posé dans elle ; `MeshSessionTicket.requeteOuverture()` en est la seule définition.*
3. ~~**La page Appareils** (étape 9, frontend) : sessions, dernière activité, « Fermer ses sessions » distinct de la révocation, l'adresse `tailnetAddress` à saisir — et son vitest sur une fonction pure de formatage.~~ *Fait le 26/09/2026 (voir l'étape 9).*
4. ~~**Le signal « servi par le tailnet » au bundle** (constat 15, phase 3) : sans lui, le bundle interroge sans relâche `/v1/account/status`, `/v1/triggers/poll`, `/v1/mesh/inbox`, `/v1/vie/sync/status`, `/v1/voice/live/health` et `POST /v1/context/view`, tous refusés~~ ; ~~et `crossorigin="use-credentials"` sur le lien du manifeste si la PWA doit s'installer depuis le téléphone~~. *Le manifeste, fait le 26/09/2026 (`useCredentials: true` du plugin PWA, tenu par `lib/manifeste.build.test.ts` qui lit le lien que le vrai plugin injecte) : par la passerelle de l'instance de test, `/manifest.webmanifest` rend 401 sans le cookie et 200 avec — un lien sans l'attribut est demandé en mode « omit », donc toujours sans. Le signal, fait le 26/09/2026 (branche `chantier/mobile`, `2c169cf9` ; le manifeste `b3c1df87`, le service worker `38775caf`) : servi par le tailnet = le pont natif (`estMobile`) OU l'en-tête `X-Diapason-Passerelle: tailnet`, que la passerelle pose sur chaque réponse, refus compris, et que 8000 ne pose jamais (verrouillé pour la vie de la page). `lib/tailnet.ts` retient dans `apiFetch`, avant tout envoi, TOUTE lecture que la passerelle refuse (32 gabarits et la famille `/v1/succes/`) plus `POST /v1/context/view` : `SondeNonEnvoyee`, dite une fois par route dans la console, jamais relancée par les boucles de `features/mesh/api.ts` et `features/vie/api.ts`. Une action refusée au clic part toujours : la phrase du refus est celle de la passerelle (§100). La liste est tenue par `tailnet.test.ts` contre `tailnet_portee.json` dans les deux sens (une route ouverte n'y reste pas, une lecture refusée n'y manque pas). Les boucles ne démarrent plus au téléphone (relève des déclencheurs, santé de la voix, partage d'écran, statut du compte) ; les Réglages disent « la voix n'est pas encore ouverte au téléphone » et « le compte se gère sur le Mac », les pages Appareils et Synchronisation le disent aussi (l'import Life OS reste), les Tâches ne demandent plus l'état de synchronisation. Vu le 26/09/2026 sur l'instance de test (18500, pont simulé à 375 px) : aucune route refusée n'a atteint le serveur pendant le parcours accueil → Appareils → Synchronisation → Tâches → Réglages (16 routes demandées, toutes `session` ou `ouverte`), contre 317 relèves, 107 santés de la voix, 32 lectures de la boîte et 11 statuts du compte pendant la session de bureau qui précédait ; `curl` sur 18502 montre l'en-tête sur un 200 et sur un 403, 18500 ne le porte pas.*
5. **Le banc sur le vrai téléphone** (étape 10) : à faire par Carlito, pas à pas, dans « Ce que Carlito fait lui-même » → « Le banc sur le téléphone ». Tout le reste de la partie mobile est commité (voir la table ci-dessous).

Décisions à confirmer par Carlito, prises par défaut dans ce chantier : la liste des 16 outils permis au téléphone (le courrier, les messages, `find_files` et l'écriture dans Notes, Rappels et Calendrier en sont exclus jusqu'à la phase 6) ; les agents consultables mais ni créés, ni modifiés, ni lancés depuis le téléphone ; la mémoire, l'ingestion de fichiers, la dictée et `speech/transcribe` (un clip envoyé, pas une écoute continue) sous session.

#### Les contre-épreuves du chantier mobile (26/09/2026, second tour)

Vingt et un constats sur les lots 1 à 4 (appairage, coquille, import, rappels, navigation). Chacun revérifié ; un correctif porte le test qui l'aurait attrapé, et ce test échoue sans lui (mutant nommé dans chaque message de commit). « Ici » = `chantier/mobile` ; « mobile » = `diapason_mobile`.

| # | Constat | Verdict | Commits |
|---|---|---|---|
| 1 | Le Dart postait en clair (appairage, ticket, cookie, import) vers toute adresse http, même dans l'app publiée | corrigé : `refusDuTransport`, http seulement en variante dev vers localhost / 127.0.0.1 / 10.0.2.2 | mobile `f6a1b52` |
| 2 | Un `<form method=post>` de la page du Mac pouvait emmener la coquille chez un tiers (POST sans `shouldOverrideUrlLoading`) | corrigé côté passerelle : `form-action 'self'` ; reporté côté Dart : un canal lié à l'origine (`WebViewCompat.addWebMessageListener` par `WebViewFlutterAndroidExternalApi.getWebView`) demande un banc sur la vraie WebView | ici `9275e6c7` |
| 3 | La branche « cadre » de `deciderNavigation` décidait pour des cadres que le greffon ne lui passe jamais | corrigé : branche retirée ; la CSP, seule garde, est tenue par un test Python | mobile `7ded737`, ici `9275e6c7` |
| 4 | Toute app Android pouvait ouvrir `/import` ou `/appareils` par une intention | corrigé : `flutter_deeplinking_enabled=false`, `getInitialRoute()` = « / » | mobile `2b5c612` |
| 5 | « Quitter l'appairage » laissait deux sessions de 12 h sur le téléphone | corrigé (coffre natif, cookies de la WebView) ; la fermeture côté Mac reste à la page Appareils | mobile `0220111` |
| 6 | `enregistrer` : tout type, toute taille, sans geste | corrigé : types du bundle seulement (et leur extension), 50 Mo | mobile `6ab24ef` |
| 7 | Couper le site avant l'envoi, ou sur un refus du Mac : tests verts | tests ajoutés (I4, I7) | mobile `005f20a` |
| 8 | Le bundle pouvait acquitter `naviguer` avant la montée de la page | fonction pure `naviguerAuTelephone` + tests (NDT1, PA3 ; NDT2 équivalent, tenu par l'ordre) | ici `3f05c218` |
| 9 | Fermer le dialogue de la télécommande sans « Annuler » : non éprouvé | tests ajoutés (barrière, retour) | mobile `2ee7568` |
| 10 | `NavigationCoquille` sans test | tests ajoutés (X3, X4) | mobile `f084a30` |
| 11 | Jeton du site refusé pendant l'import : non éprouvé | tests ajoutés (401, 403 ; I11) | mobile `005f20a` |
| 12 | Le cookie natif d'un Mac pouvait partir vers un autre hôte | test ajouté (SN6) | mobile `9c0a143` |
| 13 | Une habitude dite « cochée » sur toute réponse portant `habit` | corrigé : `habit.done` exigé | mobile `eb7a42b` |
| 14 | Sept gardes de la coquille sans test | tests ajoutés (C5, C1b, S4, B9, B10, B11, R3b) | mobile `88f8212` |
| 15 | Le refus de `diapason://` non figé par un vecteur | vecteur `diapason://tasks` dans les deux copies | ici `c074da42`, mobile `2605d91` |
| 16 | `test_vie_rappels` ne comparait que les noms des paramètres | corrigé (PR4) | ici `8c29ff41` |
| 17 | Signal tailnet et pont : gardes sans test | tests ajoutés (V8, V9, V11, N4, NB3, D6) ; SE1 non reproduit (la fonction pure est tenue, le recompte ne pourrait vivre que dans le composant) | ici `558cb565`, mobile `8a474da` |
| 18 | Appairage par l'adresse du réseau local, puis « Not Found » | corrigé avec le 1 (sonde avant l'invitation, 404 traduit) | mobile `f6a1b52` |
| 19 | Sans pont, le bundle servi par la passerelle envoie deux sondes refusées au premier chargement | non corrigé, dit ici : la coquille pose le pont avant tout module ; au banc AVEC pont, 0 réponse 403 sur 24 routes | — |
| 20 | FOREGROUND_SERVICE déclarée sans usage ; deux permissions d'alarme exacte | FOREGROUND_SERVICE retirée du manifeste de l'app (WorkManager 2.10.2 la déclare lui-même : l'APK ne change pas) ; les alarmes exactes, à trancher après le banc | mobile `c8d0d09` |
| 21 | Les tests de contrat lisaient l'arbre vivant du dépôt mobile | `DIAPASON_MOBILE` désigne une copie ; `docs/client-mobile.md` le dit | ici `bef119f7` |

**À dire à Carlito (constat 21)** : pendant la revue, l'arbre de `diapason_mobile` a porté tour à tour des mutants non commités d'autres sessions (`mesh_api.dart` sans le cas 502, `requiresConfirmation: false`…), chacun avec un `.mutbak`. Le runner auto-hébergé lit ce même arbre : une session de mutation doit restaurer ses fichiers avant qu'une CI ne parte.


---

### Plan de la phase 3 — La WebView

La passerelle de la phase 2 fixe le modèle de sécurité. **Le secret de session reste un cookie `HttpOnly` et n'est jamais donné au JavaScript.** Le pont ne porte donc pas de verbe `cle`, et `getBase()` rend déjà `''` hors Tauri (même origine).

~~**1. « Une citation importée puis supprimée aurait fait tomber toutes les routes de vie au démarrage ».**~~ *Commité le 25/09/2026 (`cff1f2f`), avant la 1b.* `_materialize_continuity_snapshot` teste l'existence d'une citation **y compris supprimée** avant `create_quote`, sur le modèle de `get_template`, qui refuse un identifiant existant. Ce correctif n'attend rien : il peut précéder la 1b.
*Risque silencieux (DÉDUIT) :* le plantage n'arriverait qu'au redémarrage launchd qui suit la première suppression, bien après un import réussi.
*Preuve :* importer, supprimer la citation, rouvrir `SuccesSyncStore` sur la même base : aucune exception, et la citation reste supprimée.

~~**2. « L'import perdait des coches d'habitude et des notes sans le dire ».**~~ *Commité le 26/09/2026 (le commit qui barre cette ligne, et `b9496b5` dans `diapason_mobile`).* Ce que la réalisation a ajouté au plan :
- l'horodatage de repli est **minuit UTC du jour coché**, fixe : le constructeur rejoue chaque import archivé à chaque démarrage, et un `now_ms()` aurait rajeuni la coche à chaque fois, écrasant une décoche faite depuis sur le Mac (contre-épreuve : avec `now_ms()`, `test_le_rejeu_au_demarrage_ne_rajeunit_pas_une_coche_sans_horodatage` échoue) ;
- deux motifs de plus que les quatre prévus, parce qu'aucun des quatre ne disait vrai : `dejaSurLeMac` (modèle ou citation déjà présents, même supprimés) et `habitudeAbsente` (coche d'une habitude que le Mac n'a pas) ; et les champs **raccourcis** au plafond du Mac (notes d'une tâche au-delà de 2 000 caractères) sont comptés dans `truncated` ;
- un nom de projet de plus de 200 caractères faisait tomber l'import ENTIER en 400 : il est désormais sauté et compté `tropLong` ;
- la ligne archivée ne gardait que tâches et projets (les couches fusionnaient leur résumé après l'archivage) : un second import rendait « déjà importé » avec un résumé amputé. Les couches passent par `_materialiser_import`, et le résumé entier est archivé ;
- la phrase de la route vient du résumé (`vie/resume_import.py::phrase`), et la page Synchronisation l'affiche au lieu de composer la sienne ;
- `vie_api_surface.json` n'a pas bougé : l'instantané fige les routes, pas la forme des réponses.

La contre-épreuve du 26/09/2026 a trouvé, en exécutant chaque cas dans une base de travail (`94af6ab`, et `3a3044f` dans `diapason_mobile`) :
- **l'import effaçait** une sous-tâche ajoutée sur le Mac (pierre tombale sur toutes les sous-tâches de la tâche) sous la phrase « n'efface rien sur le Mac » : chaque sous-tâche se compare désormais seule, et une absente n'est pas touchée ;
- **le rejeu au démarrage écrasait** une note et une décoche faites sur le Mac quand la sauvegarde portait un horodatage en avance (plafond « maintenant + 5 min » recalculé à chaque rejeu) : le plafond d'un import est son heure d'import, archivée ; il ramenait aussi une coche retirée par la synchronisation (pierre tombale `habit_logs` ignorée), et recréait à chaque démarrage un modèle et une citation sans `id` (identifiant désormais tiré du contenu) ;
- **le résumé disait faux** : une décoche du téléphone (clé dans `habitLogsAt` seulement) se comptait « coche » (`habitLogUnchecksImported` désormais, et la fixture commune en porte une) ; un doublon de la sauvegarde comptait deux importés (`enDouble`) ; à horodatage égal, « plus récent sur le Mac » était faux (`dejaSurLeMac`), et une tâche inchangée était réimportée avec une opération de synchronisation ; un titre de sous-tâche coupé, une sous-tâche sans `id` ou trop profonde n'étaient pas comptés (`truncated.subtasks`, `invalide`, `tropProfond`) ; les coches d'une habitude de modèle passaient avant la couche qui la crée ; « 2 suppressions … n'efface » s'accorde.

Le plan, tel qu'écrit le 25/09/2026 :
- Les coches sont importées sur l'union des clés de `habitLogs` et de `habitLogsAt`, avec un horodatage de repli.
- Chaque saut est compté par motif : `plusRecentSurLeMac`, `titreVide`, `tropLong`, `invalide`.
- Le résumé déclare les clés ignorées et pourquoi : l'état d'interface, les 5 réglages du site et `sync.deletes` (§5).
- Si la forme de la réponse change, `vie_api_surface.json` est régénéré dans ce même commit.

*Risque silencieux :* avec la copie de dev, 2 coches sur 3 disparaîtraient, et le résumé dirait « importé ».
*Preuve :* une fixture `LifeOsState.toJson()` produite par le Dart, **un seul fichier lu par pytest et par `flutter test`** :
- 3 coches, dont 1 horodatée, donnent 3 lignes ;
- un second import rend `alreadyImported: true` ;
- une note sans titre figure au résumé avec son motif.

~~**3. « Le bundle ne savait pas qu'il tournait dans un téléphone ».**~~ *Côté bundle commité le 26/09/2026 (`f0eb73e`) ; côté Flutter, avec la coquille (étape 7, `1e5ba9d` dans `diapason_mobile`) : `https://exemple.com` donne `ouvrirAilleurs` (refusé ici, confié au système), l'origine du Mac `charger`.* On crée `frontend/src/lib/natif.ts`, sur le modèle de `lib/compact.ts`.
- **Détection.** Le bundle repère `window.DiapasonNatif` (un canal JavaScript injecté avant le chargement), pose `data-diapason-mobile="1"` et exporte `estMobile`.
- **Protocole.** Requête et réponse sont identifiées par `id`, avec un délai limite.
- **Verbes :** `theme`, `enregistrer`, `ouvrirExterne`, `retour`.
- **Côté Flutter.** `onNavigationRequest` n'autorise que l'origine du Mac.

*Risque silencieux :* le canal JavaScript d'Android est exposé à **toute** page chargée dans la WebView. Un lien suivi en interne pourrait appeler le pont.
*Preuve :* des vitest sur les fonctions pures (réponse arrivée avant son attente, délai en français, identifiant inconnu ignoré). En Dart, `https://exemple.com` donne `prevent` et l'origine du Mac donne `navigate`.

Le contrat que la coquille doit tenir, tel que le bundle l'attend (26/09/2026) :
- **Canal.** Un `JavaScriptChannel` nommé `DiapasonNatif`, injecté avant le chargement. Sa présence — et elle seule — fait `estMobile` : ni la largeur, ni l'agent utilisateur.
- **Du bundle vers la coquille.** `DiapasonNatif.postMessage(JSON)` avec `{type: "demande", id, verbe, donnees}` ; `id` vaut `<préfixe>-1`, `<préfixe>-2`…, le préfixe étant tiré au chargement de la page (26/09/2026 : `b1` à chaque chargement, une réponse en route à travers un rechargement aurait résolu la nouvelle `b1`). La coquille répond par `window.diapasonNatifRecevoir(JSON)` avec `{type: "reponse", id, ok, donnees?, erreur?}`. Une réponse peut arriver avant que l'attente soit posée ; un `id` inconnu est ignoré ; une réponse arrivée après le délai ne résout rien, mais un `enregistrer` réussi en retard s'annonce encore (« Le téléphone a finalement enregistré le fichier »).
- **Liens.** Le bundle intercepte tout clic sur un `<a href>` http(s) d'une autre origine que celle du Mac et l'envoie par `ouvrirExterne` (26/09/2026 : les sources de recherche, les citations, les liens des réponses et ceux des pages d'administration étaient des `<a target="_blank">` bruts, morts dans la WebView). La coquille, elle, ne charge JAMAIS une navigation refusée vers http(s) : `onNavigationRequest` rend `prevent` et l'ouvre par `url_launcher` — un filet pour un lien que le bundle n'aurait pas vu.
- **Verbes sortants et délais.** `theme` (10 s) : `{theme, skin, fond, encre, clair}`. `ouvrirExterne` (10 s) : `{url}`, http(s) seulement, filtré avant l'envoi. `enregistrer` (120 s, parce qu'il attend une personne dans le sélecteur d'Android) : `{nom, mime, base64}` ; `ok` avec `donnees.nom` = le nom écrit (affiché tel quel) ; `ok: false, erreur: "annule"` = la personne a renoncé, rien n'est annoncé ; toute autre `erreur` est une phrase affichée.
- **Verbes entrants.** La coquille envoie `{type: "demande", id, verbe: "retour"}` ; le bundle répond `ok: true, donnees: {traite}`. `traite: false` n'est pas un échec : la coquille fait alors `goBack()`, puis passe en arrière-plan. Depuis l'étape 5 (`5e87751`), la barre latérale s'y inscrit : un tiroir ouvert se ferme et le bundle répond `traite: true` ; sinon `false`. Un verbe entrant inconnu reçoit `ok: false, erreur: "verbeInconnu"`. **`naviguer`** (ajouté le 26/09/2026, étape 9 — la liste fermée s'élargit, décision prise dans ce chantier) : `{path, selection?}` → le bundle refuse tout chemin hors de `PATHS` (`readShellNavigation`), navigue, et ne répond `ok: true, donnees: {path, selection}` qu'une fois la page MONTÉE (8 s au plus, sinon `ok: false` avec sa phrase) ; `erreur: "pasPret"` si rien n'est inscrit. Délai côté coquille : 10 s.
- **Aucun verbe ne rend un secret.** La liste est fermée par un test (`natif.test.ts`) : l'élargir est une décision.

**4. « Hors de Tauri, des pages annonçaient un succès qui n'avait pas eu lieu ».** *Côté bundle commité le 26/09/2026 : exports et liens (`70ba5de`), lectures serveur (`4be917d`, `f8ea8bf`), gestes (`77eeac4`), et un correctif de construction (`c71df92`). Reste, à l'étape 7 : la vraie écriture dans Téléchargements, vue à la main.* *Vue sur l'émulateur le 26/09/2026 par le verbe lui-même (`enregistrer` posté dans la vraie WebView) : « banc-coquille.txt », puis « banc-coquille (1).txt » — le nom renommé par MediaStore est celui rendu au bundle. Pas vu : un export lancé depuis l'interface du bundle (PDF d'une pile).*
- Les 4 téléchargements `blob:` (`photosExport.ts:72-80`, `exportVisuel.ts:85-87`, `features/vie/api.ts:802`, `SettingsPage.tsx:449`) passent par le verbe `enregistrer` et ne réussissent que sur la réponse de Flutter.
- `impressionDisponible` rend `false` quand `estMobile` (`compte.ts:989`).
- `get_cloud_key_status` et `get_inference_source` lisent une route serveur en lecture seule, au lieu de rendre `{}` et `ollama` inventés (`api.ts:17-27`, `:1302-1312`).
- Les messages anglais « desktop app only » passent en français.
- Le mode gestes est caché quand `estMobile` : il ouvrirait la caméra **du téléphone** (`useModeGestes.ts:280`).
- Les commandes Tauri sans effet (focus, réglette, dictée en direct) ou déjà doublées par HTTP (santé, modèles, transcription) ne demandent rien.

*Risque silencieux :* « exporté » alors qu'aucun fichier n'existe ; une source d'inférence qui contredit celle du Mac.
*Preuve :* un export mobile ne rend un nom qu'après un `enregistrer` confirmé, et `null` sur refus. `getInferenceSource()` hors Tauri lit le serveur. À la main, une pile exportée en PDF apparaît dans Téléchargements.

Ce que la réalisation a appris ou ajouté (26/09/2026) :
- les routes serveur sont `GET /v1/cloud/keys` (`{keys: [{key, set}]}`, jamais une valeur) et `GET /v1/inference/source` (l'`inference.json` de l'app, Ollama s'il manque, hôte sans `user:mot@`), synchrones parce que le trousseau passe par `security`. La phase 2 devra les classer dans `tailnet_portee.json` : lecture seule, sans secret. La liste des noms de clés est gardée contre celle de `lib.rs` par un test ;
- la palette lit l'état des clés partout, mais « Retirer » n'existe que dans l'app de bureau, la seule qui écrive le trousseau ; les Réglages disent un échec de lecture au lieu de laisser « Ollama » affiché (vu à l'écran : un 401 laissait la valeur initiale se faire passer pour celle du Mac) ;
- les liens externes passent aussi par la coquille (`ouvrirExterne`) : `window.open` est muet dans la WebView d'Android, et « Imprimer » la clé du compte n'est pas proposé ;
- l'audit des autres commandes Tauri (focus, réglette, dictée en direct, notifications, mise à jour, accessibilité, pointeur, dialogues) les a trouvées toutes gardées par `isTauri()` : aucune ne demande rien hors de Tauri ;
- contre-épreuve du 26/09/2026 : les Réglages inventaient encore l'état des clés hors du bureau (seule la palette avait été corrigée), lisaient la liste des modèles sur `localhost:11434` DEPUIS LA PAGE (le téléphone lui-même ; c'était aussi la cause du « serveur d'essai qui a lu l'Ollama de la machine ») et affichaient « Ollama intégré » au-dessus d'un échec de lecture (`5c75792`) ; la route des clés lisait chaque SECRET pour dire « présente » — elle ne lit plus que les attributs (`97d3d7d`, demande d'accès du trousseau sur le Mac DÉDUITE, pas observée) ; la source d'inférence pouvait rendre un secret (`f6d2be7`) ; « exporté » n'était gardé par aucun test des appelants et nommait un fichier que la coquille n'avait pas nommé (`aab4c83`) ; les liens `<a>` bruts des réponses et des pages d'administration étaient morts dans la WebView (`7b493ed`) ; et le bundle montait au téléphone les deux hôtes du Mac, dont celui qui VIDE la boîte du maillage (`86bf95a`) ;
- **piège de construction** : `document.documentElement?.getAttribute?.('lang')` écrit en valeur par défaut de paramètre était abaissé par esbuild (cible de Vite, safari14) en une référence hors de portée — « n is not defined » dans le bundle, vitest vert. Vu à l'écran, pas par les tests ; `locale.build.test.ts` construit désormais le vrai fichier ;
- vu à l'écran le 26/09/2026, instance de test sur 127.0.0.1:18100 et pont natif simulé par une page de banc hors dépôt, à 375, 340 et ~700 px : `data-diapason-mobile="1"`, le thème envoyé au chargement puis à chaque changement (Ardéchine : `clair: true`, fond `#beb3a1`), l'export JSON du Bilan annoncé avec le nom rendu par la coquille et silencieux sur `annule`, la sauvegarde des conversations des Réglages, la phrase des gestes à la place du panneau (le panneau reste en `?compact` à 340 px), la source d'inférence du Mac affichée et son refus d'écriture en français. Pas vu : l'export PDF d'une pile et d'un visuel (ni photo ni graphique sur l'instance de test ; même chemin, couvert par les tests).

~~**5. « À 390 px, la barre latérale cachait deux tiers de la Discussion et ne se refermait jamais ».**~~ *Côté bundle commité le 26/09/2026, avec l'adaptation au téléphone de toutes les pages décidée au §4 (douze commits, de `5e87751` à `5117cfa`, et celui qui barre cette ligne). Reste, à l'étape 7 : revoir chaque page dans la vraie WebView d'Android — survol, clavier virtuel et barre d'état ne se simulent pas.* *Le 26/09/2026, sur l'émulateur (WebView 124) : la Discussion, le tiroir (le retour d'Android le ferme), les Tâches ; le reste des pages n'a pas été revu, ni sur un vrai téléphone.*

Ce que la réalisation a ajouté au plan :
- **le téléphone est un mode, pas une largeur** : variant `mobile:` (`data-diapason-mobile`, posé par le pont), à côté de `max-sm:` et `compact:` sur chaque action révélée au survol — `max-sm:` s'éteint à 640 px, un téléphone à l'horizontale en fait 740 à 915 (`0239897`). Le menu « ⋯ » des discussions, la case et la légende d'une photo et Copier n'avaient aucune exception ;
- `barreApresNavigation` laisse le tiroir ouvert dans deux cas qui ne sont pas des choix : entrer dans les Réglages et en sortir par « Retour » (le tiroir change de contenu). Le retour d'Android ne ferme qu'un tiroir, jamais une colonne (`lib/barre.ts`, 16 cas vitest) ;
- **cibles de 40 px au doigt**, posées une fois dans `index.css` pour le seul mode `mobile` ; un contrôle dessiné (interrupteur, case) garde sa taille et étend sa surface par un pseudo-élément (`cible-etendue`) — vu à l'écran : porté à 40 px, l'interrupteur devenait une goutte (`66feb8d`) ;
- ce qui flotte au-dessus des pages a sa réserve : `--bande-barre-fermee` (le bouton de la barre couvrait le surtitre de chaque page et le coin des fenêtres modales) et `--degagement-barre-fermee` (le titre de la Discussion) (`dfa9997`) ;
- le panneau Système couvrait la Discussion au premier lancement : il ne s'ouvre seul que là où il est une colonne (`32aac52`) ;
- défauts de page trouvés en regardant : une adresse longue faisait défiler tout le fil (`ee44ed1`), les chemises 3D des Notes et des Projets débordaient de 13 et 7 px (`e77d7f1`), les Réglages écrasaient leurs étiquettes (`5b86ba7`), ✕ de la fenêtre Photos sortait du cadre (`639ff45`), « Synchroniser » était rogné dans les Sources (`18e77c4`), les Journaux cassaient leurs boutons et parlaient anglais (`ae4dc05`), Copier couvrait les commandes de Démarrer (`5117cfa`) ;
- le cas téléphone est écrit dans `mini-panneau-responsive.md` (règles 6 à 9) et résumé dans `CLAUDE.md`.

**Pages vues le 26/09/2026.** Instance de test (`127.0.0.1:18100`, moteur factice, données créées par l'API : 8 tâches, 6 projets — un par forme —, 3 habitudes, 2 notes, 1 compte et 3 transactions, 1 pile de 3 photos, 3 discussions dont un tableau large, du code et une adresse longue), dans le Chromium du banc. « Vue » = regardée à l'écran ; « mesurée » = `scrollWidth` du document égal à sa largeur, aucun défilement horizontal hors des défileurs voulus (bloc de code, tableau, onglets des Finances, colonnes du pipeline) et, à 375 px, aucune cible de moins de 40 px hors curseurs et contrôles à surface étendue. 375 px : pont natif simulé (un faux canal `DiapasonNatif` injecté avant le bundle). 340 px : `?compact`, sans pont. 1280 px : sans pont, barre ouverte.

| Page | 375 px (téléphone) | 340 px (mini-panneau) | 1280 px (bureau) |
|---|---|---|---|
| Discussion (compositeur, bulles, cartes d'outils, menus « Demander » et modèle, sauteur, menu « ⋯ ») | vue | vue | vue |
| Tableau de bord | vue | mesurée | mesurée |
| Planificateur | vue | mesurée | mesurée |
| Tâches (Liste, Semaine, Mois, formulaire) | vue | mesurée | mesurée |
| Projets (liste, et Liste, Arbre, Carte, Pipeline, Réseau — Graphe et Liste —, Cycle ; fenêtre Photos et pile ouverte) | vue | mesurée | vue (fenêtre Photos) |
| Finances (et formulaire de transaction) | vue | mesurée | mesurée |
| Habitudes | vue | mesurée | mesurée |
| Notes (liste et éditeur) | vue | mesurée | mesurée |
| Bilan | vue | mesurée | mesurée |
| Réglages | vue | vue | vue |
| Agents (et choix d'un modèle d'agent) | vue | mesurée | mesurée |
| Sources de données (trois onglets) | vue | mesurée | mesurée |
| Journaux | vue | mesurée | mesurée |
| Démarrer | vue | mesurée | mesurée |
| Appareils | vue | mesurée | mesurée |
| Vue d'ensemble du système (le tableau système) | vue | mesurée | mesurée |
| Synchronisation | vue | mesurée | mesurée |
| Panneau Système de la Discussion | vue (fermé au lancement) | — | vue (ouvert au lancement) |

Pas vu : la palette ⌘K (sans clavier sur un téléphone ; le choix du modèle a son menu), les toasts, un export réel.

**Revus par la contre-épreuve du 26/09/2026** (instance de test sur `127.0.0.1:18300`, avant/après) : le tableau ci-dessus avait été rempli avec des noms courts, le thème sombre et le seul `?compact` à 340 px. En téléphone simulé à 340 px, en Ardéchine, avec un nom de catégorie de 42 caractères, il manquait : les cases de TasksBoard en carrés vides de 40 px (`a5f5995`), le Mois qui débordait (même commit), les boutons des chemises qui se recouvraient et une catégorie longue hors de l'écran (`ba177fd`), « Grille De Septembre 20… » (`3525c3c`), les aides des Photos à la souris (`9b28268`), et dans les Réglages les pastilles grises, « Ollama intégré » sur un échec et le bouton noir sur noir (`5c75792`). Un banc qui déclare une page « mesurée » la mesure désormais **en mode téléphone à 340 px ET en Ardéchine, avec des noms longs** : la police d'affichage de l'Ardéchine est ce qui a révélé les colonnes de grille `auto` (voir `mini-panneau-responsive.md`, règle 10).

Le plan, tel qu'écrit le 25/09/2026 :
- `sidebarOpen` démarre fermé sous `md` (`store.ts:367`), lu par `matchMedia` une seule fois à l'amorçage, sans `innerWidth` (règle 2 du mini-panneau).
- La fonction pure `barreApresNavigation()` referme la barre après une navigation.
- Le retour Android ferme d'abord la barre.
- `max-sm:opacity-100` sur le menu « ⋯ » de `ConversationList.tsx:287` et sur `PilesPhotos.tsx:1681` et `:1698`.
- Le cas téléphone s'ajoute à `docs/development/mini-panneau-responsive.md`.

*Risque silencieux :* supprimer une discussion devient impossible au doigt (§82). Une correction faite sur la largeur casserait le mini-panneau, où « compact » est un mode.
*Preuve :* un vitest sur `barreApresNavigation`, puis chaque page de vie vue dans la vraie WebView, marquée « vue » dans le document. Un banc Chromium ne suffit pas pour le survol.

~~**6. « La coquille ignorait l'apparence choisie dans la WebView ».**~~ *Côté bundle commité le 26/09/2026 (`07cf899`) : le thème part au chargement, à chaque changement, et à chaque bascule d'Android quand l'apparence est « Système ». ~~Côté Flutter (`SystemUiOverlayStyle`, mémoire pour le démarrage à froid) : étape 7.~~ Fait avec la coquille (`1e5ba9d` dans `diapason_mobile`) : `ThemeCoquille.styleSysteme`, `MemoireCoquille.retenirTheme` ; vu sur l'émulateur (Ardéchine peint la barre d'état).* À côté de `reglette_set_theme` (`App.tsx:180`), le bundle envoie le verbe `theme` avec `{theme, skin, fond, encre, clair}`. Flutter en tire `SystemUiOverlayStyle` et le fond de ses écrans natifs, et mémorise le dernier thème pour le démarrage à froid.
*Risque silencieux :* une barre d'état illisible en Ardéchine si le drapeau `clair` manque, et un flash blanc au lancement en Phosphore.
*Preuve :* un vitest vérifie que `terminal/ardechine` donne `clair=true`. En Dart, un thème reçu puis relu donne le même fond.

~~**7. « Il n'y avait pas de coquille pour porter le bundle » (dépôt mobile).**~~ *Commité le 26/09/2026 dans `diapason_mobile` : `f341bb0` (sonde `/health`, `MeshController.ouvrirSession`) et `1e5ba9d` (la coquille, `lib/coquille/`, et le canal Kotlin `diapason/coquille`). Corrigé après contre-épreuve : cadres et formulaires (`7ded737`, et `9275e6c7` ici), liens profonds (`2b5c612`), sessions laissées par « Quitter l'appairage » (`0220111`), `enregistrer` borné (`6ab24ef`), sept gardes éprouvées (`88f8212`). La racine de l'app est la coquille ; Life OS (`/life-os`), l'Entité et l'appairage restent derrière son menu natif (barre de 40 px), rien n'est retiré. Ce que la réalisation a ajouté ou changé :*
- *Pas d'`image_picker` ni d'`url_launcher` (ni de `file_picker`) : leur partie Android exige `androidx.browser` 1.9.0, `androidx.activity` 1.12.4, `androidx.core` 1.18.0 et `exifinterface` 1.4.2, absents du cache Gradle hors ligne. Le canal Kotlin de `MainActivity` fait les cinq gestes sans dépendance nouvelle : `ACTION_VIEW`, `ACTION_PICK_IMAGES`, `ACTION_OPEN_DOCUMENT`, `ACTION_IMAGE_CAPTURE` par un FileProvider propre (`FichiersCoquille`, `cache/coquille-photos` seulement ; aucune permission CAMERA déclarée), et `MediaStore.Downloads` (le sélecteur « Enregistrer sous » avant Android 10).*
- *Session : une session de moins de 6 h (la moitié des 12 h) est REPRISE au démarrage à froid et à la reprise — sinon une session par lancement s'accumulait sur la page Appareils ; au-delà, elle est renouvelée (la page se recharge). Un 401 du document sur un cookie repris rouvre UNE session ; sur une session fraîche, c'est un écran d'échec, pas une boucle.*
- *Le micro : webview_flutter_android 4.12.0 ne transmet pas l'origine d'une demande de permission ; la coquille compare la page principale (seule à naviguer) à l'origine du Mac, et la passerelle pose déjà `microphone=(self)` pour les cadres.*
- *Deux défauts vus seulement dans la vraie WebView (émulateur Android 15, WebView 124), corrigés avant le commit : le `MeshController` gardé par la coquille était jeté par son fournisseur (il regarde la Life OS) — l'appairage fait depuis l'écran natif ne basculait jamais vers le bundle ; et Android donne `onReceivedHttpError` AVANT `onPageStarted` — effacer le statut au début de page laissait « Ouvre Diapason depuis l'app » à l'écran après des sessions fermées depuis le Mac.*
- *Vu sur l'émulateur, contre un `diapason serve` de banc (`adb reverse` vers la passerelle) : appairage par l'écran natif, bundle affiché avec `data-diapason-mobile="1"`, `document.cookie` sans le cookie de session, aucun service worker ; les verbes (enregistrer, verbeInconnu, ouvrirExterne refusé pour `intent:`, thème Ardéchine peint la barre d'état) ; une navigation vers example.com laisse la page du Mac et ouvre Chrome ; caméra refusée sans invite ; micro : invite RECORD_AUDIO d'Android ; sélecteur PDF annulé deux fois puis rouvert ; photo prise jointe à l'`<input>` (74 653 octets) ; retour : tiroir, puis historique, puis arrière-plan (même processus à la reprise) ; serveur arrêté → « Mac injoignable », Réessayer → le bundle ; sessions fermées côté Mac → une session rouverte. `test/coquille/live_coquille.dart` refait le parcours de session contre la passerelle. **Non vu** : la variante release, un vrai téléphone, la voix.*
- *À dire à Carlito : l'APK de banc, construit avec `config/secrets.json` comme toute construction de `tool/flutter_avec_secrets.sh`, a lancé la synchronisation Life OS existante au démarrage : l'émulateur a envoyé des `GET https://carlitoportfolio.com/lifeos-api.php` pendant une quinzaine de minutes (tous rendus 503 par le site, aucun `POST` journalisé ; aucune donnée Life OS modifiée dans l'émulateur). L'app a été désinstallée et l'émulateur (lancé en `-read-only`) arrêté.*

Le plan, tel qu'écrit :
- **Chargement.** La coquille sonde `/health` avant `loadRequest` ; sans réponse, elle affiche l'écran natif « Mac injoignable ». Elle ouvre ensuite la session (phase 2) et fait un POST du ticket vers `/v1/appareil/ouvrir`.
- **Micro.** `onPermissionRequest` n'accorde le micro qu'à l'origine du Mac, après `RECORD_AUDIO`, et refuse la caméra.
- **Fichiers.** `setOnShowFileSelector` ouvre une feuille native Appareil photo / Galerie / Fichiers (paquets `image_picker` et `file_picker` à ajouter — écarté, voir ci-dessus : un canal Kotlin).
- **Retour.** `PopScope` interroge d'abord le verbe `retour`, puis `goBack()`, puis passe l'app en arrière-plan.
- **Liens externes.** `url_launcher` — pour le verbe `ouvrirExterne` ET pour toute navigation refusée vers http(s), jamais chargée dans la WebView.
- **Divers.** SafeArea ; débogage de la WebView en variante dev seulement ; service worker **désinscrit** pour l'origine mobile : le bundle est toujours exactement celui du serveur. *Côté bundle, fait le 26/09/2026 : le plugin PWA n'injecte plus `registerSW.js` (`injectRegister: false`), qui réinscrivait le service worker à CHAQUE chargement, téléphone compris — une désinscription faite par la coquille n'aurait tenu qu'un chargement. `main.tsx` l'inscrit à `load` comme avant sur le Mac et le mini-panneau, et, servi par le tailnet, désinscrit ce qui l'était et vide les caches `workbox-*` (`lib/serviceWorker.ts`). Vu dans deux iframes de l'instance de test : sans pont, `register('/sw.js', {scope: '/'})` ; avec le pont, `getRegistrations` puis `unregister`, aucune inscription. La coquille n'a donc rien à désinscrire elle-même, sinon par prudence au premier lancement.*

*Risque silencieux :* sans sélecteur de fichiers, « joindre » ne fait **rien**, sans erreur. Accorder toute demande de permission ouvrirait le micro à n'importe quelle page (§78). Sans sonde, un bundle en cache s'affiche hors de portée du Mac et chaque action échoue une à une.
*Preuve :* des tests Dart purs (permission, navigation, source du fichier selon `acceptTypes`). À la main : joindre un PDF, photographier dans une pile, le bouton retour, le Mac éteint.

~~**8. « L'import depuis le téléphone pouvait écraser ce que le téléphone avait écrit » (dépôt mobile, écran natif unique).**~~ *Commité le 26/09/2026 dans `diapason_mobile` : `7c5fc5b` (la session native) et `b18d7ca` (l'import). Corrigé après contre-épreuve : https exigé hors variante dev (`f6a1b52`) ; la coupure du site et le jeton refusé éprouvés (`005f20a`), le cookie natif lié à son Mac (`9c0a143`), le drapeau d'import à travers « Quitter l'appairage » (`8a474da`). Rien à changer côté Diapason : la route et la fixture commune existaient (étape 2). Ce que la réalisation a ajouté ou changé :*
- *`SessionNative` : le Dart ouvre SA session (même enveloppe signée, même `POST /v1/appareil/ouvrir` sans suivre le 303), garde le cookie dans le trousseau, le reprend sous 6 h, rouvre UNE fois sur un 401. Elle envoie `Origin: https://<Host>` : la passerelle l'exige sur toute écriture — contre-épreuve sur le banc, sans lui l'import rend « Origine refusée par la passerelle. ».*
- *Écart au plan : `_bootstrapFromServer` est CORRIGÉ, pas seulement évité. Il remplaçait l'état local à chaque démarrage : la tâche écrite sur le téléphone seul aurait disparu au lancement, avant qu'on touche le bouton d'import. Il fusionne désormais (`mergeRemoteSnapshotIntoLocal`, pierres tombales comprises).*
- *`rassemblerPourImport` = lecture FORCÉE du site fusionnée (révision ignorée : l'import doit être sûr d'avoir tout), puis envoi au site ; les deux lèvent au lieu de se taire. Un site en 503 ou un jeton refusé : rien ne part vers le Mac. Sans jeton dans la construction, l'écran le dit avant le bouton et seul le téléphone part.*
- *Le drapeau est `MeshStore.importLifeOs` (phrase, résumé, heure) ; `NetClient(coupee:)` lève `SyncCoupee` avant tout envoi, et le démarrage ne lit plus le site. Un Mac qui répond sans résumé ne confirme rien.*
- *L'écran « Importer la Life OS » est dans le menu de la coquille (`/import`).*
- *Banc réel (`test/import/live_import.dart`, `diapason serve` à trois sockets, foyer jetable, site PHP non contacté) : la fixture commune rend « Importé : 1 tâche, 1 projet, 1 habitude, 3 coches d'habitude, 1 décoche d'habitude, 1 note, 1 modèle, 1 citation. Non importé : 1 tâche (trop long), 1 habitude (invalide), 1 note (sans titre)… », relue sur le Mac ; le second import dit « déjà été importée ». **Non vu** : l'import depuis le vrai téléphone et le vrai site (étape 11 de Carlito).*

Le plan, tel qu'écrit :
1. `_pullSnapshotFromApi` (`life_os_controller.dart:524`) puis `mergeRemoteSnapshotIntoLocal`, **jamais** `_bootstrapFromServer` (`:329`), qui écrase l'état local.
2. `_pushSnapshotToApi` (`:588`).
3. POST de `LifeOsState.toJson()` vers `/v1/vie/import/legacy` par la session d'appareil.
4. Affichage du résumé **rendu par le Mac** (§100).
5. Un drapeau dans `MeshStore`.
6. Seulement ensuite : désactivation de la synchronisation PHP.

*Risque silencieux :* couper le PHP avant un import confirmé perd les écritures faites entre-temps. Appeler le bootstrap efface le local.
*Preuve :* en Dart, un état local portant une tâche absente du site part vers le Mac avec les deux. La fixture commune de l'étape 2 est relue des deux côtés.

~~**9. « Les rappels et la navigation du maillage dépendaient de la Life OS qui part ».**~~ *Commité le 26/09/2026 : la navigation (`cf67fb5` ici, `7e8029b` dans `diapason_mobile`), les rappels (`4e9de13` ici, `943cacc` là-bas). Corrigé après contre-épreuve : `naviguerAuTelephone` (`3f05c218`), les gardes du signal et du pont (`558cb565`), le guichet (`f084a30` là-bas), l'habitude « cochée » seulement si le Mac la rend cochée (`eb7a42b` là-bas), `diapason://` figé (`c074da42` ici, `2605d91` là-bas), les paramètres des rappels (`8c29ff41`). Ce que la réalisation a ajouté ou changé :*
- *Navigation : `mesh_routes.dart` rend un `CibleReact` (table `_chemins` = `PATHS`), la coquille demande l'écran par le verbe `naviguer` (voir le contrat ci-dessus) et `MeshExecutor` ne rend SUCCESS que sur « page montée » — FAILED/`NOT_DISPLAYED` avec la phrase du téléphone sinon, rien demandé devant l'écran « Mac injoignable ». Côté bundle : `NavigationDuTelephone`, `lib/pagesAffichees.ts` (l'effet d'un `PageAffichee` autour de chaque page de vie, qui ne part jamais pour une page restée derrière son `Suspense`). Le fichier de vecteurs commun est `frontend/src/features/mesh/vecteurs_routes.json`, écrit à la main (20 routes, 10 refusées), copié à l'octet côté mobile ; `test_routes_du_maillage.py` exige les deux copies égales, Python d'accord sur chaque refus et les chemins Dart égaux à `PATHS`. `MeshController` ne regarde plus la Life OS (il était reconstruit à chaque tâche modifiée). Vu dans le vrai bundle construit (banc 18530, faux `DiapasonNatif` posé avant les modules) : trois pages répondent ok en 13 à 25 ms, titre déjà dans le document ; `/settings` refusé avec sa phrase. Pas vu : un morceau de page lent.*
- *Rappels, SEULEMENT une fois l'import confirmé : `etatDesRappels` tire un `LifeOsState` de trois lectures de `/v1/vie` (tâches ouvertes TOUTES dates — écart : pas « du jour » seulement, le planificateur prévoit 14 jours d'avance —, habitudes, 120 jours de coches) par la session native ; un Mac injoignable ne touche à AUCUN rappel posé. Preuve : `etat_rappels.json` (écrit par le Dart) importé par la vraie route et relu par `scripts/gen_vie_rappels.py` → `vie_rappels.json` ; 12 tests Dart exigent les mêmes jours, heures, priorités, reports, sous-tâches, `reminderTime` et jours dus ; `test_vie_rappels.py` exige le fichier identique à ce que les routes rendent.*
- *« Marquer fait » et la coche d'une habitude vont au Mac avec un `opId` ; injoignable ou 502 → en file, annoncé « En attente du Mac », jamais compté fait ; au retour, même `opId`, « fait » seulement si le Mac rend la tâche faite. L'annonce passe par le plugin déjà initialisé, sur un identifiant épargné par la replanification (`idFaitsDuMac`) — sinon « en attente » était effacé aussitôt affiché. Toucher un rappel ouvre la page dans la coquille ; reporter depuis une notification « n'est pas encore relié au Mac » et le dit (écart : non porté vers `/v1/vie/tasks/{id}/reschedule`).*
- *Banc réel (`test/rappels/live_rappels.dart`) : heures identiques par la passerelle ; « Marquer fait » hors réseau laisse la tâche ouverte sur le Mac ; au retour, « est faite sur le Mac » et elle ne sonne plus. **Non vu** : une notification réelle sur un téléphone, la tâche de fond des 12 h.*
- *Relevé au banc, hors de ce chantier : deux fixtures importées l'une après l'autre partageaient un identifiant de sous-tâche (`sous-arrosoir`) sous deux tâches différentes ; la seconde a été comptée « une version plus récente est sur le Mac » à horodatage égal. À vérifier côté import (identifiant de sous-tâche global ou par tâche ?).*

Le plan, tel qu'écrit :
- `mesh_executor` exécute `app.navigate` et `app.show_resource` sans `LifeOsController` : il traduit la route du maillage en chemin React dans la WebView, avec un **fichier de vecteurs commun** à `routes.ts` et à `mesh_routes.dart`.
- Le planificateur de notifications (`notification_scheduler.dart:47`, `:82`, `:244`) lit `/v1/vie` au travers d'un adaptateur (tâches du jour, `reminder_time` des habitudes).
- « Marquer fait » hors réseau est mis en file et affiché « en attente ».

Les approbations poussées, le partage et le verrou restent en phase 5.
*Risque silencieux :* retirer la Life OS sans adaptateur coupe les rappels sans rien dire (§5). Une table de routes mal portée fait acquitter une navigation vers une page qui n'affiche pas la cible, ce qui est un faux SUCCESS côté émetteur.
*Preuve :* l'adaptateur rend les mêmes heures que l'ancien `LifeOsState` sur une fixture ; « Marquer fait » hors ligne n'est jamais compté fait ; `test_mesh_client_contract.py` reste vert.

**10. « L'Entité restait alors que la Discussion était là ».** Seulement une fois la Discussion servie et vérifiée à l'étape 7. On retire `entite_*`, `admin_*`, `secret_admin_listener`, `entite_morph` et ses ressources, `speech_to_text` et `flutter_tts`, ainsi que les `<queries>` du manifeste. La tâche `entite-veille-unique` est **annulée** par `cancelByUniqueName`, puis son canal de notification est supprimé. Le patron de `entite_file_attente.dart` est recopié avant suppression.
*Risque silencieux :* une tâche Workmanager simplement retirée du code reste inscrite dans le système.
*Preuve :* `flutter analyze` propre, et plus aucune tâche `entite` listée après installation.

**11. « Nocturne et la Life OS native survivaient à l'import ».** Seulement après le résumé d'import confirmé à l'étape 8. On retire `life_os_*` (écran, contrôleur, fusion, modèles, stockage), `net_client`, le neumorphisme, liquid, les shaders, les polices, les paquets associés et la partie PHP d'`app_config`. Selon le décompte d'un lecteur, non revérifié, environ 6 000 des 22 310 lignes de Dart restent.
*Risque silencieux :* retirer `life_os_models` avant l'import rend les données du téléphone illisibles.
*Preuve :* `flutter analyze` sans import mort, et `flutter test` vert.

---

### Ce que Carlito fait lui-même

**Pendant la phase 1b**
- Après le commit de la migration du fichier (1b, étape 5) : `launchctl kickstart -k gui/$(id -u)/com.diapason.serve`, puis ouvrir une pile de photos dans Projets et vérifier que les images s'affichent.
- Après les commits du bundle et de la réglette (étapes 9 et 10), **dans cet ordre** : serveur relancé d'abord, puis `./scripts/install-desktop.sh`. Dans l'ordre inverse, la fenêtre neuve appellerait `/v1/vie` sur l'ancien serveur.
- Puis, une fois : ouvrir le mini-panneau par une icône de la réglette, et si la page est vide, **recharger** (ou cliquer une seconde fois). PLAUSIBLE, non vérifié (25/09/2026) : l'origine `127.0.0.1:8000` a un service worker (`VitePWA`, `registerType: 'autoUpdate'`) dont la `NavigationRoute` sert l'`index.html` précaché. Le premier `/vie/tasks` après la mise à jour peut donc charger l'ANCIEN bundle, qui ne connaît que `/succes/*` et n'a pas de route « * » : un module vide, une seule fois, le temps que le nouveau service worker prenne la main. La preuve attendue : une icône montre sa page au second essai au plus tard.

**Marche arrière, si le renommage doit être défait** (contre-épreuve du 25/09/2026). Restaurer la sauvegarde ne suffit pas : ses chemins de photos sont ABSOLUS vers `…/succes-photos/`, que la migration a renommé ; et l'ancien code, ne trouvant plus `succes.db`, en créerait une vide (ouverture `rwc`). Dans cet ordre :
1. `launchctl bootout gui/$(id -u)/com.diapason.serve` (le serveur ne doit plus rien écrire).
2. Mettre `~/.diapason/vie.db`, `vie.db-wal` et `vie.db-shm` de côté (dans `backups/`, jamais à la corbeille).
3. Copier `backups/succes.db.avant-vie-AAAAMMJJ` sous le nom `~/.diapason/succes.db`.
4. Renommer `~/.diapason/vie-photos` en `succes-photos`.
5. Seulement alors, remettre l'ancien code, puis `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.diapason.serve.plist` (voir `docs/deployment/launchd.md`).

Toute écriture faite après la migration (tâche, note, photo) est perdue par cette voie : elle n'existe que dans la `vie.db` mise de côté. Le nouveau code, lui, n'a pas besoin de cette procédure : il relit une `succes.db` restaurée et la re-migre.
- Page Appareils : oublier l'ancien « Mon téléphone » (Android, vu le 18 août) et l'appareil dont le nom contient « Succès ». Oublier aussi le PC Windows (déclaré en 1.0.0, vu le 29 août) : il ne sert plus que de CI (décidé le 25/09/2026).

**Avant la phase 2, dans cet ordre**
1. Créer le compte Tailscale (offre Personal gratuite) avec l'identité de son choix, et utiliser la même sur le téléphone.
2. Installer la variante « Standalone » pour Mac (DÉDUIT : moins bridée que celle de l'App Store), autoriser l'extension système et la configuration VPN, puis installer la CLI depuis le menu Tailscale. `tailscale status` doit montrer une adresse 100.x.
3. Console Tailscale → Machines → le Mac : le nommer **atelier** **avant** d'activer HTTPS, parce que ce nom sera publié dans les journaux publics des certificats. Puis « Disable key expiry », sinon le Mac quitte le tailnet sans bruit au bout de 180 jours.
4. Console → DNS : vérifier que MagicDNS est actif, renommer le tailnet si voulu, puis « HTTPS Certificates » → Enable.
5. Console → Access controls : retirer le bloc `nodeAttrs` qui accorde `funnel`, s'il y figure.
6. Réglages du Mac : empêcher la mise en veille sur secteur, écran éteint.
7. Android : installer Tailscale avec la même identité ; « VPN permanent » est facultatif. Si les noms `.ts.net` ne se résolvent pas, passer le DNS privé sur Automatique (DÉDUIT).
8. Test : Wi-Fi coupé, `http://<nom>:8001/` rend un 404 JSON, rien de plus.

**Pendant la phase 2** — le côté Diapason est prêt (branche `chantier/phase2`) ; dans cet ordre, **une fois la branche fusionnée dans `main`** (le LaunchAgent lance le code de l'arbre principal) :
1. Console Tailscale → DNS → « HTTPS Certificates » → **Enable** (pas encore fait au 26/09/2026). Rien de ce qui suit ne sert avant.
2. Dans `~/.diapason/config.toml`, poser l'adresse, jamais devinée par le code :
   ```toml
   [tailnet]
   adresse = "atelier.tail6efbba.ts.net"
   ```
3. Depuis `/Users/carlito.e/Projets/Diapason` :
   ```bash
   .venv/bin/python -m diapason.cli serve-service install --maillage-reseau --tailnet
   ```
   `--maillage-reseau` garde le socket 8001 du plist actuel — sans lui, l'installation le retire : le téléphone neuf passe par https, mais l'ancienne app « Succès » vise encore 8001. Le plist obtenu porte `--host 127.0.0.1 --port 8000 --lan-host 0.0.0.0 --lan-port 8001 --tailnet-port 8002`. Si un port secondaire est déjà tenu, la commande le dit ; le serveur démarre alors sans ce socket au lieu de tomber.
4. Vérifier : `lsof -nP -iTCP:8002 -sTCP:LISTEN` montre **127.0.0.1** seulement.
5. Puis :
   ```bash
   tailscale serve --bg 8002
   ```
   Accepter l'activation de Serve si une URL s'affiche. Vérifier `tailscale serve status` (https://atelier.tail6efbba.ts.net → http://127.0.0.1:8002) et `tailscale funnel status` (vide). **Ne jamais lancer `tailscale serve 8000` ni `tailscale funnel`.**
6. Test, Wi-Fi coupé sur le téléphone : `https://atelier.tail6efbba.ts.net/health` répond 200 ; `/` rend « Ouvre Diapason depuis l'app » ; serveur arrêté, 502. À vérifier au passage : si `tailscale serve` réécrit l'en-tête Host, l'adresse posée à l'étape 2 suffit à l'Origin ; sans elle, les écritures et les WebSockets du téléphone rendraient 403.
7. Ensuite seulement : créer une invitation depuis la page Appareils et appairer la nouvelle app avec cette adresse (partie mobile).
- Après chaque commit mobile : reconstruire et réinstaller l'APK avec `tool/flutter_avec_secrets.sh`.

**Pendant la phase 3**
- Avant l'import : ouvrir une fois l'ancienne app « Succès » avec le réseau et la laisser synchroniser ; ouvrir aussi `life-os.php` dans le navigateur où il sert. Ne désinstaller l'ancienne app qu'après le résumé d'import affiché par la nouvelle.
- L'import : menu « ⋮ » de la coquille → « Importer la Life OS » → « Importer vers le Mac ». La phrase affichée est celle du Mac ; si elle manque ou si l'écran dit « la synchronisation avec le site continue », rien n'est coupé. Une fois confirmé, la nouvelle app ne parle plus au site, et ses rappels se lisent sur le Mac.
- Après l'import confirmé seulement : régénérer côté site le jeton de synchronisation et le mot de passe admin (`config/lifeos-*.php`). Ils figurent dans les 15 commits de `cfc5869` à `88a92b6`.
- Au premier lancement de la coquille : accepter le micro quand Android le demande, pas avant.

**Le banc sur le téléphone (étape 10 de la phase 2, la Discussion et l'import)** — écrit le 26/09/2026, pour le Nothing Phone (4a) Pro. Rien de ceci n'a été vu sur un vrai téléphone : c'est ce banc qui le dit. L'Entité et Nocturne restent dans l'app tant qu'il n'est pas fait (étapes 10 et 11 de la phase 3 : pas avant).

*Avant de commencer, sur le Mac* — le serveur de launchd lance le code de `~/Projets/Diapason` (branche `main`), et le bundle que le téléphone charge est `src/diapason/server/static` de CE dossier : sans ces trois gestes, le téléphone recevrait l'ancien bundle, sans pont ni mode téléphone.
1. Fusionner `chantier/mobile` dans `main` (avance rapide : `main` en est l'ancêtre), une fois `git status` propre dans `~/Projets/Diapason` : `git merge --ff-only chantier/mobile`.
2. `cd frontend && npm run build` dans `~/Projets/Diapason`, puis `launchctl kickstart -k gui/$(id -u)/com.diapason.serve`.
3. Vérifier : `tailscale serve status` montre toujours https://atelier.tail6efbba.ts.net → http://127.0.0.1:8002 ; depuis le téléphone en données mobiles, `https://atelier.tail6efbba.ts.net/health` rend 200.

*Installer « Diapason dev »* — l'APK du 26/09/2026 : `~/Projets/diapason_mobile/build/app/outputs/flutter-apk/app-debug.apk`, 191 779 131 octets, sha256 `4d67725a83da53f25cf92e23603354d1bdc1cb1ce23257677e8e22f5a7c243f4` (`shasum -a 256` pour comparer), `com.diapason.mobile.dev`, versionName 1.0.0-dev. Construit avec `config/secrets.json` : au lancement, la Life OS se synchronise avec le site PHP, comme prévu jusqu'à l'import.
4. Copier l'APK sur le téléphone, sans adb : par Taildrop (menu Tailscale du Mac → envoyer le fichier au téléphone, ou `tailscale file cp <apk> <nom-du-téléphone>:`), ou par un câble USB en mode « transfert de fichiers » (Android File Transfer ou OpenMTP), dans Téléchargements.
5. Sur le téléphone, Fichiers → Téléchargements → toucher `app-debug.apk`. Android demande d'autoriser l'installation d'applis inconnues pour l'app qui ouvre le fichier (Fichiers, ou Tailscale) : l'autoriser pour elle seule. Installer. Si Play Protect avertit d'une app non analysée : « Installer quand même ». Puis retirer l'autorisation d'installer à cette app (Réglages → Applis → accès spéciaux).
6. Ne PAS désinstaller l'ancienne « Succès » avant le résumé d'import (plus bas).

*Le banc, Wi-Fi COUPÉ, Tailscale actif sur le téléphone. Noter pour chaque ligne : vu / pas vu, et l'heure.*
7. **Appairage.** Sur le Mac, page Appareils → « Ajouter un appareil » → nom « Nothing Phone » → « Créer une invitation ». La carte montre le code et l'adresse https://atelier.tail6efbba.ts.net (boutons Copier). Sur le téléphone, ouvrir « Diapason dev » : l'écran d'appairage. Contre-épreuve d'abord : taper `192.168.0.104` (ou `atelier`) et un code quelconque → « Cette adresse passe en clair par le réseau local… » et rien d'autre (l'invitation n'est pas dépensée). Puis l'adresse `https://atelier.tail6efbba.ts.net` et le code → « Relier ». Attendu : le bundle s'affiche (la Discussion), la page Appareils du Mac dit « 1 session ouverte · dernière activité à l'instant ».
8. **Le bundle.** Le tiroir s'ouvre et se ferme ; le bouton retour d'Android ferme d'abord le tiroir, puis recule, puis met l'app en arrière-plan. Parcourir Tâches, Planificateur, Habitudes, Notes, Projets, Réglages : ni débordement horizontal, ni bouton plus petit qu'un doigt, ni page « Chargement… » qui ne finit pas. Réglages → Apparence → Ardéchine : la barre d'état d'Android passe en clair ; tuer l'app et la rouvrir : pas de flash blanc.
9. **La Discussion.** Envoyer « Quelle heure est-il ? » : la réponse apparaît jeton par jeton (le flux passe par `tailscale serve`), pas d'un bloc à la fin. Demander « Qu'y a-t-il à mon écran ? » : le Mac doit refuser de lire son écran (outil fermé au téléphone), en le disant. Joindre une photo : « Appareil photo » → prendre → la pièce jointe apparaît dans le compositeur. Joindre un PDF par « Fichiers ».
10. **Le micro (§78).** Dans la Discussion, toucher la dictée : Android demande le micro — accepter. Le voyant vert d'Android s'allume pendant la dictée et S'ÉTEINT à l'arrêt. La voix en direct (`/v1/voice/live`) doit, elle, rester fermée : les Réglages disent « la voix n'est pas encore ouverte au téléphone » (phase 4).
11. **Un export.** Projets → une pile de photos → exporter en PDF : « Enregistré : … .pdf », et le fichier est dans Téléchargements (nom éventuellement suffixé « (1) » par Android — c'est ce nom-là qui doit s'afficher).
12. **L'import (étape 11 de Carlito).** Avant : ouvrir une fois l'ancienne « Succès » avec le réseau et la laisser synchroniser. Puis dans « Diapason dev » : menu « ⋮ » → « Importer la Life OS » → « Importer vers le Mac ». Attendu : la phrase affichée est CELLE DU MAC (« Importé : N tâches, … Non importé : … ») ; sur le Mac, les tâches, habitudes, notes et projets du téléphone sont là. Refaire l'import : « déjà été importée ». Si la phrase manque, ou si l'écran dit « la synchronisation avec le site continue », rien n'est coupé : noter la phrase exacte. Seulement après le résumé : désinstaller l'ancienne « Succès ».
13. **Les rappels.** Sur le Mac, une tâche du jour avec un rappel dans 5 minutes ; attendre la notification sur le téléphone ; « Marquer fait » → la tâche est faite sur le Mac (et la notification « Fait sur le Mac »). Wi-Fi et données coupés, « Marquer fait » sur un autre rappel → « En attente du Mac », la tâche reste ouverte sur le Mac ; réseau revenu, rouvrir l'app → « Fait sur le Mac ».
14. **La télécommande.** Menu « ⋮ » → Appareils → « Notes » : le téléphone demande « Ouvrir « Notes » sur le Mac ? ». Toucher hors du dialogue → « Rien n'a été envoyé au Mac. » Recommencer, « Ouvrir sur le Mac » → la phrase affichée est celle du Mac (succès ou refus).
15. **Le Mac en veille.** Pomme → Suspendre l'activité. Sur le téléphone, menu « ⋮ » → Recharger → « Mac injoignable. Vérifie qu'il est allumé et que Tailscale est actif sur le téléphone. » (jamais la page d'erreur de Chromium). Réveiller le Mac → « Réessayer » → le bundle.
16. **Fermer les sessions, puis révoquer (en dernier).** Page Appareils du Mac → « Fermer ses sessions » pour le téléphone → « 1 session fermée… » ; sur le téléphone, Recharger → une session est rouverte d'elle-même (l'appareil est encore reconnu). Puis « Retirer » le téléphone : dans les 30 s, une Discussion ouverte est coupée, et Recharger → « Appareil non reconnu par le Mac » avec « Refaire l'appairage ». Pour le réadmettre : « Oublier », nouvelle invitation, étape 7.
17. **Quitter l'appairage** (menu « ⋮ » → Appareils → « Quitter cette flotte ») : l'écran d'appairage revient ; aucune page du Mac ne reste derrière.

*Après le banc* : le tableau daté (étape → vu / pas vu → remarque) va à l'étape 10 de la phase 2 ci-dessus, `CAPABILITY_MATRIX.md` est mis à jour, et seulement alors les étapes 10 et 11 de la phase 3 (retirer l'Entité, puis Nocturne et la Life OS native) peuvent commencer.

*Le banc de la voix (phase 4)* — seulement après la fusion de `chantier/phases45` dans `main`, `npm run build` et le redémarrage du serveur ; la dictée et l'étape 10 ci-dessus restent valables jusque-là. Wi-Fi coupé, Tailscale actif :
18. **Parler.** Toucher « Parler » (l'orbe) : la séance démarre sans que les Réglages disent « pas encore ouverte au téléphone » ; le voyant vert d'Android s'allume. « Diapason, quelle heure est-il ? » → la réponse est dite par le téléphone.
19. **La coupure.** Ne plus rien dire pendant deux minutes : la voix se coupe seule, le voyant S'ÉTEINT, et l'orbe dit « La voix s'est coupée seule après un long silence ». Noter la durée mesurée.
20. **Le plafond.** « Diapason, ouvre Safari » → rien ne s'ouvre sur le Mac, la voix dit que ce n'est pas possible depuis le téléphone. « Qu'est-ce que j'ai copié ? » → même refus, jamais le presse-papiers du Mac. Dans la Discussion, dicter « ouvre Safari » → le texte arrive dans le compositeur, rien ne s'ouvre sur le Mac.
21. **L'arrière-plan.** Pendant une séance, verrouiller le téléphone : noter si le voyant reste allumé et combien de temps (la coupure serveur le borne à deux minutes).

**À dire à Carlito (constat 19 de la seconde contre-épreuve)** : ouvert SANS la coquille (un navigateur sur l'adresse https, après un cookie posé), le bundle envoie une fois au premier chargement `POST /v1/context/view` et `GET /v1/voice/live/health` (celle-ci rouverte en phase 4, 26/09/2026 : elle rend désormais 200), que la passerelle refuse en 403 — avant d'avoir vu l'en-tête `X-Diapason-Passerelle`. Ensuite, plus rien. Au téléphone, le pont existe avant tout module : 0 réponse 403 sur 24 routes au banc. La coquille est le seul client prévu ; ce n'est pas corrigé.
