"""§100 — une relecture explicite exige des données reçues pendant le tour."""

import json
import re


def offre_de_lecture(texte: str) -> bool:
    """Une offre encore en attente, pas le contenu d'une lecture déjà faite."""
    return "?" in texte and bool(
        re.search(
            r"\b(?:relis(?:e)?|relire|lire|lis(?:e)?|lecture|retrouve)\b",
            texte,
            re.I,
        )
    )


def relecture_note_demandee(texte: str) -> bool:
    return bool(
        re.search(
            r"\b(?:relis|relire|consulte|lire|lis|retrouve)\b.*\bnote\b",
            texte,
            re.I | re.S,
        )
        and not re.search(
            r"\b(?:explique|comment|ne\s+(?:lis|relis|consulte|retrouve))\b",
            texte,
            re.I,
        )
        and not re.search(r"\b(?:Apple\s+Notes|Notes\.app)\b", texte, re.I)
    )


def titre_note_cite(texte: str) -> str | None:
    trouve = re.search(r'\bnote\b[^«"“\n]*[«"“]([^»"”\n]+)[»"”]', texte, re.I)
    return trouve[1].strip() if trouve else None


def cibler_recherche_note(arguments: str, demande: str) -> str:
    """Une liste non filtrée ne prouve pas l'absence d'une note nommée."""
    titre = titre_note_cite(demande)
    if not titre:
        return arguments
    try:
        params = json.loads(arguments)
    except (TypeError, ValueError):
        return arguments
    if not isinstance(params, dict) or params.get("action") != "list_notes":
        return arguments
    if params.get("search"):
        return arguments
    # 27/09/2026 : la liste entière, tronquée à 4 000 caractères, masquait
    # la note du diagnostic. Le titre était pourtant cité dans la demande.
    params["search"] = titre
    return json.dumps(params, ensure_ascii=False)


CONSIGNE_RELECTURE = (
    "Une relecture de note est demandée. Utilise vie_workspace : read_note "
    "avec l'identifiant reçu précédemment, ou list_notes pour retrouver la note. "
    "Réponds avec le texte réellement reçu de l'outil, pas avec le souvenir du "
    "contenu créé. Aucun graphique pour une demande de texte."
)
