"""Qui tient un port, et qui descend de qui — d'après le système, pas d'après nous.

Ce module existe parce que quatre chemins de démarrage différents posaient la
même question et y répondaient chacun à leur façon : ``diapason start``,
l'application de bureau, ``serve-service install`` et ``quickstart.sh``. Trois
d'entre eux ne la posaient même pas, et lançaient un serveur par-dessus un
autre sans qu'aucune erreur ne soit rapportée.

Le principe : ne rien DÉDUIRE. Une liaison qui échoue, un ``200`` sur un port,
une ligne de commande recollée sont des indices, pas des preuves. On demande au
noyau, et quand il ne répond pas, on le dit au lieu de conclure.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys

# Le PATH doit contenir /usr/sbin : c'est là que vit ``lsof`` sur macOS, et
# un PATH forcé qui l'oublie ferait silencieusement échouer toute la mécanique.
PATH_SYS = "/usr/bin:/bin:/usr/sbin:/sbin"


def run_tool(
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
            env={"LC_ALL": "C", "PATH": os.environ.get("PATH", "") + ":" + PATH_SYS},
        )
    except (OSError, subprocess.SubprocessError):
        return None


def listeners_on(port: int) -> list[tuple[int, str]] | None:
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
        return listeners_windows(port)
    sortie = run_tool(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "pn"])
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


def listeners_windows(port: int) -> list[tuple[int, str]] | None:
    """Équivalent Windows de ``lsof``, via ``netstat -ano``.

    NON VÉRIFIÉ sur cette machine, faute de Windows sous la main : la forme est
    documentée, pas mesurée, à la différence du reste de ce fichier. Elle existe
    surtout pour que ``start`` ne réponde pas « je ne sais pas » à l'infini là
    où lsof n'existe pas — un garde qui refuse toujours de démarrer serait une
    panne, pas une protection.
    """
    sortie = run_tool(["netstat", "-ano", "-p", "TCP"])
    if sortie is None or sortie.returncode != 0:
        return None
    trouves: list[tuple[int, str]] = []
    for ligne in sortie.stdout.splitlines():
        morceaux = ligne.split()
        if len(morceaux) < 5 or morceaux[0].upper() != "TCP":
            continue
        if morceaux[3].upper() != "LISTENING":
            continue
        locale = morceaux[1]
        if not locale.rsplit(":", 1)[-1].isdigit():
            continue
        if int(locale.rsplit(":", 1)[-1]) != port:
            continue
        try:
            trouves.append((int(morceaux[4]), locale))
        except ValueError:
            continue
    return trouves


def port_occupe_par_liaison(port: int) -> bool | None:
    """Dernier repli : tenter la liaison soi-même. None si on n'apprend rien.

    Ne voit qu'un détenteur sur l'une des quatre formes essayées — c'est
    précisément la faiblesse qui a laissé passer un serveur lié à l'adresse du
    maillage. On ne s'en sert donc que si le système n'a pas su répondre.

    ``SO_REUSEADDR`` seulement sur POSIX : il y ignore TIME_WAIT, sans quoi un
    port qu'on vient de libérer paraîtrait pris. Sur Windows sa sémantique est
    INVERSE — il autorise à se lier par-dessus un socket actif — et le poser
    annulerait entièrement le contrôle.
    """
    import errno
    import socket

    formes = (
        (socket.AF_INET, "0.0.0.0"),
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET6, "::"),
        (socket.AF_INET6, "::1"),
    )
    a_pu_tester = False
    for famille, adresse in formes:
        try:
            sonde = socket.socket(famille, socket.SOCK_STREAM)
        except OSError:
            continue
        if sys.platform != "win32":
            sonde.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if famille == socket.AF_INET6:
            with contextlib.suppress(OSError):
                sonde.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            sonde.bind((adresse, port))
            a_pu_tester = True
        except OSError as erreur:
            if erreur.errno == errno.EADDRINUSE:
                sonde.close()
                return True
        finally:
            sonde.close()
    return False if a_pu_tester else None


def descendants_of(racine: int) -> set[int]:
    """``racine`` et toute sa descendance, d'après ``ps``.

    Un serveur peut être lancé derrière un lanceur (``uv run``), auquel cas le
    processus qui tient le port n'est pas celui qu'on a lancé, mais son enfant.
    """
    sortie = run_tool(["ps", "-eo", "pid=,ppid="])
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


# Trois états d'un port, et « je ne sais pas » en est un.
LIBRE = "libre"
OCCUPE = "occupe"
INCONNU = "inconnu"


def port_state(port: int) -> tuple[str, str]:
    """État du port et description lisible du détenteur."""
    auditeurs = listeners_on(port)
    if auditeurs is None:
        # Le système n'a pas su répondre. Plutôt que de refuser tout démarrage
        # à jamais, on retombe sur la liaison directe — partielle, mais valant
        # mieux que rien — et on ne rend INCONNU que si elle échoue aussi.
        par_liaison = port_occupe_par_liaison(port)
        if par_liaison is True:
            return OCCUPE, f"port {port} occupé (détecté par liaison directe)"
        if par_liaison is False:
            return LIBRE, ""
        return INCONNU, "ni lsof ni liaison directe n'ont pu répondre"
    if not auditeurs:
        return LIBRE, ""
    detail = ", ".join(f"PID {p} sur {adresse}" for p, adresse in auditeurs)
    return OCCUPE, detail
