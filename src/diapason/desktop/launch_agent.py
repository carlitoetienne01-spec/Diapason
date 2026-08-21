"""Install Diapason background services as macOS LaunchAgents.

Two services use this: the dictation agent (`diapason dictate`) and the API
server (`diapason serve`). They differ only in label and arguments, so the
plist builder is parameterised rather than duplicated.

A LaunchAgent (not a LaunchDaemon) runs in the user's GUI session at login,
which is required: the key tap and the paste both need a logged-in graphical
session. The plist is generated from the CURRENT interpreter so it keeps
working regardless of where the venv lives.

The unavoidable caveat, made explicit to the caller: TCC permissions
(Input Monitoring, Accessibility) attach to the executable, and the agent runs
the Python binary directly — NOT Terminal. The grants you gave Terminal do not
transfer. The agent's first run requests them for the Python binary; you grant
those once, then `launchctl kickstart` it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LABEL = "com.diapason.dictate"  # dictation agent
SERVE_LABEL = "com.diapason.serve"  # API server


def plist_path(label: str = LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def log_dir() -> Path:
    from diapason.core.paths import get_config_dir

    return get_config_dir() / "logs"


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_plist(
    *,
    python: str,
    workdir: str,
    out_log: str,
    err_log: str,
    executable: str | None = None,
    label: str = LABEL,
    args: list[str] | None = None,
) -> str:
    """Render the LaunchAgent plist.

    When *executable* is given (the .app bundle's launcher), launchd runs THAT
    — which is what gives the process a bundle identity, and therefore the
    ability to hold Microphone permission at all. Falling back to the bare
    interpreter keeps the agent usable on a machine where the bundle could not
    be built, at the cost of a mic that macOS will never authorise.
    """
    if args is not None:
        program_args = args
    elif executable:
        program_args = [executable]
    else:
        program_args = [python, "-m", "diapason.cli", "dictate"]
    args = program_args
    args_xml = "\n".join(f"        <string>{_xml_escape(a)}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{_xml_escape(workdir)}</string>
    <key>RunAtLoad</key>
    <true/>
    <!-- Restart on CRASH only, not on a clean exit. When permissions are not
         yet granted the process exits 0 on purpose and must NOT be relaunched
         in a loop (that spam of prompts is exactly what a naive KeepAlive:true
         produced). After the grant, `dictate-service restart` starts it fresh. -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>{_xml_escape(out_log)}</string>
    <key>StandardErrorPath</key>
    <string>{_xml_escape(err_log)}</string>
</dict>
</plist>
"""


def _uid() -> int:
    import os

    return os.getuid()


def install(
    *,
    executable: str | None = None,
    label: str = LABEL,
    args: list[str] | None = None,
    log_prefix: str = "dictate",
) -> Path:
    """Write the plist and bootstrap it into the user's launchd domain.

    Logs are truncated here: they accumulate one block per (re)start, and a
    stale wall of "still missing" lines from an earlier attempt makes the
    current state impossible to read.
    """
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)
    for name in (f"{log_prefix}.out.log", f"{log_prefix}.err.log"):
        try:
            (logs / name).write_text("", encoding="utf-8")
        except OSError:
            pass
    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_plist(
            python=sys.executable,
            # HOME, not the project dir: the project may sit under a
            # TCC-protected folder the agent cannot read.
            workdir=str(Path.home()),
            out_log=str(logs / f"{log_prefix}.out.log"),
            err_log=str(logs / f"{log_prefix}.err.log"),
            executable=executable,
            label=label,
            args=args,
        ),
        encoding="utf-8",
    )
    _bootstrap(path, label=label)
    return path


def _bootstrap(path: Path, *, attempts: int = 5, label: str = LABEL) -> bool:
    """Reload the agent, tolerating launchd's asynchronous unload.

    ``bootout`` returns before the job is fully gone, so an immediate
    ``bootstrap`` loses a race and fails with "service already loaded" —
    silently, since the output was being discarded. Retrying briefly is the
    documented way through it.
    """
    import time

    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{label}"],
        capture_output=True,
        check=False,
    )
    for attempt in range(attempts):
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{_uid()}", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True
        time.sleep(0.3 * (attempt + 1))
    return False


def uninstall(label: str = LABEL) -> bool:
    """Stop the agent and remove its plist. Returns True if a plist existed."""
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{label}"],
        capture_output=True,
        check=False,
    )
    path = plist_path(label)
    if path.exists():
        path.unlink()
        return True
    return False


def kickstart(label: str = LABEL) -> None:
    """Force a (re)start now, after permissions are granted."""
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{_uid()}/{label}"],
        capture_output=True,
        check=False,
    )


def job_pid(label: str = LABEL) -> int | None:
    """Le PID que launchd donne à ce job, ou None s'il n'en a pas.

    « Chargé » n'est ni « vivant » ni « seul » : ``is_loaded`` répond vrai pour
    un job déclaré mais arrêté. Avec un PID, on peut comparer au détenteur réel
    d'un port et savoir si le service qu'on croit posséder est bien celui qui
    sert.
    """
    r = subprocess.run(
        ["launchctl", "print", f"gui/{_uid()}/{label}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    trouve = re.search(r"\n\tpid = (\d+)\n", r.stdout)
    return int(trouve.group(1)) if trouve else None


def is_loaded(label: str = LABEL) -> bool:
    r = subprocess.run(
        ["launchctl", "print", f"gui/{_uid()}/{label}"],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0
