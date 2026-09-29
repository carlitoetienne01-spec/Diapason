"""Le lieu que l'app Météo du Mac a déjà ouvert.

29/09/2026 : « Quelle température il fait à présentement ? » partait en
recherche et revenait « entre 10 °C en Savoie et 22 °C », plus Ottawa
pris dans la config. « à présentement » n'est pas une ville. L'app
Météo garde dans son cache l'URL de la dernière prévision, avec les
coordonnées du lieu. On lit cette URL — pas le jeton, pas le corps —
et Open-Meteo donne le degré du jour. Sans ce cache, on demande la ville.

Appelants : ``stream_with_tools`` et ``LocalVoiceSession._respond_to_text``.
Pas de route nouvelle, pas de champ sur le fil. Carlito : « aller
vérifier dans météo sur le système de mon mac pour voir la ville ».
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from diapason.server.meteo_ouverte import lire_aux_coordonnees, ville_hors_table
from diapason.server.sources_officielles import _METEO, _plat, ville_de

_CACHE = (
    Path.home()
    / "Library/Containers/com.apple.weather/Data/Library/Caches"
    / "com.apple.weather/Cache.db"
)
_COORD = re.compile(r"/weather/[^/]+/(-?\d+\.\d+)/(-?\d+\.\d+)")
_MAINTENANT = re.compile(r"Maintenant : (-?\d+(?:,\d+)? °C)")
_LIEU = re.compile(r"^([^,\n]+)")


def coordonnees_meteo_mac(chemin: Path | None = None) -> tuple[float, float] | None:
    """Les coordonnées de la dernière prévision ouverte dans Météo, ou None."""
    base = chemin or _CACHE
    if not base.is_file():
        return None
    try:
        connexion = sqlite3.connect(f"file:{base}?mode=ro", uri=True, timeout=1.0)
        try:
            ligne = connexion.execute(
                "SELECT request_key FROM cfurl_cache_response "
                "WHERE request_key LIKE '%/weather/%' "
                "ORDER BY entry_ID DESC LIMIT 1"
            ).fetchone()
        finally:
            connexion.close()
    except sqlite3.Error:
        return None
    if not ligne:
        return None
    trouve = _COORD.search(str(ligne[0]))
    if trouve is None:
        return None
    return float(trouve.group(1)), float(trouve.group(2))


def phrase_ici(
    question: str,
    localiser=None,
    obtenir=None,
) -> str:
    """Le degré du lieu Météo, ou "" quand la question nomme déjà une ville
    ou que le Mac n'en a pas."""
    from diapason.server.precision import sujet_quitte

    if sujet_quitte(question):
        return ""
    if not _METEO.search(_plat(question or "")):
        return ""
    if ville_de(question, "") or ville_hors_table(question):
        return ""
    lire_lieu = localiser or coordonnees_meteo_mac
    lieu = lire_lieu()
    if not lieu:
        return ""
    latitude, longitude = lieu
    corpus = lire_aux_coordonnees(latitude, longitude, obtenir)
    degre = _MAINTENANT.search(corpus or "")
    if degre is None:
        return ""
    entete = _LIEU.search(corpus)
    nom = entete.group(1).strip() if entete else ""
    if nom and nom != "ici":
        return f"À {nom}, il fait {degre.group(1)}."
    return f"Il fait {degre.group(1)}."
