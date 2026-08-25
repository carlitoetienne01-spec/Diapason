"""``diapason mesh`` — rejoindre une flotte, et voir qui en fait partie.

Spatial Mesh, phase 0, 25 août 2026. Le côté HÔTE du jumelage était
complet (créer une invitation depuis la page Appareils), le côté INVITÉ
n'existait nulle part : ni écran « rejoindre », ni commande. Deux
Diapason ne pouvaient donc pas se joindre — et quand bien même, ils se
seraient refusé chaque échange faute d'adopter l'identité de flotte.

Cette commande est le chemin invité qui manquait.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("mesh")
def mesh() -> None:
    """La flotte d'appareils : rejoindre, lister, quitter."""


@mesh.command("join")
@click.argument("host")
@click.argument("token")
@click.option(
    "--address",
    default=None,
    help="L'adresse à laquelle CET appareil est joignable (sinon devinée).",
)
def join(host: str, token: str, address: str | None) -> None:
    """Rejoindre la flotte d'un autre Diapason.

    HOST est son adresse (« 192.168.0.5:8000 »), TOKEN le code d'invitation
    qu'il affiche dans Appareils → Ajouter un appareil.
    """
    from diapason.mesh.join import JoinError, join_fleet

    try:
        resultat = join_fleet(host, token, my_address=address)
    except JoinError as exc:
        console.print(f"[red]Jumelage impossible[/red] — {exc}")
        raise SystemExit(1) from exc

    console.print(f"[green]Rejoint[/green] la flotte de « {resultat.host_name} ».")
    console.print(f"  identité de flotte : {resultat.owner_id}")
    console.print(f"  hôte               : {resultat.host_device_id}")
    if resultat.host_address:
        console.print(f"  adresse            : {resultat.host_address}")
    if resultat.granted_capabilities:
        console.print(
            "  accordé            : "
            + ", ".join(sorted(resultat.granted_capabilities))
        )
    else:
        # Ne pas laisser croire à une permission qu'on n'a pas reçue.
        console.print("  accordé            : rien pour l'instant")


@mesh.command("devices")
@click.option("--all", "tout", is_flag=True, help="Inclure les appareils révoqués.")
def devices(tout: bool) -> None:
    """Lister les appareils de la flotte, avec leur présence."""
    from diapason.mesh.presence import presence_of
    from diapason.mesh.registry import DeviceRegistry

    liste = DeviceRegistry().list_devices(include_revoked=tout)
    if not liste:
        console.print(
            "Aucun appareil. Sur l'autre machine : Appareils → Ajouter un "
            "appareil, puis ici : [bold]diapason mesh join <adresse> <code>[/bold]"
        )
        return
    table = Table(title=f"Flotte — {len(liste)} appareil(s)")
    for colonne in ("Nom", "Plateforme", "Confiance", "Présence", "Identifiant"):
        table.add_column(colonne)
    for d in liste:
        table.add_row(
            str(d.get("name") or "?"),
            str(d.get("platform") or "?"),
            str(d.get("trustLevel") or "?"),
            str((presence_of(d) or {}).get("state") or "?"),
            str(d.get("deviceId") or "?"),
        )
    console.print(table)


@mesh.command("whoami")
def whoami() -> None:
    """L'identité de CET appareil dans la flotte."""
    from diapason.mesh.identity import public_identity

    moi = public_identity()
    console.print(f"appareil : {moi['deviceId']}  ({moi['name']})")
    console.print(f"plateforme : {moi['platform']}")
    console.print(f"flotte   : {moi['ownerId']}")
    # La clé publique est publiable ; la privée n'apparaît nulle part.
    console.print(f"clé publique : {moi['publicKey']}")


__all__ = ["mesh"]
