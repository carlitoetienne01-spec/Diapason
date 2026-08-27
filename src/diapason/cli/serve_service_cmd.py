"""CLI: diapason serve-service — keep the API server running at login.

The desktop app talks to the Python backend on 127.0.0.1:8000. Without this,
the app shows "Backend unreachable" until someone remembers to run
`diapason serve` in a terminal — and loses it again when that terminal closes.

Unlike the dictation agent, this one needs no TCC permissions: it opens a
loopback socket and touches neither the keyboard nor the microphone. So it
installs and works in one step.
"""

from __future__ import annotations

import sys

import click

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


@click.group("serve-service")
def serve_service() -> None:
    """Manage the background API server (macOS LaunchAgent)."""


def _require_macos() -> None:
    if sys.platform != "darwin":
        click.echo("The serve service is macOS-only.", err=True)
        sys.exit(1)


def _label():
    from diapason.desktop import launch_agent

    return launch_agent.SERVE_LABEL


@serve_service.command("install")
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int)
@click.option(
    "--maillage-reseau",
    is_flag=True,
    help="Ouvrir un SECOND socket pour que vos autres appareils atteignent "
    "ce Mac. Dix routes du maillage y sont exposées, créance d'appareil "
    "exigée ; le chat, la voix et Succès restent sur la loopback.",
)
@click.option(
    "--lan-port",
    default=8001,
    show_default=True,
    type=int,
    help="Port du second socket, celui du maillage.",
)
@click.option("--allow-network", is_flag=True, hidden=True)
def install(
    host: str,
    port: int,
    maillage_reseau: bool,
    lan_port: int,
    allow_network: bool,
) -> None:
    """Run the API server at login, in the background."""
    _require_macos()
    from diapason.desktop import launch_agent

    if allow_network:
        # Cette option mettait les DEUX CENT DIX routes sur le réseau. Elle
        # existait pour un besoin légitime — « un téléphone ne peut pas
        # joindre 127.0.0.1 » — auquel il n'y avait alors pas d'autre
        # réponse. Il y en a une depuis : un second socket qui ne porte que
        # dix routes. Le besoin étant servi, l'échappatoire se referme.
        #
        # Elle échoue au lieu d'être un alias silencieux : la même commande
        # ne doit pas se mettre à faire autre chose sans le dire.
        click.echo(
            "--allow-network n'existe plus : elle exposait l'API ENTIÈRE au "
            "réseau, et c'est ainsi que ce Mac a servi deux cent dix routes "
            "sur le Wi-Fi jusqu'au 26 août 2026.\n"
            "  • Pour que vos autres appareils atteignent ce Mac : "
            "--maillage-reseau, qui n'expose que les dix routes du "
            "maillage, créance d'appareil exigée.\n"
            "  • L'application complète reste sur 127.0.0.1, toujours.",
            err=True,
        )
        sys.exit(1)

    if host not in ("127.0.0.1", "localhost", "::1"):
        # Plus d'échappatoire. Le seul motif qu'on lui connaissait a
        # désormais sa propre porte, plus étroite et mieux gardée.
        click.echo(
            f"Refusing to bind {host!r} from a background service: it would "
            "expose the API beyond this machine.\n"
            "  • Pour un usage local : gardez 127.0.0.1.\n"
            "  • Pour que vos autres appareils atteignent ce Mac : gardez "
            "127.0.0.1 ET ajoutez --maillage-reseau.",
            err=True,
        )
        sys.exit(1)

    if maillage_reseau and lan_port == port:
        click.echo(
            f"--lan-port et --port valent tous deux {port} : deux serveurs "
            "sur le même port se lient en silence sur macOS et échouent sur "
            "Linux.",
            err=True,
        )
        sys.exit(1)

    if maillage_reseau:
        click.echo(
            f"⚠ Le maillage écoutera sur 0.0.0.0:{lan_port} : toute machine "
            "de votre réseau local pourra l'atteindre. Dix routes, "
            "créance d'appareil exigée — mais un réseau partagé reste un "
            "réseau partagé.",
            err=True,
        )

    # Installer, c'est LANCER : le plist porte RunAtLoad. Poser un service sur
    # un port déjà servi crée exactement le doublon silencieux que le reste de
    # ce chantier traque — les deux se disputent le port, le plus spécifique
    # gagne le routage, l'autre devient un zombie muet, et rien ne le dit.
    #
    # Réinstaller par-dessus SON PROPRE service reste permis : launchd remplace
    # un job de même étiquette, il n'en empile pas un second.
    from diapason.core import ports

    etat, detail = ports.port_state(port)
    if etat == ports.OCCUPE:
        notre_pid = launch_agent.job_pid(launch_agent.SERVE_LABEL)
        a_nous = notre_pid is not None and f"PID {notre_pid} " in f"{detail} "
        if not a_nous:
            click.echo(
                f"Port {port} is already served by: {detail}\n"
                "Installing would start a second server on the same port, and "
                "neither would report an error.\n"
                "Stop that one first, or install on another port with --port.",
                err=True,
            )
            sys.exit(1)
        click.echo(f"↻ Remplacement du service existant (PID {notre_pid}).", err=True)
    elif etat == ports.INCONNU:
        # Ici on avertit sans refuser : contrairement à `diapason start`, qui
        # est répété au quotidien, une installation est un geste délibéré et
        # rare. La bloquer parce que lsof manque empêcherait toute mise en
        # place sur un système minimal.
        click.echo(
            f"⚠ Impossible de vérifier si le port {port} est libre ({detail}).\n"
            f"  Vérifiez à la main :  lsof -nP -iTCP:{port} -sTCP:LISTEN",
            err=True,
        )

    path = launch_agent.install(
        label=launch_agent.SERVE_LABEL,
        log_prefix="serve",
        args=[
            sys.executable,
            "-m",
            "diapason.cli",
            "serve",
            "--host",
            host,
            "--port",
            str(port),
        ]
        + (
            ["--lan-host", "0.0.0.0", "--lan-port", str(lan_port)]
            if maillage_reseau
            else []
        ),
    )
    click.echo(f"Installed LaunchAgent → {path}")
    if launch_agent.is_loaded(launch_agent.SERVE_LABEL):
        click.echo(f"API server running at http://{host}:{port} — and at every login.")
    else:
        click.echo(
            "WARNING: launchd did not accept the job. Check "
            "`diapason serve-service logs`.",
            err=True,
        )


@serve_service.command("uninstall")
def uninstall() -> None:
    """Stop the API server and remove it from login."""
    _require_macos()
    from diapason.desktop import launch_agent

    existed = launch_agent.uninstall(launch_agent.SERVE_LABEL)
    click.echo(
        "Removed the API server LaunchAgent." if existed else "Nothing installed."
    )


@serve_service.command("status")
def status() -> None:
    """Show whether the API server agent is loaded and answering."""
    _require_macos()
    from diapason.desktop import launch_agent

    loaded = launch_agent.is_loaded(launch_agent.SERVE_LABEL)
    click.echo(f"LaunchAgent: {'loaded' if loaded else 'not loaded'}")
    click.echo(f"Plist: {launch_agent.plist_path(launch_agent.SERVE_LABEL)}")

    # Loaded is not the same as answering — say which.
    reachable = False
    try:
        import urllib.request

        with urllib.request.urlopen(
            f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/health", timeout=3
        ) as r:
            reachable = r.status == 200
    except Exception:  # noqa: BLE001
        reachable = False
    click.echo(f"Health: {'answering' if reachable else 'not answering'}")
    click.echo(f"Logs: {launch_agent.log_dir()}/serve.out.log (and .err.log)")


@serve_service.command("restart")
def restart() -> None:
    """Restart the API server."""
    _require_macos()
    from diapason.desktop import launch_agent

    launch_agent.kickstart(launch_agent.SERVE_LABEL)
    click.echo("Restarted.")


@serve_service.command("logs")
@click.option("--lines", default=40, show_default=True)
def logs(lines: int) -> None:
    """Print the tail of the API server logs."""
    _require_macos()
    from diapason.desktop import launch_agent

    ld = launch_agent.log_dir()
    for name in ("serve.out.log", "serve.err.log"):
        p = ld / name
        click.echo(f"\n=== {p} ===")
        if not p.exists():
            click.echo("(no log yet)")
            continue
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in content[-lines:]:
            click.echo(line)
