"""La clé de récupération : format, saisie tolérante, scellement HPKE.

Conception : ``docs/development/compte-chiffre.md`` §2.2 et §2.7, étape 1
du §6.
"""

from __future__ import annotations

import pytest

from diapason.compte import cles
from diapason.compte import enveloppe as env
from diapason.compte import recuperation as rec

R = bytes(range(16))
AMK = bytes([5]) * 32


class TestLeFormat:
    def test_huit_groupes_de_quatre_en_crockford(self):
        """§2.7 — 16 o de R et 4 o de contrôle : 32 caractères, 8 groupes."""
        texte = rec.formater_cle_recuperation(R)
        groupes = texte.split("-")
        assert len(groupes) == 8 and all(len(g) == 4 for g in groupes), "8 groupes de 4"
        assert set("".join(groupes)) <= set(rec.ALPHABET_CROCKFORD), (
            "alphabet Crockford seul"
        )

    def test_l_aller_retour_rend_r(self):
        """§2.7 — la clé notée sur papier doit redonner R, sinon le compte
        est perdu avec elle."""
        assert rec.lire_cle_recuperation(rec.formater_cle_recuperation(R)) == R, (
            "R doit revenir"
        )

    def test_la_saisie_est_tolerante(self):
        """§2.7 — tirets et espaces ignorés, O lu 0, I et L lus 1, casse et
        pleine chasse indifférentes : une clé recopiée à la main ne doit
        pas être refusée pour une confusion que Crockford a prévue."""
        texte = rec.formater_cle_recuperation(R).replace("-", "")
        brouille = (
            " ".join(texte[i : i + 3] for i in range(0, len(texte), 3))
            .lower()
            .replace("0", "o")
            .replace("1", "l")
        )
        assert rec.lire_cle_recuperation(brouille) == R, (
            "la saisie brouillée doit être lue"
        )
        pleine = "".join(chr(ord(c) + 0xFEE0) for c in texte)
        assert rec.lire_cle_recuperation(pleine) == R, "la pleine chasse doit être lue"
        assert rec.lire_cle_recuperation(texte.replace("1", "I")) == R, (
            "I doit être lu 1"
        )

    def test_une_faute_de_frappe_est_detectee_a_chaque_position(self):
        """§2.7 — la faute est détectée LOCALEMENT, avant tout appel
        réseau : sinon chaque essai compterait dans les délais de /login."""
        texte = rec.formater_cle_recuperation(R).replace("-", "")
        for i, c in enumerate(texte):
            autre = "7" if c != "7" else "8"
            faute = texte[:i] + autre + texte[i + 1 :]
            with pytest.raises(rec.CleRecuperationInvalide) as exc:
                rec.lire_cle_recuperation(faute)
            assert exc.value.code == "recoveryKeyInvalid", (
                f"position {i} : code attendu"
            )

    @pytest.mark.parametrize("saisie", ["", "ABCD", "U" * 32, "0" * 31, "0" * 33])
    def test_une_saisie_mal_formee_est_refusee(self, saisie):
        """§2.7 — U n'est pas dans l'alphabet ; une longueur fausse est une faute."""
        with pytest.raises(rec.CleRecuperationInvalide):
            rec.lire_cle_recuperation(saisie)


class TestLesClesDerivees:
    def test_elles_sont_deterministes(self):
        """§2.2 — la même R, notée sur papier, doit redonner la même paire."""
        a, b = rec.cles_recuperation(R), rec.cles_recuperation(R)
        assert a.cle_publique == b.cle_publique, "pk_rec doit être stable"
        assert a.recovery_auth_key == b.recovery_auth_key, "recoveryAuthKey stable"

    def test_recovery_auth_key_n_est_pas_la_cle_privee(self):
        """§2.2 et §2.9 — recoveryAuthKey part au VPS. Si elle valait la
        graine X25519, le VPS tiendrait sk_rec et ouvrirait toute AMK
        scellée vers la récupération. La première passe ne la comparait
        qu'à la clé PUBLIQUE : seul le vecteur l'aurait vu, et une
        régénération « dans le même commit » l'aurait fait taire."""
        a = rec.cles_recuperation(R)
        graine = cles.hkdf(R, cles.INFO_RECUPERATION_X25519)
        assert a.recovery_auth_key != graine, "recoveryAuthKey ≠ graine X25519"
        assert a.recovery_auth_key != a.cle_privee.private_bytes_raw(), (
            "recoveryAuthKey ≠ sk_rec"
        )
        assert a.recovery_auth_key != a.cle_publique, "recoveryAuthKey ≠ pk_rec"

    def test_les_info_hkdf_sont_deux_a_deux_distinctes(self):
        """§2.2 — deux rôles qui partageraient un ``info`` partageraient
        leur clé ; c'est la seule séparation entre ce qui part au VPS et ce
        qui ne quitte jamais l'appareil."""
        infos = [getattr(cles, n) for n in dir(cles) if n.startswith("INFO_")]
        assert len(infos) >= 7, "les sept info du §2.2"
        assert len(set(infos)) == len(infos), "chaque info HKDF doit être unique"
        assert all(i.startswith(cles.PREFIXE_INFO) for i in infos), (
            "préfixe diapason/compte/v1/ : aucun recoupement avec le maillage"
        )

    def test_elles_ne_s_impriment_pas(self):
        """§2.10 — un ``logger.debug`` ne doit écrire ni recoveryAuthKey ni
        sk_rec. La première passe comparait à ``.hex()``, que ``repr``
        n'écrit jamais : le test passait sans ``repr=False``."""
        a = rec.cles_recuperation(R)
        texte = repr(a)
        assert repr(a.recovery_auth_key) not in texte, "recoveryAuthKey imprimée"
        assert "recovery_auth_key=" not in texte, "recoveryAuthKey nommée"
        assert "cle_privee=" not in texte, "sk_rec nommée"


class TestLeScellementHpke:
    def test_on_scelle_sans_r_et_on_ouvre_avec_r(self):
        """§2.2 — faire tourner l'AMK exige de la resceller pour la
        récupération alors que R n'est jamais stockée : on scelle vers
        pk_rec seule, et seule R, ressaisie, rouvre."""
        pk = rec.cles_recuperation(R).cle_publique
        blob = env.sceller_amk_recuperation(
            pk, AMK, account_id="acc_1", incarnation=1, vault_version=4
        )
        assert len(blob) == 86, "§2.5 : 86 o pour une AMK"
        r_ressaisie = rec.lire_cle_recuperation(rec.formater_cle_recuperation(R))
        sk = rec.cles_recuperation(r_ressaisie).cle_privee
        ouverte = env.ouvrir_amk_recuperation(
            sk,
            blob,
            account_id="acc_1",
            incarnation=1,
            vault_version=4,
            plancher_vault_version=4,
        )
        assert ouverte == AMK, "R doit rouvrir l'AMK scellée vers pk_rec"

    def test_une_autre_r_n_ouvre_pas(self):
        """§2.7 — une clé de récupération remplacée ne rouvre plus."""
        pk = rec.cles_recuperation(R).cle_publique
        blob = env.sceller_amk_recuperation(
            pk, AMK, account_id="acc_1", incarnation=1, vault_version=1
        )
        autre = rec.cles_recuperation(bytes(16)).cle_privee
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk_recuperation(
                autre,
                blob,
                account_id="acc_1",
                incarnation=1,
                vault_version=1,
                plancher_vault_version=1,
            )

    @pytest.mark.parametrize(
        "contexte",
        [
            {"account_id": "acc_2", "incarnation": 1, "vault_version": 1},
            {"account_id": "acc_1", "incarnation": 1, "vault_version": 2},
            {"account_id": "acc_1", "incarnation": 2, "vault_version": 1},
        ],
        ids=["compte", "vaultVersion", "incarnation"],
    )
    def test_le_contexte_passe_par_info(self, contexte):
        """§2.3 — l'API HPKE n'a pas d'AAD : compte, incarnation et
        vaultVersion passent par ``info``, sinon une AMK scellée d'un compte
        ouvrirait l'autre, ou celle d'avant une réinitialisation la suivante."""
        pk = rec.cles_recuperation(R).cle_publique
        blob = env.sceller_amk_recuperation(
            pk, AMK, account_id="acc_1", incarnation=1, vault_version=1
        )
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk_recuperation(
                rec.cles_recuperation(R).cle_privee,
                blob,
                plancher_vault_version=1,
                **contexte,
            )

    def test_une_amk_scellee_sous_le_plancher_est_refusee(self):
        """§4.4 — une AMK scellée d'avant une rotation, ramenée par une
        restauration, donnerait l'ancienne AMK à qui a l'ancienne R."""
        pk = rec.cles_recuperation(R).cle_publique
        blob = env.sceller_amk_recuperation(
            pk, AMK, account_id="acc_1", incarnation=1, vault_version=1
        )
        with pytest.raises(env.CleServeurPerimee):
            env.ouvrir_amk_recuperation(
                rec.cles_recuperation(R).cle_privee,
                blob,
                account_id="acc_1",
                incarnation=1,
                vault_version=1,
                plancher_vault_version=2,
            )

    @pytest.mark.parametrize("position", [0, 1, 2, 5, 6, 40, -1])
    def test_un_octet_modifie_est_refuse(self, position):
        """§4.12 — en-tête, enc, chiffré et tag sont tous authentifiés."""
        pk = rec.cles_recuperation(R).cle_publique
        blob = bytearray(
            env.sceller_amk_recuperation(
                pk, AMK, account_id="acc_1", incarnation=1, vault_version=1
            )
        )
        blob[position] ^= 0x01
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk_recuperation(
                rec.cles_recuperation(R).cle_privee,
                bytes(blob),
                account_id="acc_1",
                incarnation=1,
                vault_version=1,
                plancher_vault_version=1,
            )
