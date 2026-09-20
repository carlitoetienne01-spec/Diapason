"""Une demande courte peut exiger une longue réponse (19 septembre 2026).

« Je veux les 400 » était classé trivial. Le modèle décidait de livrer cent
lignes, et la boucle jetait le motif d'arrêt fourni par le moteur.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from typing import Any

from diapason.core.types import Message, Role
from diapason.engine._stubs import StreamChunk

# Trois générations de 8192 jetons au plus : assez pour plusieurs centaines
# de lignes courtes, sans laisser une continuation occuper Ollama indéfiniment.
MAX_PASSAGES = 3
JETONS_PAR_PASSAGE = 8192
# Sous 50 entrées courtes, l'estimation reste sous 2624 jetons et tient
# dans les 4096 du bureau : pas de reprise automatique pour ces petits tours.
SEUIL_REPRISE = 50
# Le refus observé pèse 660 caractères. Deux petits paragraphes (2048)
# suffisent à le reconnaître avant affichage ; au-delà le flux reste direct.
AMORCE_MAX_CARACTERES = 2048

_ACTION = re.compile(
    r"\b(?:donne|génère|genere|rédige|redige|écris|ecris|liste|je veux|"
    r"give|generate|write|list|provide)\b",
    re.I,
)
_QUANTITE = re.compile(
    r"\b(\d{1,6})\s+(?:verbes?|exemples?|idées?|idees?|éléments?|elements?|"
    r"questions?|phrases?|lignes?|entrées?|entrees?|exercices?|items?|verbs?|"
    r"examples?|ideas?|sentences?|rows?)\b",
    re.I,
)
_REPRISE = re.compile(
    r"\b(?:je veux (?:les|ces)|(?:liste|tableau)\s+(?:compl[eè]te?\s+)?"
    r"(?:des|de|les))\s+(\d{1,6})\b",
    re.I,
)


def quantite_demandee(texte: str) -> int | None:
    if not _ACTION.search(texte):
        return None
    trouve = _QUANTITE.search(texte) or _REPRISE.search(texte)
    return int(trouve[1]) if trouve and int(trouve[1]) > 0 else None


def budget_quantite(texte: str) -> int:
    nombre = quantite_demandee(texte)
    # 32 jetons par entrée + 1024 pour titres/explications ; estimation de
    # capacité, jamais promesse d'exactitude ni autorisation de fabriquer.
    return min(MAX_PASSAGES * JETONS_PAR_PASSAGE, 1024 + nombre * 32) if nombre else 0


def quantite_du_tour(messages: Sequence[Message]) -> int | None:
    for message in reversed(messages):
        if message.role == Role.USER:
            return quantite_demandee(message.content or "")
    return None


def consigne_quantite(nombre: int) -> str:
    return (
        f"L'utilisateur demande {nombre} éléments. Respecte cette quantité et le "
        "format demandé si les faits le permettent. Une demande exhaustive prime "
        "sur une préférence de concision. Ne réduis pas à un échantillon et ne "
        "demande pas de confirmation pour poursuivre une quantité déjà demandée. "
        "N'élargis pas la portée de la demande pour la déclarer impossible. "
        "Si un détail est ambigu, annonce brièvement une interprétation raisonnable. "
        "N'invente aucune limite technique ou impossibilité d'affichage. "
        "Vérifie les entrées et évite les doublons, même sous des numéros différents. "
        "Une quantité demandée n'est pas une preuve qu'autant d'éléments existent : "
        "corrige une prémisse erronée et indique les incertitudes ; ne fabrique "
        "jamais d'éléments ni de sources pour atteindre le nombre."
    )


def refus_de_volume(texte: str) -> bool:
    """Reconnaît un refus technique initial, pas un refus factuel ou de sécurité."""
    propre = texte.strip().casefold().replace("’", "'")
    if any(
        m in propre
        for m in (
            "sécurité",
            "confidenti",
            "dangereu",
            "illégal",
            "illegal",
            "privacy",
            "safety",
            "copyright",
            "droit d'auteur",
            "vérifier",
            "verify",
            "n'existe",
            "existent pas",
            "source fiable",
            "fiable",
        )
    ):
        return False
    refuse = re.match(
        r"^(?:désolé[, .]*|désolée[, .]*|sorry[, .]*)?\s*"
        r"(?:je ne peux pas|je ne suis pas en mesure|il (?:est|serait) impossible|"
        r"i (?:cannot|can't)|it is impossible)",
        propre,
    )
    limite = re.search(
        r"(?:limit\w*\s+(?:techniques?|de (?:caractères|longueur|tokens)|"
        r"d'une réponse)|(?:trop|too) (?:long|large)|"
        r"(?:dépass\w*|exceed\w*).{0,100}(?:limit|capacit))",
        propre,
    )
    return bool(refuse and limite and compter_entrees(texte) is None)


def cadrer_generation(
    messages: Sequence[Message],
    nombre: int,
    budget: int,
    *,
    corriger_refus: bool = False,
) -> list[Message]:
    """Rappelle la capacité réelle près de la demande, sans effacer l'historique."""
    consigne = (
        "Cadre de génération fourni par l'application, pour ce tour uniquement : "
        f"{consigne_quantite(nombre)} Budget de sortie total : {budget} jetons, "
        f"jusqu'à {MAX_PASSAGES} générations assemblées dans UNE réponse. "
        "L'application reprend une coupure de longueur ; commence donc le contenu "
        "demandé sans imposer une tranche de 50 ou 100 ni demander de validation. "
        "Les affirmations techniques de tes anciennes réponses ne sont pas des "
        "règles du logiciel. Si les faits ne permettent pas le nombre demandé, "
        "corrige cette prémisse précisément plutôt que d'inventer une limite "
        "d'affichage. Ne présente pas ces détails techniques à l'utilisateur."
    )
    if corriger_refus:
        consigne += (
            " Ton brouillon vient de refuser au seul motif de la longueur. "
            "Reconsidère uniquement ce motif à la lumière de ce budget réel. "
            "Commence le résultat ou explique une difficulté factuelle précise. "
            "Ne contourne aucune règle de sécurité, de confidentialité ou "
            "d'exactitude. Ne t'excuse pas et ne répète pas le brouillon."
        )
    travail = list(messages)
    # La consigne initiale était noyée avant des milliers de mots d'historique
    # qui affirmaient l'inverse. La rapprocher du dernier tour ne change ni
    # les mots de l'utilisateur ni ses messages enregistrés.
    index = next(
        (i for i in range(len(travail) - 1, -1, -1) if travail[i].role == Role.USER),
        len(travail),
    )
    travail.insert(index, Message(role=Role.SYSTEM, content=consigne))
    return travail


def compter_entrees(texte: str) -> int | None:
    """Compte les entrées distinctes d'un tableau Markdown simple ou d'une liste.

    La première colonne numérique n'est pas une identité : renuméroter un
    même verbe ne fait pas un nouveau verbe. Rien n'est supprimé du contenu.
    """
    cles: set[str] = set()
    colonnes = 0
    tableau_vu = False
    entete: list[str] = []
    precedente: list[str] = []
    code = False
    for ligne in texte.splitlines():
        if ligne.lstrip().startswith(("```", "~~~")):
            code = not code
            continue
        if code:
            continue
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if len(cellules) > 1 and all(re.fullmatch(r":?-{3,}:?", c) for c in cellules):
            tableau_vu = True
            colonnes = len(cellules)
            entete = precedente
            continue
        if (
            colonnes
            and len(cellules) == colonnes
            and "|" in ligne
            and cellules != entete
        ):
            if cellules and cellules[0].isdigit():
                cellules = cellules[1:]
            if cellules:
                cles.add(re.sub(r"\s+", " ", cellules[0]).strip().casefold())
        precedente = cellules
    if tableau_vu:
        return len(cles)
    entrees = re.findall(r"^\s*\d+[.)]\s+(.+)$", texte, re.M)
    return len({e.strip().casefold() for e in entrees}) if entrees else None


async def prolonger_flux(
    engine: Any, messages: Sequence[Message], **kwargs: Any
) -> AsyncIterator[StreamChunk]:
    """Poursuit une sortie coupée, sans réexécuter un appel d'outil.

    Motif d'arrêt et compteurs appartiennent au flux courant, jamais à un
    attribut partagé du moteur (deux fenêtres peuvent parler simultanément).
    """
    nombre = quantite_du_tour(messages)
    if nombre is None or nombre < SEUIL_REPRISE:
        async with aclosing(engine.stream_full(messages, **kwargs)) as source_flux:
            async for morceau in source_flux:
                yield morceau
        return
    total = ""
    restant = min(
        int(kwargs.get("max_tokens", 4096)), MAX_PASSAGES * JETONS_PAR_PASSAGE
    )
    travail = cadrer_generation(messages, nombre, restant)
    refus_corrige = False
    raison = None
    incomplet = False
    compte_precedent = None
    for passage in range(MAX_PASSAGES):
        budget = min(restant, JETONS_PAR_PASSAGE)
        if budget <= 0:
            break
        morceaux: list[str] = []
        outils = False
        raison = None
        consommes = None
        amorce: list[str] = []
        diffuse = passage > 0
        async with aclosing(
            engine.stream_full(travail, **{**kwargs, "max_tokens": budget})
        ) as source_flux:
            async for morceau in source_flux:
                if morceau.content:
                    morceaux.append(morceau.content)
                    if diffuse:
                        yield StreamChunk(content=morceau.content)
                    else:
                        amorce.append(morceau.content)
                        debut = "".join(amorce)
                        if (
                            len(debut) >= AMORCE_MAX_CARACTERES
                            or compter_entrees(debut) is not None
                        ):
                            yield StreamChunk(content=debut)
                            amorce.clear()
                            diffuse = True
                outils = outils or bool(morceau.tool_calls)
                if morceau.tool_calls or morceau.tool_results or morceau.content_blocks:
                    if amorce:
                        yield StreamChunk(content="".join(amorce))
                        amorce.clear()
                    diffuse = True
                    yield StreamChunk(
                        tool_calls=morceau.tool_calls,
                        tool_results=morceau.tool_results,
                        content_blocks=morceau.content_blocks,
                    )
                if morceau.finish_reason:
                    raison = morceau.finish_reason
                usage = (morceau.usage or {}).get("completion_tokens")
                if (
                    isinstance(usage, int)
                    and not isinstance(usage, bool)
                    and usage >= 0
                ):
                    consommes = usage
        texte = "".join(morceaux)
        # Un modèle qui s'arrête tôt n'a pas consommé tout son plafond.
        # Sinon une première tranche de 25 lignes épuiserait artificiellement
        # les 4096 jetons et interdirait justement la suite attendue.
        restant -= min(budget, max(1, consommes)) if consommes is not None else budget
        if (
            not diffuse
            and not outils
            and not refus_corrige
            and raison == "stop"
            and refus_de_volume(texte)
            and restant > 0
            and passage + 1 < MAX_PASSAGES
        ):
            refus_corrige = True
            travail = cadrer_generation(messages, nombre, restant, corriger_refus=True)
            continue
        if amorce:
            yield StreamChunk(content="".join(amorce))
        total += texte
        if outils:
            yield StreamChunk(finish_reason=raison or "tool_calls")
            return
        compte = compter_entrees(total)
        incomplet = compte is not None and compte < nombre
        if (
            raison == "stop"
            and incomplet
            and compte_precedent is not None
            and compte <= compte_precedent
        ):
            break
        compte_precedent = compte
        # Un arrêt de sécurité, une panne ou un moteur sans motif explicite
        # ne constituent jamais une autorisation de relancer la génération.
        reprendre = raison == "length" or (raison == "stop" and incomplet)
        if not reprendre or not texte.strip():
            break
        if passage + 1 == MAX_PASSAGES or restant <= 0:
            break
        if raison == "stop":
            # Un arrêt volontaire finit souvent par « veux-tu la suite ? ».
            # La nouvelle liste commence sur sa ligne ; une coupure au
            # milieu d'un mot, elle, ne reçoit aucun séparateur artificiel.
            derniere = total.rstrip().splitlines()[-1].strip()
            separateur = "\n\n"
            if derniere.startswith("|") and derniere.endswith("|"):
                separateur = "" if total.endswith("\n") else "\n"
            total += separateur
            if separateur:
                yield StreamChunk(content=separateur)
        travail = [
            *messages,
            Message(role=Role.ASSISTANT, content=total),
            Message(
                role=Role.USER,
                content=(
                    "Poursuis exactement à l'endroit de l'interruption, sans répéter "
                    "le texte, les entrées ou l'en-tête du tableau déjà fournis. "
                    f"La demande initiale reste de {nombre} éléments distincts. "
                    "Complète le mot ou la ligne interrompue si nécessaire. "
                    "Ne fabrique rien pour atteindre le nombre ; si la liste ne "
                    "peut pas être complétée de façon fiable, explique pourquoi."
                ),
            ),
        ]
        # Les continuations textuelles ne disposent pas d'outils : aucun
        # effet externe ne doit être rejoué pour allonger un tableau.
        kwargs = {k: v for k, v in kwargs.items() if k != "tools"}
    if raison == "length" or incomplet:
        compte = compter_entrees(total)
        precision = (
            f" ({compte} entrées distinctes détectées sur {nombre})"
            if compte is not None
            else ""
        )
        yield StreamChunk(
            content=(
                f"\n\n*Réponse partielle{precision} : la génération automatique "
                "s'est arrêtée. L'exhaustivité et l'exactitude ne sont pas garanties.*"
            )
        )
    yield StreamChunk(finish_reason=raison or "stop")
