# Native Windows (advanced)

Phase-1 of the native-Windows-support RFC (#298). Mirrors the Linux
(systemd) and macOS (launchd) deployments — but for PowerShell, without
WSL2 or Docker. Choose this over [WSL2](wsl2.md) only if you want to
avoid a Linux VM; WSL2 remains the smoother experience for most users.

## What you get

- A PowerShell installer that probes prerequisites, installs `uv`, clones the
  repo, and installs the desktop/server dependencies without assuming Rust.
- An optional Windows scheduled-task service equivalent to the systemd
  unit and launchd plist.
- Loopback default — the service binds `127.0.0.1` so no API key is
  required.

This is the native Python server and its browser interface. It is **not yet
the Tauri `.msi` desktop application**; that artifact still requires a real
Windows build and validation.

## What you need

- Windows 10 1809+ or Windows 11.
- Python 3.10 – 3.13 (Python 3.14 has no numpy Windows wheels yet —
  see [#432](https://github.com/carlitoetienne01-spec/Diapason/issues/432)).
- `git` on PATH.
- ~5 GB free disk on `%LOCALAPPDATA%`.

## Install

In any PowerShell:

```powershell
# NE FONCTIONNE PAS : le dépôt est privé, cette URL rend 404.
# Voir deploy/windows/README.md pour la procédure à jour :
#   gh auth login
#   git clone https://github.com/carlitoetienne01-spec/Diapason.git `
#     "$env:LOCALAPPDATA\Diapason\src"
#   powershell -ExecutionPolicy Bypass `
#     -File "$env:LOCALAPPDATA\Diapason\src\deploy\windows\install.ps1"
```

The installer will:

1. Refuse non-Windows hosts and old Windows builds.
2. Confirm Python 3.10 – 3.13.
3. Confirm `git`.
4. Install `uv` if absent (via the official `astral.sh/uv` PowerShell
   installer).
5. Clone the repo to `%LOCALAPPDATA%\Diapason\src`.
6. Run `uv sync --extra desktop`; build the native group only if Rust and the
   Windows build tools are present.
7. Install Ollama and the starter model when reachable.
8. Prompt to register the scheduled-task service (skip with
   `-SkipService`).

## Run it

```powershell
cd "$env:LOCALAPPDATA\Diapason\src"
diapason serve
```

Open `http://127.0.0.1:8000/health` to verify.

## Scheduled-task service

If you skipped the prompt during install, register the auto-start task
manually:

```powershell
$srv = "$env:LOCALAPPDATA\Diapason\src\deploy\windows\diapason-service.ps1"
powershell -ExecutionPolicy Bypass -File $srv install

# Or keep the full API on loopback and expose only Mesh to paired devices:
powershell -ExecutionPolicy Bypass -File $srv install -MaillageReseau
```

State:

```powershell
powershell -ExecutionPolicy Bypass -File $srv status
```

## Verify before calling it ready

With the scheduled task running, execute the repository's read-only bench:

```powershell
$verify = "$env:LOCALAPPDATA\Diapason\src\deploy\windows\verify.ps1"
powershell -ExecutionPolicy Bypass -File $verify -RequireNative -RequireMesh
```

This is stricter than checking that a process exists. It imports the Python
package and PyO3 extension, asks `/health`, verifies that port 8000 listens on
loopback only, and proves that port 8001 contains a Mesh door while chat,
health and documentation all return 404. `-Json` produces a report suitable
for attaching to the Mac↔Windows validation notes.

Remove:

```powershell
powershell -ExecutionPolicy Bypass -File $srv uninstall
```

See [`deploy/windows/README.md`](https://github.com/carlitoetienne01-spec/Diapason/blob/main/deploy/windows/README.md)
for the LAN-exposed configuration and the parity table against
systemd / launchd.

## See also

- [WSL2 install](wsl2.md) — the recommended Windows path.
- [Full installer reference](install.md).
