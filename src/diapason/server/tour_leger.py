"""Un modèle léger pour les tours courts ; le modèle choisi garde les tâches lourdes.

20 septembre 2026 : Carlito avait choisi qwen3.8:27b-mlx dans le sélecteur du
chat. Ce modèle tient 18 à 26 Go sur un Mac de 32 Go qui n'en avait que
10,5 de libres au chargement (journal d'Ollama, 10:54:14). Résultat sur deux
questions d'une ligne : « Qui est le président actuel d'Haïti ? » 56,6 s,
« Que veut dire "Self Aware" en français ? » 89,4 s — pendant que « Ouvre
moi YouTube et joue… », servi sans modèle par la voie éclair, prenait 1,2 s.
Le classificateur de complexité marquait les deux « trivial » (0,06) mais ne
changeait que le budget de jetons, jamais le modèle. Ses motifs sont anglais
(explain, why, write) : en français presque tout est « trivial », il ne peut
donc pas servir de critère de routage.

Règle : quand [intelligence].light_model est configuré, un tour LÉGER part
sur ce modèle et le modèle choisi reste pour le reste. Léger = une demande
d'une ou deux lignes, sans image, sans code, sans quantité (« 30
exercices »), sans production ni raisonnement demandé. Le modèle réellement
utilisé est écrit dans chaque fragment (model) et dans le bilan (routing) :
rien n'est fait semblant. Une trousse fournie par le client (API brute) et
un modèle distant ne sont jamais reroutés.

Limite connue, mesurée : deux modèles ne cohabitent pas quand le lourd
occupe la mémoire. Recharger le 27b après un tour léger coûte 7 s de
démarrage plus une première passe qui repagine 18 Go (1 min 38 s le 20
septembre à 10:55) ; choisir le 27b dans le sélecteur le précharge, et un
premier message léger l'évince aussitôt. Une suite (« Continue ») garde le
modèle du tour qu'elle prolonge, mais une question neuve change de modèle.
Sur cette machine, le remède de fond reste le 9b comme modèle du quotidien —
ce routage évite seulement de payer le 27b pour une traduction.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from diapason.core.types import Message, Role
from diapason.server.reponses_longues import quantite_du_tour

# Deux lignes de chat. Les deux questions du 20 septembre faisaient 35 et
# 40 caractères ; « Prépare moi un programme pour la programmation » (47)
# est écarté par les verbes de production, pas par la longueur.
LONGUEUR_MAX = 160

# Production, raisonnement, transformation d'un texte : le modèle choisi.
# Des VERBES en tête de phrase (ou après « peux-tu… »), jamais des noms
# seuls : revue du 20/09 — « Quel cours j'ai demain ? », « C'est quoi le
# plan aujourd'hui ? », « As-tu reçu un courriel ? » restaient sur le 27b
# parce que « cours », « plan », « courriel » figuraient dans la liste.
# « explique » et « pourquoi » y sont à dessein — une explication est ce pour
# quoi on choisit un grand modèle ; « que veut dire » et « traduis » n'y sont
# pas : un mot, une phrase, le petit modèle suffit.
_IMPERATIF = re.compile(
    r"^(?:(?:est.ce que |es.tu capable de |serais.tu capable de )?"
    r"(?:peux.tu|pourrais.tu|tu peux|tu pourrais|je veux que tu|j'aimerais que tu|"
    r"je voudrais que tu|can you|could you|please)\s+)?"
    r"(?:me |m'|nous |te |lui )?"
    r"(?:redig|ecri|prepar|conc|elabor|gener|cre|construi|develop|implement|"
    r"cod|programm|script|resum|synthetis|analys|compar|expliqu|demontr|prouv|"
    r"resou|corrig|reformul|amelior|invent|imagin|compos|propos|fais|fait|faire|"
    r"write|draft|generate|create|build|implement|code|explain|analy[sz]|compare|"
    r"summari[sz]|prove|solve|compose|make|design)\w*\b"
)
# Raisonnement demandé, où qu'il soit dans la phrase.
_RAISONNEMENT = re.compile(
    r"\b(?:pourquoi|why|demontre|prouve|resous|resoudre|derivee|integrale|"
    r"equation|theoreme|prove|solve|derivative|integral)\b"
)
# Revue du 20/09/2026 : « Continue », « Plus long », « Traduis-la », « Ajoute
# un paragraphe » après une lettre rédigée par le 27b partaient sur le 9b, qui
# évinçait le 27b, relisait tout le fil et prolongeait la lettre d'un autre
# style. Une suite reprend le modèle du tour qu'elle prolonge.
_SUITE = re.compile(
    r"^(?:continue|poursuis|encore|suite|la suite|plus (?:long|court|detaille|"
    r"simple|formel|familier)|ajoute|enleve|retire|supprime|change|remplace|"
    r"reformule|reecris|reprends|developpe|raccourcis|allonge|termine|finis|"
    r"complete|refais|recommence|meme chose|pareil|idem|en (?:anglais|francais|"
    r"espagnol|creole)|version|(?:traduis|resume|corrige|ameliore|adapte)"
    r"(?:-| )?(?:le|la|les|ca|moi ca)\b|continue|go on|more|longer|shorter|"
    r"again|redo|translate (?:it|this|that))\b"
)
_CODE = re.compile(
    r"```|`[^`]+`|\{\s*\}|=>|->|\bdef\s|\bfunction\b|\bimport\s|"
    r"\b(?:script|regex|sql|json|python|javascript|typescript|rust|bash|html|css)\b|"
    r"[²³^]|\d\s*[+*/×÷]\s*\d"
)


@dataclass(frozen=True)
class Routage:
    """Le modèle du tour, et d'où il vient quand il a changé."""

    modele: str
    origine: str | None = None
    motif: str = ""

    @property
    def substitue(self) -> bool:
        return self.origine is not None

    def public(self) -> dict[str, Any]:
        return {"model": self.modele, "from": self.origine, "reason": self.motif}


def _normaliser(texte: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    )


def _legere_en_soi(demande: Message) -> bool:
    if demande.images:
        return False
    texte = (demande.content or "").strip()
    if not texte or len(texte) > LONGUEUR_MAX or "\n" in texte:
        return False
    if quantite_du_tour([demande]):
        return False
    plat = _normaliser(texte)
    if _CODE.search(plat) or _RAISONNEMENT.search(plat):
        return False
    return not _IMPERATIF.search(plat)


def _est_une_suite(demande: Message) -> bool:
    plat = _normaliser((demande.content or "").strip())
    return bool(_SUITE.search(plat)) or len(plat.split()) <= 3


def est_un_tour_leger(messages: Sequence[Message]) -> bool:
    """Vrai si la demande courante se règle bien avec un petit modèle.

    Le poids se propage : une suite (« Continue », « Plus court », trois mots
    ou moins) garde le poids du tour qu'elle prolonge, de proche en proche —
    « Rédige… » → « Continue » → « Encore » restent sur le modèle choisi.
    """
    leger = False
    premiere = True
    for demande in (m for m in messages if m.role == Role.USER):
        propre = _legere_en_soi(demande)
        if propre and not premiere and not leger and _est_une_suite(demande):
            propre = False
        leger, premiere = propre, False
    return leger and not premiere


# Revue du 20/09/2026 : un light_model mal orthographié ou pas encore tiré
# cassait TOUS les tours courts (404 d'Ollama) alors que le modèle demandé
# aurait répondu. On ne reroute que vers un modèle qu'Ollama liste ; la
# liste est relue au plus toutes les 60 s (GET /api/tags, ~3 ms).
DISPONIBILITE_TTL_S = 60.0
_disponibles: dict[str, tuple[float, frozenset[str]]] = {}


def modele_disponible(engine: Any, modele: str, *, horloge=time.monotonic) -> bool:
    lister = getattr(engine, "list_models", None)
    if lister is None:
        return True  # rien ne permet de vérifier : on fait confiance à la config
    cle = str(getattr(engine, "_host", "") or id(engine))
    maintenant = horloge()
    entree = _disponibles.get(cle)
    if entree is None or maintenant - entree[0] > DISPONIBILITE_TTL_S:
        try:
            noms = frozenset(str(n) for n in lister() or ())
        except Exception:  # noqa: BLE001 - un listing en panne ne route rien
            noms = frozenset()
        entree = (maintenant, noms)
        _disponibles[cle] = entree
    return modele in entree[1]


def choisir_le_modele(
    modele: str,
    messages: Sequence[Message],
    config: Any,
    *,
    trousse_du_client: bool = False,
    engine: Any = None,
) -> Routage:
    """Le léger configuré pour un tour léger ; sinon le modèle demandé."""
    intelligence = getattr(config, "intelligence", None)
    leger = str(getattr(intelligence, "light_model", "") or "").strip()
    if not leger or trousse_du_client:
        return Routage(modele)
    demande = modele
    if modele in ("", "default"):
        demande = str(getattr(intelligence, "default_model", "") or modele)
    if demande == leger or _est_distant(demande):
        return Routage(modele)
    if not est_un_tour_leger(messages):
        return Routage(modele)
    if engine is not None and not modele_disponible(engine, leger):
        return Routage(modele)
    return Routage(leger, origine=demande, motif="tour léger")


def _est_distant(modele: str) -> bool:
    try:
        from diapason.server.cloud_router import is_cloud_model
    except Exception:  # noqa: BLE001 - sans routeur cloud, tout est local
        return False
    return bool(is_cloud_model(modele))
