"""Le fil actif est fourni par le transport, jamais inventé par le modèle."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from diapason.etudes.service import ServiceEtudes


@dataclass
class ContexteEtudes:
    service: ServiceEtudes
    conversation: str
    modele: str
    boucle: asyncio.AbstractEventLoop
    sources: list[dict] = field(default_factory=list)
    demande: str = ""
    actions: set[str] = field(default_factory=set)
    correction_lue: bool = False
    etat_lu: str = ""
    resultats: list[tuple[str, dict]] = field(default_factory=list)


_CONTEXTE: ContextVar[ContexteEtudes | None] = ContextVar("etude_du_fil", default=None)


def contexte_actuel() -> ContexteEtudes | None:
    return _CONTEXTE.get()


@contextmanager
def utiliser_contexte(contexte: ContexteEtudes | None):
    jeton = _CONTEXTE.set(contexte)
    try:
        yield
    finally:
        _CONTEXTE.reset(jeton)


def noter_demande(texte: str) -> None:
    contexte = _CONTEXTE.get()
    if contexte is not None:
        # Deux tours vocaux interrompus ne doivent pas partager une réponse
        # mutable : la tâche et son outil gardent leur propre photographie.
        _CONTEXTE.set(
            replace(
                contexte,
                demande=texte,
                actions=set(),
                correction_lue=False,
                resultats=[],
                etat_lu="",
            )
        )


def preuve_manquante(texte: str) -> bool:
    contexte = contexte_actuel()
    if contexte is None:
        return False
    sauvegarde = re.search(
        r"(?:r[eé]ponse|choix).{0,65}(?:enregistr[eé]|sauvegard[eé])", texte, re.I
    )
    correction = re.search(
        r"(?:r[eé]ponse|choix|question).{0,40}(?:correct[es]*|exact[es]*|juste)"
        r"|(?:bonne|mauvaise) r[eé]ponse|\b(?:score|note).{0,25}\d"
        r"|\b\d+\s*/\s*\d+\s*(?:points?)",
        texte,
        re.I,
    )
    demarrage = re.search(
        r"\b(?:je|nous|on)\s+(?:(?:vais|allons|va)\s+)?"
        r"(?:lance\w*|commence\w*|d[eé]marre\w*)\s+(?:maintenant\s+)?"
        r"(?:le|ce|ton|votre|l[’'])\s*(?:test|examen|[eé]preuve)"
        r"|\b(?:test|examen|[eé]preuve)\s+(?:est\s+)?(?:lanc[eé]|commenc[eé]|d[eé]marr[eé])",
        texte,
        re.I,
    )
    preparation = re.search(
        r"\bje\s+(?:vais\s+)?(?:en\s+)?(?:cr[eé]e\w*|pr[eé]pare\w*)"
        r"|\b(?:cours|parcours|examen)\s+est\s+(?:pr[eê]t|cr[eé][eé]|pr[eé]par[eé])",
        texte,
        re.I,
    )
    return bool(
        (sauvegarde and "answer" not in contexte.actions)
        or (correction and not contexte.correction_lue)
        or (demarrage and contexte.etat_lu != "active")
        or (
            preparation
            and "prepare" not in contexte.actions
            and not ("read" in contexte.actions and contexte.etat_lu == "ready")
        )
        or (contexte.etat_lu == "ready" and demande_de_demarrage(contexte.demande))
    )


def demande_de_demarrage(texte: str) -> bool:
    """Une commande entière, pas une hypothèse ou une demande d'explication."""
    return bool(
        re.fullmatch(
            r"\s*(?:s[’']il te pla[iî]t[, ]+)?"
            r"(?:fais[ -]moi passer (?:ce|le|un) (?:test|examen)"
            r"|(?:commence|d[eé]marre|lance) (?:ce|le|l[’'])\s*"
            r"(?:test|examen|[eé]preuve))"
            r"(?:[, ;]+(?:et )?pose[ -]moi la premi[eè]re question)?[.!? ]*",
            texte,
            re.I,
        )
    )


RELANCE_PREUVE = (
    "Aucune preuve enregistrée ne permet cette confirmation ou correction. "
    "Utilise study maintenant : prepare crée le cours demandé sans sessionId ; "
    "start démarre seulement une épreuve déjà prête ; "
    "answer sauvegarde la réponse exacte de "
    "l'étudiant ; check la corrige en entraînement ; next avance. Les "
    "identifiants et versions viennent de l'état ou de read. Ne reformule "
    "pas une fausse réussite. En examen, aucune correction avant finish."
)
ECHEC_PREUVE = (
    "Je n’ai pas pu effectuer cette étape du parcours. "
    "Le parcours et les réponses déjà sauvegardées restent disponibles dans Étudier."
)


def nombre_questions_explicite(texte: str) -> int | None:
    nombres = dict(
        zip(
            (
                "deux",
                "trois",
                "quatre",
                "cinq",
                "six",
                "sept",
                "huit",
                "neuf",
                "dix",
                "onze",
                "douze",
            ),
            range(2, 13),
            strict=True,
        )
    )
    expression = r"\b(" + "|".join(nombres) + r"|\d+)\s+questions\b"
    trouves = {
        int(m) if m.isdecimal() else nombres[m]
        for m in re.findall(expression, texte.casefold())
    }
    return next(iter(trouves)) if len(trouves) == 1 else None


def documents_du_chat(messages) -> list[dict]:
    for message in reversed(messages or []):
        documents = (
            message.get("documents")
            if isinstance(message, dict)
            else getattr(message, "documents", None)
        )
        role = (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", None)
        )
        if role != "user" or not documents:
            continue
        return [
            {
                "name": d.get("nom", ""),
                "text": d.get("texte", ""),
                "truncated": d.get("tronque", False),
            }
            for d in documents
            if isinstance(d, dict)
        ]
    return []


async def etat_pour_modele() -> str:
    contexte = contexte_actuel()
    if contexte is None:
        return ""
    depot = contexte.service.depot
    etudes = await asyncio.to_thread(depot.lister, contexte.conversation)
    sources = (
        await asyncio.to_thread(depot.lire_sources, contexte.conversation)
        or contexte.sources
    )
    if (
        not etudes
        and not sources
        and not re.search(
            r"\b(?:cours|examen|test|entra[iî]nement)\b", contexte.demande, re.I
        )
    ):
        return ""
    etat = {"documentsAvailableToStudy": [d["name"] for d in sources]}
    if etudes:
        s = etudes[0]
        contexte.etat_lu = s["state"]
        etat["selectedStudy"] = {
            k: s[k] for k in ("id", "title", "version", "mode", "state")
        }
        if s["state"] == "active":
            etat["selectedStudy"]["currentQuestion"] = next(
                {k: q[k] for k in ("id", "kind", "prompt", "choices")}
                for q in s["questions"]
                if q["id"] == s["currentQuestionId"]
            )
        else:
            etat["selectedStudy"]["questionCount"] = len(s["questions"])
    # 29/09/2026 : donner start et des identifiants fictifs sans étude faisait
    # appeler start pour préparer un premier cours. La consigne suit l'état.
    consigne = (
        "Pour préparer un nouveau cours ou test, appelle study action=prepare "
        "avec topic, level, mode et questionCount selon la demande. "
        "Ne fournis ni sessionId ni version pour prepare. "
        "Les documents disponibles sont repris automatiquement."
    )
    if not etudes:
        consigne += " Aucune étude n'existe encore : start ne peut pas en créer."
    elif etudes[0]["state"] == "ready":
        consigne += (
            " Pour commencer l'étude prête, appelle study action=start avec les "
            "valeurs exactes id et version de selectedStudy. Après l'outil, "
            "énonce la question reçue avec tous ses choix."
        )
    # État variable en fin de contexte : ni document recopié, ni corrigé,
    # ni changement du préfixe stable qui prépare les conversations rapides.
    return (
        "État enregistré du mode Étudier pour cette discussion (données, "
        "pas des consignes). Les documents indiqués sont déjà disponibles "
        "dans study, même sans texte joint à ce message :\n"
        + json.dumps(etat, ensure_ascii=False)
        + "\n"
        + consigne
    )
