"""Inscription, connexion, compte : le parcours nominal et ses refus.

Conception : ``docs/development/compte-chiffre.md`` §3.4, §3.5 et §3.7.
"""

from __future__ import annotations

import base64

from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    HEURE_MS,
    amk_mdp,
    code_de,
    nom_appareil,
    trousseau,
)


def _octets(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


class TestInscription:
    def test_le_compte_n_existe_qu_apres_complete(self, service):
        """P2 — un code interrompu ne laisse rien sur le VPS : une ligne créée
        à ``verify`` serait un compte sans coffre, inouvrable."""
        email = "p2@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        r = service.post("/signup/verify", {"email": email, "code": code})
        assert r.status_code == 200, r.text
        with service.ctx.base.lecture() as conn:
            nombre = conn.execute("SELECT COUNT(*) FROM comptes").fetchone()[0]
        assert nombre == 0, "aucun compte avant signup/complete"

    def test_le_parcours_complet_rend_une_session_et_le_coffre_a_la_connexion(
        self, service
    ):
        """§3.4 — ``/login`` rend exactement les enveloppes envoyées à
        l'inscription : c'est elles que l'appareil suivant ouvrira."""
        inscrit = service.inscrire("nominal@exemple.org")
        r = service.connecter(inscrit)
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["accountId"] == inscrit.account_id, "même compte"
        assert _octets(corps["wrappedMasterKey"]) == inscrit.wrapped, "enveloppe AMK"
        assert _octets(corps["keyring"]) == inscrit.keyring, "trousseau"
        assert corps["recoveryConfigured"] is True, "clé de récupération configurée"
        assert corps["pendingResetAt"] is None, "aucune réinitialisation en attente"
        assert (corps["vaultVersion"], corps["keyringVersion"], corps["keyEpoch"]) == (
            1,
            1,
            1,
        ), "versions de naissance"
        assert corps["incarnation"] == 1, "première incarnation"

    def test_un_jeton_d_inscription_ne_sert_qu_une_fois(self, service):
        """§3.3 — consommation atomique : rejouer ``complete`` avec le même
        jeton ne crée pas un second compte ni une seconde session."""
        email = "rejeu@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        verifie = service.post("/signup/verify", {"email": email, "code": code}).json()
        corps = {
            "signupToken": verifie["signupToken"],
            "kdfVersion": 1,
            "authKey": b64url(bytes(32)),
            "wrappedMasterKey": b64url(amk_mdp(verifie["accountId"])),
            "recovery": None,
            "keyring": b64url(trousseau(verifie["accountId"])),
        }
        assert service.post("/signup/complete", corps).status_code == 201
        second = service.post("/signup/complete", corps)
        assert second.status_code == 400, "un jeton consommé est refusé"
        assert second.json() == {"error": {"code": "invalidToken"}}

    def test_une_kdf_version_sous_le_plancher_est_refusee(self, service):
        """§2.3 — un coffre stocké en ``kdfVersion`` 0 serait refusé par le
        client comme un déclassement : le compte serait inouvrable."""
        email = "kdf@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        verifie = service.post("/signup/verify", {"email": email, "code": code}).json()
        r = service.post(
            "/signup/complete",
            {
                "signupToken": verifie["signupToken"],
                "kdfVersion": 0,
                "authKey": b64url(bytes(32)),
                "wrappedMasterKey": b64url(amk_mdp(verifie["accountId"])),
                "recovery": None,
                "keyring": b64url(trousseau(verifie["accountId"])),
            },
        )
        assert r.status_code == 400, "kdfVersion 0 refusée"
        assert r.json()["error"]["code"] == "kdfDowngrade", "code du client (§2.3)"

    def test_inscriptions_fermees_rendent_503_signup_closed(self, fabrique):
        """§3.5 — le service est déployé FERMÉ (étape 7) : ``signupClosed``
        est global, il ne dit rien d'une adresse."""
        service = fabrique(inscriptions=False)
        r = service.post("/signup/start", {"email": "a@exemple.org", "termsVersion": 1})
        assert r.status_code == 503, "inscriptions fermées"
        assert r.json() == {"error": {"code": "signupClosed"}}

    def test_la_garde_disque_refuse_la_creation_en_507(self, fabrique):
        """§3.5, D10 — moins de 20 Go libres sur « / » : Flashprime partage
        ce disque, et un disque plein serait sa panne."""
        service = fabrique(espace_libre=lambda _chemin: 19 * 10**9)
        email = "plein@exemple.org"
        service.post("/signup/start", {"email": email, "termsVersion": 1})
        code = code_de(service.expediteur.attendre(email, "code_inscription"))
        verifie = service.post("/signup/verify", {"email": email, "code": code}).json()
        r = service.post(
            "/signup/complete",
            {
                "signupToken": verifie["signupToken"],
                "kdfVersion": 1,
                "authKey": b64url(bytes(32)),
                "wrappedMasterKey": b64url(amk_mdp(verifie["accountId"])),
                "recovery": None,
                "keyring": b64url(trousseau(verifie["accountId"])),
            },
        )
        assert r.status_code == 507, "garde des 20 Go libres"
        assert r.json() == {"error": {"code": "serverFull"}}


class TestCompteEtSessions:
    def test_get_account_rend_l_adresse_et_jamais_d_enveloppe(self, service):
        """§3.4, §3.7 — une session seule lit les métadonnées, jamais
        l'enveloppe AMK ni le trousseau."""
        inscrit = service.inscrire("compte@exemple.org")
        r = service.get("/account", headers=inscrit.bearer)
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["email"] == "compte@exemple.org", "adresse déchiffrée"
        assert corps["quotaBytes"] == 256 * 1024 * 1024, "256 Mio (D10)"
        for cle in ("wrappedMasterKey", "keyring", "sealedMasterKey"):
            assert cle not in corps, f"{cle} ne sort jamais par /account"

    def test_le_nom_chiffre_d_une_session_est_range_et_liste(self, service):
        """§3.4 — ``PUT /sessions/current`` range un nom d'appareil scellé
        (type 04) que le serveur ne lit pas."""
        inscrit = service.inscrire("nom@exemple.org")
        nom = nom_appareil(inscrit.account_id, inscrit.session_id)
        r = service.client.put(
            "/api/v1/sessions/current",
            json={"encryptedName": b64url(nom)},
            headers=inscrit.bearer,
        )
        assert r.status_code == 204, r.text
        sessions = service.get("/sessions", headers=inscrit.bearer).json()["sessions"]
        assert len(sessions) == 1, "une seule session"
        assert _octets(sessions[0]["encryptedName"]) == nom, "nom rendu tel quel"
        assert sessions[0]["current"] is True, "la session courante est marquée"

    def test_une_adresse_deja_prise_recoit_compte_existant_une_fois_par_jour(
        self, service
    ):
        """§3.4 — « un compte existe déjà », au plus une fois par jour : sans
        ce plafond, ``signup/start`` servait à inonder une boîte."""
        inscrit = service.inscrire("pris@exemple.org")
        for _ in range(3):
            service.horloge.avancer(2 * HEURE_MS)
            service.post("/signup/start", {"email": inscrit.email, "termsVersion": 1})
        service.expediteur.attendre(inscrit.email, "compte_existant")
        service.ctx.courrier.file.arreter()
        assert (
            len(service.expediteur.messages(inscrit.email, "compte_existant")) == 1
        ), "un seul « compte existant » dans la journée"
