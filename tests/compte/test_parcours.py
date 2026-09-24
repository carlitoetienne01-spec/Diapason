"""Le compte local de bout en bout : parcours P1 à P8 contre le vrai service.

Conception : ``docs/development/compte-chiffre.md`` §3.11 (parcours), §3.7
(sessions), §2.8 (rotation), §2.11 bis, §4.4, §4.12, §6 bis, et la liste
des tests de l'étape 8 du §6.

Chaque appareil est un ``ServiceCompte`` avec son propre dossier ``compte/``
jetable ; le serveur est ``diapason_comptes`` en mémoire, joint par un
``httpx.MockTransport`` (``tests/compte/_banc.py``). Aucun envoi réseau
réel, aucun trousseau réel, aucun ``~/.diapason``.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from diapason.compte import cles
from diapason.compte.cles import DeclassementKdf, ErreurCompte
from diapason.compte.enveloppe import CleServeurPerimee
from diapason.compte.etat import RetourArriereServeur
from diapason.compte.gardien import ELEMENT_AMK, ELEMENT_SESSION
from diapason.compte.recuperation import CleRecuperationInvalide, lire_cle_recuperation
from diapason.compte.serrure import CompteVerrouille, TropDEssais
from diapason.compte.service import (
    ETATS,
    EtatRefuse,
    ExtraitFaux,
    MotDePasseFaux,
    SessionExpiree,
    _verifier_extrait,
)
from diapason.compte.transport import (
    VARIABLE_SURCHARGE,
    CompteInactif,
    ErreurServeur,
    ServeurInjoignable,
)
from diapason.core import local_mode
from tests.compte._banc import (
    EMAIL,
    MDP,
    MDP_2,
    MDP_3,
    Mono,
    ProtecteurPersistant,
    Vps,
    appareil,
    argon_rapide,
    extrait,
    formes,
    inscrire,
    reponse_json,
)
from tests.diapason_comptes._outils import JOUR_MS


@pytest.fixture(autouse=True)
def _argon(monkeypatch):
    argon_rapide(monkeypatch)


@pytest.fixture
def vps(tmp_path):
    serveur = Vps(tmp_path / "vps")
    yield serveur
    serveur.fermer()


@pytest.fixture
def fabrique(tmp_path, vps):
    crees = []

    def construire(nom: str = "a", **arguments):
        service = appareil(vps, tmp_path / nom, nom=f"Appareil {nom}", **arguments)
        crees.append(service)
        return service

    yield construire
    for service in crees:
        service.fermer()


def _comptes_sur_le_vps(vps: Vps) -> int:
    with vps.ctx.base.lecture() as conn:
        return conn.execute("SELECT COUNT(*) FROM comptes").fetchone()[0]


def _epoque(service) -> int:
    return service.serrure.exiger().trousseau.current_epoch


# ----------------------------------------------------------------------
# P1 — inscription
# ----------------------------------------------------------------------


class TestP1Inscription:
    """§3.11 P1 : adresse, code, mot de passe, clé de récupération."""

    def test_l_inscription_ouvre_l_appareil_avec_une_cle_confirmee(self, fabrique, vps):
        """P1 étapes 1 à 4 : chaque étape change l'état que les vues lisent."""
        a = fabrique()
        assert a.statut()["state"] == "none"
        a.inscription_debut(EMAIL, True)
        assert a.statut()["state"] == "signupInProgress"
        a.inscription_code(vps.code(EMAIL, "code_inscription", 1))
        rendu = a.inscription_preparer(MDP, False)
        assert len(rendu["recoveryKey"]) == 39, "32 caractères en 8 groupes de 4"
        assert len(set(rendu["confirmGroups"])) == 2
        a.inscription_terminer(extrait(rendu), None)
        statut = a.statut()
        assert statut["state"] == "unlocked", "l'appareil doit être ouvert après P1"
        assert statut["recoveryConfigured"] is True
        assert statut["backupMeans"] == {"recoveryKey": True, "rememberedDevices": 0}
        assert statut["email"] == EMAIL
        assert _comptes_sur_le_vps(vps) == 1

    def test_continuer_sans_cle_laisse_zero_moyen_de_secours(self, fabrique, vps):
        """D4 : on peut continuer sans clé ; les Réglages doivent alors
        afficher « 0 moyen de secours » — le statut ne doit rien inventer."""
        a = fabrique()
        assert inscrire(a, vps, avec_cle=False) is None
        statut = a.statut()
        assert statut["recoveryConfigured"] is False
        assert statut["backupMeans"] == {
            "recoveryKey": False,
            "rememberedDevices": 0,
        }, "sans clé ni mémorisation, aucun moyen de secours n'existe"

    def test_un_extrait_faux_ne_cree_rien_sur_le_serveur(self, fabrique, vps):
        """§2.7 preuve de sauvegarde : une clé mal notée ne doit pas devenir
        la seule issue d'un compte."""
        a = fabrique()
        a.inscription_debut(EMAIL, True)
        a.inscription_code(vps.code(EMAIL, "code_inscription", 1))
        rendu = a.inscription_preparer(MDP, False)
        with pytest.raises(ExtraitFaux):
            a.inscription_terminer(["0000", "0000"], None)
        assert _comptes_sur_le_vps(vps) == 0, "un extrait faux a créé le compte"
        a.inscription_terminer(extrait(rendu), None)
        assert _comptes_sur_le_vps(vps) == 1

    def test_la_memorisation_est_refusee_sans_protecteur_persistant(
        self, fabrique, vps
    ):
        """D7 : la case est grisée quand ``rememberAllowed`` est faux ; la
        route refuse aussi, et dit pourquoi (§5 du cahier)."""
        a = fabrique()
        a.inscription_debut(EMAIL, True)
        a.inscription_code(vps.code(EMAIL, "code_inscription", 1))
        with pytest.raises(EtatRefuse) as refus:
            a.inscription_preparer(MDP, True)
        assert refus.value.code == "rememberNotAllowed"
        assert refus.value.raison == "noPersistentProtector"
        assert a.statut()["rememberAllowed"] is False

    def test_un_mot_de_passe_court_est_refuse_avant_tout_calcul(self, fabrique, vps):
        """D5 : 12 caractères au moins, jugés avant Argon2id et avant le
        réseau."""
        a = fabrique()
        a.inscription_debut(EMAIL, True)
        a.inscription_code(vps.code(EMAIL, "code_inscription", 1))
        with pytest.raises(cles.MotDePasseRefuse) as refus:
            a.inscription_preparer("court", False)
        assert refus.value.code == "passwordTooShort"


# ----------------------------------------------------------------------
# P2 — code interrompu
# ----------------------------------------------------------------------


class TestP2CodeInterrompu:
    def test_rien_n_existe_sur_le_serveur_avant_complete(self, fabrique, vps):
        """§3.11 P2 : « Rien n'existe sur le VPS avant signup/complete. On
        recommence à l'étape du code. »"""
        a = fabrique()
        a.inscription_debut(EMAIL, True)
        a.inscription_code(vps.code(EMAIL, "code_inscription", 1))
        a.inscription_preparer(MDP, False)
        assert _comptes_sur_le_vps(vps) == 0
        # On recommence : un nouveau départ remplace l'inscription en cours.
        assert inscrire(a, vps) is not None
        assert _comptes_sur_le_vps(vps) == 1

    def test_un_code_faux_est_refuse(self, fabrique, vps):
        a = fabrique()
        a.inscription_debut(EMAIL, True)
        vps.code(EMAIL, "code_inscription", 1)
        with pytest.raises(ErreurServeur) as refus:
            a.inscription_code("000000")
        assert refus.value.code == "invalidCode"

    def test_la_cle_montree_ne_survit_pas_trente_minutes(self, fabrique, vps):
        """§2.7 : ``R`` vit en mémoire entre préparer et terminer, 30 min au
        plus — au-delà, un onglet oublié la laisserait dans le processus."""
        mono = Mono()
        a = fabrique(mono=mono)
        a.inscription_debut(EMAIL, True)
        a.inscription_code(vps.code(EMAIL, "code_inscription", 1))
        rendu = a.inscription_preparer(MDP, False)
        mono.avancer(30 * 60 + 1)
        with pytest.raises(EtatRefuse) as refus:
            a.inscription_terminer(extrait(rendu), None)
        assert refus.value.code == "noPendingSignup"
        assert a.statut()["state"] == "none"


# ----------------------------------------------------------------------
# P3 — second appareil ; déverrouillage
# ----------------------------------------------------------------------


class TestP3SecondAppareil:
    def test_un_second_appareil_se_connecte_et_s_ouvre(self, fabrique, vps):
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        assert b.statut()["state"] == "unlocked"
        assert _epoque(b) == _epoque(a) == 1
        assert (
            b.serrure.exiger().trousseau.id_key == a.serrure.exiger().trousseau.id_key
        ), "deux appareils du même compte doivent nommer pareil les objets"

    def test_des_conversations_locales_demandent_le_consentement(self, fabrique, vps):
        """§3.11 P3 : « Cet appareil a déjà 3 conversations. […] [Ajouter] »."""
        inscrire(fabrique("a"), vps)
        b = fabrique("b", compter=lambda: 3)
        b.connecter(EMAIL, MDP, False)
        statut = b.statut()
        assert statut["localConversations"] == 3
        assert statut["sync"]["state"] == "needsConsent"
        b.consentir()
        assert b.statut()["sync"]["state"] == "disabled", (
            "sans moteur (étape 8), la synchronisation se dit désactivée, "
            "jamais « à jour »"
        )

    def test_un_mauvais_mot_de_passe_rend_invalid_credentials(self, fabrique, vps):
        inscrire(fabrique("a"), vps)
        b = fabrique("b")
        with pytest.raises(ErreurServeur) as refus:
            b.connecter(EMAIL, MDP_2, False)
        assert refus.value.code == "invalidCredentials"
        assert getattr(refus.value, "raison", None) is None, (
            "une simple faute de frappe ne doit pas évoquer un changement ailleurs"
        )
        assert b.statut()["state"] == "none"

    def test_une_session_expiree_se_rouvre_sans_verrouiller_d_abord(
        self, fabrique, vps
    ):
        """§3.7 : après 90 jours sans contact, ``sessionExpired`` redemande le
        mot de passe sans rien effacer — la serrure reste ouverte, et la
        reconnexion ne doit pas buter sur « déjà déverrouillé »."""
        a = fabrique("a")
        inscrire(a, vps)
        vps.horloge.avancer(91 * JOUR_MS)
        with pytest.raises(SessionExpiree):
            a.appareils()
        assert a.statut()["state"] == "sessionExpired"
        assert a.etat.enveloppe_locale() is not None, (
            "une simple expiration ne doit pas effacer l'enveloppe locale"
        )
        a.connecter(EMAIL, MDP, False)
        assert a.statut()["state"] == "unlocked"
        assert a.appareils(), "la session neuve doit servir"

    def test_la_memorisation_rouvre_l_appareil_au_lancement_suivant(
        self, fabrique, vps, tmp_path
    ):
        """§2.11 « Redémarrage » : le serveur relit lui-même l'AMK mémorisée ;
        verrouiller l'oublie, sinon le voyant mentirait au lancement suivant."""
        protecteur = ProtecteurPersistant()
        a = fabrique("a", protecteur=protecteur)
        inscrire(a, vps, remember=True)
        assert a.statut()["remembered"] is True
        a.fermer()
        relance = appareil(vps, tmp_path / "a", protecteur=protecteur)
        assert relance.statut()["state"] == "unlocked", "l'AMK mémorisée n'a pas servi"
        relance.verrouiller()
        relance.fermer()
        encore = appareil(vps, tmp_path / "a", protecteur=protecteur)
        assert encore.statut()["state"] == "locked", (
            "un appareil verrouillé s'est rouvert seul au lancement"
        )
        encore.fermer()


class TestDeverrouillage:
    def test_le_deverrouillage_se_fait_hors_ligne(self, fabrique, vps):
        """§2.10 : l'enveloppe locale ouvre l'appareil sans le serveur."""
        a = fabrique()
        inscrire(a, vps)
        a.verrouiller()
        assert a.statut()["state"] == "locked"
        avant = len(vps.requetes)
        a.deverrouiller(MDP)
        assert a.statut()["state"] == "unlocked"
        assert len(vps.requetes) == avant, "le déverrouillage a joint le serveur"

    def test_cinq_essais_puis_trente_secondes(self, fabrique, vps):
        """§3.8 : ``unlock`` est strict — 5 essais, puis 30 s d'attente. Sans
        elle, un programme de la session essaierait 120 mots de passe par
        minute contre l'enveloppe locale."""
        mono = Mono()
        a = fabrique(mono=mono)
        inscrire(a, vps)
        a.verrouiller()
        for _ in range(5):
            with pytest.raises(MotDePasseFaux):
                a.deverrouiller(MDP_2)
        with pytest.raises(TropDEssais) as refus:
            a.deverrouiller(MDP)
        assert refus.value.retry_after_s == 30, "l'attente doit être de 30 s"
        assert a.statut()["state"] == "locked", (
            "le bon mot de passe est passé en attente"
        )
        mono.avancer(30)
        a.deverrouiller(MDP)
        assert a.statut()["state"] == "unlocked"


# ----------------------------------------------------------------------
# Chaque rotation
# ----------------------------------------------------------------------


def _rotation(nom: str, a, b, vps, fabrique, cle: str) -> object:
    """Joue une rotation ; rend l'appareil qui l'a faite."""
    if nom == "password":
        a.changer_mot_de_passe(MDP, MDP_2)
    elif nom == "forgottenHere":
        vps.plus_tard()
        avant = vps.nombre(EMAIL, "code_coffre")
        a.code_oubli_ici()
        a.oubli_ici(vps.code(EMAIL, "code_coffre", avant + 1), MDP_2)
    elif nom == "recoveryKeyReplace":
        rendu = a.nouvelle_cle_preparer(MDP)
        a.nouvelle_cle_confirmer(extrait(rendu))
    elif nom == "recoveryKeyRemove":
        a.retirer_cle(MDP)
    elif nom == "disconnectOther":
        a.deconnecter_appareil(b.etat.lire("sessionId"), MDP)
    elif nom == "recover":
        c = fabrique("c")
        c.recuperer(EMAIL, cle, MDP_3, False, False)
        return c
    else:  # pragma: no cover
        raise AssertionError(nom)
    return a


ROTATIONS = (
    "password",
    "forgottenHere",
    "recoveryKeyReplace",
    "recoveryKeyRemove",
    "disconnectOther",
    "recover",
)


class TestChaqueRotation:
    """§2.8 et étape 8 : « chaque rotation : les autres sessions tombent en
    sessionExpired, et enveloppe_locale est effacée sur sessionRevoked »."""

    @pytest.mark.parametrize("nom", ROTATIONS)
    def test_les_autres_appareils_tombent_en_session_expiree(self, nom, fabrique, vps):
        a = fabrique("a")
        cle = inscrire(a, vps)
        protecteur_b = ProtecteurPersistant()
        b = fabrique("b", protecteur=protecteur_b)
        b.connecter(EMAIL, MDP, True)
        compte = b.etat.lire("accountId")
        assert protecteur_b.lire(compte, ELEMENT_AMK) is not None

        auteur = _rotation(nom, a, b, vps, fabrique, cle)

        assert _epoque(auteur) == 2, "la rotation n'a pas ouvert l'époque suivante"
        assert auteur.appareils(), "l'appareil qui a fait tourner doit rester connecté"
        with pytest.raises(SessionExpiree):
            b.appareils()
        assert b.statut()["state"] == "sessionExpired"
        assert b.etat.enveloppe_locale() is None, (
            "l'enveloppe locale d'avant la rotation a survécu à sessionRevoked"
        )
        assert protecteur_b.lire(compte, ELEMENT_AMK) is None, (
            "l'AMK mémorisée a survécu à sessionRevoked"
        )
        assert protecteur_b.lire(compte, ELEMENT_SESSION) is None
        assert b.statut()["remembered"] is False
        assert b.etat.planchers().vault_version_max == 1, (
            "les planchers doivent rester après sessionRevoked"
        )


# ----------------------------------------------------------------------
# P5 — changement de mot de passe
# ----------------------------------------------------------------------


class TestP5ChangementDeMotDePasse:
    def test_l_ancien_mot_de_passe_ne_rouvre_plus(self, fabrique, vps):
        """§2.8 : l'ancienne enveloppe et l'ancien mot de passe ne rendent
        plus l'AMK courante."""
        a = fabrique()
        inscrire(a, vps)
        amk_avant = a.serrure.exiger().amk
        a.changer_mot_de_passe(MDP, MDP_2)
        assert a.serrure.exiger().amk != amk_avant, "l'AMK n'a pas tourné"
        a.verrouiller()
        with pytest.raises(MotDePasseFaux):
            a.deverrouiller(MDP)
        a.deverrouiller(MDP_2)

    def test_un_appareil_hors_ligne_s_ouvre_encore_avec_l_ancien(self, fabrique, vps):
        """§3.11 P5 : « un appareil resté hors ligne s'ouvre encore localement
        avec l'ancien, sans rien recevoir, jusqu'à son prochain contact »."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        b.verrouiller()
        a.changer_mot_de_passe(MDP, MDP_2)
        b.deverrouiller(MDP)
        assert b.statut()["state"] == "unlocked"
        with pytest.raises(SessionExpiree):
            b.appareils()
        assert b.etat.enveloppe_locale() is None

    def test_un_mot_de_passe_actuel_faux_ne_joint_pas_le_serveur(self, fabrique, vps):
        """Jugé contre l'enveloppe locale : pas d'essai consommé dans les
        délais de ``/login``, pas de courriel « mot de passe changé »."""
        a = fabrique()
        inscrire(a, vps)
        avant = len(vps.requetes)
        with pytest.raises(MotDePasseFaux):
            a.changer_mot_de_passe(MDP_3, MDP_2)
        assert len(vps.requetes) == avant

    def test_le_code_du_coffre_exige_l_appareil_deverrouille(self, fabrique, vps):
        """§3.8 : ``forgotten-here`` exige cet appareil déverrouillé EN CE
        MOMENT — 423, jamais 401."""
        a = fabrique()
        inscrire(a, vps)
        a.verrouiller()
        with pytest.raises(CompteVerrouille) as refus:
            a.code_oubli_ici()
        assert refus.value.code == "accountLocked"


# ----------------------------------------------------------------------
# P4 — récupération par la clé
# ----------------------------------------------------------------------


class TestP4Recuperation:
    def test_les_cles_tournent_avant_toute_ecriture(self, fabrique, vps):
        """§2.11 bis : HPKE Base n'authentifie pas l'expéditeur ; un appareil
        perdu peut forger un coffre qui porte la vraie ``pk_rec``. Après une
        récupération, ``vault/commit`` est la première écriture, et
        l'historique ouvert par ce chemin est marqué non authentifié."""
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")
        debut = len(vps.requetes)
        c.recuperer(EMAIL, cle, MDP_3, False, False)
        chemins = vps.chemins()[debut:]
        deballage = chemins.index("POST /api/v1/recovery/unwrap")
        assert chemins[deballage + 1] == "POST /api/v1/vault/commit", (
            f"la rotation doit suivre immédiatement le déballage : {chemins}"
        )
        ecritures = [
            i
            for i, ch in enumerate(chemins)
            if ch.startswith(("PUT ", "POST /api/v1/sync", "DELETE "))
        ]
        assert all(i > deballage + 1 for i in ecritures), (
            f"une écriture a précédé la rotation : {chemins}"
        )
        assert _epoque(c) == 2
        assert c.etat.lire("epoqueAuthentifieeMin") == "2"

    def test_si_le_commit_echoue_rien_ne_s_ecrit(self, fabrique, vps):
        """Sans rotation, rien ne doit s'écrire sous le trousseau ouvert par
        ``R`` : l'appareil reste fermé et sans compte."""
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")

        def refuser_le_commit(requete, reponse):
            if requete.chemin == "/api/v1/vault/commit":
                return reponse_json(409, {"error": {"code": "vaultConflict"}})
            return None

        vps.falsifier = refuser_le_commit
        debut = len(vps.requetes)
        with pytest.raises(ErreurServeur):
            c.recuperer(EMAIL, cle, MDP_3, False, False)
        apres = vps.chemins()[debut:]
        assert not [ch for ch in apres if ch.startswith("PUT ")], apres
        assert c.statut()["state"] == "none"
        assert not c.serrure.ouverte

    def test_une_faute_de_frappe_ne_coute_aucun_appel(self, fabrique, vps):
        """§2.7 : une faute est détectée LOCALEMENT, avant tout appel réseau
        — elle n'use pas un essai des délais de récupération."""
        a = fabrique("a")
        cle = inscrire(a, vps)
        faute = ("Y" if cle[0] != "Y" else "Z") + cle[1:]
        c = fabrique("c")
        avant = len(vps.requetes)
        with pytest.raises(CleRecuperationInvalide):
            c.recuperer(EMAIL, faute, MDP_3, False, False)
        assert len(vps.requetes) == avant

    def test_la_cle_utilisee_est_remplacee_par_defaut(self, fabrique, vps):
        """D22 : une clé qui a servi a été tapée ; une neuve est proposée, et
        une fois ressaisie l'ancienne ne rouvre plus rien."""
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")
        rendu = c.recuperer(EMAIL, cle, MDP_3, False, False)
        nouvelle = rendu["newRecoveryKey"]
        assert nouvelle != cle
        c.nouvelle_cle_confirmer(extrait(rendu))
        d = fabrique("d")
        with pytest.raises(ErreurServeur) as refus:
            d.recuperer(EMAIL, cle, MDP_2, False, False)
        assert refus.value.code == "invalidCredentials"
        d.recuperer(EMAIL, nouvelle, MDP_2, False, True)
        assert d.statut()["state"] == "unlocked"

    def test_garder_la_cle_la_laisse_valable(self, fabrique, vps):
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")
        assert c.recuperer(EMAIL, cle, MDP_3, False, True) == {}
        d = fabrique("d")
        d.recuperer(EMAIL, cle, MDP_2, False, True)
        assert d.statut()["recoveryConfigured"] is True


# ----------------------------------------------------------------------
# P4 — réinitialisation
# ----------------------------------------------------------------------


def _une_heure_plus_tard(vps: Vps) -> None:
    """Le VPS n'envoie que 3 courriels par heure et par adresse, avis de
    sécurité compris (§3.5) : une inscription, une rotation et son avis
    suffisent à retenir le code suivant."""
    vps.horloge.avancer(61 * 60_000)


def _reinitialiser(a, vps, nouveau: str = MDP_2, *, confirmer: bool = True) -> dict:
    """P4 chemin 3 complet ; rend ce que ``reset/complete`` a rendu. La clé
    proposée est ressaisie si ``confirmer``."""
    _une_heure_plus_tard(vps)
    avant = vps.nombre(EMAIL, "code_reinitialisation")
    a.reinit_demander(EMAIL)
    effectif = a.reinit_confirmer(
        EMAIL, vps.code(EMAIL, "code_reinitialisation", avant + 1)
    )["effectiveAt"]
    assert a.statut()["state"] == "resetPending"
    assert a.statut()["pendingResetAt"] == effectif
    vps.horloge.avancer(7 * JOUR_MS + 1)
    a.reinit_demander(EMAIL)
    code = vps.code(EMAIL, "code_reinitialisation", avant + 2)
    rendu = a.reinit_terminer(EMAIL, code, nouveau, False)
    if confirmer:
        a.nouvelle_cle_confirmer(extrait(rendu))
    return rendu


class TestP4Reinitialisation:
    def test_la_reinitialisation_ouvre_une_incarnation_neuve(self, fabrique, vps):
        """§3.6 : ``reset/complete`` ouvre ``incarnation + 1``, un coffre neuf,
        époque 1 ; un autre appareil le rouvre avec le nouveau mot de passe."""
        a = fabrique("a")
        inscrire(a, vps)
        nouvelle = _reinitialiser(a, vps)["newRecoveryKey"]
        assert nouvelle
        assert a.statut()["state"] == "unlocked"
        assert a.etat.planchers().incarnation_max == 2
        b = fabrique("b")
        b.connecter(EMAIL, MDP_2, False)
        assert b.etat.lire("incarnation") == "2"

    def test_annuler_depuis_un_appareil_connecte(self, fabrique, vps):
        """§3.6 : ``reset/cancel`` est accepté depuis n'importe quelle session."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        vps.plus_tard()
        a.reinit_demander(EMAIL)
        a.reinit_confirmer(EMAIL, vps.code(EMAIL, "code_reinitialisation", 1))
        b.reinit_annuler()
        with vps.ctx.base.lecture() as conn:
            attente = conn.execute("SELECT reinit_effective_ms FROM comptes").fetchone()
        assert attente[0] is None, "l'annulation n'a pas atteint le serveur"

    def test_un_appareil_qui_ne_connait_pas_le_compte_refuse(self, fabrique, vps):
        """L'AAD du coffre neuf porte l'incarnation suivante, que le corps du
        VPS ne rend qu'après : un appareil sans ce compte ne la connaît pas,
        et refuse plutôt que de sceller un coffre que personne ne rouvrirait."""
        inscrire(fabrique("a"), vps)
        d = fabrique("d")
        with pytest.raises(EtatRefuse) as refus:
            d.reinit_terminer(EMAIL, "123456", MDP_2, False)
        assert refus.value.code == "resetNeedsKnownAccount"

    def test_un_appareil_inconnu_ne_programme_rien(self, fabrique, vps):
        """§34 : un appareil qui ne pourra pas terminer la réinitialisation
        ne doit pas la programmer. Sinon : courriel « prévue », avertissement
        sur chaque appareil, sept jours d'attente — puis
        ``resetNeedsKnownAccount``, sans rien ni personne pour l'annuler
        depuis cet appareil (constat du 24/09/2026)."""
        inscrire(fabrique("a"), vps)
        d = fabrique("d")
        debut = len(vps.requetes)
        with pytest.raises(EtatRefuse) as refus:
            d.reinit_demander(EMAIL)
        assert refus.value.code == "resetNeedsKnownAccount"
        with pytest.raises(EtatRefuse):
            d.reinit_confirmer(EMAIL, "123456")
        assert not [c for c in vps.chemins()[debut:] if "/reset/" in c], (
            "un appareil inconnu a joint /reset/*"
        )
        with vps.ctx.base.lecture() as conn:
            attente = conn.execute("SELECT reinit_effective_ms FROM comptes").fetchone()
        assert attente[0] is None, "une réinitialisation a été programmée"

    def test_une_seconde_reinitialisation_depuis_un_appareil_en_retard_est_refusee(
        self, fabrique, vps
    ):
        """§6 bis, constat du 24/09/2026 : A réinitialise (1 → 2) ; B, resté
        sur l'incarnation 1, termine une seconde réinitialisation. Il scellait
        pour 2 quand le VPS ouvrait 3 : compte muré, et le nouveau mot de
        passe lu partout comme faux. B doit refuser AVANT ``reset/complete``,
        puisque rien ne lui confirme l'incarnation courante."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        _reinitialiser(a, vps, MDP_2)
        # A programme une seconde réinitialisation ; le code du courriel
        # peut être tapé sur B.
        _une_heure_plus_tard(vps)
        avant = vps.nombre(EMAIL, "code_reinitialisation")
        a.reinit_demander(EMAIL)
        a.reinit_confirmer(EMAIL, vps.code(EMAIL, "code_reinitialisation", avant + 1))
        vps.horloge.avancer(7 * JOUR_MS + 1)
        b.reinit_demander(EMAIL)
        code = vps.code(EMAIL, "code_reinitialisation", avant + 2)
        debut = len(vps.requetes)
        with pytest.raises(EtatRefuse) as refus:
            b.reinit_terminer(EMAIL, code, MDP_3, False)
        assert (refus.value.code, refus.value.raison) == (
            "resetNeedsKnownAccount",
            "incarnationUnconfirmed",
        )
        assert "POST /api/v1/reset/complete" not in vps.chemins()[debut:], (
            "un coffre a été scellé sur une incarnation devinée"
        )
        c = fabrique("c")
        c.connecter(EMAIL, MDP_2, False)
        assert c.etat.lire("incarnation") == "2", "le compte a changé d'incarnation"

    def test_une_session_expiree_prouve_encore_l_incarnation(self, fabrique, vps):
        """§3.7 : 90 jours sans contact ne compromettent rien. Le jeton expiré
        reste, et le VPS répond ``sessionExpired`` tant que la session n'a
        été effacée ni par une rotation ni par une réinitialisation : c'est
        ce qui permet encore à qui revient après trois mois, mot de passe
        oublié, de réinitialiser depuis cet appareil."""
        a = fabrique("a")
        inscrire(a, vps)
        compte = a.etat.lire("accountId")
        vps.horloge.avancer(91 * JOUR_MS)
        with pytest.raises(SessionExpiree):
            a.appareils()
        assert a.protecteur.lire(compte, ELEMENT_SESSION) is not None, (
            "le jeton expiré a été effacé : il ne prouverait plus rien"
        )
        vps.plus_tard()
        avant = vps.nombre(EMAIL, "code_reinitialisation")
        a.reinit_demander(EMAIL)
        a.reinit_confirmer(EMAIL, vps.code(EMAIL, "code_reinitialisation", avant + 1))
        vps.horloge.avancer(7 * JOUR_MS + 1)
        a.reinit_demander(EMAIL)
        code = vps.code(EMAIL, "code_reinitialisation", avant + 2)
        a.reinit_terminer(EMAIL, code, MDP_2, False)
        assert a.statut()["state"] == "unlocked"
        assert a.etat.lire("incarnation") == "2"

    def test_la_cle_du_coffre_neuf_n_existe_qu_une_fois_ressaisie(self, fabrique, vps):
        """§100 : ``reset/complete`` scellait une clé tirée ici et ne la
        rendait qu'une fois ; réponse perdue, le serveur gardait une clé que
        personne n'avait vue et le statut comptait « clé de récupération »."""
        a = fabrique("a")
        inscrire(a, vps)
        rendu = _reinitialiser(a, vps, MDP_2, confirmer=False)
        assert a.statut()["backupMeans"]["recoveryKey"] is False, (
            "une clé jamais ressaisie compte comme moyen de secours"
        )
        a.nouvelle_cle_confirmer(extrait(rendu))
        assert a.statut()["backupMeans"]["recoveryKey"] is True
        a.verrouiller()
        d = fabrique("d")
        d.recuperer(EMAIL, rendu["newRecoveryKey"], MDP_3, False, True)
        assert d.statut()["state"] == "unlocked"

    def test_une_reponse_perdue_ne_laisse_pas_de_cle_fantome(self, fabrique, vps):
        """Constat du 24/09/2026 : ``reset/complete`` exécuté au VPS, réponse
        perdue. La connexion avec le nouveau mot de passe affichait
        ``recoveryKey: True`` pour une clé que personne ne détenait ; D4
        (« 0 moyen de secours ») disparaissait pour qui venait de prouver
        qu'il oublie."""
        a = fabrique("a")
        inscrire(a, vps)

        def perdre(requete, reponse):
            if requete.chemin == "/api/v1/reset/complete":
                raise httpx.ReadTimeout("réponse perdue")
            return None

        vps.plus_tard()
        avant = vps.nombre(EMAIL, "code_reinitialisation")
        a.reinit_demander(EMAIL)
        a.reinit_confirmer(EMAIL, vps.code(EMAIL, "code_reinitialisation", avant + 1))
        vps.horloge.avancer(7 * JOUR_MS + 1)
        a.reinit_demander(EMAIL)
        code = vps.code(EMAIL, "code_reinitialisation", avant + 2)
        vps.falsifier = perdre
        with pytest.raises(ServeurInjoignable):
            a.reinit_terminer(EMAIL, code, MDP_2, False)
        vps.falsifier = None
        b = fabrique("b")
        b.connecter(EMAIL, MDP_2, False)
        assert b.statut()["backupMeans"] == {
            "recoveryKey": False,
            "rememberedDevices": 0,
        }, "une clé que personne n'a vue est comptée comme moyen de secours"

    def test_une_date_passee_n_est_plus_une_attente(self, fabrique, vps):
        """P9 : « Réinitialisation prévue le {date} — [Annuler] ». Une date
        locale PASSÉE (terminée ou annulée ailleurs, réponse perdue) laissait
        ce bandeau indéfiniment."""
        a = fabrique("a")
        inscrire(a, vps)
        vps.plus_tard()
        a.reinit_demander(EMAIL)
        effectif = a.reinit_confirmer(
            EMAIL, vps.code(EMAIL, "code_reinitialisation", 1)
        )["effectiveAt"]
        assert a.statut()["state"] == "resetPending"
        vps.horloge.avancer(7 * JOUR_MS + 1)
        statut = a.statut()
        assert statut["state"] == "unlocked", "une date passée reste « prévue »"
        assert statut["pendingResetAt"] == effectif


# ----------------------------------------------------------------------
# Face à un VPS hostile (§4.12)
# ----------------------------------------------------------------------


def _capturer_la_connexion(vps: Vps, capture: dict) -> None:
    def capturer(requete, reponse):
        if requete.chemin == "/api/v1/login" and reponse.status_code == 200:
            capture.setdefault("login", reponse.json())
        return None

    vps.falsifier = capturer


def _rejouer_la_connexion(vps: Vps, capture: dict) -> None:
    def rejouer(requete, reponse):
        if requete.chemin == "/api/v1/login":
            return reponse_json(200, capture["login"])
        return None

    vps.falsifier = rejouer


class TestFaceAUnVpsHostile:
    @pytest.mark.parametrize("version", [0, 2, True])
    def test_un_argon2_affaibli_est_refuse_avant_tout_calcul(
        self, version, fabrique, vps
    ):
        """§2.3, §4.12 « impose un Argon2 faible » : ``kdfDowngrade``, et
        aucun ``authKey`` n'est parti."""
        inscrire(fabrique("a"), vps)
        b = fabrique("b")

        def affaiblir(requete, reponse):
            if requete.chemin == "/api/v1/login/params":
                return reponse_json(200, {**reponse.json(), "kdfVersion": version})
            return None

        vps.falsifier = affaiblir
        debut = len(vps.requetes)
        with pytest.raises((DeclassementKdf, ErreurServeur)) as refus:
            b.connecter(EMAIL, MDP, False)
        assert refus.value.code in {"kdfDowngrade", "serverError"}
        assert "POST /api/v1/login" not in vps.chemins()[debut:], (
            "un authKey est parti sous des paramètres affaiblis"
        )

    def test_un_coffre_rejoue_sous_le_plancher_est_refuse(self, fabrique, vps):
        """§4.4, §4.12 « rejoue un coffre ancien » : ``serverKeyStale``, même
        avec l'ancien mot de passe qui l'ouvrirait."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        capture: dict = {}
        _capturer_la_connexion(vps, capture)
        b.connecter(EMAIL, MDP, False)
        vps.falsifier = None
        a.changer_mot_de_passe(MDP, MDP_2)
        with pytest.raises(SessionExpiree):
            b.appareils()
        b.connecter(EMAIL, MDP_2, False)
        assert b.etat.planchers().vault_version_max == 2
        b.verrouiller()
        _rejouer_la_connexion(vps, capture)
        with pytest.raises(CleServeurPerimee) as refus:
            b.connecter(EMAIL, MDP, False)
        assert refus.value.code == "serverKeyStale"
        assert b.etat.enveloppe_locale().version_coffre == 2, (
            "le coffre rejoué a remplacé l'enveloppe locale"
        )
        assert not b.serrure.ouverte

    def test_une_incarnation_rejouee_est_un_retour_arriere(self, fabrique, vps):
        """§6 bis : le coffre d'avant la réinitialisation, rejoué avec SON
        incarnation, s'ouvrirait avec l'ancien mot de passe — l'AAD
        concorde. Le plancher ``incarnation_max`` le refuse AVANT tout essai
        de clé, en ``serverRolledBack`` et non en « mauvais mot de passe »."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        capture: dict = {}
        _capturer_la_connexion(vps, capture)
        b.connecter(EMAIL, MDP, False)
        vps.falsifier = None
        _reinitialiser(a, vps, MDP_2)
        with pytest.raises(SessionExpiree):
            b.appareils()
        b.connecter(EMAIL, MDP_2, False)
        assert b.etat.planchers().incarnation_max == 2
        b.verrouiller()
        _rejouer_la_connexion(vps, capture)
        with pytest.raises(RetourArriereServeur) as refus:
            b.connecter(EMAIL, MDP, False)
        assert refus.value.code == "serverRolledBack"
        assert b.statut()["state"] == "serverRolledBack"
        assert not b.serrure.ouverte, "le coffre d'avant la réinitialisation a ouvert"


def _capturer_le_deballage(vps: Vps, capture: dict) -> None:
    def capturer(requete, reponse):
        if requete.chemin == "/api/v1/recovery/unwrap" and reponse.status_code == 200:
            capture.setdefault("unwrap", reponse.json())
        return None

    vps.falsifier = capturer


def _rejouer_le_deballage(vps: Vps, capture: dict) -> None:
    def rejouer(requete, reponse):
        if requete.chemin == "/api/v1/recovery/unwrap":
            return reponse_json(200, capture["unwrap"])
        return None

    vps.falsifier = rejouer


class TestLaRecuperationFaceAUnVpsHostile:
    """§4.12 et §6 bis sur le chemin de ``/recover`` : les planchers et le
    refus d'incarnation valent AUSSI pour ``/recovery/unwrap``. Le
    24/09/2026, une mutation qui les remplaçait par des planchers nuls dans
    ``recuperer`` laissait toute la suite verte."""

    def test_une_incarnation_rejouee_par_unwrap_est_un_retour_arriere(
        self, fabrique, vps
    ):
        a = fabrique("a")
        cle = inscrire(a, vps)
        b = fabrique("b")
        capture: dict = {}
        _capturer_le_deballage(vps, capture)
        b.recuperer(EMAIL, cle, MDP_2, False, True)
        vps.falsifier = None
        _reinitialiser(b, vps, MDP_3)
        assert b.etat.planchers().incarnation_max == 2
        b.verrouiller()
        _rejouer_le_deballage(vps, capture)
        debut = len(vps.requetes)
        with pytest.raises(RetourArriereServeur) as refus:
            b.recuperer(EMAIL, cle, MDP, False, True)
        assert refus.value.code == "serverRolledBack"
        assert b.statut()["state"] == "serverRolledBack"
        assert not b.serrure.ouverte, "le coffre d'avant la réinitialisation a ouvert"
        assert "POST /api/v1/vault/commit" not in vps.chemins()[debut:], (
            "un commit est parti sur un coffre rejoué"
        )

    def test_un_coffre_rejoue_par_unwrap_sous_le_plancher_est_refuse(
        self, fabrique, vps
    ):
        a = fabrique("a")
        cle = inscrire(a, vps)
        b = fabrique("b")
        capture: dict = {}
        _capturer_le_deballage(vps, capture)
        b.recuperer(EMAIL, cle, MDP_2, False, True)
        vps.falsifier = None
        assert b.etat.planchers().vault_version_max == 2
        b.verrouiller()
        _rejouer_le_deballage(vps, capture)
        debut = len(vps.requetes)
        with pytest.raises(CleServeurPerimee) as refus:
            b.recuperer(EMAIL, cle, MDP, False, True)
        assert refus.value.code == "serverKeyStale"
        assert "POST /api/v1/vault/commit" not in vps.chemins()[debut:], (
            "un commit est parti sur un coffre sous le plancher"
        )
        assert b.etat.enveloppe_locale().version_coffre == 2, (
            "le coffre rejoué a remplacé l'enveloppe locale"
        )
        assert not b.serrure.ouverte


# ----------------------------------------------------------------------
# Ce qui ne part jamais, ce qui ne s'écrit jamais
# ----------------------------------------------------------------------


def _parcours_complet(fabrique, vps) -> tuple[list[bytes], list[str]]:
    """Inscription, second appareil, changement de mot de passe, nouvelle
    clé, déconnexion d'un appareil, récupération. Rend les secrets vus."""
    secrets_vus: list[bytes] = []
    cles_vues: list[str] = []

    def relever(service) -> None:
        ouverture = service.serrure.exiger()
        secrets_vus.append(ouverture.amk)
        secrets_vus.extend(ouverture.trousseau.epochs.values())
        secrets_vus.append(ouverture.trousseau.id_key)

    a = fabrique("a")
    cle = inscrire(a, vps)
    cles_vues.append(cle)
    relever(a)
    b = fabrique("b")
    b.connecter(EMAIL, MDP, False)
    relever(b)
    a.changer_mot_de_passe(MDP, MDP_2)
    relever(a)
    rendu = a.nouvelle_cle_preparer(MDP_2)
    cles_vues.append(rendu["recoveryKey"])
    a.nouvelle_cle_confirmer(extrait(rendu))
    relever(a)
    b.verrouiller()
    b.connecter(EMAIL, MDP_2, False)
    a.deconnecter_appareil(b.etat.lire("sessionId"), MDP_2)
    relever(a)
    c = fabrique("c")
    cles_vues.append(
        c.recuperer(EMAIL, cles_vues[-1], MDP_3, False, False)["newRecoveryKey"]
    )
    relever(c)
    sel = c.etat.enveloppe_locale().sel_kdf
    for mdp in (MDP, MDP_2, MDP_3):
        secrets_vus.append(cles.deriver_cles_mot_de_passe(mdp, EMAIL, sel, 1).kek)
    for texte in cles_vues:
        secrets_vus.append(lire_cle_recuperation(texte))
    return secrets_vus, cles_vues


class TestCeQuiNePartJamais:
    def test_aucune_requete_ne_contient_kek_ni_amk(self, fabrique, vps):
        """§2.9 « Jamais » : ni le mot de passe, ni les KEK, ni l'AMK, ni les
        DEK, ni ``K_id``, ni ``R`` ne voyagent — sous aucune écriture."""
        secrets_vus, cles_vues = _parcours_complet(fabrique, vps)
        assert len(vps.requetes) >= 15, "le parcours doit avoir parlé au serveur"
        assert vps.hotes == {"https://diapason.flashprime.online"}, vps.hotes
        interdits = [f for s in secrets_vus for f in formes(s)]
        interdits += [m.encode() for m in (MDP, MDP_2, MDP_3)]
        interdits += [texte.encode() for texte in cles_vues]
        interdits += [texte.replace("-", "").encode() for texte in cles_vues]
        for requete in vps.requetes:
            brut = requete.contenu + repr(sorted(requete.en_tetes.items())).encode()
            for interdit in interdits:
                assert interdit not in brut, (
                    f"un secret est parti dans {requete.methode} {requete.chemin}"
                )

    def test_le_mot_de_passe_n_entre_dans_aucun_journal(self, fabrique, vps, caplog):
        """§2.10 « ce qu'on ne fait jamais : en écrire un dans un journal »,
        refus compris."""
        caplog.set_level(logging.DEBUG)
        _parcours_complet(fabrique, vps)
        a = fabrique("x")
        with pytest.raises(ErreurServeur):
            a.connecter(EMAIL, "Mauvais-canari-journal-8Hq", False)
        texte = caplog.text + "".join(
            repr(r.args) + r.getMessage() for r in caplog.records
        )
        for mdp in (MDP, MDP_2, MDP_3, "Mauvais-canari-journal-8Hq"):
            assert mdp not in texte, "un mot de passe est entré au journal"


# ----------------------------------------------------------------------
# P6 — appareils ; P7 — déconnexion ; P8 — suppression
# ----------------------------------------------------------------------


class TestP6P7P8:
    def test_les_appareils_portent_leur_nom_dechiffre(self, fabrique, vps):
        """Le nom voyage scellé sous ``K_noms`` (type 04) ; seul un appareil
        du compte le lit."""
        a = fabrique("a")
        inscrire(a, vps)
        fabrique("b").connecter(EMAIL, MDP, False)
        noms = sorted(s["name"] for s in a.appareils())
        assert noms == ["Appareil a", "Appareil b"]
        with vps.ctx.base.lecture() as conn:
            brut = b"".join(
                r[0] or b"" for r in conn.execute("SELECT nom_chiffre FROM sessions")
            )
        assert b"Appareil" not in brut, "un nom d'appareil est en clair au serveur"

    def test_on_ne_deconnecte_pas_cet_appareil_par_la_liste(self, fabrique, vps):
        """§2.8 : se déconnecter de CET appareil (P7) ne fait pas tourner les
        clés ; la liste ne doit pas le faire par ce chemin-là."""
        a = fabrique("a")
        inscrire(a, vps)
        with pytest.raises(EtatRefuse) as refus:
            a.deconnecter_appareil(a.etat.lire("sessionId"), MDP)
        assert refus.value.code == "currentDevice"

    def test_la_deconnexion_efface_tout_sans_tourner(self, fabrique, vps):
        """§3.11 P7 et §4.4 : l'état local disparaît, fichier compris ; la
        session serveur est refermée ; les clés ne tournent pas."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        jeton = b.protecteur.lire(b.etat.lire("accountId"), ELEMENT_SESSION).decode()
        assert b.deconnecter(False) == {"serverSessionClosed": True}
        assert not b.etat.existe(), "etat.key a survécu à la déconnexion"
        assert b.statut()["state"] == "none"
        refus = vps.client.get(
            "/api/v1/account", headers={"Authorization": f"Bearer {jeton}"}
        )
        assert refus.status_code == 401, "la session serveur est restée ouverte"
        assert _epoque(a) == 1 and a.appareils(), "P7 a fait tourner les clés"

    def test_effacer_les_donnees_locales_n_est_pas_promis(self, fabrique, vps):
        """§100 : ``eraseLocalData:true`` n'est pas encore fait ; répondre
        « oui » sans l'avoir fait serait un faux SUCCESS."""
        a = fabrique("a")
        inscrire(a, vps)
        with pytest.raises(Exception) as refus:
            a.deconnecter(True)
        assert getattr(refus.value, "code", None) == "invalidRequest"
        assert a.statut()["state"] == "unlocked"

    def test_la_suppression_exige_le_mot_de_passe(self, fabrique, vps):
        """§3.11 P8 : il faut le mot de passe ; un faux ne supprime rien."""
        a = fabrique("a")
        inscrire(a, vps)
        with pytest.raises(MotDePasseFaux):
            a.supprimer(MDP_2, False)
        assert _comptes_sur_le_vps(vps) == 1
        a.supprimer(MDP, False)
        assert _comptes_sur_le_vps(vps) == 0
        assert a.statut()["state"] == "none"
        assert not a.etat.existe()


class TestSansCompteRienNePart:
    def test_un_appareil_neuf_ne_joint_jamais_le_serveur(self, fabrique, vps):
        """§3.12 condition 4 : ni l'état, ni un verrouillage, ni l'accueil ne
        font partir quoi que ce soit."""
        a = fabrique("a")
        a.statut()
        a.verrouiller()
        a.accueil_termine()
        with pytest.raises(EtatRefuse):
            a.consentir()
        assert vps.requetes == []
        assert a.statut()["onboarding"] == "done"
        assert not a.etat.existe(), "l'accueil a créé etat.key"


# ----------------------------------------------------------------------
# Contre-épreuves du 24/09/2026
# ----------------------------------------------------------------------


class _Interruption(BaseException):
    """La fermeture de l'app au milieu d'un appel : rien ne l'attrape."""


def _geste_juge(nom: str, a, b, mot_de_passe: str) -> None:
    """Un geste qui juge le mot de passe contre l'enveloppe locale."""
    if nom == "password":
        a.changer_mot_de_passe(mot_de_passe, MDP_3)
    elif nom == "recoveryKey":
        a.nouvelle_cle_preparer(mot_de_passe)
    elif nom == "recoveryKeyRemove":
        a.retirer_cle(mot_de_passe)
    elif nom == "disconnectOther":
        a.deconnecter_appareil(b.etat.lire("sessionId"), mot_de_passe)
    elif nom == "delete":
        a.supprimer(mot_de_passe, False)
    else:  # pragma: no cover
        raise AssertionError(nom)


class TestLaLimiteCouvreChaqueJugementDuMotDePasse:
    """§3.8 : « 5 essais, puis 30 s ». Le 24/09/2026, seul ``unlock``
    comptait : ``/delete`` (appareil verrouillé compris), ``/password``,
    ``/recovery-key``, ``/recovery-key/remove`` et ``/devices/{id}/disconnect``
    jugeaient le mot de passe contre la même enveloppe sans limite — un
    programme de la session (A7) le devinait, puis prenait le compte."""

    @pytest.mark.parametrize(
        "nom",
        ["password", "recoveryKey", "recoveryKeyRemove", "disconnectOther", "delete"],
    )
    def test_cinq_echecs_bloquent_ce_geste_et_le_deverrouillage(
        self, nom, fabrique, vps
    ):
        mono = Mono()
        a = fabrique("a", mono=mono)
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        for _ in range(5):
            with pytest.raises(MotDePasseFaux):
                _geste_juge(nom, a, b, MDP_2)
        debut = len(vps.requetes)
        with pytest.raises(TropDEssais) as refus:
            _geste_juge(nom, a, b, MDP)
        assert refus.value.retry_after_s == 30, "l'attente doit être de 30 s"
        assert vps.requetes[debut:] == [], "le bon mot de passe est passé en attente"
        a.verrouiller()
        with pytest.raises(TropDEssais):
            a.deverrouiller(MDP)
        assert _comptes_sur_le_vps(vps) == 1
        mono.avancer(30)
        a.deverrouiller(MDP)
        assert a.statut()["state"] == "unlocked"

    def test_la_suppression_sur_un_appareil_verrouille_compte_ses_echecs(
        self, fabrique, vps
    ):
        """Appareil verrouillé : 50 essais sur ``/delete`` rendaient chacun
        ``invalidPassword`` sans rien compter ; le bon supprimait le compte."""
        a = fabrique("a")
        inscrire(a, vps)
        a.verrouiller()
        for _ in range(5):
            with pytest.raises(MotDePasseFaux):
                a.supprimer(MDP_2, False)
        with pytest.raises(TropDEssais):
            a.supprimer(MDP, False)
        with pytest.raises(TropDEssais):
            a.deverrouiller(MDP)
        assert _comptes_sur_le_vps(vps) == 1, "le compte a été supprimé en attente"


class TestCeQuiAttendEnMemoire:
    """§2.7 : ``R`` vit en mémoire 30 min au plus ; §78 : le voyant dit la
    vérité. Le 24/09/2026, ``R`` et la KEK de ``/recovery-key`` survivaient
    au verrouillage, à ``sessionRevoked`` et à 24 h d'horloge."""

    def test_verrouiller_efface_la_cle_en_attente_et_sa_kek(self, fabrique, vps):
        a = fabrique()
        inscrire(a, vps)
        a.nouvelle_cle_preparer(MDP)
        kek, r = a._nouvelle_cle.kek, a._nouvelle_cle.r
        a.verrouiller()
        assert a._nouvelle_cle is None, "l'attente a survécu au verrouillage"
        assert kek == bytearray(32), "la KEK en attente n'a pas été écrasée"
        assert r == bytearray(len(r)), "R en attente n'a pas été écrasée"

    def test_trente_minutes_puis_un_statut_effacent_l_attente(self, fabrique, vps):
        mono = Mono()
        a = fabrique(mono=mono)
        inscrire(a, vps)
        a.nouvelle_cle_preparer(MDP)
        kek = a._nouvelle_cle.kek
        mono.avancer(30 * 60 + 1)
        a.statut()
        assert a._nouvelle_cle is None, "R a survécu plus de 30 min en mémoire"
        assert kek == bytearray(32)

    def test_une_session_revoquee_efface_l_attente(self, fabrique, vps):
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        b.nouvelle_cle_preparer(MDP)
        a.changer_mot_de_passe(MDP, MDP_2)
        with pytest.raises(SessionExpiree):
            b.appareils()
        assert b._nouvelle_cle is None, "une clé pour un trousseau mort attend encore"


class TestUneReponsePerdueApresLaRotation:
    """§100. Le 24/09/2026 : ``vault/commit`` exécuté par le VPS, réponse
    perdue ; l'ancienne ``R`` était morte (D22 la remplaçait dans le même
    commit), la nouvelle jamais montrée, et la connexion suivante comptait
    « clé de récupération » comme moyen de secours."""

    def test_l_ancienne_cle_rouvre_encore_apres_une_reponse_perdue(self, fabrique, vps):
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")

        def perdre(requete, reponse):
            if requete.chemin == "/api/v1/vault/commit":
                raise httpx.ReadTimeout("réponse perdue")
            return None

        vps.falsifier = perdre
        with pytest.raises(ServeurInjoignable):
            c.recuperer(EMAIL, cle, MDP_3, False, False)
        vps.falsifier = None
        assert c.statut()["state"] == "none"
        rendu = c.recuperer(EMAIL, cle, MDP_3, False, False)
        assert c.statut()["state"] == "unlocked", "la clé détenue ne rouvre plus"
        c.nouvelle_cle_confirmer(extrait(rendu))
        d = fabrique("d")
        with pytest.raises(ErreurServeur):
            d.recuperer(EMAIL, cle, MDP_2, False, True)
        d.recuperer(EMAIL, rendu["newRecoveryKey"], MDP_2, False, True)

    def test_la_cle_proposee_ne_remplace_rien_avant_la_ressaisie(self, fabrique, vps):
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")
        rendu = c.recuperer(EMAIL, cle, MDP_3, False, False)
        assert len(rendu["confirmGroups"]) == 2
        commits = [r for r in vps.requetes if r.chemin == "/api/v1/vault/commit"]
        assert len(commits) == 1, "une seule rotation avant la ressaisie"
        assert commits[0].json()["recovery"]["mode"] == "keep", (
            "la clé a été remplacée avant d'avoir été ressaisie"
        )

    def test_le_marqueur_d_epoque_survit_a_une_fermeture_pendant_le_nommage(
        self, fabrique, vps
    ):
        """§2.11 bis : ``epoqueAuthentifieeMin`` s'écrivait APRÈS
        ``PUT /sessions/current`` (15 s). Une fermeture pendant le nommage
        laissait le compte installé et la serrure ouverte sans marqueur, et
        rien ne le réécrivait : l'étape 10 aurait tenu pour sûres les époques
        qu'un appareil perdu a pu forger."""
        a = fabrique("a")
        cle = inscrire(a, vps)
        c = fabrique("c")

        def fermer_l_app(requete, reponse):
            if (
                requete.methode == "PUT"
                and requete.chemin == "/api/v1/sessions/current"
            ):
                raise _Interruption()
            return None

        vps.falsifier = fermer_l_app
        with pytest.raises(_Interruption):
            c.recuperer(EMAIL, cle, MDP_3, False, True)
        vps.falsifier = None
        assert c.etat.lire("accountId"), "le compte devait être installé"
        assert c.etat.lire("epoqueAuthentifieeMin") == "2", (
            "le marqueur d'époque authentifiée manque après une interruption"
        )


class TestLesRefusDEtat:
    """§3.8 : 409 ``alreadyConnected`` / ``alreadyUnlocked`` ; aucun n'était
    exercé le 24/09/2026 (une mutation qui ne refusait plus restait verte)."""

    def test_connexion_et_recuperation_refusees_sur_un_appareil_ouvert(
        self, fabrique, vps
    ):
        a = fabrique("a")
        cle = inscrire(a, vps)
        debut = len(vps.requetes)
        with pytest.raises(EtatRefuse) as refus:
            a.connecter(EMAIL, MDP, False)
        assert refus.value.code == "alreadyConnected"
        with pytest.raises(EtatRefuse) as refus:
            a.recuperer(EMAIL, cle, MDP_2, False, True)
        assert refus.value.code == "alreadyConnected"
        with pytest.raises(EtatRefuse) as refus:
            a.deverrouiller(MDP)
        assert refus.value.code == "alreadyUnlocked"
        assert vps.requetes[debut:] == [], "un refus d'état a joint le serveur"

    def test_une_session_au_coffre_refuse_est_refermee(self, fabrique, vps):
        """Un ``/login`` dont le coffre est refusé ici laisse au serveur un
        jeton sans appareil, s'il n'est pas refermé."""
        inscrire(fabrique("a"), vps)
        b = fabrique("b")
        capture: dict = {}

        def fausser(requete, reponse):
            if requete.chemin == "/api/v1/login" and reponse.status_code == 200:
                corps = reponse.json()
                capture["jeton"] = corps["sessionToken"]
                return reponse_json(200, {**corps, "keyEpoch": 9})
            return None

        vps.falsifier = fausser
        with pytest.raises(ErreurCompte):
            b.connecter(EMAIL, MDP, False)
        vps.falsifier = None
        refus = vps.client.get(
            "/api/v1/account", headers={"Authorization": f"Bearer {capture['jeton']}"}
        )
        assert refus.status_code == 401, (
            "la session du coffre refusé est restée ouverte"
        )

    def test_un_appareil_relance_parle_au_serveur_sans_nouveau_geste(
        self, fabrique, vps, tmp_path
    ):
        """§3.12 condition 4 : un compte ENREGISTRÉ suffit. Après un
        redémarrage, aucun geste n'a eu lieu dans le processus."""
        protecteur = ProtecteurPersistant()
        a = fabrique("a", protecteur=protecteur)
        inscrire(a, vps, remember=True)
        a.fermer()
        relance = appareil(vps, tmp_path / "a", protecteur=protecteur)
        try:
            assert relance.appareils(), "le compte enregistré n'active pas le transport"
        finally:
            relance.fermer()

    def test_sans_compte_ni_geste_le_service_ne_joint_rien(self, fabrique, vps):
        d = fabrique("d")
        with pytest.raises(CompteInactif):
            d.client.login_params(EMAIL)
        assert vps.requetes == [], "une requête est partie sans compte ni geste"


class TestLaMemorisationEtLesSessions:
    def test_deverrouiller_peut_retablir_la_memorisation(self, fabrique, vps):
        """Verrouiller retire la mémorisation ; ``unlock`` la rétablit, sans
        passer par une nouvelle connexion."""
        protecteur = ProtecteurPersistant()
        a = fabrique("a", protecteur=protecteur)
        inscrire(a, vps, remember=True)
        compte = a.etat.lire("accountId")
        a.verrouiller()
        assert a.statut()["remembered"] is False
        a.deverrouiller(MDP, True)
        assert a.statut()["remembered"] is True
        assert protecteur.lire(compte, ELEMENT_AMK) is not None

    def test_se_reconnecter_ne_laisse_pas_de_session_fantome(self, fabrique, vps):
        """Une connexion sur un appareil verrouillé laissait l'ancienne
        session : la liste montrait deux fois cet appareil, et
        « Déconnecter » le fantôme faisait tourner les clés du compte."""
        a = fabrique("a")
        inscrire(a, vps)
        a.verrouiller()
        a.connecter(EMAIL, MDP, False)
        assert len(a.appareils()) == 1, "l'ancienne session de cet appareil reste"

    def test_un_compte_supprime_ailleurs_ne_se_lit_pas_comme_une_faute(
        self, fabrique, vps
    ):
        """§34 : après une suppression faite ailleurs, « mot de passe
        incorrect » menait à « mot de passe oublié », puis à un code qui ne
        vient jamais. Le refus dit que le compte a pu changer ailleurs."""
        a = fabrique("a")
        inscrire(a, vps)
        b = fabrique("b")
        b.connecter(EMAIL, MDP, False)
        a.supprimer(MDP, False)
        with pytest.raises(SessionExpiree):
            b.appareils()
        with pytest.raises(ErreurServeur) as refus:
            b.connecter(EMAIL, MDP, False)
        assert refus.value.code == "invalidCredentials"
        assert refus.value.raison == "changedElsewhere", (
            "le refus laisse croire à une faute de frappe"
        )
        assert "accountDeleted" not in ETATS, "un état que rien ne pose est promis"

    def test_une_surcharge_refusee_est_dite_avant_le_geste(
        self, fabrique, vps, monkeypatch
    ):
        """§3.12 condition 1 : sous ``local_only``, ``serverOrigin`` nommait
        la surcharge qui serait refusée."""
        monkeypatch.setattr(local_mode, "local_only", lambda config=None: True)
        assert fabrique("a").statut()["serverOriginAllowed"] is True
        monkeypatch.setenv(VARIABLE_SURCHARGE, "https://ailleurs.example")
        statut = fabrique("b").statut()
        assert statut["serverOrigin"] == "https://ailleurs.example"
        assert statut["serverOriginAllowed"] is False, (
            "l'écran nommerait une destination qui ne sera jamais jointe"
        )


class TestLaPreuveDeSauvegarde:
    """§2.7 : saisie tolérante, et les deux groupes DANS L'ORDRE demandé."""

    # 0x08 0x42 0x10 0x84 0x21 répète ``00001`` : la clé commence par des
    # « 1 » en base32 Crockford ; ``bytes(16)`` par des « 0 ».
    _UNS = bytes([0x08, 0x42, 0x10, 0x84, 0x21] * 3 + [0x08])

    def test_o_i_l_tirets_et_espaces_sont_toleres(self):
        _verifier_extrait(bytes(16), (1, 2), [" o-O o0 ", "OOOO"])
        _verifier_extrait(self._UNS, (1, 2), ["iIlL", "l-1 i-L"])

    def test_des_groupes_inverses_sont_refuses(self):
        from diapason.compte.recuperation import formater_cle_recuperation

        r = bytes(range(16))
        groupes = formater_cle_recuperation(r).split("-")
        assert groupes[2] != groupes[5]
        _verifier_extrait(r, (3, 6), [groupes[2], groupes[5]])
        with pytest.raises(ExtraitFaux):
            _verifier_extrait(r, (3, 6), [groupes[5], groupes[2]])
