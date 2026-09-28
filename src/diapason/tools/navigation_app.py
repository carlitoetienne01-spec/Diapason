"""Navigation locale : seule la vue remontée par l'interface confirme l'ouverture."""

import re
import time
import unicodedata
import uuid

from diapason.desktop.contexte_app import dernier_contexte
from diapason.mesh.executor import push_shell_event, shell_is_collecting
from diapason.vie.store import VieError

# 27/09/2026 : le maillage ne connaît que cinq écrans. La navigation locale
# emploie les chemins réels, sans étendre le protocole signé des appareils.
PAGES = {
    "chat": "/",
    "overview": "/vie/dashboard",
    "planner": "/vie/planner",
    "tasks": "/vie/tasks",
    "projects": "/vie/projects",
    "finances": "/vie/finances",
    "habits": "/vie/habits",
    "notes": "/vie/notes",
    "year-review": "/vie/year-review",
    "settings": "/settings",
    "devices": "/devices",
    "get-started": "/get-started",
    "data-sources": "/data-sources",
    "agents": "/agents",
    "sync": "/vie/sync",
    "dashboard": "/dashboard",
    "logs": "/logs",
}


def page_demandee(texte: str) -> str | None:
    """Une page nommée explicitement, jamais le nom approximatif d'une app."""
    simple = "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.lower())
        if not unicodedata.combining(c)
    ).strip(" .!?")
    m = re.fullmatch(
        r"(?:diapason[, ]+)?(?:ouvre|affiche|montre|va sur|va dans)\s+"
        r"(?:la |le |les |mes |l['’])?(?:page |section |onglet )?(.+?)"
        r"(?:\s+(?:de|dans)\s+diapason)?",
        simple,
    )
    if not m or not (
        "diapason" in simple or re.search(r"\b(page|section|onglet)\b", simple)
    ):
        return None
    aliases = {
        "discussion": "chat",
        "chat": "chat",
        "vue d'ensemble": "overview",
        "planificateur": "planner",
        "planning": "planner",
        "taches": "tasks",
        "projets": "projects",
        "finances": "finances",
        "habitudes": "habits",
        "notes": "notes",
        "bilan annuel": "year-review",
        "reglages": "settings",
        "parametres": "settings",
        "appareils": "devices",
        "demarrage": "get-started",
        "sources de donnees": "data-sources",
        "agents": "agents",
        "synchronisation": "sync",
        "tableau de bord": "dashboard",
        "journaux": "logs",
    }
    return aliases.get(m[1])


def naviguer(page: str) -> dict:
    chemin = PAGES.get(page)
    if chemin is None:
        raise VieError("Page inconnue. Consulte les pages du catalogue.")
    if not shell_is_collecting():
        raise VieError("Aucune fenêtre Diapason ne reçoit la navigation.")
    debut = time.monotonic()
    vue = dernier_contexte()
    if vue and vue.chemin == chemin:
        return {"displayed": True, "page": page, "path": chemin}
    # La fenêtre relève toutes les deux secondes. Quatre secondes couvrent
    # deux relèves ; après cela l'événement expire, plutôt qu'ouvrir plus tard.
    entree = {
        "commandId": str(uuid.uuid4()),
        "originDeviceId": "local-assistant",
        "receivedAtMs": int(time.time() * 1000),
        "appPath": chemin,
        "expiresAtMs": int((time.time() + 4) * 1000),
    }
    if not push_shell_event(entree):
        raise VieError("La file de navigation est pleine ; écran non ouvert.")
    while time.monotonic() - debut < 4:
        vue = dernier_contexte()
        if vue and vue.chemin == chemin and vue.quand >= debut:
            return {"displayed": True, "page": page, "path": chemin}
        time.sleep(0.05)
    raise VieError("L'interface n'a pas confirmé l'affichage de cette page.")
