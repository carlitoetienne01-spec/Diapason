# Installation

!!! danger "Les commandes d'une ligne ci-dessous ne fonctionnent pas"

    Elles vont chercher un script sur GitHub Pages. **Ce dépôt est privé** :
    Pages ne publie rien, et ces URL rendent une page d'erreur — que `iex` ou
    `bash` exécuteraient. Vérifié le 26 août 2026 : 404 sur `install.sh`, sur
    `install.ps1`, et sur la racine du site.

    Tant que le dépôt reste privé, **clone d'abord, exécute ensuite** :

    ```bash
    gh auth login
    git clone https://github.com/carlitoetienne01-spec/Diapason.git
    cd Diapason && make setup          # macOS, Linux, WSL2
    ```

    Sur Windows natif, voir [Installation sur Windows natif](windows-native.md),
    dont la procédure est à jour.


## Les guides par plateforme

| Plateforme | Invocation depuis le clone authentifié | Guide détaillé |
|---|---|---|
| **macOS** | `bash scripts/install/install.sh` | [Installation macOS](macos.md) |
| **Linux** | `bash scripts/install/install.sh` | [Installation Linux](linux.md) |
| **WSL2 sur Windows** | `bash scripts/install/install.sh` (dans Ubuntu) | [Installation WSL2](wsl2.md) |
| **Windows natif** | `.\deploy\windows\install.ps1` | [Installation sur Windows natif](windows-native.md) |
| **Interface de bureau** | aucune version publiée ; construire depuis le clone | [État Tauri](../user-guide/desktop-tauri.md) |

Les installateurs bash et PowerShell font la même chose, chacun sur son système. La suite de cette page décrit l'installateur bash en détail ; le [guide Windows natif](windows-native.md) est la référence équivalente pour PowerShell.

## L'installateur bash

```bash
bash scripts/install/install.sh
```

L'installateur télécharge tout pour toi — dont [uv](https://docs.astral.sh/uv/)
(le gestionnaire de paquets Python), l'environnement virtuel Python, Ollama et un
petit modèle de départ. **Tu n'as rien à installer au préalable, pas même uv.**

!!! warning "Publication future"
    La construction MkDocs copie toujours les scripts vers `install.sh` et
    `install.ps1`, afin qu'ils soient prêts le jour où Pages sera réellement
    publié. Aujourd'hui ces URL rendent 404 : le fichier local du clone est la
    seule source exécutable annoncée.

Environ 3 minutes sur une connexion haut débit ordinaire. Tape `diapason` pour commencer à discuter.

## Ce que fait l'installateur

| Phase | Étape | Où |
|---|---|---|
| Premier plan | Installe `uv` (le gestionnaire de paquets Python) | `~/.cargo/bin/` ou `~/.local/bin/` |
| Premier plan | Clone le dépôt Diapason | `~/.diapason/src/` |
| Premier plan | Crée l'environnement virtuel Python 3.11 | `~/.diapason/.venv/` |
| Premier plan | `uv pip install -e .` (installation éditable) | l'environnement virtuel |
| Premier plan | Installe Ollama | emplacement par défaut du système |
| Premier plan | Démarre `ollama serve` | systemd-user / launchd / nohup |
| Premier plan | Télécharge `qwen3.5:2b` (~1,5 Go) | la réserve de modèles d'Ollama |
| Premier plan | Écrit `config.toml` (matériel détecté, moteur et modèle) | `~/.diapason/config.toml` |
| Premier plan | Crée les liens `diapason` et `diapason-uninstall` | `~/.local/bin/` |
| Premier plan | Ajoute `~/.local/bin` au PATH s'il y manque (avec un avis à l'écran) | `~/.bashrc` ou `~/.zshrc` |
| Arrière-plan | Installe la chaîne d'outils Rust via rustup | `~/.cargo/` |
| Arrière-plan | Construit l'extension maturin (mémoire et sécurité) | l'environnement virtuel |
| Arrière-plan | Télécharge les modèles du palier matériel et du palier au-dessus | la réserve de modèles d'Ollama |

## Ce que l'installateur ne touche PAS

- Tes installations Python existantes
- Ton `~/.bashrc` / `~/.zshrc`, hormis une ligne de PATH ajoutée à la fin (avec un avis à l'écran)
- Tes modèles Ollama existants
- Tout autre outil ou fichier de configuration

## Relancer sans risque

Relancer le script local ne casse rien. L'installateur lit `~/.diapason/.state/install-state.json` et saute les étapes déjà faites. Si ton environnement virtuel a été détruit, une relance le répare.

## Le chemin rapide vers le cloud

Si l'une de ces variables d'environnement est posée au moment de l'installation ou de `diapason init`, l'installateur (ou `init`) propose le cloud par défaut et écrit le fournisseur correspondant dans `config.toml` :

- `OPENROUTER_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY` (ou `GEMINI_API_KEY`)

Le local d'abord reste le défaut tant qu'aucune clé n'est dans l'environnement. L'ordre de priorité est OpenRouter > Anthropic > OpenAI > Google.

## Les drapeaux

| Drapeau | Effet |
|---|---|
| `--minimal` | Saute le téléchargement du modèle au premier plan. La première discussion devra attendre la fin du téléchargement en arrière-plan. |
| `--no-bg-orchestrator` | Ne détache pas la chaîne de travail d'arrière-plan. (Surtout pour les tests.) |
| `--force` | Rejoue toutes les étapes, même celles qu'`install-state.json` dit terminées. |

## Les variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DIAPASON_HOME` | `$HOME/.diapason` | Où installer. |
| `DIAPASON_REPO_URL` | `https://github.com/carlitoetienne01-spec/Diapason.git` | Le dépôt source de l'étape de clonage. |

## Désinstaller

```bash
diapason-uninstall
```

Retire `~/.diapason/`, `~/.local/bin/diapason` et `~/.local/bin/diapason-uninstall`. Laisse Ollama, uv et la chaîne d'outils Rust en place (d'autres outils s'en servent peut-être) ; le script affiche les indications pour les retirer.

## Mettre à jour

```bash
diapason update
```

Récupère les dernières sources, rafraîchit l'installation éditable et reconstruit l'extension Rust en arrière-plan. Les modèles ne sont pas touchés.

## Dépannage

### « command not found: diapason »

`~/.local/bin` n'est pas dans ton PATH. Lance `source ~/.bashrc` (ou `~/.zshrc`), ou ouvre un nouveau terminal.

### « memory features unavailable »

L'extension Rust n'a pas fini de se construire — ou sa construction a échoué. Regarde où ça en est :

```bash
diapason doctor
```

Pour relancer à la main :

```bash
~/.diapason/.scripts/install-rust.sh && ~/.diapason/.scripts/build-extension.sh
```

### Le téléchargement d'un gros modèle a échoué

Regarde où ça en est, puis relance :

```bash
diapason doctor
~/.diapason/.scripts/pull-model.sh qwen3.5:9b
```

### Derrière un proxy d'entreprise

Pose `HTTPS_PROXY` et `CURL_CA_BUNDLE` dans ton environnement avant de lancer l'installateur.
