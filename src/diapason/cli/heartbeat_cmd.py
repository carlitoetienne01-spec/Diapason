"""``diapason heartbeat`` — ambient HEARTBEAT.md queue."""

from __future__ import annotations

from typing import Optional

import click
from rich.console import Console
from rich.table import Table


def _workspace() -> Optional[str]:
    try:
        from diapason.core.config import load_config

        return (load_config().heartbeat.workspace_dir or "").strip() or None
    except Exception:
        return None


@click.group("heartbeat")
def heartbeat() -> None:
    """Manage the HEARTBEAT.md ambient task queue."""


@heartbeat.command("status")
def heartbeat_status() -> None:
    """Show pending heartbeat tasks and config."""
    from diapason.core.config import load_config
    from diapason.heartbeat.markdown import ensure_heartbeat_file, pending_now, read_heartbeat

    console = Console()
    cfg = load_config().heartbeat
    ws = _workspace()
    path = ensure_heartbeat_file(ws)
    now, watching = read_heartbeat(ws)
    pending = [t for t in now if not t.done]
    console.print(f"[bold]Heartbeat[/bold] enabled={cfg.enabled} interval={cfg.interval_seconds}s")
    console.print(f"  file: {path}")
    console.print(f"  pending: {len(pending)}  done: {sum(1 for t in now if t.done)}  watching: {len(watching)}")
    for t in pending[:10]:
        console.print(f"  - [ ] {t.text}")


@heartbeat.command("list")
def heartbeat_list() -> None:
    """List ## Now tasks."""
    from diapason.heartbeat.markdown import read_heartbeat

    console = Console()
    now, _ = read_heartbeat(_workspace())
    table = Table(title="HEARTBEAT ## Now")
    table.add_column("Status")
    table.add_column("Task")
    for t in now:
        table.add_row("done" if t.done else "pending", t.text)
    console.print(table)


@heartbeat.command("add")
@click.argument("text")
def heartbeat_add(text: str) -> None:
    """Append a pending task under ## Now."""
    from diapason.heartbeat.markdown import append_task

    task = append_task(text, _workspace())
    Console().print(f"[green]Added[/green] {task.text}")


@heartbeat.command("tick")
@click.option("--force", is_flag=True, help="Run even if heartbeat disabled / quiet hours.")
@click.option("--dry-run", is_flag=True, help="Do not call the agent (acknowledge only).")
def heartbeat_tick(force: bool, dry_run: bool) -> None:
    """Drain the first pending heartbeat task now."""
    from diapason.heartbeat.runner import run_heartbeat_tick

    console = Console()
    system = None
    if not dry_run:
        try:
            from diapason.sdk import Jarvis

            # Leave system None — tick will acknowledge without agent unless Jarvis works
            # Prefer dry acknowledge for CLI simplicity; optional live ask:
            with Jarvis() as j:
                result = run_heartbeat_tick(system=j, force=force, workspace=_workspace())
            _print_tick(console, result)
            return
        except Exception:
            pass
    result = run_heartbeat_tick(system=system, force=force, workspace=_workspace())
    _print_tick(console, result)


def _print_tick(console: Console, result: dict) -> None:
    if result.get("skipped"):
        console.print(f"[dim]Skipped ({result.get('reason')})[/dim]")
        return
    if result.get("ok"):
        console.print(f"[green]Done[/green] {result.get('task')}")
        if result.get("content"):
            console.print(result["content"][:500])
    else:
        console.print(f"[red]Failed[/red] {result.get('error') or result.get('content')}")


@heartbeat.command("clear-done")
def heartbeat_clear_done() -> None:
    """Remove checked items under ## Now."""
    from diapason.heartbeat.markdown import clear_done

    n = clear_done(_workspace())
    Console().print(f"Removed {n} done item(s).")
