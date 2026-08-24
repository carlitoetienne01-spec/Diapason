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
    from diapason.heartbeat.markdown import (
        ensure_heartbeat_file,
        read_heartbeat,
    )

    console = Console()
    cfg = load_config().heartbeat
    ws = _workspace()
    path = ensure_heartbeat_file(ws)
    now, watching = read_heartbeat(ws)
    pending = [t for t in now if not t.done]
    console.print(
        f"[bold]Heartbeat[/bold] enabled={cfg.enabled} interval={cfg.interval_seconds}s"
    )
    console.print(f"  file: {path}")
    console.print(
        f"  pending: {len(pending)}  "
        f"done: {sum(1 for t in now if t.done)}  "
        f"watching: {len(watching)}"
    )
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
@click.option(
    "--force", is_flag=True, help="Run even if heartbeat disabled / quiet hours."
)
@click.option(
    "--dry-run", is_flag=True, help="Do not call the agent (acknowledge only)."
)
def heartbeat_tick(force: bool, dry_run: bool) -> None:
    """Drain the first pending heartbeat task now."""
    from diapason.heartbeat.runner import run_heartbeat_tick

    console = Console()
    system = None
    if not dry_run:
        try:
            from diapason.sdk import Diapason

            # Acknowledge without an agent if Diapason cannot be initialized.
            # Prefer dry acknowledge for CLI simplicity; optional live ask:
            with Diapason() as j:
                result = run_heartbeat_tick(
                    system=j, force=force, workspace=_workspace()
                )
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
        console.print(
            f"[red]Failed[/red] {result.get('error') or result.get('content')}"
        )


@heartbeat.command("clear-done")
def heartbeat_clear_done() -> None:
    """Remove checked items under ## Now."""
    from diapason.heartbeat.markdown import clear_done

    n = clear_done(_workspace())
    Console().print(f"Removed {n} done item(s).")


@heartbeat.command("briefing")
@click.option(
    "--silencieux",
    is_flag=True,
    help="N'affiche rien et ne notifie pas quand il n'y a rien à dire.",
)
@click.option("--sans-notification", is_flag=True, help="Journalise seulement.")
@click.option("--prenom", default="", help="Nom par lequel saluer.")
def heartbeat_briefing(silencieux: bool, sans_notification: bool, prenom: str) -> None:
    """Compose le briefing du jour et le fait parvenir à l'utilisateur.

    C'est la commande qu'un déclencheur (launchd) appelle le matin. Elle ne
    consulte AUCUN modèle : le briefing se compose des données de Succès, ce
    qui le rend instantané, toujours juste, et sans effet sur le créneau
    unique d'Ollama. À ne pas confondre avec ``diapason digest``, qui fait
    rédiger un résumé par le modèle à partir des connecteurs (Gmail, agenda
    Google) — utile quand ils sont branchés, muet sinon.
    """
    from diapason.heartbeat.briefing import briefing_du_jour
    from diapason.heartbeat.livraison import livrer

    console = Console()
    b = briefing_du_jour(prenom=prenom or _prenom_configure())

    if b.rien_a_signaler and silencieux:
        # Une notification quotidienne qui ne dit rien apprend à être ignorée,
        # et le jour où elle compte, elle ne sera pas lue non plus.
        return

    resultat = livrer(b.titre, b.corps, notifier=not sans_notification)
    console.print(b.corps)
    if not resultat.ok:
        console.print(f"[red]Non livré[/red] : {resultat.detail}")
        raise SystemExit(1)
    if not resultat.notifiee and not sans_notification:
        console.print(f"[yellow]Notification non posée[/yellow] : {resultat.detail}")


def _prenom_configure() -> str:
    """Le prénom lu dans USER.md, s'il s'y trouve."""
    import re

    try:
        from diapason.core.paths import get_config_dir

        texte = (get_config_dir() / "USER.md").read_text(encoding="utf-8")
    except Exception:
        return ""
    trouve = re.search(r"Pr[ée]nom[^:\n]*:\s*([^\n,.]+)", texte)
    return trouve.group(1).strip().split()[0] if trouve else ""


@heartbeat.group("briefing-service")
def briefing_service() -> None:
    """Le réveil qui déclenche le briefing chaque matin.

    Il s'appuie sur launchd, l'ordonnanceur de macOS, et NON sur
    l'ordonnanceur interne de Diapason : celui-ci calcule ses crons en UTC
    (sept heures y devient trois heures du matin), son analyseur casse sur
    « */15 » et « 7,13,18 », et sa porte one-shot est inopérante. launchd,
    lui, lit l'heure locale, survit au redémarrage, et exécute au réveil un
    travail manqué pendant que la machine dormait.
    """


def _heure(valeur: str) -> tuple[int, int]:
    morceaux = str(valeur or "").strip().split(":")
    if len(morceaux) != 2 or not all(m.isdigit() for m in morceaux):
        raise click.BadParameter("Format attendu : HH:MM, par exemple 07:00.")
    heure, minute = int(morceaux[0]), int(morceaux[1])
    if not (0 <= heure <= 23 and 0 <= minute <= 59):
        raise click.BadParameter("Heure hors du cadran.")
    return heure, minute


@briefing_service.command("install")
@click.option("--a", "--at", "quand", default="07:00", help="Heure locale, HH:MM.")
def briefing_install(quand: str) -> None:
    """Installe le réveil quotidien du briefing."""
    import sys

    from diapason.desktop import launch_agent

    console = Console()
    heure = _heure(quand)
    chemin = launch_agent.install(
        label=launch_agent.BRIEFING_LABEL,
        args=[
            sys.executable,
            "-m",
            "diapason.cli",
            "heartbeat",
            "briefing",
            "--silencieux",
        ],
        log_prefix="briefing",
        schedule=heure,
    )
    console.print(f"[green]Installé[/green] — briefing à {quand}, tous les jours.")
    console.print(f"  plist   : {chemin}")
    console.print(f"  journaux: {launch_agent.log_dir()}/briefing.out.log")
    console.print("[dim]Essai immédiat : diapason heartbeat briefing[/dim]")


@briefing_service.command("uninstall")
def briefing_uninstall() -> None:
    """Retire le réveil quotidien."""
    from diapason.desktop import launch_agent

    console = Console()
    existait = launch_agent.uninstall(launch_agent.BRIEFING_LABEL)
    console.print("[green]Retiré[/green]" if existait else "[dim]Rien à retirer[/dim]")


@briefing_service.command("status")
def briefing_status() -> None:
    """Dit si le réveil est en place, et à quelle heure."""
    import plistlib

    from diapason.desktop import launch_agent

    console = Console()
    chemin = launch_agent.plist_path(launch_agent.BRIEFING_LABEL)
    if not chemin.exists():
        console.print("[yellow]Aucun réveil installé.[/yellow]")
        console.print(
            "[dim]diapason heartbeat briefing-service install --at 07:00[/dim]"
        )
        return
    with chemin.open("rb") as f:
        donnees = plistlib.load(f)
    quand = donnees.get("StartCalendarInterval") or {}
    charge = launch_agent.is_loaded(launch_agent.BRIEFING_LABEL)
    console.print(
        f"Réveil à {quand.get('Hour', '?'):02}:{quand.get('Minute', 0):02} "
        f"— chargé : {'oui' if charge else 'non'}"
    )
    console.print(f"  plist : {chemin}")


@heartbeat.command("consolidation")
@click.option(
    "--jour",
    default="",
    help="Journée à consolider, AAAA-MM-JJ. Vide = hier.",
)
def consolidation_cmd(jour: str) -> None:
    """Relit la journée, dépose les faits durables, écrit le résumé."""
    from datetime import date

    from diapason.heartbeat.consolidation import consolider_le_jour

    console = Console()
    cible = None
    if jour.strip():
        try:
            cible = date.fromisoformat(jour.strip())
        except ValueError as exc:
            raise click.BadParameter("Format attendu : AAAA-MM-JJ.") from exc

    resultat = consolider_le_jour(cible)
    if resultat.vide:
        console.print("[dim]Aucune conversation ce jour-là — rien à consolider.[/dim]")
        return
    console.print(
        f"[green]Consolidé[/green] — {resultat.echanges_lus} échange(s) relus, "
        f"{resultat.faits_ajoutes} fait(s) nouveaux."
    )
    for fait in resultat.faits:
        console.print(f"  · {fait}")
    if resultat.resume:
        console.print(f"[dim]{resultat.resume}[/dim]")


@heartbeat.group("consolidation-service")
def consolidation_service() -> None:
    """La passe nocturne qui dépose la journée en mémoire durable.

    Même ordonnanceur que le briefing : launchd, en heure locale, avec
    rattrapage au réveil si la machine dormait à l'heure dite.
    """


@consolidation_service.command("install")
@click.option("--a", "--at", "quand", default="03:30", help="Heure locale, HH:MM.")
def consolidation_install(quand: str) -> None:
    """Installe la passe nocturne quotidienne."""
    import sys

    from diapason.desktop import launch_agent

    console = Console()
    heure = _heure(quand)
    chemin = launch_agent.install(
        label=launch_agent.CONSOLIDATION_LABEL,
        args=[
            sys.executable,
            "-m",
            "diapason.cli",
            "heartbeat",
            "consolidation",
        ],
        log_prefix="consolidation",
        schedule=heure,
    )
    console.print(f"[green]Installé[/green] — consolidation à {quand}, chaque nuit.")
    console.print(f"  plist   : {chemin}")
    console.print(f"  journaux: {launch_agent.log_dir()}/consolidation.out.log")
    console.print("[dim]Essai immédiat : diapason heartbeat consolidation[/dim]")


@consolidation_service.command("uninstall")
def consolidation_uninstall() -> None:
    """Retire la passe nocturne."""
    from diapason.desktop import launch_agent

    console = Console()
    existait = launch_agent.uninstall(launch_agent.CONSOLIDATION_LABEL)
    console.print("[green]Retiré[/green]" if existait else "[dim]Rien à retirer[/dim]")


@consolidation_service.command("status")
def consolidation_status() -> None:
    """Dit si la passe nocturne est en place, et à quelle heure."""
    import plistlib

    from diapason.desktop import launch_agent

    console = Console()
    chemin = launch_agent.plist_path(launch_agent.CONSOLIDATION_LABEL)
    if not chemin.exists():
        console.print("[yellow]Aucune passe nocturne installée.[/yellow]")
        console.print(
            "[dim]diapason heartbeat consolidation-service install --at 03:30[/dim]"
        )
        return
    with chemin.open("rb") as f:
        donnees = plistlib.load(f)
    quand = donnees.get("StartCalendarInterval") or {}
    charge = launch_agent.is_loaded(launch_agent.CONSOLIDATION_LABEL)
    console.print(
        f"Consolidation à {quand.get('Hour', '?'):02}:{quand.get('Minute', 0):02} "
        f"— chargée : {'oui' if charge else 'non'}"
    )
    console.print(f"  plist : {chemin}")


@heartbeat.command("tick")
def tick_cmd() -> None:
    """Un passage de la veille de jour : agenda imminent, rappels, batterie."""
    from diapason.heartbeat.tick import faire_le_tick

    console = Console()
    passage = faire_le_tick()
    if not passage.notifications and not passage.erreurs:
        console.print("[dim]Rien à signaler.[/dim]")
        return
    for titre, corps in passage.notifications:
        console.print(f"[green]{titre}[/green] — {corps}")
    for erreur in passage.erreurs:
        console.print(f"[yellow]{erreur}[/yellow]")


@heartbeat.group("tick-service")
def tick_service() -> None:
    """La veille de jour : launchd réveille le tick tous les quarts d'heure.

    Entre le briefing de 07:00 et la consolidation de 03:30, personne ne
    veillait : pas de « rendez-vous dans 20 minutes », pas de batterie
    faible signalée, pas de rappel interne. Le tick est cette veille —
    sans inférence, moins d'une seconde par passage.
    """


@tick_service.command("install")
@click.option(
    "--intervalle",
    default=900,
    type=int,
    help="Secondes entre deux passages (défaut 900 = 15 min).",
)
def tick_install(intervalle: int) -> None:
    """Installe la veille de jour."""
    import sys

    from diapason.desktop import launch_agent

    console = Console()
    chemin = launch_agent.install(
        label=launch_agent.TICK_LABEL,
        args=[sys.executable, "-m", "diapason.cli", "heartbeat", "tick"],
        log_prefix="tick",
        interval_s=max(60, intervalle),
    )
    console.print(
        f"[green]Installé[/green] — un passage toutes les {max(60, intervalle) // 60} min."
    )
    console.print(f"  plist   : {chemin}")
    console.print(f"  journaux: {launch_agent.log_dir()}/tick.out.log")
    console.print("[dim]Essai immédiat : diapason heartbeat tick[/dim]")


@tick_service.command("uninstall")
def tick_uninstall() -> None:
    """Retire la veille de jour."""
    from diapason.desktop import launch_agent

    console = Console()
    existait = launch_agent.uninstall(launch_agent.TICK_LABEL)
    console.print("[green]Retiré[/green]" if existait else "[dim]Rien à retirer[/dim]")


@tick_service.command("status")
def tick_status() -> None:
    """Dit si la veille est en place, et à quel rythme."""
    import plistlib

    from diapason.desktop import launch_agent

    console = Console()
    chemin = launch_agent.plist_path(launch_agent.TICK_LABEL)
    if not chemin.exists():
        console.print("[yellow]Aucune veille installée.[/yellow]")
        console.print("[dim]diapason heartbeat tick-service install[/dim]")
        return
    with chemin.open("rb") as f:
        donnees = plistlib.load(f)
    intervalle = int(donnees.get("StartInterval") or 0)
    charge = launch_agent.is_loaded(launch_agent.TICK_LABEL)
    console.print(
        f"Veille toutes les {intervalle // 60} min — chargée : "
        f"{'oui' if charge else 'non'}"
    )
    console.print(f"  plist : {chemin}")
