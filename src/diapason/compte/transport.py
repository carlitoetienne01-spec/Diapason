"""La seule porte par laquelle le compte parle au serveur de comptes.

Conception : ``docs/development/compte-chiffre.md`` §3.12 (``local_only``),
§3.4 (conventions du VPS) et §3.7 (sessions).

``local_only`` est vrai par défaut et ``assert_may_leave`` refuse tout
(``core/local_mode.py``). Le compte obtient une TROISIÈME frontière étroite,
sur le modèle de ``mesh/transport.assert_may_reach_device`` :
:func:`assert_may_reach_account_server`. Quatre conditions, toutes
nécessaires (§3.12) :

1. **l'origine est une constante du code**, :data:`SERVEUR_COMPTES` — une
   surcharge par ``DIAPASON_SERVEUR_COMPTES`` n'est PAS exemptée ;
2. **le compte s'active par un geste explicite** (inscription, connexion,
   récupération, réinitialisation), depuis un écran qui nomme la
   destination ;
3. **la synchronisation ne transporte que des** :class:`EnveloppeChiffree` ;
4. **sans compte, rien ne part.**

Ce module est le seul du paquet ``compte`` qui ouvre une connexion. Il ne
journalise ni corps, ni jeton, ni réponse : seulement la méthode, le chemin
et le statut.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from diapason.compte.cles import ErreurCompte, b64url, entier
from diapason.compte.enveloppe import (
    FORMAT_DPE1,
    SURCOUT,
    TYPE_OBJET,
    TYPE_PIECE,
    EnveloppeIllisible,
    lire_en_tete,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SERVEUR_COMPTES",
    "PREFIXE_API",
    "VARIABLE_SURCHARGE",
    "ClairRefuse",
    "CompteInactif",
    "EnveloppeChiffree",
    "ErreurServeur",
    "ReponseServeur",
    "ServeurInjoignable",
    "SortieRefusee",
    "Transport",
    "assert_may_reach_account_server",
    "client_http_par_defaut",
    "construire_client_http",
    "origine_configuree",
]

# D3 n'est PAS tranchée (24/09/2026) : qui héberge le serveur de comptes
# reste à décider par Carlito. Cette origine est celle du VPS actuel, qu'on
# partage avec la production de Flashprime ; elle PEUT CHANGER avant toute
# publication. La changer demande une nouvelle version de l'app (§3.12,
# condition 1), et le runbook de publication le dit — c'est ce qui empêche
# une variable d'environnement, ou un fichier de configuration écrit par
# n'importe quel programme de la session, de faire partir l'adresse et
# ``authKey`` ailleurs sous ``local_only``.
SERVEUR_COMPTES = "https://diapason.flashprime.online"
PREFIXE_API = "/api/v1"
VARIABLE_SURCHARGE = "DIAPASON_SERVEUR_COMPTES"

# 15 s : Argon2id ne tourne PAS au VPS (§2.3), aucune route ne calcule plus
# qu'un HMAC et un AES-GCM ; au-delà, c'est le réseau qui est mort. Les
# routes locales sont des ``def`` dans le pool de 40 fils de Starlette :
# un délai de 60 s bloquerait un fil par clic de la personne qui insiste.
_DELAI_S = 15.0

# Un 429 de nginx n'a pas de corps JSON ni de ``retryAfterS`` : on attend
# 60 s (§3.9), la fenêtre de la zone ``diapason_compte`` (10 r/min).
_ATTENTE_429_SANS_CORPS_S = 60

# Les seuls chemins que la porte générique :meth:`Transport.requete` laisse
# passer : ceux d'identité et de coffre que ``client.py`` appelle, comparés
# À L'IDENTIQUE. Les routes de données (``/sync/*``, ``/pieces/*``) passent
# par les méthodes typées, qui exigent des :class:`EnveloppeChiffree`.
#
# 24/09/2026 : c'était une liste NOIRE de préfixes (``/sync/``,
# ``/pieces/``). ``/./sync/push``, ``/account/../sync/push``,
# ``/sync%2Fpush``, ``//sync/push`` et ``/SYNC/push`` la passaient, et httpx
# normalisait les deux premiers en ``/api/v1/sync/push`` : la condition 3
# (« rien que des enveloppes chiffrées ») se contournait avec un corps en
# clair. Une liste blanche exacte n'a rien à normaliser.
_CHEMINS_PERMIS = frozenset(
    {
        "/signup/start",
        "/signup/verify",
        "/signup/complete",
        "/login/params",
        "/login",
        "/logout",
        "/account",
        "/account/delete",
        "/sessions",
        "/sessions/current",
        "/vault/code",
        "/vault/commit",
        "/recovery/unwrap",
        "/reset/request",
        "/reset/confirm",
        "/reset/cancel",
        "/reset/complete",
    }
)


# ----------------------------------------------------------------------
# Erreurs
# ----------------------------------------------------------------------


class SortieRefusee(ErreurCompte):
    """``local_only`` refuse cette destination (§3.12, condition 1)."""

    code = "localOnly"
    # Même attribut que ``LocalOnlyError`` : l'appelant peut dire « rien
    # n'est parti » plutôt qu'« erreur réseau ».
    nothing_left_the_machine = True


class CompteInactif(ErreurCompte):
    """Aucun compte ni aucun geste explicite : rien ne part (conditions 2 et 4)."""

    code = "notConnected"
    nothing_left_the_machine = True


class ClairRefuse(ErreurCompte):
    """Autre chose qu'une :class:`EnveloppeChiffree` vers une route de
    données (condition 3)."""

    code = "plaintextRefused"
    nothing_left_the_machine = True


class ServeurInjoignable(ErreurCompte):
    """Réseau coupé, délai dépassé, TLS refusé, redirection."""

    code = "serverUnreachable"


class ErreurServeur(ErreurCompte):
    """Le serveur a répondu par un refus ``{"error":{"code":…}}``.

    ``statut`` est celui du VPS. Il ne doit JAMAIS remonter tel quel au
    bundle quand il vaut 401 : ``apiFetch`` rejoue les 401 en rafraîchissant
    la clé d'API locale (``api.ts:191-201``), et la personne verrait
    l'interface boucler au lieu de lire « session expirée » (§3.7).
    """

    code = "serverError"

    def __init__(
        self, statut: int, code: str, *, retry_after_s: int | None = None
    ) -> None:
        super().__init__(f"le serveur de comptes a répondu {statut} {code}", code=code)
        self.statut = statut
        self.retry_after_s = retry_after_s


# ----------------------------------------------------------------------
# La frontière (§3.12)
# ----------------------------------------------------------------------


def _origine(url: str) -> str:
    """``https://hote[:port]`` en minuscules, sans chemin — ou ``""``."""
    try:
        morceaux = urlsplit(url)
        port = morceaux.port
    except ValueError:
        return ""
    if not morceaux.scheme or not morceaux.hostname:
        return ""
    origine = f"{morceaux.scheme.lower()}://{morceaux.hostname.lower()}"
    if port is not None:
        origine += f":{port}"
    return origine


def origine_configuree() -> str:
    """L'origine que ce processus viserait : la surcharge si elle est posée,
    sinon la constante.

    La surcharge existe pour pointer un serveur de développement ; elle ne
    sert QUE si ``local_only`` est coupé — :func:`assert_may_reach_account_server`
    la refuse sinon.
    """
    surcharge = (os.environ.get(VARIABLE_SURCHARGE) or "").strip()
    return surcharge.rstrip("/") if surcharge else SERVEUR_COMPTES


def assert_may_reach_account_server(
    url: str, *, actif: bool, config: Any = None
) -> None:
    """Lève si ``url`` ne peut pas être jointe pour le compte. Appelée par
    :class:`Transport` AVANT de lire le jeton de session et avant de
    construire le corps de la requête.

    - ``actif`` faux : :class:`CompteInactif`, que ``local_only`` soit
      coupé ou non — « sans compte, rien ne part » n'est pas une règle du
      verrou local mais du compte (§3.12, condition 4) ;
    - ``local_only`` actif : seule l'origine CONSTANTE passe, en HTTPS. Une
      origine surchargée, même égale à la constante écrite autrement, est
      comparée après normalisation ; toute autre est refusée ;
    - ``local_only`` coupé : HTTPS, ou la boucle locale (un serveur de
      développement).
    """
    from diapason.core import local_mode

    if not actif:
        raise CompteInactif(
            "aucun compte n'est activé sur cet appareil : rien n'a été envoyé"
        )
    origine = _origine(url)
    if local_mode.local_only(config):
        if origine != SERVEUR_COMPTES:
            logger.info(
                "compte : sortie refusée sous local_only — rien n'a quitté la machine"
            )
            raise SortieRefusee(
                "le mode local est actif : seul le serveur de comptes fixé dans "
                "cette version de Diapason peut être joint"
            )
        return
    if origine.startswith("https://"):
        return
    if origine and local_mode.host_is_local(url):
        return
    raise SortieRefusee("le serveur de comptes doit être joint en HTTPS")


# ----------------------------------------------------------------------
# Enveloppes chiffrées (condition 3)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EnveloppeChiffree:
    """Un blob DPE1 d'objet (01) ou de pièce (02), et rien d'autre.

    Le type existe pour que la condition 3 soit vérifiable par le TYPE, pas
    par une promesse : :meth:`Transport.pousser_objets` et
    :meth:`Transport.deposer_piece` refusent tout ce qui n'en est pas une.
    La construction vérifie l'en-tête et la taille minimale : un JSON en
    clair, même enveloppé dans cette classe, n'a pas l'octet ``0x01`` en
    tête suivi d'un type de données.
    """

    octets: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.octets, bytes):
            raise ClairRefuse("une enveloppe chiffrée est une suite d'octets")
        try:
            en_tete = lire_en_tete(self.octets)
        except EnveloppeIllisible as exc:
            raise ClairRefuse("ce ne sont pas des octets DPE1") from exc
        if en_tete.format != FORMAT_DPE1 or en_tete.type not in (
            TYPE_OBJET,
            TYPE_PIECE,
        ):
            raise ClairRefuse("seuls les types 01 (objet) et 02 (pièce) voyagent")
        if len(self.octets) < SURCOUT + 4:
            raise ClairRefuse("enveloppe tronquée")


def _exiger_enveloppe(valeur: object) -> EnveloppeChiffree:
    # ``type(...) is`` et non ``isinstance`` : une sous-classe pourrait
    # redéfinir ``__post_init__`` et laisser passer n'importe quoi.
    if type(valeur) is not EnveloppeChiffree:
        raise ClairRefuse(
            f"refus d'envoyer un {type(valeur).__name__} : "
            "seules des enveloppes chiffrées partent vers le serveur"
        )
    return valeur


# ----------------------------------------------------------------------
# Le transport
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReponseServeur:
    statut: int
    corps: dict[str, Any]
    date: str | None


def construire_client_http() -> Any:
    """Le client de production, tel quel — construit sans rien joindre.

    - **sans suivi de redirection** : une redirection mènerait ailleurs que
      l'origine que la frontière vient de vérifier, et un 307 y renverrait
      le corps (``authKey``) ;
    - **sans rien lire de l'environnement** (``trust_env=False``). Le
      24/09/2026, une contre-épreuve a montré qu'avec le défaut d'httpx,
      ``HTTPS_PROXY`` faisait passer la requête par un proxy local (qui
      recevait ``CONNECT diapason.flashprime.online:443``) et que
      ``SSL_CERT_FILE`` choisissait le magasin de certificats : les deux
      ensemble, posés par n'importe quel programme de la session,
      interceptaient l'adresse, ``authKey``, les codes et le jeton — alors
      que ``DIAPASON_SERVEUR_COMPTES`` est, elle, refusée sous
      ``local_only``. ``.netrc`` et ``NO_PROXY`` tombent avec. Les
      certificats viennent alors de ``certifi``, versionné avec l'app.
    """
    import httpx

    return httpx.Client(timeout=_DELAI_S, follow_redirects=False, trust_env=False)


def client_http_par_defaut() -> Any:
    """Ce que :class:`Transport` construit au premier appel.

    Fonction de module, et non ligne enfouie dans ``Transport`` : la fixture
    ``_isoler_le_compte`` la remplace par un refus, si bien qu'un test qui
    oublierait d'injecter son ``MockTransport`` échoue au lieu de joindre le
    vrai serveur de comptes. :func:`construire_client_http`, elle, reste
    appelable par le test qui vérifie la configuration de production.
    """
    return construire_client_http()


class Transport:
    """Un ``httpx.Client`` vers le serveur de comptes, derrière la frontière.

    ``client_http`` est injectable : les tests passent un
    ``httpx.Client(transport=httpx.MockTransport(...))`` relié au service
    ``diapason_comptes`` en mémoire, sans aucun envoi réseau réel. En
    production, un client est construit au premier appel, sans suivi de
    redirection — une redirection mènerait ailleurs que l'origine vérifiée.
    """

    def __init__(
        self,
        *,
        actif: Callable[[], bool],
        client_http: Any = None,
        origine: str | None = None,
        config: Any = None,
    ) -> None:
        self._actif = actif
        self._client = client_http
        self._origine = (origine or origine_configuree()).rstrip("/")
        self._config = config

    @property
    def origine(self) -> str:
        return self._origine

    def _http(self) -> Any:
        if self._client is None:
            self._client = client_http_par_defaut()
        return self._client

    def origine_permise(self) -> bool:
        """L'origine configurée passerait-elle la frontière, un compte actif ?

        Sans réseau. Le 24/09/2026, ``/status`` annonçait ``serverOrigin`` =
        la surcharge ``DIAPASON_SERVEUR_COMPTES`` alors que ``local_only``
        la refuserait : l'écran d'activation aurait nommé une destination
        jamais jointe, puis affiché « mode local ». Il peut maintenant dire
        le refus AVANT le geste.
        """
        try:
            assert_may_reach_account_server(
                self._origine + PREFIXE_API, actif=True, config=self._config
            )
        except SortieRefusee:
            return False
        return True

    def fermer(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - la fermeture ne doit rien casser
                pass

    # --- Requêtes ------------------------------------------------------

    def requete(
        self,
        methode: str,
        chemin: str,
        *,
        corps: dict[str, Any] | None = None,
        jeton: Callable[[], str | None] | None = None,
    ) -> ReponseServeur:
        """Une requête JSON d'identité ou de coffre, vers un chemin de
        :data:`_CHEMINS_PERMIS` exactement. Les routes de données
        (``/sync/*``, ``/pieces/*``) passent par les méthodes typées."""
        if chemin not in _CHEMINS_PERMIS:
            raise ClairRefuse(
                "la porte générique ne joint que les routes d'identité et de "
                "coffre ; les données passent par pousser_objets et "
                "deposer_piece"
            )
        return self._envoyer(methode, chemin, json_=corps, jeton=jeton)

    def pousser_objets(
        self,
        *,
        incarnation: int,
        key_epoch: int,
        elements: Sequence[tuple[str, int, EnveloppeChiffree]],
        jeton: Callable[[], str | None],
    ) -> ReponseServeur:
        """``POST /sync/push`` — chaque blob DOIT être une :class:`EnveloppeChiffree`.

        La vérification précède la frontière et la lecture du jeton : un
        clair est refusé sans qu'un octet ne parte.
        """
        items = []
        for object_id, base_rev, blob in elements:
            enveloppe = _exiger_enveloppe(blob)
            if lire_en_tete(enveloppe.octets).type != TYPE_OBJET:
                raise ClairRefuse("une poussée ne transporte que des objets (type 01)")
            items.append(
                {
                    "objectId": str(object_id),
                    "baseRev": entier(base_rev, "baseRev"),
                    "blob": b64url(enveloppe.octets),
                }
            )
        corps = {
            "incarnation": entier(incarnation, "incarnation", minimum=1),
            "keyEpoch": entier(key_epoch, "keyEpoch", minimum=1),
            "items": items,
        }
        return self._envoyer("POST", "/sync/push", json_=corps, jeton=jeton)

    def deposer_piece(
        self,
        piece_id: str,
        blob: EnveloppeChiffree,
        *,
        jeton: Callable[[], str | None],
    ) -> ReponseServeur:
        """``PUT /pieces/{id}`` — en ``application/octet-stream``."""
        enveloppe = _exiger_enveloppe(blob)
        if lire_en_tete(enveloppe.octets).type != TYPE_PIECE:
            raise ClairRefuse("une pièce est une enveloppe de type 02")
        return self._envoyer(
            "PUT", f"/pieces/{piece_id}", contenu=enveloppe.octets, jeton=jeton
        )

    # --- Le cœur -------------------------------------------------------

    def _envoyer(
        self,
        methode: str,
        chemin: str,
        *,
        json_: dict[str, Any] | None = None,
        contenu: bytes | None = None,
        jeton: Callable[[], str | None] | None = None,
    ) -> ReponseServeur:
        url = self._origine + PREFIXE_API + chemin
        # AVANT le jeton et avant toute sérialisation (§4.3, étape 2 du
        # cycle) : sous local_only, un refus ne doit avoir touché aucune
        # lettre de créance.
        assert_may_reach_account_server(url, actif=self._actif(), config=self._config)
        en_tetes = {"Accept": "application/json"}
        if jeton is not None:
            valeur = jeton()
            if not valeur:
                raise ErreurServeur(401, "sessionExpired")
            en_tetes["Authorization"] = f"Bearer {valeur}"
        if contenu is not None:
            en_tetes["Content-Type"] = "application/octet-stream"
        try:
            import httpx

            reponse = self._http().request(
                methode,
                url,
                json=json_,
                content=contenu,
                headers=en_tetes,
            )
        except httpx.HTTPError as exc:
            # Le TYPE seulement : le message d'une erreur httpx peut citer
            # l'URL complète, et rien d'autre ne doit finir au journal.
            logger.warning(
                "compte : %s %s injoignable (%s)", methode, chemin, type(exc).__name__
            )
            raise ServeurInjoignable("le serveur de comptes est injoignable") from None
        logger.debug("compte : %s %s → %s", methode, chemin, reponse.status_code)
        if 300 <= reponse.status_code < 400:
            raise ServeurInjoignable("redirection refusée")
        corps = _corps_json(reponse)
        if reponse.status_code >= 400:
            raise _erreur_de(reponse.status_code, corps)
        return ReponseServeur(
            statut=reponse.status_code,
            corps=corps if isinstance(corps, dict) else {},
            date=reponse.headers.get("date"),
        )


def _corps_json(reponse: Any) -> Any:
    if not reponse.content:
        return {}
    try:
        return reponse.json()
    except ValueError:
        return None


def _erreur_de(statut: int, corps: Any) -> ErreurServeur:
    erreur = corps.get("error") if isinstance(corps, dict) else None
    code = erreur.get("code") if isinstance(erreur, dict) else None
    if not isinstance(code, str) or not code:
        # Un 429 de nginx, sans corps JSON (§3.9) : on attend la fenêtre.
        if statut == 429:
            return ErreurServeur(
                429, "tooManyAttempts", retry_after_s=_ATTENTE_429_SANS_CORPS_S
            )
        return ErreurServeur(statut, "serverError")
    attente = None
    if isinstance(erreur, dict):
        brut = erreur.get("retryAfterS")
        if isinstance(brut, int) and not isinstance(brut, bool) and brut > 0:
            attente = brut
    if statut == 429 and attente is None:
        attente = _ATTENTE_429_SANS_CORPS_S
    return ErreurServeur(statut, code, retry_after_s=attente)
