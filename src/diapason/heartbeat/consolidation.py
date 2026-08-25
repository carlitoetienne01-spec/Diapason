"""La consolidation nocturne — le jour se dépose en mémoire durable.

Demandé le 23 août 2026 : « la consolidation nocturne de mémoire ». Le
service de mémoire extrait déjà des faits AU FIL des échanges, mais il est
myope : il voit chaque tour isolément. La nuit, quand le créneau Ollama ne
sert personne, cette passe relit LA JOURNÉE ENTIÈRE (traces.db, la seule
source horodatée fiable), en tire des faits durables — préférences,
décisions, personnes, projets — et un résumé du jour.

Les faits empruntent le MÊME circuit que la mémoire automatique
(journal memory_facts.jsonl qui dédoublonne + index memory.db relu à
chaque chat — voir SearchableFactStore) : rien de nouveau à relire, tout
ce que la nuit dépose est retrouvable au matin. Le résumé, lui, s'écrit
dans ~/.diapason/journal.md — la mémoire d'« il s'est passé quoi jeudi ? ».

Tout est injectable (générateur, magasins, chemins) : les tests ne
touchent ni Ollama ni ~/.diapason, la convention de ce dépôt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from diapason.core.types import Message, Role

logger = logging.getLogger(__name__)

# Une journée bavarde ne doit pas noyer le modèle : on garde les derniers
# échanges, tronqués — l'essentiel d'une journée tient là-dedans.
ECHANGES_MAX = 60
QUESTION_MAX = 500
REPONSE_MAX = 700
FAITS_MAX = 12


@dataclass(frozen=True)
class Echange:
    question: str
    reponse: str
    quand: datetime


@dataclass(frozen=True)
class Consolidation:
    """Ce que la nuit a déposé."""

    faits: List[str] = field(default_factory=list)
    faits_ajoutes: int = 0
    resume: str = ""
    echanges_lus: int = 0

    @property
    def vide(self) -> bool:
        return self.echanges_lus == 0


def est_trace_de_banc(model: str) -> bool:
    """Vrai pour le trafic de banc d'essai — jamais de la vie vécue.

    Constaté à la première consolidation réelle (23 août 2026) : 293 traces
    « who are you? » → « Hello world » au modèle « test-model » noyaient les
    vraies conversations, et le journal du jour résumait fidèlement... le
    banc. La mémoire n'apprend que du vécu.
    """
    return "test" in (model or "").lower()


def collecter_le_jour(chemin_traces: str | Path, jour: date) -> List[Echange]:
    """Les échanges du jour, du matin au soir, bornés et tronqués."""
    from diapason.traces.store import TraceStore

    minuit = datetime.combine(jour, dtime.min)
    magasin = TraceStore(str(chemin_traces))
    traces = magasin.list_traces(
        since=minuit.timestamp(),
        until=(minuit + timedelta(days=1)).timestamp(),
        limit=500,
    )
    echanges = [
        Echange(
            question=t.query.strip()[:QUESTION_MAX],
            reponse=t.result.strip()[:REPONSE_MAX],
            quand=datetime.fromtimestamp(t.started_at),
        )
        for t in traces
        if t.query.strip() and t.result.strip() and not est_trace_de_banc(t.model)
    ]
    # list_traces rend du plus récent au plus ancien ; la journée se lit
    # dans l'ordre du vécu, et si elle déborde, ce sont les DERNIERS
    # échanges qui comptent — la fin de journée dit où l'on en est.
    echanges.sort(key=lambda e: e.quand)
    return echanges[-ECHANGES_MAX:]


def composer_messages(echanges: Sequence[Echange], jour: date) -> List[Message]:
    """La journée transcrite, et l'ordre d'en tirer la substance."""
    lignes = []
    for e in echanges:
        lignes.append(f"— {e.quand.strftime('%H:%M')}")
        lignes.append(f"Lui : {e.question}")
        lignes.append(f"Toi : {e.reponse}")
    transcription = "\n".join(lignes)
    consigne = (
        "Tu es la mémoire nocturne d'un assistant personnel. Voici les "
        f"conversations du {jour.isoformat()} entre l'utilisateur (Lui) et "
        "l'assistant (Toi). Tires-en :\n"
        f"1. `faits` : au plus {FAITS_MAX} faits DURABLES sur l'utilisateur, "
        "sa vie, ses projets — préférences, décisions prises, personnes, "
        "échéances. Chaque fait est une phrase française autonome à "
        "l'indicatif, compréhensible sans contexte. IGNORE l'éphémère "
        "(salutations, essais, questions techniques ponctuelles).\n"
        "2. `resume` : la journée en 3 à 6 phrases — ce qui a été fait, "
        "décidé, avancé.\n"
        "Réponds UNIQUEMENT avec un objet JSON : "
        '{"faits": ["…"], "resume": "…"}. Rien d\'autre.'
    )
    return [
        Message(role=Role.SYSTEM, content=consigne),
        Message(role=Role.USER, content=transcription),
    ]


def interpreter(brut: str) -> tuple[List[str], str]:
    """Le JSON du modèle, extrait avec indulgence — jamais d'exception."""
    texte = str(brut or "")
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin <= debut:
        return [], ""
    try:
        donnees = json.loads(texte[debut : fin + 1])
    except (ValueError, TypeError):
        return [], ""
    faits_bruts = donnees.get("faits", [])
    faits = [
        " ".join(str(f).split())
        for f in faits_bruts
        if isinstance(f, str) and str(f).strip()
    ][:FAITS_MAX]
    resume = str(donnees.get("resume", "") or "").strip()
    return faits, resume


def _generer_par_defaut() -> Callable[[List[Message]], str]:
    """Ollama, avec le modèle de réflexion s'il y en a un — la nuit, le
    créneau est libre, autant confier la synthèse au plus fin."""
    from diapason.core.config import load_config
    from diapason.engine.ollama import OllamaEngine

    config = load_config()
    modele = (
        str(getattr(config.reflexion, "model", "") or "").strip()
        or str(getattr(config.intelligence, "default_model", "") or "").strip()
        or "qwen3.5:9b"
    )
    engine = OllamaEngine()

    def generer(messages: List[Message]) -> str:
        resultat = engine.generate(
            messages, model=modele, temperature=0.2, max_tokens=900
        )
        return str((resultat or {}).get("content", "") or "")

    return generer


def _magasin_par_defaut() -> Any:
    """Le circuit de la mémoire automatique : journal + index de recherche."""
    from diapason.core.config import load_config
    from diapason.memory.store import SearchableFactStore, create_fact_store

    config = load_config()
    mem = config.memory
    journal = create_fact_store(
        getattr(mem, "backend", "local"),
        path=getattr(mem, "facts_path", None),
        max_facts=int(getattr(mem, "max_facts", 1000)),
    )
    try:
        from diapason.tools.storage.sqlite import SQLiteMemory

        return SearchableFactStore(journal, SQLiteMemory(getattr(mem, "db_path", "")))
    except Exception:  # noqa: BLE001 - le journal suffit, l'index est un bonus
        logger.warning("consolidation : index de recherche indisponible", exc_info=True)
        return journal


def journaliser_le_jour(chemin: str | Path, jour: date, resume: str) -> None:
    """Le résumé rejoint journal.md — la mémoire relisible des journées."""
    fichier = Path(chemin)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    with fichier.open("a", encoding="utf-8") as f:
        f.write(f"\n## {jour.isoformat()}\n\n{resume.strip()}\n")


def consolider_le_jour(
    jour: Optional[date] = None,
    *,
    chemin_traces: Optional[str | Path] = None,
    generer: Optional[Callable[[List[Message]], str]] = None,
    magasin_faits: Any = None,
    chemin_journal: Optional[str | Path] = None,
) -> Consolidation:
    """Relit la journée, dépose les faits, écrit le résumé.

    Par défaut : la journée d'HIER (la passe tourne à 03:30, elle regarde
    le jour qui vient de se clore), traces.db et journal.md de la config.
    """
    from diapason.core.config import get_config_dir, load_config

    if jour is None:
        jour = date.today() - timedelta(days=1)
    if chemin_traces is None:
        chemin_traces = load_config().traces.db_path
    if chemin_journal is None:
        chemin_journal = get_config_dir() / "journal.md"

    echanges = collecter_le_jour(chemin_traces, jour)
    if not echanges:
        logger.info("consolidation : aucune conversation le %s", jour.isoformat())
        return Consolidation()

    if generer is None:
        generer = _generer_par_defaut()
    brut = generer(composer_messages(echanges, jour))
    faits, resume = interpreter(brut)
    if not faits and not resume:
        logger.warning("consolidation : le modèle n'a rien rendu d'exploitable")
        return Consolidation(echanges_lus=len(echanges))

    if magasin_faits is None:
        magasin_faits = _magasin_par_defaut()
    ajoutes = 0
    for fait in faits:
        try:
            if magasin_faits.add(fait, source="consolidation"):
                ajoutes += 1
        except Exception:  # noqa: BLE001 - un fait perdu ne perd pas la nuit
            logger.warning("consolidation : fait non déposé : %.80s", fait)

    if resume:
        journaliser_le_jour(chemin_journal, jour, resume)

    logger.info(
        "consolidation du %s : %d échange(s) relus, %d fait(s) nouveaux, résumé %s",
        jour.isoformat(),
        len(echanges),
        ajoutes,
        "écrit" if resume else "absent",
    )
    return Consolidation(
        faits=faits,
        faits_ajoutes=ajoutes,
        resume=resume,
        echanges_lus=len(echanges),
    )
