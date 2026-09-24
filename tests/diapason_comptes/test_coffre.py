"""``vault/commit`` et ``recovery/unwrap`` : la rotation et ses gardes.

Conception : ``docs/development/compte-chiffre.md`` §2.8, §3.4 et étape 4
du §6 (« vault/commit »).
"""

from __future__ import annotations

import base64
import os

from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    HEURE_MS,
    amk_mdp,
    amk_recup,
    code_de,
    trousseau,
)


def _octets(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


class TestComparerEchanger:
    def test_une_version_de_base_perimee_rend_vault_conflict(self, service):
        """§3.4 — comparer-et-échanger sur ``vaultVersion`` ET
        ``keyringVersion`` : un appareil qui fait tourner les clés sur un
        coffre déjà remplacé ailleurs écraserait la rotation de l'autre."""
        inscrit = service.inscrire("cas@exemple.org")
        for surcharge in ({"base_coffre": 2}, {"base_trousseau": 2}):
            r = service.post(
                "/vault/commit",
                service.corps_commit(inscrit, **surcharge),
                headers=inscrit.bearer,
            )
            assert r.status_code == 409, f"base périmée {surcharge}"
            assert r.json() == {"error": {"code": "vaultConflict"}}

    def test_de_deux_rotations_sur_la_meme_base_une_seule_gagne(self, service):
        """§3.4 — la seconde voit ses versions de base dépassées."""
        inscrit = service.inscrire("deux@exemple.org")
        corps = service.corps_commit(inscrit)
        premiere = service.post("/vault/commit", corps, headers=inscrit.bearer)
        assert premiere.status_code == 200, premiere.text
        nouveau = {"Authorization": f"Bearer {premiere.json()['sessionToken']}"}
        seconde = service.post("/vault/commit", corps, headers=nouveau)
        assert seconde.status_code == 409, "la seconde perd"

    def test_new_key_epoch_doit_valoir_l_epoque_courante_plus_un(self, service):
        """§2.8 — une époque sautée ou répétée casserait la règle « toute
        nouvelle écriture sous DEK_{e+1} » que ``sync/push`` vérifiera."""
        inscrit = service.inscrire("epoque@exemple.org")
        for epoque in (1, 3):
            r = service.post(
                "/vault/commit",
                service.corps_commit(inscrit, epoque=epoque),
                headers=inscrit.bearer,
            )
            assert r.status_code == 409, f"newKeyEpoch {epoque} refusé"
        r = service.post(
            "/vault/commit", service.corps_commit(inscrit), headers=inscrit.bearer
        )
        assert r.status_code == 200, r.text
        assert r.json()["keyEpoch"] == 2, "époque 1 → 2"
        assert (r.json()["vaultVersion"], r.json()["keyringVersion"]) == (2, 2)

    def test_garder_une_recuperation_absente_est_un_conflit(self, service):
        """§3.4 — ``mode: keep`` sur un compte sans clé de récupération : le
        client se croit dans un autre état que le serveur."""
        inscrit = service.inscrire("sansrecup@exemple.org", recuperation=False)
        corps = service.corps_commit(
            inscrit,
            recuperation={
                "mode": "keep",
                "sealedMasterKey": b64url(amk_recup(inscrit.account_id, 2)),
            },
        )
        r = service.post("/vault/commit", corps, headers=inscrit.bearer)
        assert r.status_code == 409, "keep sans récupération"


class TestRevocationDOffice:
    def test_toutes_les_autres_sessions_tombent(self, service):
        """§2.8 et §3.7 — révocation d'office, SANS option : un appareil
        perdu ne reçoit plus rien après un changement de mot de passe fait
        ailleurs, dès son premier contact."""
        inscrit = service.inscrire("office@exemple.org")
        autre = service.connecter(inscrit).json()["sessionToken"]
        r = service.post(
            "/vault/commit",
            service.corps_commit(inscrit, nouvelle_auth=os.urandom(32)),
            headers=inscrit.bearer,
        )
        assert r.status_code == 200, r.text
        for jeton in (inscrit.jeton, autre):
            vieux = service.get(
                "/account", headers={"Authorization": f"Bearer {jeton}"}
            )
            assert vieux.status_code == 401, "toute session d'avant tombe"
            assert vieux.json()["error"]["code"] == "sessionRevoked"
        neuf = {"Authorization": f"Bearer {r.json()['sessionToken']}"}
        assert service.get("/account", headers=neuf).status_code == 200, (
            "la réponse porte une session neuve"
        )

    def test_le_nouveau_mot_de_passe_remplace_l_ancien(self, service):
        """P5 — après la rotation, l'ancien ``authKey`` ne rend plus rien et
        ``/login`` rend la NOUVELLE enveloppe."""
        inscrit = service.inscrire("p5@exemple.org")
        nouvelle = os.urandom(32)
        corps = service.corps_commit(inscrit, nouvelle_auth=nouvelle)
        r = service.post("/vault/commit", corps, headers=inscrit.bearer)
        assert r.status_code == 200, r.text
        assert service.connecter(inscrit).status_code == 401, "ancien mot de passe"
        inscrit.auth_key = nouvelle
        connexion = service.connecter(inscrit).json()
        assert _octets(connexion["wrappedMasterKey"]) == _octets(
            corps["password"]["wrappedMasterKey"]
        ), "l'enveloppe du nouveau mot de passe"
        service.expediteur.attendre(inscrit.email, "mot_de_passe_change")

    def test_deconnecter_un_appareil_annonce_la_revocation(self, service):
        """P6 — « appareil déconnecté et clés renouvelées », par courriel."""
        inscrit = service.inscrire("p6@exemple.org")
        perdu = service.connecter(inscrit).json()
        r = service.post(
            "/vault/commit",
            service.corps_commit(inscrit, revokedSessionId=perdu["sessionId"]),
            headers=inscrit.bearer,
        )
        assert r.status_code == 200, r.text
        service.expediteur.attendre(inscrit.email, "appareil_deconnecte")


class TestPreuveParCode:
    def test_email_code_exige_aussi_un_bearer(self, service):
        """§3.4 — un code seul, lu dans une boîte compromise (A3), ne fait
        pas tourner les clés : il faut AUSSI une session."""
        inscrit = service.inscrire("code@exemple.org")
        service.horloge.avancer(2 * HEURE_MS)
        assert (
            service.post("/vault/code", {}, headers=inscrit.bearer).status_code == 202
        )
        code = code_de(service.expediteur.attendre(inscrit.email, "code_coffre"))
        corps = service.corps_commit(
            inscrit,
            preuve={"kind": "emailCode", "code": code},
            nouvelle_auth=os.urandom(32),
        )
        sans = service.post("/vault/commit", corps)
        assert sans.status_code in (401, 403), "sans Bearer, refusé"
        avec = service.post("/vault/commit", corps, headers=inscrit.bearer)
        assert avec.status_code == 200, "avec Bearer ET code, accepté"


class TestRecuperation:
    def test_la_cle_de_recuperation_mene_a_une_rotation_sans_session(self, service):
        """P4, chemin 1 — ``recovery/unwrap`` rend l'AMK scellée et un jeton de
        10 min à usage unique ; ``vault/commit`` l'accepte sans Bearer."""
        inscrit = service.inscrire("recup@exemple.org")
        r = service.post(
            "/recovery/unwrap",
            {
                "email": inscrit.email,
                "recoveryAuthKey": b64url(inscrit.recovery_auth_key),
            },
        )
        assert r.status_code == 200, r.text
        deballe = r.json()
        assert _octets(deballe["sealedMasterKey"]) == inscrit.sealed, "AMK scellée"
        preuve = {"kind": "recovery", "recoveryToken": deballe["recoveryToken"]}
        corps = service.corps_commit(
            inscrit, preuve=preuve, nouvelle_auth=os.urandom(32)
        )
        assert service.post("/vault/commit", corps).status_code == 200, "rotation"
        rejeu = service.post(
            "/vault/commit", service.corps_commit(inscrit, preuve=preuve)
        )
        assert rejeu.status_code == 403, "le jeton de récupération ne sert qu'une fois"
        service.expediteur.attendre(inscrit.email, "recuperation_utilisee")

    def test_le_jeton_de_recuperation_meurt_apres_dix_minutes(self, service):
        """§3.4 — 10 min : entre l'ouverture et la rotation, pas davantage."""
        inscrit = service.inscrire("dix@exemple.org")
        deballe = service.post(
            "/recovery/unwrap",
            {
                "email": inscrit.email,
                "recoveryAuthKey": b64url(inscrit.recovery_auth_key),
            },
        ).json()
        service.horloge.avancer(10 * 60_000 + 1)
        preuve = {"kind": "recovery", "recoveryToken": deballe["recoveryToken"]}
        r = service.post("/vault/commit", service.corps_commit(inscrit, preuve=preuve))
        assert r.status_code == 403, "jeton expiré"

    def test_remplacer_puis_retirer_la_cle_de_recuperation(self, service):
        """§2.8 — remplacer ou retirer la clé est une rotation ; l'ancienne
        ``recoveryAuthKey`` cesse d'ouvrir le compte."""
        inscrit = service.inscrire("remplace@exemple.org")
        nouvelle_recup = os.urandom(32)
        r = service.post(
            "/vault/commit",
            service.corps_commit(
                inscrit,
                recuperation={
                    "mode": "replace",
                    "authKey": b64url(nouvelle_recup),
                    "sealedMasterKey": b64url(amk_recup(inscrit.account_id, 2)),
                },
            ),
            headers=inscrit.bearer,
        )
        assert r.status_code == 200, r.text
        ancienne = service.post(
            "/recovery/unwrap",
            {
                "email": inscrit.email,
                "recoveryAuthKey": b64url(inscrit.recovery_auth_key),
            },
        )
        assert ancienne.status_code == 401, "l'ancienne clé ne vaut plus"
        neuve = service.post(
            "/recovery/unwrap",
            {"email": inscrit.email, "recoveryAuthKey": b64url(nouvelle_recup)},
        )
        assert neuve.status_code == 200, "la nouvelle clé ouvre"

        inscrit.vault_version = inscrit.keyring_version = inscrit.key_epoch = 2
        bearer = {"Authorization": f"Bearer {r.json()['sessionToken']}"}
        r = service.post(
            "/vault/commit",
            service.corps_commit(inscrit, recuperation={"mode": "remove"}),
            headers=bearer,
        )
        assert r.status_code == 200, r.text
        compte = service.get(
            "/account", headers={"Authorization": f"Bearer {r.json()['sessionToken']}"}
        ).json()
        assert compte["recoveryConfigured"] is False, "plus de clé de récupération"


def _deballer(service, inscrit) -> str:
    r = service.post(
        "/recovery/unwrap",
        {
            "email": inscrit.email,
            "recoveryAuthKey": b64url(inscrit.recovery_auth_key),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["recoveryToken"]


class TestJetonDeRecuperationApresRiposte:
    """§3.4 — le jeton de ``recovery/unwrap`` vit 10 min. Jusqu'au
    24/09/2026, il survivait à la rotation que le propriétaire fait
    PRÉCISÉMENT parce que sa clé a fuité : l'attaquant rejouait son vieux
    jeton avec des versions faciles à deviner et reprenait le compte."""

    def test_un_jeton_anterieur_a_un_retrait_de_cle_est_refuse(self, service):
        """§2.8, §3.4 — l'attaquant a ``R`` et déballe ; le propriétaire,
        prévenu par « clé utilisée », retire la clé ; le vieux jeton ne doit
        plus rien faire tourner."""
        alice = service.inscrire("riposte@exemple.org")
        jeton_vole = _deballer(service, alice)
        r = service.post(
            "/vault/commit",
            service.corps_commit(alice, recuperation={"mode": "remove"}),
            headers=alice.bearer,
        )
        assert r.status_code == 200, r.text
        alice.vault_version = alice.keyring_version = alice.key_epoch = 2
        alice.sealed = None
        attaque = service.post(
            "/vault/commit",
            service.corps_commit(
                alice,
                preuve={"kind": "recovery", "recoveryToken": jeton_vole},
                nouvelle_auth=os.urandom(32),
            ),
        )
        assert attaque.status_code == 403, "le jeton d'avant la riposte est mort"
        assert attaque.json() == {"error": {"code": "invalidProof"}}
        neuf = {"Authorization": f"Bearer {r.json()['sessionToken']}"}
        assert service.get("/account", headers=neuf).status_code == 200, (
            "la session du propriétaire vit toujours"
        )

    def test_un_jeton_anterieur_a_un_remplacement_de_cle_est_refuse(self, service):
        """§3.4 — « clé de récupération remplacée : l'ancienne ne sert plus »,
        dit le courriel ; c'était faux pendant 10 min."""
        alice = service.inscrire("remplacee@exemple.org")
        jeton_vole = _deballer(service, alice)
        r = service.post(
            "/vault/commit",
            service.corps_commit(
                alice,
                recuperation={
                    "mode": "replace",
                    "authKey": b64url(os.urandom(32)),
                    "sealedMasterKey": b64url(amk_recup(alice.account_id, 2)),
                },
            ),
            headers=alice.bearer,
        )
        assert r.status_code == 200, r.text
        alice.vault_version = alice.keyring_version = alice.key_epoch = 2
        attaque = service.post(
            "/vault/commit",
            service.corps_commit(
                alice,
                preuve={"kind": "recovery", "recoveryToken": jeton_vole},
                recuperation={"mode": "remove"},
            ),
        )
        assert attaque.status_code == 403, "le jeton d'avant le remplacement est mort"

    def test_un_jeton_anterieur_a_reset_complete_est_refuse(self, service):
        """§3.6 — ``reset/complete`` remet les versions à 1/1/1 : un jeton pris
        avant s'appliquait au coffre NEUF, versions triviales à deviner."""
        from diapason_comptes import jetons as jetons_

        alice = service.inscrire("apresreset@exemple.org")
        jeton_vole = _deballer(service, alice)
        with service.ctx.base.transaction() as conn:
            conn.execute(
                "UPDATE comptes SET reinit_demandee_ms = ?, reinit_effective_ms = ?",
                (service.horloge() - 1, service.horloge() - 1),
            )
            jetons_.enregistrer_code(
                conn,
                service.secrets,
                service.secrets.index_courriel(alice.email),
                "reinitialisation",
                "616161",
                service.horloge(),
            )
        nouvelle = os.urandom(32)
        r = service.post(
            "/reset/complete",
            {
                "email": alice.email,
                "code": "616161",
                "kdfVersion": 1,
                "authKey": b64url(nouvelle),
                "wrappedMasterKey": b64url(amk_mdp(alice.account_id)),
                "recovery": None,
                "keyring": b64url(trousseau(alice.account_id)),
            },
        )
        assert r.status_code == 200, r.text
        alice.sealed = None
        attaque = service.post(
            "/vault/commit",
            service.corps_commit(
                alice,
                preuve={"kind": "recovery", "recoveryToken": jeton_vole},
                nouvelle_auth=os.urandom(32),
            ),
        )
        assert attaque.status_code == 403, (
            "le jeton d'avant la réinitialisation est mort"
        )
        alice.auth_key = nouvelle
        assert service.connecter(alice).status_code == 200, (
            "le mot de passe posé par reset/complete reste le bon"
        )
