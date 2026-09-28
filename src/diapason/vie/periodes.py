"""Les périodes de consultation, distinctes de la date d'une création."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from diapason.vie.dates import DEFAULT_TIMEZONE, _fold, _today, resolve_date_expression
from diapason.vie.store import VieError

MOIS_FR = (
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


def plage_de_consultation(
    expression: str = "",
    periode: str = "",
    debut: str = "",
    fin: str = "",
    *,
    now: datetime | date | None = None,
) -> tuple[str | None, str | None]:
    """Bornes inclusives ; une semaine va du lundi au dimanche."""

    def exacte(texte: str) -> date:
        francais = re.fullmatch(r"(\d{1,2}) ([a-z]+) (\d{4})", _fold(texte))
        mois = [_fold(nom) for nom in MOIS_FR]
        if francais and francais[2] in mois:
            return date(int(francais[3]), mois.index(francais[2]) + 1, int(francais[1]))
        resultat = resolve_date_expression(texte.replace("’", "'"), now=now)
        if resultat.status != "exact" or not resultat.value:
            raise VieError("La période nécessite des dates précises : " + texte)
        return date.fromisoformat(resultat.value)

    if debut or fin:
        if not debut or not fin or expression:
            raise VieError("Indique les deux bornes, ou une date et sa période.")
        borne_debut, borne_fin = exacte(debut), exacte(fin)
        if borne_fin < borne_debut:
            raise VieError("La fin de la période précède son début.")
        if periode and plage_de_consultation(debut, periode, now=now) != (
            borne_debut.isoformat(),
            borne_fin.isoformat(),
        ):
            raise VieError("La période et ses bornes se contredisent.")
        return borne_debut.isoformat(), borne_fin.isoformat()
    texte = _fold(expression).replace("’", "'")
    aujourd_hui = _today(DEFAULT_TIMEZONE, now)
    relatives = {
        "cette semaine": ("week", 0),
        "semaine prochaine": ("week", 1),
        "la semaine prochaine": ("week", 1),
        "semaine derniere": ("week", -1),
        "la semaine derniere": ("week", -1),
        "ce mois": ("month", 0),
        "mois prochain": ("month", 1),
        "le mois prochain": ("month", 1),
        "mois dernier": ("month", -1),
        "le mois dernier": ("month", -1),
        "cette annee": ("year", 0),
        "annee prochaine": ("year", 1),
        "l'annee prochaine": ("year", 1),
        "annee derniere": ("year", -1),
        "l'annee derniere": ("year", -1),
    }
    if texte in relatives:
        nature, decalage = relatives[texte]
        if periode and periode != nature:
            raise VieError("La période et la date demandées se contredisent.")
        periode = nature
        if nature == "week":
            ancre = aujourd_hui + timedelta(weeks=decalage)
        elif nature == "month":
            annee, mois = divmod(
                aujourd_hui.year * 12 + aujourd_hui.month - 1 + decalage, 12
            )
            ancre = date(annee, mois + 1, 1)
        else:
            ancre = date(aujourd_hui.year + decalage, 1, 1)
    elif re.fullmatch(r"\d{4}", texte):
        ancre = date(int(texte), 1, 1)
        periode = periode or "year"
    elif re.fullmatch(r"\d{4}-\d{2}", texte):
        ancre = date.fromisoformat(texte + "-01")
        periode = periode or "month"
    elif expression:
        ancre = exacte(expression)
    elif periode:
        ancre = aujourd_hui
    else:
        return None, None
    periode = periode or "day"
    if periode == "day":
        borne_debut = borne_fin = ancre
    elif periode == "week":
        borne_debut = ancre - timedelta(days=ancre.weekday())
        borne_fin = borne_debut + timedelta(days=6)
    elif periode == "month":
        borne_debut = ancre.replace(day=1)
        borne_fin = ancre.replace(day=calendar.monthrange(ancre.year, ancre.month)[1])
    elif periode == "year":
        borne_debut, borne_fin = date(ancre.year, 1, 1), date(ancre.year, 12, 31)
    else:
        raise VieError("La période doit être day, week, month ou year.")
    return borne_debut.isoformat(), borne_fin.isoformat()
