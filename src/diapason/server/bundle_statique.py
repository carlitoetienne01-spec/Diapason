"""Le bundle servi par le serveur : ce qui se garde, ce qui se revalide,
ce qui se comprime.

26/09/2026, chantier de la fluidité (lot 1, le réseau). Le téléphone ouvre
le bundle React par la passerelle du tailnet, à 110 ms d'aller-retour en 4G.
Jusqu'ici, CHAQUE fichier partait en ``no-cache, no-store, must-revalidate``,
sans ETag ni Last-Modified, et sans compression : 2 480 Ko retéléchargés à
chaque ouverture de l'app (2 350 ms jusqu'à la Discussion, mesuré au banc à
processeur ×4), dont un ``index-*.js`` de 1 422 181 octets qui en pèse
353 108 en brotli. Rien dans l'historique ne justifiait le ``no-store`` : il
datait du renommage du dépôt.

Quatre règles, et elles tiennent ensemble :

1. **Les fichiers à empreinte sont immuables.** ``/assets/<nom>-<hash>.<ext>``
   : Vite change le nom dès que le contenu change, donc un nom donné n'a
   qu'un contenu, pour toujours. ``public, max-age=31536000, immutable``.
2. **Le document ne se garde pas.** ``index.html`` (et tout ``.html``)
   part en ``no-store`` : c'est lui qui nomme les empreintes, donc lui qui
   garantit que le téléphone exécute EXACTEMENT le bundle du Mac. En
   ``no-cache``, un retour arrière le reprenait du cache SANS le redemander
   — Chromium 152, cache de retour arrière coupé comme dans la WebView
   (26/09/2026) : l'ancien index et son ancien bundle tournaient après un
   nouveau build, zéro requête. Il pèse 909 octets : le garder ne gagnait
   que l'écart entre un 304 et un 200, dans le même aller-retour.
3. **Tout le reste se revalide.** ``sw.js``, le manifeste, les icônes et
   les polices sans empreinte : ``no-cache`` et un ETag. ``no-cache`` ne
   veut pas dire « ne pas garder » : le navigateur garde, mais redemande à
   chaque usage ; un 304 de quelques centaines d'octets répond quand rien
   n'a changé.
4. **Les variantes précomprimées sont choisies, jamais fabriquées ici.**
   ``frontend/scripts/precomprimer.mjs`` pose ``.br`` et ``.gz`` à côté de
   chaque fichier texte au build ; on sert la meilleure que le client
   accepte, avec ``Vary: Accept-Encoding``. Comprimer à la volée un fichier
   de 1,4 Mo en brotli 11 prendrait plus d'une seconde sur la boucle.

Les réponses de l'API ne passent jamais par ici : ``/v1/*`` n'est ni monté
ni rattrapé par ce module (voir ``passerelle_tailnet._ESPACES_D_API``). Leur
compression vit dans ``server/compression_api.py``, qui ne touche qu'au
corps, jamais au cache.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
from email.utils import parsedate
from mimetypes import guess_type
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles

__all__ = [
    "CACHE_DOCUMENT",
    "CACHE_IMMUABLE",
    "CACHE_REVALIDE",
    "COMPRESSIBLES",
    "FichiersDuBundle",
    "ReponseDuBundle",
    "choisir_encodage",
    "cache_hors_empreinte",
    "encodages_acceptes",
    "fichier_du_bundle",
    "monter_le_bundle",
    "porte_une_empreinte",
]

CACHE_IMMUABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDE = "no-cache"
CACHE_DOCUMENT = "no-store"

# L'empreinte que Vite pose par défaut : huit caractères base64url avant
# l'extension (« index-DP3oxbgi.css », « KaTeX_Main-Regular-CTRA-rTL.woff »).
_EMPREINTE_RE = re.compile(r"-[A-Za-z0-9_-]{8}\.[A-Za-z0-9]+$")

# Les extensions que precomprimer.mjs traite — la même liste des deux côtés,
# vérifiée par tests/server/test_bundle_statique.py. Les woff2, png et autres
# formats déjà comprimés n'y sont pas : les recomprimer ne gagne rien.
COMPRESSIBLES = frozenset(
    {
        ".js",
        ".mjs",
        ".css",
        ".html",
        ".svg",
        ".json",
        ".webmanifest",
        ".txt",
        ".xml",
        ".map",
        ".ttf",
        ".otf",
        ".ico",
        ".wasm",
    }
)

# L'ordre est la préférence : brotli gagne ~17 % sur gzip (626 Ko contre
# 752 Ko pour l'ouverture de l'app, node zlib, 26/09/2026).
_VARIANTES = (("br", ".br"), ("gzip", ".gz"))


def porte_une_empreinte(nom: str) -> bool:
    """Vrai quand le nom du fichier porte une empreinte de contenu Vite."""
    return bool(_EMPREINTE_RE.search(nom))


def cache_hors_empreinte(nom: str) -> str:
    """La règle d'un fichier sans empreinte : ``no-store`` pour un document
    HTML (règle 2), ``no-cache`` pour le reste (règle 3)."""
    if os.path.splitext(nom)[1].lower() in (".html", ".htm"):
        return CACHE_DOCUMENT
    return CACHE_REVALIDE


def encodages_acceptes(entete: str | None) -> frozenset[str]:
    """Les codages qu'un ``Accept-Encoding`` autorise (``q=0`` exclut).

    Un ``*`` accepté vaut pour br et gzip, sauf s'ils sont nommés à ``q=0``.
    """
    if not entete:
        return frozenset()
    acceptes: set[str] = set()
    refuses: set[str] = set()
    joker = False
    for morceau in entete.split(","):
        nom, _, params = morceau.strip().partition(";")
        nom = nom.strip().lower()
        if not nom:
            continue
        q = 1.0
        for param in params.split(";"):
            cle, _, valeur = param.strip().partition("=")
            if cle.strip().lower() == "q":
                try:
                    q = float(valeur)
                except ValueError:
                    q = 0.0
        if q <= 0:
            refuses.add(nom)
        elif nom == "*":
            joker = True
        else:
            acceptes.add(nom)
    if joker:
        acceptes |= {"br", "gzip"} - refuses
    return frozenset(acceptes - refuses)


def choisir_encodage(
    acceptes: frozenset[str], disponibles: tuple[str, ...] = ("br", "gzip")
) -> str | None:
    """Le premier codage de ``disponibles`` que le client accepte."""
    for encodage in disponibles:
        if encodage in acceptes:
            return encodage
    return None


def fichier_du_bundle(racine: Path, chemin: str) -> Path:
    """Le fichier que l'attrape-tout sert pour ``chemin`` : lui s'il existe
    sous ``racine``, sinon ``index.html`` (une route de la SPA)."""
    if chemin:
        candidat = (racine / chemin).resolve()
        if candidat.is_relative_to(racine.resolve()) and candidat.is_file():
            return candidat
    return racine / "index.html"


def _variante(
    chemin: str, stat_brut: os.stat_result | None, acceptes: frozenset[str]
) -> tuple[str, os.stat_result, str | None]:
    """Le fichier à envoyer : la variante précomprimée si elle est là, à jour,
    et acceptée ; sinon l'original. Appelée dans un fil (des ``stat``)."""
    if stat_brut is None:
        stat_brut = os.stat(chemin)
    if os.path.splitext(chemin)[1].lower() in COMPRESSIBLES:
        for encodage, suffixe in _VARIANTES:
            if encodage not in acceptes:
                continue
            try:
                stat_variante = os.stat(chemin + suffixe)
            except OSError:
                continue
            # Une variante plus vieille que son original vient d'un build
            # précédent (un `vite build` lancé sans `npm run build`, une copie
            # qui a remplacé le fichier sans elle) : la servir, ce serait
            # exécuter au téléphone un bundle que le Mac n'a plus.
            if (
                stat.S_ISREG(stat_variante.st_mode)
                and stat_variante.st_mtime >= stat_brut.st_mtime
            ):
                return chemin + suffixe, stat_variante, encodage
    return chemin, stat_brut, None


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
    """Un fichier du bundle : variante choisie, cache posé, 304 si l'ETag
    concorde. Le choix se fait à l'envoi, dans un fil : une route ``async``
    qui lit le disque sur la boucle gèle tout (CLAUDE.md §5)."""

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
        acceptes = encodages_acceptes(requete.get("accept-encoding"))
        servi, stat_servi, encodage = await asyncio.to_thread(
            _variante, self.chemin, self.stat_result, acceptes
        )
        entetes = {"cache-control": self.cache_control}
        if os.path.splitext(self.chemin)[1].lower() in COMPRESSIBLES:
            entetes["vary"] = "Accept-Encoding"
        if encodage is not None:
            entetes["content-encoding"] = encodage
        reponse: Response = FileResponse(
            servi,
            status_code=self.status_code,
            stat_result=stat_servi,
            media_type=guess_type(self.chemin)[0] or "text/plain",
            headers=entetes,
        )
        if self.status_code == 200 and _non_modifie(reponse.headers, requete):
            reponse = NotModifiedResponse(reponse.headers)
        await reponse(scope, receive, send)


class FichiersDuBundle(StaticFiles):
    """``/assets`` : immuable quand le nom porte une empreinte, revalidé
    sinon ; variantes précomprimées servies selon ``Accept-Encoding``."""

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Any,
        status_code: int = 200,
    ) -> Response:
        nom = os.path.basename(os.fspath(full_path))
        if porte_une_empreinte(nom):
            cache = CACHE_IMMUABLE
        else:
            cache = cache_hors_empreinte(nom)
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
        return ReponseDuBundle(chemin, cache_hors_empreinte(chemin.name))
