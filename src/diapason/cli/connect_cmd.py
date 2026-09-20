"""``diapason connect`` -- manage data source connections."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


def _list_sources(registry: object) -> None:
    """Print a Rich table of registered connectors and their sync status."""
    console = Console()
    items = registry.items()  # type: ignore[attr-defined]

    if not items:
        console.print("[yellow]No connectors registered.[/yellow]")
        return

    table = Table(title="Connected Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")

    for key, connector_cls in items:
        # Try to instantiate with no args to check status (best-effort)
        try:
            instance = connector_cls()
            connected = instance.is_connected()
            status = "connected" if connected else "disconnected"
            auth_type = getattr(connector_cls, "auth_type", "unknown")
        except Exception:  # noqa: BLE001
            status = "unknown"
            auth_type = getattr(connector_cls, "auth_type", "unknown")

        table.add_row(key, auth_type, status)

    console.print(table)

    # Un « disconnected » sur une base locale n'est presque jamais une
    # absence de fichier : c'est une autorisation macOS manquante. Le dire
    # ici, avec le bon chemin de binaire, épargne une heure de recherche —
    # et évite d'autoriser un lien symbolique, qui ne sert à rien.
    from diapason.connectors._stubs import tcc_remediation

    conseil = tcc_remediation(_local_db_paths(registry))
    if conseil:
        console.print()
        console.print(conseil)


def _local_db_paths(registry: object) -> list:
    """Les bases SQLite locales que les connecteurs déclarent lire."""
    from pathlib import Path

    chemins: list[Path] = []
    for key in registry.keys():  # type: ignore[attr-defined]
        try:
            instance = registry.get(key)()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - un connecteur qui ne s'instancie pas
            continue
        for attribut in ("_db_path", "_healthkit_db_path"):
            chemin = getattr(instance, attribut, None)
            if isinstance(chemin, Path):
                chemins.append(chemin)
    return chemins


def _disconnect_source(registry: object, source: str) -> None:
    """Find and disconnect a registered source connector."""
    console = Console()

    if not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        return

    connector_cls = registry.get(source)  # type: ignore[attr-defined]
    try:
        instance = connector_cls()
        instance.disconnect()
        console.print(f"[green]Disconnected {source}.[/green]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to disconnect {source}: {exc}[/red]")


def _connect_source(registry: object, source: str, path: str = "") -> None:
    """Route connector setup by auth_type."""
    console = Console()

    if not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        console.print(
            "[yellow]Available sources: "
            + ", ".join(registry.keys())  # type: ignore[attr-defined]
            + "[/yellow]"
        )
        return

    connector_cls = registry.get(source)  # type: ignore[attr-defined]
    auth_type = getattr(connector_cls, "auth_type", "")

    if auth_type == "filesystem":
        # Filesystem connectors (e.g. Obsidian) need a path
        if not path:
            console.print(
                f"[red]{source} requires a --path argument (e.g. --path ~/vault).[/red]"
            )
            return
        try:
            instance = connector_cls(vault_path=path)
        except TypeError:
            try:
                instance = connector_cls(path)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Failed to create {source} connector: {exc}[/red]")
                return

        if instance.is_connected():
            console.print(f"[green]{source} connected at path: {path}[/green]")
        else:
            console.print(
                f"[red]{source}: path '{path}' does not exist or is not accessible."
                "[/red]"
            )

    elif auth_type == "oauth":
        # OAuth connectors — auto-open browser + catch callback
        from diapason.connectors.oauth import (
            get_client_credentials,
            get_provider_for_connector,
            run_connector_oauth,
            save_client_credentials,
        )

        try:
            instance = connector_cls()
            if instance.is_connected():
                console.print(f"[green]{source} is already connected.[/green]")
                return

            # Le fichier peut porter un verdict de Google : le dire ici, à
            # l'endroit même où l'on va redemander un consentement.
            from diapason.connectors.google_auth import revocation_of

            revoque = revocation_of(str(getattr(instance, "_credentials_path", "")))
            if revoque:
                quand, pourquoi = revoque
                console.print(
                    f"[yellow]Google revoked this access on {quand} ({pourquoi}). "
                    "Starting a new OAuth flow.[/yellow]"
                )

            provider = get_provider_for_connector(source)
            if provider is None:
                console.print(f"[red]No OAuth provider configured for {source}.[/red]")
                return

            creds = get_client_credentials(provider)
            client_id = creds[0] if creds else ""
            client_secret = creds[1] if creds else ""

            if not client_id or not client_secret:
                console.print(f"[cyan]First-time setup for {source}.[/cyan]")
                console.print(
                    f"[yellow]Create an OAuth app at: {provider.setup_url}[/yellow]"
                )
                console.print(f"[dim]{provider.setup_hint}[/dim]")
                # Un prompt nu a déjà fait inscrire un nom d'utilisateur
                # macOS comme client OAuth — Google répondait
                # « invalid_client » sans autre indice. Dire d'où viennent
                # ces valeurs coûte quatre lignes.
                click.echo(
                    "\nCes identifiants viennent de Google Cloud Console\n"
                    "(console.cloud.google.com → APIs & Services →\n"
                    "Credentials → Create credentials → OAuth client ID →\n"
                    "type « Desktop app »). Le Client ID se termine par\n"
                    "« .apps.googleusercontent.com »."
                )
                client_id = click.prompt("Client ID")
                if ".apps.googleusercontent.com" not in client_id:
                    click.echo(
                        "⚠ Ce Client ID ne ressemble pas à un client Google "
                        "(attendu : …apps.googleusercontent.com). Google le "
                        "refusera probablement avec « invalid_client »."
                    )
                client_secret = click.prompt("Client Secret")
                save_client_credentials(provider, client_id, client_secret)

            run_connector_oauth(source, client_id, client_secret)
            console.print(f"[green]{source} authorised successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]OAuth flow failed for {source}: {exc}[/red]")

    elif auth_type == "token":
        # Token-based connectors (e.g. Oura) — prompt for personal access token
        import json
        from pathlib import Path

        from diapason.connectors.oauth import save_tokens
        from diapason.core.config import DEFAULT_CONFIG_DIR

        try:
            instance = connector_cls()
            if instance.is_connected():
                console.print(f"[green]{source} is already connected.[/green]")
                return

            token = click.prompt(f"Enter your {source} personal access token")
            token_dir = Path(DEFAULT_CONFIG_DIR) / "connectors"
            token_dir.mkdir(parents=True, exist_ok=True)
            token_file = token_dir / f"{source}.json"
            token_file.write_text(json.dumps({"token": token}))
            save_tokens(source, {"token": token})
            console.print(f"[green]{source} connected successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Token setup failed for {source}: {exc}[/red]")

    else:
        # Generic / bridge connectors
        try:
            instance = connector_cls()
            connected = instance.is_connected()
            status = "connected" if connected else "disconnected"
            console.print(f"{source} status: {status}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Failed to connect {source}: {exc}[/red]")


@click.group(invoke_without_command=True)
@click.argument("source", required=False)
@click.option(
    "--list",
    "list_sources",
    is_flag=True,
    help="List connected sources and sync status.",
)
@click.option(
    "--sync",
    "trigger_sync",
    is_flag=True,
    help="Trigger incremental sync for all sources.",
)
@click.option(
    "--disconnect",
    "disconnect_source",
    default="",
    help="Disconnect a source.",
)
@click.option(
    "--path",
    default="",
    help="Path for filesystem connectors (e.g., Obsidian vault).",
)
@click.pass_context
def connect(
    ctx: click.Context,
    source: str | None,
    list_sources: bool,
    trigger_sync: bool,
    disconnect_source: str,
    path: str,
) -> None:
    """Manage data source connections (Gmail, Obsidian, etc.)."""
    # Lazy imports to avoid top-level side effects
    import diapason.connectors  # noqa: F401 — registers all connectors
    from diapason.core.registry import ConnectorRegistry

    if list_sources:
        _list_sources(ConnectorRegistry)
        return

    if trigger_sync:
        click.echo("Sync not yet implemented in CLI")
        return

    if disconnect_source:
        _disconnect_source(ConnectorRegistry, disconnect_source)
        return

    if source:
        _connect_source(ConnectorRegistry, source, path=path)
        return

    # No arguments — show help
    click.echo(ctx.get_help())
