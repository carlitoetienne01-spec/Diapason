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
from contextlib import aclosing
from typing import Any, AsyncIterator, Iterable, Sequence

from diapason.core.promesse import est_une_promesse_sans_acte
from diapason.core.types import Message, Role, ToolCall
from diapason.engine._base import EngineToolsUnsupportedError
from diapason.server.actualite import (
    AVERTISSEMENT,
    AVERTISSEMENT_RECHERCHE,
    AVEU,
    CONSIGNE_AUTRE_REQUETE,
    CONSIGNE_DEMANDEE,
    CONSIGNE_FERME,
    CONSIGNE_PAGE_LUE,
    CONSIGNE_PAGE_LUE_SANS_OUTIL,
    completer_arguments,
    consigne_actualite,
    desaccord_sur_le_titulaire,
    elements_hors_sources,
    est_une_demande_de_verification,
    est_une_non_reponse,
    niveau_de_verification,
    note_avant_redaction,
    page_de_reference,
    question_a_verifier,
    question_courante_d_actualite,
    question_de_titulaire,
    question_personnelle,
    recherche_concluante,
    renumeroter,
    sources_prometteuses,
    sous_l_url_demandee,
)
from diapason.server.questions_chat import (
    CADRAGE_MAX_JETONS,
    POSER_QUESTIONS,
    RAPPEL,
    ajouter_consigne,
    cadrer_sans_outils,
    consigne_sans_outils,
    est_un_cadrage_textuel,
    schema_questions,
    texte_questions,
    valider_questions,
)
from diapason.server.reponses_longues import prolonger_flux
from diapason.server.sources_officielles import (
    PageOfficielle,
    entete_officielle,
    page_officielle,
    source_officielle,
)
from diapason.server.suite import avec_rappel
from diapason.server.trousse_chat import MAX_CHARGEMENTS, TrousseChat

logger = logging.getLogger("diapason.server")

# Au-delà, on cesse de proposer des outils au modèle et on lui demande sa
# réponse. Trois suffisent au quotidien (lire l'heure, lire l'agenda, répondre)
# et bornent le temps qu'une question peut coûter.
DEFAULT_MAX_TOOL_TURNS = 3

# Un résultat d'outil très long noie le contexte d'un 9b et ralentit le tour
# suivant. On tronque en le disant, plutôt que de laisser le modèle croire
# qu'il a tout vu.
MAX_TOOL_RESULT_CHARS = 4000
# Sur une non-réponse, le code lit au plus deux sources prometteuses avant
# de renvoyer le modèle chercher autrement (21/09/2026).
LECTURES_SUR_NON_REPONSE = 2

# Plafond de température des tours qui PROPOSENT des outils.
#
# Décider d'appeler un outil n'est pas un acte créatif, et le hasard s'y voit.
# Mesuré sur qwen3.5:9b, « qu'est-ce que j'ai comme tâches aujourd'hui ? »,
# dix essais par palier :
#
#     0,7 →  9/10 appels        0,3 → 10/10
#     0,1 → 10/10               0,0 → 10/10
#
# L'essai manquant à 0,7 n'était pas un refus mais pire : le modèle répondait
# « Je vais regarder tes tâches pour aujourd'hui. » et s'arrêtait là. Une
# promesse sans suite, que rien ne signale comme un échec — l'utilisateur
# attend un résultat qui ne viendra pas.
#
# Le plafond ne s'applique QU'AUX tours porteurs d'outils. Le dernier tour,
# celui qui rédige sans outils, garde la température demandée par l'appelant :
# c'est là que la prose se joue.
TOOL_TURN_TEMPERATURE = 0.3


def _tronquer(texte: str, limite: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(texte) <= limite:
        return texte
    return texte[:limite] + f"\n[… {len(texte) - limite} caractères de plus, tronqués]"


# Clés de métadonnées qui parlent à l'application, pas au modèle.
# « sources » : la liste structurée des pastilles [N], que le texte porte déjà.
_META_TECHNIQUE = frozenset({"persistence", "when", "_taint", "sources"})

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


# La renumérotation des sources vit dans actualite.py (partagée avec la voix).
_renumeroter = renumeroter


def _controle_des_sources(
    reponse: str,
    corpus: str,
    question: str,
    donnees: dict[str, Any] | None = None,
    *,
    sources: Sequence[dict[str, Any]] = (),
    recherche_tentee: bool = False,
    verification_faite: bool = False,
    controle_lexical: bool = True,
    dernier_passage: str | None = None,
) -> list[ToolStreamEvent]:
    """Le signal de fin de tour d'une question d'actualité : le niveau de
    vérification (calculé par le code, jamais déclaré par le modèle), ce que
    la réponse affirme sans source, le titulaire qu'elle nomme contre celui
    des sources, l'âge des sources.

    Un événement à part, pas un jeton : revue du 20/09 — un jeton entrait
    dans le texte copié, dans conversations.db et dans l'historique que le
    modèle relit au tour suivant. Un seul événement, toutes clés réunies :
    le client n'en garde qu'un par message. Les clés sont anglaises sur le
    fil (CLAUDE.md) ; « nonRetrouves » du 20/09 l'était en français.
    """
    signal: dict[str, Any] = dict(donnees or {})
    if corpus.strip() and controle_lexical:
        manquants = elements_hors_sources(reponse, corpus, question)
        if manquants:
            signal["notFound"] = manquants
        desaccord = desaccord_sur_le_titulaire(reponse, corpus, question)
        if desaccord:
            signal["disagreement"] = desaccord
    signal["level"] = niveau_de_verification(
        reponse, sources, verification_faite, signal, dernier_passage, question
    )
    signal["searchTried"] = bool(recherche_tentee)
    return [ToolStreamEvent("verification", signal)]


# Partagée avec la voix (actualite.sous_l_url_demandee).
_sous_l_url_demandee = sous_l_url_demandee


def _url_demandee(arguments: str) -> str:
    try:
        donnees = json.loads(arguments or "{}")
    except (ValueError, TypeError):
        return ""
    return str(donnees.get("url") or "") if isinstance(donnees, dict) else ""


async def _lire_la_page(
    executor: Any,
    url: str,
    question: str,
    deja: list[dict[str, Any]],
    officielle: PageOfficielle | None = None,
) -> AsyncIterator[tuple[ToolStreamEvent | None, str]]:
    """Lit la page de la fonction — ou la page officielle du sujet — par
    web_read, comme si le modèle l'avait demandé : les événements
    tool_start/tool_end la rendent visible dans l'interface (§5 — rien ne se
    fait en cachette), et le texte renuméroté revient pour être joint au
    résultat de la recherche. Une page officielle porte son propre en-tête
    (« source officielle · consultée le … ») : une page vivante n'a pas de
    date de publication qui compte."""
    focus = officielle.focus if officielle is not None else question
    arguments = json.dumps({"url": url, "focus": focus}, ensure_ascii=False)
    yield (
        ToolStreamEvent(
            "tool_start", {"tool": "web_read", "arguments": arguments, "auto": True}
        ),
        "",
    )
    debut = time.time()
    texte = ""
    try:
        resultat = await asyncio.to_thread(
            executor.execute,
            ToolCall(id="auto_web_read", name="web_read", arguments=arguments),
        )
        succes = bool(getattr(resultat, "success", False))
        contenu = observation(resultat)
        if succes:
            meta = getattr(resultat, "metadata", None) or {}
            texte, nouvelles = _renumeroter(
                contenu, _sous_l_url_demandee(meta.get("sources") or [], url), deja
            )
            if officielle is not None and nouvelles:
                ref = int(nouvelles[0]["ref"])
                # Le titre lu AVANT d'écraser la carte : celui de pm.gc.ca est
                # le nom du titulaire, c'est-à-dire la réponse.
                titre_lu = str(nouvelles[0].get("title") or "")
                nouvelles = [source_officielle(officielle, ref, titre_lu)]
                lignes = texte.split("\n", 1)
                texte = entete_officielle(officielle, ref, titre_lu) + (
                    "\n" + lignes[1] if len(lignes) > 1 else ""
                )
            if nouvelles:
                deja.extend(nouvelles)
                yield ToolStreamEvent("sources", list(nouvelles)), ""
    except Exception as exc:  # noqa: BLE001 - une page illisible n'arrête pas le tour
        logger.warning("lecture automatique de %s en échec : %s", url, exc)
        succes, contenu = False, f"L'outil a échoué : {exc}"
    yield (
        ToolStreamEvent(
            "tool_end",
            {
                "tool": "web_read",
                "success": succes,
                "latency": round(time.time() - debut, 3),
                "result": (texte or contenu)[:1000],
            },
        ),
        texte,
    )


def details_du_fil(resultat: Any) -> dict[str, Any]:
    """Ce qu'une carte d'outil doit pouvoir dire d'une recherche : QUEL moteur
    a répondu, et COMBIEN de résultats (S2 du jury, 22/09/2026).

    `web_search` le sait depuis le 20/09 — `engine` vaut « brave/news », le
    moteur et son vertical — mais rien ne le faisait traverser : la carte
    affichait « web_search · 0,8 s » et rien d'autre. Une recherche qui rend
    ZÉRO résultat se lisait donc exactement comme une qui en rend huit, et
    une réponse bâtie sur du vide ne s'annonçait pas (§5). Le modèle, lui,
    n'a pas à lire ça : il lit déjà le texte numéroté.

    Les clés sont recopiées telles quelles — elles sont déjà en anglais
    camelCase dans la métadonnée, donc sur le fil aussi.
    """
    meta = getattr(resultat, "metadata", None)
    if not isinstance(meta, dict):
        return {}
    details: dict[str, Any] = {}
    moteur = meta.get("engine")
    if isinstance(moteur, str) and moteur:
        details["engine"] = moteur
    nombre = meta.get("numResults")
    # `0` compte : c'est même le cas pour lequel ceci existe.
    if isinstance(nombre, int) and not isinstance(nombre, bool):
        details["numResults"] = nombre
    return details


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
    interactive_questions: bool = False,
    trousse_adaptative: bool = False,
    verifier_en_ligne: bool = False,
    signal_textuel: bool = True,
    ville: str = "",
) -> AsyncIterator[ToolStreamEvent]:
    """Diffuse la réponse du modèle en exécutant les outils qu'il réclame.

    ``tools`` sont des instances de ``BaseTool`` ; leurs specs OpenAI sont
    dérivées ici pour que l'appelant n'ait pas à connaître ce détail.
    ``executor`` est un ``ToolExecutor`` déjà porteur de sa politique de
    sécurité — ce module ne décide jamais seul qu'un appel est permis.
    ``trousse_adaptative`` rend la trousse du 19 septembre (catalogue +
    familles) ; par défaut la trousse est la même à chaque tour, pour que le
    préfixe calculé par Ollama survive d'un tour à l'autre (20/09/2026).
    """
    trousse = TrousseChat(tools, messages, adaptative=trousse_adaptative)
    travail: list[Message] = list(messages)
    if interactive_questions:
        travail = ajouter_consigne(travail)
        # 19/09/2026 : sur le 9b, le seul système initial donnait des listes
        # en prose. Le rappel au tour courant a produit le véritable appel.
        travail.append(Message(role=Role.SYSTEM, content=RAPPEL))
    # 21/09/2026, 23 h : « Raconte-moi l'histoire de ce pays » après Haïti
    # → « de quel pays tu parles ? ». Le rappel du sujet (server/suite.py),
    # après la consigne des questions — qui se recolle au DERNIER système
    # du fil, et ce doit être le prompt d'identité.
    travail = avec_rappel(travail)
    # 20/09/2026 : « Qui est le président actuel du Canada ? » → « Justin
    # Trudeau, depuis 2015 », de mémoire, sans appel, en 5,1 s. Une question
    # d'actualité reçoit sa consigne au tour courant, sa réponse est retenue
    # tant qu'aucune recherche n'a abouti, et une relance ferme précède l'aveu.
    # 21/09/2026 (P2) : la reconnaissance est lexicale et le restera. Le
    # bouton « Vérifier en ligne » (verifyOnline) et « Vérifie ça » tapé ou
    # dicté forcent la vérification, avec une consigne qui nomme la question
    # à vérifier — celle qui précède la demande, pas la demande elle-même.
    dernier_message = next((m for m in reversed(messages) if m.role == Role.USER), None)
    derniere_demande = (dernier_message.content or "") if dernier_message else ""
    avec_image = bool(dernier_message is not None and dernier_message.images)
    demande_de_verification = (
        "web_search" in trousse.noms
        and not avec_image
        and (verifier_en_ligne or est_une_demande_de_verification(derniere_demande))
    )
    question_courante = derniere_demande
    if demande_de_verification:
        question_courante = question_a_verifier(messages, forcee=verifier_en_ligne)
        # Revue du 21/09 : « Vérifie ça » après « quelles sont mes tâches ? »
        # forçait une recherche web sur des données personnelles, retenait
        # la réponse venue de l'outil local et finissait par « je n'ai pas pu
        # vérifier ». Ce qui est personnel ne se vérifie pas sur le web ; ce
        # tour redevient ordinaire. Sans question avant, rien à vérifier.
        if not question_courante.strip() or question_personnelle(question_courante):
            demande_de_verification = False
            question_courante = derniere_demande
    actualite = demande_de_verification or (
        "web_search" in trousse.noms and question_courante_d_actualite(messages)
    )
    if demande_de_verification:
        travail = consigne_actualite(
            travail, CONSIGNE_DEMANDEE.format(question=question_courante.strip())
        )
    elif actualite:
        travail = consigne_actualite(travail)
    relance_actualite_faite = False
    relance_recherche_faite = False
    # Revue du 20/09 : « un outil a tourné » ne vaut pas vérification —
    # current_time, ou un web_search sans résultat, laissaient passer la
    # réponse de mémoire comme vérifiée. Seule une recherche qui a rendu
    # quelque chose lève la retenue.
    recherche_tentee = False
    verification_faite = False
    # Les sources numérotées des recherches du tour (pastilles [N] dans
    # l'interface) et leur texte, pour le contrôle a posteriori : ce que la
    # réponse affirme et que les sources ne portent pas est signalé (20/09).
    sources_du_tour: list[dict[str, Any]] = []
    corpus_sources = ""
    # 21/09/2026 : cinq sources et « Justin Trudeau [3] ». Ce que le code
    # établit sur les sources avant que le modèle rédige (titulaire désigné,
    # âge des sources) lui est dit en SYSTEM ; ce qui concerne l'interface
    # part avec le signal de fin de tour.
    donnees_verification: dict[str, Any] = {}
    index_de_la_note: int | None = None
    lecture_auto_faite = False
    officielle_lue = False
    pages_lues: list[str] = []
    # Revue du 21/09 : le contrôle ne jugeait que le DERNIER passage du
    # modèle ; « Justin Trudeau [3], depuis 2015 » écrit avant un second
    # outil restait affiché sous un badge vert. On juge ce que la bulle
    # AFFICHE : tout le texte parti sur le fil pendant le tour.
    texte_affiche: list[str] = []
    deja_vus: set[str] = set()
    deja_ecrit = False
    # Le filet anti-promesse, au chat aussi (Atlas, 24 août 2026) : une seule
    # sommation par réponse, et jamais après qu'un outil a réellement tourné
    # — un compte rendu d'outil n'est pas une promesse en l'air.
    sommation_faite = False
    un_outil_a_tourne = False
    cadrage_requis = False
    outils_indisponibles = False

    tours_actions = 0
    passages = max_tool_turns + MAX_CHARGEMENTS + 1
    for passage in range(passages):
        # Le tour de trop se fait sans outils : on veut une phrase, pas un
        # nouvel appel qu'on n'exécuterait pas.
        # 19/09/2026 : charger un schéma ne doit pas prendre la place d'une
        # vraie action dans les trois tours permis. La découverte reste bornée.
        dernier_tour = tours_actions >= max_tool_turns or passage == passages - 1
        specs = [] if outils_indisponibles else trousse.specs
        if interactive_questions:
            specs = [*specs, schema_questions()]
        specs_du_tour = None if dernier_tour else specs
        verifier_actualite = (
            actualite
            and not dernier_tour
            and not outils_indisponibles
            and not verification_faite
        )
        verifier_lecture = verifier_actualite or (
            not dernier_tour
            and not outils_indisponibles
            and not un_outil_a_tourne
            and trousse.verifier_lecture(messages)
        )

        morceaux: list[str] = []
        fragments: dict[int, dict[str, Any]] = {}
        premier_du_tour = True
        raison_arret = None

        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if specs_du_tour:
            kwargs["tools"] = specs_du_tour
            kwargs["tools_required"] = True
            kwargs["temperature"] = (
                0.0
                if interactive_questions
                else min(temperature, TOOL_TURN_TEMPERATURE)
            )

        try:
            async with aclosing(
                prolonger_flux(engine, travail, **kwargs)
            ) as source_flux:
                async for morceau in source_flux:
                    if morceau.content:
                        morceaux.append(morceau.content)
                        if (
                            not verifier_lecture
                            and premier_du_tour
                            and deja_ecrit
                            and morceau.content.strip()
                        ):
                            # Le tour précédent avait écrit (« Je regarde tes
                            # tâches… ») et celui-ci reprend après l'outil. Sans ce
                            # séparateur les deux se recollent :
                            # « Je regarde tes tâches.Tu as une tâche ».
                            yield ToolStreamEvent("token", "\n\n")
                        if not verifier_lecture:
                            premier_du_tour = False
                            # Un tour composé d'espaces ne doit pas faire
                            # précéder le suivant d'un saut de ligne.
                            deja_ecrit = deja_ecrit or bool(morceau.content.strip())
                            yield ToolStreamEvent("token", morceau.content)
                    if morceau.tool_calls:
                        _fusionner_fragments(fragments, morceau.tool_calls)
                    if morceau.finish_reason:
                        raison_arret = morceau.finish_reason
        except EngineToolsUnsupportedError:
            # 19/09/2026 : Gemma disait « Appelle diapason_ask_questions » car
            # Ollama retirait les outils sans retirer leurs consignes. Le JSON
            # contraint fournit les mêmes choix, sans fonction ni exécuteur.
            if morceaux or fragments or outils_indisponibles:
                raise
            if interactive_questions:
                try:
                    demande = await cadrer_sans_outils(engine, model, list(messages))
                except Exception:
                    logger.warning(
                        "Questionnaire sans outils indisponible", exc_info=True
                    )
                    yield ToolStreamEvent(
                        "token",
                        "Je n’ai pas pu préparer le questionnaire. Tu peux préciser "
                        "ta demande ici pour continuer.",
                    )
                    return
                if demande is not None:
                    yield ToolStreamEvent("questions", demande)
                    yield ToolStreamEvent("token", texte_questions(demande))
                    return
            outils_indisponibles = True
            interactive_questions = False
            travail = consigne_sans_outils(avec_rappel(messages))
            continue

        appels = [fragments[i] for i in sorted(fragments)]
        if outils_indisponibles and appels:
            yield ToolStreamEvent(
                "token", "Je n’ai pas pu terminer cette demande sans accès aux outils."
            )
            return
        cadrage = next(
            (
                a
                for a in appels
                if (a.get("function") or {}).get("name") == POSER_QUESTIONS
            ),
            None,
        )
        if interactive_questions and cadrage is not None:
            # 19/09/2026 : le cadrage suspend LE TOUR, pas un thread Ollama.
            # Même si le modèle joint une création au même lot, aucune action
            # de ce lot ne s'exécute avant que l'utilisateur ait répondu.
            try:
                demande = valider_questions(
                    cadrage["function"].get("arguments") or "{}"
                )
            except ValueError:
                cadrage_requis = True
                if dernier_tour:
                    yield ToolStreamEvent("token", "\n\nPeux-tu préciser ta demande ?")
                    return
                travail.append(
                    Message(
                        role=Role.SYSTEM,
                        content=(
                            "Le questionnaire n'est pas valide. Utilise des "
                            "questions distinctes, utiles et concises, chacune "
                            "avec 2 à 4 options "
                            "{label, description}. Ne lance aucune autre action "
                            "avant la réponse de l'utilisateur."
                        ),
                    )
                )
                tours_actions += 1
                continue
            yield ToolStreamEvent("questions", demande)
            yield ToolStreamEvent("token", "\n\n" + texte_questions(demande))
            return
        if cadrage_requis and appels:
            yield ToolStreamEvent("token", "\n\nPeux-tu préciser ta demande ?")
            return
        if not verifier_lecture:
            texte_affiche.extend(morceaux)
        texte_retenu = "".join(morceaux)
        cadrage_textuel = (
            interactive_questions
            and raison_arret == "stop"
            and est_un_cadrage_textuel(texte_retenu)
        )
        if verifier_actualite and not appels and cadrage_textuel:
            # Le modèle demande une précision (« quel billet ? ») : ce n'est
            # pas une réponse de mémoire. Le cadrage suit son chemin ordinaire,
            # jusqu'aux boutons (revue du 20/09).
            verifier_lecture = False
        if verifier_lecture:
            # Une réponse de mémoire coupée par le plafond (« length ») reste
            # une réponse de mémoire ; la relecture du 19/09, elle, ne rejoue
            # jamais un arrêt qui n'est pas « stop » (ne pas contourner une coupure).
            arret_ordinaire = raison_arret == "stop" or (
                verifier_actualite and raison_arret == "length"
            )
            if not appels and arret_ordinaire:
                if (
                    verifier_actualite
                    and not relance_actualite_faite
                    and not recherche_tentee
                ):
                    # Le premier passage a répondu de mémoire : une seule
                    # relance, ferme, sans afficher l'affirmation non vérifiée.
                    relance_actualite_faite = True
                    travail = consigne_actualite(travail, CONSIGNE_FERME)
                    continue
                if verifier_actualite:
                    # Deux refus d'appeler web_search, ou une recherche qui n'a
                    # rien rendu : la réponse part, annoncée pour ce qu'elle
                    # est (§100) — par le niveau « memory » du signal, plus par
                    # un préfixe de texte qui se copiait et se prononçait
                    # (21/09) ; un silence devient un aveu, pas un bandeau nu.
                    if not texte_retenu.strip():
                        morceaux = [AVEU]
                    elif signal_textuel:
                        # Un client qui ne lit pas les événements (curl, SDK
                        # OpenAI) garde le signe dans le texte (§100) ; le
                        # client de bureau lit le niveau et n'en veut pas.
                        yield ToolStreamEvent(
                            "token",
                            AVERTISSEMENT_RECHERCHE
                            if recherche_tentee
                            else AVERTISSEMENT,
                        )
                    if deja_ecrit:
                        yield ToolStreamEvent("token", "\n\n")
                    for contenu in morceaux:
                        yield ToolStreamEvent("token", contenu)
                    texte_affiche.extend(morceaux)
                    for evt in _controle_des_sources(
                        "".join(texte_affiche),
                        corpus_sources,
                        question_courante,
                        donnees_verification,
                        sources=sources_du_tour,
                        recherche_tentee=recherche_tentee,
                        verification_faite=verification_faite,
                        dernier_passage="".join(morceaux),
                    ):
                        yield evt
                    return
                # 19/09/2026 : le 9b affirmait ne voir aucun message sans
                # lecture. Ne pas diffuser cette réponse : revenir UNE fois
                # aux schémas complets, sans injecter l'affirmation dans le fil.
                trousse.elargir()
                continue
            if deja_ecrit and any(m.strip() for m in morceaux):
                yield ToolStreamEvent("token", "\n\n")
            for contenu in morceaux:
                yield ToolStreamEvent("token", contenu)
            texte_affiche.extend(morceaux)
            deja_ecrit = deja_ecrit or any(m.strip() for m in morceaux)
            if not appels:
                # Une coupure ou un arrêt de sécurité n'autorise pas une
                # nouvelle génération destinée à contourner cet arrêt.
                if actualite or verification_faite:
                    for evt in _controle_des_sources(
                        "".join(texte_affiche),
                        corpus_sources,
                        question_courante,
                        donnees_verification,
                        sources=sources_du_tour,
                        recherche_tentee=recherche_tentee,
                        verification_faite=verification_faite,
                        controle_lexical=actualite,
                        dernier_passage="".join(morceaux),
                    ):
                        yield evt
                return
        if not appels:
            texte_du_tour = "".join(morceaux)
            if (
                actualite
                and verification_faite
                and not relance_recherche_faite
                and passage < passages - 1
                and est_une_non_reponse(texte_du_tour, question=question_courante)
            ):
                # La lecture est faite par le code, pas par le modèle : elle
                # ne coûte aucun tour d'outil et reste possible quand le 9b a
                # brûlé ses trois recherches sans trouver (revue du 21/09 :
                # la garde « tours_actions < max_tool_turns » la refusait
                # justement dans ce cas-là). Seul le DERNIER passage la
                # refuse — après lui, la boucle s'arrête sans phrase.
                # Reste-t-il un tour d'outil APRÈS celui-ci ? Sinon, une
                # consigne « appelle web_search » serait une impasse : le
                # passage suivant est sans outils — par les tours d'outil ou
                # par le budget de passages, la même condition que
                # dernier_tour (revue du 21/09, 22 h).
                encore_un_outil = (
                    tours_actions + 1 < max_tool_turns and passage + 1 < passages - 1
                )
                # Banc du 21/09 : « Les résultats ne mentionnent pas le
                # vainqueur … il faudrait attendre » — puis rien, ou « Je vais
                # relancer la recherche » sans la relancer. Une seconde
                # recherche, avec une autre requête, une fois ; ce qui est
                # déjà affiché reste, la suite s'ajoute dessous.
                relance_recherche_faite = True
                travail.append(Message(role=Role.ASSISTANT, content=texte_du_tour))
                # D'abord lire, par le code, la source la plus prometteuse :
                # nhl.com « 2026 Stanley Cup Final » était dans les résultats
                # et le 9b n'y allait pas (banc du 21/09). Sans source qui
                # s'impose, ou si la page ne se lit pas : une autre requête.
                page_jointe = False
                candidates = (
                    sources_prometteuses(sources_du_tour, question_courante, pages_lues)
                    if "web_read" in trousse.noms
                    else []
                )
                # Deux essais : la première page peut ne pas se lire (essai du
                # 21/09 : Le Devoir refusait, nhl.com juste derrière lisait).
                for prometteuse in candidates[:LECTURES_SUR_NON_REPONSE]:
                    pages_lues.append(str(prometteuse["url"]))
                    async for evt, texte in _lire_la_page(
                        executor,
                        str(prometteuse["url"]),
                        question_courante,
                        sources_du_tour,
                    ):
                        if evt is not None:
                            yield evt
                        if texte:
                            page_jointe = True
                            corpus_sources += "\n" + texte
                            consigne_page = (
                                CONSIGNE_PAGE_LUE
                                if encore_un_outil
                                else CONSIGNE_PAGE_LUE_SANS_OUTIL
                            )
                            # La page suit l'aveu, dans la consigne — pas
                            # dans le résultat de recherche déjà envoyé :
                            # modifier un message au milieu du fil jetait le
                            # préfixe qu'Ollama avait en cache, et la
                            # reprise re-préremplissait extraits, note et
                            # aveu (revue du 21/09, 22 h).
                            travail.append(
                                Message(
                                    role=Role.SYSTEM,
                                    content="Page lue (web_read) :\n"
                                    + _tronquer(texte, MAX_TOOL_RESULT_CHARS * 2)
                                    + "\n\n"
                                    + consigne_page.format(ref=prometteuse["ref"]),
                                )
                            )
                    if page_jointe:
                        break
                if not page_jointe:
                    if not encore_un_outil:
                        # Ni page, ni tour d'outil : l'aveu reste tel quel.
                        travail.pop()
                        if actualite or verification_faite:
                            for evt in _controle_des_sources(
                                "".join(texte_affiche),
                                corpus_sources,
                                question_courante,
                                donnees_verification,
                                sources=sources_du_tour,
                                recherche_tentee=recherche_tentee,
                                verification_faite=verification_faite,
                                controle_lexical=actualite,
                                dernier_passage=texte_du_tour,
                            ):
                                yield evt
                        return
                    travail.append(
                        Message(role=Role.SYSTEM, content=CONSIGNE_AUTRE_REQUETE)
                    )
                tours_actions += 1
                continue
            # La PROMESSE SANS L'ACTE, version chat : « je regarde tes
            # tâches » sans appel d'outil. La promesse est déjà partie dans
            # le flux — la livraison la suit après le séparateur \n\n, et
            # les événements tool_start rendent la reprise visible.
            if (
                interactive_questions
                and raison_arret == "stop"
                and est_un_cadrage_textuel(texte_du_tour)
            ):
                # 19/09/2026 : le 9b posait quatre questions en Markdown malgré
                # l'outil. Une seule conversion isolée, sans exécuteur, transforme
                # CE cadrage en boutons ; une réponse normale ne paie pas ce tour.
                fragments_cadrage: dict[int, dict[str, Any]] = {}
                conversion = [
                    Message(
                        role=Role.USER,
                        content=(
                            "Convertis ce questionnaire en appel de "
                            "diapason_ask_questions. "
                            "Appelle cet outil maintenant, sans prose. Conserve toutes "
                            "les questions utiles, sans doublons ni quota, "
                            "deux à quatre options courtes chacune, "
                            "et la langue du texte. N'exécute pas la demande "
                            "d'origine.\n\n" + texte_du_tour
                        ),
                    )
                ]
                try:
                    async with aclosing(
                        engine.stream_full(
                            conversion,
                            model=model,
                            tools=[schema_questions()],
                            temperature=0.0,
                            max_tokens=CADRAGE_MAX_JETONS,
                        )
                    ) as flux_cadrage:
                        async for morceau in flux_cadrage:
                            if morceau.tool_calls:
                                _fusionner_fragments(
                                    fragments_cadrage, morceau.tool_calls
                                )
                except Exception:  # la prose de secours est déjà livrée
                    logger.warning("Conversion du cadrage indisponible", exc_info=True)
                    return
                for candidat in fragments_cadrage.values():
                    fonction = candidat.get("function") or {}
                    if fonction.get("name") != POSER_QUESTIONS:
                        continue
                    try:
                        demande = valider_questions(fonction.get("arguments") or "{}")
                    except ValueError:
                        continue
                    yield ToolStreamEvent("questions", demande)
                    return
                # Le texte déjà écrit reste utilisable si la conversion échoue.
                return
            if (
                not dernier_tour
                and specs
                and not sommation_faite
                and not un_outil_a_tourne
                and est_une_promesse_sans_acte(texte_du_tour, ecrit=True)
            ):
                sommation_faite = True
                travail.append(Message(role=Role.ASSISTANT, content=texte_du_tour))
                travail.append(
                    Message(
                        role=Role.SYSTEM,
                        content=(
                            "Tu viens d'ANNONCER une action sans appeler "
                            "d'outil — c'est une promesse en l'air. Appelle "
                            "MAINTENANT l'outil qui convient, puis confirme "
                            "en une phrase courte, sans répéter ton annonce."
                        ),
                    )
                )
                logger.warning("chat promise without action, retrying with a summons")
                tours_actions += 1
                continue
            if actualite or verification_faite:
                # Seule une question d'actualité a reçu la consigne de s'en
                # tenir aux sources ; juger une recette sur ce critère
                # signalait « Ricardo Larrivée » (revue du 20/09). Mais une
                # recherche faite d'elle-même mérite son badge (21/09).
                for evt in _controle_des_sources(
                    "".join(texte_affiche),
                    corpus_sources,
                    question_courante,
                    donnees_verification,
                    sources=sources_du_tour,
                    recherche_tentee=recherche_tentee,
                    verification_faite=verification_faite,
                    controle_lexical=actualite,
                    dernier_passage=texte_du_tour,
                ):
                    yield evt
            return
        if dernier_tour:
            if any(
                trousse.est_chargement((a.get("function") or {}).get("name", ""))
                for a in appels
            ):
                yield ToolStreamEvent(
                    "token",
                    "\n\nJe n’ai pas pu préparer les outils nécessaires pour "
                    "terminer cette demande.",
                )
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

        chargement_seul = True
        for appel in appels:
            fonction = appel.get("function") or {}
            nom = fonction.get("name", "")
            arguments = fonction.get("arguments", "") or "{}"

            if not nom:
                continue

            if trousse.est_chargement(nom):
                travail.append(
                    Message(
                        role=Role.TOOL,
                        name=nom,
                        tool_call_id=appel.get("id") or "",
                        content=trousse.charger(arguments),
                    )
                )
                continue

            chargement_seul = False

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

            if actualite and nom == "web_search":
                # Fraîcheur et vertical décidés par le code, pas par le 9b :
                # sans eux, la page Wikipédia de Trudeau sortait en tête (20/09).
                arguments = completer_arguments(arguments, question_courante)

            yield ToolStreamEvent("tool_start", {"tool": nom, "arguments": arguments})

            un_outil_a_tourne = True
            debut = time.time()
            # Nommé avant le try : un outil qui lève n'a pas de résultat, et
            # la carte doit pouvoir le dire sans que le nom manque.
            resultat: Any = None
            try:
                if nom not in trousse.noms:
                    raise ValueError(
                        "Cet outil n'appartient pas à la trousse autorisée."
                    )
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
            page_lue = ""
            if nom == "web_search":
                recherche_tentee = True
                if recherche_concluante(nom, succes, contenu):
                    verification_faite = True
                    meta = getattr(resultat, "metadata", None) or {}
                    contenu, nouvelles = _renumeroter(
                        contenu, meta.get("sources") or [], sources_du_tour
                    )
                    if nouvelles:
                        sources_du_tour.extend(nouvelles)
                        yield ToolStreamEvent("sources", list(nouvelles))
                    corpus_sources += "\n" + contenu
                    # 21/09/2026 : aucun des cinq extraits ne nommait le
                    # premier ministre ; la page du poste le fait dans son
                    # infobox. Pour un titulaire, le code lit cette page —
                    # sans attendre que le 9b y pense — et la joint au
                    # résultat de la recherche.
                    if (
                        actualite
                        and not lecture_auto_faite
                        and "web_read" in trousse.noms
                        and question_de_titulaire(question_courante)
                    ):
                        url = page_de_reference(sources_du_tour, question_courante)
                        if url:
                            lecture_auto_faite = True
                            pages_lues.append(url)
                            async for evt, texte in _lire_la_page(
                                executor, url, question_courante, sources_du_tour
                            ):
                                if evt is not None:
                                    yield evt
                                if texte:
                                    page_lue = texte
                                    corpus_sources += "\n" + texte
            if (
                nom == "web_search"
                and actualite
                and not officielle_lue
                # UNE seule lecture automatique par tour. Depuis que
                # `pm.gc.ca` est dans la table (22/09), « Qui est le premier
                # ministre du Canada ? » déclenchait les deux : la page du
                # poste ci-dessus ET la page officielle, soit deux allers au
                # réseau pour un seul fait, sur un moteur à un créneau. La
                # page du poste passe d'abord parce qu'elle porte la DATE
                # d'entrée en fonction (« depuis le 14 mars 2025 ») que le
                # titre de pm.gc.ca ne donne pas ; la page officielle reste
                # le recours quand la recherche n'a rien rendu — et c'est
                # exactement le cas où elle vaut le plus.
                and not lecture_auto_faite
            ):
                # P6 (21/09) : la page officielle du sujet — la prévision
                # d'Environnement Canada, le taux de la Banque du Canada —
                # lue en complément de la recherche, que celle-ci ait rendu
                # quelque chose ou non : cinq articles sans une donnée météo
                # laissaient « Quel temps fait-il ce soir ? » sans réponse.
                off = (
                    page_officielle(question_courante, ville)
                    if "web_read" in trousse.noms
                    else None
                )
                if off is not None:
                    officielle_lue = True
                    pages_lues.append(off.url)
                    async for evt, texte in _lire_la_page(
                        executor, off.url, question_courante, sources_du_tour, off
                    ):
                        if evt is not None:
                            yield evt
                        if texte:
                            verification_faite = True
                            page_lue = (page_lue + "\n\n" if page_lue else "") + (
                                "Source officielle, lue par le code — réponds "
                                "d'après elle :\n" + texte
                            )
                            corpus_sources += "\n" + texte
            elif nom == "web_read" and succes:
                # Une page lue est une source au même titre qu'une recherche.
                verification_faite = True
                pages_lues.append(_url_demandee(arguments))
                meta = getattr(resultat, "metadata", None) or {}
                contenu, nouvelles = _renumeroter(
                    contenu,
                    _sous_l_url_demandee(
                        meta.get("sources") or [], _url_demandee(arguments)
                    ),
                    sources_du_tour,
                )
                if nouvelles:
                    sources_du_tour.extend(nouvelles)
                    yield ToolStreamEvent("sources", list(nouvelles))
                corpus_sources += "\n" + contenu

            contenu = _tronquer(contenu)
            if page_lue:
                # Deux plafonds distincts : la page lue ne doit pas manger
                # les extraits, ni l'inverse.
                contenu += "\n\nPage lue (web_read) :\n" + _tronquer(
                    page_lue, MAX_TOOL_RESULT_CHARS * 2
                )

            yield ToolStreamEvent(
                "tool_end",
                {
                    "tool": nom,
                    "success": succes,
                    "latency": round(latence, 3),
                    "result": contenu[:1000],
                    **details_du_fil(resultat),
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

        if actualite and corpus_sources:
            # Ce que le code sait des sources, dit au modèle avant qu'il
            # rédige : le titulaire qu'elles désignent, leur âge. Recalculé à
            # chaque passage, et la note REMPLACE la précédente dans le fil —
            # revue du 21/09 : ajoutée, deux consignes contradictoires
            # (« appuie-toi sur X » puis « plusieurs titulaires ») restaient
            # empilées, et « sources datées » survivait à la lecture d'une
            # page du jour.
            note, donnees_verification = note_avant_redaction(
                sources_du_tour, corpus_sources, question_courante
            )
            if index_de_la_note is not None:
                del travail[index_de_la_note]
                index_de_la_note = None
            if note:
                travail.append(Message(role=Role.SYSTEM, content=note))
                index_de_la_note = len(travail) - 1

        if not chargement_seul:
            tours_actions += 1


__all__ = [
    "DEFAULT_MAX_TOOL_TURNS",
    "MAX_TOOL_RESULT_CHARS",
    "TOOL_TURN_TEMPERATURE",
    "ToolStreamEvent",
    "observation",
    "stream_with_tools",
]
