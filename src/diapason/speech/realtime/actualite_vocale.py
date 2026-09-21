"""Les gardes d'actualité du chat, portées à la voix (21 septembre 2026).

Le 20 et le 21 septembre, le chat a reçu ses gardes : consigne au tour
courant pour une question d'actualité, fraîcheur imposée à web_search,
lecture automatique de la page du poste pour un titulaire, note SYSTEM
avant la rédaction, désaccord de titulaire signalé. La voix n'en avait
aucune — « Qui est le premier ministre du Canada ? » dit au micro recevait
« Justin Trudeau » sans qu'une recherche parte, et rien ne le disait.

La voix ne peut pas RETENIR une réponse comme le chat : les phrases sont
synthétisées à mesure qu'elles arrivent, et le silence d'une retenue serait
le pire des signaux. Ce que la voix peut faire : poser la consigne (au chat,
elle a suffi au premier passage), imposer la fraîcheur, lire la page du
poste, prévenir le modèle avant qu'il rédige, relancer UNE fois quand le
premier passage a répondu sans chercher (la parole est sortie ; la
livraison suit, comme pour une promesse sans acte) — et, quand rien n'a été
vérifié ou que la réponse contredit les sources, LE DIRE à voix haute en
fin de tour (§100 : jamais de faux succès, même prononcé).

Les messages sont ici des dicts (``{"role", "content"}``), la forme de la
boucle vocale ; ``server/actualite.py`` travaille sur des ``Message``. Les
fonctions de ce module font le pont, rien de plus : la logique reste dans
``actualite.py``, une seule fois.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from diapason.core.types import Message, Role
from diapason.server.actualite import (
    AVEU,
    completer_arguments,
    desaccord_sur_le_titulaire,
    est_une_demande_de_verification,
    note_avant_redaction,
    page_de_reference,
    question_a_verifier,
    question_d_actualite,
    question_de_titulaire,
    question_personnelle,
    recherche_concluante,
    renumeroter,
    sous_l_url_demandee,
)

# La consigne du chat demandait de citer « [1] » : Kokoro prononçait « Mark
# Carney deux, depuis mars deux mille vingt-cinq » (revue vocale du 21/09).
# À l'oral, la source se nomme et la date se dit en toutes lettres.
CONSIGNE_VOCALE = (
    "Cette question porte sur une réalité qui a pu changer depuis ton "
    "entraînement : une fonction en cours, un prix, un résultat, une date. "
    "Appelle web_search maintenant avec une requête précise, puis réponds en "
    "une ou deux phrases parlées d'après les résultats : nomme la source "
    "(le site) et dis la date de l'information en toutes lettres si elle est "
    "donnée — jamais de numéro entre crochets ni d'adresse web. Si la "
    "recherche ne rend rien d'utile, dis que tu n'as pas pu vérifier — ne "
    "réponds pas de mémoire à cette question."
)
CONSIGNE_DEMANDEE_VOCALE = (
    "Une vérification en ligne est demandée pour : « {question} ». Appelle "
    "web_search maintenant avec une requête précise, sans parler avant "
    "l'appel ; puis réponds en une ou deux phrases parlées d'après les "
    "résultats : nomme la source (le site) et dis la date en toutes lettres "
    "— jamais de numéro entre crochets ni d'adresse web. Si tu ne trouves "
    "rien, dis-le ; ne confirme jamais de mémoire."
)
# La relance, une seule fois, quand le premier passage a parlé sans chercher.
CONSIGNE_FERME_VOCALE = (
    "Tu viens de répondre sans appeler web_search. Appelle web_search "
    "maintenant, sans parler avant l'appel ; puis dis en une phrase ce que "
    "les résultats donnent, en nommant la source — si cela contredit ce que "
    "tu viens de dire, dis-le."
)
# Ce que la voix dit quand rien n'a été vérifié : court, prononçable, et à
# la fin — la réponse est déjà sortie des haut-parleurs.
AVEU_VOCAL = "Je le dis de mémoire, sans avoir pu vérifier en ligne."
AVEU_VOCAL_RECHERCHE = "La recherche n'a rien donné : je le dis de mémoire."
AVEU_VOCAL_REFUS = "Je n'ai pas pu chercher en ligne : je le dis de mémoire."
# Ce que la voix dit pendant que la recherche tourne — le silence d'une
# recherche et d'une lecture (une à trois secondes) n'était signalé par rien.
ACCUSE_RECHERCHE = "Je vérifie en ligne."
# La réponse porte déjà son aveu : pas de second.
_DEJA_AVOUE = re.compile(
    r"pas (?:pu|reussi a) (?:le |la |les )?verifier|impossible de verifier|"
    r"de memoire|sans (?:avoir )?verifi|non verifi|n'a rien donne|a echoue|"
    r"je ne peux pas verifier|je n'ai pas acces",
)
# Ces formes, dites au micro, arrivent souvent sans point d'interrogation :
# Whisper ne le pose pas toujours. L'énoncé ENTIER doit être la forme.
_DEMANDE_SANS_PONCTUATION = frozenset(
    {
        "c'est vrai",
        "c'est vrai ca",
        "c'est sur",
        "vraiment",
        "ah bon",
        "t'es sur",
        "tu es sur",
        "es-tu sur",
        "t'es sur de ca",
        "tu es sur de ca",
        "serieux",
    }
)
# Une question de moins de douze caractères n'est pas une question de fait :
# « Vérifie ça » après « Diapason ? » demandait de vérifier « Oui ? ».
_QUESTION_MIN = 12
# Les mêmes plafonds que le chat (MAX_TOOL_RESULT_CHARS) : la recherche et
# la page lue ont chacune le leur, pour que l'une ne mange pas l'autre.
PLAFOND_CARACTERES = 4000
# Ce que le modèle n'a pas à lire : la liste structurée des sources (le
# texte est numéroté), les plans de recherche, les arguments rejoués.
_META_TECHNIQUE = frozenset({"sources", "plans", "arguments", "persistence", "when"})


@dataclass
class TourVocal:
    """Ce qu'un tour d'actualité accumule, du micro au dernier mot."""

    question: str
    demande: bool = False
    recherche_tentee: bool = False
    recherche_refusee: bool = False
    verification_faite: bool = False
    outil_local_ok: bool = False
    relance_faite: bool = False
    lecture_faite: bool = False
    sources: list[dict[str, Any]] = field(default_factory=list)
    pages_lues: set[str] = field(default_factory=set)
    corpus: str = ""


def _en_messages(historique: Sequence[dict[str, Any]], texte: str) -> list[Message]:
    messages = [
        Message(role=Role(m["role"]), content=str(m.get("content") or ""))
        for m in historique
        if m.get("role") in ("user", "assistant")
    ]
    messages.append(Message(role=Role.USER, content=texte))
    return messages


def _plat(texte: str) -> str:
    import unicodedata

    plat = "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    )
    return re.sub(r"[\s.!?,]+$", "", plat.replace("’", "'")).strip()


def est_une_demande_vocale(texte: str) -> bool:
    """« Vérifie ça » et ses formes ; à la voix, aussi « c'est vrai » et
    « vraiment » sans ponctuation, quand c'est tout l'énoncé."""
    return (
        est_une_demande_de_verification(texte)
        or _plat(texte) in _DEMANDE_SANS_PONCTUATION
    )


def preparer_tour(texte: str, historique: Sequence[dict[str, Any]]) -> TourVocal | None:
    """Le tour est-il une question d'actualité, ou une demande de vérifier
    ce qui vient d'être dit ? None quand la voix n'a rien à garder."""
    if est_une_demande_vocale(texte):
        question = question_a_verifier(_en_messages(historique, texte + " ?"))
        if (
            est_une_demande_vocale(question)
            or len(question.strip()) < _QUESTION_MIN
            or question_personnelle(question)
        ):
            return None
        return TourVocal(question=question, demande=True)
    if question_d_actualite(texte):
        return TourVocal(question=texte)
    return None


def consigne(tour: TourVocal) -> dict[str, str]:
    """La consigne au tour courant, après la demande — là où le 9b obéit."""
    if tour.demande:
        return {
            "role": "system",
            "content": CONSIGNE_DEMANDEE_VOCALE.format(question=tour.question.strip()),
        }
    return {"role": "system", "content": CONSIGNE_VOCALE}


def relance(tour: TourVocal, parle: str) -> list[dict[str, str]]:
    """Le premier passage a parlé sans chercher : ce qui a été dit reste dans
    le fil (c'est sorti des haut-parleurs), et une sommation suit."""
    tour.relance_faite = True
    return [
        {"role": "assistant", "content": parle.strip()},
        {"role": "system", "content": CONSIGNE_FERME_VOCALE},
    ]


def preparer_appel(
    tour: TourVocal, nom: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Fraîcheur et vertical décidés par le code, pas par le modèle."""
    if nom != "web_search":
        return arguments
    try:
        complets = json.loads(
            completer_arguments(
                json.dumps(arguments, ensure_ascii=False), tour.question
            )
        )
    except (ValueError, TypeError):
        return arguments
    return complets if isinstance(complets, dict) else arguments


def deja_lue(
    tour: TourVocal, nom: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Le modèle redemande la page que le code vient de lire : la réponse,
    sans réseau (revue du 21/09 : deux téléchargements, le même texte deux
    fois dans le fil)."""
    if nom != "web_read":
        return None
    from diapason.tools.web_search import url_canonique

    url = str(arguments.get("url") or "")
    if url and url_canonique(url) in tour.pages_lues:
        ref = next(
            (
                s["ref"]
                for s in tour.sources
                if url_canonique(str(s.get("url") or "")) == url_canonique(url)
            ),
            None,
        )
        ou = f" sous le numéro {ref}" if ref else ""
        return {"ok": True, "content": f"Cette page est déjà lue ci-dessus{ou}."}
    return None


Lecteur = Callable[[str, dict[str, Any]], dict[str, Any]]


def _tronquer(texte: str) -> str:
    if len(texte) <= PLAFOND_CARACTERES:
        return texte
    reste = len(texte) - PLAFOND_CARACTERES
    return texte[:PLAFOND_CARACTERES] + f"\n[… {reste} caractères de plus, tronqués]"


def _pour_le_modele(resultat: dict[str, Any]) -> dict[str, Any]:
    """Le résultat sans ce que le modèle n'a pas à lire, borné."""
    meta = (
        resultat.get("metadata") if isinstance(resultat.get("metadata"), dict) else {}
    )
    utile = {k: v for k, v in meta.items() if k not in _META_TECHNIQUE}
    propre = {k: v for k, v in resultat.items() if k != "metadata"}
    if utile:
        propre["metadata"] = utile
    return propre


def absorber_resultat(
    tour: TourVocal,
    nom: str,
    arguments: dict[str, Any],
    resultat: dict[str, Any],
    lire: Lecteur | None = None,
) -> dict[str, Any]:
    """Après un outil : les sources numérotées rejoignent le tour, et pour un
    titulaire la page du poste est lue et jointe au résultat — exactement
    ce que fait agentic_stream pour le chat. Rend ce que le MODÈLE lit."""
    contenu = str(resultat.get("content") or "")
    ok = bool(resultat.get("ok"))
    meta = (
        resultat.get("metadata") if isinstance(resultat.get("metadata"), dict) else {}
    )
    if nom == "web_search":
        tour.recherche_tentee = True
        if not ok and not recherche_concluante(nom, ok, contenu):
            tour.recherche_refusee = (
                tour.recherche_refusee
                or not contenu.strip()
                or bool(resultat.get("error"))
            )
        if not recherche_concluante(nom, ok, contenu):
            return _pour_le_modele(resultat)
    elif nom == "web_read":
        if not ok:
            return _pour_le_modele(resultat)
    else:
        if ok:
            tour.outil_local_ok = True
        return resultat
    from diapason.tools.web_search import url_canonique

    tour.verification_faite = True
    sources = meta.get("sources") or []
    if nom == "web_read":
        url = str(arguments.get("url") or "")
        sources = sous_l_url_demandee(list(sources), url)
        if url:
            tour.pages_lues.add(url_canonique(url))
    contenu, nouvelles = renumeroter(contenu, sources, tour.sources)
    tour.sources.extend(nouvelles)
    tour.corpus += "\n" + contenu
    contenu = _tronquer(contenu)
    if (
        nom == "web_search"
        and lire is not None
        and not tour.lecture_faite
        and question_de_titulaire(tour.question)
    ):
        url = page_de_reference(tour.sources, tour.question)
        if url:
            tour.lecture_faite = True
            page = lire("web_read", {"url": url, "focus": tour.question})
            if page.get("ok") and str(page.get("content") or "").strip():
                pmeta = (
                    page.get("metadata")
                    if isinstance(page.get("metadata"), dict)
                    else {}
                )
                texte, nv = renumeroter(
                    str(page["content"]),
                    sous_l_url_demandee(list(pmeta.get("sources") or []), url),
                    tour.sources,
                )
                tour.sources.extend(nv)
                tour.corpus += "\n" + texte
                tour.pages_lues.add(url_canonique(url))
                contenu += "\n\nPage lue (web_read) :\n" + _tronquer(texte)
            else:
                raison = str(page.get("error") or page.get("content") or "")[:200]
                contenu += f"\n\nPage du poste non lue ({url}) : {raison}"
    return _pour_le_modele({**resultat, "content": contenu})


def note(tour: TourVocal) -> dict[str, str] | None:
    """Ce que le code sait des sources, dit au modèle avant qu'il rédige."""
    if not tour.corpus.strip():
        return None
    texte, _donnees = note_avant_redaction(tour.sources, tour.corpus, tour.question)
    return {"role": "system", "content": texte} if texte else None


def _affirme_quelque_chose(reponse: str) -> bool:
    """Une question de précision, un aveu ou une phrase sans nom, nombre ni
    année n'affirment rien : « je le dis de mémoire » n'y a pas sa place."""
    plat = _plat(reponse)
    if not plat or reponse.strip().endswith("?"):
        return False
    if re.search(r"\d", reponse):
        return True
    # Un nom propre hors tête de phrase : « C'est Carney. », « Mark Carney ».
    for phrase in re.split(r"(?<=[.!?])\s+", reponse.strip()):
        mots = phrase.split()
        if any(re.match(r"^[A-ZÀ-Ý][\wÀ-ÿ'’-]{2,}", m) for m in mots[1:]):
            return True
    return False


def epilogue(tour: TourVocal, reponse: str) -> str:
    """La phrase à prononcer après la réponse, ou "" : de mémoire, ou en
    désaccord avec les sources sur le titulaire.

    Revue vocale du 21/09 : « je le dis de mémoire » était prononcé après une
    réponse vide, après une question de précision, après un aveu déjà dit,
    et après un fait lu à l'horloge locale. Chacun de ces cas se tait ; une
    réponse vide reçoit l'aveu qui se tient seul.
    """
    if _DEJA_AVOUE.search(_plat(reponse)):
        return ""
    if not tour.verification_faite:
        if tour.outil_local_ok and not tour.recherche_tentee:
            return ""
        if not reponse.strip():
            return AVEU
        if not _affirme_quelque_chose(reponse):
            return ""
        if tour.recherche_refusee:
            return AVEU_VOCAL_REFUS
        return AVEU_VOCAL_RECHERCHE if tour.recherche_tentee else AVEU_VOCAL
    desaccord = desaccord_sur_le_titulaire(reponse, tour.corpus, tour.question)
    if desaccord:
        return (
            f"Attention : les sources désignent {', '.join(desaccord['sources'])} "
            f"comme titulaire, pas {desaccord['answer']}."
        )
    return ""


__all__ = [
    "ACCUSE_RECHERCHE",
    "AVEU_VOCAL",
    "AVEU_VOCAL_RECHERCHE",
    "AVEU_VOCAL_REFUS",
    "CONSIGNE_FERME_VOCALE",
    "CONSIGNE_VOCALE",
    "TourVocal",
    "absorber_resultat",
    "consigne",
    "deja_lue",
    "epilogue",
    "est_une_demande_vocale",
    "note",
    "preparer_appel",
    "preparer_tour",
    "relance",
]
