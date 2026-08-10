"""CLI: jarvis serve-service — keep the API server running at login.

The desktop app talks to the Python backend on 127.0.0.1:8000. Without this,
the app shows "Backend unreachable" until someone remembers to run
`jarvis serve` in a terminal — and loses it again when that terminal closes.

Unlike the dictation agent, this one needs no TCC permissions: it opens a
loopback socket and touches neither the keyboard nor the microphone. So it
installs and works in one step.
"""

from __future__ import annotations

import sys

import click

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


@click.group("serve-service")
def serve_service() -> None:
    """Manage the background API server (macOS LaunchAgent)."""


def _require_macos() -> None:
    if sys.platform != "darwin":
        click.echo("The serve service is macOS-only.", err=True)
        sys.exit(1)


def _label():
    from openjarvis.desktop import launch_agent

    return launch_agent.SERVE_LABEL


@serve_service.command("install")
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int)
def install(host: str, port: int) -> None:
    """Run the API server at login, in the background."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    if host not in ("127.0.0.1", "localhost", "::1"):
        # Binding beyond loopback exposes the API to the network. That is a
        # deliberate choice with security consequences, not a default.
        click.echo(
            f"Refusing to bind {host!r} from a background service: it would "
            "expose the API beyond this machine. Use 127.0.0.1, or run "
            "`jarvis serve` manually if you really mean to.",
            err=True,
        )
        sys.exit(1)

    path = launch_agent.install(
        label=launch_agent.SERVE_LABEL,
        log_prefix="serve",
        args=[
            sys.executable,
            "-m",
            "openjarvis.cli",
            "serve",
            "--host",
            host,
            "--port",
            str(port),
        ],
    )
    click.echo(f"Installed LaunchAgent → {path}")
    if launch_agent.is_loaded(launch_agent.SERVE_LABEL):
        click.echo(f"API server running at http://{host}:{port} — and at every login.")
    else:
        click.echo(
            "WARNING: launchd did not accept the job. Check "
            "`jarvis serve-service logs`.",
            err=True,
        )


@serve_service.command("uninstall")
def uninstall() -> None:
    """Stop the API server and remove it from login."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    existed = launch_agent.uninstall(launch_agent.SERVE_LABEL)
    click.echo(
        "Removed the API server LaunchAgent." if existed else "Nothing installed."
    )


@serve_service.command("status")
def status() -> None:
    """Show whether the API server agent is loaded and answering."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    loaded = launch_agent.is_loaded(launch_agent.SERVE_LABEL)
    click.echo(f"LaunchAgent: {'loaded' if loaded else 'not loaded'}")
    click.echo(f"Plist: {launch_agent.plist_path(launch_agent.SERVE_LABEL)}")

    # Loaded is not the same as answering — say which.
    reachable = False
    try:
        import urllib.request

        with urllib.request.urlopen(
            f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/health", timeout=3
        ) as r:
            reachable = r.status == 200
    except Exception:  # noqa: BLE001
        reachable = False
    click.echo(f"Health: {'answering' if reachable else 'not answering'}")
    click.echo(f"Logs: {launch_agent.log_dir()}/serve.out.log (and .err.log)")


@serve_service.command("restart")
def restart() -> None:
    """Restart the API server."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    launch_agent.kickstart(launch_agent.SERVE_LABEL)
    click.echo("Restarted.")


@serve_service.command("logs")
@click.option("--lines", default=40, show_default=True)
def logs(lines: int) -> None:
    """Print the tail of the API server logs."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    ld = launch_agent.log_dir()
    for name in ("serve.out.log", "serve.err.log"):
        p = ld / name
        click.echo(f"\n=== {p} ===")
        if not p.exists():
            click.echo("(no log yet)")
            continue
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in content[-lines:]:
            click.echo(line)
