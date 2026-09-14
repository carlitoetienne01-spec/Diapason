# AGENTS.md — ce qu'une session doit savoir avant d'écrire une ligne

Ce fichier est lu automatiquement au début de chaque session Codex dans
ce dépôt. Plusieurs sessions travaillent souvent **en parallèle** sur cette
machine : ce qui suit existe pour qu'elles ne se contredisent pas.

Il est court à dessein. Ce qui est long vit dans `docs/`, et est pointé d'ici.

> **`CLAUDE.md` est la source ; `AGENTS.md` en découle.** Codex lit
> `AGENTS.md`, Claude Code lit celui-ci, et les deux portaient le même texte
> sans que rien ne les y oblige — deux copies divergent toujours, et celle
> qu'on oublie de corriger continue d'instruire quelqu'un. Corrige donc
> **ici**, puis régénère dans le même commit :
> `.venv/bin/python scripts/gen_agents_md.py`. `tests/test_agents_md.py`
> refuse qu'ils s'écartent.

---

## 1. Ce qu'est Diapason

Un assistant personnel **local d'abord**. Le modèle, la voix et la vision
tournent sur la machine ; aucun backend cloud n'existe et aucun n'est
souhaité. Le serveur FastAPI écoute **127.0.0.1** et vit comme agent launchd
(`com.diapason.serve`).

```
Diapason (ce dépôt)                    Succès (~/Desktop/Porfolio/Succes)
├── src/diapason/     Python 3.13      └── lib/   Dart/Flutter, client mobile
│   ├── mesh/         maillage d'appareils           (Android construit,
│   ├── server/       FastAPI                         iOS à moitié préparé,
│   ├── desktop/      macOS : Vision, OCR, gestes     le reste : squelettes)
│   ├── speech/       Whisper, Kokoro, claps
│   ├── succes/       73 routes métier
│   └── tools/        ~100 outils
├── frontend/         React 19 + Vite 6 + Tailwind 4
│   └── src-tauri/    l'app de bureau (Tauri 2, Rust)
└── rust/             17 crates, dont l'extension PyO3 obligatoire
```

**Quatre applications, pas plus** : le bundle React (servi à la fois par le
serveur Python et par Tauri), l'app Tauri, le workspace Rust, le cœur Python.

---

## 2. Vérifier — et pourquoi c'est à toi de le faire

> **La CI tourne de nouveau — sur le Mac de Carlito, pas chez GitHub.**
> Depuis le 24 août 2026, aucun runner hébergé par GitHub ne démarre :
> *« recent account payments have failed »*. Un **runner auto-hébergé**
> (`mac-de-carlito`, étiquettes `self-hosted, macos-local`) a été installé
> le 26 août, et le blocage ne le concerne pas : il ne porte que sur les
> minutes facturées.
>
> Y tournent : `ci.yml` (`lint`, `test`, `rust`), `frontend.yml` et la
> validation de `desktop.yml` (TypeScript + tests Rust Tauri). **Ce qui les
> rend verts est donc macOS, plus Ubuntu** — un défaut propre à Linux ou
> Windows ne sera plus attrapé. Un test qui tourne vaut mieux qu'un test qui
> ne tourne pas, mais ce n'est pas le même test.
>
> Ce qui ne tourne plus du tout, et qui est **sauté** plutôt que rouge :
> `autotag`, `docs` et les publications Tauri Linux/macOS/Windows de
> `desktop.yml`. (`test-windows` y a figuré jusqu'au 30 août 2026, dix lignes
> au-dessus du paragraphe qui le dit vert sur `pc-bureau` : une session
> parallèle pouvait lire l'un ou l'autre et en tirer deux conduites
> opposées.) Un rouge permanent ne signale plus
> rien ; « skipped » dit l'absence sans l'écraser. Pour tout rallumer une
> fois la facturation réglée dans « Billing & plans » : créer la variable de
> dépôt `RUNNERS_GITHUB = true` (Settings → Secrets and variables →
> Actions → Variables), puis remettre les `runs-on: ubuntu-latest` indiqués
> en commentaire dans chaque fichier.
>
> Windows a aussi son chemin sans minutes facturées : `pc-bureau`, étiquettes
> `self-hosted, windows-local`, est actif depuis le 27 août 2026 et la variable
> `RUNNER_WINDOWS_LOCAL = true` est posée. Les matrices 3.12 et 3.13 de
> `test-windows` sont vertes sur ce PC : parseur PowerShell 5.1, tests natifs,
> extension PyO3 compilée/importée et fumée CLI. Un lancement manuel de
> `desktop.yml` ajoute `build-windows-local` : il produit un `.msi` de
> validation non publié et sans updater sous la racine du runner
> (`C:\actions-runner\artifacts` ici). Ce n'est pas une release signée.
>
> Conséquence pratique inchangée : **lance la vérification toi-même, en
> entier, avant de pousser.** La CI confirme, elle ne découvre pas.

Les commandes ci-dessous sont celles de `.github/workflows/ci.yml` et de
`frontend.yml`, au seuil de couverture près — voir la note dessous :

```bash
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m ruff format --check src/ tests/
.venv/bin/python -m pytest tests/ -n auto -q -m "not live and not cloud and not hub"
.venv/bin/python scripts/check_project_identity.py
uv audit --locked --ignore-until-fixed GHSA-w8v5-vhqr-4h9v --ignore GHSA-h35f-9h28-mq5c
uv lock --check
cd frontend && npx tsc --noEmit && npx vitest run && npm run build
cd rust && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd frontend/src-tauri && cargo check && cargo test
```

Les deux dernières lignes ont été AJOUTÉES le 30 août 2026. Le bloc n'avait
jamais porté une seule commande `cargo` alors que le job `rust` en lance
quatre — et il servait de seul filet à un chantier de 569 lignes de Rust dans
`src-tauri`. Le job `rust` de la CI ne couvre d'ailleurs que `rust/` : la
caisse Tauri n'est vérifiée que par `desktop.yml`, d'où la seconde ligne.

La CI ajoute `--cov=diapason --cov-fail-under=60` à `pytest`. Le bloc
ci-dessus l'omet volontairement : la couverture se mesure sur la suite
entière, et l'omettre ici évite de croire qu'un sous-ensemble l'a vérifiée.
Pour reproduire la CI au chiffre près, ajoute-le. Cette phrase existe parce
que ce bloc s'annonçait « exactement » identique à la CI alors qu'il en
différait sur deux points — dans le commit même qui en faisait le seul filet
des sessions parallèles.

Ce qui reste hors du bloc, et pourquoi : `uv sync` (il ÉLAGUE le venv, voir
plus bas), `maturin develop` (l'extension Rust est déjà construite ici), et le
balayage de secrets `gitleaks`. Le contrôle d'identité et l'audit du verrou
Python, eux, ont été AJOUTÉS le 26 août 2026 après que la CI eut refusé un
commit sur `check_project_identity.py` — que ce bloc ne mentionnait pas. Une
vérification locale qui ne couvre pas la CI donne une confiance qu'elle ne
mérite pas.

**N'utilise pas `uv run` pour lancer un simple lint.** `uv sync` ÉLAGUE tout
extra non listé dans `make setup` — constaté deux fois : `faster-whisper` et
`pytest` ont disparu du venv, et la voix serait morte au redémarrage suivant.
`make setup` réinstalle aussi `sherpa-onnx`, qui perd ses dylibs à chaque
synchronisation. En cas de doute, `.venv/bin/python -m <outil>`.

Deux tests de `tests/desktop/test_vision_mains.py` se **sautent** quand
« Enregistrement de l'écran » n'est pas accordé au programme qui lance
pytest. C'est normal, et le message dit quoi faire.

### Reconstruire l'app / recharger le serveur

```bash
./scripts/install-desktop.sh                              # l'app de bureau
launchctl kickstart -k gui/$(id -u)/com.diapason.serve    # le serveur
```

Les deux sont indépendants par choix : le serveur ne doit pas mourir parce
que l'interface se recompile. Voir `docs/reconstruire-le-bureau.md`.

---

## 3. Les conventions, et pourquoi elles ont cette forme

### La frontière de langue est stricte et signifiante

- **Français** dans la couche produit : `desktop/`, `server/gestes_routes.py`,
  `speech/`, `succes/`, `frontend/src/features/`. Les identifiants aussi :
  `attraper`, `lacher`, `tenu`, `joignables`, `cible`, `basculer`.
- **Anglais** dans `mesh/` : `resolve_device`, `dispatch_command`,
  `presence_of`. Docstrings anglaises comprises. **Ne francise pas en y
  entrant.**
- **Les champs qui passent sur le fil sont TOUJOURS en anglais camelCase**,
  même émis par un module français : `handRatio`, `lastDrop`, `deviceId`. Un
  champ en snake_case se lit `undefined` côté TypeScript, en silence.

### Les commentaires racontent le défaut, avec sa date

Pas ce que fait le code — le code le dit déjà. Le commentaire dit ce qui est
arrivé quand il n'était pas là :

```python
# Le fil est mort — casque débranché, micro repris par une autre
# application. Garder le cadavre fait répondre « déjà en écoute » à toute
# tentative de relance, et le micro reste fermé sans que rien ne le dise.
```

Un nombre porte toujours sa justification chiffrée. `_CHOIX_MAX_S = 45.0` est
suivi de la raison pour laquelle ce n'est pas 120.

### Les tests

Classes `Test…` et méthodes en phrases françaises, docstring citant le §N du
cahier et l'échec évité. Assertions porteuses d'un message :

```python
assert pp.tenu() is None, "la main doit être vide après avoir lâché"
```

`tests/` miroite `src/`. Frontend : vitest colocalisé. **Il n'existe aucun
test de composant React dans ce dépôt** — n'en invente pas l'outillage ;
extrais la logique en fonction pure et teste celle-là.

### Les messages de commit

Sujet : une phrase française qui nomme le DÉFAUT, pas la fonctionnalité.
« Le geste attrape et dépose », « Le portier nommait trois personnes qui
n'ont pas la clé ». Corps : des sections en CAPITALES, chacune racontant une
cause et sa preuve chiffrée. Finir par :

```
Co-Authored-By: Codex Opus 5 <noreply@anthropic.com>
```

---

## 4. Ce qui casse le client mobile — à ne pas enfreindre

Le Dart de *Succès* réimplémente l'encodage canonique et n'applique qu'un
contrôle sur onze. Trois règles ne se négocient pas :

1. **Aucun flottant dans une enveloppe signée.** Python écrit `1e-07`, Dart
   écrit `1e-7` : signatures invalides, sans un mot d'explication.
2. **Ne pas incrémenter `COMMAND_VERSION` ni `PULL_VERSION`** avant qu'un
   client Dart acceptant deux versions soit déployé. Le Dart écrit `1` en dur.
3. **Ne pas ajouter de champ à `_POLL_FIELDS` / `_ACK_FIELDS`.** La signature
   couvre une liste explicite ; un champ absent côté Dart y entre comme
   `null` et invalide toutes les relèves.

Ajouter des **capacités** et des **outils** est en revanche sûr par
construction : le plafond écarte les verbes inconnus et un client ancien
répond `UNSUPPORTED`, statut accepté.

### Les contrats sont figés par des instantanés

| Instantané | Régénérer avec |
|---|---|
| `tests/contract/mesh_api_surface.json` | `scripts/gen_mesh_surface.py` |
| `tests/contract/succes_api_surface.json` | `scripts/gen_succes_surface.py` |
| `canonical_vectors.json` (dépôt Succès) | `scripts/gen_canonical_vectors.py` |

Régénère **dans le même commit** que le changement qui l'a causé, jamais
après. Voir `docs/succes-client-mobile.md`.

---

## 5. Pièges déjà payés — ne pas les repayer

| Piège | Ce qu'il faut savoir |
|---|---|
| **Ollama tourne avec `-np 1`** | Un seul créneau d'inférence. Un workflow multi-agents affame l'assistant, et le délai d'attente ment en disant « not reachable ». |
| **`ruff --fix` supprime les ré-exports** | Un alias d'import inutilisé DANS le module est supprimé même s'il est importé d'ailleurs. Écris un ré-export comme une **affectation** (`_X = X`), jamais comme un alias. Voir `speech/realtime/local_voice.py`. |
| **`Path(MagicMock())` écrit sur le disque** | `__fspath__` rend « MagicMock/<nom>/<id> ». 42 vraies bases SQLite ont dormi à la racine. Un code qui écrit doit valider son chemin. |
| **WKWebView refuse les corps binaires** | La fenêtre Tauri échoue sur un `Blob` ou un `ArrayBuffer` avec un « Load failed » opaque. Passe par du JSON base64. |
| **Le `dblclick` n'arrive pas au WebView** | Détection maison et bouton visible ; un banc Chromium ne le reproduit pas. |
| **L'app Tauri sort *ad hoc*** | TCC ancre Accessibilité sur le cdhash. `install-desktop.sh` re-signe avec une identité Apple Development du trousseau, sinon le droit meurt encore et la case cochée ment. Après un changement d'identité : retirer l'entrée, ajouter `/Applications/Diapason.app`, relancer. |
| **Aucun runner macOS en CI** | Tout le code caméra / Vision / PyObjC / gestes n'est vérifié qu'à la main, sur cette machine. |
| **Une route `async def` qui appelle du bloquant gèle TOUT** | Ce qu'une route `async` fait en ligne s'exécute **sur la boucle d'événements** : un `httpx.post` de 6 s y fige le WebSocket vocal, le flux du chat et la cloche d'approbation. Les routes `def` **synchrones**, elles, sont exécutées par Starlette dans un fil et n'ont pas ce défaut. Dans une route `async`, tout appel réseau ou disque passe par `await asyncio.to_thread(...)`. |
| **Une restriction qu'un client peut lever est décorative** | `DEFAULT_VOICE_TOOL_IDS` était un *défaut*, pas un plafond : une trame WebSocket `tools: "mesh_send"` suffisait à obtenir l'outil que le test-fusible prétendait exclure. Toute liste venant du réseau se confronte au plafond du serveur — **restreindre, jamais élargir**. |
| **`X = AutreClasse.methode` fige l'objet fonction** | L'emprunt est fait à la définition de la classe. Patcher `AutreClasse.methode` ensuite n'atteint pas la copie : dans un test, patche la classe qui emprunte, pas celle qui prête. |
| **Un refus de capacité ne lève PAS d'exception** | `ToolExecutor` transforme un refus en *résultat d'outil* (« Capability 'x' denied »). Le modèle le lit comme n'importe quelle sortie et enchaîne sur une réponse parfaitement fluide. Tout code qui conclut « pas d'exception donc ça a marché » écrit un faux SUCCESS. Le signal existe : l'événement `CAPABILITY_DENIED` sur le bus. |
| **Aucune migration SQLite** | Six bases dans `~/.diapason/` ; chacune crée son schéma à l'ouverture. |

---

## 6. Où en est le chantier

Ne déduis jamais la branche courante de ce document : l'arbre est partagé et
la branche change au fil des intégrations. Lis `git branch --show-current` et
`git status` avant toute action. Le point d'entrée du chantier est
[`docs/spatial-mesh/README.md`](docs/spatial-mesh/README.md) — il dit ce qui
est livré, ce qui reste, et dans quel ordre. Deux compagnons :

- [`INITIAL_AUDIT.md`](docs/spatial-mesh/INITIAL_AUDIT.md) — pourquoi chaque
  chose est dans cet état. Un audit ne se réécrit pas : ce qui est traité y
  est **barré**, pas effacé.
- [`CAPABILITY_MATRIX.md`](docs/spatial-mesh/CAPABILITY_MATRIX.md) — l'état
  réel par plateforme. **Elle périme en quinze heures** : elle l'a déjà fait
  une fois, en niant un travail livré le matin même. Relis-la à chaque
  modification du maillage ou des gestes.

Le reste du produit : `docs/development/roadmap.md`.

---

## 7. Travailler à plusieurs sessions sur cette machine

1. **`git status` d'abord.** Des modifications non commitées peuvent être le
   chantier d'une autre session — ou de Carlito. Ne les commite pas sans
   demander, ne les écrase jamais.
2. **Committe par thème**, pas par lot. Un thème = un défaut nommé.
3. **Annonce le périmètre avant d'éditer.** Deux sessions dans
   `gestes_routes.py` en même temps, c'est un conflit garanti.
4. **Ne reformate pas ce que tu ne modifies pas.** Un `ruff format` global
   noie le diff de l'autre session. (Le dépôt est formaté depuis le 25 août
   2026 ; il n'y a plus de raison d'y revenir.)
5. **Ne pousse pas et ne fusionne pas sans que Carlito le demande.**

---

## 8. Ce que ce projet refuse

Ces règles viennent du cahier des charges et gouvernent les arbitrages :

- **§5 — ne jamais faire semblant.** Un champ qui voyage sans être lu finit
  par se faire promettre. Une capacité que rien n'exerce est une promesse en
  attente.
- **§34 — ne jamais deviner une direction.** Aucun capteur de cette flotte ne
  mesure où l'on pointe. Quand deux appareils conviennent, on **demande** —
  et la question doit pouvoir être répondue, sinon c'est une impasse.
- **§78 — rien ne guette en permanence.** Micro et caméra s'arment
  explicitement et se désarment seuls. Le voyant vert doit dire la vérité.
- **§82 — un geste n'est jamais l'unique chemin vers une action.** Tout
  reste atteignable au clic, au clavier et à la voix.
- **§100 — jamais de faux SUCCESS.** La phrase rendue vient du RÉCEPTEUR,
  jamais de ce qu'on a envoyé.

« Je pense que cela a fonctionné » est déjà un échec.
