"""``diapason start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import contextlib
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


# Le PATH doit contenir /usr/sbin : c'est là que vit ``lsof`` sur macOS, et
# un PATH forcé qui l'oublie ferait silencieusement échouer toute la mécanique.
_PATH_SYS = "/usr/bin:/bin:/usr/sbin:/sbin"


def _run(
    argv: list[str], *, timeout: float = 10.0
) -> subprocess.CompletedProcess | None:
    """Lancer un utilitaire système. None si on n'a PAS PU demander.

    La distinction compte : « je n'ai pas pu demander » n'est pas « la réponse
    est non ». Confondre les deux faisait effacer le fichier PID d'un serveur
    parfaitement vivant, qui devenait alors inarrêtable par la CLI.
    """
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            # LC_ALL=C : on ne compare jamais de la prose traduite.
            env={"LC_ALL": "C", "PATH": os.environ.get("PATH", "") + ":" + _PATH_SYS},
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _listeners_on(port: int) -> list[tuple[int, str]] | None:
    """Qui ÉCOUTE sur ce port, d'après le NOYAU. None = indéterminé.

    Sonder en tentant des liaisons, c'est deviner : quatre adresses littérales
    ne couvriront jamais les N adresses d'une machine. MESURÉ — un serveur lié
    à 192.168.0.121, exactement ce que « serve-service install --allow-network »
    installe pour que le téléphone du maillage atteigne ce Mac, échappait aux
    quatre sondes, et « diapason start » en lançait tranquillement un second.

    ``lsof`` répond pour toutes les adresses à la fois, et donne le PID du
    détenteur — ce dont la confirmation d'après-lancement a besoin.
    """
    if sys.platform == "win32":
        return None  # ni lsof ni équivalent ici : on ne prétend pas savoir
    sortie = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "pn"])
    if sortie is None:
        return None
    if sortie.returncode not in (0, 1):
        return None
    if sortie.returncode == 1 and sortie.stdout.strip():
        return None  # code d'erreur avec du bruit : on ne conclut rien
    trouves: list[tuple[int, str]] = []
    pid: int | None = None
    for ligne in sortie.stdout.splitlines():
        if ligne.startswith("p"):
            try:
                pid = int(ligne[1:])
            except ValueError:
                pid = None
        elif ligne.startswith("n") and pid is not None:
            trouves.append((pid, ligne[1:]))
    return trouves


def _descendants(racine: int) -> set[int]:
    """``racine`` et toute sa descendance, d'après ``ps``.

    Un serveur peut être lancé derrière un lanceur (``uv run``), auquel cas le
    processus qui tient le port n'est pas celui qu'on a lancé, mais son enfant.
    """
    sortie = _run(["ps", "-eo", "pid=,ppid="])
    if sortie is None or sortie.returncode != 0:
        return {racine}
    enfants: dict[int, list[int]] = {}
    for ligne in sortie.stdout.splitlines():
        morceaux = ligne.split()
        if len(morceaux) != 2:
            continue
        try:
            fils, pere = int(morceaux[0]), int(morceaux[1])
        except ValueError:
            continue
        enfants.setdefault(pere, []).append(fils)
    vus = {racine}
    a_voir = [racine]
    while a_voir:
        courant = a_voir.pop()
        for fils in enfants.get(courant, ()):
            if fils not in vus:
                vus.add(fils)
                a_voir.append(fils)
    return vus


def _looks_like_serve_argv(ligne: str) -> bool:
    """La ligne de commande décrit-elle un ``diapason serve`` ?

    Indice secondaire seulement : ``ps`` rend les arguments JOINTS par des
    espaces, sans échappement, donc la frontière entre eux est perdue. MESURÉ —
    un interpréteur sous « /Users/John Smith/… » ou « ~/Library/Mobile
    Documents/… » était rejeté, le fichier PID effacé, et le serveur devenait
    inarrêtable. On accepte donc plusieurs découpages plausibles plutôt qu'un
    seul, et la vraie preuve reste la propriété du port.
    """
    tokens = (ligne or "").strip().split()
    if len(tokens) < 2:
        return False
    if "serve" not in [t.lower() for t in tokens[1:]]:
        return False
    if not any("diapason" in t.lower() for t in tokens):
        return False
    # argv[0] peut avoir été coupé en morceaux par un espace dans le chemin :
    # on cherche l'interpréteur parmi les premiers jetons, pas au seul index 0.
    for jeton in tokens[: min(6, len(tokens))]:
        base = os.path.basename(jeton).lower()
        if base.startswith("python") or base.startswith("diapason") or base == "uv":
            return True
    return False


def _is_diapason_server(pid: int, port: int | None = None) -> bool | None:
    """Ce PID porte-t-il notre serveur ? None quand on ne peut pas trancher.

    ``os.kill(pid, 0)`` ne prouve qu'une existence, et les numéros de processus
    sont recyclés — « diapason stop » désignait ainsi un /bin/sleep comme cible
    de SIGKILL. Sur Windows, pire : ``os.kill(pid, 0)`` ne teste rien, il
    TERMINE le processus. Il n'apparaît donc plus ici.

    La preuve la plus solide est la propriété du port, attestée par le noyau.
    La ligne de commande n'est qu'un repli.
    """
    if port is not None:
        auditeurs = _listeners_on(port)
        if auditeurs is not None:
            if any(p == pid for p, _ in auditeurs):
                return True
            if auditeurs:
                return False  # quelqu'un d'autre tient le port
    sortie = _run(["ps", "-p", str(pid), "-o", "command="])
    if sortie is None:
        return None  # on n'a pas pu demander
    if sortie.returncode != 0:
        return False  # ps a répondu : ce PID n'existe pas
    return _looks_like_serve_argv(sortie.stdout)


def _read_pid(port: int | None = None) -> int | None:
    """Le PID de notre serveur, s'il tourne encore.

    Le fichier n'est effacé que sur une RÉFUTATION, jamais sur une réponse
    indéterminée : effacer sur un doute laissait un serveur vivant que plus
    aucune commande ne savait retrouver.
    """
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        _PID_FILE.unlink(missing_ok=True)
        return None
    verdict = _is_diapason_server(pid, port)
    if verdict is False:
        _PID_FILE.unlink(missing_ok=True)
        return None
    if verdict is None:
        return pid  # dans le doute, on garde la trace plutôt que de la perdre
    return pid


# Trois états d'un port, et « je ne sais pas » en est un.
LIBRE = "libre"
OCCUPE = "occupe"
INCONNU = "inconnu"


def _port_state(port: int) -> tuple[str, str]:
    """État du port et description lisible du détenteur."""
    auditeurs = _listeners_on(port)
    if auditeurs is None:
        return INCONNU, "impossible d'interroger le noyau (lsof indisponible)"
    if not auditeurs:
        return LIBRE, ""
    detail = ", ".join(f"PID {p} sur {adresse}" for p, adresse in auditeurs)
    return OCCUPE, detail


def _http_status(host: str, port: int, *, timeout: float = 3.0) -> int | None:
    """Code HTTP de /health, ou None si rien d'exploitable ne répond.

    Un détenteur qui ne parle pas HTTP levait ``http.client.BadStatusLine``,
    qui n'hérite PAS de OSError : « diapason start » sortait sur une trace.
    """
    import http.client
    import urllib.error
    import urllib.request

    cible = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    if ":" in cible and not cible.startswith("["):
        cible = f"[{cible}]"
    try:
        with urllib.request.urlopen(  # noqa: S310 - hôte local, schéma littéral
            f"http://{cible}:{port}/health", timeout=timeout
        ) as reponse:
            return int(reponse.status)
    except urllib.error.HTTPError as erreur:
        return int(erreur.code)  # 503 « moteur pas prêt » EST une réponse
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return None


def _write_pid(pid: int) -> None:
    """Write PID to pid file."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


# Quatre issues après un lancement. « Le port répond » ne suffit pas : MESURÉ,
# un /bin/sleep passait pour un serveur en marche parce qu'un TIERS répondait
# déjà sur le port. Le fichier PID recevait alors le perdant de la course.
SERVING = "serving"
DEAD = "dead"
SILENT = "silent"
USURPED = "usurped"


def _wait_until_serving(
    proc: subprocess.Popen, host: str, port: int, *, timeout_s: float = 60.0
) -> str:
    """Le processus LANCÉ sert-il vraiment ce port ?

    On exige deux choses ensemble : que le port réponde, et qu'il appartienne
    au processus qu'on a lancé — ou à l'un de ses descendants, un lanceur
    pouvant s'intercaler. L'une sans l'autre ne prouve rien.
    """
    fin = time.time() + timeout_s
    while time.time() < fin:
        if proc.poll() is not None:
            return DEAD
        code = _http_status(host, port, timeout=2.0)
        if code is not None:
            auditeurs = _listeners_on(port)
            if auditeurs is None:
                # Sans l'avis du noyau, on s'en tient au fait vérifiable : le
                # processus est vivant et le port répond.
                return SERVING if proc.poll() is None else DEAD
            famille = _descendants(proc.pid)
            if any(p in famille for p, _ in auditeurs):
                return SERVING if proc.poll() is None else DEAD
            if auditeurs:
                return USURPED
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

    config = load_config()
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Un verrou de démarrage, tenu du contrôle jusqu'à la confirmation.
    #
    # Entre « le port est libre » et « mon enfant l'a pris », il s'écoule des
    # secondes — le seul import du paquet en coûte presque une, et un premier
    # démarrage charge un modèle. Deux `diapason start` lancés dans cet
    # intervalle voyaient tous deux le port libre. Le verrou ne protège QUE
    # cette commande manuelle : launchd n'y passe pas, donc il ne peut pas
    # empêcher un service supervisé de démarrer.
    verrou = None
    if sys.platform != "win32":
        import fcntl

        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            verrou = os.open(
                str(DEFAULT_CONFIG_DIR / "start.lock"), os.O_RDWR | os.O_CREAT, 0o600
            )
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if verrou is not None:
                os.close(verrou)
            console.print(
                "[yellow]Another 'diapason start' is already in progress.[/yellow]\n"
                "  Wait for it to finish, then check with 'diapason status'."
            )
            sys.exit(1)

    try:
        existing = _read_pid(bind_port)
        if existing is not None:
            console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
            console.print(
                "Use 'diapason stop' to stop it first, or 'diapason restart'."
            )
            sys.exit(1)

        # Le fichier PID ne connaît que nos propres démarrages ; le noyau, lui,
        # voit aussi ceux de launchd, du bureau et des terminaux — sur TOUTES
        # les adresses, y compris celle du maillage. On laisse quelques
        # secondes à un port qu'on vient d'arrêter : sans cela, `restart`
        # arrêtait le serveur puis refusait de le relancer.
        etat, detail = _port_state(bind_port)
        attente = time.time() + 5.0
        while etat == OCCUPE and time.time() < attente:
            time.sleep(0.4)
            etat, detail = _port_state(bind_port)

        if etat == OCCUPE:
            console.print(f"[yellow]Port {bind_port} is already in use.[/yellow]")
            console.print(f"  Held by: {detail}")
            console.print(
                "Something is already serving there — launchd, the desktop app, "
                "or another terminal. Starting a second server would not report "
                "an error: it would quietly lose the race for the port."
            )
            sys.exit(1)
        if etat == INCONNU:
            # Fail-closed : ne pas lancer sur une ignorance. Un doublon
            # silencieux coûte plus cher qu'un démarrage refusé.
            console.print(
                f"[yellow]Cannot verify whether port {bind_port} is free "
                f"({detail}).[/yellow]"
            )
            console.print(
                "Refusing to start rather than risk a second, invisible server.\n"
                f"  Check by hand:  lsof -nP -iTCP:{bind_port} -sTCP:LISTEN"
            )
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

        # Start as background process, fully detached from the launching
        # terminal.
        #
        # ``start_new_session`` is POSIX-only: CPython's Windows
        # ``_execute_child`` names the parameter ``unused_start_new_session``
        # and ignores it. Relying on it there leaves the server sharing its
        # parent's console, so closing that console — or logging off —
        # delivers CTRL_CLOSE_EVENT and kills the daemon. DETACHED_PROCESS
        # gives it no console at all; the new process group additionally stops
        # a Ctrl-C in the parent reaching it.
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

        # Vérifier plutôt qu'annoncer, et vérifier la bonne chose : que le
        # processus LANCÉ serve, pas seulement que le port réponde.
        issue = _wait_until_serving(proc, bind_host, bind_port)

        if issue == DEAD:
            _PID_FILE.unlink(missing_ok=True)
            console.print(
                f"[red]The server exited before serving port {bind_port}.[/red]\n"
                f"  Log: {_LOG_FILE}"
            )
            sys.exit(1)

        if issue == USURPED:
            # Le port répond, mais il appartient à un autre : notre processus a
            # perdu la course. L'inscrire comme « le serveur » ferait perdre la
            # trace du vrai. On retire le nôtre plutôt que de mentir.
            _PID_FILE.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                proc.terminate()
            etat, detail = _port_state(bind_port)
            console.print(
                f"[red]Another server took port {bind_port} first.[/red]\n"
                f"  Held by: {detail or 'unknown'}\n"
                "  The process we launched has been stopped."
            )
            sys.exit(1)

        if issue == SILENT:
            # Vivant mais muet. On GARDE le fichier PID : l'effacer laisserait
            # un processus que `diapason stop` ne saurait plus retrouver. Code
            # de sortie 3, distinct de l'échec : ce n'est pas encore un succès,
            # mais ce n'est pas non plus une panne avérée.
            console.print(
                f"[yellow]Started (PID {proc.pid}) but no answer on "
                f"{bind_host}:{bind_port} yet.[/yellow]\n"
                "  A first boot can take a while to load its model.\n"
                f"  Log:    {_LOG_FILE}\n"
                "  Check:  diapason status\n"
                "  Stop:   diapason stop"
            )
            sys.exit(3)

        console.print(
            f"[green]Diapason server started[/green] (PID {proc.pid})\n"
            f"  URL: http://{bind_host}:{bind_port}\n"
            f"  Log: {_LOG_FILE}"
        )
    finally:
        if verrou is not None:
            os.close(verrou)


@daemon.command()
def stop() -> None:
    """Stop the running Diapason server daemon."""
    console = Console(stderr=True)
    config = load_config()
    bind_port = config.server.port
    pid = _read_pid(bind_port)
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        # Le fichier PID ne connaît que nos propres démarrages. Si le port est
        # servi par quelqu'un d'autre, le dire plutôt que laisser l'utilisateur
        # devant un « rien à arrêter » qui contredit ce qu'il voit.
        etat, detail = _port_state(bind_port)
        if etat == OCCUPE:
            console.print(f"  But port {bind_port} is served by: {detail}")
            console.print(
                "  This server was not started by 'diapason start'. Stop it "
                "where it came from — launchd, the desktop app, or its terminal."
            )
        sys.exit(1)

    if sys.platform == "win32":
        # ``os.kill(pid, 0)`` ne teste rien sur Windows : il TERMINE le
        # processus. On n'a donc aucun moyen sûr de sonder ici, et on se
        # contente de demander l'arrêt puis de vérifier par le port.
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            else:
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)

    # Vérifier plutôt qu'annoncer : « Server stopped » s'affichait même quand
    # le signal avait échoué, et le fichier PID était effacé par-dessus — le
    # serveur survivait, sans plus aucune trace pour le retrouver.
    fin = time.time() + 5.0
    while time.time() < fin:
        etat, detail = _port_state(bind_port)
        if etat != OCCUPE or all(str(pid) not in d for d in (detail,)):
            break
        time.sleep(0.3)
    etat, detail = _port_state(bind_port)
    encore_la = etat == OCCUPE and f"PID {pid} " in f"{detail} "

    if encore_la:
        console.print(
            f"[red]Could not stop the server (PID {pid}).[/red]\n"
            f"  It still holds port {bind_port}: {detail}\n"
            "  The PID file is kept so you can try again."
        )
        sys.exit(1)

    _PID_FILE.unlink(missing_ok=True)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the Diapason server daemon."""
    console = Console(stderr=True)
    config = load_config()
    pid = _read_pid(config.server.port)
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        # `stop` sort en 1 s'il n'a pas pu arrêter le serveur. Enchaîner sur
        # `start` reviendrait alors à lancer un doublon par-dessus. On s'arrête
        # là, en le disant — plutôt que d'arrêter le serveur puis d'échouer en
        # silence à le relancer.
        try:
            ctx.invoke(stop)
        except SystemExit as sortie:
            if sortie.code not in (0, None):
                console.print(
                    "[red]Not restarting: the server could not be stopped.[/red]"
                )
                raise
    ctx.invoke(start)


@daemon.command()
def status() -> None:
    """Show status of the Diapason server daemon."""
    console = Console(stderr=True)
    config_pour_port = load_config()
    bind_port = config_pour_port.server.port
    pid = _read_pid(bind_port)
    if pid is None:
        console.print("[yellow]Server is not running.[/yellow]")
        # Trois commandes doivent raconter la même histoire. `start` refuse
        # quand le port est pris ; `status` doit donc le dire aussi, sans quoi
        # l'utilisateur reçoit deux réponses incompatibles et aucune action.
        etat, detail = _port_state(bind_port)
        if etat == OCCUPE:
            console.print(f"  But port {bind_port} is served by: {detail}")
            console.print("  It was not started by 'diapason start'.")
        elif etat == INCONNU:
            console.print(f"  (Could not check port {bind_port}: {detail})")
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
