"""``diapason routines`` — cron routine catalog."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


def _workspace() -> str | None:
    try:
        from diapason.core.config import load_config

        return (load_config().heartbeat.workspace_dir or "").strip() or None
    except Exception:
        return None


def _scheduler():
    from diapason.core.config import DEFAULT_CONFIG_DIR, load_config
    from diapason.scheduler.scheduler import TaskScheduler
    from diapason.scheduler.store import SchedulerStore

    config = load_config()
    db_path = config.scheduler.db_path or str(DEFAULT_CONFIG_DIR / "scheduler.db")
    store = SchedulerStore(db_path)
    return store, TaskScheduler(store)


@click.group("routines")
def routines() -> None:
    """Manage ROUTINES.json cron automations."""


@routines.command("list")
def routines_list() -> None:
    """List routines and enabled state."""
    from diapason.heartbeat.routines import load_routines, load_state

    console = Console()
    items = load_routines(_workspace())
    state = load_state(_workspace())
    last = state.get("last_run") or {}
    table = Table(title="Routines")
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Cron")
    table.add_column("On")
    table.add_column("Last")
    for r in items:
        lr = last.get(r.id) or {}
        table.add_row(
            r.id,
            r.kind,
            r.cron,
            "yes" if r.enabled else "no",
            str(lr.get("at") or "—")[:19],
        )
    console.print(table)


@routines.command("run")
@click.argument("routine_id")
@click.option("--force", is_flag=True, help="Run even if disabled / quiet hours.")
@click.option("--dry-run", is_flag=True, help="No agent — use dry handlers.")
def routines_run(routine_id: str, force: bool, dry_run: bool) -> None:
    """Run a routine once now."""
    from diapason.heartbeat.kinds import run_routine
    from diapason.heartbeat.routines import get_routine

    console = Console()
    routine = get_routine(routine_id, _workspace())
    if routine is None:
        console.print(f"[red]Unknown routine:[/red] {routine_id}")
        raise SystemExit(1)

    system = None
    if not dry_run:
        try:
            from diapason.sdk import Diapason

            with Diapason() as j:
                out = run_routine(
                    routine, system=j, force=force, workspace=_workspace()
                )
            _print_run(console, routine_id, out)
            return
        except Exception as exc:
            console.print(f"[yellow]Diapason unavailable ({exc}); dry run.[/yellow]")

    out = run_routine(routine, system=system, force=force, workspace=_workspace())
    _print_run(console, routine_id, out)


def _print_run(console: Console, rid: str, out: dict) -> None:
    if out.get("skipped"):
        console.print(f"[dim]{rid} skipped ({out.get('reason')})[/dim]")
        return
    if out.get("ok"):
        console.print(f"[green]{rid}[/green]")
        if out.get("quiet"):
            console.print("[dim]quiet hours — not delivered[/dim]")
        content = out.get("content") or ""
        if content:
            console.print(content[:800])
    else:
        console.print(f"[red]{rid} failed[/red] {out.get('error') or out.get('content')}")


@routines.command("enable")
@click.argument("routine_id")
def routines_enable(routine_id: str) -> None:
    from diapason.heartbeat.routines import set_routine_enabled

    r = set_routine_enabled(routine_id, True, _workspace())
    if r is None:
        raise SystemExit(f"Unknown routine: {routine_id}")
    Console().print(f"[green]Enabled[/green] {routine_id}")


@routines.command("disable")
@click.argument("routine_id")
def routines_disable(routine_id: str) -> None:
    from diapason.heartbeat.routines import set_routine_enabled

    r = set_routine_enabled(routine_id, False, _workspace())
    if r is None:
        raise SystemExit(f"Unknown routine: {routine_id}")
    Console().print(f"[yellow]Disabled[/yellow] {routine_id}")


@routines.command("sync")
def routines_sync() -> None:
    """Push heartbeat + routines into the TaskScheduler DB."""
    from diapason.heartbeat.sync import sync_heartbeat_and_routines

    console = Console()
    store, sched = _scheduler()
    try:
        summary = sync_heartbeat_and_routines(sched, workspace=_workspace())
        console.print(f"[green]Synced[/green] heartbeat={summary.get('heartbeat')}")
        for r in summary.get("routines") or []:
            flag = "on" if r.get("active") else "off"
            console.print(f"  {r['task_id']} [{flag}]")
        console.print("[dim]Start the daemon with: diapason scheduler start[/dim]")
    finally:
        store.close()


@routines.command("preview")
def routines_preview() -> None:
    """Show which routines would fire (enabled + cron)."""
    from diapason.heartbeat.routines import load_routines

    console = Console()
    for r in load_routines(_workspace()):
        status = "would-fire" if r.enabled else "disabled"
        console.print(f"{r.id:20} {r.cron:20} {status}")
