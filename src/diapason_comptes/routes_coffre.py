"""Routes du coffre : code du coffre, rotation, récupération, réinitialisation.

Conception : ``docs/development/compte-chiffre.md`` §2.8, §3.4 et §3.6.

TOUTE rotation passe par ``vault/commit`` : changement de mot de passe,
oubli avec un appareil déverrouillé, récupération par ``R``, remplacement ou
retrait de la clé de récupération, déconnexion d'un appareil perdu. Le
serveur y fait un comparer-et-échanger sur ``vaultVersion`` ET
``keyringVersion`` en une transaction, exige ``newKeyEpoch = courant + 1``,
et révoque d'office TOUTES les sessions — sans option. C'est ce qui fait
qu'un changement de mot de passe fait ailleurs atteint chaque appareil au
premier contact (§3.7), au lieu de laisser un appareil perdu lire la suite.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from diapason_comptes import jetons
from diapason_comptes.base import ecriture, lire_compte
from diapason_comptes.limites import FAMILLE_CONNEXION, FAMILLE_RECUPERATION
from diapason_comptes.routes_identite import (
    COMPTE_FACTICE,
    adresse_du_compte,
    attendre,
    aux_secrets_courants,
    contexte,
    echec_compte,
    exiger_courriel_disponible,
    index_pour,
    mettre_a_jour,
    prefixe,
    recuperation_initiale,
    reponse_session,
    sceller_coffre,
    session_requise,
    trouver_compte,
    verifier_auth,
)
from diapason_comptes.validation import (
    ErreurRequete,
    b64url,
    cle_32,
    code_six_chiffres,
    corps_json,
    courriel,
    entier,
    enveloppe_amk_mot_de_passe,
    enveloppe_amk_recuperation,
    enveloppe_trousseau,
    invalide,
    kdf_version,
    objet,
    texte,
)

routeur = APIRouter(prefix="/api/v1")

PREUVES = ("password", "emailCode", "recovery")
MODES_RECUPERATION = ("keep", "replace", "remove")


# ----------------------------------------------------------------------
# Code du coffre
# ----------------------------------------------------------------------


@routeur.post("/vault/code", status_code=202)
def vault_code(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Code pour « oublié, appareil déverrouillé » (P4, chemin 2). La session
    seule ne suffit pas à changer le mot de passe : il faut ce code en plus."""
    ctx = contexte(request)
    maintenant = ctx.horloge()
    with ctx.base.transaction() as conn:
        session = session_requise(ctx, conn, request, maintenant)
        exiger_courriel_disponible(ctx, conn, maintenant)
        compte = lire_compte(conn, session.compte_id)
        code = jetons.nouveau_code()
        message = ctx.courrier.preparer(
            conn,
            "code_coffre",
            adresse_du_compte(ctx, compte),
            compte.courriel_index,
            maintenant,
            code=code,
        )
        if message is not None:
            jetons.enregistrer_code(
                conn, ctx.secrets, compte.courriel_index, "coffre", code, maintenant
            )
    # Authentifié : dire « trop tôt » ne renseigne personne sur l'adresse,
    # et la personne attendrait sinon un code qui ne viendra pas.
    if message is None:
        raise ErreurRequete(429, "tooManyAttempts", retry_after_s=60)
    ctx.courrier.deposer(message)
    return JSONResponse({}, status_code=202)


# ----------------------------------------------------------------------
# Rotation
# ----------------------------------------------------------------------


def _lire_commit(corps: dict[str, Any]) -> dict[str, Any]:
    preuve = objet(corps, "proof")
    genre = preuve.get("kind")
    if genre not in PREUVES:
        raise invalide("proof.kind")
    mot_de_passe = objet(corps, "password")
    recuperation = objet(corps, "recovery")
    mode = recuperation.get("mode")
    if mode not in MODES_RECUPERATION:
        raise invalide("recovery.mode")
    lu: dict[str, Any] = {
        "genre": genre,
        "base_coffre": entier(corps, "baseVaultVersion", minimum=1),
        "nouveau_coffre": entier(corps, "newVaultVersion", minimum=1),
        "base_trousseau": entier(corps, "baseKeyringVersion", minimum=1),
        "nouveau_trousseau": entier(corps, "newKeyringVersion", minimum=1),
        "nouvelle_epoque": entier(corps, "newKeyEpoch", minimum=1, maximum=0xFFFFFFFF),
        "kdf": kdf_version(mot_de_passe, chemin="password."),
        "auth_key": cle_32(mot_de_passe, "authKey", chemin="password."),
        "amk_mdp": enveloppe_amk_mot_de_passe(mot_de_passe, chemin="password."),
        "mode": mode,
        "trousseau": enveloppe_trousseau(corps),
        "session_revoquee": None,
    }
    if genre == "password":
        lu["preuve"] = cle_32(preuve, "authKey", chemin="proof.")
    elif genre == "emailCode":
        lu["preuve"] = code_six_chiffres(preuve, chemin="proof.")
    else:
        lu["preuve"] = texte(preuve, "recoveryToken", chemin="proof.")
    if mode == "keep":
        lu["recuperation"] = (
            None,
            enveloppe_amk_recuperation(recuperation, chemin="recovery."),
        )
    elif mode == "replace":
        lu["recuperation"] = (
            cle_32(recuperation, "authKey", chemin="recovery."),
            enveloppe_amk_recuperation(recuperation, chemin="recovery."),
        )
    else:
        lu["recuperation"] = None
    if corps.get("revokedSessionId") is not None:
        lu["session_revoquee"] = texte(corps, "revokedSessionId", maximum=64)
    return lu


@routeur.post("/vault/commit")
def vault_commit(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Comparer-et-échanger, rotation, révocation de toutes les sessions."""
    ctx = contexte(request)
    lu = _lire_commit(corps)
    pref = prefixe(request)
    maintenant = ctx.horloge()
    avis: list = []
    resultat = None
    refus: ErreurRequete | None = None
    with ctx.base.transaction() as conn:
        # --- La preuve -------------------------------------------------
        if lu["genre"] == "recovery":
            # Aucun Bearer : on a tout perdu sauf ``R``. Le jeton vient de
            # ``recovery/unwrap``, 10 min, usage unique.
            consomme = jetons.consommer_jeton(
                conn, lu["preuve"], "recuperation", maintenant
            )
            compte = None if consomme is None else lire_compte(conn, consomme.compte_id)
            if compte is None:
                raise ErreurRequete(403, "invalidProof")
            adresse = adresse_du_compte(ctx, compte)
        else:
            # ``emailCode`` exige AUSSI un Bearer (§3.4) : un code seul, reçu
            # dans une boîte compromise (A3), ne fait pas tourner les clés.
            session = session_requise(ctx, conn, request, maintenant)
            compte = lire_compte(conn, session.compte_id)
            adresse = adresse_du_compte(ctx, compte)
            if lu["genre"] == "password":
                attendre(ctx, conn, adresse, pref, maintenant, FAMILLE_CONNEXION)
                prouve = verifier_auth(ctx, compte, lu["preuve"])
            else:
                prouve = jetons.consommer_code(
                    conn,
                    ctx.secrets,
                    compte.courriel_index,
                    "coffre",
                    lu["preuve"],
                    maintenant,
                )
            if not prouve:
                if lu["genre"] == "password":
                    avis.append(
                        echec_compte(
                            ctx,
                            conn,
                            adresse,
                            compte.courriel_index,
                            pref,
                            maintenant,
                            FAMILLE_CONNEXION,
                            compte=compte,
                        )
                    )
                refus = ErreurRequete(403, "invalidProof")

        # --- Le comparer-et-échanger -------------------------------------
        if refus is None:
            conflit = (
                lu["base_coffre"] != compte.version_coffre
                or lu["base_trousseau"] != compte.version_trousseau
                or lu["nouveau_coffre"] <= compte.version_coffre
                or lu["nouveau_trousseau"] <= compte.version_trousseau
                or lu["nouvelle_epoque"] != compte.epoque_cle + 1
                or (lu["mode"] == "keep" and compte.verif_recup is None)
            )
            if conflit:
                # Annule la transaction : un code consommé par un commit
                # perdant reste utilisable pour le suivant.
                raise ErreurRequete(409, "vaultConflict")
            if lu["session_revoquee"] is not None:
                ligne = conn.execute(
                    "SELECT 1 FROM sessions WHERE id = ? AND compte_id = ?",
                    (lu["session_revoquee"], compte.id),
                ).fetchone()
                if ligne is None:
                    raise ErreurRequete(422, "invalidRequest", champ="revokedSessionId")

            ancien_mot_de_passe = verifier_auth(ctx, compte, lu["auth_key"])
            colonnes = sceller_coffre(
                ctx,
                compte.id,
                kdf=lu["kdf"],
                auth_key=lu["auth_key"],
                amk_mdp=lu["amk_mdp"],
                recuperation=None,
                trousseau=lu["trousseau"],
            )
            if lu["mode"] == "keep":
                colonnes["verif_recup"] = compte.verif_recup
                colonnes["amk_recup"] = ctx.secrets.sceller(
                    compte.id, "amk_recup", lu["recuperation"][1]
                )
            elif lu["mode"] == "replace":
                colonnes["verif_recup"] = ctx.secrets.verificateur_recuperation(
                    compte.id, lu["recuperation"][0]
                )
                colonnes["amk_recup"] = ctx.secrets.sceller(
                    compte.id, "amk_recup", lu["recuperation"][1]
                )
            colonnes.update(
                version_coffre=lu["nouveau_coffre"],
                version_trousseau=lu["nouveau_trousseau"],
                epoque_cle=lu["nouvelle_epoque"],
            )
            curseur = conn.execute(
                "UPDATE comptes SET "
                + ", ".join(f"{nom} = ?" for nom in colonnes)
                + " WHERE id = ? AND version_coffre = ? AND version_trousseau = ? "
                "AND epoque_cle = ?",
                (
                    *colonnes.values(),
                    compte.id,
                    compte.version_coffre,
                    compte.version_trousseau,
                    compte.epoque_cle,
                ),
            )
            if curseur.rowcount != 1:
                raise ErreurRequete(409, "vaultConflict")
            aux_secrets_courants(ctx, conn, compte.id, adresse, lu["auth_key"])

            # Toutes les sessions, la courante comprise : la réponse en porte
            # une neuve. Un jeton d'avant la rotation ne vaut plus rien, ni
            # un jeton de récupération, ni un code du coffre.
            revoques = jetons.revoquer_sessions(conn, compte.id)
            jetons.invalider_preuves(conn, compte.id, compte.courriel_index)
            session_id, jeton = jetons.creer_session(conn, compte.id, maintenant)
            seq = ecriture(conn)
            apres = lire_compte(conn, compte.id)
            ctx.journal.ligne_de_securite(
                "vaultCommit",
                apres,
                maintenant,
                seq,
                sessionHashes=sorted(h.hex() for h in revoques),
            )
            index = compte.courriel_index
            if not ancien_mot_de_passe:
                avis.append(
                    ctx.courrier.preparer(
                        conn, "mot_de_passe_change", adresse, index, maintenant
                    )
                )
            if lu["mode"] == "replace":
                avis.append(
                    ctx.courrier.preparer(
                        conn, "recuperation_remplacee", adresse, index, maintenant
                    )
                )
            elif lu["mode"] == "remove" and compte.verif_recup is not None:
                avis.append(
                    ctx.courrier.preparer(
                        conn, "recuperation_retiree", adresse, index, maintenant
                    )
                )
            if lu["session_revoquee"] is not None:
                avis.append(
                    ctx.courrier.preparer(
                        conn, "appareil_deconnecte", adresse, index, maintenant
                    )
                )
            resultat = {
                "vaultVersion": apres.version_coffre,
                "keyringVersion": apres.version_trousseau,
                "keyEpoch": apres.epoque_cle,
                "sessionId": session_id,
                "sessionToken": jeton,
            }
    ctx.courrier.deposer(*avis)
    if refus is not None:
        raise refus
    return JSONResponse(resultat)


# ----------------------------------------------------------------------
# Récupération
# ----------------------------------------------------------------------


@routeur.post("/recovery/unwrap")
def recovery_unwrap(
    request: Request, corps: dict = Depends(corps_json)
) -> JSONResponse:
    """L'AMK scellée, contre ``recoveryAuthKey``. Compteur d'échecs à part."""
    ctx = contexte(request)
    adresse = courriel(corps)
    cle = cle_32(corps, "recoveryAuthKey")
    pref = prefixe(request)
    maintenant = ctx.horloge()
    resultat = None
    avis = None
    with ctx.base.transaction() as conn:
        attendre(ctx, conn, adresse, pref, maintenant, FAMILLE_RECUPERATION)
        compte = trouver_compte(ctx, conn, adresse)
        index = index_pour(ctx, compte, adresse)
        if compte is None or compte.verif_recup is None:
            ctx.secrets.verifier_mac(
                bytes([ctx.secrets.version]) + bytes(32),
                b"recuperation",
                COMPTE_FACTICE.encode("ascii") + cle,
            )
            bon = False
        else:
            bon = ctx.secrets.verifier_mac(
                compte.verif_recup, b"recuperation", compte.id.encode("ascii") + cle
            )
        if not bon:
            avis = echec_compte(
                ctx,
                conn,
                adresse,
                index,
                pref,
                maintenant,
                FAMILLE_RECUPERATION,
                compte=compte,
            )
        else:
            ctx.limiteur.reussite(conn, adresse, pref, FAMILLE_RECUPERATION)
            if compte.verif_recup[0] != ctx.secrets.version:
                # Le seul moment où l'on tient ``recoveryAuthKey`` : le
                # vérificateur passe au poivre courant (§3.2).
                mettre_a_jour(
                    conn,
                    compte.id,
                    {
                        "verif_recup": ctx.secrets.verificateur_recuperation(
                            compte.id, cle
                        )
                    },
                )
                aux_secrets_courants(ctx, conn, compte.id, adresse)
            jeton = jetons.creer_jeton_recuperation(conn, index, compte.id, maintenant)
            avis = ctx.courrier.preparer(
                conn, "recuperation_utilisee", adresse, index, maintenant
            )
            resultat = {
                "accountId": compte.id,
                "recoveryToken": jeton,
                "sealedMasterKey": b64url(
                    ctx.secrets.ouvrir(compte.id, "amk_recup", compte.amk_recup)
                ),
                "vaultVersion": compte.version_coffre,
                "keyring": b64url(
                    ctx.secrets.ouvrir(compte.id, "trousseau", compte.trousseau)
                ),
                "keyringVersion": compte.version_trousseau,
                "keyEpoch": compte.epoque_cle,
                "incarnation": compte.incarnation,
            }
    ctx.courrier.deposer(avis)
    if resultat is None:
        raise ErreurRequete(401, "invalidCredentials")
    return JSONResponse(resultat)


# ----------------------------------------------------------------------
# Réinitialisation — l'effacement (§3.6)
# ----------------------------------------------------------------------


@routeur.post("/reset/complete")
def reset_complete(request: Request, corps: dict = Depends(corps_json)) -> JSONResponse:
    """Seulement après ``effectiveAt``, avec un NOUVEAU code. Tout en UNE
    transaction : effacement des objets, des pièces et des sessions ; coffre
    et trousseau neufs ; ``incarnation + 1`` ; ``keyEpoch = 1`` ; entrée au
    journal.

    La version précédente faisait effacer par un minuteur, ailleurs : entre
    l'effacement et le coffre neuf, le compte existait sans données ni clés,
    et un appareil qui se connectait à ce moment-là voyait un serveur vide
    sous l'ancienne incarnation. Ici, rien ne s'efface tout seul.
    """
    ctx = contexte(request)
    adresse = courriel(corps)
    code = code_six_chiffres(corps)
    kdf = kdf_version(corps)
    auth_key = cle_32(corps, "authKey")
    amk_mdp = enveloppe_amk_mot_de_passe(corps)
    recuperation = recuperation_initiale(corps)
    trousseau = enveloppe_trousseau(corps)
    pref = prefixe(request)
    maintenant = ctx.horloge()
    resultat = None
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
        else:
            attendue = compte.reinitialisation_attendue
            if attendue is None or attendue > maintenant:
                raise ErreurRequete(409, "resetNotDue")
            conn.execute("DELETE FROM objets WHERE compte_id = ?", (compte.id,))
            conn.execute("DELETE FROM pieces WHERE compte_id = ?", (compte.id,))
            revoques = jetons.revoquer_sessions(conn, compte.id)
            jetons.invalider_preuves(conn, compte.id, compte.courriel_index)
            colonnes = sceller_coffre(
                ctx,
                compte.id,
                kdf=kdf,
                auth_key=auth_key,
                amk_mdp=amk_mdp,
                recuperation=recuperation,
                trousseau=trousseau,
            )
            # Le corps de ``reset/complete`` ne porte aucune version (§3.4) :
            # le client scelle son coffre neuf comme à l'inscription, en
            # version 1, et c'est ce que le serveur doit stocker pour que
            # l'AAD ``w`` corresponde.
            colonnes.update(
                version_coffre=1,
                version_trousseau=1,
                epoque_cle=1,
                incarnation=compte.incarnation + 1,
                octets=0,
                reinit_demandee_ms=None,
                reinit_effective_ms=None,
            )
            mettre_a_jour(conn, compte.id, colonnes)
            aux_secrets_courants(ctx, conn, compte.id, adresse, auth_key)
            session_id, jeton = jetons.creer_session(conn, compte.id, maintenant)
            seq = ecriture(conn)
            apres = lire_compte(conn, compte.id)
            ctx.journal.ligne_de_securite(
                "resetComplete",
                apres,
                maintenant,
                seq,
                sessionHashes=sorted(h.hex() for h in revoques),
            )
            avis = ctx.courrier.preparer(
                conn, "reinitialisation_effectuee", adresse, index, maintenant
            )
            resultat = reponse_session(apres, session_id, jeton)
    ctx.courrier.deposer(avis)
    if resultat is None:
        raise ErreurRequete(400, "invalidCode")
    return JSONResponse(resultat)
