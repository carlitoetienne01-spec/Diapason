"""Install `jarvis dictate` as a macOS LaunchAgent — background, no terminal.

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

import subprocess
import sys
from pathlib import Path

LABEL = "com.openjarvis.dictate"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_dir() -> Path:
    from openjarvis.core.paths import get_config_dir

    return get_config_dir() / "logs"


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_plist(*, python: str, workdir: str, out_log: str, err_log: str) -> str:
    """Render the LaunchAgent plist. Runs `python -m openjarvis.cli dictate`.

    ``-m openjarvis.cli`` rather than the console script so the agent does not
    depend on a ``jarvis`` entry point being on any PATH.
    """
    args = [python, "-m", "openjarvis.cli", "dictate"]
    args_xml = "\n".join(f"        <string>{_xml_escape(a)}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
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


def install() -> Path:
    """Write the plist and bootstrap it into the user's launchd domain."""
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_plist(
            python=sys.executable,
            workdir=str(Path.cwd()),
            out_log=str(logs / "dictate.out.log"),
            err_log=str(logs / "dictate.err.log"),
        ),
        encoding="utf-8",
    )
    # bootout first so a re-install picks up a changed plist; ignore if absent.
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_uid()}", str(path)],
        capture_output=True,
        check=False,
    )
    return path


def uninstall() -> bool:
    """Stop the agent and remove its plist. Returns True if a plist existed."""
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    path = plist_path()
    if path.exists():
        path.unlink()
        return True
    return False


def kickstart() -> None:
    """Force a (re)start now, after permissions are granted."""
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{_uid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )


def is_loaded() -> bool:
    r = subprocess.run(
        ["launchctl", "print", f"gui/{_uid()}/{LABEL}"],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0
