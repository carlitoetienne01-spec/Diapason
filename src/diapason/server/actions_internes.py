"""Les lectures périment après une écriture, pas les protections contre les doublons."""

import json
import re
import unicodedata


def mutation_interne_demandee(texte: str) -> bool:
    """Une demande d'action, pas une explication ni une consultation."""
    simple = "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.lower())
        if not unicodedata.combining(c)
    )
    if re.search(r"\b(comment|explique|exemple|si je|ne |n['’])", simple):
        return False
    return bool(
        re.search(
            r"\b(cree|creer|ajoute|ajouter|modifie|modifier|fixe|fixer|supprime|"
            r"supprimer|efface|effacer|enregistre|enregistrer|renomme|renommer|"
            r"deplace|deplacer|mets a jour|mettre a jour|reporte|reporter|"
            r"marque|marquer)\b",
            simple,
        )
        and re.search(
            r"\b(taches?|notes?|projets?|habitudes?|budgets?|comptes?|depenses?|revenus?|transactions?|abonnements?|objectifs?|routines?)\b",
            simple,
        )
    )


def clarification_sans_confirmation(texte: str) -> bool:
    """§100 : retenir un faux succès ne doit pas empêcher de demander la cible."""
    simple = "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.lower())
        if not unicodedata.combining(c)
    )
    return "?" in texte and not re.search(
        r"\b(fait|cree|ajoute|modifie|supprime|efface|enregistre|renomme|deplace|"
        r"confirme|effectue|termine|mis a jour|fixe|reporte|marque)\b",
        simple,
    )


_LECTURES = {
    "vie_tasks": {"list", "count", "read", "branches", "next_actions"},
    "vie_workspace": {
        "overview",
        "list_projects",
        "list_habits",
        "list_notes",
        "read_note",
    },
    "vie_continuity": {"list_templates", "list_quotes", "year_review"},
    "vie_finances": {
        "overview",
        "list_accounts",
        "list_subscriptions",
        "list_categories",
    },
}


def nature_action_interne(nom: str, arguments: str) -> str:
    try:
        args = json.loads(arguments)
        if not isinstance(args, dict):
            return ""
    except ValueError:
        return ""
    if nom == "diapason_app":
        operation = args.get("operation", "")
        if operation in {"catalogue", "describe", "navigate", "current_view"}:
            return ""
        from diapason.tools.diapason_app import _noms

        if operation not in _noms():
            return ""
        if operation.startswith(("get_", "list_")) or operation in {
            "planner",
            "planner_pastilles",
            "dashboard",
            "year_review",
            "note_summaries",
            "finance_overview",
        }:
            return "read"
        return "write"
    if nom in _LECTURES:
        return "read" if args.get("action") in _LECTURES[nom] else "write"
    if nom in {
        "diapason_app_delete",
        "vie_delete_task",
        "vie_delete_item",
        "vie_delete_continuity",
    }:
        return "write"
    return ""
