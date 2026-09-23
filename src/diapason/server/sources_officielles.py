"""Les pages officielles qui répondent mieux qu'une recherche (21/09/2026).

« Quel temps fait-il aujourd'hui à Ottawa ? », le 20 septembre au soir :
la recherche (vertical actualités, fraîcheur d'une semaine) rendait cinq
articles datés sans une seule donnée météo, et le modèle le disait
honnêtement — « La recherche n'a pas retourné de données météo pour
Ottawa. » Honnête, mais sans réponse. Environnement Canada publie pourtant
la prévision sept jours de chaque ville, en français, sur une page que
web_read lit d'un coup : « Ce soir et cette nuit 3 °C Partiellement
nuageux — mar 22 sep 17 °C Ensoleillé… ».

P6 du jury « recherches véridiques » : une table sujet → page officielle,
lue EN COMPLÉMENT de la recherche générale, jamais à sa place, étiquetée
comme telle dans les sources. Une table figée périme ; elle est courte et
chaque entrée dit ce qu'elle couvre. Une ville absente de la table n'a pas
de page officielle : la recherche générale reste seule, comme avant.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

# Environnement Canada : la page « location » prend des coordonnées et rend
# la prévision de la station la plus proche. Sondé le 21/09 : l'ancienne
# adresse city/pages/on-118_metric_f.html répond 404 ; celle-ci, en
# français, est rendue côté serveur (lisible sans JavaScript).
_METEO_GC = "https://meteo.gc.ca/fr/location/index.html?coords={lat},{lon}"
# Les villes que Carlito nomme, et les grandes villes canadiennes. Les
# coordonnées sont celles du centre-ville ; Environnement Canada choisit la
# station. Clé normalisée (sans accent, minuscules).
VILLES: dict[str, tuple[float, float, str]] = {
    "ottawa": (45.421, -75.697, "Ottawa"),
    "gatineau": (45.477, -75.701, "Gatineau"),
    "montreal": (45.508, -73.588, "Montréal"),
    "laval": (45.606, -73.712, "Laval"),
    "longueuil": (45.531, -73.518, "Longueuil"),
    "quebec": (46.813, -71.208, "Québec"),
    "levis": (46.803, -71.178, "Lévis"),
    "sherbrooke": (45.404, -71.892, "Sherbrooke"),
    "trois-rivieres": (46.343, -72.541, "Trois-Rivières"),
    "saguenay": (48.428, -71.068, "Saguenay"),
    "kingston": (44.231, -76.486, "Kingston"),
    "cornwall": (45.021, -74.730, "Cornwall"),
    "toronto": (43.653, -79.383, "Toronto"),
    "mississauga": (43.589, -79.644, "Mississauga"),
    "hamilton": (43.256, -79.871, "Hamilton"),
    "london": (42.984, -81.246, "London"),
    "windsor": (42.317, -83.037, "Windsor"),
    "sudbury": (46.492, -80.993, "Sudbury"),
    "thunder bay": (48.382, -89.246, "Thunder Bay"),
    "winnipeg": (49.895, -97.138, "Winnipeg"),
    "regina": (50.445, -104.618, "Regina"),
    "saskatoon": (52.133, -106.670, "Saskatoon"),
    "calgary": (51.045, -114.057, "Calgary"),
    "edmonton": (53.546, -113.494, "Edmonton"),
    "vancouver": (49.283, -123.121, "Vancouver"),
    "victoria": (48.428, -123.365, "Victoria"),
    "halifax": (44.649, -63.575, "Halifax"),
    "moncton": (46.088, -64.778, "Moncton"),
    "fredericton": (45.964, -66.643, "Fredericton"),
    "charlottetown": (46.238, -63.129, "Charlottetown"),
    "st. john's": (47.562, -52.713, "St. John's"),
    "whitehorse": (60.721, -135.057, "Whitehorse"),
    "yellowknife": (62.454, -114.372, "Yellowknife"),
    "iqaluit": (63.746, -68.517, "Iqaluit"),
}
_METEO = re.compile(
    r"\b(?:meteo|temperature|previsions?|pleuvoir|pluie|neige|neiger|quel temps|"
    r"fait.il (?:beau|froid|chaud)|weather|forecast|rain|snow)\b"
)
_TAUX_DIRECTEUR = re.compile(r"\btaux (?:directeur|cible)\b|\bpolicy rate\b")
_BANQUE_DU_CANADA = "https://www.banqueducanada.ca/grandes-fonctions/politique-monetaire/taux-directeur/"

# Le défaut fondateur du chantier (21/09) : « Qui est le premier ministre du
# Canada ? » → « Justin Trudeau [3] », cité et daté. Aucun des cinq extraits
# ne nommait le titulaire — brave rend un passage pris au hasard. Le Cabinet
# du Premier ministre, lui, TITRE sa page du nom du titulaire : sondé le
# 22/09, `pm.gc.ca/fr` rend « Le très honorable Mark Carney », et son corps
# le répète à chaque communiqué.
#
# Il faut le Canada dans la question : un « premier ministre » nu peut être
# celui du Québec, de la France ou du Japon, et §34 interdit de deviner.
# « premier ministre du Québec » ne porte pas « Canada » et ne passe donc
# pas ici — la recherche générale lui reste seule, comme avant.
_PREMIER_MINISTRE = re.compile(r"\b(?:premi(?:er|ere) ministre|prime minister|pm)\b")
_CANADA = re.compile(r"\bcanad(?:a|ien|ienne|ian)\b")
_PM_GC = "https://www.pm.gc.ca/fr"

# Les taux de change quotidiens : un vrai tableau rendu côté serveur, en
# en-tête les cinq derniers jours ouvrables, et « Dollar (États-Unis) |
# 1,3947 | … | 1,4064 » en ligne (sondé le 22/09). La dernière colonne est
# celle du jour — l'en-tête la date, le modèle n'a pas à le deviner.
_TAUX_DE_CHANGE = re.compile(
    r"\btaux de change\b|\bexchange rate\b|"
    r"\bcombien vaut\b.{0,40}\b(?:dollar|euro|livre|yen|peso|franc|roupie)\b|"
    r"\bcours (?:du|de l'|de la)\s?(?:dollar|euro|livre|yen|peso|franc)\b|"
    r"\b(?:convertir|conversion)\b.{0,30}\b(?:dollar|euro|livre|yen)\b"
)
_TAUX_DE_CHANGE_BDC = (
    "https://www.banqueducanada.ca/taux/taux-de-change/taux-de-change-quotidiens/"
)


@dataclass(frozen=True)
class PageOfficielle:
    """Ce que le code lit en complément de la recherche."""

    url: str
    titre: str
    focus: str
    domaine: str
    titre_de_la_page: bool = False
    """Le titre de la page porte le fait — le garder.

    Vrai pour `pm.gc.ca`, dont le titre est le nom du titulaire. Le reste du
    temps l'étiquette fixe vaut mieux : « Ottawa — Prévision 7 jours » dit ce
    qu'on lit, là où le titre de la page dit « Météo - Environnement Canada ».
    """


def _plat(texte: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    ).replace("’", "'")


# Un nom propre au milieu de la question qui n'est pas une ville connue :
# « à Tombouctou » — la ville de la config ne prend pas sa place.
_NOM_PROPRE_MILIEU = re.compile(r"(?<!^)(?<![.!?]\s)\b[A-ZÀ-Ý][\wÀ-ÿ'’-]{2,}")


def ville_de(question: str, ville_par_defaut: str = "") -> str:
    """La ville nommée dans la question (clé de VILLES), sinon celle de la
    config, sinon "" — on ne devine pas une ville (§34 : on ne devine pas
    une direction non plus), et une ville inconnue n'est pas remplacée par
    celle de la config."""
    plat = _plat(question)
    for cle in sorted(VILLES, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(cle)}(?![\w-])", plat):
            return cle
    if _NOM_PROPRE_MILIEU.search(question.strip()):
        return ""
    defaut = _plat(ville_par_defaut).strip()
    return defaut if defaut in VILLES else ""


def page_officielle(question: str, ville_par_defaut: str = "") -> PageOfficielle | None:
    """La page officielle du sujet de la question, ou None."""
    plat = _plat(question)
    if _METEO.search(plat):
        ville = ville_de(question, ville_par_defaut)
        if not ville:
            return None
        lat, lon, nom = VILLES[ville]
        return PageOfficielle(
            url=_METEO_GC.format(lat=lat, lon=lon),
            titre=f"{nom} — Prévision 7 jours, Environnement Canada",
            # Les fenêtres du lecteur se posent sur ces mots : la prévision du
            # soir, de la nuit et du lendemain avant le reste de la page.
            focus="ce soir cette nuit demain prévisions émises " + question,
            domaine="meteo.gc.ca",
        )
    if _PREMIER_MINISTRE.search(plat) and _CANADA.search(plat):
        return PageOfficielle(
            url=_PM_GC,
            titre="Premier ministre du Canada",
            focus="premier ministre titulaire le très honorable " + question,
            domaine="pm.gc.ca",
            titre_de_la_page=True,
        )
    if _TAUX_DE_CHANGE.search(plat):
        return PageOfficielle(
            url=_TAUX_DE_CHANGE_BDC,
            titre="Taux de change quotidiens — Banque du Canada",
            # Le tableau porte une ligne par devise ; les fenêtres du lecteur
            # se posent sur le nom de la devise demandée, puis sur les deux
            # plus courantes.
            focus="Dollar (États-Unis) Euro (Europe) devise " + question,
            domaine="banqueducanada.ca",
        )
    if _TAUX_DIRECTEUR.search(plat):
        return PageOfficielle(
            url=_BANQUE_DU_CANADA,
            titre="Taux directeur — Banque du Canada",
            focus="taux cible modification date " + question,
            domaine="banqueducanada.ca",
        )
    return None


def _titre(page: PageOfficielle, titre_lu: str = "") -> str:
    """L'étiquette de la page, augmentée du titre lu quand celui-ci PORTE le
    fait.

    Remplacer le titre de `pm.gc.ca` par le nôtre jetait la réponse : la page
    s'appelle « Le très honorable Mark Carney ». Le garder seul ne dirait pas
    de quel poste il s'agit. Les deux : « Premier ministre du Canada : Le très
    honorable Mark Carney »."""
    lu = (titre_lu or "").strip()
    if page.titre_de_la_page and lu and lu.casefold() != page.titre.casefold():
        return f"{page.titre} : {lu}"
    return page.titre


def entete_officielle(page: PageOfficielle, ref: int, titre_lu: str = "") -> str:
    """L'en-tête numéroté d'une page officielle, datée du jour de sa lecture :
    une page vivante n'a pas de date de publication qui compte."""
    return (
        f"[{ref}] {_titre(page, titre_lu)} — {page.domaine} · source officielle · "
        f"consultée le {date.today().isoformat()}"
    )


def carte_officielle(
    page: PageOfficielle,
    nouvelles: list[dict[str, object]],
    deja: list[dict[str, object]],
    titre_lu: str = "",
) -> tuple[dict[str, object] | None, int | None]:
    """La carte de source d'une page officielle et son numéro — que la
    recherche l'ait déjà rendue ou non.

    22/09/2026. P6 promettait qu'une page officielle se dise « officiel ·
    consultée le <aujourd'hui> ». Elle ne le disait QUE lorsque la recherche
    avait échoué. Sinon la page figurait déjà parmi les résultats,
    `renumeroter` la dédoublonnait, `nouvelles` sortait vide, et tout le bloc
    qui pose l'étiquette sautait : la Banque du Canada, lue par le code à
    l'instant, s'affichait comme une source ordinaire datée de dix-huit mois
    (constaté en direct sur « Quel est le taux directeur ? »). Le cas raté
    est le plus fréquent : une page officielle est bien indexée, donc la
    recherche la rend.

    La carte est FUSIONNÉE sur l'entrée existante, jamais substituée : une
    source de recherche porte plus de champs que les six d'une carte
    officielle, et le `title` alimente le score de `sources_prometteuses`,
    qui décide quelle page relire quand la réponse avoue. Rien ne mute ici ;
    l'appelant décide d'ajouter ou de remplacer.
    """
    from diapason.tools.web_search import url_canonique

    if nouvelles:
        ref = int(nouvelles[0]["ref"])  # type: ignore[arg-type]
        return {**nouvelles[0], **source_officielle(page, ref, titre_lu)}, ref
    # La page était déjà connue : retrouver SA pastille, pas une autre. Une
    # autre lecture du même tour (la page du poste) peut aussi être dans la
    # liste — seule l'URL canonique de CETTE page compte.
    cible = url_canonique(page.url)
    for d in deja:
        if not isinstance(d, dict) or not isinstance(d.get("ref"), int):
            continue
        if url_canonique(str(d.get("url") or "")) == cible:
            ref = int(d["ref"])
            return {**d, **source_officielle(page, ref, titre_lu)}, ref
    return None, None


def source_officielle(
    page: PageOfficielle, ref: int, titre_lu: str = ""
) -> dict[str, object]:
    return {
        "ref": ref,
        "title": _titre(page, titre_lu),
        "url": page.url,
        "date": date.today().isoformat(),
        "sender": page.domaine,
        "official": True,
    }


__all__ = [
    "VILLES",
    "carte_officielle",
    "PageOfficielle",
    "entete_officielle",
    "page_officielle",
    "source_officielle",
    "ville_de",
]
