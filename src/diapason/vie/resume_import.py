"""Le résumé d'un import Life OS : ce qui est entré, ce qui ne l'est pas, et pourquoi.

26/09/2026, étape 2 de la phase 3 (docs/development/diapason-mobile.md).
L'import de la sauvegarde du téléphone sautait des éléments sans les compter
— une note sans titre, une habitude refusée par la validation, une coche
d'habitude sans horodatage — et le résumé disait « importé ». Sur la copie
de dev, 2 coches sur 3 disparaissaient ainsi. Ce module tient le compte des
sauts, par motif, et nomme les clés de la sauvegarde que le Mac n'importe
pas du tout.

Les champs du résumé voyagent vers la fenêtre et vers le téléphone : ils sont
en anglais camelCase, comme tout ce qui passe sur le fil. Les MOTIFS sont des
valeurs, écrites en français comme le reste du domaine.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Les motifs d'un saut. Chacun dit ce que l'utilisateur doit savoir pour
# retrouver l'élément de son côté.
PLUS_RECENT_SUR_LE_MAC = "plusRecentSurLeMac"
DEJA_SUR_LE_MAC = "dejaSurLeMac"
TITRE_VIDE = "titreVide"
TROP_LONG = "tropLong"
INVALIDE = "invalide"
HABITUDE_ABSENTE = "habitudeAbsente"

# Les raisons pour lesquelles une clé de la sauvegarde n'est pas importée.
ETAT_INTERFACE = "etatInterface"
REGLAGE_SANS_EQUIVALENT = "reglageSansEquivalent"
SUPPRESSIONS_NON_REJOUEES = "suppressionsNonRejouees"
CURSEUR_SYNCHRO_PHP = "curseurSynchroPhp"
CLE_INCONNUE = "cleInconnue"
ENVELOPPE = "enveloppe"

# Ce que le Mac importe, couche par couche (store, workspace, continuity).
_CLES_IMPORTEES = frozenset(
    {
        "todos",
        "projects",
        "habits",
        "habitLogs",
        "habitLogsAt",
        "notes",
        "quotes",
        "todoTemplates",
    }
)

# L'écran que le téléphone ou le site avait ouvert : aucune donnée, et rien
# qui ait un sens sur une autre fenêtre.
_ETAT_INTERFACE = ("activeNoteId", "notesView", "notesEditorId", "selectedDate")

# 100 éléments nommés suffisent à retrouver ce qui manque ; au-delà, le
# résumé grossirait la réponse (et la ligne archivée) sans rien apprendre de
# plus que les comptes, qui restent exacts.
ELEMENTS_NOMMES_MAX = 100

# 60 caractères : de quoi reconnaître une note sans titre par sa première
# phrase, sans recopier son contenu dans le résumé.
_LIBELLE_MAX = 60

_BALISE = re.compile(r"<[^>]+>")


def libelle(*valeurs: Any) -> str:
    """Le premier texte non vide parmi ``valeurs``, sans balises, raccourci."""
    for valeur in valeurs:
        texte = " ".join(_BALISE.sub(" ", str(valeur or "")).split())
        if texte:
            if len(texte) > _LIBELLE_MAX:
                return texte[: _LIBELLE_MAX - 1] + "…"
            return texte
    return ""


def motif_de_l_erreur(erreur: BaseException) -> str:
    """``tropLong`` pour un dépassement de plafond, ``invalide`` sinon."""
    return str(getattr(erreur, "motif", INVALIDE))


class Sauts:
    """Le compte des éléments non importés, et des champs raccourcis."""

    def __init__(self) -> None:
        self._comptes: dict[str, dict[str, int]] = {}
        self._elements: list[dict[str, str]] = []
        self._tronques: dict[str, dict[str, int]] = {}

    def noter(self, genre: str, motif: str, ident: Any, etiquette: str = "") -> None:
        par_motif = self._comptes.setdefault(genre, {})
        par_motif[motif] = par_motif.get(motif, 0) + 1
        if len(self._elements) < ELEMENTS_NOMMES_MAX:
            self._elements.append(
                {
                    "kind": genre,
                    "id": str(ident or ""),
                    "label": etiquette,
                    "reason": motif,
                }
            )

    def tronquer(self, genre: str, champ: str, valeur: Any, plafond: int) -> str:
        """``valeur`` ramenée à ``plafond`` caractères — en le comptant."""
        texte = str(valeur or "")
        if len(texte) <= plafond:
            return texte
        par_champ = self._tronques.setdefault(genre, {})
        par_champ[champ] = par_champ.get(champ, 0) + 1
        return texte[:plafond]

    def resume(self) -> dict[str, Any]:
        return {
            "skipped": {genre: dict(m) for genre, m in self._comptes.items()},
            "skippedItems": list(self._elements),
            "truncated": {genre: dict(c) for genre, c in self._tronques.items()},
        }


def fusionner(*parties: Mapping[str, Any]) -> dict[str, Any]:
    """Les résumés des couches d'import, réunis sans qu'aucun n'écrase l'autre.

    Un ``{**a, **b}`` remplaçait le ``skipped`` de la première couche par
    celui de la suivante : les notes sautées effaçaient les tâches sautées.
    """
    total: dict[str, Any] = {}
    for partie in parties:
        for cle, valeur in partie.items():
            if cle in ("skipped", "truncated"):
                cible = total.setdefault(cle, {})
                for genre, comptes in valeur.items():
                    par_genre = cible.setdefault(genre, {})
                    for motif, n in comptes.items():
                        par_genre[motif] = par_genre.get(motif, 0) + int(n)
            elif cle == "skippedItems":
                place = ELEMENTS_NOMMES_MAX - len(total.setdefault(cle, []))
                total[cle].extend(list(valeur)[: max(0, place)])
            else:
                total[cle] = valeur
    return total


def cles_ignorees(instantane: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Chaque clé de la sauvegarde que le Mac n'importe pas, avec sa raison.

    Décidé le 25/09/2026 : les réglages du site (``theme``, ``colorTheme``,
    ``todosViewMode``, ``bilanFutureExtraYears``, ``bilanHorizonLastYear``)
    n'ont pas d'équivalent ici — l'apparence du téléphone est indépendante de
    celle du Mac — et sont ignorés, mais NOMMÉS : un réglage qui disparaît
    sans un mot ressemble à une perte.
    """
    etat = instantane.get("state")
    ignorees: list[dict[str, Any]] = []
    if isinstance(etat, Mapping):
        for cle in sorted(k for k in instantane if k != "state"):
            ignorees.append({"key": str(cle), "reason": ENVELOPPE})
    else:
        etat = instantane
    for cle in sorted(str(k) for k in etat):
        valeur = etat[cle]
        if cle in _CLES_IMPORTEES:
            continue
        if cle in _ETAT_INTERFACE:
            ignorees.append({"key": cle, "reason": ETAT_INTERFACE})
        elif cle == "settings" and isinstance(valeur, Mapping):
            for reglage in sorted(str(k) for k in valeur):
                ignorees.append(
                    {"key": f"settings.{reglage}", "reason": REGLAGE_SANS_EQUIVALENT}
                )
        elif cle == "sync" and isinstance(valeur, Mapping):
            for sous_cle in sorted(str(k) for k in valeur):
                if sous_cle == "deletes":
                    # Une suppression faite sur le téléphone n'efface rien sur
                    # le Mac : l'import n'ajoute et ne met à jour que ce que
                    # la sauvegarde CONTIENT. Le compte dit combien.
                    ignorees.append(
                        {
                            "key": "sync.deletes",
                            "reason": SUPPRESSIONS_NON_REJOUEES,
                            "count": _compte_suppressions(valeur.get("deletes")),
                        }
                    )
                else:
                    ignorees.append(
                        {"key": f"sync.{sous_cle}", "reason": CURSEUR_SYNCHRO_PHP}
                    )
        else:
            ignorees.append({"key": cle, "reason": CLE_INCONNUE})
    return ignorees


def _compte_suppressions(suppressions: Any) -> int:
    if not isinstance(suppressions, Mapping):
        return 0
    return sum(len(v) for v in suppressions.values() if isinstance(v, Mapping))


_IMPORTES = (
    ("tasksImported", "tâche", "tâches"),
    ("projectsImported", "projet", "projets"),
    ("habitsImported", "habitude", "habitudes"),
    ("habitLogsImported", "coche d'habitude", "coches d'habitude"),
    ("notesImported", "note", "notes"),
    ("templatesImported", "modèle", "modèles"),
    ("quotesImported", "citation", "citations"),
)

_GENRES = {
    "tasks": ("tâche", "tâches"),
    "projects": ("projet", "projets"),
    "habits": ("habitude", "habitudes"),
    "habitLogs": ("coche d'habitude", "coches d'habitude"),
    "notes": ("note", "notes"),
    "templates": ("modèle", "modèles"),
    "quotes": ("citation", "citations"),
}

_MOTIFS = {
    PLUS_RECENT_SUR_LE_MAC: "une version plus récente est sur le Mac",
    DEJA_SUR_LE_MAC: "déjà sur le Mac",
    TITRE_VIDE: "sans titre",
    TROP_LONG: "trop long",
    INVALIDE: "invalide",
    HABITUDE_ABSENTE: "habitude absente du Mac",
}


_RAISONS = {
    ETAT_INTERFACE: "état d'écran",
    REGLAGE_SANS_EQUIVALENT: "réglages sans équivalent sur le Mac",
    SUPPRESSIONS_NON_REJOUEES: "suppressions de l'ancienne synchronisation",
    CURSEUR_SYNCHRO_PHP: "curseurs de l'ancienne synchronisation",
    CLE_INCONNUE: "clés inconnues",
    ENVELOPPE: "enveloppe de la sauvegarde",
}


def _nombre(n: int, singulier: str, pluriel: str) -> str:
    return f"{n} {singulier if n == 1 else pluriel}"


def phrase(resume: Mapping[str, Any]) -> str:
    """La phrase que la fenêtre et le téléphone affichent, tirée du résumé.

    Elle vient du RÉCEPTEUR (§100) : l'appelant ne compose pas « importé »
    à partir de ce qu'il a envoyé.
    """
    if resume.get("alreadyImported"):
        return (
            "Cette sauvegarde avait déjà été importée : rien n'a changé. "
            "Le résumé ci-dessous est celui du premier import."
        )
    importes = [
        _nombre(int(resume.get(cle) or 0), s, p)
        for cle, s, p in _IMPORTES
        if int(resume.get(cle) or 0)
    ]
    morceaux = [
        "Importé : " + ", ".join(importes) + "."
        if importes
        else "Rien n'a été importé."
    ]
    sauts = []
    for genre, par_motif in (resume.get("skipped") or {}).items():
        s, p = _GENRES.get(genre, (genre, genre))
        for motif, n in par_motif.items():
            sauts.append(f"{_nombre(int(n), s, p)} ({_MOTIFS.get(motif, motif)})")
    if sauts:
        morceaux.append("Non importé : " + ", ".join(sauts) + ".")
    tronques = sum(
        int(n) for c in (resume.get("truncated") or {}).values() for n in c.values()
    )
    if tronques:
        morceaux.append(
            f"{_nombre(tronques, 'champ raccourci', 'champs raccourcis')} "
            "au plafond du Mac."
        )
    ignorees = resume.get("ignoredKeys") or []
    if ignorees:
        raisons = []
        for cle in ignorees:
            raison = _RAISONS.get(cle.get("reason"), str(cle.get("reason")))
            if raison not in raisons:
                raisons.append(raison)
        morceaux.append(
            f"{_nombre(len(ignorees), 'clé ignorée', 'clés ignorées')} "
            f"({', '.join(raisons)})."
        )
    suppressions = sum(
        int(cle.get("count") or 0)
        for cle in ignorees
        if cle.get("reason") == SUPPRESSIONS_NON_REJOUEES
    )
    if suppressions:
        morceaux.append(
            f"{_nombre(suppressions, 'suppression faite', 'suppressions faites')} "
            "ailleurs n'efface rien sur le Mac."
        )
    return " ".join(morceaux)


__all__ = [
    "CLE_INCONNUE",
    "CURSEUR_SYNCHRO_PHP",
    "DEJA_SUR_LE_MAC",
    "ELEMENTS_NOMMES_MAX",
    "ENVELOPPE",
    "ETAT_INTERFACE",
    "HABITUDE_ABSENTE",
    "INVALIDE",
    "PLUS_RECENT_SUR_LE_MAC",
    "REGLAGE_SANS_EQUIVALENT",
    "SUPPRESSIONS_NON_REJOUEES",
    "Sauts",
    "TITRE_VIDE",
    "TROP_LONG",
    "cles_ignorees",
    "fusionner",
    "libelle",
    "motif_de_l_erreur",
    "phrase",
]
