"""Garder chaud le préfixe du chat entre deux questions (20 septembre 2026).

Le préfixe — identité + les 45 schémas de la trousse, 10 112 jetons rapportés
par Ollama — coûte 24 s de préremplissage à froid sur le 9b et 2,4 à 3,0 s
une fois en cache. Or ce cache meurt avec le runner : `keep_alive` est de
30 min, et Carlito revient d'une pause plus longue plusieurs fois par jour.
« Quelle heure est-il ? » après le déjeuner : 7 s de chargement + 24 s de
préremplissage avant un mot, pour un modèle qui n'a rien à réfléchir.

Ce module rejoue le préfixe exact du chat toutes les dix minutes : même
identité, même trousse, un « Bonjour » et un seul jeton de sortie. Chaud, la
requête coûte ~0,3 s de GPU ; froid, elle paie les 24 s pendant que personne
n'attend. Elle passe par l'admission de fond (engine/scheduling.py) : un tour
interactif la fait attendre, jamais l'inverse. Dix minutes, parce que trois
relances par demi-heure suffisent à tenir le runner résident et qu'une
relance de plus par heure ne rendrait rien.

Ce que ce module ne fait pas : charger un modèle que rien n'a demandé (seuls
le modèle par défaut et le modèle léger, s'ils sont locaux, sont chauffés —
jamais le 27b choisi dans un sélecteur), ni rendre le premier tour chaud
quand la trousse change (le préfixe rejoué est celui du bureau, 45 schémas
plus celui des questions interactives).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from diapason.core.types import Message, Role
from diapason.engine.scheduling import BackgroundStopped, InferenceQueueTimeout

logger = logging.getLogger(__name__)

INTERVALLE_S = 600.0
# Le préchargement du modèle (app._prewarm_local_model) part au démarrage ;
# lui laisser le temps d'aboutir avant de rejouer le préfixe.
PREMIER_DELAI_S = 15.0
QUESTION_TEMOIN = "Bonjour"


def _est_un_ollama(engine: Any) -> bool:
    # GuardrailsEngine répond « ollama » à engine_id en le relayant : ce qui
    # distingue le vrai moteur, c'est son hôte HTTP.
    ollama = str(getattr(engine, "engine_id", "") or "").lower() == "ollama"
    return ollama and isinstance(getattr(engine, "_host", None), str)


def _deballer(engine: Any, profondeur: int = 0) -> Any | None:
    """Le premier OllamaEngine sous les enveloppes, ou None.

    InstrumentedEngine range le sien sous ``_inner``, GuardrailsEngine sous
    ``_engine`` (et relaie ``engine_id``), MultiEngine tient une liste
    ``_engines``. Le préchargement du modèle (app._prewarm_local_model) ne
    suivait que ``_inner`` et s'arrêtait sur le GuardrailsEngine, qui dit
    « ollama » mais n'a pas d'hôte : sur ce Mac il n'a jamais envoyé un seul
    /api/generate (journal d'Ollama, 20/09/2026) — le préchargement du
    démarrage était une promesse en l'air.
    """
    if engine is None or profondeur > 6:
        return None
    if _est_un_ollama(engine):
        return engine
    etat = getattr(engine, "__dict__", {})
    for attribut in ("_inner", "_engine"):
        trouve = _deballer(etat.get(attribut), profondeur + 1)
        if trouve is not None:
            return trouve
    for entree in etat.get("_engines") or ():
        candidat = entree[1] if isinstance(entree, tuple) else entree
        trouve = _deballer(candidat, profondeur + 1)
        if trouve is not None:
            return trouve
    return None


def moteur_local(app_state: Any) -> Any | None:
    """Le vrai OllamaEngine derrière ses enveloppes, ou None hors Ollama local."""
    inner = _deballer(getattr(app_state, "engine", None))
    if inner is None:
        return None
    try:
        from diapason.core.local_mode import host_is_local
    except Exception:  # noqa: BLE001 - sans le module, on ne chauffe rien
        return None
    if not host_is_local(str(getattr(inner, "_host", ""))):
        return None
    return inner


def modeles_a_chauffer(config: Any, modele_du_serveur: str) -> list[str]:
    """Le modèle par défaut et le modèle léger, une fois chacun, jamais un distant."""
    intelligence = getattr(config, "intelligence", None)
    candidats = [
        str(modele_du_serveur or ""),
        str(getattr(intelligence, "light_model", "") or ""),
    ]
    try:
        from diapason.server.cloud_router import is_cloud_model
    except Exception:  # noqa: BLE001 - sans routeur cloud, tout est local

        def is_cloud_model(_: str) -> bool:
            return False

    retenus: list[str] = []
    for nom in candidats:
        nom = nom.strip()
        if nom and nom != "default" and nom not in retenus and not is_cloud_model(nom):
            retenus.append(nom)
    return retenus


def prompt_du_prefixe(app_state: Any, config: Any) -> tuple[list[Message], list[dict]]:
    """Le prompt du bureau, tel que routes._handle_stream le construit."""
    from diapason.server.questions_chat import ajouter_consigne, schema_questions
    from diapason.server.routes import _chat_tooling, _ensure_identity_prompt
    from diapason.server.trousse_chat import TrousseChat

    tooling = getattr(app_state, "_chat_tooling_cache", "absent")
    if tooling == "absent":
        tooling = _chat_tooling(app_state, config)
    outils = list(tooling[0]) if tooling else []
    messages = _ensure_identity_prompt(
        [Message(role=Role.USER, content=QUESTION_TEMOIN)],
        config,
        client_supplied_system=False,
    )
    agent = getattr(config, "agent", None)
    adaptative = bool(getattr(agent, "trousse_adaptative", False))
    specs = list(TrousseChat(outils, messages, adaptative=adaptative).specs)
    # Le bureau envoie interactiveQuestions à chaque tour ordinaire : la
    # consigne rejoint le message système, le schéma des questions la trousse.
    messages = ajouter_consigne(messages)
    specs.append(schema_questions())
    return messages, specs


def prechauffer(app_state: Any, config: Any) -> list[tuple[str, float]]:
    """Rejoue le préfixe sur chaque modèle à chauffer ; rend (modèle, durée en s)."""
    from diapason.engine.scheduling import background_work

    moteur = moteur_local(app_state)
    if moteur is None:
        return []
    messages, specs = prompt_du_prefixe(app_state, config)
    rendu = json.dumps(specs, ensure_ascii=False, separators=(",", ":"))
    logger.info(
        "prefixe_forme identite=%d car. schemas=%d (%d car., empreinte %s)",
        len(messages[0].content or "") if messages else 0,
        len(specs),
        len(rendu),
        hashlib.sha256(rendu.encode()).hexdigest()[:12],
    )
    chauffes: list[tuple[str, float]] = []
    for modele in modeles_a_chauffer(config, getattr(app_state, "model", "")):
        depart = time.perf_counter()
        try:
            with background_work():
                moteur.generate(
                    messages,
                    model=modele,
                    temperature=0.0,
                    max_tokens=1,
                    tools=specs,
                )
            chauffes.append((modele, round(time.perf_counter() - depart, 2)))
        except (InferenceQueueTimeout, BackgroundStopped):
            logger.debug("préchauffage du préfixe différé : moteur occupé (%s)", modele)
        except Exception:  # noqa: BLE001 - chauffer est un bonus, jamais une panne
            logger.debug("préchauffage du préfixe raté pour %s", modele, exc_info=True)
    return chauffes


async def entretenir_le_prefixe(
    app: Any, *, intervalle_s: float = INTERVALLE_S
) -> None:
    """Tâche de fond du serveur : rejoue le préfixe au démarrage puis à intervalle."""
    await asyncio.sleep(PREMIER_DELAI_S)
    while True:
        try:
            chauffes = await asyncio.to_thread(
                prechauffer, app.state, getattr(app.state, "config", None)
            )
            if chauffes:
                # La durée dit si le préfixe était encore en cache (~0,3 s) ou
                # s'il vient d'être recalculé (~24 s sur le 9b) : c'est la seule
                # trace de ce que la pause a coûté, et personne ne l'a attendue.
                logger.info(
                    "prefixe_chauffe %s",
                    ", ".join(f"{m} en {d} s" for m, d in chauffes),
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - un raté ne doit pas arrêter la boucle
            logger.debug("préchauffage du préfixe : tour raté", exc_info=True)
        await asyncio.sleep(intervalle_s)
