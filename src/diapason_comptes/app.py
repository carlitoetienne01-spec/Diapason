"""L'application FastAPI du service de comptes.

Conception : ``docs/development/compte-chiffre.md`` §3.1.

systemd la lance ainsi (étape 7) ::

    uvicorn diapason_comptes.app:app --host 127.0.0.1 --port 8710 --workers 1 \\
      --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log

``app`` n'est construite qu'au premier accès (``__getattr__`` de module) :
les tests importent ce module pour appeler :func:`creer_app` avec leurs
propres secrets, et une construction à l'import aurait exigé
``comptes.env`` sur toute machine qui lance ``pytest``.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from diapason_comptes import VERSION
from diapason_comptes.base import Base, espace_libre_reel, generation, global_seq
from diapason_comptes.courriel import (
    Courrier,
    Expediteur,
    ExpediteurResend,
    FileCourriels,
    charger_configuration_courriel,
)
from diapason_comptes.journal import Journal
from diapason_comptes.limites import (
    BudgetsCourriel,
    LimiteurConnexions,
    LimiteurIp,
    Portillon,
)
from diapason_comptes.routes_coffre import routeur as routeur_coffre
from diapason_comptes.routes_identite import routeur as routeur_identite
from diapason_comptes.routes_pieces import routeur as routeur_pieces
from diapason_comptes.routes_synchro import routeur as routeur_synchro
from diapason_comptes.secrets_serveur import (
    Configuration,
    SecretsServeur,
    charger_configuration,
    charger_secrets,
    journaliser_presence,
)
from diapason_comptes.validation import ErreurRequete

_journal = logging.getLogger("diapason_comptes")


def horloge_reelle() -> int:
    """Millisecondes entières (§3.4 : aucun flottant sur le fil)."""
    return time.time_ns() // 1_000_000


@dataclass
class Contexte:
    """Tout ce qu'une route touche, rangé dans ``app.state.contexte``."""

    configuration: Configuration
    secrets: SecretsServeur
    base: Base
    journal: Journal
    courrier: Courrier
    limiteur: LimiteurConnexions
    limiteur_ip: LimiteurIp
    horloge: Callable[[], int]
    espace_libre: Callable[[Path], int]
    portillon: Portillon = field(default_factory=Portillon)

    def fermer(self) -> None:
        self.courrier.file.arreter()
        self.base.fermer()


def creer_contexte(
    configuration: Configuration,
    secrets_: SecretsServeur,
    expediteur: Expediteur,
    *,
    origine_publique: str | None,
    horloge: Callable[[], int] = horloge_reelle,
    espace_libre: Callable[[Path], int] = espace_libre_reel,
    file_courriels: FileCourriels | None = None,
) -> Contexte:
    budgets = BudgetsCourriel(
        secrets_,
        codes_jour=configuration.budget_codes_jour,
        securite_jour=configuration.budget_securite_jour,
    )
    base = Base(configuration.chemin_base)
    return Contexte(
        configuration=configuration,
        secrets=secrets_,
        base=base,
        journal=Journal(configuration.chemin_journal, secrets_, base=base),
        courrier=Courrier(
            file_courriels or FileCourriels(expediteur),
            budgets,
            origine_publique=origine_publique,
        ),
        limiteur=LimiteurConnexions(secrets_),
        limiteur_ip=LimiteurIp(secrets_),
        horloge=horloge,
        espace_libre=espace_libre,
    )


# ----------------------------------------------------------------------
# En-têtes sur CHAQUE réponse (§3.1)
# ----------------------------------------------------------------------


class EnTetesSurs:
    """``Cache-Control: no-store`` et ``X-Content-Type-Options: nosniff``.

    ASGI pur plutôt que ``BaseHTTPMiddleware``, qui fait passer chaque
    réponse par une tâche et une file de plus. Un 500, lui, est produit par
    ``ServerErrorMiddleware``, À L'EXTÉRIEUR de celui-ci : ``_reponse_erreur``
    pose donc les deux en-têtes lui-même, sinon le 500 partait sans
    ``no-store``.
    """

    _POSES = ((b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"))

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        noms = {nom for nom, _ in self._POSES}

        async def envoyer(message: dict) -> None:
            if message["type"] == "http.response.start":
                en_tetes = [
                    (nom, valeur)
                    for nom, valeur in message.get("headers", [])
                    if nom.lower() not in noms
                ]
                message = {**message, "headers": en_tetes + list(self._POSES)}
            await send(message)

        await self.app(scope, receive, envoyer)


# ----------------------------------------------------------------------
# Erreurs : jamais d'écho (§3.1)
# ----------------------------------------------------------------------


def _reponse_erreur(erreur: ErreurRequete) -> JSONResponse:
    en_tetes = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if erreur.retry_after_s is not None:
        en_tetes["Retry-After"] = str(erreur.retry_after_s)
    return JSONResponse(erreur.corps(), status_code=erreur.statut, headers=en_tetes)


async def _erreur_requete(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ErreurRequete)
    return _reponse_erreur(exc)


async def _erreur_validation(_request: Request, exc: Exception) -> JSONResponse:
    """Remplace le gestionnaire de FastAPI, qui recopie l'entrée refusée
    (``"input": …``) dans le 422 : un ``authKey`` mal formé y serait revenu
    en écho. On ne nomme que le chemin du champ."""
    champ = "body"
    if isinstance(exc, RequestValidationError) and exc.errors():
        emplacement = [str(p) for p in exc.errors()[0].get("loc", ()) if p != "body"]
        champ = ".".join(emplacement) or "body"
    return _reponse_erreur(ErreurRequete(422, "invalidRequest", champ=champ))


_CODES_HTTP = {404: "notFound", 405: "methodNotAllowed", 413: "payloadTooLarge"}


async def _erreur_http(_request: Request, exc: Exception) -> JSONResponse:
    statut = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    return _reponse_erreur(ErreurRequete(statut, _CODES_HTTP.get(statut, "httpError")))


class ErreursInternes:
    """Toute exception imprévue devient un 500 sobre, et NE SORT PAS de
    l'application.

    Le TYPE seulement au journal : le message d'une exception SQLite ou
    d'AESGCM peut citer une valeur, et journald la garderait 7 jours.
    Jusqu'au 24/09/2026, c'était un gestionnaire ``Exception`` de
    Starlette : ``ServerErrorMiddleware`` l'appelle, puis RELANCE
    l'exception « pour que le serveur la journalise », et uvicorn écrivait
    message et trace dans ``uvicorn.error``. Ce middleware vit à
    l'intérieur : l'exception s'arrête ici.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        commencee = False

        async def envoyer(message: dict) -> None:
            nonlocal commencee
            if message["type"] == "http.response.start":
                commencee = True
            await send(message)

        try:
            await self.app(scope, receive, envoyer)
        except Exception as exc:
            _journal.error("erreur interne : %s", type(exc).__name__)
            if not commencee:
                await _reponse_erreur(ErreurRequete(500, "internal"))(
                    scope, receive, send
                )


# ----------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------


routeur_sante = APIRouter(prefix="/api/v1")


@routeur_sante.get("/health")
def health(request: Request) -> JSONResponse:
    """Sans authentification. ``generation`` et ``globalSeq`` permettent à un
    appareil de voir une perte ou un retour arrière du serveur (§3.10)."""
    contexte: Contexte = request.app.state.contexte
    with contexte.base.lecture() as conn:
        gen, seq = generation(conn), global_seq(conn)
    return JSONResponse(
        {
            "status": "ok",
            "version": VERSION,
            "timeMs": contexte.horloge(),
            "generation": gen,
            "globalSeq": seq,
        }
    )


# Tous les routeurs du service : ``scripts/gen_compte_surface.py`` en tire
# la surface figée sans construire l'application (donc sans secrets).
ROUTEURS = (
    routeur_sante,
    routeur_identite,
    routeur_coffre,
    routeur_synchro,
    routeur_pieces,
)


def creer_app(contexte: Contexte) -> FastAPI:
    app = FastAPI(
        title="Diapason — comptes",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.contexte = contexte
    app.add_exception_handler(ErreurRequete, _erreur_requete)
    app.add_exception_handler(RequestValidationError, _erreur_validation)
    app.add_exception_handler(StarletteHTTPException, _erreur_http)
    # Le dernier ajouté est le plus extérieur : ``EnTetesSurs`` pose donc
    # ses en-têtes sur le 500 d'``ErreursInternes`` aussi.
    app.add_middleware(ErreursInternes)
    app.add_middleware(EnTetesSurs)
    for routeur in ROUTEURS:
        app.include_router(routeur)
    return app


class _VersStderr(logging.StreamHandler):
    """``sys.stderr`` lu à chaque ligne, pas figé à la création : systemd le
    passe à journald, et un test qui le capture le voit."""

    @property  # type: ignore[override]
    def stream(self) -> Any:
        return sys.stderr

    @stream.setter
    def stream(self, _valeur: Any) -> None:
        pass


def configurer_journal() -> None:
    """Les lignes INFO du service vers stderr, donc journald.

    Rien ne configurait ``logging`` : uvicorn ne règle que ses propres
    journaux, le niveau effectif de ``diapason_comptes`` restait WARNING, et
    « secrets présents », seule trace que le §3.2 attend au démarrage,
    n'atteignait jamais journald (24/09/2026). Idempotent.
    """
    racine = logging.getLogger("diapason_comptes")
    if not any(isinstance(h, _VersStderr) for h in racine.handlers):
        gestionnaire = _VersStderr()
        gestionnaire.setFormatter(
            logging.Formatter("%(levelname)s %(name)s : %(message)s")
        )
        racine.addHandler(gestionnaire)
    racine.setLevel(logging.INFO)


def creer_app_depuis_environnement(env: Mapping[str, str] | None = None) -> FastAPI:
    """L'application de production. Refuse de démarrer s'il manque un secret
    de ``comptes.env`` ou une valeur de ``mail.env`` (§3.2)."""
    configurer_journal()
    env = os.environ if env is None else env
    secrets_ = charger_secrets(env)
    configuration = charger_configuration(env)
    configuration_courriel = charger_configuration_courriel(env)
    journaliser_presence(secrets_)
    contexte = creer_contexte(
        configuration,
        secrets_,
        ExpediteurResend(configuration_courriel),
        origine_publique=configuration_courriel.origine_publique,
    )
    return creer_app(contexte)


_APP: FastAPI | None = None


def __getattr__(nom: str) -> Any:
    global _APP
    if nom == "app":
        if _APP is None:
            _APP = creer_app_depuis_environnement()
        return _APP
    raise AttributeError(nom)
