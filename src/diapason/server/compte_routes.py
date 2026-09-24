"""Routes locales du compte : ``/v1/account/*`` (§3.8).

Conception : ``docs/development/compte-chiffre.md`` §3.8 et §3.11.

Montées sur l'app de boucle locale, à côté des conversations, derrière la
clé locale — JAMAIS sur la sous-app ``lan`` (``mesh/routes.py``,
``files_routes.py``) : ``_PORTES_LAN`` ne change pas. Toutes les routes
sont des ``def`` synchrones : Argon2id (0,5 s) et l'appel au serveur de
comptes bloquent, et ce qu'une route ``async`` fait en ligne gèle la boucle
d'événements — le WebSocket vocal, le flux du chat, la cloche
d'approbation (CLAUDE.md §5). Seule la lecture du corps, qui n'attend que
le réseau local, est ``async``.

**Jamais de 401.** Un compte verrouillé rend 423 ``accountLocked`` ; une
session perdue, 409 ``sessionExpired``. ``apiFetch`` rejoue tout 401 en
rafraîchissant la clé d'API locale (``api.ts:191-201``) : un 401 venu du
serveur de comptes aurait fait boucler l'interface sur une clé qui était
bonne. :func:`_statut_de` le garantit pour toute erreur, y compris un code
qu'on n'aurait pas prévu.

Les corps sont validés à la main et aucun refus ne renvoie la valeur reçue :
un mot de passe mal typé ne doit pas revenir en écho dans un 422, ni dans
un journal.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.responses import Response

if TYPE_CHECKING:  # pragma: no cover - typage seulement
    from diapason.compte.service import ServiceCompte

logger = logging.getLogger(__name__)

# Le plus gros corps légitime est un mot de passe de 1 024 caractères (D5)
# en UTF-8, soit 4 Kio, deux fois dans ``/password``. 64 Kio, comme ce que
# nginx laisse passer vers ``/api/`` du VPS (§3.9) : de quoi ne jamais
# gêner, sans laisser un programme local pousser un corps de 100 Mo dans
# ``json.loads``.
_CORPS_MAX_OCTETS = 64 * 1024

# Le statut HTTP de chaque code d'erreur. Tout code absent vaut 409 : un
# état qui ne permet pas l'action, jamais une faute d'authentification.
_STATUTS: dict[str, int] = {
    "accountLocked": 423,
    "tooManyAttempts": 429,
    "invalidPassword": 403,
    "invalidCredentials": 403,
    "invalidProof": 403,
    "recoveryExcerptMismatch": 403,
    "invalidCode": 400,
    "invalidToken": 400,
    "invalidRequest": 422,
    "emailInvalid": 422,
    "passwordRejected": 422,
    "passwordTooShort": 422,
    "passwordTooLong": 422,
    "passwordContainsEmail": 422,
    "recoveryKeyInvalid": 422,
    "mailUnavailable": 503,
    "signupClosed": 503,
    # 24/09/2026 : les comptes ne sont pas encore ouverts côté appareil
    # (service.COMPTES_OUVERTS) — même statut que la fermeture du serveur.
    "accountsNotOpen": 503,
    "serverUnreachable": 503,
    "serverBusy": 503,
    "serverFull": 507,
    "quotaExceeded": 507,
    "serverError": 502,
    "serverRejected": 502,
}


def _statut_de(code: str) -> int:
    statut = _STATUTS.get(code, 409)
    # Ceinture : aucune table, aucun code futur ne fera sortir un 401 d'ici.
    return 409 if statut == 401 else statut


def _reponse_erreur(exc: Exception) -> JSONResponse:
    from diapason.compte.transport import ErreurServeur

    code = getattr(exc, "code", "accountError")
    if isinstance(exc, ErreurServeur) and code == "invalidRequest":
        # Le serveur de comptes a refusé la FORME de ce que ce client a
        # envoyé : c'est une faute de ce client, pas de la personne. Un
        # 422 lui aurait fait chercher une erreur de saisie qui n'existe pas.
        code = "serverRejected"
    erreur: dict[str, Any] = {"code": code}
    en_tetes: dict[str, str] = {}
    champ = getattr(exc, "champ", None)
    if isinstance(champ, str):
        erreur["field"] = champ
    raison = getattr(exc, "raison", None)
    if isinstance(raison, str):
        erreur["reason"] = raison
    attente = getattr(exc, "retry_after_s", None)
    if isinstance(attente, int) and attente > 0:
        erreur["retryAfterS"] = attente
        en_tetes["Retry-After"] = str(attente)
    return JSONResponse(
        {"error": erreur}, status_code=_statut_de(code), headers=en_tetes
    )


class _RouteCompte(APIRoute):
    """Traduit toute ``ErreurCompte`` — levée par la route OU par la lecture
    du corps — en ``{"error": {"code": …}}``. Le code seul, jamais le
    message : il peut citer un chemin ou une valeur."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def gestionnaire(request: Request) -> Response:
            from diapason.compte.cles import ErreurCompte

            try:
                return await original(request)
            except ErreurCompte as exc:
                logger.info(
                    "compte : %s %s refusé (%s)",
                    request.method,
                    request.url.path,
                    exc.code,
                )
                return _reponse_erreur(exc)
            except UnicodeError:
                # Ceinture derrière ``_corps`` : une chaîne qui ne s'écrit pas
                # en UTF-8 (un substitut isolé dans un paramètre de chemin)
                # rendait 500, hors du contrat « le code seul ». Le message
                # d'une UnicodeError cite le caractère : il n'est pas repris.
                logger.info(
                    "compte : %s %s refusé (invalidRequest, texte illisible)",
                    request.method,
                    request.url.path,
                )
                return JSONResponse(
                    {"error": {"code": "invalidRequest"}}, status_code=422
                )

        return gestionnaire


async def _corps(request: Request) -> dict[str, Any]:
    """Le corps JSON, borné. Vide = ``{}``. Jamais d'écho de la valeur."""
    from diapason.compte.service import RequeteInvalide

    brut = b""
    async for morceau in request.stream():
        brut += morceau
        if len(brut) > _CORPS_MAX_OCTETS:
            raise RequeteInvalide("body")
    if not brut.strip():
        return {}
    try:
        corps = json.loads(brut)
    except (ValueError, UnicodeDecodeError, RecursionError):
        # RecursionError : 64 Kio de « [ » suffisent à la lever dans
        # ``json.loads`` (24/09/2026), et elle sortait en 500.
        raise RequeteInvalide("body") from None
    if not isinstance(corps, dict) or not _texte_encodable(corps):
        raise RequeteInvalide("body")
    return corps


def _texte_encodable(valeur: Any) -> bool:
    """Toute chaîne du corps, clés comprises, s'écrit en UTF-8 strict.

    24/09/2026 : ``json.loads`` accepte ``"\\ud800"`` — un substitut isolé
    — et rend une chaîne que ni la normalisation de l'adresse ni l'encodage
    du mot de passe ne savent écrire. La UnicodeEncodeError, qui n'est pas
    une ``ErreurCompte``, sortait en 500 de ``/login``, ``/unlock`` et
    ``/signup/start``. Refusée ici, elle devient un 422 sans écho."""
    if isinstance(valeur, str):
        try:
            valeur.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(valeur, dict):
        return all(
            _texte_encodable(k) and _texte_encodable(v) for k, v in valeur.items()
        )
    if isinstance(valeur, list):
        return all(_texte_encodable(v) for v in valeur)
    return True


class AccesCompte:
    """Le service, construit au premier appel et une seule fois.

    ``create_app`` tourne des centaines de fois par suite de tests ; ne
    rien construire avant la première requête garde ``compte/`` et le
    trousseau hors de tout test qui ne touche pas au compte — et évite de
    charger ``cryptography`` pour qui n'a jamais ouvert l'écran du compte.
    """

    def __init__(self, fabrique: Callable[[], ServiceCompte] | None = None) -> None:
        self._fabrique = fabrique
        self._service: ServiceCompte | None = None
        self._verrou = threading.Lock()

    def __call__(self) -> ServiceCompte:
        with self._verrou:
            if self._service is None:
                if self._fabrique is not None:
                    self._service = self._fabrique()
                else:
                    from diapason.compte.service import ServiceCompte

                    self._service = ServiceCompte()
            return self._service

    def fermer(self) -> None:
        with self._verrou:
            service, self._service = self._service, None
        if service is not None:
            service.fermer()


def _champ(corps: dict[str, Any], nom: str, *, defaut: Any = ...) -> Any:
    from diapason.compte.service import RequeteInvalide

    if nom not in corps:
        if defaut is ...:
            raise RequeteInvalide(nom)
        return defaut
    return corps[nom]


def create_compte_router(acces: AccesCompte) -> APIRouter:
    router = APIRouter(prefix="/v1/account", tags=["account"], route_class=_RouteCompte)

    def _avec_statut(extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**(extra or {}), "status": acces().statut()}

    # --- État ----------------------------------------------------------

    @router.get("/status")
    def status() -> dict[str, Any]:
        return acces().statut()

    # --- P1 : inscription ----------------------------------------------

    @router.post("/signup/start")
    def signup_start(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().inscription_debut(
            _champ(corps, "email"), _champ(corps, "termsAccepted")
        )
        return _avec_statut()

    @router.post("/signup/verify")
    def signup_verify(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().inscription_code(_champ(corps, "code"))
        return _avec_statut()

    @router.post("/signup/prepare")
    def signup_prepare(corps: dict = Depends(_corps)) -> dict[str, Any]:
        rendu = acces().inscription_preparer(
            _champ(corps, "password"), _champ(corps, "remember", defaut=False)
        )
        return _avec_statut(rendu)

    @router.post("/signup/complete")
    def signup_complete(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().inscription_terminer(
            _champ(corps, "recoveryExcerpt", defaut=None),
            _champ(corps, "skipRecovery", defaut=None),
        )
        return _avec_statut()

    # --- P3 : connexion, déverrouillage --------------------------------

    @router.post("/login")
    def login(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().connecter(
            _champ(corps, "email"),
            _champ(corps, "password"),
            _champ(corps, "remember", defaut=False),
        )
        return _avec_statut()

    @router.post("/unlock")
    def unlock(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().deverrouiller(
            _champ(corps, "password"), _champ(corps, "remember", defaut=False)
        )
        return _avec_statut()

    @router.post("/lock")
    def lock(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().verrouiller()
        return _avec_statut()

    # --- P5, P4 ---------------------------------------------------------

    @router.post("/password")
    def password(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().changer_mot_de_passe(
            _champ(corps, "currentPassword"), _champ(corps, "newPassword")
        )
        return _avec_statut()

    @router.post("/password/forgotten-here/code")
    def forgotten_here_code(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().code_oubli_ici()
        return _avec_statut()

    @router.post("/password/forgotten-here")
    def forgotten_here(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().oubli_ici(_champ(corps, "code"), _champ(corps, "newPassword"))
        return _avec_statut()

    @router.post("/recover")
    def recover(corps: dict = Depends(_corps)) -> dict[str, Any]:
        rendu = acces().recuperer(
            _champ(corps, "email"),
            _champ(corps, "recoveryKey"),
            _champ(corps, "newPassword"),
            _champ(corps, "remember", defaut=False),
            _champ(corps, "keepRecoveryKey", defaut=False),
        )
        return _avec_statut(rendu)

    # --- Clé de récupération -------------------------------------------

    @router.post("/recovery-key")
    def recovery_key(corps: dict = Depends(_corps)) -> dict[str, Any]:
        return _avec_statut(acces().nouvelle_cle_preparer(_champ(corps, "password")))

    @router.post("/recovery-key/confirm")
    def recovery_key_confirm(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().nouvelle_cle_confirmer(_champ(corps, "recoveryExcerpt"))
        return _avec_statut()

    @router.post("/recovery-key/remove")
    def recovery_key_remove(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().retirer_cle(_champ(corps, "password"))
        return _avec_statut()

    # --- Réinitialisation ----------------------------------------------

    @router.post("/reset/request")
    def reset_request(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().reinit_demander(_champ(corps, "email"))
        return _avec_statut()

    @router.post("/reset/confirm")
    def reset_confirm(corps: dict = Depends(_corps)) -> dict[str, Any]:
        rendu = acces().reinit_confirmer(_champ(corps, "email"), _champ(corps, "code"))
        return _avec_statut(rendu)

    @router.post("/reset/cancel")
    def reset_cancel(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().reinit_annuler()
        return _avec_statut()

    @router.post("/reset/complete")
    def reset_complete(corps: dict = Depends(_corps)) -> dict[str, Any]:
        rendu = acces().reinit_terminer(
            _champ(corps, "email"),
            _champ(corps, "code"),
            _champ(corps, "newPassword"),
            _champ(corps, "remember", defaut=False),
        )
        return _avec_statut(rendu)

    # --- P6 : appareils ------------------------------------------------

    @router.get("/devices")
    def devices() -> dict[str, Any]:
        return {"devices": acces().appareils()}

    @router.post("/devices/{session_id}/disconnect")
    def device_disconnect(
        session_id: str, corps: dict = Depends(_corps)
    ) -> dict[str, Any]:
        acces().deconnecter_appareil(session_id, _champ(corps, "password"))
        return _avec_statut()

    # --- P7, P8 ---------------------------------------------------------

    @router.post("/logout")
    def logout(corps: dict = Depends(_corps)) -> dict[str, Any]:
        rendu = acces().deconnecter(_champ(corps, "eraseLocalData", defaut=False))
        return _avec_statut(rendu)

    @router.post("/delete")
    def delete(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().supprimer(
            _champ(corps, "password"), _champ(corps, "eraseLocalData", defaut=False)
        )
        return _avec_statut()

    # --- Synchronisation, premier lancement ----------------------------

    @router.post("/sync/consent")
    def sync_consent(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().consentir()
        return _avec_statut()

    @router.post("/sync-now")
    def sync_now(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().synchroniser_maintenant()
        return _avec_statut()

    @router.post("/onboarding/done")
    def onboarding_done(corps: dict = Depends(_corps)) -> dict[str, Any]:
        acces().accueil_termine()
        return _avec_statut()

    return router
