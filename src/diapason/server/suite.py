"""La suite d'une conversation hérite de son sujet.

21 septembre 2026, 23 h : « Qui est le président actuel d'Haïti ? », réponse
vérifiée en ligne — puis « Raconte-moi l'histoire de ce pays » recevait
« il faudrait que tu me dises de quel pays tu parles ! Est-ce que tu veux
parler de la France, du Canada, des États-Unis… ». Le fil était bien
envoyé en entier (16 722 jetons) ; rejoué par l'API avec le même
historique, le 9b répond « Est-ce Haïti, comme suggéré par la question
précédente ? » — il VOIT la question d'avant et n'ose pas conclure. Avec
une ligne qui dit que « ce pays » renvoie à l'échange précédent, il
raconte 1804 sans hésiter.

Le code sait, lui, qu'une demande courte qui dit « ce pays », « cette
équipe », « celui-ci », « parle-moi de lui », « son histoire » renvoie à
ce qui précède : il le dit au modèle, en citant la question précédente et
le début de sa réponse. Rien n'est deviné (§34) — le référent reste à
résoudre par le modèle, dans deux phrases au lieu de seize mille jetons.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from diapason.core.types import Message, Role
from diapason.server.actualite import _plat, est_une_demande_de_verification

# Deux lignes de chat, comme tour_leger.LONGUEUR_MAX : une demande longue
# porte son sujet.
LONGUEUR_MAX = 200
# Ce qu'on cite de la réponse précédente : assez pour y lire le référent
# (« Alix Didier Fils-Aimé », « les Hurricanes ») sans tout recopier.
EXTRAIT_REPONSE = 240

# Les démonstratifs qui désignent une chose dite avant — pas le temps (« ce
# soir », « cette semaine »), pas la tournure (« ce que », « ce qui »), pas
# le message lui-même (« ce texte », « cette phrase »).
_RENVOI = re.compile(
    r"\b(?:ce|cet|cette|ces)\s+"
    r"(?!(?:que|qui|qu|dont|soir|matin|midi|apres.midi|nuit|semaine|mois|"
    r"week.end|weekend|jour|jours|annee|annees|fois|moment|temps|heure|heures|"
    r"instant|genre|cas|point|texte|phrase|message|mot|mots|passage|paragraphe|"
    r"code|fichier|script|courriel|mail|dernier|derniere)\b)"
    r"[a-z][a-z-]{2,}|"
    r"\bcel(?:ui|le|les|ux)[- ](?:ci|la)\b|"
    r"\b(?:de|d')\s?(?:lui|elle|eux|elles)\b|"
    r"\bet (?:lui|elle|eux|elles)\s*\?|"
    r"\b(?:son|sa|ses|leur|leurs)\s+(?:histoire|nom|age|capitale|population|"
    r"carriere|parcours|prix|score|biographie|origines?|equipe|entraineur|"
    r"president|premier ministre|maire|langue|monnaie|drapeau|superficie|"
    r"climat|economie|culture|geographie|hymne|auteur|realisateur|date|"
    r"adresse|site|numero|horaires?)\b|"
    r"\bla.bas\b"
)
_CITATION = re.compile(r"\s*\[\d+\]")

RAPPEL_DU_SUJET = (
    "La demande renvoie à ce qui précède (« {renvoi} ») : elle porte sur le "
    "sujet de l'échange précédent — question : « {question} »{reponse}. Réponds "
    "sur ce sujet ; ne redemande pas de quoi il s'agit."
)


def renvoi(texte: str) -> str | None:
    """Le mot par lequel la demande renvoie à ce qui précède, ou None."""
    if not texte or len(texte) > LONGUEUR_MAX:
        return None
    brut = texte.strip()
    plat = _plat(brut)
    m = _RENVOI.search(plat)
    if m is None:
        return None
    # Le mot tel qu'il a été écrit (« cette équipe »), quand l'aplatissement
    # a gardé les positions — c'est le cas du français courant.
    if len(plat) == len(brut):
        return brut[m.start() : m.end()].strip()
    return m.group(0).strip()


def rappel_du_sujet(
    demande: str, question_precedente: str, reponse_precedente: str = ""
) -> str | None:
    """La ligne SYSTEM qui dit au modèle sur quoi porte « ce pays »."""
    mot = renvoi(demande)
    if mot is None or not question_precedente.strip():
        return None
    extrait = _CITATION.sub("", reponse_precedente or "").strip()
    extrait = " ".join(extrait.split())
    if len(extrait) > EXTRAIT_REPONSE:
        extrait = extrait[:EXTRAIT_REPONSE].rsplit(" ", 1)[0] + "…"
    reponse = f" ; début de la réponse : « {extrait} »" if extrait else ""
    question = " ".join(question_precedente.split())
    if len(question) > LONGUEUR_MAX:
        question = question[:LONGUEUR_MAX].rsplit(" ", 1)[0] + "…"
    return RAPPEL_DU_SUJET.format(renvoi=mot, question=question, reponse=reponse)


def _echange_precedent(
    tours: Sequence[tuple[str, str]],
) -> tuple[str, str] | None:
    """La question d'avant (hors demandes de vérification, qui n'ont pas
    de sujet à elles) et la réponse qui l'a suivie."""
    reponse = ""
    for role, contenu in reversed(tours):
        if role == "assistant":
            if not reponse:
                reponse = contenu
            continue
        if role == "user":
            if est_une_demande_de_verification(contenu):
                continue
            return contenu, reponse
    return None


def avec_rappel(messages: Sequence[Message]) -> list[Message]:
    """Le fil, plus le rappel du sujet quand la dernière demande renvoie à
    ce qui précède — en fin de fil, après les consignes du tour déjà
    posées (le rappel des questions suit la demande ; le poser AVANT lui
    faisait recoller la consigne des questions au rappel du sujet au lieu
    du prompt d'identité, et le préfixe en cache ne correspondait plus)."""
    rang = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == Role.USER),
        None,
    )
    if rang is None or messages[rang].images:
        return list(messages)
    demande = messages[rang].content or ""
    tours = [
        (m.role.value if hasattr(m.role, "value") else str(m.role), m.content or "")
        for m in messages[:rang]
        if m.role in (Role.USER, Role.ASSISTANT)
    ]
    precedent = _echange_precedent(tours)
    if precedent is None:
        return list(messages)
    rappel = rappel_du_sujet(demande, *precedent)
    if rappel is None:
        return list(messages)
    return [*messages, Message(role=Role.SYSTEM, content=rappel)]


def rappel_pour_la_voix(
    historique: Sequence[dict[str, Any]], demande: str
) -> dict[str, str] | None:
    """Le même rappel, pour l'assemblage vocal (messages en dictionnaires)."""
    tours = [
        (str(m.get("role") or ""), str(m.get("content") or ""))
        for m in historique
        if m.get("role") in ("user", "assistant")
    ]
    precedent = _echange_precedent(tours)
    if precedent is None:
        return None
    rappel = rappel_du_sujet(demande, *precedent)
    return {"role": "system", "content": rappel} if rappel else None


__all__ = [
    "EXTRAIT_REPONSE",
    "LONGUEUR_MAX",
    "RAPPEL_DU_SUJET",
    "avec_rappel",
    "rappel_du_sujet",
    "rappel_pour_la_voix",
    "renvoi",
]
