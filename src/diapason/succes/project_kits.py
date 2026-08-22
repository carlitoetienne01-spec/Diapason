"""Built-in project blueprints that materialize as task trees."""

from __future__ import annotations

from typing import Any, Mapping

from diapason.succes.store import SuccesError
from diapason.succes.structures import (  # noqa: F401 - réexport de compat
    PROJECT_STRUCTURES,
    normalize_structure,
)

# Each node: title, optional notes (short description), optional children.
_KitNode = Mapping[str, Any]

_KITS: tuple[dict[str, Any], ...] = (
    {
        "id": "moving",
        "name": "Déménagement",
        "description": "Préparer, emballer et s’installer sans rien oublier.",
        "icon": "📦",
        "nodes": (
            {
                "title": "Avant le déménagement",
                "notes": "Tout ce qu’il faut verrouiller avant le jour J.",
                "children": (
                    {
                        "title": "Résilier / transférer contrats",
                        "notes": "Loyer, internet, électricité, assurances.",
                    },
                    {
                        "title": "Cartons et emballage",
                        "notes": "Pièce par pièce, étiqueter clairement.",
                    },
                    {
                        "title": "Réservation camion / aide",
                        "notes": "Véhicule, amis, ou déménageurs.",
                    },
                ),
            },
            {
                "title": "Jour J",
                "notes": "Chargement, trajet, déchargement.",
                "children": (
                    {
                        "title": "Check-list départ",
                        "notes": "Compteurs, clés, état des lieux.",
                    },
                    {
                        "title": "Arrivée et déchargement",
                        "notes": "Prioriser cuisine et literie.",
                    },
                ),
            },
            {
                "title": "Installation",
                "notes": "Rendre le nouveau logement habitable.",
                "children": (
                    {
                        "title": "Ouvrir les services",
                        "notes": "Eau, électricité, internet.",
                    },
                    {
                        "title": "Déclarations administratives",
                        "notes": "Adresse, banque, employeur.",
                    },
                ),
            },
        ),
    },
    {
        "id": "exams",
        "name": "Semaine d’examens",
        "description": "Planifier révisions, matériel et récupération.",
        "icon": "📚",
        "nodes": (
            {
                "title": "Organisation",
                "notes": "Calendrier et conditions de passage.",
                "children": (
                    {
                        "title": "Horaires et salles",
                        "notes": "Noter date, heure, lieu.",
                    },
                    {
                        "title": "Matériel autorisé",
                        "notes": "Calculatrice, pièces d’identité…",
                    },
                ),
            },
            {
                "title": "Révisions",
                "notes": "Couvrir chaque matière sans surcharge.",
                "children": (
                    {
                        "title": "Matière principale",
                        "notes": "Priorité haute, fiches + annales.",
                    },
                    {
                        "title": "Matières secondaires",
                        "notes": "Révisions ciblées, points faibles.",
                    },
                    {
                        "title": "Quiz blanc",
                        "notes": "Simuler le temps limité.",
                    },
                ),
            },
            {
                "title": "Après les examens",
                "notes": "Repos et suivi des résultats.",
                "children": (
                    {
                        "title": "Repos",
                        "notes": "Sommeil et pause sans culpabilité.",
                    },
                    {
                        "title": "Suivi notes",
                        "notes": "Dates de publication et recours.",
                    },
                ),
            },
        ),
    },
    {
        "id": "podcast-launch",
        "name": "Lancer un podcast",
        "description": "Du concept au premier épisode publié.",
        "icon": "🎙️",
        "nodes": (
            {
                "title": "Concept",
                "notes": "Positionnement et format.",
                "children": (
                    {
                        "title": "Sujet et audience",
                        "notes": "Qui écoute, pourquoi.",
                    },
                    {
                        "title": "Nom et identité",
                        "notes": "Titre, visuel, intro.",
                    },
                ),
            },
            {
                "title": "Production",
                "notes": "Enregistrement et montage du pilote.",
                "children": (
                    {
                        "title": "Script du pilote",
                        "notes": "Structure 10–20 min.",
                    },
                    {
                        "title": "Enregistrement",
                        "notes": "Micro, pièce calme, prises.",
                    },
                    {
                        "title": "Montage et musique",
                        "notes": "Coupes, générique, niveaux.",
                    },
                ),
            },
            {
                "title": "Publication",
                "notes": "Hébergement et diffusion.",
                "children": (
                    {
                        "title": "Hébergeur / flux RSS",
                        "notes": "Compte et premiers réglages.",
                    },
                    {
                        "title": "Annonce",
                        "notes": "Réseaux, newsletter, proches.",
                    },
                ),
            },
        ),
    },
)


_EXTRA_KITS: tuple[dict[str, Any], ...] = (
    {
        "id": "video-release",
        "name": "Sortie d'une vidéo",
        "description": "Chaque vidéo traverse le même couloir, "
        "de l'idée à la publication.",
        "icon": "🎬",
        "structure": "pipeline",
        "structureConfig": {
            "stages": ["Idée", "Écrit", "Tourné", "Monté", "Publié"],
        },
        "nodes": (
            {"title": "Vidéo 1 — sujet à définir", "stage": "Idée"},
            {"title": "Vidéo 2 — sujet à définir", "stage": "Idée"},
            {"title": "Vidéo 3 — sujet à définir", "stage": "Idée"},
        ),
    },
    {
        "id": "weekly-reset",
        "name": "Routine hebdomadaire",
        "description": "La roue des rendez-vous avec soi-même ; "
        "chaque tour les régénère.",
        "icon": "🔄",
        "structure": "cycle",
        "nodes": (
            {
                "title": "Revue de la semaine",
                "notes": "Ce qui a marché, ce qui attend.",
                "cadence": {"every": "week", "day": 6},
            },
            {
                "title": "Budget et dépenses",
                "cadence": {"every": "week", "day": 2},
            },
            {
                "title": "Sport",
                "cadence": {"every": "week", "day": 0},
            },
            {
                "title": "Ménage et courses",
                "cadence": {"every": "week", "day": 5},
            },
        ),
    },
)


def _all_kits() -> tuple[dict[str, Any], ...]:
    return _KITS + _EXTRA_KITS


def list_project_kits() -> list[dict[str, Any]]:
    """Return kit summaries (no full node trees) for the picker UI."""
    return [
        {
            "id": kit["id"],
            "name": kit["name"],
            "description": kit["description"],
            "icon": kit.get("icon") or "",
            "structure": str(kit.get("structure") or "tree"),
            "nodeCount": _count_nodes(kit["nodes"]),
        }
        for kit in _all_kits()
    ]


def get_project_kit(kit_id: str) -> dict[str, Any]:
    needle = (kit_id or "").strip()
    for kit in _all_kits():
        if kit["id"] == needle:
            return {
                "id": kit["id"],
                "name": kit["name"],
                "description": kit["description"],
                "icon": kit.get("icon") or "",
                "structure": str(kit.get("structure") or "tree"),
                "structureConfig": dict(kit.get("structureConfig") or {}),
                "nodes": _clone_nodes(kit["nodes"]),
            }
    raise SuccesError("Ce modèle de projet est inconnu.")


def _count_nodes(nodes: Any) -> int:
    total = 0
    for node in nodes or ():
        total += 1
        total += _count_nodes(node.get("children") if isinstance(node, Mapping) else ())
    return total


def _clone_nodes(nodes: Any) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for node in nodes or ():
        if not isinstance(node, Mapping):
            continue
        cloned.append(
            {
                "title": str(node.get("title") or ""),
                "notes": str(node.get("notes") or ""),
                "stage": str(node.get("stage") or ""),
                "cadence": dict(node["cadence"])
                if isinstance(node.get("cadence"), Mapping)
                else None,
                "children": _clone_nodes(node.get("children")),
            }
        )
    return cloned
