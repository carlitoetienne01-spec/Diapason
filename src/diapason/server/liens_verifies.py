"""§100 — une adresse proposée se retrouve dans un résultat réellement reçu."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

_ADRESSE = re.compile(
    r"https?://[^\s<>\[\]{}\"']+|(?<![\w@/])(?:[a-z0-9-]+\.)+"
    r"(?:com|org|net|fr|ca|io|edu|gov)(?:/[^\s<>\[\]{}\"']*)?",
    re.I,
)


def adresses(texte: str) -> list[str]:
    return list(
        dict.fromkeys(m.group().rstrip(".,;:!?)") for m in _ADRESSE.finditer(texte))
    )


def _cle(adresse: str) -> str:
    url = urlsplit(adresse if "://" in adresse else "https://" + adresse)
    return (
        url.netloc.lower().removeprefix("www.")
        + url.path.rstrip("/")
        + ("?" + url.query if url.query else "")
    )


def demande_de_liens(texte: str) -> bool:
    # « le lien social » ou « crée un lien entre mes tâches » ne réclame
    # aucune adresse. Ne pas transformer ces conversations en recherches.
    return bool(
        re.search(
            r"\b(?:donne|redonne|envoie|cherche|recherche|vérifie|verifie|trouve|"
            r"obtenir|besoin|veux|voudrais|quel|quelle|give|find|send|check)\b"
            r"[^!?\n]*\b(?:liens?|url|adresse (?:exacte|officielle|web)|links?)\b",
            texte,
            re.I,
        )
    )


def liens_sans_preuve(texte: str, sources: list[str]) -> bool:
    connus = {_cle(url) for url in sources}
    cites = adresses(texte)
    return not cites or any(_cle(url) not in connus for url in cites)


def page_a_verifier(texte: str, demande: str, sources: list[str]) -> str | None:
    """Une adresse candidate se lit avant d'être présentée comme vérifiée."""
    connus = {_cle(url) for url in sources}
    # Le domaine demandé a priorité sur un nouveau chemin improvisé.
    for url in [*adresses(demande), *adresses(texte)]:
        if _cle(url) not in connus:
            return url if "://" in url else "https://" + url
    return None


CONSIGNE_LIENS = (
    "Des liens sont demandés. Cherche ou lis les pages avec les outils. "
    "Recopie leurs adresses complètes, sans inventer un chemin ni un lien de "
    "remplacement. Une page en échec n'est pas vérifiée : cherche une autre "
    "adresse avec web_search. Pour un site officiel, consulte sa page. "
    "Si tu n'as pas de source, dis que tu n'as pas pu obtenir le lien. "
    "Ne restreins pas la recherche au dernier mois pour un sujet intemporel."
)


def repli_liens(sources: list[str], demande: str = "") -> str:
    # 27/09/2026 : après HTTP 404, le modèle affirmait une seconde adresse
    # jamais consultée. Le dernier recours livre les sources reçues sans
    # les rebaptiser « officielles » ni valider leur pertinence à sa place.
    if not sources:
        return "Je n’ai pas pu obtenir de lien vérifié pour cette demande."
    # 27/09/2026 : une page du domaine demandé avait bien été lue, mais
    # le dernier recours la noyait parmi cinq sites tiers. Garder l'adresse
    # reçue (redirection comprise), sans lui inventer un nouveau chemin.
    domaines = {_cle(url).split("/", 1)[0] for url in adresses(demande)}
    directes = [url for url in sources if _cle(url).split("/", 1)[0] in domaines]
    if len(domaines) == 1 and directes:
        return "Adresse reçue pour le site demandé : " + directes[0]
    return (
        "Voici les adresses reçues des outils ; leur pertinence reste à confirmer :\n"
        + "\n".join(dict.fromkeys(sources))
    )


def erreur_destination(nom: str, demande: str) -> str | None:
    plat = "".join(
        c
        for c in unicodedata.normalize("NFD", demande.lower())
        if not unicodedata.combining(c)
    )
    if nom == "notes_write" and re.search(
        r"\b(?:note\s+diapason|dans\s+diapason)\b", plat
    ):
        return (
            "La destination demandée est Notes dans Diapason. notes_write écrit "
            "dans Apple Notes : aucun changement effectué. Utilise vie_workspace "
            "(create_note, list_notes ou update_note) pour cette demande."
        )
    return None


CONSIGNE_REPRISE_LIENS = (
    CONSIGNE_LIENS + " La proposition précédente n’avait pas les adresses reçues. "
    "Elle n’a pas été livrée. Effectue la recherche manquante."
)
