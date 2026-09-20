"""Catalogue léger, sans retirer une capacité du chat (19 septembre 2026).

44 schémas occupaient 31 748 caractères pour expliquer la croissance d'un
arbre. Tout filtrer par mots-clés ferait en revanche inventer les données des
formulations inconnues. Le catalogue conserve l'accès à TOUS les outils de
la trousse autorisée ; seuls leurs paramètres détaillés sont différés.
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
    (r"\b(cherche|recherche|search|web|internet|actualites?)\b", ("web_search",)),
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
_REDACTION = re.compile(
    r"^(?:(?:peux.tu|pourrais.tu|tu peux)\s+)?"
    r"(?:explique|explain|definis|define|raconte|invente|conjugue|conjugate)\b"
)
# 19/09/2026 : « Prépare moi un programme pour la programmation » envoyait
# les 44 schémas complets au 14b : 57,8 s pour répéter la demande. Le catalogue
# conserve tous les outils, sans leurs paramètres inutiles avant le cadrage.
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


def _normaliser(texte: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    )


def _amorcer(messages: Sequence[Message]) -> set[str]:
    noms: set[str] = set()
    demandes = [m.content or "" for m in messages if m.role == Role.USER]
    texte = demandes[-1] if demandes else ""
    # « Et demain ? » n'efface pas la demande précédente. Un vrai changement
    # de sujet n'embarque pas en permanence les outils de tout l'historique.
    if len(texte) < 100 and len(demandes) > 1:
        texte = demandes[-2] + "\n" + texte
    texte = _normaliser(texte)
    for motif, groupe in _INDICES:
        if motif.search(texte):
            noms.update(groupe)
    for message in messages[-8:]:
        for appel in message.tool_calls or []:
            noms.add(appel.name)
    return noms


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

    def __init__(self, tools: Sequence[Any], messages: Sequence[Message]):
        self._specs = [outil.to_openai_function() for outil in tools]
        self.noms = {s["function"]["name"] for s in self._specs}
        self._charges = 0
        self._actifs = _amorcer(messages) & self.noms
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
            CHARGER_OUTILS not in self.noms
            and _taille(self._specs) > SEUIL_CATALOGUE
            # Essai réel du 19/09 : « J'ai reçu quoi ? » avec catalogue seul
            # produisait une absence de messages inventée. Une demande inconnue
            # garde donc les schémas complets ; les indices ne sont pas un plafond.
            and (bool(self._actifs) or _redaction_autonome(messages))
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
