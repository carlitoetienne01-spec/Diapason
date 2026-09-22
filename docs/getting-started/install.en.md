# Installation

!!! danger "Les commandes d'une ligne ci-dessous ne fonctionnent pas"

    Elles vont chercher un script sur GitHub Pages. **Ce dépôt est privé** :
    Pages ne publie rien, et ces URL rendent une page d'erreur — que `iex` ou
    `bash` exécuteraient. Vérifié le 26 août 2026 : 404 sur `install.sh`, sur
    `install.ps1`, et sur la racine du site.

    Tant que le dépôt reste privé, **clonez d'abord, exécutez ensuite** :

    ```bash
    gh auth login
    git clone https://github.com/carlitoetienne01-spec/Diapason.git
    cd Diapason && make setup          # macOS, Linux, WSL2
    ```

    Sur Windows natif, voir [Native Windows install](windows-native.md), dont
    la procédure est à jour.


## Platform-specific guides

| Platform | Invocation depuis le clone authentifié | Detailed guide |
|---|---|---|
| **macOS** | `bash scripts/install/install.sh` | [macOS install](macos.md) |
| **Linux** | `bash scripts/install/install.sh` | [Linux install](linux.md) |
| **WSL2 on Windows** | `bash scripts/install/install.sh` (dans Ubuntu) | [WSL2 install](wsl2.md) |
| **Native Windows** | `.\deploy\windows\install.ps1` | [Native Windows install](windows-native.md) |
| **Desktop GUI** | aucune release publiée ; construire depuis le clone | [État Tauri](../user-guide/desktop-tauri.md) |

The bash and PowerShell installers do the same thing on their respective hosts. The rest of this page documents the bash installer in detail; the [native Windows guide](windows-native.md) is the equivalent reference for PowerShell.

## Bash installer

```bash
bash scripts/install/install.sh
```

The installer downloads everything for you — including [uv](https://docs.astral.sh/uv/)
(the Python package manager), the Python venv, Ollama, and a small starter
model. **You don't need to install uv or any other prerequisite first.**

!!! warning "Publication future"
    La construction MkDocs copie toujours les scripts vers `install.sh` et
    `install.ps1`, afin qu'ils soient prêts le jour où Pages sera réellement
    publié. Aujourd'hui ces URL rendent 404 : le fichier local du clone est la
    seule source exécutable annoncée.

About 3 minutes on a typical broadband connection. Type `diapason` to start chatting.

## What the installer does

| Phase | Step | Where |
|---|---|---|
| Foreground | Install `uv` (Python package manager) | `~/.cargo/bin/` or `~/.local/bin/` |
| Foreground | Clone Diapason repo | `~/.diapason/src/` |
| Foreground | Create Python 3.11 venv | `~/.diapason/.venv/` |
| Foreground | `uv pip install -e .` (editable install) | venv |
| Foreground | Install Ollama | system default |
| Foreground | Start `ollama serve` | systemd-user / launchd / nohup |
| Foreground | Pull `qwen3.5:2b` (~1.5 GB) | Ollama's model store |
| Foreground | Write `config.toml` (auto-detected hardware + engine + model) | `~/.diapason/config.toml` |
| Foreground | Symlink `diapason` and `diapason-uninstall` | `~/.local/bin/` |
| Foreground | Add `~/.local/bin` to PATH if missing (with on-screen notice) | `~/.bashrc` or `~/.zshrc` |
| Background | Install Rust toolchain via rustup | `~/.cargo/` |
| Background | Build the maturin extension (memory + security features) | venv |
| Background | Pull hardware-tier and tier+1 models | Ollama's model store |

## What the installer does NOT touch

- Your existing Python installations
- Your `~/.bashrc` / `~/.zshrc` other than appending one PATH line (with on-screen notice)
- Your existing Ollama models
- Any other tool or dotfile

## Idempotent re-runs

Re-running the local script is safe. The installer reads `~/.diapason/.state/install-state.json` and skips completed steps. If your venv got nuked, re-running heals it.

## Cloud quick-path

If any of these env vars are set when you install or run `diapason init`, the installer/init proposes cloud as the default and writes the matching provider into `config.toml`:

- `OPENROUTER_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY` (or `GEMINI_API_KEY`)

Local-first remains the default when no key is in env. Precedence is OpenRouter > Anthropic > OpenAI > Google.

## Flags

| Flag | Effect |
|---|---|
| `--minimal` | Skip the foreground model pull. First chat will need to wait for the bg pull to finish. |
| `--no-bg-orchestrator` | Don't detach the background work pipeline. (Mostly for testing.) |
| `--force` | Re-run all steps even if `install-state.json` says they're done. |

## Environment overrides

| Variable | Default | Purpose |
|---|---|---|
| `DIAPASON_HOME` | `$HOME/.diapason` | Install location. |
| `DIAPASON_REPO_URL` | `https://github.com/carlitoetienne01-spec/Diapason.git` | Source repo for the clone step. |

## Uninstall

```bash
diapason-uninstall
```

Removes `~/.diapason/`, `~/.local/bin/diapason`, and `~/.local/bin/diapason-uninstall`. Leaves Ollama, uv, and the Rust toolchain in place (they may be used by other tools); the script prints removal hints.

## Updating

```bash
diapason update
```

Pulls the latest source, refreshes the editable install, and rebuilds the Rust extension in the background. Models are not touched.

## Troubleshooting

### "command not found: diapason"

`~/.local/bin` isn't on your PATH. Run `source ~/.bashrc` (or `~/.zshrc`) or open a new terminal.

### "memory features unavailable"

Rust extension hasn't finished building yet (or failed). Check status:

```bash
diapason doctor
```

Manually retry:

```bash
~/.diapason/.scripts/install-rust.sh && ~/.diapason/.scripts/build-extension.sh
```

### A bigger model failed to download

Check status and retry:

```bash
diapason doctor
~/.diapason/.scripts/pull-model.sh qwen3.5:9b
```

### Behind a corporate proxy

Set `HTTPS_PROXY` and `CURL_CA_BUNDLE` in your environment before running the installer.
