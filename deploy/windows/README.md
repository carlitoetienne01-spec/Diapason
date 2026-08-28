# Diapason on native Windows

Phase-1 of the native-Windows-support RFC (#298). Mirrors the Linux
(`deploy/systemd/`) and macOS (`deploy/launchd/`) deployments — but for
PowerShell, without WSL2 or Docker.

> **Portée exacte.** Cet installateur pose aujourd'hui le cœur Python, le
> serveur, le maillage et l'interface web locale. Il **n'installe pas encore
> l'application Tauri `.msi`**. Le workflow sait décrire une construction
> Windows, mais aucune exécution Windows de ce dépôt privé ne l'a encore
> validée. Ne pas confondre « serveur natif Windows » et « application de
> bureau Windows livrée ».

## Installation

> **La commande d'une ligne ne fonctionne pas, et ne peut pas fonctionner.**
> Elle allait chercher le script sur GitHub Pages :
>
> ```powershell
> irm https://carlitoetienne01-spec.github.io/Diapason/install.ps1 | iex   # 404
> ```
>
> Ce dépôt est **privé** : Pages ne publie rien, et cette URL rend une page
> d'erreur — que `iex` exécuterait comme du PowerShell. Vérifié le 26 août
> 2026 : 404 sur le script ET sur la racine du site. Le workflow qui
> publierait Pages est par ailleurs en sommeil, faute de runners GitHub.
>
> Tant que le dépôt reste privé, **clonez d'abord, exécutez ensuite**. Le
> script détecte un dépôt déjà cloné et saute cette étape.

```powershell
# 1. Les outils, si absents
winget install Git.Git
winget install Python.Python.3.13
winget install GitHub.cli

# 2. S'authentifier — le dépôt est privé
gh auth login

# 3. Cloner à l'endroit que le script attend
git clone https://github.com/carlitoetienne01-spec/Diapason.git `
  "$env:LOCALAPPDATA\Diapason\src"

# 4. Lancer l'installateur local
powershell -ExecutionPolicy Bypass `
  -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\install.ps1"
```

What it does:

1. Refuses non-Windows hosts and Windows < 10 1809.
2. Checks Python 3.10 – 3.13 (3.14 has no numpy wheels yet — see #432).
3. Checks `git` on PATH.
4. Installs `uv` (https://astral.sh/uv) if absent.
5. Clones the Diapason repository to `%LOCALAPPDATA%\Diapason\src`
   (override with `$env:DIAPASON_HOME`).
6. Runs `uv sync --extra desktop`; when both Rust and the Windows build tools
   are already present, it also builds `desktop-native`. Otherwise it lists
   the missing tools instead of failing midway through the installation.
7. Installs Ollama and pulls the starter model when the daemon is reachable.
8. Installs a `diapason` shim that invokes the project venv directly — no
   `uv run` at every command, so startup cannot prune installed extras.
9. Optionally prompts to register a scheduled task that auto-starts the
   server at logon.

Flags (when invoked directly rather than via `irm | iex`):

| Flag | Effect |
|------|--------|
| `-Service` | Register the scheduled task without prompting |
| `-MaillageReseau` | With `-Service`, expose only the restricted Mesh socket on port 8001 |
| `-SkipService` | Don't prompt; don't register |
| `-Force` | Re-run all steps even if already done |

`irm | iex` can't pass `param()` args into a piped script string, so
the same knobs are honored via env vars when the corresponding flag is
absent:

```powershell
$env:DIAPASON_SKIP_SERVICE = '1'
powershell -ExecutionPolicy Bypass `
  -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\install.ps1"
```

(Ces variables existaient pour la commande d'une ligne, qui ne pouvait pas
recevoir de paramètres. En exécutant le fichier directement, les drapeaux
`-SkipService`, `-Service` et `-Force` sont plus clairs.)

The available env vars are `DIAPASON_SKIP_SERVICE`, `DIAPASON_SERVICE`,
`DIAPASON_MESH_NETWORK`, and `DIAPASON_FORCE`. Prefer the flags above when
invoking the authenticated local copy of the script.

## Manual scheduled-task setup

If you skipped the prompt during install, you can register / inspect /
remove the task with `diapason-service.ps1`:

```powershell
$srv = "$env:LOCALAPPDATA\Diapason\src\deploy\windows\diapason-service.ps1"

# install (idempotent — replaces existing)
powershell -ExecutionPolicy Bypass -File $srv install

# status
powershell -ExecutionPolicy Bypass -File $srv status

# remove
powershell -ExecutionPolicy Bypass -File $srv uninstall
```

The task runs as the current user with `LogonType=Interactive` and
`RunLevel=Limited`. It restarts up to 3 times on failure (1-minute
gap), has no execution-time limit, and starts when available (catches
up if missed).

## Loopback vs LAN-exposed

By default the scheduled task binds `127.0.0.1` — reachable only from
this machine, no API key required. This matches launchd parity (see
`deploy/launchd/com.diapason.serve.plist`).

To let paired devices discover and reach Mesh:

```powershell
powershell -ExecutionPolicy Bypass -File $srv install -MaillageReseau
```

The complete API stays on `127.0.0.1:8000`. A second socket exposes exactly
the ten Mesh routes on `0.0.0.0:8001`; chat, voice, Succès and the rest of the
API do not exist on that port. `-ListenHost 0.0.0.0` is refused rather than
turning this narrow option back into full API exposure.

The scheduled task executes `.venv\Scripts\diapason.exe` directly. Running
`uv run diapason serve` at every logon used to synchronize the environment
and could remove the native group that the installer had just built.

## Validation on the real PC

Start the scheduled task, then run the read-only verification bench:

```powershell
Start-ScheduledTask -TaskName Diapason
$verify = "$env:LOCALAPPDATA\Diapason\src\deploy\windows\verify.ps1"
powershell -ExecutionPolicy Bypass -File $verify -RequireNative -RequireMesh
```

The bench exits non-zero unless all required facts are true: the project venv
imports `diapason` and `diapason_rust`, `/health` answers on loopback, the full
API has no non-loopback listener, port 8001 listens publicly, chat/health/docs
return 404 on that port, and a signed Mesh door exists. It does not start,
stop, install, pair or transfer anything. Use `-Json` for a machine-readable
report.

Omit `-RequireMesh` only when the service was deliberately installed without
`-MaillageReseau`. Omit `-RequireNative` to diagnose the browser/server-only
installation, but that reduced result is not sufficient to call the Tauri
desktop ready.

## Build the validation MSI on this PC

After the GitHub Actions runner on this PC has the labels
`self-hosted,windows-local`, set the repository variable
`RUNNER_WINDOWS_LOCAL=true` and manually run **Desktop Build & Release**. Its
`build-windows-local` job builds an unsigned validation MSI and keeps a copy
here, even if GitHub artifact upload is unavailable:

```text
%LOCALAPPDATA%\Diapason\artifacts
```

For a deliberate in-place update of the real test PC, manually dispatch the
same workflow with **deploy_windows** enabled. This option is never enabled by
a push or a tag. It requires the runner to have been started from an elevated
PowerShell, refuses a dirty or non-fast-forward installed checkout, repairs
the same-version MSI, restarts the `Diapason` scheduled task, then runs
`verify.ps1 -RequireNative -RequireMesh`. If dependencies changed, it stops
and asks for `install.ps1 -Force` instead of pruning the environment silently.

This artifact disables updater generation and is for the Mac↔Windows bench.
It contains the native window, not a second incomplete copy of Ollama: run the
bootstrap first so system Ollama and the Python backend are present. It is not
a published or Authenticode-signed release. Stable distribution still requires
the release signing and publication path.

## Parity table

| Concern | systemd | launchd | Windows |
|---------|---------|---------|---------|
| Service definition | `deploy/systemd/diapason.service` | `deploy/launchd/com.diapason.serve.plist` | `deploy/windows/diapason-service.ps1` (cmdlet-driven) |
| Default bind | `0.0.0.0` (with API key) | `127.0.0.1` (no API key) | `127.0.0.1` (no API key) |
| Restart on failure | `Restart=on-failure RestartSec=5` | `KeepAlive=true` | `RestartCount=3 RestartInterval=PT1M` |
| Auto-start | `multi-user.target` | `RunAtLoad=true` | `AtLogOn` trigger |

## Updating

To pull the latest:

```powershell
cd "$env:LOCALAPPDATA\Diapason\src"
git pull --ff-only
uv sync --extra desktop
# If cargo + MSVC/CMake/NASM are installed:
uv sync --extra desktop --group desktop-native
```

Or re-run the installer with `-Force`:

```powershell
powershell -ExecutionPolicy Bypass `
  -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\install.ps1" -Force
```

The manual `desktop.yml` deployment can apply a change limited to `uv.lock`.
It first synchronizes the complete locked desktop and local-voice plan in the
runner checkout, then repeats that exact plan in the installed environment.
It still refuses a `pyproject.toml` change: rerun `install.ps1 -Force` when the
set of declared dependencies or installation requirements changes.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\diapason-service.ps1" uninstall
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Diapason"
```

Uninstalling does NOT remove `uv` (it's a separate tool — you may have
other Python projects using it).
