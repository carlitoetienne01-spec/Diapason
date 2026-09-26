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

Aucune coupure automatique n'existe aujourd'hui pour `/v1/voice/live`
(déduit par la conception, à revérifier) : §78 l'exige avant d'ouvrir la voix
au téléphone.

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
- **Synchro.** Côté invité, `sync.py:565` et `:626` continuent d'émettre `/v1/succes/sync/*`, que les hôtes anciens comme les nouveaux acceptent.
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
- Sur le Mac, après coup : 1 679 tâches, 57 notes, 62 photos dont chaque fichier existe, et `ls ~/.diapason | grep succes` ne montre que les sauvegardes.

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
- (a) Les émetteurs passent au nouveau schéma quand l'APK et Diapason.app reconstruites l'acceptent.
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

**1. « Rien ne représentait une session d'appareil ».** On crée `mesh/sessions.py` (en anglais, comme le reste de `mesh/`) et, dans le `_SCHEMA` de `DeviceRegistry`, deux tables :
- `mesh_sessions` : `session_hash` sha256, `device_id` avec `REFERENCES mesh_devices ON DELETE CASCADE`, et des dates en millisecondes entières ;
- `mesh_session_tickets` : à usage unique, valables 60 s, avec la garde `UPDATE … WHERE redeemed IS NULL`.

`verify_session()` exige `TRUSTED` à **chaque** appel. Il n'y a pas de migration, puisque la table se crée à l'ouverture.
*Risque silencieux :* un cache de validité rendrait une révocation sans effet. Oublier `PRAGMA foreign_keys=ON` laisserait des sessions orphelines, qu'un réappairage sous le même identifiant retrouverait.
*Preuve :* la session est refusée juste après `revoke()` ; `forget()` efface ses lignes ; le jeton en clair est introuvable dans la base ; deux échanges concurrents du même ticket ne donnent qu'un seul gagnant.

**2. « Aucune enveloppe ne permettait d'ouvrir une session ».** C'est un type d'enveloppe distinct de celui des commandes : `purpose: "webview-session"`, `audience` = identifiant du Mac, validité de 60 s au plus, nonce consommé dans `mesh_nonces`, et seulement des entiers et des chaînes. On ajoute un vecteur à `scripts/gen_canonical_vectors.py` et on régénère `diapason_mobile/test/mesh/canonical_vectors.json` en même temps, dans les deux dépôts.
*Risque silencieux :* un flottant rend toutes les signatures invalides (`1e-07` contre `1e-7`). Réutiliser l'enveloppe des commandes ferait accepter un ordre comme une ouverture de session.
*Preuve :* sont refusés le rejeu, une audience étrangère, un appareil révoqué, une expiration trop lointaine et un flottant. `git diff` ne touche aucune des quatre constantes du §4.

**3. « Une requête venue du tailnet aurait hérité des droits de la boucle locale ».** Nouveau fichier `server/passerelle_tailnet.py`, qui enveloppe l'app principale sans toucher `app.py`.
- **Portes sans session :** `/health`, les 9 portes LAN, `POST /v1/appareil/session` et `POST /v1/appareil/ouvrir`. Cette dernière pose le cookie `diapason_appareil` (`HttpOnly; Secure; SameSite=Strict`, 12 h), puis répond 303.
- **Tout le reste exige le cookie.** Une clé locale reçue ici est refusée.
- **Marquage.** La passerelle pose `scope['diapason.appareil']`, remplace `client` par `appareil:<id>` et force `scheme='https'`.
- **Origine.** Elle est contrôlée pour les WebSockets et pour tout ce qui n'est pas un GET.
- **Liste refusée, en 403 français :** le plan de contrôle du maillage (dont `POST /v1/mesh/commands`), les écritures de `/v1/config`, les secrets, `/v1/account`, `/v1/gestures/*`, et les actions sur le Mac tant que Carlito n'en a pas décidé autrement.
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

**4. « Le serveur n'avait que deux sockets ».** `diapason serve --tailnet-port 8002` et `serve-service install --tailnet` :
- `_servir_deux_sockets` (`serve.py:237`) est généralisé à N sockets ;
- 8002 écoute sur `127.0.0.1` seulement, avec `lifespan="off"` et `proxy_headers=False` ;
- un port égal à `--port` ou à `--lan-port` est refusé.

Le piège `proxy_headers` d'uvicorn entre au §5 de CLAUDE.md, puis dans AGENTS.md.
*Risque silencieux :* sans `lifespan="off"`, il y a deux battements du maillage, deux tâches de synchronisation du compte, et une double fermeture du magasin des conversations. Écouter sur `0.0.0.0` exposerait la passerelle en HTTP clair.
*Preuve :* le banc à événement `arret` est étendu à 3 sockets. `lsof -iTCP:8002 -sTCP:LISTEN` montre 127.0.0.1. Une commande reçue sur 8002 apparaît dans `/v1/mesh/inbox` lu sur 8000.

**5. (Carlito) `tailscale serve --bg 8002`.** Aucun code.
*Preuve :* en données mobiles, `https://<nom>.<tailnet>.ts.net/health` rend 200 ; `/` rend la page 401 « Ouvre Diapason depuis l'app » ; le serveur arrêté donne 502 ; `tailscale funnel status` est vide.

**6. « L'appairage visait un port qui n'écoute plus le réseau » (dépôt mobile).**
- `normalizeBase` : n'ajoute rien à une adresse https, et ajoute `:8001` à une adresse http sans port.
- `network_security_config.xml` : plus de trafic en clair dans la configuration de base ; `localhost` et `10.0.2.2` seulement dans la variante dev.
- `MeshApi.openSession()` signe l'échange et rend le ticket.
- Les échecs sont distingués : délai ou nom introuvable → « Mac injoignable » ; 502 → « Diapason est arrêté sur le Mac » ; 401 ou 403 → « appareil non reconnu ».

*Risque silencieux :* avec un `:8000` ajouté à une adresse https, l'appairage échoue sur un délai affiché comme « réseau », alors que l'adresse est juste.
*Preuve :* `normalizeBase('https://x.ts.net') == 'https://x.ts.net'` et `normalizeBase('192.168.0.12') == 'http://192.168.0.12:8001'` ; le vecteur de session est vérifié ; l'appairage réussit en données mobiles.

**7. « La télécommande était refusée, et le téléphone annonçait un succès qu'il avait écrit lui-même ».** On change la valeur de `mesh_api.dart:155`, sans ajouter de champ : `requiresConfirmation: true`, après un dialogue de confirmation SUR LE TÉLÉPHONE (décidé). `mesh_pairing_screen.dart:241` affiche toujours le `userSafeMessage` du Mac, et `MeshController.commander` le rend.
*Risque silencieux :* `true` sans dialogue ferait du contrôle n°10 une formalité.
*Preuve :* en Python, une enveloppe `desktop.open` signée par le téléphone avec `true` passe le contrôle n°10, et avec `false` elle rend `DENIED`. En Dart, le texte affiché est égal au `userSafeMessage` simulé, y compris quand c'est un échec.

**8. (Facultatif, si pc-bureau rejoint le tailnet) « Le maillage tenait une adresse Tailscale pour publique ».** `mesh/transport.py:86` reconnaît `100.64.0.0/10` comme privé.
*Risque silencieux :* sans ce changement, un envoi poussé du Mac vers le PC par Tailscale est refusé en mode `local_only`.
*Preuve :* `address_is_private('100.100.1.1')` rend `True`, et `8.8.8.8` reste public.

**9. « La page Appareils ne montrait pas les sessions ouvertes ».** Pour chaque appareil : ses sessions, sa dernière activité, et un bouton « Fermer ses sessions » distinct de la révocation. L'adresse à saisir vient d'une clé `[tailnet] adresse`, posée par Carlito et jamais devinée. `tests/contract/mesh_api_surface.json` est régénéré dans ce même commit.
*Risque silencieux :* un instantané régénéré plus tard par une autre session, qui ne saurait pas pourquoi il a bougé.
*Preuve :* un vitest sur une fonction pure de formatage (aucun test de composant). Fermer les sessions depuis le Mac fait répondre 401 à la requête suivante.

**10. Banc sur le vrai téléphone, puis la doc.** Wi-Fi coupé, on vérifie dans l'ordre : l'appairage, le bundle, le flux du chat jeton par jeton, la poignée de main `/v1/voice/live` avec l'invite micro et le voyant Android, la révocation qui coupe HTTP et WebSocket en 30 s au plus, et le Mac en veille, que l'app doit dire injoignable. Le tableau daté va ici ; `CAPABILITY_MATRIX.md` est mis à jour.
*Risque silencieux :* déclarer la phase livrée sur la foi des tests ASGI. Ni le passage du SSE à travers serve, ni la CSP `wss` dans la WebView Android, ni le micro ne se vérifient ailleurs que sur l'appareil.
*Preuve :* le tableau des mesures, daté, dans ce document.

Pour la phase 4 : aucune coupure automatique n'existe aujourd'hui pour `/v1/voice/live` (DÉDUIT par un lecteur, non revérifié). §78 l'exige avant d'ouvrir la voix au téléphone.

---

### Plan de la phase 3 — La WebView

La passerelle de la phase 2 fixe le modèle de sécurité. **Le secret de session reste un cookie `HttpOnly` et n'est jamais donné au JavaScript.** Le pont ne porte donc pas de verbe `cle`, et `getBase()` rend déjà `''` hors Tauri (même origine).

~~**1. « Une citation importée puis supprimée aurait fait tomber toutes les routes de vie au démarrage ».**~~ *Commité le 25/09/2026 (`cff1f2f`), avant la 1b.* `_materialize_continuity_snapshot` teste l'existence d'une citation **y compris supprimée** avant `create_quote`, sur le modèle de `get_template`, qui refuse un identifiant existant. Ce correctif n'attend rien : il peut précéder la 1b.
*Risque silencieux (DÉDUIT) :* le plantage n'arriverait qu'au redémarrage launchd qui suit la première suppression, bien après un import réussi.
*Preuve :* importer, supprimer la citation, rouvrir `SuccesSyncStore` sur la même base : aucune exception, et la citation reste supprimée.

**2. « L'import perdait des coches d'habitude et des notes sans le dire ».**
- Les coches sont importées sur l'union des clés de `habitLogs` et de `habitLogsAt`, avec un horodatage de repli.
- Chaque saut est compté par motif : `plusRecentSurLeMac`, `titreVide`, `tropLong`, `invalide`.
- Le résumé déclare les clés ignorées et pourquoi : l'état d'interface, les 5 réglages du site et `sync.deletes` (§5).
- Si la forme de la réponse change, `vie_api_surface.json` est régénéré dans ce même commit.

*Risque silencieux :* avec la copie de dev, 2 coches sur 3 disparaîtraient, et le résumé dirait « importé ».
*Preuve :* une fixture `LifeOsState.toJson()` produite par le Dart, **un seul fichier lu par pytest et par `flutter test`** :
- 3 coches, dont 1 horodatée, donnent 3 lignes ;
- un second import rend `alreadyImported: true` ;
- une note sans titre figure au résumé avec son motif.

**3. « Le bundle ne savait pas qu'il tournait dans un téléphone ».** On crée `frontend/src/lib/natif.ts`, sur le modèle de `lib/compact.ts`.
- **Détection.** Le bundle repère `window.DiapasonNatif` (un canal JavaScript injecté avant le chargement), pose `data-diapason-mobile="1"` et exporte `estMobile`.
- **Protocole.** Requête et réponse sont identifiées par `id`, avec un délai limite.
- **Verbes :** `theme`, `enregistrer`, `ouvrirExterne`, `retour`.
- **Côté Flutter.** `onNavigationRequest` n'autorise que l'origine du Mac.

*Risque silencieux :* le canal JavaScript d'Android est exposé à **toute** page chargée dans la WebView. Un lien suivi en interne pourrait appeler le pont.
*Preuve :* des vitest sur les fonctions pures (réponse arrivée avant son attente, délai en français, identifiant inconnu ignoré). En Dart, `https://exemple.com` donne `prevent` et l'origine du Mac donne `navigate`.

**4. « Hors de Tauri, des pages annonçaient un succès qui n'avait pas eu lieu ».**
- Les 4 téléchargements `blob:` (`photosExport.ts:72-80`, `exportVisuel.ts:85-87`, `features/vie/api.ts:802`, `SettingsPage.tsx:449`) passent par le verbe `enregistrer` et ne réussissent que sur la réponse de Flutter.
- `impressionDisponible` rend `false` quand `estMobile` (`compte.ts:989`).
- `get_cloud_key_status` et `get_inference_source` lisent une route serveur en lecture seule, au lieu de rendre `{}` et `ollama` inventés (`api.ts:17-27`, `:1302-1312`).
- Les messages anglais « desktop app only » passent en français.
- Le mode gestes est caché quand `estMobile` : il ouvrirait la caméra **du téléphone** (`useModeGestes.ts:280`).
- Les commandes Tauri sans effet (focus, réglette, dictée en direct) ou déjà doublées par HTTP (santé, modèles, transcription) ne demandent rien.

*Risque silencieux :* « exporté » alors qu'aucun fichier n'existe ; une source d'inférence qui contredit celle du Mac.
*Preuve :* un export mobile ne rend un nom qu'après un `enregistrer` confirmé, et `null` sur refus. `getInferenceSource()` hors Tauri lit le serveur. À la main, une pile exportée en PDF apparaît dans Téléchargements.

**5. « À 390 px, la barre latérale cachait deux tiers de la Discussion et ne se refermait jamais ».**
- `sidebarOpen` démarre fermé sous `md` (`store.ts:367`), lu par `matchMedia` une seule fois à l'amorçage, sans `innerWidth` (règle 2 du mini-panneau).
- La fonction pure `barreApresNavigation()` referme la barre après une navigation.
- Le retour Android ferme d'abord la barre.
- `max-sm:opacity-100` sur le menu « ⋯ » de `ConversationList.tsx:287` et sur `PilesPhotos.tsx:1681` et `:1698`.
- Le cas téléphone s'ajoute à `docs/development/mini-panneau-responsive.md`.

*Risque silencieux :* supprimer une discussion devient impossible au doigt (§82). Une correction faite sur la largeur casserait le mini-panneau, où « compact » est un mode.
*Preuve :* un vitest sur `barreApresNavigation`, puis chaque page de vie vue dans la vraie WebView, marquée « vue » dans le document. Un banc Chromium ne suffit pas pour le survol.

**6. « La coquille ignorait l'apparence choisie dans la WebView ».** À côté de `reglette_set_theme` (`App.tsx:180`), le bundle envoie le verbe `theme` avec `{theme, skin, fond, encre, clair}`. Flutter en tire `SystemUiOverlayStyle` et le fond de ses écrans natifs, et mémorise le dernier thème pour le démarrage à froid.
*Risque silencieux :* une barre d'état illisible en Ardéchine si le drapeau `clair` manque, et un flash blanc au lancement en Phosphore.
*Preuve :* un vitest vérifie que `terminal/ardechine` donne `clair=true`. En Dart, un thème reçu puis relu donne le même fond.

**7. « Il n'y avait pas de coquille pour porter le bundle » (dépôt mobile).**
- **Chargement.** La coquille sonde `/health` avant `loadRequest` ; sans réponse, elle affiche l'écran natif « Mac injoignable ». Elle ouvre ensuite la session (phase 2) et fait un POST du ticket vers `/v1/appareil/ouvrir`.
- **Micro.** `onPermissionRequest` n'accorde le micro qu'à l'origine du Mac, après `RECORD_AUDIO`, et refuse la caméra.
- **Fichiers.** `setOnShowFileSelector` ouvre une feuille native Appareil photo / Galerie / Fichiers (paquets `image_picker` et `file_picker` à ajouter).
- **Retour.** `PopScope` interroge d'abord le verbe `retour`, puis `goBack()`, puis passe l'app en arrière-plan.
- **Liens externes.** `url_launcher`.
- **Divers.** SafeArea ; débogage de la WebView en variante dev seulement ; service worker **désinscrit** pour l'origine mobile : le bundle est toujours exactement celui du serveur.

*Risque silencieux :* sans sélecteur de fichiers, « joindre » ne fait **rien**, sans erreur. Accorder toute demande de permission ouvrirait le micro à n'importe quelle page (§78). Sans sonde, un bundle en cache s'affiche hors de portée du Mac et chaque action échoue une à une.
*Preuve :* des tests Dart purs (permission, navigation, source du fichier selon `acceptTypes`). À la main : joindre un PDF, photographier dans une pile, le bouton retour, le Mac éteint.

**8. « L'import depuis le téléphone pouvait écraser ce que le téléphone avait écrit » (dépôt mobile, écran natif unique).**
1. `_pullSnapshotFromApi` (`life_os_controller.dart:524`) puis `mergeRemoteSnapshotIntoLocal`, **jamais** `_bootstrapFromServer` (`:329`), qui écrase l'état local.
2. `_pushSnapshotToApi` (`:588`).
3. POST de `LifeOsState.toJson()` vers `/v1/vie/import/legacy` par la session d'appareil.
4. Affichage du résumé **rendu par le Mac** (§100).
5. Un drapeau dans `MeshStore`.
6. Seulement ensuite : désactivation de la synchronisation PHP.

*Risque silencieux :* couper le PHP avant un import confirmé perd les écritures faites entre-temps. Appeler le bootstrap efface le local.
*Preuve :* en Dart, un état local portant une tâche absente du site part vers le Mac avec les deux. La fixture commune de l'étape 2 est relue des deux côtés.

**9. « Les rappels et la navigation du maillage dépendaient de la Life OS qui part ».**
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

**Pendant la phase 2**
- Après le commit du troisième socket : `.venv/bin/python -m diapason.cli serve-service install --tailnet` (nom exact à confirmer à ce commit), puis `tailscale serve --bg 8002`. Accepter l'activation de Serve si une URL s'affiche. Vérifier `tailscale serve status` et `tailscale funnel status` (vide). **Ne jamais lancer `tailscale serve 8000` ni `tailscale funnel`.**
- Test : en données mobiles, `https://<nom>.<tailnet>.ts.net/health` répond ; poser `[tailnet] adresse` ; créer une invitation et appairer la nouvelle app avec cette adresse.
- Après chaque commit mobile : reconstruire et réinstaller l'APK avec `tool/flutter_avec_secrets.sh`.

**Pendant la phase 3**
- Avant l'import : ouvrir une fois l'ancienne app « Succès » avec le réseau et la laisser synchroniser ; ouvrir aussi `life-os.php` dans le navigateur où il sert. Ne désinstaller l'ancienne app qu'après le résumé d'import affiché par la nouvelle.
- Après l'import confirmé seulement : régénérer côté site le jeton de synchronisation et le mot de passe admin (`config/lifeos-*.php`). Ils figurent dans les 15 commits de `cfc5869` à `88a92b6`.
- Au premier lancement de la coquille : accepter le micro quand Android le demande, pas avant.
