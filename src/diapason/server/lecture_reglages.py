"""Deux réglages du Mac, lus par HTTP — en lecture seule, sans secret.

26/09/2026 : hors de l'app de bureau (le téléphone, un navigateur), le
bundle ne peut pas appeler les commandes Tauri `get_cloud_key_status` et
`get_inference_source`. Il inventait donc la réponse : aucune clé cloud
(`{}`) et une source d'inférence « ollama ». Le téléphone aurait affiché une
source qui contredit celle du Mac, et caché les modèles cloud d'un Mac qui
en a les clés.

Ces deux routes disent ce que le SERVEUR voit :

- ``GET /v1/cloud/keys`` : pour chaque nom de clé que l'app de bureau gère,
  présente ou absente (``set``), jamais sa valeur. « Présente » veut dire
  dans l'environnement du serveur, ou dans le trousseau — dont on ne lit
  que les attributs, jamais le secret (``cloud_key_present``).
- ``GET /v1/inference/source`` : ``inference.json``, que l'app de bureau
  écrit, avec la même règle qu'elle : un fichier absent ou illisible vaut
  Ollama. L'hôte est réduit à schéma, nom et port : ni identifiants, ni
  chemin, ni requête. Un hôte qui n'est pas une URL http(s) lisible est
  omis, et ``hostIllisible`` le dit.

Rien ici n'écrit : choisir une source ou enregistrer une clé reste l'affaire
de l'app de bureau, qui tient le trousseau.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter

from diapason.core.cloud_keys import cloud_key_present
from diapason.core.paths import get_config_dir

# Miroir de MANAGED_CLOUD_KEY_NAMES (frontend/src-tauri/src/lib.rs). Un test
# lit lib.rs et compare : une clé ajoutée d'un seul côté serait tue ici.
NOMS_DE_CLES_GERES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
    "TAVILY_API_KEY",
)

# Miroir de CUSTOM_FALLBACK_ENGINE (lib.rs), gardé par le même test.
MOTEUR_PAR_DEFAUT = "lmstudio"

_NOM_VALIDE = re.compile(r"^[A-Z0-9_]{1,128}$")


def nom_de_cle_du_moteur(moteur: str) -> str:
    """``lm-studio`` → ``LM_STUDIO_API_KEY``, comme ``engine_api_key_name``."""
    normalise = "".join(
        c.upper() if c.isascii() and c.isalnum() else "_" for c in moteur
    )
    nettoye = normalise.strip("_") or MOTEUR_PAR_DEFAUT.upper()
    return f"{nettoye}_API_KEY"


def _chemin_inference() -> Path:
    return get_config_dir() / "inference.json"


def lire_source_inference(chemin: Path | None = None) -> dict[str, Any]:
    """La source choisie dans l'app de bureau, Ollama par défaut."""
    chemin = chemin or _chemin_inference()
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"kind": "ollama"}
    if not isinstance(brut, dict):
        return {"kind": "ollama"}
    genre = brut.get("kind", "ollama")
    if genre not in ("ollama", "custom"):
        # Rust refuse un genre inconnu et retombe sur Ollama : même verdict.
        return {"kind": "ollama"}
    source: dict[str, Any] = {"kind": genre}
    for champ in ("model", "engine"):
        valeur = brut.get(champ)
        if isinstance(valeur, str) and valeur:
            source[champ] = valeur
    hote = brut.get("host")
    if isinstance(hote, str) and hote:
        propre = _hote_sans_identifiants(hote)
        if propre:
            source["host"] = propre
        else:
            source["hostIllisible"] = True
    return source


def _hote_sans_identifiants(hote: str) -> str:
    """``schéma://nom[:port]`` d'une URL http(s), ou ``""``.

    26/09/2026 : seul ``user:mot@`` était retiré, et seulement quand
    ``urlsplit`` le voyait. ``u:secretpw@h:1234`` (sans « // ») ressortait
    intact, ``https://h/v1?api_key=sk-…`` gardait sa requête, et un port non
    numérique levait hors de tout ``try`` : 500. ``normalize_host`` (lib.rs)
    n'impose ni schéma ni forme ; c'est donc ici qu'on ne rend que ce qui
    est sûr.
    """
    try:
        morceaux = urlsplit(hote.strip())
        if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
            return ""
        port = morceaux.port
    except ValueError:
        return ""
    nom = morceaux.hostname
    if ":" in nom:
        nom = f"[{nom}]"
    lieu = nom if port is None else f"{nom}:{port}"
    return urlunsplit((morceaux.scheme, lieu, "", "", ""))


def noms_de_cles_geres(source: dict[str, Any] | None = None) -> list[str]:
    """Les noms que l'app de bureau affiche, triés (``managed_cloud_key_names``)."""
    noms = set(NOMS_DE_CLES_GERES)
    source = source if source is not None else lire_source_inference()
    if source.get("kind") == "custom":
        nom = nom_de_cle_du_moteur(str(source.get("engine") or MOTEUR_PAR_DEFAUT))
        if _NOM_VALIDE.match(nom):
            noms.add(nom)
    return sorted(noms)


def create_lecture_reglages_router() -> APIRouter:
    router = APIRouter()

    # Routes SYNCHRONES à dessein : `cloud_key_present` lance `security`
    # (jusqu'à 5 s par clé si le trousseau hésite). Dans une route `async`, ce serait
    # sur la boucle d'événements et tout le serveur gèlerait (CLAUDE.md §5).
    @router.get("/v1/cloud/keys")
    def statut_des_cles_cloud() -> dict[str, Any]:
        return {
            "keys": [
                {"key": nom, "set": cloud_key_present(nom)}
                for nom in noms_de_cles_geres()
            ]
        }

    @router.get("/v1/inference/source")
    def source_inference() -> dict[str, Any]:
        return lire_source_inference()

    return router
