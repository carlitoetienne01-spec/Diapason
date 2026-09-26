"""Le bundle servi par le serveur : ce qui se garde, ce qui se revalide.

26/09/2026, chantier de la fluidité (lot 1, le réseau). Le téléphone ouvre
le bundle React par la passerelle du tailnet, à 110 ms d'aller-retour en 4G.
Jusqu'ici, CHAQUE fichier partait en ``no-cache, no-store, must-revalidate``,
sans ETag ni Last-Modified, et sans compression : 2 480 Ko retéléchargés à
chaque ouverture de l'app (2 350 ms jusqu'à la Discussion, mesuré au banc à
processeur ×4). Rien dans l'historique ne justifiait le ``no-store`` : il
datait du renommage du dépôt.

Deux règles, et elles tiennent ensemble :

1. **Les fichiers à empreinte sont immuables.** ``/assets/<nom>-<hash>.<ext>``
   : Vite change le nom dès que le contenu change, donc un nom donné n'a
   qu'un contenu, pour toujours. ``public, max-age=31536000, immutable``.
2. **Tout le reste se revalide.** ``index.html``, ``sw.js``, le manifeste,
   les icônes et les polices sans empreinte : ``no-cache`` et un ETag.
   ``no-cache`` ne veut pas dire « ne pas garder » : le navigateur garde,
   mais redemande à chaque usage ; un 304 de quelques centaines d'octets
   répond quand rien n'a changé. C'est ce qui garantit que le téléphone
   exécute EXACTEMENT le bundle du Mac : un nouveau build réécrit
   ``index.html`` (nouvel ETag), qui ne nomme que les nouvelles empreintes.

Les réponses de l'API ne passent jamais par ici : ``/v1/*`` n'est ni monté
ni rattrapé par ce module (voir ``passerelle_tailnet._ESPACES_D_API``).
"""

from __future__ import annotations

import asyncio
import os
import re
from email.utils import parsedate
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles

__all__ = [
    "CACHE_IMMUABLE",
    "CACHE_REVALIDE",
    "FichiersDuBundle",
    "ReponseDuBundle",
    "fichier_du_bundle",
    "monter_le_bundle",
    "porte_une_empreinte",
]

CACHE_IMMUABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDE = "no-cache"

# L'empreinte que Vite pose par défaut : huit caractères base64url avant
# l'extension (« index-DP3oxbgi.css », « KaTeX_Main-Regular-CTRA-rTL.woff »).
_EMPREINTE_RE = re.compile(r"-[A-Za-z0-9_-]{8}\.[A-Za-z0-9]+$")


def porte_une_empreinte(nom: str) -> bool:
    """Vrai quand le nom du fichier porte une empreinte de contenu Vite."""
    return bool(_EMPREINTE_RE.search(nom))


def fichier_du_bundle(racine: Path, chemin: str) -> Path:
    """Le fichier que l'attrape-tout sert pour ``chemin`` : lui s'il existe
    sous ``racine``, sinon ``index.html`` (une route de la SPA)."""
    if chemin:
        candidat = (racine / chemin).resolve()
        if candidat.is_relative_to(racine.resolve()) and candidat.is_file():
            return candidat
    return racine / "index.html"


def _non_modifie(reponse: Headers, requete: Headers) -> bool:
    """La règle de ``StaticFiles.is_not_modified`` : ``If-None-Match`` d'abord,
    ``If-Modified-Since`` seulement en son absence (RFC 9110 §13.2.2)."""
    si_aucun = requete.get("if-none-match")
    if si_aucun is not None:
        etag = reponse.get("etag", "").removeprefix("W/")
        return any(
            morceau.strip().removeprefix("W/") in (etag, "*")
            for morceau in si_aucun.split(",")
        )
    depuis = parsedate(requete.get("if-modified-since", ""))
    modifie = parsedate(reponse.get("last-modified", ""))
    return depuis is not None and modifie is not None and depuis >= modifie


class ReponseDuBundle(Response):
    """Un fichier du bundle : cache posé, 304 si l'ETag concorde. Le ``stat``
    se fait à l'envoi, dans un fil : une route ``async`` qui lit le disque
    sur la boucle gèle tout (CLAUDE.md §5)."""

    def __init__(
        self,
        chemin: str | os.PathLike[str],
        cache_control: str,
        stat_result: os.stat_result | None = None,
        status_code: int = 200,
    ) -> None:
        super().__init__(status_code=status_code)
        self.chemin = os.fspath(chemin)
        self.cache_control = cache_control
        self.stat_result = stat_result

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        requete = Headers(scope=scope)
        stat_servi = self.stat_result or await asyncio.to_thread(os.stat, self.chemin)
        reponse: Response = FileResponse(
            self.chemin,
            status_code=self.status_code,
            stat_result=stat_servi,
            headers={"cache-control": self.cache_control},
        )
        if self.status_code == 200 and _non_modifie(reponse.headers, requete):
            reponse = NotModifiedResponse(reponse.headers)
        await reponse(scope, receive, send)


class FichiersDuBundle(StaticFiles):
    """``/assets`` : immuable quand le nom porte une empreinte, revalidé
    sinon."""

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Any,
        status_code: int = 200,
    ) -> Response:
        nom = os.path.basename(os.fspath(full_path))
        cache = CACHE_IMMUABLE if porte_une_empreinte(nom) else CACHE_REVALIDE
        return ReponseDuBundle(full_path, cache, stat_result, status_code)


def monter_le_bundle(app: Any, racine: Path) -> None:
    """``/assets`` et l'attrape-tout de la SPA, sur ``app``.

    À appeler APRÈS toutes les routes : l'attrape-tout répond à tout chemin
    qu'aucune route n'a pris.
    """
    assets = racine / "assets"
    if assets.is_dir():
        app.mount("/assets", FichiersDuBundle(directory=assets), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_catch_all(full_path: str) -> Response:
        """Serve static files directly, fall back to index.html for SPA routes."""
        # La recherche touche le disque : dans un fil, pas sur la boucle.
        chemin = await asyncio.to_thread(fichier_du_bundle, racine, full_path)
        return ReponseDuBundle(chemin, CACHE_REVALIDE)
