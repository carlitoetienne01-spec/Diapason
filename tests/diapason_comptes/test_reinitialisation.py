"""Réinitialisation : retardée, annulable, atomique, jamais automatique.

Conception : ``docs/development/compte-chiffre.md`` §3.6, D8, et étape 4
du §6 (« Réinitialisation »).
"""

from __future__ import annotations

import os

from diapason_comptes import jetons
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    HEURE_MS,
    JOUR_MS,
    amk_mdp,
    code_de,
    trousseau,
)


def _poser_des_donnees(service, account_id: str) -> None:
    """Deux objets et une pièce, comme l'étape 5 les poussera."""
    with service.ctx.base.transaction() as conn:
        for i in (1, 2):
            conn.execute(
                "INSERT INTO objets (compte_id, objet_id, rev, seq, blob) "
                "VALUES (?, ?, 1, ?, ?)",
                (account_id, f"obj{i}", i, os.urandom(1090)),
            )
        conn.execute(
            "INSERT INTO pieces (compte_id, piece_id, blob, reclame_seq) "
            "VALUES (?, ?, ?, 2)",
            (account_id, "piece1", os.urandom(4162)),
        )


def _poser_un_code(service, email: str, code: str) -> None:
    with service.ctx.base.transaction() as conn:
        index = service.secrets.index_courriel(email)
        jetons.enregistrer_code(
            conn, service.secrets, index, "reinitialisation", code, service.horloge()
        )


def _compter(service, table: str, account_id: str) -> int:
    with service.ctx.base.lecture() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE compte_id = ?", (account_id,)
        ).fetchone()[0]


def _demander(service, email: str, nombre: int) -> str:
    """Un code de réinitialisation ; ``nombre`` = rang du courriel attendu."""
    service.horloge.avancer(2 * HEURE_MS)
    r = service.post("/reset/request", {"email": email})
    assert r.status_code == 202, r.text
    return code_de(service.expediteur.attendre(email, "code_reinitialisation", nombre))


def _confirmer(service, email: str) -> int:
    code = _demander(service, email, 1)
    r = service.post("/reset/confirm", {"email": email, "code": code})
    assert r.status_code == 202, r.text
    return r.json()["effectiveAt"]


def _corps_complete(inscrit, code: str, nouvelle_auth: bytes) -> dict:
    return {
        "email": inscrit.email,
        "code": code,
        "kdfVersion": 1,
        "authKey": b64url(nouvelle_auth),
        "wrappedMasterKey": b64url(amk_mdp(inscrit.account_id)),
        "recovery": None,
        "keyring": b64url(trousseau(inscrit.account_id)),
    }


class TestDelai:
    def test_sept_jours_si_une_session_a_ete_vue_dans_les_trente_derniers_jours(
        self, service
    ):
        """D8 — un compte actif a un appareil qui affichera le bandeau et
        pourra annuler : on lui laisse une semaine."""
        inscrit = service.inscrire("actif@exemple.org")
        avant = service.horloge()
        effectif = _confirmer(service, inscrit.email)
        assert effectif - avant == 7 * JOUR_MS + 2 * HEURE_MS, "7 jours après confirm"

    def test_soixante_douze_heures_sans_session_recente(self, service):
        """D8 — sans appareil vu depuis 30 jours, personne ne peut annuler :
        72 h suffisent à qui a tout perdu."""
        inscrit = service.inscrire("inactif@exemple.org")
        service.horloge.avancer(31 * JOUR_MS)
        confirme_a = service.horloge() + 2 * HEURE_MS
        effectif = _confirmer(service, inscrit.email)
        assert effectif - confirme_a == 72 * HEURE_MS, "72 h après confirm"

    def test_l_attente_se_voit_partout_ou_le_compte_se_montre(self, service):
        """§3.6 — ``pendingResetAt`` dans ``/login`` et ``/account`` : c'est
        l'appareil connecté, pas le courriel, qui protège d'une boîte
        compromise (A3)."""
        inscrit = service.inscrire("visible@exemple.org")
        effectif = _confirmer(service, inscrit.email)
        assert service.connecter(inscrit).json()["pendingResetAt"] == effectif, "/login"
        compte = service.get("/account", headers=inscrit.bearer).json()
        assert compte["pendingResetAt"] == effectif, "/account"
        service.expediteur.attendre(inscrit.email, "reinitialisation_prevue")

    def test_confirmer_de_nouveau_ne_rapproche_pas_l_echeance(self, service):
        """§3.6 — une seconde confirmation, trois jours plus tard, ne relance
        pas un délai plus court que celui qui court déjà."""
        inscrit = service.inscrire("rapproche@exemple.org")
        effectif = _confirmer(service, inscrit.email)
        service.horloge.avancer(3 * JOUR_MS)
        _poser_un_code(service, inscrit.email, "535353")
        r = service.post("/reset/confirm", {"email": inscrit.email, "code": "535353"})
        assert r.status_code == 202, r.text
        assert r.json()["effectiveAt"] == effectif, "échéance inchangée"


class TestAnnulationEtEcheance:
    def test_annulable_depuis_n_importe_quelle_session(self, service):
        """§3.6 — ``reset/cancel`` depuis toute session : l'appareil qui voit
        le bandeau n'est pas forcément celui qui s'est connecté le premier."""
        inscrit = service.inscrire("annule@exemple.org")
        autre = service.connecter(inscrit).json()["sessionToken"]
        _confirmer(service, inscrit.email)
        r = service.post("/reset/cancel", headers={"Authorization": f"Bearer {autre}"})
        assert r.status_code == 200, r.text
        compte = service.get("/account", headers=inscrit.bearer).json()
        assert compte["pendingResetAt"] is None, "plus rien en attente"
        service.expediteur.attendre(inscrit.email, "reinitialisation_annulee")

    def test_complete_est_refuse_avant_l_echeance(self, service):
        """§3.6 — seulement après ``effectiveAt``."""
        inscrit = service.inscrire("tot@exemple.org")
        _confirmer(service, inscrit.email)
        # Pendant l'attente, reset/request n'envoie pas de code (il ne
        # servirait à rien) ; on pose un code comme le ferait un attaquant
        # qui a la boîte, pour vérifier que l'échéance, elle, tient.
        _poser_un_code(service, inscrit.email, "424242")
        r = service.post(
            "/reset/complete", _corps_complete(inscrit, "424242", os.urandom(32))
        )
        assert r.status_code == 409, "trop tôt"
        assert r.json() == {"error": {"code": "resetNotDue"}}

    def test_le_minuteur_n_efface_rien(self, service):
        """§3.6 — « le timer n'efface RIEN » : l'échéance passée, sans
        ``reset/complete``, les données et l'ancien mot de passe restent."""
        inscrit = service.inscrire("minuteur@exemple.org")
        _poser_des_donnees(service, inscrit.account_id)
        _confirmer(service, inscrit.email)
        service.horloge.avancer(8 * JOUR_MS)
        service.get("/health")
        assert service.connecter(inscrit).status_code == 200, (
            "l'ancien mot de passe vit"
        )
        assert _compter(service, "objets", inscrit.account_id) == 2, "objets intacts"
        assert _compter(service, "pieces", inscrit.account_id) == 1, "pièce intacte"


class TestReinitialisationComplete:
    def test_complete_efface_et_remplace_en_une_fois(self, service):
        """§3.6 — effacement des objets, des pièces et des sessions ; coffre
        neuf ; ``incarnation + 1`` ; ``keyEpoch = 1``."""
        inscrit = service.inscrire("complete@exemple.org")
        _poser_des_donnees(service, inscrit.account_id)
        _confirmer(service, inscrit.email)
        service.horloge.avancer(8 * JOUR_MS)
        code = _demander(service, inscrit.email, 2)
        nouvelle = os.urandom(32)
        r = service.post("/reset/complete", _corps_complete(inscrit, code, nouvelle))
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["incarnation"] == 2, "incarnation + 1"
        assert (corps["keyEpoch"], corps["vaultVersion"], corps["keyringVersion"]) == (
            1,
            1,
            1,
        ), "coffre neuf, comme à l'inscription"
        assert _compter(service, "objets", inscrit.account_id) == 0, "objets effacés"
        assert _compter(service, "pieces", inscrit.account_id) == 0, "pièces effacées"
        assert service.get("/account", headers=inscrit.bearer).status_code == 401, (
            "les anciennes sessions tombent"
        )
        assert service.connecter(inscrit).status_code == 401, (
            "l'ancien mot de passe aussi"
        )
        inscrit.auth_key = nouvelle
        connexion = service.connecter(inscrit).json()
        assert connexion["pendingResetAt"] is None, "plus rien en attente"
        assert connexion["recoveryConfigured"] is False, "recovery: null respecté"
        service.expediteur.attendre(inscrit.email, "reinitialisation_effectuee")

    def test_complete_est_atomique(self, fabrique):
        """§3.4 — « en une transaction » : une panne au milieu (ici, le
        journal qui refuse d'écrire) ne laisse ni objets effacés sous
        l'ancien coffre, ni coffre neuf sur des objets restés. La version
        précédente effaçait ailleurs et laissait cet état-là."""
        service = fabrique(raise_server_exceptions=False)
        inscrit = service.inscrire("atomique@exemple.org")
        _poser_des_donnees(service, inscrit.account_id)
        _confirmer(service, inscrit.email)
        service.horloge.avancer(8 * JOUR_MS)
        code = _demander(service, inscrit.email, 2)

        def refuser(*_a, **_k):
            raise OSError("disque plein simulé")

        service.ctx.journal.ligne_de_securite = refuser
        r = service.post(
            "/reset/complete", _corps_complete(inscrit, code, os.urandom(32))
        )
        assert r.status_code == 500, "la panne remonte"
        assert r.json() == {"error": {"code": "internal"}}, "sans écho de l'exception"
        assert _compter(service, "objets", inscrit.account_id) == 2, "objets intacts"
        assert _compter(service, "pieces", inscrit.account_id) == 1, "pièce intacte"
        assert service.get("/account", headers=inscrit.bearer).status_code == 200, (
            "les sessions sont intactes"
        )
        assert service.connecter(inscrit).json()["incarnation"] == 1, "même incarnation"
