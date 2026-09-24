"""Sessions : hachage, révocation, expiration, et les limites d'un jeton seul.

Conception : ``docs/development/compte-chiffre.md`` §3.7 et étape 4 du §6
(« Sessions », « Ce qu'une session seule ne peut pas faire »).
"""

from __future__ import annotations

import hashlib
import os

from diapason_comptes.base import JOUR_MS
from diapason_comptes.validation import b64url


class TestHachageEtRevocation:
    def test_seul_le_sha256_du_jeton_est_garde(self, service):
        """§3.7 — une copie de ``comptes.db`` ne donne aucune session : le
        jeton n'y est pas, seulement son SHA-256."""
        inscrit = service.inscrire("hache@exemple.org")
        assert inscrit.jeton.startswith("dps1_"), "préfixe du jeton de session"
        with service.ctx.base.lecture() as conn:
            (hash_,) = conn.execute("SELECT jeton_hash FROM sessions").fetchone()
        assert hash_ == hashlib.sha256(inscrit.jeton.encode()).digest(), "SHA-256"
        assert inscrit.jeton.encode() not in service.octets_sur_disque(), (
            "le jeton n'apparaît nulle part dans la base"
        )

    def test_la_deconnexion_revoque_le_jeton(self, service):
        """§3.7 — la révocation est consultée à CHAQUE requête."""
        inscrit = service.inscrire("logout@exemple.org")
        assert service.post("/logout", headers=inscrit.bearer).status_code == 204
        r = service.get("/account", headers=inscrit.bearer)
        assert r.status_code == 401, "jeton révoqué"
        assert r.json() == {"error": {"code": "sessionRevoked"}}

    def test_un_jeton_inconnu_ou_absent_vaut_session_revoquee(self, service):
        """§3.7 — un jeton inconnu : révoqué, purgé ou compte supprimé ;
        dans tous les cas l'appareil doit effacer ce qu'il garde."""
        faux = {"Authorization": "Bearer dps1_" + "A" * 43}
        assert service.get("/account", headers=faux).json()["error"]["code"] == (
            "sessionRevoked"
        )
        assert service.get("/account").status_code == 401, "sans en-tête : 401"

    def test_quatre_vingt_dix_jours_d_inactivite_expirent_la_session(self, service):
        """§3.7 — 90 jours d'inactivité, glissants : ``sessionExpired``, qui
        redemande le mot de passe sans effacer l'AMK mémorisée."""
        inscrit = service.inscrire("expire@exemple.org")
        service.horloge.avancer(91 * JOUR_MS)
        r = service.get("/account", headers=inscrit.bearer)
        assert r.status_code == 401, "session expirée"
        assert r.json() == {"error": {"code": "sessionExpired"}}

    def test_une_session_utilisee_glisse(self, service):
        """§3.7 — « glissants » : un appareil utilisé tous les deux mois ne
        redemande jamais le mot de passe."""
        inscrit = service.inscrire("glisse@exemple.org")
        for _ in range(3):
            service.horloge.avancer(60 * JOUR_MS)
            r = service.get("/account", headers=inscrit.bearer)
            assert r.status_code == 200, "la session a été prolongée"


class TestCeQuUneSessionSeuleNePeutPasFaire:
    def test_aucune_route_a_jeton_seul_ne_rend_d_enveloppe(self, service):
        """§3.7, A9 — un jeton volé lit les métadonnées, jamais l'enveloppe
        AMK, l'AMK scellée ni le trousseau."""
        inscrit = service.inscrire("vol@exemple.org")
        secrets_ = [inscrit.wrapped, inscrit.keyring, inscrit.sealed]
        for chemin in ("/account", "/sessions"):
            r = service.get(chemin, headers=inscrit.bearer)
            assert r.status_code == 200, f"{chemin} répond à la session"
            for secret in secrets_:
                assert b64url(secret).encode() not in r.content, (
                    f"{chemin} ne rend aucune enveloppe"
                )

    def test_une_session_seule_ne_fait_pas_tourner_les_cles(self, service):
        """§3.7 — modifier le coffre exige ``authKey`` ou un code ; avec un
        jeton seul et une preuve fausse, 403 et rien ne change."""
        inscrit = service.inscrire("rotation@exemple.org")
        faux = {"kind": "password", "authKey": b64url(os.urandom(32))}
        r = service.post(
            "/vault/commit",
            service.corps_commit(inscrit, preuve=faux),
            headers=inscrit.bearer,
        )
        assert r.status_code == 403, "preuve fausse"
        assert r.json() == {"error": {"code": "invalidProof"}}
        assert (
            service.get("/account", headers=inscrit.bearer).json()["vaultVersion"] == 1
        )

    def test_une_session_seule_ne_revoque_pas_les_autres(self, service):
        """§3.4 — la révocation d'une autre session ne passe QUE par
        ``vault/commit`` : aucune route ne révoque par identifiant."""
        inscrit = service.inscrire("revoque@exemple.org")
        autre = service.connecter(inscrit).json()
        routes = [r for r in service.app.routes if hasattr(r, "methods")]
        assert not [
            r.path for r in routes if "DELETE" in r.methods and "session" in r.path
        ], "aucune route DELETE de session"
        faux = {"kind": "emailCode", "code": "000000"}
        r = service.post(
            "/vault/commit",
            service.corps_commit(
                inscrit, preuve=faux, revokedSessionId=autre["sessionId"]
            ),
            headers=inscrit.bearer,
        )
        assert r.status_code == 403, "code faux"
        jeton_autre = {"Authorization": f"Bearer {autre['sessionToken']}"}
        assert service.get("/account", headers=jeton_autre).status_code == 200, (
            "l'autre session vit toujours"
        )

    def test_une_session_seule_ne_supprime_pas_le_compte(self, service):
        """§3.4, A9 — ``account/delete`` exige ``authKey`` en plus du jeton."""
        inscrit = service.inscrire("supprime@exemple.org")
        r = service.post(
            "/account/delete",
            {"authKey": b64url(os.urandom(32))},
            headers=inscrit.bearer,
        )
        assert r.status_code == 403, "authKey fausse"
        assert service.connecter(inscrit).status_code == 200, "le compte existe encore"


class TestPlafondDeSessions:
    def test_un_compte_garde_au_plus_cinquante_sessions(self, service):
        """§3.5 — ``/login`` insère une session à chaque appel, sans garde ni
        plafond : un titulaire qui boucle faisait grossir ``sessions`` et la
        réponse de ``GET /sessions`` sans limite. 50 par compte, la moins
        récemment vue part la première."""
        from diapason_comptes.jetons import SESSIONS_MAX_PAR_COMPTE

        inscrit = service.inscrire("boucle@exemple.org")
        derniere = None
        for _ in range(SESSIONS_MAX_PAR_COMPTE + 5):
            r = service.connecter(inscrit)
            assert r.status_code == 200, r.text
            derniere = r.json()["sessionToken"]
        with service.ctx.base.lecture() as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        assert n == SESSIONS_MAX_PAR_COMPTE, f"{n} sessions gardées"
        neuve = {"Authorization": f"Bearer {derniere}"}
        assert service.get("/account", headers=neuve).status_code == 200, (
            "la session la plus récente vit"
        )
