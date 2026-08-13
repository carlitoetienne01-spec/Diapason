"""CLI: diapason dictate-service — run dictation in the background at login."""

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
    from diapason.desktop import app_bundle, launch_agent, permissions

    # The .app is what makes Microphone grantable at all: TCC needs an
    # Info.plist with NSMicrophoneUsageDescription, which a bare interpreter
    # launched by launchd does not have.
    bundle = app_bundle.build()
    click.echo(f"Built app bundle → {bundle}")

    path = launch_agent.install(executable=str(app_bundle.executable_path(bundle)))
    click.echo(f"Installed LaunchAgent → {path}")
    if launch_agent.is_loaded():
        click.echo("It will start at every login and restart itself if it crashes.")
    else:
        click.echo(
            "WARNING: launchd did not accept the job. Run "
            "`diapason dictate-service status` to check.",
            err=True,
        )

    # The critical caveat, surfaced rather than buried: TCC grants attach to
    # the bundle, so the ones you gave your terminal do not carry over.
    click.echo("")
    click.echo(
        f"The agent now runs as an app named {app_bundle.BUNDLE_NAME!r}, "
        "which needs its OWN macOS permissions (your terminal's do not carry "
        "over).",
        err=True,
    )
    click.echo(
        f"Opening the three panes. Enable {app_bundle.BUNDLE_NAME!r} under "
        "Input Monitoring and Accessibility. Microphone is requested the "
        "first time it records — approve the popup. Then run:  diapason "
        "dictate-service restart",
        err=True,
    )
    for _pane in ("Input Monitoring", "Accessibility", "Microphone"):
        permissions.open_pane(_pane)


@dictate_service.command("uninstall")
def uninstall() -> None:
    """Stop dictation and remove it from login."""
    _require_macos()
    import shutil

    from diapason.desktop import app_bundle, launch_agent

    existed = launch_agent.uninstall()
    bundle = app_bundle.default_bundle_path()
    if bundle.exists():
        shutil.rmtree(bundle, ignore_errors=True)
    click.echo(
        "Removed the dictation LaunchAgent and app bundle."
        if existed
        else "Nothing installed."
    )


@dictate_service.command("status")
def status() -> None:
    """Show whether the background dictation agent is loaded."""
    _require_macos()
    from diapason.desktop import launch_agent, permissions

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
    from diapason.desktop import launch_agent

    launch_agent.kickstart()
    click.echo("Restarted. Hold Control and speak to test.")


@dictate_service.command("logs")
@click.option("--lines", default=40, show_default=True, help="Tail this many lines.")
def logs(lines: int) -> None:
    """Print the tail of the background agent's logs."""
    _require_macos()
    from diapason.desktop import launch_agent

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
