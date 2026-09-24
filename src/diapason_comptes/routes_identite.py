"""Routes d'identité : inscription, connexion, sessions, réinitialisation,
suppression.

Conception : ``docs/development/compte-chiffre.md`` §3.4 à §3.7.

Toutes sont des ``def`` SYNCHRONES : Starlette les exécute dans un fil, et
rien de ce qu'elles font (SQLite, HMAC) ne touche la boucle d'événements
(piège de CLAUDE.md §5 : une route ``async`` qui appelle du bloquant gèle
tout le service).

Énumération (§3.5) : même statut, même corps et même classe de temps pour
une adresse connue ou inconnue, sur ``signup/*``, ``login/params``,
``login``, ``recovery/unwrap`` et ``reset/*``. Chaque route ci-dessous
fait le même travail dans les deux cas : un HMAC de vérification contre un
vérificateur factice, un code enregistré ou un avis compté.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from diapason_comptes import jetons
from diapason_comptes.base import (
    JOUR_MS,
    Compte,
    compte_par_indices,
    ecriture,
    garde_depassee,
    jour,
    lire_compte,
)
from diapason_comptes.limites import FAMILLE_CONNEXION, prefixe_ip
from diapason_comptes.validation import (
    KDF_VERSION_DEFAUT,
    ErreurRequete,
    b64url,
    cle_32,
    code_six_chiffres,
    corps_json,
    courriel,
    entier,
    enveloppe_amk_mot_de_passe,
    enveloppe_amk_recuperation,
    enveloppe_nom_appareil,
    enveloppe_trousseau,
    invalide,
    jeton_bearer,
    kdf_version,
)

if TYPE_CHECKING:
    from diapason_comptes.app import Contexte

routeur = APIRouter(prefix="/api/v1")

_journal = logging.getLogger("diapason_comptes.routes")

# La version des conditions que ce service fait accepter. ``signup/start``
# refuse toute autre valeur : le compte garde celle qu'il a acceptée
# (``conditions_version``), et un client qui en affiche une plus ancienne
# doit d'abord se mettre à jour.
CONDITIONS_VERSION = 1

# D8 (décision par défaut du 24/09/2026) : 72 h, ou 7 jours si une session a
# été vue dans les 30 derniers jours. Un compte actif a un appareil qui
# affichera le bandeau et pourra annuler (§3.6) ; lui laisser une semaine
# couvre des vacances. Un compte sans appareil actif n'a personne pour
# annuler : 72 h suffisent à qui a vraiment tout perdu.
DELAI_REINITIALISATION_MS = 72 * 3_600_000
DELAI_REINITIALISATION_ACTIF_MS = 7 * JOUR_MS
FENETRE_ACTIVITE_JOURS = 30

# Pour une adresse inconnue, ``/login`` compare quand même à un vérificateur :
# celui d'un compte factice. Sans lui, un échec sur adresse inconnue
# répondait sans HMAC, donc plus vite — et le chronomètre disait qui existe.
COMPTE_FACTICE = "00000000-0000-4000-8000-000000000000"


# ----------------------------------------------------------------------
# Outils partagés avec ``routes_coffre``
# ----------------------------------------------------------------------


def contexte(request: Request) -> Contexte:
    return request.app.state.contexte


def prefixe(request: Request) -> str:
    return prefixe_ip(request.client.host if request.client else None)


def trouver_compte(
    ctx: Contexte, conn: sqlite3.Connection, adresse: str
) -> Compte | None:
    return compte_par_indices(conn, ctx.secrets.indices_courriel(adresse))


def index_pour(ctx: Contexte, compte: Compte | None, adresse: str) -> bytes:
    """L'index sous lequel ranger codes et jetons : celui du compte s'il
    existe (il peut dater d'un ancien poivre), sinon le courant."""
    return (
        compte.courriel_index
        if compte is not None
        else ctx.secrets.index_courriel(adresse)
    )


def adresse_du_compte(ctx: Contexte, compte: Compte) -> str:
    return ctx.secrets.ouvrir(compte.id, "courriel", compte.courriel_chiffre).decode(
        "utf-8"
    )


def verifier_auth(ctx: Contexte, compte: Compte | None, auth_key: bytes) -> bool:
    if compte is None:
        # Un seul HMAC, comme pour un vrai compte : le vérificateur factice
        # porte l'octet de la version courante et ne correspond à rien.
        ctx.secrets.verifier_mac(
            bytes([ctx.secrets.version]) + bytes(32),
            b"auth",
            COMPTE_FACTICE.encode("ascii") + auth_key,
        )
        return False
    return ctx.secrets.verifier_mac(
        compte.verif_auth, b"auth", compte.id.encode("ascii") + auth_key
    )


def session_requise(
    ctx: Contexte, conn: sqlite3.Connection, request: Request, maintenant: int
) -> jetons.Session:
    try:
        return jetons.authentifier(conn, jeton_bearer(request), maintenant)
    except jetons.SessionRefusee as refus:
        raise ErreurRequete(401, refus.code) from None


def attendre(
    ctx: Contexte, conn, adresse: str, pref: str, maintenant: int, famille: bytes
) -> None:
    """Lève 429 si l'adresse, le préfixe ou l'IP doivent attendre."""
    attente = max(
        ctx.limiteur.attente_s(conn, adresse, pref, maintenant, famille),
        ctx.limiteur_ip.attente_s(pref, maintenant),
    )
    if attente:
        raise ErreurRequete(429, "tooManyAttempts", retry_after_s=attente)


def echec_compte(
    ctx: Contexte,
    conn,
    adresse: str,
    index: bytes,
    pref: str,
    maintenant: int,
    famille: bytes,
    *,
    compte: Compte | None,
):
    """Compte un échec ; rend l'avis « connexions bloquées » s'il est dû.

    L'avis n'est RÉEL que pour un compte, et pour les connexions : il dit
    « votre compte Diapason » et « les nouvelles connexions sont
    bloquées ». Jusqu'au 24/09/2026, cent échecs sur n'importe quelle
    adresse le faisaient partir vers ce tiers (§100), et un blocage de la
    récupération l'annonçait comme un blocage des connexions. Ailleurs,
    l'envoi est fantôme : compté pareil, pour que le budget ne dise pas qui
    a un compte.
    """
    ctx.limiteur_ip.echec(pref, maintenant)
    if ctx.limiteur.echec(conn, adresse, pref, maintenant, famille):
        return ctx.courrier.preparer(
            conn,
            "connexions_bloquees",
            adresse,
            index,
            maintenant,
            reel=compte is not None and famille == FAMILLE_CONNEXION,
        )
    return None


def exiger_courriel_disponible(ctx: Contexte, conn, maintenant: int) -> None:
    if not ctx.courrier.disponible(conn, maintenant):
        raise ErreurRequete(503, "mailUnavailable")


def exiger_place(ctx: Contexte) -> None:
    cfg = ctx.configuration
    if garde_depassee(
        ctx.base,
        garde_base_octets=cfg.garde_base_octets,
        garde_disque_libre_octets=cfg.garde_disque_libre_octets,
        chemin_disque=cfg.chemin_disque,
        espace_libre=ctx.espace_libre,
    ):
        raise ErreurRequete(507, "serverFull")


def recuperation_initiale(
    corps: dict[str, Any],
) -> tuple[bytes, bytes] | None:
    """``recovery: {authKey, sealedMasterKey} | null`` (signup, reset)."""
    if "recovery" not in corps:
        raise invalide("recovery")
    valeur = corps["recovery"]
    if valeur is None:
        return None
    if not isinstance(valeur, dict):
        raise invalide("recovery")
    return (
        cle_32(valeur, "authKey", chemin="recovery."),
        enveloppe_amk_recuperation(valeur, chemin="recovery."),
    )


def sceller_coffre(
    ctx: Contexte,
    compte_id: str,
    *,
    kdf: int,
    auth_key: bytes,
    amk_mdp: bytes,
    recuperation: tuple[bytes, bytes] | None,
    trousseau: bytes,
) -> dict[str, Any]:
    """Les colonnes de sécurité d'un coffre neuf, poivrées et sur-chiffrées.

    Sans ``secrets_version`` : il ne se pose qu'une fois TOUTES les colonnes
    versionnées relues (:func:`aux_secrets_courants`).
    """
    s = ctx.secrets
    return {
        "kdf_version": kdf,
        "verif_auth": s.verificateur_auth(compte_id, auth_key),
        "amk_mdp": s.sceller(compte_id, "amk_mdp", amk_mdp),
        "verif_recup": (
            None
            if recuperation is None
            else s.verificateur_recuperation(compte_id, recuperation[0])
        ),
        "amk_recup": (
            None
            if recuperation is None
            else s.sceller(compte_id, "amk_recup", recuperation[1])
        ),
        "trousseau": s.sceller(compte_id, "trousseau", trousseau),
    }


def mettre_a_jour(
    conn: sqlite3.Connection, compte_id: str, colonnes: dict[str, Any]
) -> None:
    affectations = ", ".join(f"{nom} = ?" for nom in colonnes)
    conn.execute(
        f"UPDATE comptes SET {affectations} WHERE id = ?",
        (*colonnes.values(), compte_id),
    )


def reponse_session(compte: Compte, session_id: str, jeton: str) -> dict[str, Any]:
    return {
        "accountId": compte.id,
        "sessionId": session_id,
        "sessionToken": jeton,
        "vaultVersion": compte.version_coffre,
        "keyringVersion": compte.version_trousseau,
        "keyEpoch": compte.epoque_cle,
        "incarnation": compte.incarnation,
    }


# Les colonnes qui portent en tête l'octet de la version de secret qui les a
# produites (§3.2). ``secrets_version`` en est le MINIMUM : la plus vieille
# version encore nécessaire pour lire ce compte.
COLONNES_VERSIONNEES = (
    "courriel_index",
    "courriel_chiffre",
    "sel_kdf",
    "verif_auth",
    "amk_mdp",
    "verif_recup",
    "amk_recup",
    "trousseau",
)
# Celles que le serveur sait ouvrir et re-sceller sans rien recevoir.
_COLONNES_SCELLEES = ("sel_kdf", "amk_mdp", "amk_recup", "trousseau")


def version_des_secrets(compte: Compte) -> int:
    return min(
        blob[0]
        for blob in (getattr(compte, c) for c in COLONNES_VERSIONNEES)
        if blob is not None
    )


def aux_secrets_courants(
    ctx: Contexte,
    conn,
    compte_id: str,
    adresse: str,
    auth_key: bytes | None = None,
) -> None:
    """Réécrit sous la version COURANTE des secrets ce qui peut l'être, puis
    pose ``secrets_version`` d'après ce qui est RÉELLEMENT stocké.

    §3.2 : « la rotation a lieu à la connexion suivante ». Quand on tient
    l'adresse (connexion, rotation, récupération, réinitialisation), index,
    adresse, sel, enveloppes et trousseau passent au poivre et à la clé
    courants ; le vérificateur d'authentification aussi quand on tient
    ``authKey``. Celui de récupération ne peut pas (on n'a pas
    ``recoveryAuthKey``) : il garde l'octet de sa version, reste vérifiable
    tant qu'elle est déclarée, et ``recovery/unwrap`` le réécrit.

    Jusqu'au 24/09/2026, ``vault/commit`` et ``reset/complete`` posaient
    ``secrets_version`` à la version courante sans réécrire l'index ni
    l'adresse : la connexion suivante n'y touchait plus, l'exploitant lisait
    « v2 partout » et retirait v1, et le compte ne s'ouvrait plus jamais.
    """
    s = ctx.secrets
    compte = lire_compte(conn, compte_id)
    v = s.version
    colonnes: dict[str, Any] = {}
    if compte.courriel_index[0] != v:
        colonnes["courriel_index"] = s.index_courriel(adresse)
    if compte.courriel_chiffre[0] != v:
        colonnes["courriel_chiffre"] = s.sceller(
            compte_id, "courriel", adresse.encode("utf-8")
        )
    if auth_key is not None and compte.verif_auth[0] != v:
        colonnes["verif_auth"] = s.verificateur_auth(compte_id, auth_key)
    for colonne in _COLONNES_SCELLEES:
        blob = getattr(compte, colonne)
        if blob is not None and blob[0] != v:
            colonnes[colonne] = s.sceller(
                compte_id, colonne, s.ouvrir(compte_id, colonne, blob)
            )
    version = version_des_secrets(dataclasses.replace(compte, **colonnes))
    if version != compte.secrets_version:
        colonnes["secrets_version"] = version
    if colonnes:
        mettre_a_jour(conn, compte_id, colonnes)


def tourner_secrets(
    ctx: Contexte, conn, compte: Compte, adresse: str, auth_key: bytes
) -> None:
    """À la connexion : rien à faire si tout est déjà en version courante."""
    if compte.secrets_version != ctx.secrets.version:
        aux_secrets_courants(ctx, conn, compte.id, adresse, auth_key)


def _vide(statut: int = 202) -> JSONResponse:
    return JSONResponse({}, status_code=statut)


# ----------------------------------------------------------------------
# Inscription
# ----------------------------------------------------------------------


@routeur.post("/signup/start", status_code=202)
def signup_start(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Adresse libre : un code. Adresse prise : « un compte existe déjà », au
    plus une fois par jour. Même 202 vide dans les deux cas."""
    ctx = contexte(request)
    adresse = courriel(corps)
    if entier(corps, "termsVersion", minimum=1) != CONDITIONS_VERSION:
        raise ErreurRequete(409, "termsOutdated")
    if not ctx.configuration.inscriptions_ouvertes:
        raise ErreurRequete(503, "signupClosed")
    maintenant = ctx.horloge()
    message = None
    with ctx.base.transaction() as conn:
        exiger_courriel_disponible(ctx, conn, maintenant)
        compte = trouver_compte(ctx, conn, adresse)
        index = index_pour(ctx, compte, adresse)
        code = jetons.nouveau_code()
        # Les MÊMES écritures pour une adresse connue ou inconnue (§3.5) :
        # un envoi compté comme un code, un code enregistré, la marque du
        # jour de « compte existant ». Jusqu'au 24/09/2026, le second appel
        # du jour écrivait 0 ligne pour une adresse prise et 3 pour une
        # libre, et le budget global bougeait d'un côté seulement.
        # Budget de l'adresse épuisé : l'ancien code reste le bon, et rien
        # n'est remplacé par un code que personne ne recevra.
        if ctx.courrier.compter_code(conn, adresse, maintenant):
            # Pour un compte, ce code ne part pas et ne sert à rien :
            # ``signup/verify`` refuse toute adresse déjà prise.
            jetons.enregistrer_code(
                conn, ctx.secrets, index, "inscription", code, maintenant
            )
            # La marque du jour, une ligne des deux côtés. Pour l'adresse
            # libre, sous une AUTRE clé : marquer « compte existant » pour
            # elle aurait tu, le jour même, l'avis qu'elle doit recevoir une
            # fois inscrite si quelqu'un d'autre tape son adresse.
            premier = ctx.courrier.budgets.premier_du_jour(
                conn,
                "code_inscription" if compte is None else "compte_existant",
                adresse,
                maintenant,
            )
            if compte is None:
                message = ctx.courrier.rediger(
                    "code_inscription", adresse, index, code=code
                )
            elif premier:
                message = ctx.courrier.rediger("compte_existant", adresse, index)
    ctx.courrier.deposer(message)
    return _vide()


@routeur.post("/signup/verify")
def signup_verify(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Le même 400 ``invalidCode`` pour une adresse inconnue, déjà prise ou
    un code faux. L'``accountId`` naît ici : le client en a besoin pour
    sceller son coffre (AAD ``a``) avant ``signup/complete``."""
    ctx = contexte(request)
    adresse = courriel(corps)
    code = code_six_chiffres(corps)
    pref = prefixe(request)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        attente = ctx.limiteur_ip.attente_s(pref, maintenant)
        if attente:
            raise ErreurRequete(429, "tooManyAttempts", retry_after_s=attente)
        compte = trouver_compte(ctx, conn, adresse)
        index = index_pour(ctx, compte, adresse)
        bon = jetons.consommer_code(
            conn, ctx.secrets, index, "inscription", code, maintenant
        )
        if compte is not None or not bon:
            ctx.limiteur_ip.echec(pref, maintenant)
            resultat = None
        else:
            compte_id = str(uuid.uuid4())
            resultat = {
                "signupToken": jetons.creer_jeton_inscription(
                    conn, ctx.secrets, index, compte_id, adresse, maintenant
                ),
                "accountId": compte_id,
                "kdfSalt": b64url(ctx.secrets.kdf_salt(adresse)),
            }
    # Hors de la transaction : l'essai compté doit être VALIDÉ, pas annulé
    # avec elle.
    if resultat is None:
        raise ErreurRequete(400, "invalidCode")
    return JSONResponse(resultat)


@routeur.post("/signup/complete", status_code=201)
def signup_complete(
    request: Request, corps: dict = Depends(corps_json)
) -> JSONResponse:
    """Le compte n'existe qu'à partir d'ici (§3.4, P2)."""
    ctx = contexte(request)
    jeton = corps.get("signupToken")
    if not isinstance(jeton, str):
        raise invalide("signupToken")
    kdf = kdf_version(corps)
    auth_key = cle_32(corps, "authKey")
    amk_mdp = enveloppe_amk_mot_de_passe(corps)
    recuperation = recuperation_initiale(corps)
    trousseau = enveloppe_trousseau(corps)
    exiger_place(ctx)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        consomme = jetons.consommer_jeton(conn, jeton, "inscription", maintenant)
        adresse = (
            None
            if consomme is None
            else jetons.courriel_du_jeton_inscription(ctx.secrets, consomme)
        )
        if consomme is None or adresse is None:
            raise ErreurRequete(400, "invalidToken")
        if trouver_compte(ctx, conn, adresse) is not None:
            raise ErreurRequete(409, "accountExists")
        compte_id = consomme.compte_id
        colonnes = {
            "id": compte_id,
            "courriel_index": ctx.secrets.index_courriel(adresse),
            "courriel_chiffre": ctx.secrets.sceller(
                compte_id, "courriel", adresse.encode("utf-8")
            ),
            "cree_jour": jour(maintenant),
            "conditions_version": CONDITIONS_VERSION,
            # Scellé : en clair, ce sel public (``login/params``) faisait de
            # la base volée seule un annuaire des inscrits (24/09/2026).
            "sel_kdf": ctx.secrets.sceller(
                compte_id, "sel_kdf", ctx.secrets.kdf_salt(adresse)
            ),
            "secrets_version": ctx.secrets.version,
            "version_coffre": 1,
            "version_trousseau": 1,
            "epoque_cle": 1,
            "incarnation": 1,
            "quota_octets": ctx.configuration.quota_compte_octets,
            **sceller_coffre(
                ctx,
                compte_id,
                kdf=kdf,
                auth_key=auth_key,
                amk_mdp=amk_mdp,
                recuperation=recuperation,
                trousseau=trousseau,
            ),
        }
        conn.execute(
            f"INSERT INTO comptes ({', '.join(colonnes)}) "
            f"VALUES ({', '.join('?' for _ in colonnes)})",
            tuple(colonnes.values()),
        )
        session_id, jeton_session = jetons.creer_session(conn, compte_id, maintenant)
        seq = ecriture(conn)
        compte = lire_compte(conn, compte_id)
        ctx.journal.ligne_de_securite("accountCreated", compte, maintenant, seq)
    return JSONResponse(
        reponse_session(compte, session_id, jeton_session), status_code=201
    )


# ----------------------------------------------------------------------
# Connexion
# ----------------------------------------------------------------------


@routeur.post("/login/params")
def login_params(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Le sel est déterministe et identique pour une adresse inconnue : il ne
    change ni à l'inscription, ni au changement de mot de passe (§2.2)."""
    ctx = contexte(request)
    adresse = courriel(corps)
    maintenant = ctx.horloge()
    with ctx.base.lecture() as conn:
        attendre(ctx, conn, adresse, prefixe(request), maintenant, FAMILLE_CONNEXION)
        compte = trouver_compte(ctx, conn, adresse)
    # Recalculé pour TOUS, jamais lu de ``sel_kdf`` : la graine ne tourne
    # pas, le sel est le même, et un déchiffrement pour les seuls comptes
    # serait un travail de plus que l'adresse inconnue ne fait pas.
    return JSONResponse(
        {
            "kdfVersion": KDF_VERSION_DEFAUT if compte is None else compte.kdf_version,
            "kdfSalt": b64url(ctx.secrets.kdf_salt(adresse)),
        }
    )


@routeur.post("/login")
def login(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    ctx = contexte(request)
    adresse = courriel(corps)
    auth_key = cle_32(corps, "authKey")
    pref = prefixe(request)
    maintenant = ctx.horloge()
    resultat = None
    avis = None
    with ctx.base.transaction() as conn:
        attendre(ctx, conn, adresse, pref, maintenant, FAMILLE_CONNEXION)
        compte = trouver_compte(ctx, conn, adresse)
        index = index_pour(ctx, compte, adresse)
        if not verifier_auth(ctx, compte, auth_key):
            avis = echec_compte(
                ctx,
                conn,
                adresse,
                index,
                pref,
                maintenant,
                FAMILLE_CONNEXION,
                compte=compte,
            )
        else:
            ctx.limiteur.reussite(conn, adresse, pref, FAMILLE_CONNEXION)
            jetons.purger_sessions_expirees(conn, compte.id, maintenant)
            tourner_secrets(ctx, conn, compte, adresse, auth_key)
            compte = lire_compte(conn, compte.id)
            session_id, jeton = jetons.creer_session(conn, compte.id, maintenant)
            jetons.borner_sessions(conn, compte.id)
            ecriture(conn)
            # D8 : un courriel à CHAQUE nouvelle connexion, sans IP ni lieu.
            avis = ctx.courrier.preparer(
                conn, "nouvelle_connexion", adresse, compte.courriel_index, maintenant
            )
            resultat = {
                **reponse_session(compte, session_id, jeton),
                "kdfVersion": compte.kdf_version,
                "wrappedMasterKey": b64url(
                    ctx.secrets.ouvrir(compte.id, "amk_mdp", compte.amk_mdp)
                ),
                "keyring": b64url(
                    ctx.secrets.ouvrir(compte.id, "trousseau", compte.trousseau)
                ),
                "recoveryConfigured": compte.verif_recup is not None,
                "pendingResetAt": compte.reinitialisation_attendue,
            }
    ctx.courrier.deposer(avis)
    if resultat is None:
        raise ErreurRequete(401, "invalidCredentials")
    return JSONResponse(resultat)


@routeur.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    ctx = contexte(request)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
        seq = ecriture(conn)
        ctx.journal.revocations(
            session.compte_id, [session.jeton_hash], maintenant, seq
        )
    return Response(status_code=204)


# ----------------------------------------------------------------------
# Compte et sessions
# ----------------------------------------------------------------------


@routeur.get("/account")
def account(request: Request) -> JSONResponse:
    """Ne rend JAMAIS d'enveloppe : une session seule ne donne pas l'AMK
    (§3.7) ; il faut ``authKey`` (``/login``) ou la récupération."""
    ctx = contexte(request)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        compte = lire_compte(conn, session.compte_id)
    return JSONResponse(
        {
            "accountId": compte.id,
            "email": adresse_du_compte(ctx, compte),
            "createdDay": compte.cree_jour,
            "usedBytes": compte.octets,
            "quotaBytes": compte.quota_octets,
            "vaultVersion": compte.version_coffre,
            "keyringVersion": compte.version_trousseau,
            "keyEpoch": compte.epoque_cle,
            "incarnation": compte.incarnation,
            "recoveryConfigured": compte.verif_recup is not None,
            "pendingResetAt": compte.reinitialisation_attendue,
        }
    )


@routeur.put("/sessions/current", status_code=204)
def sessions_current(request: Request, corps: dict = Depends(corps_json)) -> Response:
    ctx = contexte(request)
    nom = enveloppe_nom_appareil(corps)
    exiger_place(ctx)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        conn.execute(
            "UPDATE sessions SET nom_chiffre = ? WHERE id = ?", (nom, session.id)
        )
    return Response(status_code=204)


@routeur.get("/sessions")
def sessions(request: Request) -> JSONResponse:
    """La révocation d'une AUTRE session ne passe que par ``vault/commit``
    (§3.4) : ici, on ne fait que lister."""
    ctx = contexte(request)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        lignes = conn.execute(
            "SELECT id, nom_chiffre, cree_jour, vu_jour FROM sessions "
            "WHERE compte_id = ? ORDER BY cree_jour, id",
            (session.compte_id,),
        ).fetchall()
    return JSONResponse(
        {
            "sessions": [
                {
                    "sessionId": id_,
                    "encryptedName": None if nom is None else b64url(nom),
                    "createdDay": cree,
                    "lastSeenDay": vu,
                    "current": id_ == session.id,
                }
                for id_, nom, cree, vu in lignes
            ]
        }
    )


@routeur.post("/account/delete", status_code=204)
def account_delete(request: Request, corps: dict = Depends(corps_json)) -> Response:
    """Bearer ET ``authKey`` : un jeton volé ne supprime pas le compte (A9)."""
    ctx = contexte(request)
    auth_key = cle_32(corps, "authKey")
    pref = prefixe(request)
    maintenant = ctx.horloge()
    avis = None
    supprime = False
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        compte = lire_compte(conn, session.compte_id)
        adresse = adresse_du_compte(ctx, compte)
        attendre(ctx, conn, adresse, pref, maintenant, FAMILLE_CONNEXION)
        if not verifier_auth(ctx, compte, auth_key):
            avis = echec_compte(
                ctx,
                conn,
                adresse,
                compte.courriel_index,
                pref,
                maintenant,
                FAMILLE_CONNEXION,
                compte=compte,
            )
        else:
            avis = ctx.courrier.preparer(
                conn, "compte_supprime", adresse, compte.courriel_index, maintenant
            )
            conn.execute("DELETE FROM comptes WHERE id = ?", (compte.id,))
            conn.execute(
                "DELETE FROM codes WHERE courriel_index = ?", (compte.courriel_index,)
            )
            conn.execute(
                "DELETE FROM jetons_temporaires "
                "WHERE compte_id = ? OR courriel_index = ?",
                (compte.id, compte.courriel_index),
            )
            seq = ecriture(conn)
            ctx.journal.suppression(compte, maintenant, seq)
            supprime = True
    ctx.courrier.deposer(avis)
    if not supprime:
        raise ErreurRequete(403, "invalidProof")
    ctx.base.point_de_controle()
    # APRÈS le COMMIT : oublier les lignes d'un compte que la transaction
    # n'aurait finalement pas supprimé ferait perdre ses coffres au rejeu.
    try:
        ctx.journal.oublier(compte.id)
    except OSError as exc:
        # Le compte EST supprimé ; ses lignes partiront à la troncature.
        _journal.error("journal non purgé à la suppression : %s", type(exc).__name__)
    return Response(status_code=204)


# ----------------------------------------------------------------------
# Réinitialisation (§3.6) — ``reset/complete`` est dans ``routes_coffre``
# ----------------------------------------------------------------------


@routeur.post("/reset/request", status_code=202)
def reset_request(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Un code pour ``confirm`` (aucune attente en cours) ou pour
    ``complete`` (attente échue). Même 202 vide pour une adresse inconnue."""
    ctx = contexte(request)
    adresse = courriel(corps)
    maintenant = ctx.horloge()
    message = None
    with ctx.base.transaction() as conn:
        exiger_courriel_disponible(ctx, conn, maintenant)
        compte = trouver_compte(ctx, conn, adresse)
        index = index_pour(ctx, compte, adresse)
        code = jetons.nouveau_code()
        attente = None if compte is None else compte.reinitialisation_attendue
        # Pendant l'attente, un code ne servirait à rien : ni ``confirm``
        # (déjà fait) ni ``complete`` (pas encore permis).
        utile = compte is not None and (attente is None or attente <= maintenant)
        # Les MÊMES écritures dans tous les cas — un envoi compté, un code
        # enregistré — et seul le courriel diffère. Jusqu'au 24/09/2026,
        # une adresse connue écrivait 3 lignes et puisait dans le budget
        # global, une inconnue 1 ligne sans y puiser ; au second appel de la
        # minute, 0 contre 1. Le ``fsync`` du WAL et le 503 suivant disaient
        # qui a un compte (§3.5, « même classe de temps »).
        if ctx.courrier.compter_code(conn, adresse, maintenant):
            jetons.enregistrer_code(
                conn, ctx.secrets, index, "reinitialisation", code, maintenant
            )
            if utile:
                message = ctx.courrier.rediger(
                    "code_reinitialisation", adresse, index, code=code
                )
    ctx.courrier.deposer(message)
    return _vide()


@routeur.post("/reset/confirm", status_code=202)
def reset_confirm(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Fixe ``effectiveAt``. Les échecs comptent AVEC ceux de ``/login``."""
    ctx = contexte(request)
    adresse = courriel(corps)
    code = code_six_chiffres(corps)
    pref = prefixe(request)
    maintenant = ctx.horloge()
    effectif = None
    avis = None
    with ctx.base.transaction() as conn:
        attendre(ctx, conn, adresse, pref, maintenant, FAMILLE_CONNEXION)
        compte = trouver_compte(ctx, conn, adresse)
        index = index_pour(ctx, compte, adresse)
        bon = jetons.consommer_code(
            conn, ctx.secrets, index, "reinitialisation", code, maintenant
        )
        if compte is None or not bon:
            avis = echec_compte(
                ctx,
                conn,
                adresse,
                index,
                pref,
                maintenant,
                FAMILLE_CONNEXION,
                compte=compte,
            )
        elif compte.reinitialisation_attendue is not None:
            # Déjà prévue : on ne rapproche jamais l'échéance.
            effectif = compte.reinitialisation_attendue
        else:
            actif = jetons.sessions_vues_depuis(
                conn, compte.id, jour(maintenant) - FENETRE_ACTIVITE_JOURS
            )
            delai = (
                DELAI_REINITIALISATION_ACTIF_MS if actif else DELAI_REINITIALISATION_MS
            )
            effectif = maintenant + delai
            mettre_a_jour(
                conn,
                compte.id,
                {"reinit_demandee_ms": maintenant, "reinit_effective_ms": effectif},
            )
            seq = ecriture(conn)
            # Au journal : sans elle, une restauration perdait l'attente ; et
            # sans l'annulation, elle la ressuscitait (§3.6, 24/09/2026).
            ctx.journal.reinitialisation(lire_compte(conn, compte.id), maintenant, seq)
            avis = ctx.courrier.preparer(
                conn,
                "reinitialisation_prevue",
                adresse,
                index,
                maintenant,
                date_ms=effectif,
            )
    ctx.courrier.deposer(avis)
    if effectif is None:
        raise ErreurRequete(400, "invalidCode")
    return JSONResponse({"effectiveAt": effectif}, status_code=202)


@routeur.post("/reset/cancel")
def reset_cancel(request: Request) -> JSONResponse:
    """Depuis N'IMPORTE QUELLE session (§3.6) : c'est tout l'intérêt du délai."""
    ctx = contexte(request)
    maintenant = ctx.horloge()
    avis = None
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        compte = lire_compte(conn, session.compte_id)
        if compte.reinit_demandee_ms is not None:
            mettre_a_jour(
                conn,
                compte.id,
                {"reinit_demandee_ms": None, "reinit_effective_ms": None},
            )
            seq = ecriture(conn)
            ctx.journal.reinitialisation(lire_compte(conn, compte.id), maintenant, seq)
            avis = ctx.courrier.preparer(
                conn,
                "reinitialisation_annulee",
                adresse_du_compte(ctx, compte),
                compte.courriel_index,
                maintenant,
            )
    ctx.courrier.deposer(avis)
    return JSONResponse({"pendingResetAt": None})
