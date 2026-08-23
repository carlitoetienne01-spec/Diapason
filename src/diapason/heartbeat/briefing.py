"""Le briefing du matin, composé de données — sans un seul appel au modèle.

Constaté le 22 août 2026 : Diapason ne parlait jamais le premier. La routine
``morning-digest`` existait, mais elle demandait au modèle de rédiger, et sur
une machine où Ollama n'a qu'UN créneau, un briefing qui infère est un briefing
qui fait attendre — puis qui invente quand il se trompe.

Or un briefing n'a rien à inventer. « Trois tâches en retard depuis le 19 août,
dont une urgente » est une phrase que les données écrivent toutes seules. Ce
module la compose : instantané, toujours juste, et il ne dispute le GPU à
personne. Le modèle reste disponible pour ce qu'il fait mieux qu'une requête
SQL — répondre à une question.

L'ordre des sections n'est pas cosmétique. Le retard vient EN PREMIER : c'est
la seule chose qu'un briefing peut faire remarquer et qu'on ne verrait pas
autrement. Ce qui est prévu aujourd'hui, l'agenda le montre déjà.

Et quand il n'y a rien, il le dit en une ligne. Un assistant qui meuble pour
justifier son existence apprend à son utilisateur à ne plus le lire.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Au-delà, on cesse d'énumérer et on dit combien il en reste. Une notification
# qu'on ne peut pas lire d'un coup d'œil n'est pas lue du tout.
MAX_LIGNES_PAR_SECTION = 5

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def date_en_francais(jour: date) -> str:
    """« samedi 22 août ». Sans dépendre du locale, qui est global au processus."""
    return f"{_JOURS[jour.weekday()]} {jour.day} {_MOIS[jour.month - 1]}"


def _depuis_quand(echeance: str, jour: date) -> str:
    """« depuis 3 jours », ou « depuis hier ». Vague sur un long retard."""
    try:
        prevue = date.fromisoformat(echeance)
    except (TypeError, ValueError):
        return ""
    ecart = (jour - prevue).days
    if ecart <= 0:
        return ""
    if ecart == 1:
        return "depuis hier"
    if ecart < 7:
        return f"depuis {ecart} jours"
    if ecart < 30:
        semaines = ecart // 7
        return f"depuis {semaines} semaine{'s' if semaines > 1 else ''}"
    return "depuis plus d'un mois"


@dataclass(frozen=True, slots=True)
class Briefing:
    """Ce qu'on montre, et de quoi savoir s'il vaut la peine d'être montré."""

    titre: str
    corps: str
    rien_a_signaler: bool

    def __str__(self) -> str:  # pragma: no cover - confort
        return self.corps


def _echeance(t: Mapping[str, Any]) -> str:
    """La date prévue. ``list_tasks`` la nomme ``date`` ; la colonne SQL
    ``scheduled_date`` ; les deux formes circulent selon le chemin d'appel."""
    for cle in ("date", "scheduledDate", "scheduled_date"):
        valeur = str(t.get(cle) or "").strip()
        if valeur:
            return valeur
    return ""


def _titre(t: Mapping[str, Any]) -> str:
    return str(t.get("title") or t.get("titre") or "").strip()


def _urgente(t: Mapping[str, Any]) -> bool:
    return str(t.get("priority") or "").strip().lower() in ("urgent", "high")


def _lister(elements: Sequence[str]) -> list[str]:
    """Les premières, puis le compte de ce qui reste — jamais un mur."""
    if len(elements) <= MAX_LIGNES_PAR_SECTION:
        return list(elements)
    reste = len(elements) - MAX_LIGNES_PAR_SECTION
    return [
        *elements[:MAX_LIGNES_PAR_SECTION],
        f"… et {reste} autre{'s' if reste > 1 else ''}",
    ]


def composer(
    *,
    jour: date,
    taches_du_jour: Iterable[Mapping[str, Any]] = (),
    taches_en_retard: Iterable[Mapping[str, Any]] = (),
    habitudes_dues: Iterable[Mapping[str, Any]] = (),
    evenements: Iterable[Mapping[str, Any]] = (),
    prenom: str = "",
) -> Briefing:
    """Le briefing, à partir de données déjà lues. Aucune entrée/sortie ici.

    Séparé de la lecture pour être vérifiable sans base ni agenda : c'est la
    composition qu'on veut tenir, pas le pilotage de SQLite.
    """
    du_jour = [t for t in taches_du_jour if not t.get("done")]
    en_retard = list(taches_en_retard)
    habitudes = list(habitudes_dues)
    rdv = list(evenements)

    sections: list[str] = []

    # Le retard d'abord : c'est ce qu'on ne verrait pas autrement.
    if en_retard:
        urgentes = [t for t in en_retard if _urgente(t)]
        lignes = []
        for t in sorted(en_retard, key=lambda x: (not _urgente(x), _echeance(x))):
            depuis = _depuis_quand(_echeance(t), jour)
            marque = " (urgent)" if _urgente(t) else ""
            lignes.append(f"— {_titre(t)}{marque}{', ' + depuis if depuis else ''}")
        entete = f"{len(en_retard)} tâche{'s' if len(en_retard) > 1 else ''} en retard"
        if urgentes:
            entete += (
                f", dont {len(urgentes)} urgente{'s' if len(urgentes) > 1 else ''}"
            )
        sections.append(entete + " :\n" + "\n".join(_lister(lignes)))

    if rdv:
        lignes = []
        for e in rdv:
            heure = str(e.get("start") or e.get("time") or "").strip()
            lignes.append(
                f"— {heure + ' ' if heure else ''}{_titre(e) or e.get('summary', '')}"
            )
        sections.append(
            f"{len(rdv)} rendez-vous aujourd'hui :\n" + "\n".join(_lister(lignes))
        )

    if du_jour:
        lignes = [f"— {_titre(t)}{' (urgent)' if _urgente(t) else ''}" for t in du_jour]
        sections.append(
            f"{len(du_jour)} tâche{'s' if len(du_jour) > 1 else ''} prévue"
            f"{'s' if len(du_jour) > 1 else ''} aujourd'hui :\n"
            + "\n".join(_lister(lignes))
        )

    if habitudes:
        noms = [str(h.get("name") or h.get("nom") or "").strip() for h in habitudes]
        noms = [n for n in noms if n]
        if noms:
            sections.append("Habitudes du jour : " + ", ".join(noms) + ".")

    salut = f"Bonjour{' ' + prenom if prenom else ''}"
    entete = f"{salut}. Nous sommes {date_en_francais(jour)}."

    if not sections:
        # Ne rien meubler. Un assistant qui parle pour exister apprend à son
        # utilisateur à ne plus l'écouter.
        return Briefing(
            titre="Rien de prévu aujourd'hui",
            corps=f"{entete} Rien de prévu, rien en retard.",
            rien_a_signaler=True,
        )

    if en_retard:
        titre = f"{len(en_retard)} tâche{'s' if len(en_retard) > 1 else ''} en retard"
    elif rdv:
        titre = f"{len(rdv)} rendez-vous aujourd'hui"
    elif du_jour:
        titre = f"{len(du_jour)} tâche{'s' if len(du_jour) > 1 else ''} aujourd'hui"
    else:
        titre = "Habitudes du jour"

    return Briefing(
        titre=titre,
        corps=entete + "\n\n" + "\n\n".join(sections),
        rien_a_signaler=False,
    )


def _taches_en_retard(store: Any, jour: date, *, jours_max: int = 60) -> list[dict]:
    """Les tâches non faites dont la date est passée.

    Bornée dans le temps : une tâche oubliée depuis six mois n'est plus un
    retard, c'est un remords. La rappeler chaque matin ne sert personne.
    """
    trouvees: list[dict] = []
    for recul in range(1, jours_max + 1):
        veille = (jour - timedelta(days=recul)).isoformat()
        for t in store.list_tasks(scheduled_date=veille, include_done=False):
            if not t.get("done"):
                trouvees.append(t)
    return trouvees


def briefing_du_jour(
    store: Any = None,
    *,
    jour: date | None = None,
    prenom: str = "",
    evenements: Iterable[Mapping[str, Any]] = (),
) -> Briefing:
    """Lit Succès et compose.

    Ne lève jamais : un briefing muet vaut mieux qu'une trace d'exception.
    """
    jour = jour or date.today()
    if store is None:
        from diapason.succes.workspace import SuccesWorkspaceStore

        store = SuccesWorkspaceStore()
    try:
        du_jour = store.list_tasks(scheduled_date=jour.isoformat())
    except Exception:  # noqa: BLE001
        logger.warning("briefing : tâches du jour illisibles", exc_info=True)
        du_jour = []
    try:
        en_retard = _taches_en_retard(store, jour)
    except Exception:  # noqa: BLE001
        logger.warning("briefing : retards illisibles", exc_info=True)
        en_retard = []
    try:
        habitudes = [
            h for h in store.list_habits(on_date=jour.isoformat()) if h.get("due")
        ]
    except Exception:  # noqa: BLE001
        logger.warning("briefing : habitudes illisibles", exc_info=True)
        habitudes = []

    return composer(
        jour=jour,
        taches_du_jour=du_jour,
        taches_en_retard=en_retard,
        habitudes_dues=habitudes,
        evenements=evenements,
        prenom=prenom,
    )


__all__ = [
    "MAX_LIGNES_PAR_SECTION",
    "Briefing",
    "briefing_du_jour",
    "composer",
    "date_en_francais",
]
