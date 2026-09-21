"""La trousse du chat : stable par défaut, adaptative sur demande.

20 septembre 2026 — la trousse qui change coûte plus cher que la trousse
lourde. Ollama (llama-server, un créneau) réutilise le préfixe calculé du
tour précédent ; les schémas d'outils sont rendus en TÊTE du prompt, donc
toute variation de la trousse invalide tout ce qui suit. Banc de cinq tours
sur le 9b, même conversation, trousse adaptative :

    tâches (catalogue + 2)  préremplissage 9,1 s  — froid
    capitale du Pérou (45)                24,4 s  — froid
    mes notes (catalogue + 1)              8,4 s  — froid, puis relecture 2,9 s
    capitale du Chili (45)                 2,9 s  — chaud : même trousse que le Pérou
    tâches en retard (catalogue + 2)       9,0 s  — froid

Quatre tours sur cinq à froid ; le seul tour chaud est celui dont la trousse
était identique au précédent tour de même forme. Une trousse unique pour
toute la conversation — et pour TOUTES les conversations, le préfixe étant
le même partout — ne se paie qu'au chargement du modèle.

Le mode adaptatif du 19 septembre (catalogue léger + schémas des familles
reconnues, relecture d'une réponse sans appel) reste disponible :
``[agent] trousse_adaptative = true``. Il gardait l'accès à TOUS les outils
(les paramètres seuls étaient différés) et valait pour un premier tour à
froid : 3 441 jetons au lieu de 10 231.

Ce qui varie encore, mesuré ou lu le 20 septembre : un « Merci ! » part
sans trousse (préfixe = identité seule, 4,2 s de préremplissage pour 1 843
jetons) mais llama-server garde le préfixe outillé en cache — le tour
suivant est revenu chaud à 2,7 s ; le tour qui répond à un questionnaire
retire le schéma des questions (46 → 45) et le passage sans outils après
trois actions retire tout le bloc : un recalcul de l'historique chacun,
rares. La relecture avant affichage n'a plus d'objet avec tous les schémas ;
le modèle qui affirme sans lire reste possible, comme avant le 19 septembre.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from diapason.core.types import Message, Role
from diapason.server.reponses_longues import quantite_du_tour

CHARGER_OUTILS = "diapason_load_tools"
# Sous 8 000 caractères, le catalogue et un éventuel aller-retour coûtent plus
# que la petite trousse. La trousse par défaut en pesait presque quatre fois plus.
SEUIL_CATALOGUE = 8000
# Deux demandes de schémas au plus : la seconde expose le reste de la trousse
# pour éviter une chaîne de découvertes qui affamerait la réponse locale.
MAX_CHARGEMENTS = 2

# Ces indices préchargent ; ils n'autorisent ni n'interdisent rien. Une phrase
# inconnue garde le catalogue et les suites conservent leurs appels antérieurs.
_GROUPES = (
    (r"\b(taches?|tasks?|sous.taches?)\b", ("succes_tasks", "current_time")),
    (
        r"\b(projets?|projects?|habitudes?|habits?|notes?|carnets?)\b",
        ("succes_workspace",),
    ),
    (r"\b(routines?|citations?|bilan)\b", ("succes_continuity",)),
    (r"\b(finances?|budgets?|depenses?|revenus?|comptes?)\b", ("succes_finances",)),
    (
        r"\b(agenda|calendrier|calendar|rendez.vous)\b",
        ("calendar_query", "current_time"),
    ),
    (r"\b(heure|time|date|aujourd.hui|demain|hier)\b", ("current_time",)),
    (
        r"\b(cherche|recherche|search|web|internet|actualites?)\b",
        ("web_search", "web_read"),
    ),
    (r"\b(mails?|emails?|courriels?|gmail)\b", ("gmail_search", "digest_collect")),
    (r"\b(messages?|imessage|sms)\b", ("imessage_conversation", "messages_status")),
    (r"\b(ecran|screen|capture|vois|voici)\b", ("screen_describe", "screen_read_text")),
    (
        r"\b(fichiers?|documents?)\b",
        ("find_files", "knowledge_search", "knowledge_get_document"),
    ),
    (r"\b(ouvre|ouvrir|open|lance|onglets?)\b", ("open_anything", "browser_tabs")),
    (
        r"\b(appareils?|telephone|pc|windows|transfere|envoie)\b",
        ("mesh_devices", "handoff_continue"),
    ),
    (
        r"\b(souviens|retiens|memorise|memoire)\b",
        ("memory_manage", "user_profile_manage"),
    ),
    (
        r"\b(musique|spotify|pause|volume|son)\b",
        ("spotify_play", "media_control", "volume_control"),
    ),
    (r"\b(calcule|calcul|combien)\b|\d\s*[+*/×÷]\s*\d", ("calculator",)),
)
_INDICES = [(re.compile(motif), noms) for motif, noms in _GROUPES]
# 20/09/2026 : « Que veut dire "Self Aware" en français ? » a coûté 89 s sur
# le 27b, dont 88 s sans un mot à l'écran. Le tour précédent parlait de
# musique (« Ouvre moi Youtube et joue… ») et un web_search traînait dans
# l'historique : la trousse était réduite, la réponse directe — juste — a
# été retenue puis rejouée avec les 44 schémas (53 s + 36 s, journal
# d'Ollama). Une relecture n'a de sens que si l'absence d'appel rend la
# réponse invérifiable : la demande parle de données que le modèle ne peut
# pas connaître. Les MOTS comptent, pas les outils amorcés : « ouvre » et
# « onglets » amorcent le même browser_tabs, « envoie » amorce mesh_devices —
# revue du 20/09 : « Envoie-moi une blague » était relue avec 44 schémas.
_LECTURE = re.compile(
    r"\b(taches?|tasks?|sous.taches?|projets?|projects?|habitudes?|habits?|"
    r"notes?|carnets?|routines?|citations?|bilan|finances?|budgets?|depenses?|"
    r"revenus?|comptes?|agenda|calendrier|calendar|rendez.vous|cherche|recherche|"
    r"search|web|internet|actualites?|mails?|emails?|courriels?|gmail|messages?|"
    r"imessage|sms|ecran|screen|capture|fichiers?|documents?|onglets?|appareils?)\b"
)
# Les outils dont un résultat, au tour précédent, fait d'un suivi court une
# suite de lecture (« Et demain ? » après les tâches). Une action (Spotify,
# ouvrir) ne fait pas d'un suivi une demande de données.
_LECTURES = frozenset(
    {
        "succes_tasks",
        "succes_workspace",
        "succes_continuity",
        "succes_finances",
        "calendar_query",
        "web_search",
        "web_read",
        "gmail_search",
        "digest_collect",
        "imessage_conversation",
        "messages_status",
        "screen_describe",
        "screen_read_text",
        "find_files",
        "knowledge_search",
        "knowledge_get_document",
        "mesh_devices",
        "browser_tabs",
    }
)
# Un suivi court ne redemande des données que s'il interroge (« ? »), enchaîne
# (« Et les urgentes ») ou commence par un mot de question ou de lecture.
# Revue du 20/09 : « Merci, c'est toi qui gères ! » et « Bof, plus ou moins »
# étaient relus parce que « qui » et « ou » traînaient au milieu.
_SUIVI_DE_LECTURE = re.compile(
    r"\?|^(?:et|puis|aussi|ensuite)\b|"
    r"^(?:quoi|quel|quelle|quels|quelles|combien|quand|qui|montre|liste|donne|"
    r"affiche|lis|verifie|regarde|cherche|what|which|when|where|who|how|show|"
    r"list|check)\b"
)
# Revue du 20/09/2026 : « que veut dire », « traduis », « c'est quoi » sont des
# réponses autonomes au même titre qu'« explique » — sans référence à quelque
# chose de personnel (_REFERENCE), un mot ou une phrase n'ont besoin d'aucun
# outil, et le catalogue seul suffit.
_REDACTION = re.compile(
    r"^(?:(?:peux.tu|pourrais.tu|tu peux)\s+)?"
    r"(?:explique|explain|definis|define|raconte|invente|conjugue|conjugate|"
    r"traduis|traduire|translate|epelle|prononce|"
    r"que veut dire|que signifie|c'est quoi|qu'est.ce que c'est|qu'est.ce qu'|"
    r"comment (?:dit.on|on dit|traduire|ecrire|s'ecrit|se dit)|"
    r"what does .* mean|how do you say|what is the meaning)\b"
)
# 19/09/2026 : « Prépare moi un programme pour la programmation » envoyait
# les 44 schémas complets au 14b : 57,8 s pour répéter la demande. Revue du
# 20/09 : ces 57,8 s étaient le préremplissage à FROID d'un modèle qui venait
# d'être chargé, pas un coût de qualité des schémas — chaud, la même trousse
# coûte ~3 s (banc du 20/09) ; les 13 jetons qui répétaient la demande sont
# un symptôme non mesuré. Le catalogue ne vaut donc qu'en mode adaptatif.
_CONCEPTION = re.compile(
    r"^(?:(?:peux.tu|pourrais.tu|tu peux)\s+)?"
    r"(?:prepare(?:r)?|concois|concevoir|elabore(?:r)?|cree(?:r)?|fais|faire)\b[\s-]*"
    r"(?:(?:moi|nous)\s+)?(?:un |une |le |la )?"
    r"(?:programme|plan|parcours)\b"
)
_REFERENCE = re.compile(
    r"\b(je|j|nous|mon|ma|mes|notre|nos|ton|ta|tes|votre|vos|my|our|your|"
    r"ca|cela|ceci|ci.dessus|piece.jointe|fichier|document|source|lien|url|"
    r"actuel|actuelle|recent|recente|dernier|derniere|latest|current|"
    r"recu|ordinateur|machine|ecran|appareil|outil)\b|"
    r"https?://|\b20\d{2}\b"
)


def _demande_de_lecture(messages: Sequence[Message]) -> bool:
    """Vrai si la demande courante porte sur des données à lire.

    Seule la demande courante compte pour les indices : le message
    précédent ne fait qu'amorcer des schémas. Un suivi court hérite du
    sujet seulement si le tour précédent a réellement lu quelque chose et
    si ce suivi enchaîne ou interroge.
    """
    demandes = [m for m in messages if m.role == Role.USER]
    if not demandes:
        return False
    texte = _normaliser(demandes[-1].content or "").strip()
    if _LECTURE.search(texte):
        return True
    if len(texte) >= 100 or len(demandes) < 2 or not _SUIVI_DE_LECTURE.search(texte):
        return False
    # Seul le tour précédent compte : un web_search trois échanges plus haut
    # ne fait pas d'une question de vocabulaire une demande de données.
    precedente = demandes[-2]
    debut = next(i for i, m in enumerate(messages) if m is precedente)
    tour_precedent = messages[debut + 1 : -1]
    return any(
        appel.name in _LECTURES
        for message in tour_precedent
        for appel in message.tool_calls or []
    )


def _normaliser(texte: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    )


def _indices(texte: str) -> set[str]:
    noms: set[str] = set()
    for motif, groupe in _INDICES:
        if motif.search(texte):
            noms.update(groupe)
    return noms


def _amorcer(messages: Sequence[Message]) -> tuple[set[str], bool]:
    """Les schémas à précharger, et si la demande courante est RECONNUE.

    Seule une demande reconnue justifie de différer les autres schémas.
    Revue du 20/09/2026 : « Mets la musique Self Aware sur Spotify » puis
    « Est-ce que Carlito m'a répondu ? » — la demande précédente, fusionnée
    parce que la courante est courte, réduisait la trousse à Spotify, et le
    modèle répondait « non » sans lire les messages. La précédente ne fait
    plus qu'AJOUTER des schémas ; elle ne rend pas la courante connue.
    """
    demandes = [m.content or "" for m in messages if m.role == Role.USER]
    courant = _normaliser(demandes[-1]) if demandes else ""
    propres = _indices(courant)
    noms = set(propres)
    # Une réponse autonome (traduction, explication) n'embarque pas les
    # schémas du tour d'avant : « Que veut dire… » après « joue la musique »
    # recevait Spotify, le volume et un web_search dont elle n'a que faire.
    if not _redaction_autonome(messages):
        # « Et demain ? » n'efface pas la demande précédente. Un vrai changement
        # de sujet n'embarque pas en permanence les outils de tout l'historique.
        if len(courant) < 100 and len(demandes) > 1:
            noms |= _indices(_normaliser(demandes[-2]))
        for message in messages[-8:]:
            for appel in message.tool_calls or []:
                noms.add(appel.name)
    # « Qu'est-ce que j'ai reçu aujourd'hui ? » n'était reconnu que par
    # « aujourd'hui » — trousse réduite à l'horloge, et le modèle affirmait
    # « rien reçu » sans lire. Un mot de temps seul ne fait pas une demande
    # connue : elle garde les schémas complets.
    connue = bool(propres - {"current_time"}) or _demande_de_lecture(messages)
    return noms, connue


def _redaction_autonome(messages: Sequence[Message]) -> bool:
    demande = next((m for m in reversed(messages) if m.role == Role.USER), None)
    if demande is None or demande.images:
        return False
    texte = _normaliser(demande.content or "").strip()
    texte = re.sub(r"\bsans (?:utiliser )?(?:un |aucun |d['’])?outils?\b", "", texte)
    if _REFERENCE.search(texte):
        return False
    return bool(
        _REDACTION.search(texte)
        or (
            _CONCEPTION.search(texte)
            and not any(motif.search(texte) for motif, _ in _INDICES)
        )
        or quantite_du_tour(messages)
    )


def _taille(specs: list[dict[str, Any]]) -> int:
    return len(json.dumps(specs, ensure_ascii=False, separators=(",", ":")))


class TrousseChat:
    """Sélection propre au tour ; aucune mutation du registre ou de l'exécuteur."""

    def __init__(
        self,
        tools: Sequence[Any],
        messages: Sequence[Message],
        *,
        adaptative: bool = False,
    ):
        self._specs = [outil.to_openai_function() for outil in tools]
        self.noms = {s["function"]["name"] for s in self._specs}
        self._charges = 0
        amorces, connue = _amorcer(messages)
        self._actifs = amorces & self.noms
        self._lecture_attendue = _demande_de_lecture(messages)
        catalogue = "\n".join(
            s["function"]["name"]
            + ": "
            + re.split(
                r"(?<=[.!?])\s", s["function"].get("description", ""), maxsplit=1
            )[0][:180]
            for s in self._specs
        )
        self._chargement = {
            "type": "function",
            "function": {
                "name": CHARGER_OUTILS,
                "description": (
                    "Charge les paramètres des outils du catalogue ci-dessous. "
                    "Pour lire ou modifier des données personnelles, "
                    "appelle l'outil réel : "
                    "ne les invente pas. Si son schéma est absent, "
                    "charge-le ici puis utilise-le. "
                    "Pour une explication ou rédaction autonome, réponds directement. "
                    "Charger un schéma n'exécute aucune action. Catalogue :\n"
                    + catalogue
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "toolNames": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        }
                    },
                    "required": ["toolNames"],
                },
            },
        }
        self._differee = (
            adaptative
            and CHARGER_OUTILS not in self.noms
            and _taille(self._specs) > SEUIL_CATALOGUE
            # Essai réel du 19/09 : « J'ai reçu quoi ? » avec catalogue seul
            # produisait une absence de messages inventée. Une demande inconnue
            # garde donc les schémas complets ; les indices ne sont pas un plafond.
            and (connue or _redaction_autonome(messages))
            and _taille(self._selection()) < _taille(self._specs)
        )

    def _selection(self) -> list[dict[str, Any]]:
        return [
            self._chargement,
            *[s for s in self._specs if s["function"]["name"] in self._actifs],
        ]

    @property
    def specs(self) -> list[dict[str, Any]]:
        if not self._differee or self._actifs == self.noms:
            return self._specs
        selection = self._selection()
        return selection if _taille(selection) < _taille(self._specs) else self._specs

    def est_chargement(self, nom: str) -> bool:
        return self._differee and nom == CHARGER_OUTILS

    def verifier_lecture(self, messages: Sequence[Message]) -> bool:
        return (
            self._differee
            and self._lecture_attendue
            and self.specs[0]["function"]["name"] == CHARGER_OUTILS
            and not _redaction_autonome(messages)
        )

    def elargir(self) -> None:
        self._actifs = set(self.noms)

    def charger(self, arguments: str) -> str:
        self._charges += 1
        try:
            donnees = json.loads(arguments)
            noms = donnees.get("toolNames") if isinstance(donnees, dict) else None
            if (
                not isinstance(noms, list)
                or not noms
                or not all(isinstance(n, str) for n in noms)
            ):
                raise ValueError(
                    "toolNames doit être une liste non vide de noms d'outils."
                )
        except (ValueError, TypeError) as exc:
            # Un modèle qui ne comprend pas la découverte retrouve la trousse
            # ordinaire, sans gagner de nouvelles permissions ni boucler.
            self._actifs = set(self.noms)
            return json.dumps(
                {
                    "error": str(exc),
                    "detail": "Les schémas autorisés sont maintenant disponibles.",
                },
                ensure_ascii=False,
            )
        refuses = sorted(set(noms) - self.noms)
        self._actifs.update(set(noms) & self.noms)
        if self._charges >= MAX_CHARGEMENTS:
            self._actifs = set(self.noms)
        return json.dumps(
            {
                "loaded": sorted(self._actifs),
                "unavailable": refuses,
                "detail": (
                    "Schémas disponibles au prochain appel. "
                    "Aucune donnée lue ni action exécutée. "
                    "Utilise l'outil réel pour obtenir un résultat."
                ),
            },
            ensure_ascii=False,
        )
