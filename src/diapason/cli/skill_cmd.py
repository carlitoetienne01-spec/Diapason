"""CLI commands for skill management."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

import click
from rich.console import Console
from rich.table import Table

from diapason.core.config import load_config
from diapason.core.events import EventBus
from diapason.core.paths import get_config_dir
from diapason.skills.manager import SkillManager


def _get_trace_store():
    """Return a TraceStore instance from the user config (or None)."""
    try:
        from diapason.core.config import load_config
        from diapason.traces.store import TraceStore

        cfg = load_config()
        return TraceStore(cfg.traces.db_path)
    except Exception:
        return None


def _get_discovered_dir() -> Path:
    """Return the directory where discovered skill manifests are written."""
    return get_config_dir() / "skills" / "discovered"


def _get_overlay_dir() -> Path:
    """Return the directory where optimization overlays are stored."""
    return get_config_dir() / "learning" / "skills"


def _get_skill_paths() -> List[Path]:
    paths: List[Path] = []
    workspace = Path("./skills")
    if workspace.exists():
        paths.append(workspace)
    user_dir = get_config_dir() / "skills"
    paths.append(user_dir)
    return paths


def _get_manager() -> SkillManager:
    mgr = SkillManager(bus=EventBus())
    mgr.discover(paths=_get_skill_paths())
    return mgr


@click.group()
def skill():
    """Manage reusable skills."""


@skill.command("list")
def list_skills():
    """List installed skills."""
    console = Console()
    mgr = _get_manager()
    names = mgr.skill_names()
    if not names:
        console.print("[dim]No skills installed.[/dim]")
        return
    table = Table(title="Installed Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description", max_width=50)
    table.add_column("Version")
    table.add_column("Tags")
    for name in sorted(names):
        m = mgr.resolve(name)
        tags = ", ".join(m.tags) if m.tags else ""
        desc = m.description[:50] + "..." if len(m.description) > 50 else m.description
        table.add_row(name, desc, m.version, tags)
    console.print(table)


@skill.command("info")
@click.argument("skill_name")
def info(skill_name: str):
    """Show detailed information about a skill."""
    console = Console()
    mgr = _get_manager()
    try:
        m = mgr.resolve(skill_name)
    except KeyError:
        console.print(f"[red]Skill '{skill_name}' not found.[/red]")
        raise SystemExit(1)
    console.print(f"[bold]{m.name}[/bold] v{m.version}")
    if m.author:
        console.print(f"Author: {m.author}")
    if m.description:
        console.print(f"Description: {m.description}")
    if m.tags:
        console.print(f"Tags: {', '.join(m.tags)}")
    if m.required_capabilities:
        console.print(f"Capabilities: {', '.join(m.required_capabilities)}")
    if m.depends:
        console.print(f"Dependencies: {', '.join(m.depends)}")
    if m.steps:
        console.print(f"Steps: {len(m.steps)}")
    if m.markdown_content:
        console.print("Has instructions: yes")
    console.print(f"User invocable: {m.user_invocable}")
    console.print(
        f"Model invocation: {'disabled' if m.disable_model_invocation else 'enabled'}"
    )


@skill.command("run")
@click.argument("skill_name")
@click.option("--arg", "-a", multiple=True, help="Arguments as key=value pairs.")
def run(skill_name: str, arg: tuple):
    """Execute a skill directly."""
    console = Console()
    mgr = _get_manager()
    context = {}
    for a in arg:
        if "=" in a:
            k, v = a.split("=", 1)
            context[k.strip()] = v.strip()
    try:
        result = mgr.execute(skill_name, context)
    except KeyError:
        console.print(f"[red]Skill '{skill_name}' not found.[/red]")
        raise SystemExit(1)
    if result.success:
        console.print("[green]Success[/green]")
        if result.step_results:
            console.print(result.step_results[-1].content)
    else:
        console.print("[red]Failed[/red]")
        if result.step_results:
            console.print(result.step_results[-1].content)


def _parse_source_query(query: str) -> tuple[str, str]:
    """Parse a ``<source>:<name>`` query into (source, name).

    Raises ``click.BadParameter`` if the format is wrong.
    """
    if ":" not in query:
        raise click.BadParameter(
            f"Expected '<source>:<name>' format (e.g. 'hermes:apple-notes'), "
            f"got: {query!r}"
        )
    source, _, name = query.partition(":")
    if not source or not name:
        raise click.BadParameter(
            f"Both source and name are required: got source={source!r}, name={name!r}"
        )
    return source, name


def _get_resolver(source: str, url: str = "", path: str = ""):
    """Return a resolver instance for the given source name."""
    if source == "ecc":
        from diapason.skills.sources.ecc import EccResolver, repo_path

        return EccResolver(repo_path(SimpleNamespace(path=path)))
    if source == "hermes":
        from diapason.skills.sources.hermes import HermesResolver

        return HermesResolver()
    if source == "openclaw":
        from diapason.skills.sources.openclaw import OpenClawResolver

        return OpenClawResolver()
    if source == "github":
        if not url:
            raise click.BadParameter("github source requires --url")
        from pathlib import Path as _Path

        from diapason.skills.sources.github import GitHubResolver

        cache = _Path(
            str(get_config_dir() / "skill-cache" / "github")
            + "/"
            + url.rstrip("/").rsplit("/", 1)[-1]
        )
        return GitHubResolver(cache_root=cache, repo_url=url)
    raise click.BadParameter(f"Unknown source: {source!r}")


@skill.command("install")
@click.argument("query")
@click.option(
    "--with-scripts",
    is_flag=True,
    default=False,
    help="Import the skill's scripts/ directory (security-sensitive).",
)
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite existing install."
)
@click.option(
    "--url",
    default="",
    help="Repo URL (required when source is 'github').",
)
@click.option(
    "--yes-dangerous",
    is_flag=True,
    default=False,
    help=(
        "Confirm installing an unreviewed skill that requests dangerous "
        "capabilities (shell/network-listen/filesystem-write)."
    ),
)
def install(query: str, with_scripts: bool, force: bool, url: str, yes_dangerous: bool):
    """Install a skill from a source.

    Example: ``diapason skill install hermes:apple-notes``
    """
    console = Console()
    source, name = _parse_source_query(query)
    if source == "ecc":
        # 28/09/2026: the ECC selection is an allow-list in config.toml; an
        # install by name would bypass it (and the guide would not serve
        # the result anyway — an import that changes nothing, §5).
        console.print(
            "[red]Pour ecc, la sélection vit dans config.toml "
            "(\\[skills.sources.filter] names) : ajoute le nom, puis lance "
            "`diapason skill sync ecc --dry-run` et `diapason skill sync ecc`."
            "[/red]"
        )
        raise SystemExit(1)

    resolver = _get_resolver(source, url=url)
    try:
        resolver.sync()
    except Exception as exc:
        console.print(f"[red]Failed to sync source {source}: {exc}[/red]")
        raise SystemExit(1)

    # Support category/name queries (e.g. openclaw:owner/slug, hermes:apple/apple-notes)
    if "/" in name:
        category, _, skill_name = name.partition("/")
        matches = [
            s
            for s in resolver.list_skills()
            if s.name == skill_name and s.category == category
        ]
    else:
        matches = [s for s in resolver.list_skills() if s.name == name]
    if not matches:
        console.print(f"[red]No skill named '{name}' found in source '{source}'[/red]")
        raise SystemExit(1)

    from diapason.skills.importer import SkillImporter
    from diapason.skills.parser import SkillParser
    from diapason.skills.tool_translator import ToolTranslator

    importer = SkillImporter(parser=SkillParser(), tool_translator=ToolTranslator())
    result = importer.import_skill(
        matches[0],
        with_scripts=with_scripts,
        force=force,
        confirm_dangerous=yes_dangerous,
    )

    if result.success:
        if result.skipped:
            console.print("[yellow]Skill already installed[/yellow]")
        else:
            console.print(f"[green]Installed:[/green] {result.target_path}")
        if result.translated_tools:
            console.print(f"  Translated tools: {', '.join(result.translated_tools)}")
        if result.untranslated_tools:
            console.print(
                f"  [yellow]Untranslated tools:[/yellow] "
                f"{', '.join(result.untranslated_tools)}"
            )
        for warning in result.warnings:
            console.print(f"  [yellow]{warning}[/yellow]")
    else:
        console.print(
            "[red]Install failed: "
            + "; ".join(result.warnings or ["unknown error"])
            + "[/red]"
        )
        raise SystemExit(1)


@skill.command("sync")
@click.argument("source", required=False)
@click.option("--category", default="", help="Filter by category.")
@click.option("--tag", default="", help="Filter by tag.")
@click.option("--search", default="", help="Substring search across name+description.")
@click.option(
    "--with-scripts",
    is_flag=True,
    default=False,
    help="Import scripts/ directories.",
)
@click.option("--force", is_flag=True, default=False, help="Re-import existing skills.")
@click.option(
    "--yes-dangerous",
    is_flag=True,
    default=False,
    help=(
        "Confirm installing unreviewed skills that request dangerous "
        "capabilities (shell/network-listen/filesystem-write)."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be imported, and each skill's state, writing nothing.",
)
def sync(
    source: str,
    category: str,
    tag: str,
    search: str,
    with_scripts: bool,
    force: bool,
    yes_dangerous: bool,
    dry_run: bool,
):
    """Bulk install + update from a source (or all configured sources)."""
    console = Console()

    cfg = load_config()

    # The ECC source reads its allow-list, path and switch from config.toml:
    # `sync ecc` without its [[skills.sources]] block has nothing to import.
    if source == "ecc" or (not source and _ecc_configured(cfg)):
        _sync_ecc(cfg, dry_run=dry_run, force=force, with_scripts=with_scripts)
        if source == "ecc":
            return
    if dry_run:
        console.print(
            "[yellow]--dry-run n'est pris en charge que pour la source ecc : "
            "rien d'autre n'est synchronisé.[/yellow]"
        )
        return

    # Determine which sources to sync
    source_configs: list = []
    if source:
        source_configs.append({"source": source, "filter": {}, "url": ""})
    else:
        for src_cfg in cfg.skills.sources:
            if src_cfg.source == "ecc":
                continue
            source_configs.append(
                {
                    "source": src_cfg.source,
                    "filter": dict(src_cfg.filter or {}),
                    "url": src_cfg.url,
                }
            )

    if not source_configs:
        if _ecc_configured(cfg):
            return
        console.print(
            "[yellow]No sources to sync. "
            "Add sources to [skills.sources] in config.toml "
            "or pass a source name.[/yellow]"
        )
        return

    from diapason.skills.importer import SkillImporter
    from diapason.skills.parser import SkillParser
    from diapason.skills.tool_translator import ToolTranslator

    importer = SkillImporter(parser=SkillParser(), tool_translator=ToolTranslator())

    total_installed = 0
    for src in source_configs:
        console.print(f"[cyan]Syncing {src['source']}...[/cyan]")
        try:
            resolver = _get_resolver(src["source"], url=src["url"])
            resolver.sync()
        except Exception as exc:
            console.print(f"[red]Failed to sync {src['source']}: {exc}[/red]")
            continue

        skills_to_import = resolver.list_skills()

        # Apply CLI filters
        if category:
            skills_to_import = [s for s in skills_to_import if s.category == category]
        if search:
            sl = search.lower()
            skills_to_import = [
                s
                for s in skills_to_import
                if sl in s.name.lower() or sl in s.description.lower()
            ]

        # Apply config filter (categories list)
        cfg_categories = src["filter"].get("category") or []
        if cfg_categories:
            skills_to_import = [
                s for s in skills_to_import if s.category in cfg_categories
            ]

        installed_count = 0
        for resolved in skills_to_import:
            r = importer.import_skill(
                resolved,
                with_scripts=with_scripts,
                force=force,
                confirm_dangerous=yes_dangerous,
            )
            if r.success and not r.skipped:
                installed_count += 1
            elif not r.success and r.requires_confirmation:
                console.print(
                    f"  [yellow]Skipped {resolved.name}: requests dangerous "
                    f"capabilities {r.dangerous_capabilities} "
                    "(re-run with --yes-dangerous to install)[/yellow]"
                )
        console.print(f"  Imported {installed_count}/{len(skills_to_import)} skills")
        total_installed += installed_count

    console.print(f"[green]Total installed: {total_installed}[/green]")


# ---------------------------------------------------------------------------
# The ECC source (28/09/2026): an allow-list, a dry run, and statuses
# ---------------------------------------------------------------------------

_RELANCE = "launchctl kickstart -k gui/$(id -u)/com.diapason.serve"

_BLOC_ECC = """[[skills.sources]]
source = "ecc"
path = "~/Projets/ECC"
enabled = true
[skills.sources.filter]
names = ["research-ops", "article-writing"]"""


def _ecc_configured(cfg) -> bool:
    from diapason.skills.sources.ecc import ecc_source_config

    return ecc_source_config(cfg) is not None


def _short(commit: str) -> str:
    return (commit or "?")[:7]


def _read_dot_source(skill_dir: Path) -> dict:
    try:
        import tomllib

        with open(skill_dir / ".source", "rb") as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable .source is a status
        return {}


def _folder(chemin: str) -> str:
    """« skills/<dossier> » from a .source ``chemin`` (…/SKILL.md)."""
    return chemin.rsplit("/", 1)[0] if chemin.endswith("/SKILL.md") else chemin


_DOSSIER_CHANGE = "dossier changé"


def _ecc_status(upstream, installed_dir: Path | None) -> str:
    """nouvelle / à jour / changée en amont / retirée en amont / copie altérée
    / dossier changé.

    Compares the .source written at import time with HEAD's files (was it
    changed upstream? does the same NAME now come from another folder?) and
    with the files on disk (was the copy edited?).
    """
    from diapason.skills.provenance import fingerprint

    if upstream is None:
        return "retirée en amont" if installed_dir else "introuvable en amont"
    if installed_dir is None:
        return "nouvelle"
    prov = _read_dot_source(installed_dir)
    parts = []
    ancien = str(prov.get("chemin") or "")
    nouveau = str(upstream.sidecar_data.get("provenance", {}).get("chemin") or "")
    if ancien and nouveau and ancien != nouveau:
        # 29/09/2026: `name: research-ops` in a NEW folder took over the
        # allowed name at the next --force; the diff Carlito was told to
        # read (`git log -p -- skills/research-ops`) was empty.
        parts.append(f"{_DOSSIER_CHANGE} ({_folder(ancien)} → {_folder(nouveau)})")
    if fingerprint(installed_dir, text_only=True) != prov.get("sha256_importe"):
        parts.append("copie altérée")
    if upstream.sidecar_data.get("fingerprint") != prov.get("sha256_source"):
        parts.append(
            f"changée en amont ({_short(str(prov.get('commit', '')))} → "
            f"{_short(upstream.commit)})"
        )
    return ", ".join(parts) or "à jour"


def _other_sources_by_name() -> dict[str, list[str]]:
    """Installed skills from any source but ecc, by manifest name."""
    from diapason.skills.loader import discover_skills

    others: dict[str, list[str]] = {}
    for root in _get_skill_paths():
        for manifest in discover_skills(root):
            meta = (manifest.metadata or {}).get("diapason") or {}
            src = meta.get("source") or "local"
            if src != "ecc":
                others.setdefault(manifest.name, []).append(str(src))
    return others


def _sync_ecc(cfg, *, dry_run: bool, force: bool, with_scripts: bool) -> None:
    """Show the ECC selection (always), then import it (unless --dry-run).

    Only names written in filter.names are imported: the allow-list is
    Carlito's, never widened here. A name colliding with another source is
    said, never hidden. Nothing ever touches the clone.
    """
    from rich.markup import escape

    from diapason.skills.importer import SkillImporter
    from diapason.skills.parser import SkillParser
    from diapason.skills.sources.ecc import (
        AllowListError,
        EccResolver,
        allowed_names,
        ecc_source_config,
        installed_root,
        repo_path,
    )
    from diapason.skills.tool_translator import ToolTranslator

    # soft_wrap: a status must stay on its line, whatever the terminal width.
    console = Console(soft_wrap=True, highlight=False)
    src_cfg = ecc_source_config(cfg)
    if src_cfg is None:
        console.print(
            "[red]Aucune source ecc dans config.toml. Ajoute ce bloc (les noms "
            "sont une liste d'autorisation, sans joker) :[/red]"
        )
        console.print(escape(_BLOC_ECC))
        raise SystemExit(1)
    if with_scripts:
        console.print(
            "[red]Refus : les scripts d'ECC ne s'importent jamais (plafond "
            "décidé le 28/09/2026).[/red]"
        )
        raise SystemExit(1)
    try:
        names = allowed_names(src_cfg)
    except AllowListError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise SystemExit(1)

    root = installed_root(cfg)
    if root is None:
        console.print("[red]skills_dir illisible dans [skills] : rien à faire.[/red]")
        raise SystemExit(1)
    if root.is_symlink():
        # 29/09/2026: a skills/ecc linked to the clone's skills/ made
        # `--force` empty skills/<name> IN the clone. served_skills already
        # refused to serve through such a link; the import did not.
        console.print(
            f"[red]{escape(str(root))} est un lien symbolique : les méthodes "
            "doivent être des COPIES, jamais le clone lui-même. Remplace le "
            "lien par un dossier vide, puis relance.[/red]"
        )
        raise SystemExit(1)
    resolver = EccResolver(repo_path(src_cfg))
    try:
        resolver.sync()
    except FileNotFoundError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise SystemExit(1)
    state = resolver.state
    upstream = resolver.list_skills()
    # 29/09/2026: the allow-list names what the frontmatter DECLARES, and
    # `{s.name: s}` kept, in silence, the LAST folder declaring it. An
    # upstream skills/research-ops-v2/ with `name: research-ops` was served
    # under the allowed name. A name two folders declare is refused.
    declared: dict[str, list] = {}
    for skill in upstream:
        declared.setdefault(skill.name, []).append(skill)
    by_name = {name: found[0] for name, found in declared.items() if len(found) == 1}
    by_dir = {s.sidecar_data.get("dir"): s for s in upstream}
    installed: dict[str, Path] = {}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                installed[child.name] = child
    others = _other_sources_by_name()

    etat_git = (
        f"HEAD {_short(state.head)}"
        if not state.git_error
        else f"git illisible ({state.git_error})"
    )
    console.print(
        f"[bold]Source ecc[/bold] : {escape(str(resolver.cache_dir()))} — "
        f"{etat_git}, version {escape(state.version or '?')}, "
        f"{len(upstream)} compétences en amont"
    )
    hors = state.dirty_outside_skills()
    if hors:
        console.print(f"  dépôt modifié hors skills/ : {hors} fichier(s)")
    if getattr(src_cfg, "enabled", True) is not True:
        console.print(
            "  [yellow]source coupée (enabled = false) : rien n'est servi au "
            "modèle, rien ne sera importé.[/yellow]"
        )
    if not names:
        console.print(
            "  [yellow]liste d'autorisation vide (filter.names) : rien à "
            "importer.[/yellow]"
        )
    console.print(f"  liste d'autorisation : {len(names)} nom(s)")

    statuses: dict[str, str] = {}
    ambiguous: list[str] = []
    for name in names:
        found = declared.get(name, [])
        if len(found) > 1:
            ambiguous.append(name)
            dossiers = ", ".join(
                sorted(f"skills/{s.sidecar_data.get('dir')}" for s in found)
            )
            console.print(
                f"- {escape(name)} — [red]AMBIGUË : {len(found)} dossiers "
                f"déclarent ce nom ({escape(dossiers)}). Jamais importée tant "
                "qu'un seul dossier le porte.[/red]"
            )
            continue
        up = by_name.get(name)
        status = _ecc_status(up, installed.get(name))
        statuses[name] = status
        if up is None:
            console.print(f"- {escape(name)} — {status}")
            if name in by_dir:
                console.print(
                    f"    c'est un DOSSIER d'ECC ; son nom est "
                    f"« {escape(by_dir[name].name)} » : c'est ce nom qu'il faut "
                    "écrire dans filter.names."
                )
            continue
        prov = up.sidecar_data.get("provenance", {})
        console.print(
            f"- {escape(name)} — origine {escape(prov.get('origine') or '?')}, "
            f"≈{up.sidecar_data.get('tokens', 0)} jetons, "
            f"{up.sidecar_data.get('sections', 0)} sections — {escape(status)}"
        )
        console.print(f"    dossier : skills/{escape(str(up.sidecar_data.get('dir')))}")
        outils = ", ".join(prov.get("outils_cites") or []) or "aucun"
        citees = ", ".join(prov.get("competences_citees") or []) or "aucune"
        absentes = ", ".join(prov.get("ressources_absentes") or []) or "aucune"
        renvois = ", ".join(up.sidecar_data.get("flags") or []) or "aucun"
        console.print(f"    licence : {escape(prov.get('licence') or '?')}")
        console.print(f"    outils cités : {escape(outils)}")
        console.print(f"    compétences ECC citées : {escape(citees)}")
        console.print(
            f"    ressources absentes (jamais importées) : {escape(absentes)}"
        )
        console.print(f"    renvois à MCP / npx / ~/.claude : {escape(renvois)}")
        if prov.get("depot_modifie"):
            console.print("    [yellow]modifiée localement dans le clone[/yellow]")
        for other in others.get(name, []):
            console.print(
                f"    [yellow]collision : « {escape(name)} » existe aussi dans la "
                f"source {escape(other)} ; les deux restent sur le disque, le "
                "guide ne lit que la copie ecc.[/yellow]"
            )
    for name in sorted(set(installed) - set(names)):
        console.print(
            f"- {escape(name)} — hors liste : installée, jamais servie au modèle "
            f"(`diapason skill remove {escape(name)}` pour l'enlever)"
        )

    if dry_run:
        console.print("[yellow]--dry-run : rien n'a été écrit.[/yellow]")
        if ambiguous:
            raise SystemExit(1)
        return
    if getattr(src_cfg, "enabled", True) is not True:
        if ambiguous:
            raise SystemExit(1)
        return

    importer = SkillImporter(
        parser=SkillParser(),
        tool_translator=ToolTranslator({}),
        target_root=root.parent,
    )
    imported = 0
    refused = list(ambiguous)
    for name in names:
        if name in ambiguous:
            continue
        up = by_name.get(name)
        status = statuses[name]
        if _DOSSIER_CHANGE in status:
            # Not even with --force: another folder now speaks under an
            # allowed name. Accepting it is a decision, taken by hand.
            refused.append(name)
            dossier = f"skills/{up.sidecar_data.get('dir')}" if up else "?"
            console.print(
                f"  [red]{escape(name)} : {escape(status)} — jamais réimportée, "
                f"même avec --force. Relis {escape(dossier)}/SKILL.md ; pour "
                f"l'accepter : `diapason skill remove {escape(name)}` puis "
                "`diapason skill sync ecc`.[/red]"
            )
            continue
        if up is None:
            if status == "retirée en amont":
                console.print(
                    f"  [yellow]{escape(name)} : retirée en amont — la copie "
                    "reste, rien n'est effacé.[/yellow]"
                )
            continue
        if status == "à jour":
            continue
        if status != "nouvelle" and not force:
            console.print(
                f"  [yellow]{escape(name)} : {status} — relance avec --force "
                "pour réimporter.[/yellow]"
            )
            continue
        result = importer.import_skill(up, force=True)
        if result.success and not result.skipped:
            imported += 1
            console.print(f"  [green]importée[/green] : {escape(name)}")
        else:
            console.print(
                f"  [red]{escape(name)} : "
                f"{escape('; '.join(result.warnings) or 'échec')}[/red]"
            )
    console.print(f"[green]{imported} compétence(s) importée(s).[/green]")
    if imported:
        console.print(
            "Le chat lit sa trousse au démarrage : relance le service pour "
            f"qu'il voie l'outil skill_guide — {_RELANCE}"
        )
    if refused:
        console.print(
            f"[red]{len(refused)} nom(s) refusé(s) : {escape(', '.join(refused))}."
            "[/red]"
        )
        raise SystemExit(1)


@skill.command("sources")
def sources():
    """List configured skill sources."""
    console = Console()

    cfg = load_config()

    if not cfg.skills.sources:
        console.print(
            "[dim]No skill sources configured. "
            "Add entries to [skills.sources] in config.toml.[/dim]"
        )
        return

    table = Table(title="Configured Skill Sources")
    table.add_column("Source", style="cyan")
    table.add_column("URL / path")
    table.add_column("Filter")
    table.add_column("Enabled")
    table.add_column("Auto-update")
    for s in cfg.skills.sources:
        filt = ", ".join(f"{k}={v}" for k, v in (s.filter or {}).items()) or "—"
        table.add_row(
            s.source,
            s.url or getattr(s, "path", "") or "(default)",
            filt,
            "yes" if getattr(s, "enabled", True) else "no",
            "yes" if s.auto_update else "no",
        )
    console.print(table)


@skill.command("remove")
@click.argument("skill_name")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
def remove(skill_name: str, yes: bool):
    """Remove an installed skill by name.

    Searches ``~/.diapason/skills/`` and ``./skills`` for a directory whose
    name (or parsed manifest name) matches ``skill_name`` and deletes it.
    """
    console = Console()
    mgr = SkillManager(bus=EventBus())
    paths = mgr.find_installed_paths(skill_name, roots=_get_skill_paths())
    if not paths:
        console.print(f"[red]No installed skill named '{skill_name}' found.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]Will remove {len(paths)} location(s):[/bold]")
    for p in paths:
        console.print(f"  - {p}")

    if not yes:
        if not click.confirm("Proceed?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    try:
        removed = mgr.remove(skill_name, roots=_get_skill_paths())
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    for p in removed:
        console.print(f"[green]Removed:[/green] {p}")


@skill.command("search")
@click.argument("query")
@click.option(
    "--source",
    "-s",
    default="",
    help="Restrict search to a single configured source.",
)
def search(query: str, source: str):
    """Search available skills across configured sources.

    Matches ``query`` (case-insensitive substring) against skill name,
    description, and tags.
    """
    console = Console()
    cfg = load_config()

    if not cfg.skills.sources:
        console.print(
            "[yellow]No skill sources configured. "
            "Add entries to [skills.sources] in config.toml.[/yellow]"
        )
        raise SystemExit(1)

    sources_to_search = [
        s for s in cfg.skills.sources if not source or s.source == source
    ]
    if source and not sources_to_search:
        console.print(f"[red]No configured source named '{source}'.[/red]")
        raise SystemExit(1)

    q = query.lower().strip()
    rows: list[tuple[str, str, str, str]] = []  # source, name, category, description
    for src_cfg in sources_to_search:
        try:
            resolver = _get_resolver(
                src_cfg.source, url=src_cfg.url, path=getattr(src_cfg, "path", "")
            )
            resolver.sync()
        except Exception as exc:
            console.print(f"[yellow]Skipped {src_cfg.source}: {exc}[/yellow]")
            continue

        for resolved in resolver.list_skills():
            haystack = " ".join(
                [
                    resolved.name or "",
                    resolved.description or "",
                    resolved.category or "",
                ]
            ).lower()
            if q in haystack:
                rows.append(
                    (
                        src_cfg.source,
                        resolved.name,
                        getattr(resolved, "category", "") or "",
                        (getattr(resolved, "description", "") or "")[:60],
                    )
                )

    if not rows:
        console.print(f"[dim]No skills matching '{query}'.[/dim]")
        return

    table = Table(title=f"Search results for '{query}'")
    table.add_column("Source", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Category")
    table.add_column("Description", max_width=60)
    for row in rows:
        table.add_row(*row)
    console.print(table)
    console.print(
        f"[dim]{len(rows)} match(es). "
        f"Install with: diapason skill install <source>:<name>[/dim]"
        if any(row[0] != "ecc" for row in rows)
        else f"[dim]{len(rows)} match(es).[/dim]"
    )
    if any(row[0] == "ecc" for row in rows):
        # `install ecc:<nom>` is refused (it would bypass the allow-list):
        # the hint must not send Carlito into that refusal.
        console.print(
            "[dim]Pour ecc : ajoute le nom à filter.names dans config.toml, "
            "puis `diapason skill sync ecc --dry-run`.[/dim]"
        )


@skill.command("update")
def update():
    """Pull latest commits for all installed skill sources."""
    console = Console()

    cfg = load_config()
    if not cfg.skills.sources:
        console.print("[dim]No sources configured.[/dim]")
        return

    for src in cfg.skills.sources:
        if src.source == "ecc":
            # Diapason never touches the clone: pulling it is Carlito's act.
            console.print(
                "[cyan]ecc[/cyan] : lecture locale, rien à tirer. Le `git pull` "
                "du clone reste ton geste, puis `diapason skill sync ecc "
                "--dry-run`."
            )
            continue
        console.print(f"[cyan]Updating {src.source}...[/cyan]")
        try:
            resolver = _get_resolver(src.source, url=src.url)
            resolver.sync()
            console.print("  [green]OK[/green]")
        except Exception as exc:
            console.print(f"  [red]Failed: {exc}[/red]")


@skill.command("discover")
@click.option(
    "--min-frequency",
    "-f",
    default=3,
    show_default=True,
    type=int,
    help="Minimum recurrence count to surface a tool sequence as a skill.",
)
@click.option(
    "--min-outcome",
    "-o",
    default=0.5,
    show_default=True,
    type=float,
    help="Minimum average outcome score (0.0-1.0) to qualify.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print discovered patterns without writing manifests.",
)
def discover(min_frequency: int, min_outcome: float, dry_run: bool) -> None:
    """Mine the trace store for recurring tool sequences and write them as
    discovered skill manifests under ~/.diapason/skills/discovered/."""
    console = Console()
    store = _get_trace_store()
    if store is None:
        console.print(
            "[red]No trace store found. "
            "Enable tracing in config (traces.enabled = true) and run "
            "some queries first.[/red]"
        )
        raise SystemExit(1)

    output_dir = _get_discovered_dir()
    mgr = SkillManager(bus=EventBus())

    if dry_run:
        # Use a temporary directory so nothing is persisted
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="diapason-discover-dryrun-"))
        try:
            written = mgr.discover_from_traces(
                store,
                min_frequency=min_frequency,
                min_outcome=min_outcome,
                output_dir=tmp,
            )
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
    else:
        written = mgr.discover_from_traces(
            store,
            min_frequency=min_frequency,
            min_outcome=min_outcome,
            output_dir=output_dir,
        )

    if not written:
        console.print(
            "[dim]No recurring tool sequences found above the threshold.[/dim]"
        )
        return

    table = Table(title="Discovered Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Path")
    for item in written:
        table.add_row(item["name"], item["path"])
    console.print(table)
    if dry_run:
        console.print("[yellow]--dry-run: no files were written.[/yellow]")


@skill.command("show-overlay")
@click.argument("skill_name")
def show_overlay(skill_name: str) -> None:
    """Show the optimization overlay for a skill, if one exists."""
    console = Console()
    from diapason.skills.overlay import SkillOverlayLoader

    loader = SkillOverlayLoader(_get_overlay_dir())
    overlay = loader.load(skill_name)
    if overlay is None:
        console.print(f"[red]No overlay found for skill '{skill_name}'.[/red]")
        raise SystemExit(1)

    console.print(f"[bold]{overlay.skill_name}[/bold]")
    console.print(f"Optimizer: {overlay.optimizer}")
    console.print(f"Optimized at: {overlay.optimized_at}")
    console.print(f"Trace count: {overlay.trace_count}")
    console.print(f"Description: {overlay.description}")
    if overlay.few_shot:
        console.print(f"Few-shot examples ({len(overlay.few_shot)}):")
        for i, ex in enumerate(overlay.few_shot, start=1):
            inp = (ex.get("input", "") or "")[:100]
            out = (ex.get("output", "") or "")[:100]
            console.print(f"  {i}. input={inp!r}")
            console.print(f"     output={out!r}")


__all__ = ["skill"]
