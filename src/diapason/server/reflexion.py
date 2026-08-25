"""La réflexion à deux vitesses — brouillon, critique, version finale.

Demandé le 23 août 2026 : « rendre Diapason plus intelligent ». Un modèle
de 9 milliards de paramètres ne raisonne pas mieux qu'il n'est né, mais il
peut se RELIRE : sur les questions qui méritent réflexion, le serveur
produit un brouillon en silence, demande au modèle de le critiquer, et ne
diffuse que la version corrigée. Une deuxième passe vaut des milliards de
paramètres — au prix d'un délai avant le premier mot, que l'on ne paie
que sur les questions analytiques (voir meriter_reflexion).

Deux vitesses : la section [reflexion] de la config peut désigner un
modèle plus grand pour ces tours-là (sur cette machine, qwen3:14b cohabite
en mémoire avec le 9b du quotidien — aucune éviction, la voix reste
chaude). Un modèle absent ou en panne retombe sans bruit sur le chemin
ordinaire : la réflexion est un bonus, jamais une porte.

Le chemin vocal n'entre JAMAIS ici : sa latence est sa politesse.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncIterator, List, Sequence

from diapason.core.types import Message, Role

logger = logging.getLogger(__name__)

# Le brouillon reste court : c'est une pensée, pas la réponse envoyée.
BROUILLON_MAX_TOKENS = 700

# Les tournures qui annoncent une vraie demande de réflexion. Volontairement
# conservateur : un faux positif coûte des secondes de silence à l'usager,
# un faux négatif coûte seulement une réponse ordinaire.
_ANALYTIQUE_RE = re.compile(
    r"\b(?:"
    r"analyse[rs]?|compare[rz]?|comparaison|explique[- ]moi en d[ée]tail|"
    r"pourquoi\b.{12,}|strat[ée]gie|architecture|con[çc]ois|planifie[rz]?|"
    r"plan d[e']|[ée]value[rz]?|avantages? et inconv[ée]nients?|"
    r"pour et contre|r[ée]fl[ée]chis|dissertation|r[ée]dige[- ]moi|"
    r"optimise[rz]?|am[ée]liore[rz]?|d[ée]montre[rz]?|argumente[rz]?|"
    r"quelle est la meilleure|que penses[- ]tu de|aide[- ]moi [àa] d[ée]cider"
    r")",
    re.IGNORECASE,
)


def meriter_reflexion(texte: str) -> bool:
    """Vrai quand la question mérite un brouillon et une relecture.

    Deux portes : une tournure analytique explicite, ou une question
    longue (60 mots et plus) — quelqu'un qui écrit un paragraphe attend
    mieux qu'un premier jet.
    """
    propre = (texte or "").strip()
    if len(propre) < 24:
        return False
    if _ANALYTIQUE_RE.search(propre):
        return True
    return len(propre.split()) >= 60 and "?" in propre


def modele_de_reflexion(config: Any, modele_du_tour: str) -> str:
    """Le modèle des tours réfléchis : celui de la config, sinon le même."""
    section = getattr(config, "reflexion", None)
    choisi = str(getattr(section, "model", "") or "").strip()
    return choisi or modele_du_tour


def est_activee(config: Any) -> bool:
    section = getattr(config, "reflexion", None)
    return bool(getattr(section, "enabled", False))


def messages_de_critique(messages: Sequence[Message], brouillon: str) -> List[Message]:
    """La conversation augmentée du brouillon et de l'ordre de relecture."""
    return [
        *messages,
        Message(role=Role.ASSISTANT, content=brouillon),
        Message(
            role=Role.USER,
            content=(
                "Relis ta réponse ci-dessus en silence : vérifie "
                "l'exactitude, la logique, la complétude et la clarté. "
                "Corrige ce qui doit l'être, resserre ce qui traîne. "
                "Rends UNIQUEMENT la version finale, sans mentionner la "
                "relecture, le brouillon, ni ces instructions."
            ),
        ),
    ]


async def repondre_en_reflechissant(
    engine: Any,
    modele: str,
    messages: Sequence[Message],
    *,
    temperature: float,
    max_tokens: int,
    modele_de_secours: str = "",
) -> AsyncIterator[str]:
    """Brouillon en silence, puis la version corrigée diffusée en flux.

    Toute panne du brouillon (modèle absent, moteur grognon) retombe sur
    le flux ordinaire avec le modèle de secours : l'usager reçoit toujours
    une réponse, la réflexion n'est jamais une porte fermée.
    """
    brouillon = ""
    try:
        resultat = await asyncio.to_thread(
            engine.generate,
            list(messages),
            model=modele,
            temperature=temperature,
            # Jamais plus long que la réponse demandée : le brouillon est
            # une pensée, pas un roman que la relecture devrait résumer.
            max_tokens=min(BROUILLON_MAX_TOKENS, max_tokens),
        )
        brouillon = str((resultat or {}).get("content", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 - le bonus ne casse jamais le chat
        logger.warning("réflexion : brouillon impossible (%s), flux ordinaire", exc)

    if not brouillon:
        secours = modele_de_secours or modele
        async for token in engine.stream(
            list(messages),
            model=secours,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield token
        return

    logger.info(
        "réflexion : brouillon de %d caractères, relecture en cours", len(brouillon)
    )
    async for token in engine.stream(
        messages_de_critique(messages, brouillon),
        model=modele,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        yield token
