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
            "  accordé            : " + ", ".join(sorted(resultat.granted_capabilities))
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
    from diapason.mesh.scellement import etat_de_chiffrement

    registre = DeviceRegistry()
    liste = registre.list_devices(include_revoked=tout)
    if not liste:
        console.print(
            "Aucun appareil. Sur l'autre machine : Appareils → Ajouter un "
            "appareil, puis ici : [bold]diapason mesh join <adresse> <code>[/bold]"
        )
        return
    table = Table(title=f"Flotte — {len(liste)} appareil(s)")
    for colonne in (
        "Nom",
        "Plateforme",
        "Confiance",
        "Présence",
        "Commandes",
        "Identifiant",
    ):
        table.add_column(colonne)
    # Un mot par état, et jamais un mot pour deux. La première version
    # rangeait sous « EN CLAIR » trois situations opposées, puis imprimait une
    # cause et une conséquence vraies dans une seule — envoyant chercher la
    # panne sur la machine d'en face quand elle était dans le config.toml
    # local, ou décrivant comme exposé un pair auquel plus rien n'est envoyé.
    _couleurs = {
        "SCELLE": "green",
        "CLAIR": "yellow",
        "DESACTIVE": "dim",
        "BLOQUE": "red",
        "INCONNU": "dim",
    }
    _mots = {
        "SCELLE": "chiffrées",
        "CLAIR": "EN CLAIR",
        "DESACTIVE": "désactivé",
        "BLOQUE": "BLOQUÉ",
        "INCONNU": "?",
    }
    for d in liste:
        etat = etat_de_chiffrement(d, registry=registre)
        table.add_row(
            str(d.get("name") or "?"),
            str(d.get("platform") or "?"),
            str(d.get("trustLevel") or "?"),
            str((presence_of(d) or {}).get("state") or "?"),
            f"[{_couleurs.get(etat, 'dim')}]{_mots.get(etat, etat)}[/]",
            str(d.get("deviceId") or "?"),
        )
    console.print(table)
    # Une note par état PRÉSENT, et chacune dit la vérité de CET état.
    etats = {etat_de_chiffrement(d, registry=registre) for d in liste}
    notes = {
        "CLAIR": (
            "« EN CLAIR » : cet appareil ne publie pas de clé de scellement — "
            "un téléphone, ou un Diapason antérieur au 26 août 2026. Le verbe "
            "et les arguments de ses commandes sont lisibles par qui écoute."
        ),
        "DESACTIVE": (
            "« désactivé » : [mesh] chiffrement = « jamais » dans votre "
            "config.toml. Ces appareils publient peut-être une clé ; c'est "
            "cette machine-ci qui refuse de s'en servir."
        ),
        "BLOQUE": (
            "« BLOQUÉ » : [mesh] chiffrement = « exige » et cet appareil ne "
            "publie pas de clé. Rien ne lui est envoyé du tout — ses "
            "commandes ne sont pas « en clair », elles n'existent pas."
        ),
        "INCONNU": (
            "« ? » : l'état n'a pas pu être déterminé. Voir "
            "~/.diapason/logs/serve.err.log."
        ),
    }
    for etat in ("CLAIR", "DESACTIVE", "BLOQUE", "INCONNU"):
        if etat in etats:
            console.print(f"[dim]{notes[etat]}[/dim]")


@mesh.command("renouveler-cle")
def renouveler_cle() -> None:
    """Frapper une clé de scellement neuve, en gardant la précédente.

    Geste EXPLICITE, jamais automatique. Une rotation périodique n'achèterait
    rien qu'une clé statique n'ait déjà perdu, et créerait une panne
    différée : un identifiant de clé périmé refusé des heures après coup.

    L'ancienne reste déchiffrable sept jours — plus longtemps que les six
    heures qu'une commande peut attendre en file, sans quoi une commande
    deviendrait indéchiffrable pendant qu'elle patiente.
    """
    from diapason.mesh.scellement import kid, paire_locale, renouveler

    avant = kid(paire_locale().publique)
    renouveler()
    apres = kid(paire_locale().publique)
    console.print(
        f"Clé de scellement renouvelée : [dim]{avant}[/dim] → [bold]{apres}[/bold]"
    )
    console.print(
        "[dim]Vos pairs l'apprendront à leur prochaine annonce, sous quinze "
        "secondes. L'ancienne reste déchiffrable sept jours.[/dim]"
    )


@mesh.command("oublier-cle")
@click.argument("appareil")
def oublier_cle(appareil: str) -> None:
    """Oublier la clé de scellement d'un APPAREIL, et lui reparler en clair.

    Le repli normal prend sept jours — c'est délibéré : sur un corps de
    réponse, un attaquant éteindrait le chiffrement d'un paquet forgé. Ceci
    est la sortie de secours quand on SAIT déjà que le pair ne peut plus
    ouvrir ce qu'on lui scelle : réinstallation, retour en arrière.
    """
    from diapason.mesh.identity import device_identity
    from diapason.mesh.registry import DeviceRegistry
    from diapason.mesh.resolver import resolve_device

    registre = DeviceRegistry()
    flotte = [d for d in registre.list_devices() if d.get("trustLevel") == "TRUSTED"]
    issue = resolve_device(
        appareil, flotte, local_device_id=device_identity().device_id
    )
    cible = issue.get("device")
    if issue.get("status") != "RESOLVED" or cible is None:
        console.print(str(issue.get("message") or f"« {appareil} » ?"))
        raise SystemExit(1)

    registre.forget_seal_key(str(cible.get("deviceId")))
    console.print(
        f"Clé de scellement de [bold]{cible.get('name')}[/bold] oubliée — "
        "ses commandes repartent en clair jusqu'à sa prochaine publication."
    )


@mesh.command("send")
@click.argument("fichier", type=click.Path(exists=True, dir_okay=False))
@click.argument("appareil")
def send(fichier: str, appareil: str) -> None:
    """Envoyer un FICHIER vers un APPAREIL de la flotte.

    APPAREIL se donne par son nom (« PC du bureau ») ou par son genre
    (« mon téléphone »). PAS par son identifiant : le résolveur compare des
    noms, des types d'appareil et des plateformes, et rend « inconnu » sur un
    identifiant — que `mesh devices` affiche pourtant, ce qui invite à le
    copier. La docstring promettait l'inverse jusqu'au 26 août 2026, donc
    `--help` promettait l'inverse.

    La résolution est celle du maillage : une phrase qui désigne deux
    appareils est refusée, jamais tranchée au hasard.

    Cette commande est le premier appelant de ``envoyer_fichier`` : le cœur
    du transfert existait depuis le 25 août 2026, chiffré et testé par un
    banc à deux processus, mais aucun chemin de production ne l'atteignait.
    Un moteur qu'on ne peut pas démarrer n'est pas un moteur.
    """
    from pathlib import Path

    from diapason.mesh.envoi_fichier import EnvoiRefuse, envoyer_fichier
    from diapason.mesh.identity import device_identity
    from diapason.mesh.registry import DeviceRegistry
    from diapason.mesh.resolver import resolve_device

    registre = DeviceRegistry()
    flotte = [d for d in registre.list_devices() if d.get("trustLevel") == "TRUSTED"]
    if not flotte:
        console.print(
            "Aucun appareil appairé. Sur l'autre machine : Appareils → "
            "Ajouter un appareil, puis ici : "
            "[bold]diapason mesh join <adresse> <code>[/bold]"
        )
        raise SystemExit(1)

    issue = resolve_device(
        appareil, flotte, local_device_id=device_identity().device_id
    )
    cible = issue.get("device")
    if issue.get("status") != "RESOLVED" or cible is None:
        # §34 : on demande, on ne devine jamais. Le résolveur rend déjà une
        # phrase prête à dire — la répéter vaut mieux que la reformuler, et
        # elle distingue « aucun appareil », « lequel ? » et « c'est ici ».
        console.print(str(issue.get("message") or f"« {appareil} » ?"))
        raise SystemExit(1)

    taille = Path(fichier).stat().st_size
    console.print(
        f"Envoi de [bold]{Path(fichier).name}[/bold] "
        f"({_lisible(taille)}) vers [bold]{cible.get('name')}[/bold]…"
    )

    def _avance(faits: int, total: int) -> None:
        console.print(f"  {faits}/{total} morceaux", end="\r")

    def _attendre(message: str) -> None:
        console.print(f"[yellow]{message}[/yellow]")

    try:
        envoi = envoyer_fichier(
            fichier,
            cible,
            progression=_avance,
            attente=_attendre,
        )
    except EnvoiRefuse as exc:
        # Le refus vient du destinataire ou du transport : il sait pourquoi,
        # nous non. Le relayer tel quel vaut mieux que l'habiller.
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    # Les statuts que le RÉCEPTEUR produit, et eux seuls. « RECU » a vécu ici
    # une heure, inventé de toutes pièces : il n'existait nulle part dans le
    # code, et un transfert parfaitement réussi s'affichait donc en jaune. Le
    # test ne l'a pas vu parce que son double rendait « RECU » — le double
    # était plus commode que ce qu'il doublait.
    #
    # ALREADY_PRESENT est un succès, pas une réserve : la déduplication par
    # contenu a constaté que le fichier était déjà là, entier et vérifié.
    couleur = "green" if envoi.statut in _ABOUTIS else "red"
    console.print(f"[{couleur}]{envoi.message}[/{couleur}]")
    if envoi.chemin_distant:
        console.print(f"  chez {cible.get('name')} : {envoi.chemin_distant}")
    if envoi.statut not in _ABOUTIS:
        raise SystemExit(1)


# Ce que le récepteur rend quand le fichier est chez lui, entier et vérifié.
# Vérifié contre mesh/files_routes.py, pas supposé.
_ABOUTIS = frozenset({"COMPLETE", "ALREADY_PRESENT"})


def _lisible(octets: int) -> str:
    """Une taille qu'un humain lit sans compter les zéros."""
    for unite, seuil in (("Go", 1 << 30), ("Mo", 1 << 20), ("Ko", 1 << 10)):
        if octets >= seuil:
            return f"{octets / seuil:.1f} {unite}"
    return f"{octets} o"


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
