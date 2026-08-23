"""Boucle d'outils pour le chat en flux — ce qui manquait entre le modèle et les outils.

Constaté le 22 août 2026. Le chat du bureau appelle ``/v1/chat/completions``
avec ``stream: true`` et sans ``tools``. Or ``routes.py`` routait ce cas vers
``_handle_stream``, qui parle au moteur en direct : l'agent était contourné, et
avec lui les 98 outils enregistrés. Diapason ne pouvait donc ni lire l'agenda,
ni lister une tâche Succès, ni regarder l'écran — il pouvait seulement en parler.

Le pont ``stream_bridge.AgentStreamBridge`` avait été écrit pour ça, mais il
n'a jamais eu d'appelant, il n'a aucun test, et il attend la fin de
``agent.run()`` avant d'émettre : il rendrait les outils au prix du flux réel.
Ce module prend l'autre chemin. Il appelle ``engine.stream_full(tools=...)``,
laisse passer chaque token dès son arrivée, et n'interrompt le flux que le
temps d'exécuter un outil réclamé par le modèle.

Deux garde-fous valent d'être dits, parce qu'ils sont la raison d'être du
module autant que la boucle :

- Les outils passent par ``ToolExecutor``, jamais en direct. C'est lui qui
  porte la politique de capacités, le garde-frontière et la confirmation des
  actions sensibles. Sans ``confirm_callback``, un outil marqué
  ``requires_confirmation`` échoue au lieu de s'exécuter — fail-closed.
- Le dernier tour se fait TOUJOURS sans outils. Un modèle 9b qui boucle sur
  un appel produirait sinon un silence : l'utilisateur mérite une phrase.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Iterable, Sequence

from diapason.core.types import Message, Role, ToolCall

logger = logging.getLogger("diapason.server")

# Au-delà, on cesse de proposer des outils au modèle et on lui demande sa
# réponse. Trois suffisent au quotidien (lire l'heure, lire l'agenda, répondre)
# et bornent le temps qu'une question peut coûter.
DEFAULT_MAX_TOOL_TURNS = 3

# Un résultat d'outil très long noie le contexte d'un 9b et ralentit le tour
# suivant. On tronque en le disant, plutôt que de laisser le modèle croire
# qu'il a tout vu.
MAX_TOOL_RESULT_CHARS = 4000


def _tronquer(texte: str, limite: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(texte) <= limite:
        return texte
    return texte[:limite] + f"\n[… {len(texte) - limite} caractères de plus, tronqués]"


# Clés de métadonnées qui parlent à l'application, pas au modèle.
_META_TECHNIQUE = frozenset({"persistence", "when", "_taint"})

# Au-delà, on ne recopie pas la liste entière : on en donne le début et on dit
# combien manque, pour que le modèle sache qu'il ne voit pas tout.
_MAX_ELEMENTS_LISTE = 12


def _vide(valeur: Any) -> bool:
    """Champ sans information : "", None, [], {}.

    ``0`` et ``False`` n'en sont PAS — ``{"done": false}`` est précisément ce
    que le modèle doit lire pour répondre « il t'en reste ».
    """
    return valeur is None or valeur == "" or valeur == [] or valeur == {}


def _abreger(valeur: Any) -> Any:
    """Raccourcit les listes en DISANT ce qui manque, et jette les champs vides.

    Tronquer en silence est pire que tronquer : le modèle répondrait « tu as
    douze tâches » en croyant les avoir toutes vues. Les champs vides, eux, ne
    coûtent que du contexte — une tâche Succès en traîne une quinzaine.
    """
    if isinstance(valeur, list):
        if len(valeur) <= _MAX_ELEMENTS_LISTE:
            return [_abreger(v) for v in valeur]
        gardes = [_abreger(v) for v in valeur[:_MAX_ELEMENTS_LISTE]]
        gardes.append(
            f"[… et {len(valeur) - _MAX_ELEMENTS_LISTE} de plus, non montrés]"
        )
        return gardes
    if isinstance(valeur, dict):
        return {k: _abreger(v) for k, v in valeur.items() if not _vide(v)}
    return valeur


def observation(resultat: Any) -> str:
    """Ce que le MODÈLE lit d'un résultat d'outil.

    Le ``content`` d'un outil est écrit pour une oreille : « 85 tâche(s)
    trouvée(s). » se dit bien à voix haute, et ne dit rien à un modèle à qui on
    demande LESQUELLES. Les données, elles, vivent dans ``metadata`` — que le
    modèle ne recevait pas. C'est ce qui rendait les outils Succès inutiles
    même une fois branchés : l'assistant appelait le bon outil, obtenait les
    quatre-vingt-cinq tâches, et n'en voyait que le nombre.

    On ne corrige PAS le ``content`` des outils : le chemin vocal le prononce
    tel quel, et « 85 tâches trouvées » y est la bonne phrase. C'est ici, au
    seul endroit qui s'adresse au modèle, que les données sont jointes.
    """
    contenu = str(getattr(resultat, "content", "") or "")
    meta = getattr(resultat, "metadata", None)
    if not isinstance(meta, dict):
        return contenu
    utile = {k: v for k, v in meta.items() if k not in _META_TECHNIQUE}
    if not utile:
        return contenu
    try:
        donnees = json.dumps(_abreger(utile), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return contenu
    if not contenu:
        return donnees
    return f"{contenu}\n\nDonnées : {donnees}"


def _signature(nom: str, arguments: str) -> str:
    """Identifie un appel pour repérer une boucle : même outil, mêmes arguments."""
    return f"{nom}({arguments})"


def _fusionner_fragments(
    accumules: dict[int, dict[str, Any]],
    fragments: Iterable[dict[str, Any]],
) -> None:
    """Recompose les tool_calls émis par morceaux, à la manière d'OpenAI.

    Ollama les envoie d'un bloc, mais les moteurs compatibles OpenAI les
    fragmentent : le nom arrive en plusieurs deltas, les arguments aussi.
    Concaténer par ``index`` est la seule lecture correcte des deux.
    """
    for frag in fragments:
        idx = frag.get("index", 0)
        entree = accumules.setdefault(
            idx,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if frag.get("id"):
            entree["id"] = frag["id"]
        fonction = frag.get("function") or {}
        if fonction.get("name"):
            entree["function"]["name"] += fonction["name"]
        if fonction.get("arguments"):
            entree["function"]["arguments"] += fonction["arguments"]


class ToolStreamEvent:
    """Ce qu'un tour produit, dans l'ordre où le client doit le recevoir."""

    __slots__ = ("kind", "data")

    def __init__(self, kind: str, data: Any) -> None:
        self.kind = kind  # "token" | "tool_start" | "tool_end"
        self.data = data

    def __repr__(self) -> str:  # pragma: no cover - confort de débogage
        return f"ToolStreamEvent({self.kind!r}, {self.data!r})"


async def stream_with_tools(
    engine: Any,
    model: str,
    messages: Sequence[Message],
    *,
    tools: Sequence[Any],
    executor: Any,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    max_tool_turns: int = DEFAULT_MAX_TOOL_TURNS,
) -> AsyncIterator[ToolStreamEvent]:
    """Diffuse la réponse du modèle en exécutant les outils qu'il réclame.

    ``tools`` sont des instances de ``BaseTool`` ; leurs specs OpenAI sont
    dérivées ici pour que l'appelant n'ait pas à connaître ce détail.
    ``executor`` est un ``ToolExecutor`` déjà porteur de sa politique de
    sécurité — ce module ne décide jamais seul qu'un appel est permis.
    """
    specs = [outil.to_openai_function() for outil in tools]
    travail: list[Message] = list(messages)
    deja_vus: set[str] = set()

    for tour in range(max_tool_turns + 1):
        # Le tour de trop se fait sans outils : on veut une phrase, pas un
        # nouvel appel qu'on n'exécuterait pas.
        dernier_tour = tour == max_tool_turns
        specs_du_tour = None if dernier_tour else specs

        morceaux: list[str] = []
        fragments: dict[int, dict[str, Any]] = {}

        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if specs_du_tour:
            kwargs["tools"] = specs_du_tour

        async for morceau in engine.stream_full(travail, **kwargs):
            if morceau.content:
                morceaux.append(morceau.content)
                yield ToolStreamEvent("token", morceau.content)
            if morceau.tool_calls:
                _fusionner_fragments(fragments, morceau.tool_calls)

        appels = [fragments[i] for i in sorted(fragments)]
        if not appels or dernier_tour:
            return

        # Le modèle veut des outils. On enregistre son intention avant les
        # résultats : sans ce message, le modèle ne reconnaît pas les réponses
        # d'outils qui suivent et rappelle le même outil en boucle.
        travail.append(
            Message(
                role=Role.ASSISTANT,
                content="".join(morceaux),
                tool_calls=[
                    ToolCall(
                        id=a.get("id") or f"call_{i}",
                        name=(a.get("function") or {}).get("name", ""),
                        arguments=(a.get("function") or {}).get("arguments") or "{}",
                    )
                    for i, a in enumerate(appels)
                ],
            )
        )

        for appel in appels:
            fonction = appel.get("function") or {}
            nom = fonction.get("name", "")
            arguments = fonction.get("arguments", "") or "{}"

            if not nom:
                continue

            signature = _signature(nom, arguments)
            if signature in deja_vus:
                # Même outil, mêmes arguments, deuxième fois : le modèle tourne
                # en rond. On le lui dit dans le fil plutôt que de refaire le
                # travail — il enchaîne alors sur une réponse.
                travail.append(
                    Message(
                        role=Role.TOOL,
                        name=nom,
                        tool_call_id=appel.get("id") or "",
                        content=(
                            "Cet appel identique a déjà été fait à ce tour. "
                            "Réponds avec ce que tu sais déjà."
                        ),
                    )
                )
                continue
            deja_vus.add(signature)

            yield ToolStreamEvent("tool_start", {"tool": nom, "arguments": arguments})

            debut = time.time()
            try:
                resultat = await asyncio.to_thread(
                    executor.execute,
                    ToolCall(id=appel.get("id") or "", name=nom, arguments=arguments),
                )
                contenu = observation(resultat)
                succes = bool(getattr(resultat, "success", False))
            except Exception as exc:  # noqa: BLE001 - un outil cassé n'arrête pas le tour
                logger.warning("outil %s en échec : %s", nom, exc, exc_info=True)
                contenu = f"L'outil a échoué : {exc}"
                succes = False
            latence = time.time() - debut

            contenu = _tronquer(contenu)

            yield ToolStreamEvent(
                "tool_end",
                {
                    "tool": nom,
                    "success": succes,
                    "latency": round(latence, 3),
                    "result": contenu[:1000],
                },
            )

            travail.append(
                Message(
                    role=Role.TOOL,
                    name=nom,
                    tool_call_id=appel.get("id") or "",
                    content=contenu,
                )
            )


__all__ = [
    "DEFAULT_MAX_TOOL_TURNS",
    "MAX_TOOL_RESULT_CHARS",
    "ToolStreamEvent",
    "observation",
    "stream_with_tools",
]
