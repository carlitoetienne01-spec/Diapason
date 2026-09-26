"""La compression des réponses JSON de l'API — et de rien d'autre.

26/09/2026, chantier de la fluidité (lot 1, le réseau). Le JSON de l'API
partait brut au téléphone : 365 834 octets pour la liste des tâches au banc
(825 Ko chez Carlito), relue par Tâches, Planificateur ET Projets, à
10 Mbit/s en 4G. Comprimée, elle en pèse 31 292 en brotli et 35 291 en
gzip (mesuré par la passerelle de banc le 26/09/2026).

Le défaut qu'elle ne doit jamais introduire : retarder un flux. Voir la
docstring de ``CompressionDesReponses``.
"""

from __future__ import annotations

import asyncio
import gzip
from typing import Any

from starlette.datastructures import Headers, MutableHeaders

from diapason.server.bundle_statique import choisir_encodage, encodages_acceptes

__all__ = ["SEUIL_DE_COMPRESSION", "CompressionDesReponses"]

# Sous ~1 Ko, une réponse tient dans un seul paquet du tailnet (MTU 1 280) :
# la comprimer ne gagne ni un paquet ni un aller-retour, seulement du
# processeur et un en-tête. Au-dessus, le gain est net : la liste des tâches
# (365 534 octets au banc) tombe à 31 292 en brotli.
SEUIL_DE_COMPRESSION = 1024

# Au-delà, on comprime dans un fil. Mesuré le 26/09/2026 (Apple M5) :
# brotli 5 prend 0,16 ms pour 64 Ko, 1,15 ms pour 380 Ko — une milliseconde
# volée à la boucle, c'est une milliseconde de retard sur chaque mot du chat
# et chaque trame de la voix.
_SEUIL_DU_FIL = 64 * 1024

# Brotli 5 : 18 177 octets pour 380 Ko de JSON de tâches en 1,15 ms, contre
# 23 900 en 1,32 ms pour gzip 6 (mesuré le 26/09/2026). Au-dessus de 6, le
# temps croît plus vite que le gain.
_QUALITE_BROTLI = 5
_NIVEAU_GZIP = 6


def _brotli() -> Any:
    try:
        import brotli  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - dépend de l'installation
        return None
    return brotli


def _type_json(type_de_contenu: str) -> bool:
    essentiel = type_de_contenu.split(";", 1)[0].strip().lower()
    return essentiel == "application/json" or (
        essentiel.startswith("application/") and essentiel.endswith("+json")
    )


def _comprimer(corps: bytes, encodage: str) -> bytes:
    if encodage == "br":
        return _brotli().compress(corps, quality=_QUALITE_BROTLI)
    return gzip.compress(corps, compresslevel=_NIVEAU_GZIP, mtime=0)


class CompressionDesReponses:
    """Comprime les réponses JSON COMPLÈTES de l'application — rien d'autre.

    Le défaut qu'elle ne doit jamais introduire : retarder un flux. Le chat
    (SSE), la voix (WebSocket) et toute réponse en morceaux passent sans
    être touchés, pour trois raisons indépendantes :

    - seul ``http`` est lu ; un WebSocket traverse sans que rien ne l'écoute ;
    - seul un type JSON est candidat : ``text/event-stream``, l'audio et le
      HTML n'y sont pas ;
    - seule une réponse dont le PREMIER morceau est aussi le dernier est
      comprimée. Un ``StreamingResponse`` — même déclaré JSON — envoie
      ``more_body=True`` : l'en-tête part aussitôt, chaque morceau aussi.

    Doit être le middleware le plus intérieur : ``BaseHTTPMiddleware`` (la
    sécurité, la clé) redécoupe toute réponse en flux, et vue d'au-dessus
    d'eux plus rien ne serait « complet ».
    """

    def __init__(self, app: Any, seuil: int = SEUIL_DE_COMPRESSION) -> None:
        self.app = app
        self.seuil = seuil

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") == "HEAD":
            await self.app(scope, receive, send)
            return
        acceptes = encodages_acceptes(Headers(scope=scope).get("accept-encoding"))
        disponibles = ("br", "gzip") if _brotli() is not None else ("gzip",)
        encodage = choisir_encodage(acceptes, disponibles)
        if encodage is None:
            await self.app(scope, receive, send)
            return

        debut: dict | None = None
        transparent = False

        async def envoyer(message: dict) -> None:
            nonlocal debut, transparent
            if transparent:
                await send(message)
                return
            if message["type"] == "http.response.start":
                entetes = Headers(raw=message.get("headers", []))
                if (
                    not _type_json(entetes.get("content-type", ""))
                    or "content-encoding" in entetes
                    or "content-range" in entetes
                    or message.get("status") in (204, 304)
                ):
                    transparent = True
                    await send(message)
                    return
                debut = message
                return
            if message["type"] != "http.response.body" or debut is None:
                await send(message)
                return
            corps = message.get("body", b"")
            if message.get("more_body", False):
                # Une réponse en morceaux : on rend la main, tout de suite.
                transparent = True
                await send(debut)
                await send(message)
                return
            entetes = MutableHeaders(raw=list(debut.get("headers", [])))
            entetes.add_vary_header("Accept-Encoding")
            if len(corps) >= self.seuil:
                if len(corps) > _SEUIL_DU_FIL:
                    comprime = await asyncio.to_thread(_comprimer, corps, encodage)
                else:
                    comprime = _comprimer(corps, encodage)
                if len(comprime) < len(corps):
                    corps = comprime
                    entetes["content-encoding"] = encodage
                    entetes["content-length"] = str(len(corps))
                    # Un ETag fort désigne des OCTETS : ceux-ci ne sont plus
                    # ceux qu'il nommait. Faible, il reste vrai (même sens).
                    etag = entetes.get("etag")
                    if etag and not etag.startswith("W/"):
                        entetes["etag"] = "W/" + etag
            await send({**debut, "headers": entetes.raw})
            await send({"type": "http.response.body", "body": corps})

        await self.app(scope, receive, envoyer)
