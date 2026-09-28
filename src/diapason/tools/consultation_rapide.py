"""Les comptes explicites ne nécessitent pas deux inférences pour lire un total."""

import re
import unicodedata
from datetime import date

from diapason.vie.periodes import MOIS_FR, plage_de_consultation


def compte_demande(texte: str) -> dict | None:
    """Grammaire fermée : un projet, une comparaison ou une action reste au modèle."""
    simple = (
        "".join(
            c
            for c in unicodedata.normalize("NFKD", texte.lower())
            if not unicodedata.combining(c)
        )
        .replace("’", "'")
        .strip(" .!?")
    )
    simple = re.sub(
        r"[,?]\s*(?:et combien restent a terminer|donne le total, les terminees "
        r"et celles qui restent|donne uniquement le nombre enregistre "
        r"et la periode)\.?$",
        "",
        simple,
    ).strip(" .!?")
    m = re.fullmatch(
        r"(?:diapason[, ]+)?combien de (?:mes )?taches\s*"
        r"(?:ai[- ]je|j'ai|avais[- ]je|aurai[- ]je)?\s*(.+)",
        simple,
    )
    if not m:
        return None
    periode = re.sub(r"^(?:pour|sur|pendant|durant|en)\s+", "", m[1]).strip()
    periode = re.sub(r"^toute?\s+", "", periode)
    relatives = {
        "aujourd'hui",
        "demain",
        "hier",
        "cette semaine",
        "la semaine prochaine",
        "la semaine derniere",
        "ce mois",
        "le mois prochain",
        "le mois dernier",
        "cette annee",
        "l'annee prochaine",
        "l'annee derniere",
    }
    annee = re.fullmatch(r"(?:l'annee |annee )?(\d{4})", periode)
    mois = (
        r"(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|"
        r"octobre|novembre|decembre)"
    )
    date = rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}} {mois} \d{{4}})"
    intervalle = re.fullmatch(
        rf"(?:la semaine )?du ({date}) au ({date})(?: inclus)?", periode
    )
    if annee:
        args = {"date": annee[1], "period": "year"}
    elif intervalle:
        args = {"startDate": intervalle[1], "endDate": intervalle[2]}
    elif periode in relatives or re.fullmatch(rf"(?:le )?{date}", periode):
        args = {"date": re.sub(r"^le ", "", periode)}
    else:
        return None
    try:
        debut, fin = plage_de_consultation(
            args.get("date", ""),
            args.get("period", ""),
            args.get("startDate", ""),
            args.get("endDate", ""),
        )
    except ValueError:
        return None
    return {"action": "count", "startDate": debut, "endDate": fin}


def rendre_compte(donnees: dict) -> str:
    """La même preuve chiffrée, lisible dans le chat et prononçable par Orion."""
    total = int(donnees["count"])
    terminees = int(donnees["completedCount"])
    restantes = int(donnees["pendingCount"])

    def jour(iso: str) -> str:
        valeur = date.fromisoformat(iso)
        return f"{valeur.day} {MOIS_FR[valeur.month - 1]} {valeur.year}"

    debut, fin = donnees["startDate"], donnees["endDate"]
    periode = (
        f"Le {jour(debut)}" if debut == fin else f"Du {jour(debut)} au {jour(fin)}"
    )
    return (
        f"{periode}, tu as {total} tâche{'s' if total != 1 else ''} : "
        f"{terminees} terminée{'s' if terminees != 1 else ''} et "
        f"{restantes} restante{'s' if restantes != 1 else ''}."
    )
