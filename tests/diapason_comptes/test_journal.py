"""Journal d'événements, restauration logique, suppression définitive.

Conception : ``docs/development/compte-chiffre.md`` §3.3, §3.10 et étape 4
du §6 (« Journal et restauration »).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3

from diapason_comptes import journal
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import JOUR_MS, amk_mdp, trousseau


def _copier(chemin_base, destination) -> None:
    """Ce que ``sauvegarder.py`` fera (étape 7) : ``Connection.backup``."""
    source = sqlite3.connect(str(chemin_base))
    cible = sqlite3.connect(str(destination))
    try:
        source.backup(cible)
    finally:
        source.close()
        cible.close()


class TestRestauration:
    def test_restaurer_rejoue_le_journal(self, fabrique, tmp_path):
        """§3.10 — une copie d'hier, restaurée telle quelle, ramenait l'ancien
        mot de passe, la session d'un appareil perdu et un compte supprimé.
        Après rejeu : le jeton révoqué rend 401, l'ancien mot de passe est
        refusé, le compte supprimé ne revient pas."""
        service = fabrique()
        alice = service.inscrire("alice@exemple.org")
        bob = service.inscrire("bob@exemple.org")
        perdu = service.connecter(alice).json()["sessionToken"]
        with service.ctx.base.lecture() as conn:
            generation_avant = conn.execute(
                "SELECT valeur FROM meta WHERE cle = 'generation'"
            ).fetchone()[0]
        copie = tmp_path / "copie-d-hier.db"
        _copier(service.configuration.chemin_base, copie)

        # Après la copie : Alice change de mot de passe (le perdu tombe),
        # Bob supprime son compte.
        nouvelle = os.urandom(32)
        r = service.post(
            "/vault/commit",
            service.corps_commit(alice, nouvelle_auth=nouvelle),
            headers=alice.bearer,
        )
        assert r.status_code == 200, r.text
        r = service.post(
            "/account/delete", {"authKey": b64url(bob.auth_key)}, headers=bob.bearer
        )
        assert r.status_code == 204, r.text
        seq_avant = service.get("/health").json()["globalSeq"]
        service.ctx.fermer()

        rapport = journal.restaurer(
            copie,
            service.configuration.chemin_base,
            service.configuration.chemin_journal,
            service.secrets,
        )
        assert rapport.appliques >= 2, "le coffre et la suppression rejoués"

        restaure = fabrique(secrets=service.secrets, horloge=service.horloge)
        vieux = {"Authorization": f"Bearer {perdu}"}
        assert restaure.get("/account", headers=vieux).status_code == 401, (
            "le jeton de l'appareil perdu reste révoqué"
        )
        assert restaure.connecter(alice).status_code == 401, (
            "l'ancien mot de passe d'Alice est refusé"
        )
        alice.auth_key = nouvelle
        assert restaure.connecter(alice).status_code == 200, "le mot de passe courant"
        assert restaure.connecter(bob).status_code == 401, "Bob ne revient pas"
        sante = restaure.get("/health").json()
        assert sante["generation"] != generation_avant, "generation nouvelle"
        assert sante["globalSeq"] > seq_avant, (
            "globalSeq ne recule pas : un recul ferait croire à un retour arrière "
            "de toute la machine"
        )

    def test_un_evenement_anterieur_a_la_copie_n_est_pas_rejoue(
        self, fabrique, tmp_path
    ):
        """§3.10 — le rejeu se règle sur ``(incarnation, vaultVersion)`` : un
        ``vault/commit`` déjà présent dans la copie ne la fait pas reculer."""
        service = fabrique()
        alice = service.inscrire("avant@exemple.org")
        r = service.post(
            "/vault/commit", service.corps_commit(alice), headers=alice.bearer
        )
        assert r.status_code == 200, r.text
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        service.ctx.fermer()
        rapport = journal.restaurer(
            copie,
            service.configuration.chemin_base,
            service.configuration.chemin_journal,
            service.secrets,
        )
        assert rapport.appliques == 0, "rien de plus récent que la copie"
        restaure = fabrique(secrets=service.secrets, horloge=service.horloge)
        assert restaure.connecter(alice).json()["vaultVersion"] == 2, "coffre inchangé"

    def test_le_journal_ne_porte_ni_adresse_ni_enveloppe_en_clair(self, service):
        """§3.3 — le journal sort de la base : sur-chiffré par ``CLE_REPOS``,
        sinon il serait la fuite que le poivre empêche ailleurs (A2)."""
        inscrit = service.inscrire("canari@exemple.org")
        brut = service.configuration.chemin_journal.read_bytes()
        assert b"canari" not in brut, "aucune adresse dans le journal"
        for secret in (inscrit.wrapped, inscrit.keyring, inscrit.sealed):
            assert secret not in brut, "aucune enveloppe en clair"
            assert b64url(secret).encode() not in brut, "ni en base64"
        entree = json.loads(brut.splitlines()[0])
        assert entree["type"] == "accountCreated", "l'inscription est journalisée"

    def test_tronquer_garde_les_entrees_recentes(self, service):
        """§3.3 — tronqué à « dernière sauvegarde valide moins 1 jour »."""
        service.inscrire("vieux@exemple.org")
        service.horloge.avancer(3 * JOUR_MS)
        service.inscrire("recent@exemple.org")
        chemin = service.configuration.chemin_journal
        retires = journal.tronquer(chemin, service.horloge() - JOUR_MS)
        assert retires == 1, "l'entrée de trois jours part"
        assert len(list(journal.lire(chemin))) == 1, "la récente reste"


class TestSuppression:
    def test_la_suppression_efface_en_cascade_et_jusqu_aux_octets(self, service):
        """P8 — effacement immédiat : objets, pièces et sessions partent avec
        le compte (``ON DELETE CASCADE``), et ``secure_delete`` plus un point
        de contrôle ôtent jusqu'aux octets de la base et du WAL."""
        inscrit = service.inscrire("efface@exemple.org")
        with service.ctx.base.transaction() as conn:
            conn.execute(
                "INSERT INTO objets (compte_id, objet_id, rev, seq, blob) "
                "VALUES (?, 'o', 1, 1, ?)",
                (inscrit.account_id, b"CANARI-OBJET" * 90),
            )
            conn.execute(
                "INSERT INTO pieces (compte_id, piece_id, blob, reclame_seq) "
                "VALUES (?, 'p', ?, 1)",
                (inscrit.account_id, b"CANARI-PIECE" * 340),
            )
            (courriel_chiffre, verif) = conn.execute(
                "SELECT courriel_chiffre, verif_auth FROM comptes"
            ).fetchone()
        r = service.post(
            "/account/delete",
            {"authKey": b64url(inscrit.auth_key)},
            headers=inscrit.bearer,
        )
        assert r.status_code == 204, r.text
        with service.ctx.base.lecture() as conn:
            for table in ("comptes", "sessions", "objets", "pieces"):
                (n,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                assert n == 0, f"{table} vidée par la cascade"
        octets = service.octets_sur_disque()
        for trace in (b"CANARI-OBJET", b"CANARI-PIECE", courriel_chiffre, verif):
            assert trace not in octets, "rien ne reste dans les pages ni le WAL"
        service.expediteur.attendre(inscrit.email, "compte_supprime")


def _restaurer(fabrique, service, copie):
    service.ctx.fermer()
    journal.restaurer(
        copie,
        service.configuration.chemin_base,
        service.configuration.chemin_journal,
        service.secrets,
    )
    return fabrique(secrets=service.secrets, horloge=service.horloge)


def _confirmer_une_reinitialisation(service, email: str) -> int:
    from diapason_comptes import jetons

    with service.ctx.base.transaction() as conn:
        jetons.enregistrer_code(
            conn,
            service.secrets,
            service.secrets.index_courriel(email),
            "reinitialisation",
            "717171",
            service.horloge(),
        )
    r = service.post("/reset/confirm", {"email": email, "code": "717171"})
    assert r.status_code == 202, r.text
    return r.json()["effectiveAt"]


class TestRestaurationDesReinitialisations:
    """§3.6, §3.10 — « annulable » ne doit pas tomber à la première
    restauration. Jusqu'au 24/09/2026, ni ``reset/confirm`` ni
    ``reset/cancel`` n'étaient journalisés, et le rejeu d'un
    ``vaultCommit`` réécrivait ``reinit_*`` à leur valeur du moment : une
    réinitialisation annulée revenait, déjà échue, et celui qui tient la
    boîte (A3) n'avait plus qu'à la compléter."""

    def test_une_annulation_posterieure_a_la_copie_survit(self, fabrique, tmp_path):
        """Confirmation, copie, annulation, restauration : rien en attente."""
        service = fabrique()
        alice = service.inscrire("annulee@exemple.org")
        _confirmer_une_reinitialisation(service, alice.email)
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        r = service.post("/reset/cancel", headers=alice.bearer)
        assert r.status_code == 200, r.text
        restaure = _restaurer(fabrique, service, copie)
        connexion = restaure.connecter(alice).json()
        assert connexion["pendingResetAt"] is None, (
            "l'annulation faite après la copie tient après la restauration"
        )

    def test_un_coffre_rejoue_ne_ressuscite_pas_une_attente_annulee(
        self, fabrique, tmp_path
    ):
        """Copie, confirmation par l'attaquant, changement de mot de passe
        (journalisé), annulation, restauration : rien en attente."""
        service = fabrique()
        alice = service.inscrire("rejouee@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        _confirmer_une_reinitialisation(service, alice.email)
        nouvelle = os.urandom(32)
        r = service.post(
            "/vault/commit",
            service.corps_commit(alice, nouvelle_auth=nouvelle),
            headers=alice.bearer,
        )
        assert r.status_code == 200, r.text
        neuf = {"Authorization": f"Bearer {r.json()['sessionToken']}"}
        assert service.post("/reset/cancel", headers=neuf).status_code == 200
        restaure = _restaurer(fabrique, service, copie)
        alice.auth_key = nouvelle
        connexion = restaure.connecter(alice).json()
        assert connexion["pendingResetAt"] is None, (
            "le rejeu du coffre ne remet pas l'attente annulée"
        )

    def test_une_attente_d_avant_reset_complete_ne_revient_pas(
        self, fabrique, tmp_path
    ):
        """``resetScheduled`` ne vaut que pour SON incarnation : rejouée sur
        le compte neuf d'après ``reset/complete``, elle y poserait une
        attente que personne n'a demandée."""
        service = fabrique()
        alice = service.inscrire("incarnation@exemple.org")
        _confirmer_une_reinitialisation(service, alice.email)
        service.horloge.avancer(8 * JOUR_MS)
        nouvelle = os.urandom(32)
        with service.ctx.base.transaction() as conn:
            from diapason_comptes import jetons

            jetons.enregistrer_code(
                conn,
                service.secrets,
                service.secrets.index_courriel(alice.email),
                "reinitialisation",
                "727272",
                service.horloge(),
            )
        r = service.post(
            "/reset/complete",
            {
                "email": alice.email,
                "code": "727272",
                "kdfVersion": 1,
                "authKey": b64url(nouvelle),
                "wrappedMasterKey": b64url(amk_mdp(alice.account_id)),
                "recovery": None,
                "keyring": b64url(trousseau(alice.account_id)),
            },
        )
        assert r.status_code == 200, r.text
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        restaure = _restaurer(fabrique, service, copie)
        alice.auth_key = nouvelle
        connexion = restaure.connecter(alice).json()
        assert connexion["incarnation"] == 2, "le compte neuf"
        assert connexion["pendingResetAt"] is None, (
            "l'attente de l'incarnation 1 ne revient pas sur la 2"
        )

    def test_une_confirmation_posterieure_a_la_copie_revient(self, fabrique, tmp_path):
        """L'inverse : une attente VIVANTE au moment de la perte revient, pour
        que l'appareil connecté la voie encore et puisse l'annuler."""
        service = fabrique()
        alice = service.inscrire("vivante@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        effectif = _confirmer_une_reinitialisation(service, alice.email)
        restaure = _restaurer(fabrique, service, copie)
        assert restaure.connecter(alice).json()["pendingResetAt"] == effectif, (
            "l'attente en cours est rejouée"
        )


class TestTransactionAnnulee:
    """§3.3 — le journal est écrit DANS la transaction, avant le ``COMMIT``.
    Jusqu'au 24/09/2026, un ``COMMIT`` refusé (disque plein) laissait au
    journal un coffre que le client n'avait jamais vu accepté : une
    restauration en faisait le seul mot de passe valide."""

    def test_un_commit_refuse_n_est_pas_rejoue(self, fabrique, tmp_path):
        service = fabrique(raise_server_exceptions=False)
        alice = service.inscrire("refuse@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)

        vraie = service.ctx.base._conn

        class CommitRefuse:
            def execute(self, sql, *args):
                if sql == "COMMIT":
                    raise sqlite3.OperationalError("database or disk is full")
                return vraie.execute(sql, *args)

            def __getattr__(self, nom):
                return getattr(vraie, nom)

        service.ctx.base._conn = CommitRefuse()
        nouvelle = os.urandom(32)
        r = service.post(
            "/vault/commit",
            service.corps_commit(alice, nouvelle_auth=nouvelle),
            headers=alice.bearer,
        )
        service.ctx.base._conn = vraie
        assert r.status_code == 500, "le COMMIT refusé remonte"
        assert service.connecter(alice).status_code == 200, "l'ancien mot de passe vit"

        restaure = _restaurer(fabrique, service, copie)
        assert restaure.connecter(alice).status_code == 200, (
            "après restauration, l'ancien mot de passe vaut toujours"
        )
        alice.auth_key = nouvelle
        assert restaure.connecter(alice).status_code == 401, (
            "le coffre refusé n'est pas ressuscité par le rejeu"
        )


class TestOubliALaSuppression:
    """§3.3, P8 — le journal ne garde d'un compte supprimé que l'index HMAC.
    Jusqu'au 24/09/2026, ses lignes ``accountCreated`` et ``vaultCommit``
    gardaient l'adresse, scellée sous ``CLE_REPOS`` — sur le même disque —
    tant qu'aucune sauvegarde réussie ne tronquait le journal."""

    def test_l_adresse_d_un_compte_supprime_ne_se_dechiffre_plus(self, service):
        gil = service.inscrire("gil@exemple.org")
        r = service.post("/vault/commit", service.corps_commit(gil), headers=gil.bearer)
        assert r.status_code == 200, r.text
        neuf = {"Authorization": f"Bearer {r.json()['sessionToken']}"}
        r = service.post(
            "/account/delete", {"authKey": b64url(gil.auth_key)}, headers=neuf
        )
        assert r.status_code == 204, r.text
        entrees = [
            e
            for e in journal.lire(service.configuration.chemin_journal)
            if e.get("accountId") == gil.account_id
        ]
        assert [e["type"] for e in entrees] == ["accountDeleted"], (
            "seule la suppression reste au journal"
        )
        assert "row" not in entrees[0], "aucune ligne scellée ne reste"

    def test_la_restauration_ne_ramene_pas_le_compte_oublie(self, fabrique, tmp_path):
        """L'oubli ne défait pas la restauration : copie d'avant
        l'inscription ou d'avant la suppression, le compte ne revient pas."""
        service = fabrique()
        avant = tmp_path / "avant.db"
        _copier(service.configuration.chemin_base, avant)
        gil = service.inscrire("gil2@exemple.org")
        pendant = tmp_path / "pendant.db"
        _copier(service.configuration.chemin_base, pendant)
        r = service.post(
            "/account/delete", {"authKey": b64url(gil.auth_key)}, headers=gil.bearer
        )
        assert r.status_code == 204, r.text
        service.ctx.fermer()
        for copie in (avant, pendant):
            journal.restaurer(
                copie,
                service.configuration.chemin_base,
                service.configuration.chemin_journal,
                service.secrets,
            )
            with sqlite3.connect(str(service.configuration.chemin_base)) as conn:
                (n,) = conn.execute("SELECT COUNT(*) FROM comptes").fetchone()
            assert n == 0, f"le compte supprimé ne revient pas depuis {copie.name}"


class TestRejeuDesRevocations:
    def test_seule_la_session_revoquee_disparait(self, service):
        """§3.3 — une entrée ``sessionRevoked`` retire CE haché-là. La
        restauration vide ensuite toutes les sessions (§3.10, étape 3), ce
        qui masquait un rejeu qui n'aurait rien retiré."""
        alice = service.inscrire("revoc@exemple.org")
        autre = service.connecter(alice).json()["sessionToken"]
        with service.ctx.base.transaction() as conn:
            applique = journal._rejouer(
                conn,
                {
                    "type": journal.REVOCATION,
                    "accountId": alice.account_id,
                    "sessionHashes": [hashlib.sha256(autre.encode()).hexdigest()],
                },
                service.secrets,
            )
        assert applique, "l'entrée de révocation s'applique"
        vieux = {"Authorization": f"Bearer {autre}"}
        assert service.get("/account", headers=vieux).status_code == 401, (
            "la session révoquée disparaît"
        )
        assert service.get("/account", headers=alice.bearer).status_code == 200, (
            "l'autre session reste"
        )
