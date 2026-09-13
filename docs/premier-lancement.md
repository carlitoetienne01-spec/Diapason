# Le premier lancement — ce que l'app installe elle-même

Diapason.app est une fenêtre. Le modèle, la voix, le serveur Python et
l'extension native n'y sont pas : ils pèsent des gigaoctets, changent à leur
rythme, et n'ont rien à faire dans un `.dmg`. Jusqu'au 13 septembre 2026, un
Mac vierge qui ouvrait l'app lisait « *backend not installed, run the
installer* » — un `curl … | bash` qui exigeait `git` (donc Xcode), clonait un
dépôt privé, et dont l'étape Ollama ne marchait que sous Linux.

Depuis, l'app fait ce travail elle-même, au premier lancement, sans terminal.
Le code est dans [`frontend/src-tauri/src/amorcage.rs`](../frontend/src-tauri/src/amorcage.rs) ;
l'écran de configuration le montre comme première étape, « Composants locaux ».

## Ce qui est téléchargé, et d'où

| Composant | Source | Quand |
|---|---|---|
| `uv` | releases GitHub d'Astral (`uv-<cible>.tar.gz`) | si aucun `uv` n'est trouvé sur la machine |
| `ollama` | releases GitHub d'Ollama (`ollama-darwin.tgz`, universel) | si aucun `ollama` n'est trouvé, et que le moteur configuré est Ollama |
| le code Python | `diapason-src-<version>.tar.gz`, publié avec la release `desktop-v<version>` de l'app | si `src/` n'existe pas, ou porte une autre version que l'app |
| `diapason_rust` | `diapason_rust-…-<cible>.whl`, même release | avec le code |
| Python 3.13 | téléchargé par `uv` lui-même (`.python-version`) | avec `uv sync` |
| le modèle | `ollama pull`, par l'API locale d'Ollama | comme avant |

L'app cherche son backend **sous sa propre version** — jamais une autre.
Quand l'updater installe une nouvelle app, le démarrage suivant voit que
`src/` porte l'ancienne version et retélécharge le code : l'app et son
backend avancent ensemble.

## Où ça atterrit

```
~/.diapason/                    (Windows : %LOCALAPPDATA%\Diapason)
├── bin/
│   ├── uv/uv                   un dossier par outil — Ollama cherche ses
│   └── ollama/ollama, lib…     bibliothèques à côté de son binaire
├── src/                        le code, avec .python-version et .venv/
│   └── .diapason-backend       la version installée (témoin)
├── roues/diapason_rust-….whl   gardée pour réinstaller si le venv change
└── telechargements/            archives en transit, effacées après extraction
```

`lib.rs` connaissait déjà `~/.diapason/src` comme racine installée ;
`resolve_bin` regarde `bin/<outil>/` en premier.

## Ce qui n'est PAS touché

Un dépôt de développement (`~/Projets/Diapason`, ou tout chemin écrit dans
`~/.diapason/project_root`) reste prioritaire : si `find_project_root` trouve
autre chose que `src/`, l'app ne télécharge pas de code et suit le chemin
historique — `uv sync` avec le groupe `desktop-native`, `cargo` requis,
extension compilée depuis `rust/`. On ne remplace jamais le travail de
quelqu'un par une archive.

De même, un `src/pyproject.toml` posé par l'ancien script d'installation,
sans témoin de version, est respecté tel quel.

## Sur une racine gérée, `uv sync` change de forme

```
uv sync --locked --extra desktop … --inexact        (sans --group desktop-native)
uv pip install --python .venv roues/diapason_rust-….whl
```

- sans `--group desktop-native`, uv ne compile pas l'extension : pas de
  `cargo`, pas d'éditeur de liens, pas de Xcode chez l'utilisateur ;
- `--inexact` empêche uv de **retirer** la wheel au démarrage suivant — sans
  lui, uv élague tout paquet absent du verrou, et l'extension disparaissait
  après chaque relance (c'est le même piège que `uv sync` dans le venv de
  développement, voir CLAUDE.md).

## Le contrat de la release

Chaque release `desktop-v<version>` porte, en plus du `.dmg` et de
`latest.json`, trois fichiers produits par
[`scripts/build-backend-assets.sh`](../scripts/build-backend-assets.sh) :

```json
// backend.json
{
  "version": "1.0.0",
  "python": "3.13",
  "source": "diapason-src-1.0.0.tar.gz",
  "wheels": {
    "aarch64-apple-darwin": "diapason_rust-0.1.0-cp313-cp313-macosx_11_0_arm64.whl"
  }
}
```

- `version` doit être celle de l'app, sinon l'amorçage refuse ;
- `python` est la version de la wheel (pyo3 sans `abi3` : une wheel cp313
  n'importe pas dans un 3.14) ; l'app l'écrit dans `src/.python-version` ;
- une cible absente de `wheels` n'est pas une erreur : l'app compilera, et
  l'erreur existante (« install Rust ») dira quoi faire. Aujourd'hui seule
  `aarch64-apple-darwin` est produite — le runner est ce Mac.

## Tester sans release

```bash
./scripts/build-backend-assets.sh                     # → dist/backend/
(cd dist/backend && python3 -m http.server 8765 --bind 127.0.0.1) &
cd frontend/src-tauri
DIAPASON_BACKEND_URL=http://127.0.0.1:8765 \
  cargo test --release amorcage_reel -- --ignored --nocapture
```

Le test `amorcage_reel` joue le premier lancement entier dans un
`DIAPASON_HOME` jetable : vraies archives d'Astral et d'Ollama, code et
wheel depuis le serveur local, `uv sync`, `import diapason_rust`, puis un
second `uv sync` pour prouver que `--inexact` garde la wheel. Il est ignoré
par défaut (~200 Mo de réseau, plusieurs minutes).

Pour l'app elle-même : `DIAPASON_HOME=/tmp/diapason-test
DIAPASON_BACKEND_URL=http://127.0.0.1:8765 /Applications/Diapason.app/Contents/MacOS/diapason`
— attention, la fenêtre est à instance unique : quitter l'app installée
d'abord.

## Ce qui reste hors de ce chantier

- **Gatekeeper.** Un `.dmg` non notarisé affiche « endommagé » au premier
  clic ; le contournement (`xattr -cr`) est une ligne de commande. C'est
  l'affaire d'un compte Apple Developer, pas de l'amorçage.
- **Windows et Linux** suivent le même code (bsdtar lit les zip sur Windows
  10+) mais n'ont pas été joués ; aucune wheel n'est produite pour eux.
- **Les dépendances Python qui compileraient.** Sur ce Mac, tout arrive en
  wheel. Un Mac sans Xcode le confirmera — ou non — à l'essai sur machine
  vierge.
