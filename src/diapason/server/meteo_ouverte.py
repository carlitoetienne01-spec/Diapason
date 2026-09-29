"""Prévision pour une ville nommée, hors de la table canadienne (29/09/2026).

La table de ``sources_officielles`` ne couvre que des villes du Canada, et
une ville écrite (« à Lyon », « in Lisbon ») n'était pas remplacée par la
config — elle n'était pas lue du tout. Open-Meteo géocode le nom demandé et
rend la température actuelle, sans clé. Huit secondes : deux appels, et une
panne ne doit pas figer le tour ni inventer une autre ville.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from urllib.parse import urlencode

import httpx

from diapason.server.sources_officielles import _METEO, _plat, ville_de

# « à New York », « in Lisbon », « prévision pour Lyon », « météo Tokyo ».
# Le nom garde ses majuscules : c'est ce qui le distingue de « ce soir ».
_VILLE_ECRITE = re.compile(
    r"(?:"
    r"\b(?:à|a|au|aux|en|in|for|pour)\s+"
    r"|\b(?:météo|meteo|weather|forecast|prévision|prevision)\s+"
    r"(?:de\s+|d['’]|à\s+|a\s+|au\s+|in\s+|for\s+|pour\s+)?"
    r")"
    r"([A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’.-]*){0,2})"
)

# 29/09/2026 : « en France » et « ce soir » ne sont pas une ville. Les
# prendre pour cible rendait une fourchette nationale au lieu d'une
# question. La voix écrit aussi « à lyon » sans majuscule.
_PAS_UNE_VILLE = frozenset(
    {
        "soir",
        "matin",
        "midi",
        "nuit",
        "maintenant",
        "aujourdhui",
        "aujourd'hui",
        "demain",
        "hier",
        "moment",
        "instant",
        "heure",
        "heures",
        "direct",
        "present",
        "presentement",
        "actuellement",
        "couramment",
        "faire",
        "fais",
        "cuisiner",
        "preparer",
        "manger",
        "avoir",
        "vouloir",
        "recette",
        "recettes",
        "pates",
        "general",
        "moyenne",
        "semaine",
        "mois",
        "annee",
        "hui",
        "ce",
        "france",
        "canada",
        "belgique",
        "suisse",
        "espagne",
        "italie",
        "allemagne",
        "portugal",
        "europe",
        "japon",
        "chine",
        "mexique",
        "bresil",
        "maroc",
        "angleterre",
        "ecosse",
        "irlande",
        "amerique",
        "afrique",
        "asie",
    }
)
_VILLE_PLATE = re.compile(
    r"(?:"
    r"\b(?:a|au|aux|en|in|for|pour)\s+"
    r"|\b(?:meteo|weather|forecast|prevision)\s+"
    r"(?:de\s+|d'|a\s+|au\s+|in\s+|for\s+|pour\s+)?"
    r")"
    r"([a-z][\w'-]{2,}(?:\s+[a-z][\w'-]{2,}){0,2})"
)

_GEO = "https://geocoding-api.open-meteo.com/v1/search"
_PREVISION = "https://api.open-meteo.com/v1/forecast"


def _retenir(nom: str) -> str:
    propre = nom.strip(" .,;:!?")
    if not propre:
        return ""
    plat = _plat(propre)
    if plat in _PAS_UNE_VILLE or plat.split()[0] in _PAS_UNE_VILLE:
        return ""
    return propre


def ville_ecrite(question: str) -> str:
    """Une ville écrite sans le mot météo (« et pour Lyon »).

    "" si la table canadienne la connaît déjà, ou si ce n'est pas une ville.
    """
    if ville_de(question, ""):
        return ""
    for mot in _VILLE_PLATE.finditer(_plat(question)):
        retenu = _retenir(mot.group(1))
        if retenu:
            return retenu
    return ""


def ville_hors_table(question: str) -> str:
    """La ville écrite dans une question météo, si la table canadienne ne
    la connaît pas. "" quand aucune ville n'est nommée (§34) ou quand
    Environnement Canada a déjà une page pour elle."""
    if not _METEO.search(_plat(question)):
        return ""
    if ville_de(question, ""):
        return ""
    trouve = _VILLE_ECRITE.search(question)
    if trouve is not None:
        retenu = _retenir(trouve.group(1))
        if retenu:
            return retenu
    for mot in _VILLE_PLATE.finditer(_plat(question)):
        retenu = _retenir(mot.group(1))
        if retenu:
            return retenu
    return ""


def lire_aux_coordonnees(
    latitude: float,
    longitude: float,
    obtenir: Callable[[str], str] | None = None,
) -> str:
    """Le degré actuel aux coordonnées du Mac, ou "".

    Le nom vient du géocodage inverse. La température est relue : le
    cache de Météo peut dater de plusieurs semaines.
    """
    lire = obtenir or _http_get
    ville, pays = _nom_du_lieu(latitude, longitude, lire)
    try:
        mesure = lire(
            _PREVISION
            + "?"
            + urlencode(
                {
                    "latitude": f"{latitude:.4f}",
                    "longitude": f"{longitude:.4f}",
                    "current": "temperature_2m,weather_code",
                    "timezone": "auto",
                }
            )
        )
        courant = json.loads(mesure).get("current") or {}
        degre = _degre(float(courant["temperature_2m"]))
        temps = _temps(int(courant.get("weather_code") or 0))
    except (
        OSError,
        httpx.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ):
        return ""
    if not ville and not degre:
        return ""
    endroit = f"{ville}, {pays}" if ville and pays else (ville or "ici")
    return (
        f"{endroit} — Open-Meteo, consultée le {date.today().isoformat()}\n"
        f"Maintenant : {degre}, {temps}.\n"
    )


def lire_prevision_ouverte(
    question: str, obtenir: Callable[[str], str] | None = None
) -> str:
    """Le texte de la prévision pour la ville nommée, ou ""."""
    nom = ville_hors_table(question)
    if not nom:
        return ""
    lire = obtenir or _http_get
    try:
        corps = lire(
            _GEO + "?" + urlencode({"name": nom, "count": 1, "language": "fr"})
        )
        resultats = json.loads(corps).get("results") or []
        if not resultats:
            return ""
        lieu = resultats[0]
        latitude = float(lieu["latitude"])
        longitude = float(lieu["longitude"])
        ville = str(lieu.get("name") or nom)
        pays = str(lieu.get("country") or "").strip()
        mesure = lire(
            _PREVISION
            + "?"
            + urlencode(
                {
                    "latitude": f"{latitude:.4f}",
                    "longitude": f"{longitude:.4f}",
                    "current": "temperature_2m,weather_code",
                    "timezone": "auto",
                }
            )
        )
        courant = json.loads(mesure).get("current") or {}
        degre = _degre(float(courant["temperature_2m"]))
        temps = _temps(int(courant.get("weather_code") or 0))
    except (
        OSError,
        httpx.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ):
        return ""
    endroit = f"{ville}, {pays}" if pays else ville
    return (
        f"{endroit} — Open-Meteo, consultée le {date.today().isoformat()}\n"
        f"Maintenant : {degre}, {temps}.\n"
    )


def _nom_du_lieu(
    latitude: float, longitude: float, lire: Callable[[str], str]
) -> tuple[str, str]:
    """Ville et pays aux coordonnées. "" si le service de noms ne répond pas :
    le degré, lui, se lit quand même."""
    url = "https://nominatim.openstreetmap.org/reverse?" + urlencode(
        {
            "lat": f"{latitude:.4f}",
            "lon": f"{longitude:.4f}",
            "format": "json",
            "accept-language": "fr",
        }
    )
    try:
        adresse = json.loads(lire(url)).get("address") or {}
    except (
        OSError,
        httpx.HTTPError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return "", ""
    for cle in ("city", "town", "village", "municipality", "hamlet"):
        if adresse.get(cle):
            return str(adresse[cle]), str(adresse.get("country") or "")
    return "", ""


def _degre(valeur: float) -> str:
    arrondi = round(valeur, 1)
    if arrondi == int(arrondi):
        return f"{int(arrondi)} °C"
    return f"{arrondi:.1f}".replace(".", ",") + " °C"


def _temps(code: int) -> str:
    if code == 0:
        return "ciel dégagé"
    if code in (1, 2):
        return "partiellement nuageux"
    if code == 3:
        return "couvert"
    if code in (45, 48):
        return "brouillard"
    if 51 <= code <= 67 or code in (80, 81, 82):
        return "pluie"
    if 71 <= code <= 77 or code in (85, 86):
        return "neige"
    if code >= 95:
        return "orage"
    return "conditions variables"


def _http_get(url: str) -> str:
    import httpx

    # Nominatim refuse une requête sans identité. Open-Meteo l'accepte.
    reponse = httpx.get(
        url,
        timeout=8.0,
        follow_redirects=True,
        headers={"User-Agent": "Diapason/1.0 (assistant local)"},
    )
    reponse.raise_for_status()
    return reponse.text
