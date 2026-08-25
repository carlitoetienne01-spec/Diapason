"""Ce que l'utilisateur regarde DANS Diapason, à l'instant.

Spatial Mesh, handoff — 25 août 2026. « Diapason, continue ce projet sur
mon téléphone » suppose que « ce projet » ait un référent. Il n'en avait
aucun : les dix-neuf routes du frontend sont statiques, sans le moindre
paramètre, et la ressource sélectionnée vit en état local de composant
(``selectedId`` dans la page Projets, ``activeId`` dans les Notes). Ni le
serveur, ni le modèle, ne pouvaient dire quel projet était ouvert.

Ce module est le miroir exact d'``etat_bureau`` : un cliché VOLATILE en
variable de module, jamais persisté, lu sans jamais attendre, décrit en une
phrase française, et injecté en FIN de contexte du tour — un état qui change
à chaque clic n'a rien à faire dans un préambule qu'Ollama met en cache.

Il ne porte QUE ce qui traverse réellement : l'écran et la ressource
sélectionnée. Pas de filtre, pas de position de défilement, pas d'onglet —
le client mobile ne sait rien en restaurer, et un champ qui voyage sans
être lu finirait par se faire promettre.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Au-delà, le cliché ne décrit plus une intention présente mais un souvenir :
# l'utilisateur a fermé l'onglet, changé d'écran, éteint la machine. Mieux
# vaut ne rien dire que dire une vieille chose avec assurance.
TTL_S = 180.0

# Les écrans que le maillage sait ouvrir ailleurs, et le mot français qui les
# nomme. Liste blanche : un écran inconnu n'entre pas dans le cliché.
_ECRANS = {
    "/succes/projects": ("projects", "les Projets"),
    "/succes/notes": ("notes", "les Notes"),
    "/succes/tasks": ("tasks", "les Tâches"),
    "/succes/habits": ("habits", "les Habitudes"),
    "/succes/planner": ("today", "le Planificateur"),
    "/succes/dashboard": ("today", "le Tableau de bord"),
    "/succes/finances": (None, "les Finances"),
    "/succes/year-review": (None, "le Bilan annuel"),
    "/devices": (None, "les Appareils"),
    "/data-sources": (None, "les Sources de données"),
    "/agents": (None, "les Agents"),
    "/settings": (None, "les Réglages"),
    "/dashboard": (None, "le Tableau de bord"),
    "/": (None, "la conversation"),
}

# Ce que le maillage sait SÉLECTIONNER à l'arrivée, et rien d'autre : la
# table de features/mesh/routes.ts, côté serveur. Annoncer une ressource
# qu'aucun appareil ne sait mettre en évidence serait une promesse en l'air.
_SELECTIONNABLES = {"project", "note", "task"}


@dataclass(frozen=True, slots=True)
class ContexteApp:
    """L'écran ouvert, et la chose qu'on y regarde."""

    chemin: str
    ecran: str
    ressource_type: str = ""
    ressource_id: str = ""
    ressource_titre: str = ""
    quand: float = 0.0

    @property
    def frais(self) -> bool:
        return (time.monotonic() - self.quand) < TTL_S


_cache: Optional[ContexteApp] = None


def poser_contexte(
    chemin: str,
    *,
    ressource_type: str = "",
    ressource_id: str = "",
    ressource_titre: str = "",
) -> Optional[ContexteApp]:
    """Le frontend dit ce qu'il affiche. Refusé si l'écran est inconnu."""
    global _cache
    chemin = (chemin or "").strip() or "/"
    entree = _ECRANS.get(chemin)
    if entree is None:
        # Pas d'invention : un écran hors liste blanche efface le cliché
        # plutôt que d'en garder un périmé qui mentirait au tour suivant.
        _cache = None
        return None
    _, ecran = entree
    rtype = (ressource_type or "").strip().lower()
    if rtype not in _SELECTIONNABLES:
        rtype, ressource_id, ressource_titre = "", "", ""
    _cache = ContexteApp(
        chemin=chemin,
        ecran=ecran,
        ressource_type=rtype,
        ressource_id=str(ressource_id or "")[:120],
        ressource_titre=" ".join(str(ressource_titre or "").split())[:120],
        quand=time.monotonic(),
    )
    return _cache


def dernier_contexte() -> Optional[ContexteApp]:
    """Le cliché s'il est encore frais — jamais une milliseconde d'attente."""
    if _cache is not None and _cache.frais:
        return _cache
    return None


def oublier() -> None:
    """L'onglet se ferme : ce qu'il affichait n'est plus vrai."""
    global _cache
    _cache = None


def decrire(contexte: ContexteApp) -> str:
    """Le cliché en une phrase française, pour le contexte du modèle."""
    if contexte.ressource_id and contexte.ressource_titre:
        quoi = {
            "project": "le projet",
            "note": "la note",
            "task": "la tâche",
        }.get(contexte.ressource_type, "l'élément")
        return (
            f"Dans Diapason : {contexte.ecran}, {quoi} "
            f"« {contexte.ressource_titre} » ouvert(e)."
        )
    return f"Dans Diapason : {contexte.ecran}."


__all__ = [
    "ContexteApp",
    "TTL_S",
    "decrire",
    "dernier_contexte",
    "oublier",
    "poser_contexte",
]
