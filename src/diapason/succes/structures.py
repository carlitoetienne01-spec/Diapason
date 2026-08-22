"""Les cinq formes qu'un projet Succès peut prendre, et leurs règles.

Un projet n'est pas toujours une liste. Selon la forme choisie, les mêmes
tâches se pensent autrement :

- ``flat``     — la liste simple, l'existant.
- ``tree``     — l'arbre généalogique : l'objectif engendre ses livrables,
  chaque étage porte un nom (``levelLabels``).
- ``mindmap``  — la carte neuronale : mêmes données que l'arbre, rendu
  radial ; c'est la forme de la phase d'idéation.
- ``pipeline`` — le couloir d'étapes : chaque tâche traverse les ``stages``
  du projet, la vue est un kanban.
- ``network``  — le réseau de dépendances : des tâches reliées par des
  arêtes « débloque → », sans hiérarchie ; le graphe doit rester sans
  boucle, sinon « que puis-je faire maintenant ? » n'a plus de réponse.
- ``cycle``    — la roue des routines : les tâches portent une cadence et
  chaque « nouveau tour » les régénère.

Ce module ne touche pas à la base : il définit et VALIDE. Les écritures
vivent dans store.py / workspace.py, la surface HTTP dans routes.py.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from diapason.succes.store import SuccesError

# L'ordre est celui du sélecteur de création : du plus familier au plus neuf.
PROJECT_STRUCTURES: tuple[str, ...] = (
    "flat",
    "tree",
    "mindmap",
    "pipeline",
    "network",
    "cycle",
)

# Les formes qui portent un arbre parent/enfant. Un kit (gabarit) matérialise
# toujours un arbre : s'il est appliqué à une forme plate, la forme devient
# ``tree`` — mais un choix explicite de ``mindmap`` est respecté, les deux
# formes partageant les mêmes données.
TREE_FAMILY = frozenset({"tree", "mindmap"})

DEFAULT_STAGES: tuple[str, ...] = ("À faire", "En cours", "Fait")

_MAX_LEVEL_LABELS = 6
_MAX_STAGES = 8
_MAX_LABEL_LEN = 40

STRUCTURE_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "flat",
        "name": "Liste",
        "icon": "☰",
        "description": "Des tâches, dans l'ordre. Le modèle simple.",
    },
    {
        "id": "tree",
        "name": "Arbre généalogique",
        "icon": "🌳",
        "description": "L'objectif en haut, ses livrables en dessous, "
        "chaque étage nommé.",
    },
    {
        "id": "mindmap",
        "name": "Carte neuronale",
        "icon": "🧠",
        "description": "L'objectif au centre, les idées qui rayonnent. "
        "Pour penser avant d'organiser.",
    },
    {
        "id": "pipeline",
        "name": "Pipeline",
        "icon": "🏭",
        "description": "Chaque tâche traverse les étapes du projet, "
        "comme sur un tableau kanban.",
    },
    {
        "id": "network",
        "name": "Réseau",
        "icon": "🕸️",
        "description": "Des tâches reliées par « débloque → ». "
        "Le projet montre ce qui est faisable maintenant.",
    },
    {
        "id": "cycle",
        "name": "Cycle",
        "icon": "🔄",
        "description": "La roue des routines : chaque tour régénère "
        "les tâches à cadence.",
    },
)


def normalize_structure(value: Any, *, kit_id: str = "") -> str:
    """La forme demandée, ou une erreur qui dit lesquelles existent."""
    raw = str(value or "flat").strip().lower()
    if raw not in PROJECT_STRUCTURES:
        raise SuccesError(
            "La structure du projet doit être l'une de : "
            + ", ".join(PROJECT_STRUCTURES)
            + "."
        )
    if kit_id.strip() and raw == "flat":
        # Un gabarit matérialise un arbre : la forme plate ne peut pas le
        # porter. Le choix explicite d'une autre forme reste respecté.
        return "tree"
    return raw


def _clean_labels(
    raw: Any, *, field: str, maximum: int, allow_empty: bool
) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise SuccesError(f"{field} doit être une liste de textes.")
    labels: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if not text:
            raise SuccesError(f"{field} ne doit pas contenir d'entrée vide.")
        labels.append(text[:_MAX_LABEL_LEN])
    if len(labels) > maximum:
        raise SuccesError(f"{field} est limité à {maximum} entrées.")
    if len(labels) != len({label.lower() for label in labels}):
        raise SuccesError(f"{field} ne doit pas contenir de doublon.")
    if not labels and not allow_empty:
        raise SuccesError(f"{field} ne doit pas être vide.")
    return labels


def normalize_structure_config(structure: str, raw: Any) -> dict[str, Any]:
    """La configuration propre à une forme, validée et rien de plus.

    On ne garde QUE les clés que la forme connaît : une configuration qui
    survivrait à un changement de forme transporterait des réglages morts,
    et le client mobile les re-synchroniserait à jamais.
    """
    data: Mapping[str, Any]
    if raw is None:
        data = {}
    elif isinstance(raw, Mapping):
        data = raw
    else:
        raise SuccesError("La configuration de structure doit être un objet.")

    if structure in TREE_FAMILY:
        labels = _clean_labels(
            data.get("levelLabels"),
            field="levelLabels",
            maximum=_MAX_LEVEL_LABELS,
            allow_empty=True,
        )
        return {"levelLabels": labels} if labels else {}

    if structure == "pipeline":
        stages = _clean_labels(
            data.get("stages"),
            field="stages",
            maximum=_MAX_STAGES,
            allow_empty=True,
        ) or list(DEFAULT_STAGES)
        if len(stages) < 2:
            raise SuccesError("Un pipeline demande au moins deux étapes.")
        return {"stages": stages}

    # flat, network, cycle : aucune configuration aujourd'hui. Le réseau vit
    # dans ses arêtes, le cycle dans la cadence des tâches.
    return {}


def encode_structure_config(config: Mapping[str, Any]) -> str:
    return json.dumps(dict(config), ensure_ascii=False, sort_keys=True)


def decode_structure_config(raw: Any) -> dict[str, Any]:
    """Relit la configuration stockée sans jamais faire échouer une lecture."""
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def stages_of(structure: str, config: Mapping[str, Any]) -> list[str]:
    """Les étapes d'un projet pipeline ; vide pour toute autre forme."""
    if structure != "pipeline":
        return []
    stages = config.get("stages")
    if isinstance(stages, list) and len(stages) >= 2:
        return [str(s) for s in stages]
    return list(DEFAULT_STAGES)


def normalize_cadence(raw: Any) -> str:
    """La cadence d'une tâche de cycle, encodée pour la colonne.

    ``""`` = pas de cadence. Sinon ``{"every": "day"|"week"|"month",
    "day": int?}`` — ``day`` vaut 0..6 (lundi=0) pour la semaine, 1..28 pour
    le mois, et n'a pas de sens pour le jour.
    """
    if raw is None or raw == "" or raw == {}:
        return ""
    if not isinstance(raw, Mapping):
        raise SuccesError("La cadence doit être un objet {every, day?}.")
    every = str(raw.get("every") or "").strip().lower()
    if every not in ("day", "week", "month"):
        raise SuccesError("La cadence doit être day, week ou month.")
    out: dict[str, Any] = {"every": every}
    if every != "day":
        day = raw.get("day")
        if day is None:
            raise SuccesError("Cette cadence demande un jour (day).")
        try:
            day = int(day)
        except (TypeError, ValueError) as exc:
            raise SuccesError("Le jour de la cadence doit être un entier.") from exc
        if every == "week" and not 0 <= day <= 6:
            raise SuccesError("Le jour hebdomadaire va de 0 (lundi) à 6.")
        if every == "month" and not 1 <= day <= 28:
            raise SuccesError(
                "Le jour mensuel va de 1 à 28, pour exister tous les mois."
            )
        out["day"] = day
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


def decode_cadence(raw: Any) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
