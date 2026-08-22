"""Built-in project blueprints that materialize as task trees."""

from __future__ import annotations

from typing import Any, Mapping

from diapason.succes.store import SuccesError

PROJECT_STRUCTURES = frozenset({"flat", "tree"})

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


def list_project_kits() -> list[dict[str, Any]]:
    """Return kit summaries (no full node trees) for the picker UI."""
    return [
        {
            "id": kit["id"],
            "name": kit["name"],
            "description": kit["description"],
            "icon": kit.get("icon") or "",
            "nodeCount": _count_nodes(kit["nodes"]),
        }
        for kit in _KITS
    ]


def get_project_kit(kit_id: str) -> dict[str, Any]:
    needle = (kit_id or "").strip()
    for kit in _KITS:
        if kit["id"] == needle:
            return {
                "id": kit["id"],
                "name": kit["name"],
                "description": kit["description"],
                "icon": kit.get("icon") or "",
                "nodes": _clone_nodes(kit["nodes"]),
            }
    raise SuccesError("Ce modèle de projet est inconnu.")


def normalize_structure(value: Any, *, kit_id: str = "") -> str:
    if kit_id.strip():
        return "tree"
    raw = str(value or "flat").strip().lower()
    if raw not in PROJECT_STRUCTURES:
        raise SuccesError("La structure du projet doit être flat ou tree.")
    return raw


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
                "children": _clone_nodes(node.get("children")),
            }
        )
    return cloned
