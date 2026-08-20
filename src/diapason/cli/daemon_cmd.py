"""``diapason start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import click
from rich.console import Console

from diapason.core.config import DEFAULT_CONFIG_DIR, load_config

_PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
_LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"


def _is_diapason_server(pid: int) -> bool:
    """Ce PID porte-t-il VRAIMENT un serveur Diapason ?

    ``os.kill(pid, 0)`` prouve seulement qu'un processus existe. Les numéros de
    processus sont recyclés — après un redémarrage, ou simplement quand le
    système reboucle — et ce PID appartient alors à n'importe quoi. Or
    ``diapason stop`` lui envoyait SIGTERM, puis SIGKILL. On lit donc sa ligne
    de commande avant de conclure quoi que ce soit.

    Sans preuve, la réponse est NON : refuser de tuer coûte un message, tuer le
    mauvais processus coûte le travail de quelqu'un.
    """
    if sys.platform == "win32":
        # Pas de ``ps`` ici, et psutil n'est pas une dépendance du projet. On
        # retombe sur la seule question qu'on sache poser, en le sachant.
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            # LC_ALL=C : on ne compare jamais de la prose traduite.
            env={"LC_ALL": "C", "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return _looks_like_serve_argv(result.stdout)


def _looks_like_serve_argv(ligne: str) -> bool:
    """La ligne de commande décrit-elle un ``diapason serve`` ?

    Chercher « diapason » et « serve » n'importe où dans la ligne ne prouve
    rien : un shell, un éditeur ou un ``pgrep`` qui mentionnent ces mots la
    satisfont — mesuré, mon propre script de test passait pour un serveur. On
    analyse donc les arguments, ancrés sur l'exécutable :

    - argv[0] doit être un interpréteur Python ou le binaire ``diapason`` ;
    - ``serve`` doit être un ARGUMENT à lui seul, pas une sous-chaîne ;
    - pour Python, un argument doit désigner le module diapason.
    """
    tokens = (ligne or "").strip().split()
    if len(tokens) < 2:
        return False
    exe = os.path.basename(tokens[0]).lower()
    reste = [t.lower() for t in tokens[1:]]
    if "serve" not in reste:
        return False
    if exe.startswith("diapason"):
        return True
    if exe.startswith("python"):
        return any("diapason" in t for t in reste)
    return False


def _read_pid() -> int | None:
    """Le PID du serveur que NOUS avons démarré, s'il tourne encore."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        _PID_FILE.unlink(missing_ok=True)
        return None
    if not _is_diapason_server(pid):
        # Fichier périmé, ou PID recyclé par un programme sans rapport.
        _PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _port_holder(port: int) -> str | None:
    """Ce qui SERT sur ce port, quelle qu'en soit la provenance.

    Le fichier PID ne voit QUE les serveurs lancés par ``diapason start``. Un
    serveur de launchd, de l'application de bureau ou d'un terminal n'y figure
    jamais, et le garde en démarrait tranquillement un second. Le port, lui, ne
    ment pas — à condition de lui poser la bonne question.

    MESURÉ sur cette machine le 20 août 2026, et les deux mesures ensemble
    dictent la forme exacte du test :

    * ``SO_REUSEADDR`` est INDISPENSABLE. Sans lui, un port qu'on vient de
      libérer reste en ``TIME_WAIT`` et paraît occupé : ``diapason restart``
      refusait alors de redémarrer le serveur qu'il venait d'arrêter. Un garde
      qui empêche le service de tourner est pire que le doublon qu'il prévient.
    * Il faut tester les DEUX adresses. Avec ``SO_REUSEADDR``, une liaison sur
      ``0.0.0.0`` réussit pendant qu'un auditeur détient ``127.0.0.1`` — et
      réciproquement. Mais la liaison sur SA PROPRE adresse reste refusée :
      tester les deux couvre donc les deux détenteurs possibles.

    Limite assumée : un auditeur lié à une adresse tierce (``192.168.0.10``) ou
    en IPv6 pur échappe encore aux deux liaisons.
    """
    import errno
    import socket

    # (famille, adresse) : les quatre formes qu'un serveur peut prendre ici.
    # L'IPv6 y figure parce qu'un détenteur lié à « ::1 » en mode v6only est
    # invisible aux liaisons IPv4 — mesuré. Une pile double sur « :: » est en
    # revanche vue par la sonde IPv4, l'espace d'adressage étant partagé.
    formes = (
        (socket.AF_INET, "0.0.0.0"),
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET6, "::"),
        (socket.AF_INET6, "::1"),
    )
    occupe_par = None
    for famille, adresse in formes:
        try:
            sonde = socket.socket(famille, socket.SOCK_STREAM)
        except OSError:
            continue  # famille absente de cette machine : rien à en conclure
        sonde.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if famille == socket.AF_INET6:
            # Sans cela, la sonde « :: » réserverait aussi l'IPv4 et se
            # bloquerait elle-même sur la forme suivante.
            try:
                sonde.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            except OSError:
                pass
        try:
            sonde.bind((adresse, port))
        except OSError as erreur:
            # SEULE « adresse déjà utilisée » prouve une occupation. Une pile
            # IPv6 absente, une politique de bac à sable ou un pare-feu ne
            # prouvent rien — et refuser le démarrage là-dessus transformerait
            # un contrôle en panne.
            if erreur.errno == errno.EADDRINUSE:
                occupe_par = adresse
        finally:
            sonde.close()
        if occupe_par:
            break
    if occupe_par is None:
        return None

    # Occupé. Répond-il comme un Diapason, ou est-il muet ?
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(  # noqa: S310 - loopback, littéral
            f"http://127.0.0.1:{port}/health", timeout=3
        ) as reponse:
            if 200 <= reponse.status < 300:
                return "answering /health"
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return "held, but not answering /health"


def _write_pid(pid: int) -> None:
    """Write PID to pid file."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


# Trois issues distinctes après un lancement, qu'il ne faut pas confondre :
# le serveur répond, il est mort, ou il vit sans avoir encore répondu. La
# dernière n'est PAS un échec avéré — un premier démarrage charge un modèle —
# et surtout elle ne doit pas faire effacer le fichier PID, sous peine de
# laisser un processus vivant que plus rien ne sait arrêter.
SERVING = "serving"
DEAD = "dead"
SILENT = "silent"


def _wait_until_serving(
    proc: subprocess.Popen, port: int, *, timeout_s: float = 60.0
) -> str:
    """Le processus lancé répond-il vraiment sur ce port ?

    L'ancienne version annonçait « started » sans rien vérifier : un serveur
    qui perdait la course au port restait vivant, lié à une adresse que
    personne n'interroge, et l'utilisateur le croyait en service.
    """
    import urllib.error
    import urllib.request

    fin = time.time() + timeout_s
    while time.time() < fin:
        if proc.poll() is not None:
            return DEAD
        try:
            with urllib.request.urlopen(  # noqa: S310 - loopback, littéral
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as reponse:
                if 200 <= reponse.status < 300:
                    return SERVING
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    return SILENT


@click.group()
def daemon() -> None:
    """Manage the Diapason server daemon."""


@daemon.command()
@click.option("--host", default=None, help="Bind address.")
@click.option("--port", default=None, type=int, help="Port number.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
def start(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the Diapason server as a background daemon."""
    console = Console(stderr=True)

    existing = _read_pid()
    if existing is not None:
        console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
        console.print("Use 'diapason stop' to stop it first, or 'diapason restart'.")
        sys.exit(1)

    config = load_config()
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Le fichier PID ne connaît que nos propres démarrages. Le port, lui, voit
    # aussi ceux de launchd, de l'application de bureau et des terminaux — d'où
    # les deux serveurs qui ont coexisté le 20 août 2026 sans que rien ne le
    # signale.
    holder = _port_holder(bind_port)
    if holder is not None:
        console.print(
            f"[yellow]Port {bind_port} is already in use ({holder}).[/yellow]"
        )
        console.print(
            "Something is already serving there — launchd, the desktop app, or "
            "another terminal. Starting a second server would not report an "
            "error: it would quietly lose the race for the port."
        )
        console.print(f"  To identify it:  lsof -nP -iTCP:{bind_port} -sTCP:LISTEN")
        sys.exit(1)

    # Build command to run diapason serve
    cmd = [sys.executable, "-m", "diapason.cli", "serve"]
    if host:
        cmd.extend(["--host", host])
    if port:
        cmd.extend(["--port", str(port)])
    if engine_key:
        cmd.extend(["--engine", engine_key])
    if model_name:
        cmd.extend(["--model", model_name])
    if agent_name:
        cmd.extend(["--agent", agent_name])

    # Start as background process, fully detached from the launching terminal.
    #
    # ``start_new_session`` is POSIX-only: CPython's Windows ``_execute_child``
    # names the parameter ``unused_start_new_session`` and ignores it. Relying
    # on it there leaves the server sharing its parent's console, so closing
    # that console — or logging off — delivers CTRL_CLOSE_EVENT and kills the
    # daemon. DETACHED_PROCESS gives it no console at all; the new process
    # group additionally stops a Ctrl-C in the parent reaching it.
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = open(_LOG_FILE, "a")  # noqa: SIM115
    spawn_kwargs: dict = {}
    if sys.platform == "win32":
        spawn_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        spawn_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=log_fh,
        **spawn_kwargs,
    )
    _write_pid(proc.pid)

    # Vérifier plutôt qu'annoncer. Un serveur qui n'obtient pas le port ne dit
    # rien : il reste vivant, lié à une adresse que personne n'interroge, et
    # « started » s'affichait quand même. On attend qu'il RÉPONDE.
    issue = _wait_until_serving(proc, bind_port)
    if issue == DEAD:
        # Mort avant de servir : rien à arrêter, le fichier PID n'a plus d'objet.
        _PID_FILE.unlink(missing_ok=True)
        console.print(
            f"[red]The server exited before serving port {bind_port}.[/red]\n"
            f"  Log: {_LOG_FILE}"
        )
        sys.exit(1)
    if issue == SILENT:
        # Vivant mais muet. On GARDE le fichier PID : l'effacer laisserait un
        # processus que `diapason stop` ne saurait plus trouver.
        console.print(
            f"[yellow]Started (PID {proc.pid}) but no answer on port "
            f"{bind_port} yet.[/yellow]\n"
            "  A first boot can take a while to load its model. If it never "
            "answers, it may have lost the race for the port.\n"
            f"  Log:  {_LOG_FILE}\n"
            "  Stop: diapason stop"
        )
        sys.exit(1)

    console.print(
        f"[green]Diapason server started[/green] (PID {proc.pid})\n"
        f"  URL: http://{bind_host}:{bind_port}\n"
        f"  Log: {_LOG_FILE}"
    )


@daemon.command()
def stop() -> None:
    """Stop the running Diapason server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        sys.exit(1)

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 10 seconds for graceful shutdown
        for _ in range(20):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            # Force kill if still running
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    except OSError:
        pass

    _PID_FILE.unlink(missing_ok=True)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the Diapason server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        ctx.invoke(stop)
    ctx.invoke(start)


@daemon.command()
def status() -> None:
    """Show status of the Diapason server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]Server is not running.[/yellow]")
        return

    # Get process info
    uptime_info = ""
    try:
        import psutil

        proc = psutil.Process(pid)
        uptime = time.time() - proc.create_time()
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_info = f"\n  Uptime: {hours}h {minutes}m {seconds}s"
    except (ImportError, Exception):
        pass

    config = load_config()
    console.print(
        f"[green]Server is running[/green] (PID {pid}){uptime_info}\n"
        f"  URL: http://{config.server.host}:{config.server.port}\n"
        f"  Log: {_LOG_FILE}"
    )


__all__ = ["daemon", "start", "stop", "restart", "status"]
