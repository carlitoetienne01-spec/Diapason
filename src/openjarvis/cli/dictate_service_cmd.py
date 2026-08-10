"""CLI: jarvis dictate-service — run dictation in the background at login."""

from __future__ import annotations

import sys

import click


@click.group("dictate-service")
def dictate_service() -> None:
    """Manage the background dictation LaunchAgent (macOS)."""


def _require_macos() -> None:
    if sys.platform != "darwin":
        click.echo("The dictation service is macOS-only.", err=True)
        sys.exit(1)


@dictate_service.command("install")
def install() -> None:
    """Install and start dictation at login (no terminal needed)."""
    _require_macos()
    from openjarvis.desktop import launch_agent, permissions

    path = launch_agent.install()
    click.echo(f"Installed LaunchAgent → {path}")
    click.echo("It will start at every login and restart itself if it exits.")

    # The critical caveat, surfaced rather than buried: the agent runs the
    # Python binary, so it needs its OWN TCC grants — Terminal's do not carry.
    import sys as _sys

    # Check permissions from the SAME interpreter the agent runs, so the
    # verdict matches the agent's real TCC identity (a Python binary), not the
    # terminal's.
    click.echo("")
    click.echo(
        "IMPORTANT: the background agent runs this Python binary directly, "
        "not your terminal — it needs its OWN permissions:",
        err=True,
    )
    click.echo(f"  {_sys.executable}", err=True)
    click.echo(
        "Opening Input Monitoring and Accessibility now. Find the entry named "
        "'Python' (added when the agent first ran) and switch it ON in BOTH "
        "panes, then run:  jarvis dictate-service restart",
        err=True,
    )
    # Trigger the requests (populate the lists) and open both panes.
    permissions.request_input_monitoring()
    permissions.request_accessibility()
    permissions.open_pane("Input Monitoring")
    permissions.open_pane("Accessibility")


@dictate_service.command("uninstall")
def uninstall() -> None:
    """Stop dictation and remove it from login."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    existed = launch_agent.uninstall()
    click.echo(
        "Removed the dictation LaunchAgent." if existed else "Nothing installed."
    )


@dictate_service.command("status")
def status() -> None:
    """Show whether the background dictation agent is loaded."""
    _require_macos()
    from openjarvis.desktop import launch_agent, permissions

    loaded = launch_agent.is_loaded()
    click.echo(f"LaunchAgent: {'loaded' if loaded else 'not loaded'}")
    click.echo(f"Plist: {launch_agent.plist_path()}")
    missing = permissions.missing_for_dictation()
    click.echo(
        "Permissions: OK"
        if not missing
        else f"Permissions MISSING: {', '.join(missing)}"
    )
    click.echo(f"Logs: {launch_agent.log_dir()}/dictate.out.log (and .err.log)")


@dictate_service.command("restart")
def restart() -> None:
    """Restart the agent — run this after granting permissions."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    launch_agent.kickstart()
    click.echo("Restarted. Hold Control and speak to test.")


@dictate_service.command("logs")
@click.option("--lines", default=40, show_default=True, help="Tail this many lines.")
def logs(lines: int) -> None:
    """Print the tail of the background agent's logs."""
    _require_macos()
    from openjarvis.desktop import launch_agent

    ld = launch_agent.log_dir()
    for name in ("dictate.out.log", "dictate.err.log"):
        p = ld / name
        click.echo(f"\n=== {p} ===")
        if not p.exists():
            click.echo("(no log yet)")
            continue
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in content[-lines:]:
            click.echo(line)
