"""Une question à trou reçoit une question, pas une fourchette.

29/09/2026 : « Dis-moi Diabazon, il fait quelle température maintenant ? »
ne nommait aucune ville. Le tour partait en recherche et revenait
« entre 10 °C en Savoie et 22 °C dans le sud-ouest … 30 °C à Bordeaux »,
avec le badge vérifié. La config ne comble pas le trou (§34). Le même
trou, sur un autre sujet, pose une seule question.

Appelants : ``stream_with_tools`` (chat) et ``LocalVoiceSession._respond_to_text``
(voix). Pas de route nouvelle, pas de champ sur le fil.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from diapason.server.meteo_ouverte import ville_ecrite, ville_hors_table
from diapason.server.sources_officielles import (
    _METEO,
    _NOM_PROPRE_MILIEU,
    VILLES,
    _plat,
    ville_de,
)

DANS_QUELLE_VILLE = "Dans quelle ville ?"
DE_QUEL_ENDROIT = "De quel endroit ?"
DE_QUEL_PAYS = "De quel pays ?"
DE_QUEL_MATCH = "De quel match parles-tu ?"

_QUESTIONS = frozenset(
    {DANS_QUELLE_VILLE, DE_QUEL_ENDROIT, DE_QUEL_PAYS, DE_QUEL_MATCH}
)

# Le nom dit en s'adressant à l'assistant n'est pas un lieu.
_VOCATIF = re.compile(
    r"^(?:dis[- ]moi|dit[- ]moi|hey|bonjour\s+)?"
    r"(?:diapason|diabazon|diabason|diapazon)\s*[,:]?\s*",
    re.IGNORECASE,
)
_HABITANTS = re.compile(r"\b(?:population|habitants?)\b")
_CAPITALE = re.compile(r"\bcapitale\b")
_SCORE = re.compile(r"\b(?:qui a gagne|quel est le score|c'est quoi le score)\b")
_EVENEMENT = re.compile(
    r"\b(?:match|finale|coupe|ligue|championnat|serie|stanley|"
    r"nba|nfl|nhl|mlb|olympique|mondial)\b"
)
_COMPLEMENT = re.compile(
    r"\b(?:a|au|aux|en|dans|de|du|des|d')\s+(?:(?:la|le|les|l')\s+)?"
    r"([a-z][\w'-]{2,}(?:\s+[a-z][\w'-]{2,}){0,2})"
)
_PAS_UNE_REPONSE = frozenset(
    {
        "oui",
        "non",
        "ouais",
        "ok",
        "okay",
        "je ne sais pas",
        "je sais pas",
        "aucune idee",
        "peu importe",
        "aucune",
        "rien",
    }
)
# Un moment n'est pas le lieu qu'on vient de répondre. Un pays, si :
# « France » après « De quel pays ? » complète la question. Ce n'est
# toujours pas une ville — la météo redemande.
_PAS_UN_MOMENT = frozenset(
    {
        "soir",
        "matin",
        "midi",
        "nuit",
        "maintenant",
        "aujourdhui",
        "aujourd'hui",
        "demain",
        "hier",
        "moment",
        "instant",
        "heure",
        "heures",
        "direct",
        "semaine",
        "mois",
        "annee",
        "hui",
        "ce",
    }
)
_POLITESSE = re.compile(
    r"\b(?:s'il te plait|s'il vous plait|stp|svp|merci|"
    r"diapason|diabazon)\b"
)
_AMORCE = re.compile(
    r"^(?:dis[- ]moi\s+|c'est\s+|c est\s+|a\s+|au\s+|aux\s+|en\s+|"
    r"dans\s+|pour\s+|de\s+|du\s+|des\s+|d')"
)


_QUITTE_LE_SUJET = re.compile(
    r"\b(?:parle plus de|ne parle plus|plus question de|"
    r"change(?:r|ons)? de sujet|recettes?|pates|cuisiner|"
    r"pas (?:de |la )?meteo|aucune meteo)\b"
)


def sujet_quitte(texte: str) -> bool:
    """La phrase laisse le sujet en cours.

    29/09/2026 : « je parle plus de météo, je parle des recettes » contient
    le mot météo. Le tour restait une prévision et lisait Ottawa.
    """
    return bool(_QUITTE_LE_SUJET.search(_plat(texte or "")))


def question_a_poser(demande: str) -> str | None:
    """La question unique quand il manque l'argument, sinon None."""
    texte = _VOCATIF.sub("", demande.strip(), count=1)
    plat = _plat(texte)
    if sujet_quitte(texte):
        return None
    if _METEO.search(plat) and not ville_de(texte, "") and not ville_hors_table(texte):
        return DANS_QUELLE_VILLE
    if _HABITANTS.search(plat) and not _lieu_nomme(texte):
        return DE_QUEL_ENDROIT
    if _CAPITALE.search(plat) and not _lieu_nomme(texte):
        return DE_QUEL_PAYS
    if _SCORE.search(plat) and not _EVENEMENT.search(plat) and not _lieu_nomme(texte):
        return DE_QUEL_MATCH
    return None


_AUTRE_SUJET = re.compile(
    r"\b(?:maire|president|population|habitants?|capitale|score|match)\b"
)
_OUI = re.compile(r"\b(?:oui|ouais|ok|okay|d'accord|dac|vas-y|tu peux)\b")
_OFFRE = re.compile(r"\b(?:recherche|verifi|resultat|pas encore|je lance)\b")
_DEGRE = re.compile(r"°\s*c", re.IGNORECASE)
_TEMPERATURE_LUE = re.compile(r"-?\d+(?:[.,]\d+)?\s*°\s*C", re.IGNORECASE)
_PAS_UNE_VILLE_SUITE = frozenset(
    {"cette", "ville", "temps", "meteo", "recherche", "resultat", "precise", "nouvelle"}
)


def meteo_heritee(demande: str, messages: Sequence[Any]) -> str | None:
    """« Et pour Trois-Rivières ? » après une question météo redevient
    une prévision.

    29/09/2026 : le suivi nommait la ville sans le mot météo. Le tour
    n'entrait pas dans la garde, le modèle annonçait une recherche et
    n'énonçait aucun degré. Un « oui » après cette annonce reprend la
    ville déjà dite.
    """
    texte = _VOCATIF.sub("", (demande or "").strip(), count=1)
    if not texte or sujet_quitte(texte) or _AUTRE_SUJET.search(_plat(texte)):
        return None
    if _METEO.search(_plat(texte)) and _nom_affiche(texte):
        return None
    tours = _tours(messages)
    if tours and tours[-1][0] == "user" and tours[-1][1].strip() == demande.strip():
        tours = tours[:-1]
    if not any(
        _METEO.search(_plat(tour)) or _DEGRE.search(tour) for _, tour in tours[-8:]
    ):
        return None
    nom = _nom_affiche(texte)
    if not nom and "?" not in texte and _OUI.search(_plat(texte)):
        precedent = next((t for role, t in reversed(tours) if role == "assistant"), "")
        if _OFFRE.search(_plat(precedent)) or _METEO.search(_plat(precedent)):
            for role, tour in reversed(tours):
                if role != "user":
                    continue
                nom = _nom_affiche(tour)
                if nom:
                    break
    if not nom:
        return None
    return f"Quel temps fait-il à {nom} ?"


def reponse_meteo(
    question: str, reponse: str, corpus: str, *, officielle_lue: bool
) -> str:
    """Le degré lu, quand la phrase annonce une recherche sans le dire."""
    if (
        not officielle_lue
        or sujet_quitte(question)
        or not _METEO.search(_plat(question or ""))
    ):
        return ""
    if _TEMPERATURE_LUE.search(reponse or ""):
        return ""
    trouve = _TEMPERATURE_LUE.search(corpus or "")
    if trouve is None:
        return ""
    source = "Open-Meteo" if "Open-Meteo" in (corpus or "") else "Environnement Canada"
    return source + " indique " + re.sub(r"\s+", "", trouve.group(0)) + "."


def _nom_affiche(texte: str) -> str:
    cle = ville_de(texte, "")
    if cle:
        return VILLES[cle][2]
    ecrit = ville_ecrite(texte)
    if not ecrit or _plat(ecrit) in _PAS_UNE_VILLE_SUITE:
        return ""
    return _titre(ecrit)


def demande_completee(demande: str, messages: Sequence[Any]) -> str | None:
    """La demande précédente, complétée par le lieu que l'on vient de dire.

    « Lyon » seul n'est pas une question météo : sans le tour d'avant,
    la prévision ne part pas. Une nouvelle question (elle contient « ? »)
    ne compte pas comme une ville.
    """
    if "?" in demande:
        return None
    lieu = _lieu_dans_la_reponse(demande)
    if not lieu:
        return None
    tours = _tours(messages)
    if tours and tours[-1][0] == "user" and tours[-1][1].strip() == demande.strip():
        tours = tours[:-1]
    question = next((t for role, t in reversed(tours) if role == "assistant"), "")
    if question.strip() not in _QUESTIONS:
        return None
    precedente = next((t for role, t in reversed(tours) if role == "user"), "")
    if not precedente.strip():
        return None
    return _joindre(question.strip(), precedente, lieu)


def _lieu_nomme(texte: str) -> bool:
    if ville_de(texte, ""):
        return True
    if _NOM_PROPRE_MILIEU.search(_VOCATIF.sub("", texte.strip(), count=1)):
        return True
    plat = _plat(texte)
    for mot in _COMPLEMENT.finditer(plat):
        nom = mot.group(1)
        if not nom or nom in _PAS_UN_MOMENT or nom.split()[0] in _PAS_UN_MOMENT:
            continue
        # 29/09/2026 : « qui a gagné » pliait « a gagné » en lieu, à cause
        # du « à » qui perd son accent. L'auxiliaire n'est pas une préposition.
        avant = plat[: mot.start()].rstrip()
        if avant.endswith(("qui", "il", "on", "elle", "j")):
            continue
        return True
    return False


def _lieu_dans_la_reponse(demande: str) -> str:
    plat = _POLITESSE.sub(" ", _plat(demande))
    plat = _AMORCE.sub("", plat.strip())
    plat = re.sub(r"\s+", " ", plat).strip(" .,;:!")
    if not plat or plat in _PAS_UNE_REPONSE:
        return ""
    mots = plat.split()
    if len(mots) > 4 or any(m in _PAS_UN_MOMENT for m in mots):
        return ""
    if not re.fullmatch(r"[a-z][\w'-]*(?:\s+[a-z][\w'-]*){0,3}", plat):
        return ""
    return plat


def _joindre(question_posee: str, precedente: str, lieu: str) -> str:
    titre = _titre(lieu)
    if question_posee == DE_QUEL_PAYS:
        complement = f"de {titre}"
    elif lieu.startswith(("la ", "le ", "les ")):
        complement = titre
    else:
        complement = f"à {titre}"
    base = precedente.strip().rstrip(" ?.!")
    return f"{base} {complement} ?"


def _titre(lieu: str) -> str:
    def mot(piece: str) -> str:
        return "-".join(p.capitalize() for p in piece.split("-"))

    return " ".join(mot(m) for m in lieu.split())


def _tours(messages: Sequence[Any]) -> list[tuple[str, str]]:
    tours: list[tuple[str, str]] = []
    for message in messages:
        couple = _role_contenu(message)
        if couple is not None and couple[0] in ("user", "assistant"):
            tours.append(couple)
    return tours


def _role_contenu(message: Any) -> tuple[str, str] | None:
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[0]), str(message[1] or "")
    if isinstance(message, dict):
        return str(message.get("role") or ""), str(message.get("content") or "")
    role = getattr(message, "role", None)
    if role is None:
        return None
    valeur = getattr(role, "value", role)
    return str(valeur), str(getattr(message, "content", "") or "")
