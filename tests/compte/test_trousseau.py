"""Le trousseau des époques, le coffre et la rotation.

Conception : ``docs/development/compte-chiffre.md`` §2.2, §2.8 et §4.4,
étape 1 du §6. Le défaut bloquant de la revue cryptographie (24/09/2026) :
aucune clé ne tournait jamais, si bien qu'un ancien mot de passe ou un
appareil perdu donnait accès aux données présentes ET futures.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import re

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from diapason.compte import cles
from diapason.compte import enveloppe as env
from diapason.compte import recuperation as rec
from diapason.compte import trousseau as tr

COMPTE = "acc_1"
INCARNATION = 1
R = bytes(range(16))
IMAGE = b"\x89PNG" + bytes(range(60)) + bytes(8)


def _kek(mot_de_passe: str) -> bytes:
    k_mdp = cles._etirer_avec_parametres(
        cles.normaliser_mot_de_passe(mot_de_passe),
        b"sel-de-test-16oo",
        memory_cost=64,
        iterations=1,
        lanes=1,
    )
    return cles.cles_de_role(k_mdp).kek


KEK_ANCIENNE = _kek("ancien mot de passe")
KEK_NOUVELLE = _kek("nouveau mot de passe")


def _coffre_initial() -> tr.Coffre:
    return tr.creer_coffre(
        KEK_ANCIENNE,
        account_id=COMPTE,
        incarnation=INCARNATION,
        kdf_version=1,
        recovery_public_key=rec.cles_recuperation(R).cle_publique,
    )


def _tourner(coffre: tr.Coffre, **options) -> tr.Coffre:
    return tr.faire_tourner_les_cles(
        coffre.trousseau,
        kek=options.pop("kek", KEK_NOUVELLE),
        account_id=COMPTE,
        incarnation=options.pop("incarnation", INCARNATION),
        kdf_version=1,
        vault_version=coffre.vault_version,
        keyring_version=coffre.keyring_version,
        **options,
    )


def _ouvrir(kek: bytes, coffre: tr.Coffre, plancher: int):
    return tr.ouvrir_coffre(
        kek,
        enveloppe_amk=coffre.enveloppe_amk,
        enveloppe_trousseau=coffre.enveloppe_trousseau,
        account_id=COMPTE,
        incarnation=INCARNATION,
        kdf_version=1,
        vault_version=coffre.vault_version,
        keyring_version=coffre.keyring_version,
        plancher_vault_version=plancher,
        plancher_keyring_version=plancher,
    )


class TestLaRotation:
    def test_l_ancienne_enveloppe_et_l_ancien_mot_de_passe_ne_rendent_plus_l_amk(self):
        """§2.8 — après un changement de mot de passe, ni l'ancien mot de
        passe, ni l'ancienne enveloppe ramenée par une restauration ne
        doivent redonner l'AMK COURANTE."""
        avant = _coffre_initial()
        apres = _tourner(avant)
        assert apres.amk != avant.amk, "l'AMK doit être neuve à chaque rotation"
        with pytest.raises(env.EnveloppeIllisible):
            _ouvrir(KEK_ANCIENNE, apres, plancher=apres.vault_version)
        with pytest.raises(env.CleServeurPerimee):
            _ouvrir(KEK_ANCIENNE, avant, plancher=apres.vault_version)
        amk_ancienne, _ = _ouvrir(KEK_ANCIENNE, avant, plancher=0)
        assert amk_ancienne != apres.amk, (
            "même sans plancher, l'ancienne enveloppe ne rend que l'ancienne AMK"
        )
        amk, _ = _ouvrir(KEK_NOUVELLE, apres, plancher=apres.vault_version)
        assert amk == apres.amk, "le nouveau mot de passe ouvre le coffre courant"

    def test_l_ancienne_amk_ouvre_dek_1_mais_pas_dek_2(self):
        """§1.1 A4 — un appareil perdu qui garde l'AMK mémorisée lit
        l'historique (dit, pas caché), mais rien de ce qui est écrit après."""
        avant = _coffre_initial()
        apres = _tourner(avant)
        ancien = tr.ouvrir_trousseau(
            avant.amk,
            avant.enveloppe_trousseau,
            account_id=COMPTE,
            incarnation=INCARNATION,
            keyring_version=1,
            vault_version=1,
            plancher_keyring_version=0,
            plancher_vault_version=0,
        )
        assert set(ancien.epochs) == {1}, "l'ancien trousseau ne connaît que DEK_1"
        with pytest.raises(env.EnveloppeIllisible):
            tr.ouvrir_trousseau(
                avant.amk,
                apres.enveloppe_trousseau,
                account_id=COMPTE,
                incarnation=INCARNATION,
                keyring_version=apres.keyring_version,
                vault_version=apres.vault_version,
                plancher_keyring_version=0,
                plancher_vault_version=0,
            )
        oid, blob = apres.trousseau.sceller_objet(
            env.clair_objet("conversations", "c1", {"t": 1}),
            account_id=COMPTE,
            incarnation=1,
            rev=1,
        )
        assert env.lire_en_tete(blob).key_epoch == 2, "l'écriture neuve est sous DEK_2"
        with pytest.raises(tr.EpoqueInconnue) as exc:
            ancien.ouvrir_objet(
                blob, account_id=COMPTE, incarnation=1, object_id=oid, rev=1
            )
        assert exc.value.code == "keyEpochUnknown", (
            "le code doit demander un rechargement"
        )

    def test_le_nouveau_trousseau_lit_l_historique(self):
        """§2.2 — les anciennes DEK restent : l'historique se lit sans rien
        rechiffrer."""
        avant = _coffre_initial()
        oid, blob = avant.trousseau.sceller_objet(
            env.clair_objet("conversations", "c1", {"t": 1}),
            account_id=COMPTE,
            incarnation=1,
            rev=1,
        )
        apres = _tourner(avant)
        clair = apres.trousseau.ouvrir_objet(
            blob, account_id=COMPTE, incarnation=1, object_id=oid, rev=1
        )
        assert clair["data"] == {"t": 1}, "un objet de l'époque 1 doit rester lisible"
        assert apres.trousseau.epochs[1] == avant.trousseau.epochs[1], "DEK_1 conservée"
        assert apres.trousseau.id_key == avant.trousseau.id_key, (
            "idKey stable pendant l'incarnation : sinon deux appareils nomment "
            "différemment la même conversation"
        )

    def test_la_dek_neuve_est_un_tirage_frais(self, monkeypatch):
        """§2.8 étape 1 et §1.1 A4 — DEK_{e+1} et AMK′ sont tirées, pas
        dérivées de l'ancien trousseau : sinon l'appareil perdu les
        recalculerait. La première passe vérifiait qu'une recherche
        d'époque échoue, pas qu'aucune ancienne clé n'ouvre."""
        avant = _coffre_initial()
        tirages, vrai_urandom = [], os.urandom

        def urandom(n):
            tirages.append(vrai_urandom(n))
            return tirages[-1]

        monkeypatch.setattr(tr.os, "urandom", urandom)
        apres = _tourner(avant)
        assert apres.trousseau.epochs[2] in tirages, "DEK_2 vient d'un tirage"
        assert apres.amk in tirages, "AMK′ vient d'un tirage"
        oid, blob = apres.trousseau.sceller_objet(
            env.clair_objet("conversations", "c1", {"t": 1}),
            account_id=COMPTE,
            incarnation=1,
            rev=1,
        )
        anciennes = [
            *avant.trousseau.epochs.values(),
            avant.trousseau.id_key,
            avant.amk,
        ]
        for cle in anciennes:
            with pytest.raises(env.EnveloppeIllisible):
                env.ouvrir_objet(
                    cle, blob, account_id=COMPTE, incarnation=1, object_id=oid, rev=1
                )

    def test_les_versions_montent_de_un(self):
        """§2.8 — ``vault/commit`` fait un comparer-et-échanger sur les deux."""
        avant = _coffre_initial()
        apres = _tourner(avant)
        assert (apres.vault_version, apres.keyring_version) == (2, 2), (
            "w et r montent de 1"
        )
        assert apres.trousseau.current_epoch == 2, "l'époque monte de 1"

    def test_la_recuperation_gardee_rouvre_la_nouvelle_amk(self):
        """§2.8 étape 4 — scellée vers pk_rec lue dans le trousseau, sans R."""
        apres = _tourner(_coffre_initial())
        amk, _ = tr.ouvrir_coffre_par_recuperation(
            rec.cles_recuperation(R).cle_privee,
            enveloppe_amk_recuperation=apres.enveloppe_amk_recuperation,
            enveloppe_trousseau=apres.enveloppe_trousseau,
            account_id=COMPTE,
            incarnation=INCARNATION,
            vault_version=apres.vault_version,
            keyring_version=apres.keyring_version,
            plancher_vault_version=apres.vault_version,
            plancher_keyring_version=apres.keyring_version,
        )
        assert amk == apres.amk, "R doit rouvrir l'AMK neuve"

    def test_une_recuperation_retiree_ne_scelle_plus_rien(self):
        """§2.8 — retirer la clé de récupération : plus de type 06, et
        recoveryPublicKey vaut null dans le trousseau."""
        apres = _tourner(_coffre_initial(), recovery_public_key=None)
        assert apres.enveloppe_amk_recuperation is None, "aucune AMK scellée"
        assert apres.trousseau.recovery_public_key is None, "pk_rec retirée"

    def test_une_recuperation_remplacee_n_ouvre_plus_avec_l_ancienne_r(self):
        """§2.7 — une clé utilisée est remplacée : l'ancienne R ne doit plus
        rien ouvrir de ce qui est écrit ensuite."""
        nouvelle_r = bytes([9]) * 16
        apres = _tourner(
            _coffre_initial(),
            recovery_public_key=rec.cles_recuperation(nouvelle_r).cle_publique,
        )
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk_recuperation(
                rec.cles_recuperation(R).cle_privee,
                apres.enveloppe_amk_recuperation,
                account_id=COMPTE,
                incarnation=INCARNATION,
                vault_version=apres.vault_version,
                plancher_vault_version=0,
            )


class TestLaRecuperationForgee:
    def test_un_coffre_qui_ne_nomme_pas_la_cle_tiree_de_r_est_refuse(self):
        """§4.12 (« une pk_rec à lui » → serverKeyInvalid) et §1.1 A1, A4 —
        HPKE en mode Base n'authentifie pas l'expéditeur. L'appareil perdu
        connaît pk_rec ; avec le VPS, il scelle vers elle SON AMK et un
        trousseau qui nomme SA clé. La première passe l'acceptait, et la
        rotation suivante (récupération gardée) lui scellait l'AMK neuve."""
        cr = rec.cles_recuperation(R)
        honnete = _tourner(_coffre_initial())
        attaquant = X25519PrivateKey.generate()
        pk_attaquant = attaquant.public_key().public_bytes_raw()
        amk_forgee = bytes([0xAA]) * 32
        forge = tr.Trousseau(
            current_epoch=1,
            epochs={1: bytes([0xBB]) * 32},
            id_key=bytes([0xCC]) * 32,
            recovery_public_key=pk_attaquant,
        )
        w = honnete.vault_version + 1
        env_06 = env.sceller_amk_recuperation(
            cr.cle_publique,
            amk_forgee,
            account_id=COMPTE,
            incarnation=INCARNATION,
            vault_version=w,
        )
        env_05 = env.sceller_trousseau_brut(
            cles.cle_trousseau(amk_forgee),
            tr.serialiser(forge),
            account_id=COMPTE,
            incarnation=INCARNATION,
            keyring_version=w,
            vault_version=w,
        )
        with pytest.raises(tr.CleServeurInvalide) as exc:
            tr.ouvrir_coffre_par_recuperation(
                cr.cle_privee,
                enveloppe_amk_recuperation=env_06,
                enveloppe_trousseau=env_05,
                account_id=COMPTE,
                incarnation=INCARNATION,
                vault_version=w,
                keyring_version=w,
                plancher_vault_version=honnete.vault_version,
                plancher_keyring_version=honnete.keyring_version,
            )
        assert exc.value.code == "serverKeyInvalid", "le code du §4.12"

    def test_un_trousseau_sans_cle_de_recuperation_est_refuse(self):
        """§4.12 — un trousseau ``recoveryPublicKey: null`` ouvert par R
        ne peut pas venir du compte : la rotation qui retire la clé ne
        scelle plus de type 06."""
        cr = rec.cles_recuperation(R)
        amk = bytes([0xAA]) * 32
        forge = tr.nouveau_trousseau(None)
        env_06 = env.sceller_amk_recuperation(
            cr.cle_publique,
            amk,
            account_id=COMPTE,
            incarnation=INCARNATION,
            vault_version=1,
        )
        env_05 = env.sceller_trousseau_brut(
            cles.cle_trousseau(amk),
            tr.serialiser(forge),
            account_id=COMPTE,
            incarnation=INCARNATION,
            keyring_version=1,
            vault_version=1,
        )
        with pytest.raises(tr.CleServeurInvalide):
            tr.ouvrir_coffre_par_recuperation(
                cr.cle_privee,
                enveloppe_amk_recuperation=env_06,
                enveloppe_trousseau=env_05,
                account_id=COMPTE,
                incarnation=INCARNATION,
                vault_version=1,
                keyring_version=1,
                plancher_vault_version=1,
                plancher_keyring_version=1,
            )


class TestLePlancherDuTrousseau:
    def test_un_trousseau_sous_le_plancher_est_refuse(self):
        """§4.4 — un trousseau restauré d'avant une rotation n'a pas DEK_2 ;
        l'accepter ferait écrire sous une DEK que l'appareil perdu connaît."""
        coffre = _coffre_initial()
        with pytest.raises(env.CleServeurPerimee) as exc:
            tr.ouvrir_trousseau(
                coffre.amk,
                coffre.enveloppe_trousseau,
                account_id=COMPTE,
                incarnation=INCARNATION,
                keyring_version=1,
                vault_version=1,
                plancher_keyring_version=2,
                plancher_vault_version=1,
            )
        assert exc.value.code == "serverKeyStale", "le code doit être serverKeyStale"

    def test_un_trousseau_sous_le_plancher_de_vault_version_est_refuse(self):
        """§4.4 — le plancher de ``w`` vaut aussi pour le trousseau SEUL :
        sa ``keyringVersion`` peut être au plancher alors que le coffre qui
        le porte a été remplacé depuis."""
        coffre = _coffre_initial()
        with pytest.raises(env.CleServeurPerimee):
            tr.ouvrir_trousseau(
                coffre.amk,
                coffre.enveloppe_trousseau,
                account_id=COMPTE,
                incarnation=INCARNATION,
                keyring_version=1,
                vault_version=1,
                plancher_keyring_version=1,
                plancher_vault_version=2,
            )


class TestLaReinitialisation:
    def test_le_coffre_de_l_incarnation_precedente_est_refuse(self):
        """§6 bis (Constat 19) — après ``reset/complete``, le coffre neuf
        repart à ``w`` = ``r`` = 1 et l'appareil, lié à ``(compte,
        incarnation)``, vide ses planchers. Le VPS rejoue alors le coffre
        d'avant : mêmes versions, et même KEK si le mot de passe n'a pas
        changé. Seule l'incarnation dans l'AAD le distingue du nouveau —
        pourvu que l'appareil passe la SIENNE, jamais celle que le VPS
        annonce. Chaque enveloppe doit refuser par elle-même : un trousseau
        qui refuse ne prouve rien de l'AMK qui l'accompagne."""
        ancien = _coffre_initial()
        neuf = tr.creer_coffre(
            KEK_ANCIENNE,
            account_id=COMPTE,
            incarnation=INCARNATION + 1,
            kdf_version=1,
            recovery_public_key=rec.cles_recuperation(R).cle_publique,
        )
        assert (ancien.vault_version, ancien.keyring_version) == (
            neuf.vault_version,
            neuf.keyring_version,
        ), "les deux coffres portent w = r = 1 : les versions ne les séparent pas"
        contexte = {
            "account_id": COMPTE,
            "incarnation": INCARNATION + 1,
            "kdf_version": 1,
            "vault_version": 1,
            "keyring_version": 1,
            "plancher_vault_version": 0,
            "plancher_keyring_version": 0,
        }
        amk, _ = tr.ouvrir_coffre(
            KEK_ANCIENNE,
            enveloppe_amk=neuf.enveloppe_amk,
            enveloppe_trousseau=neuf.enveloppe_trousseau,
            **contexte,
        )
        assert amk == neuf.amk, "témoin : le coffre neuf s'ouvre"
        with pytest.raises(env.EnveloppeIllisible):
            tr.ouvrir_coffre(
                KEK_ANCIENNE,
                enveloppe_amk=ancien.enveloppe_amk,
                enveloppe_trousseau=ancien.enveloppe_trousseau,
                **contexte,
            )
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk(
                KEK_ANCIENNE,
                ancien.enveloppe_amk,
                account_id=COMPTE,
                incarnation=INCARNATION + 1,
                kdf_version=1,
                vault_version=1,
                plancher_vault_version=0,
            )
        with pytest.raises(env.EnveloppeIllisible):
            tr.ouvrir_trousseau(
                ancien.amk,
                ancien.enveloppe_trousseau,
                **{k: v for k, v in contexte.items() if k != "kdf_version"},
            )

    def test_la_rotation_garde_l_incarnation_qu_on_lui_donne(self):
        """§6 bis (Constat 19) — la première rotation après une
        réinitialisation (changement de mot de passe, appareil déconnecté,
        D21) scelle sous l'incarnation courante. Scellé sous 1 en dur, le
        coffre tourné ne s'ouvrirait plus sous la 2 (compte bloqué), ou
        s'ouvrirait sous la 1 et le rejeu du coffre d'avant serait rouvert,
        dans les deux cas en silence."""
        incarnation = INCARNATION + 1
        neuf = tr.creer_coffre(
            KEK_ANCIENNE,
            account_id=COMPTE,
            incarnation=incarnation,
            kdf_version=1,
            recovery_public_key=rec.cles_recuperation(R).cle_publique,
        )
        tourne = _tourner(neuf, incarnation=incarnation)
        assert (tourne.vault_version, tourne.keyring_version) == (2, 2), (
            "la rotation monte w et r de 1"
        )
        contexte = {
            "account_id": COMPTE,
            "kdf_version": 1,
            "vault_version": 2,
            "keyring_version": 2,
            "plancher_vault_version": 2,
            "plancher_keyring_version": 2,
        }
        amk, _ = tr.ouvrir_coffre(
            KEK_NOUVELLE,
            enveloppe_amk=tourne.enveloppe_amk,
            enveloppe_trousseau=tourne.enveloppe_trousseau,
            incarnation=incarnation,
            **contexte,
        )
        assert amk == tourne.amk, "le coffre tourné s'ouvre sous l'incarnation 2"
        amk_r, _ = tr.ouvrir_coffre_par_recuperation(
            rec.cles_recuperation(R).cle_privee,
            enveloppe_amk_recuperation=tourne.enveloppe_amk_recuperation,
            enveloppe_trousseau=tourne.enveloppe_trousseau,
            incarnation=incarnation,
            **{k: v for k, v in contexte.items() if k != "kdf_version"},
        )
        assert amk_r == tourne.amk, "R rouvre le coffre tourné sous l'incarnation 2"
        with pytest.raises(env.EnveloppeIllisible):
            tr.ouvrir_coffre(
                KEK_NOUVELLE,
                enveloppe_amk=tourne.enveloppe_amk,
                enveloppe_trousseau=tourne.enveloppe_trousseau,
                incarnation=INCARNATION,
                **contexte,
            )

    def test_la_recuperation_de_l_incarnation_precedente_est_refusee(self):
        """§6 bis (Constat 19) — la même R survit à une réinitialisation
        qui la garde : l'AMK d'avant, scellée vers elle, ne doit pas se
        rouvrir sous l'incarnation nouvelle. Le témoin positif d'abord : un
        refus seul se satisfait aussi d'une R qui n'ouvre plus RIEN après la
        réinitialisation, et les Réglages afficheraient encore « 1 moyen de
        secours » (§5, ne jamais faire semblant)."""
        cle_privee = rec.cles_recuperation(R).cle_privee
        ancien = _coffre_initial()
        neuf = tr.creer_coffre(
            KEK_NOUVELLE,
            account_id=COMPTE,
            incarnation=INCARNATION + 1,
            kdf_version=1,
            recovery_public_key=rec.cles_recuperation(R).cle_publique,
        )
        contexte = {
            "account_id": COMPTE,
            "incarnation": INCARNATION + 1,
            "vault_version": 1,
            "keyring_version": 1,
            "plancher_vault_version": 0,
            "plancher_keyring_version": 0,
        }
        amk, _ = tr.ouvrir_coffre_par_recuperation(
            cle_privee,
            enveloppe_amk_recuperation=neuf.enveloppe_amk_recuperation,
            enveloppe_trousseau=neuf.enveloppe_trousseau,
            **contexte,
        )
        assert amk == neuf.amk, "témoin : R rouvre le coffre de l'incarnation 2"
        with pytest.raises(env.EnveloppeIllisible):
            tr.ouvrir_coffre_par_recuperation(
                cle_privee,
                enveloppe_amk_recuperation=ancien.enveloppe_amk_recuperation,
                enveloppe_trousseau=ancien.enveloppe_trousseau,
                **contexte,
            )
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk_recuperation(
                cle_privee,
                ancien.enveloppe_amk_recuperation,
                account_id=COMPTE,
                incarnation=INCARNATION + 1,
                vault_version=1,
                plancher_vault_version=0,
            )

    @pytest.mark.parametrize(
        "fonction",
        [
            tr.creer_coffre,
            tr.faire_tourner_les_cles,
            tr.ouvrir_trousseau,
            tr.ouvrir_coffre,
            tr.ouvrir_coffre_par_recuperation,
        ],
        ids=lambda f: f.__name__,
    )
    def test_l_incarnation_est_nommee_et_sans_defaut(self, fonction):
        """§6 bis (Constat 19) — un défaut à 1 aurait scellé chaque coffre
        après une réinitialisation sous l'incarnation 1, en silence."""
        parametre = inspect.signature(fonction).parameters["incarnation"]
        assert parametre.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{fonction.__name__} : incarnation doit être nommée"
        )
        assert parametre.default is inspect.Parameter.empty, (
            f"{fonction.__name__} : incarnation ne doit pas avoir de défaut"
        )


class TestRienNeSImprime:
    def test_ni_le_coffre_ni_le_trousseau_n_ecrivent_de_cle(self):
        """§2.10 — un ``logger.debug(coffre)`` ne doit écrire ni l'AMK, ni
        une DEK, ni K_id, ni une enveloppe. Aucun test ne le gardait."""
        coffre = _coffre_initial()
        texte = repr(coffre)
        secrets = {
            "amk": coffre.amk,
            "DEK_1": coffre.trousseau.epochs[1],
            "idKey": coffre.trousseau.id_key,
            "enveloppe_amk": coffre.enveloppe_amk,
            "enveloppe_trousseau": coffre.enveloppe_trousseau,
        }
        for nom, valeur in secrets.items():
            assert repr(valeur) not in texte, f"repr du coffre contient {nom}"
        for champ in ("amk=", "epochs=", "id_key=", "enveloppe_amk="):
            assert champ not in texte, f"repr du coffre nomme {champ}"


class TestLesPieces:
    def test_piece_id_differe_d_une_epoque_a_l_autre(self):
        """§2.2 et §4.7 — après une rotation, la même image change
        d'identifiant et repart sous la nouvelle DEK."""
        apres = _tourner(_coffre_initial())
        p1 = apres.trousseau.identifiant_piece(IMAGE, 1)
        p2 = apres.trousseau.identifiant_piece(IMAGE)
        assert p1 != p2, "pieceId doit dépendre de l'époque"
        assert p2 == apres.trousseau.identifiant_piece(IMAGE, 2), "stable dans l'époque"


class TestLObjetPermute:
    def test_un_clair_scelle_sous_l_identifiant_d_un_autre_est_refuse(self):
        """§2.5 — l'objectId est recalculé à l'ouverture ; un écart met
        l'objet en quarantaine « permuté » au lieu de l'ingérer à la place
        d'une autre conversation."""
        t = _coffre_initial().trousseau
        oid_a = t.identifiant_objet("conversations", "a")
        blob = env.sceller_objet(
            t.dek_courante,
            env.encoder_clair(env.clair_objet("conversations", "b", {})),
            account_id=COMPTE,
            incarnation=1,
            object_id=oid_a,
            rev=1,
            key_epoch=t.current_epoch,
        )
        with pytest.raises(tr.ObjetPermute) as exc:
            t.ouvrir_objet(
                blob, account_id=COMPTE, incarnation=1, object_id=oid_a, rev=1
            )
        assert exc.value.code == "objectPermuted", "le code doit être objectPermuted"


class TestLaSerialisation:
    def test_l_aller_retour_est_exact(self):
        """§2.2 — le trousseau relu doit être celui qu'on a écrit."""
        t = _tourner(_coffre_initial()).trousseau
        assert tr.deserialiser(tr.serialiser(t)) == t, "aller-retour exact"

    def test_ses_cles_sont_en_anglais_camel_case(self):
        """CLAUDE.md §3 — un champ en snake_case ou en français se lit
        ``undefined`` de l'autre côté, en silence."""
        clair = json.loads(tr.serialiser(_coffre_initial().trousseau))
        assert set(clair) == {
            "v",
            "currentEpoch",
            "epochs",
            "idKey",
            "recoveryPublicKey",
        }, "clés du trousseau figées par le §2.2"
        assert all(re.fullmatch(r"[a-z][A-Za-z0-9]*", k) for k in clair), (
            "camelCase anglais"
        )

    @pytest.mark.parametrize(
        "alteration",
        [
            lambda c: c.update(extra=1),
            lambda c: c.update(v=2),
            lambda c: c.update(v=True),
            lambda c: c.update(currentEpoch=3),
            lambda c: c["epochs"].update({"2": c["epochs"]["1"]}),
            lambda c: c.update(v=1.0),
            lambda c: c.update(idKey=c["idKey"][:20] + "\n" + c["idKey"][20:]),
            lambda c: c.update(epochs={"01": c["epochs"]["1"]}),
            lambda c: c.update(idKey="pas du base64!"),
            lambda c: c.update(idKey="AAAA"),
            lambda c: c.pop("recoveryPublicKey"),
        ],
        ids=[
            "cle-inconnue",
            "version-2",
            "version-bool",
            "epoque-absente",
            "courante-sous-le-max",
            "version-flottante",
            "base64-parasite",
            "epoque-01",
            "base64",
            "longueur",
            "cle-manquante",
        ],
    )
    def test_un_trousseau_mal_forme_est_refuse(self, alteration):
        """§2.2 — un trousseau accepté à moitié écrirait sous une DEK
        fausse ; tout écart de forme est refusé en bloc. « courante = 1,
        epochs = {1, 2} » faisait écrire sous DEK_1 et la rotation écrasait
        DEK_2 en silence (24/09/2026)."""
        clair = json.loads(tr.serialiser(_coffre_initial().trousseau))
        alteration(clair)
        with pytest.raises(tr.TrousseauInvalide):
            tr.deserialiser(json.dumps(clair).encode())

    def test_une_cle_en_double_est_refusee(self):
        """§2.2 — ``json.loads`` garde la dernière occurrence, d'autres
        analyseurs la première : le même trousseau se lirait deux fois."""
        octets = tr.serialiser(_coffre_initial().trousseau)
        double = octets[:-1] + b',"currentEpoch":1}'
        with pytest.raises(tr.TrousseauInvalide):
            tr.deserialiser(double)

    def test_la_base64_parasite_a_la_bonne_longueur(self):
        """§2.2 — contrôle du cas « base64-parasite » : sans
        ``validate=True``, le « \\n » est ignoré et la clé décodée fait
        bien 32 o. Le refus vient donc de la base64 stricte, pas de la
        longueur."""
        texte = json.loads(tr.serialiser(_coffre_initial().trousseau))["idKey"]
        parasite = texte[:20] + "\n" + texte[20:]
        assert len(base64.b64decode(parasite)) == 32, "32 o une fois le \\n ignoré"
