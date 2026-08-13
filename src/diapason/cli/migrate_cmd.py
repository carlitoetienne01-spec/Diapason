"""CLI for auditing and applying Diapason compatibility migrations."""

from __future__ import annotations

import click

from diapason.migration import apply_migration, inspect_legacy_state


@click.command("migrate")
@click.option("--check", "check_only", is_flag=True, help="Audit only (default).")
@click.option("--apply", "apply_changes", is_flag=True, help="Apply safe migrations.")
def migrate(check_only: bool, apply_changes: bool) -> None:
    """Audit or migrate legacy OpenJarvis/Jarvis local state."""
    if check_only and apply_changes:
        raise click.UsageError("Choose either --check or --apply, not both.")
    findings = inspect_legacy_state()
    if not findings:
        click.echo("Migration check passed: no legacy local state detected.")
        return

    results = apply_migration(findings) if apply_changes else findings
    for item in results:
        status = "migrated" if item.applied else "action required"
        click.echo(f"[{status}] {item.kind}: {item.source} -> {item.target}")
    if any(item.kind == "environment" for item in results):
        click.echo(
            "Legacy environment variables remain compatible through Diapason 2.0; "
            "rename them in your shell, CI, and service configuration."
        )
    if not apply_changes:
        raise click.exceptions.Exit(1)
