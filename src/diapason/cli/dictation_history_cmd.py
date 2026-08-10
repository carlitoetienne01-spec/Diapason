"""CLI: jarvis dictation-history — read back what you dictated."""

from __future__ import annotations

import datetime as _dt

import click


@click.group("dictation-history")
def dictation_history() -> None:
    """Browse the local history of your dictations."""


def _fmt_time(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


@dictation_history.command("list")
@click.option("--limit", default=20, show_default=True, help="How many to show.")
@click.option("--full", is_flag=True, help="Print whole transcripts, unwrapped.")
def list_entries(limit: int, full: bool) -> None:
    """Show recent dictations, newest first."""
    from diapason.desktop.dictation_history import load_history

    entries = load_history(limit=limit)
    if not entries:
        click.echo("No dictations recorded yet.")
        return

    for e in entries:
        where = f" · {e.app}" if e.app else ""
        head = click.style(f"{_fmt_time(e.timestamp)}{where}", fg="cyan")
        click.echo(f"{head}  ({e.chars} chars, {e.duration_s:.1f}s)")
        text = e.text if full else (e.text[:200] + ("…" if len(e.text) > 200 else ""))
        click.echo(f"  {text}\n")


@dictation_history.command("stats")
def show_stats() -> None:
    """Summarise what has been dictated."""
    from diapason.desktop.dictation_history import load_history, stats

    entries = load_history()
    s = stats(entries)
    if not s["count"]:
        click.echo("No dictations recorded yet.")
        return
    click.echo(f"Dictations : {s['count']}")
    click.echo(f"Characters : {s['total_chars']}")
    click.echo(f"Speaking   : {s['total_seconds']:.0f}s")
    click.echo(f"Average    : {s['avg_chars']:.0f} chars per dictation")
    by_app: dict[str, int] = {}
    for e in entries:
        if e.app:
            by_app[e.app] = by_app.get(e.app, 0) + 1
    if by_app:
        click.echo("\nWhere you dictate:")
        for app, n in sorted(by_app.items(), key=lambda kv: -kv[1])[:5]:
            click.echo(f"  {n:4d}  {app}")


@dictation_history.command("last")
def last_entry() -> None:
    """Print the most recent transcript — for when the paste went astray."""
    from diapason.desktop.dictation_history import load_history

    entries = load_history(limit=1)
    if not entries:
        click.echo("No dictations recorded yet.")
        return
    click.echo(entries[0].text)


@dictation_history.command("clear")
@click.confirmation_option(prompt="Delete the whole dictation history?")
def clear() -> None:
    """Delete every recorded dictation."""
    from diapason.desktop.dictation_history import clear_history

    click.echo("History deleted." if clear_history() else "Nothing to delete.")
