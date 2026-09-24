"""Les vecteurs de contrat du compte chiffré sont encore ceux du code.

Conception : ``docs/development/compte-chiffre.md`` §2.12, étape 1 du §6.
Un format qui change d'un octet rend illisible tout ce qui a été écrit
avant, sur chaque appareil et sur le VPS, sans que rien ne le signale avant
le premier déverrouillage raté. Régénérer avec
``scripts/gen_vecteurs_compte.py`` dans le même commit que le format.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hpke
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from diapason.compte import cles
from diapason.compte import enveloppe as env
from diapason.compte import recuperation as rec

RACINE = Path(__file__).resolve().parents[2]
FICHIER = RACINE / "tests" / "contract" / "vecteurs_compte.json"
VECTEURS = json.loads(FICHIER.read_text("utf-8"))
_CAMEL = re.compile(r"[a-z][A-Za-z0-9]*")


def _generateur():
    chemin = RACINE / "scripts" / "gen_vecteurs_compte.py"
    spec = importlib.util.spec_from_file_location("gen_vecteurs_compte", chemin)
    assert spec and spec.loader, f"générateur introuvable : {chemin}"
    # Pas d'inscription dans sys.modules : le script n'a aucune dataclass
    # qui en aurait besoin, et l'inscrire fuyait d'un test à l'autre.
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLaRegeneration:
    def test_les_vecteurs_se_regenerent_a_l_identique(self):
        """§2.12 — si le code ne reproduit plus le fichier, le format a
        changé sans régénération : les blobs déjà écrits ne s'ouvriraient
        plus. Argon2id tourne ici aux vrais paramètres, une fois. On compare
        les OCTETS que ``main()`` écrirait : la première passe comparait
        des dictionnaires et laissait dériver la sérialisation."""
        generateur = _generateur()
        blob_hpke = VECTEURS["recoverySealed"]["blob"]
        octets = generateur.serialiser_vecteurs(generateur.calculer_vecteurs(blob_hpke))
        assert octets == FICHIER.read_bytes(), (
            "le code ne reproduit plus tests/contract/vecteurs_compte.json"
        )


class TestLesVecteursSOuvrent:
    def test_chaque_enveloppe_s_ouvre_depuis_ses_seules_entrees(self):
        """§2.5 — vérification indépendante du chemin de scellement : sous-clé,
        AAD, AES-GCM puis cadre, recalculés depuis les entrées du vecteur."""
        types = set()
        for v in VECTEURS["envelopes"]:
            blob = bytes.fromhex(v["blob"])
            sel, nonce = bytes.fromhex(v["salt"]), bytes.fromhex(v["nonce"])
            assert blob[6:38] == sel and blob[38:50] == nonce, f"{v['name']} : en-tête"
            sous_cle = env.sous_cle(bytes.fromhex(v["baseKey"]), v["type"], sel)
            assert sous_cle.hex() == v["subkey"], f"{v['name']} : sous-clé HKDF"
            aad = env.aad(blob[:50], v["aadFields"])
            assert aad.hex() == v["aad"], f"{v['name']} : AAD"
            cadre = AESGCM(sous_cle).decrypt(nonce, blob[50:], aad)
            plancher = {1: env.PLANCHER_OBJET, 2: env.PLANCHER_PIECE}.get(v["type"], 0)
            assert env.desencadrer(cadre, plancher).hex() == v["plaintext"], (
                f"{v['name']} : clair"
            )
            types.add(v["type"])
        assert types == {1, 2, 3, 4, 5}, "une enveloppe de chaque type 01 à 05"

    def test_l_enveloppe_hpke_s_ouvre_avec_l_info_du_vecteur(self):
        """§2.3 et §2.12 — un client Dart ou TypeScript ouvrira le blob avec
        l'``info`` ÉCRIT dans le vecteur, pas avec notre code. La première
        passe calculait cet ``info`` à part : changé dans ``enveloppe``, il
        restait périmé dans le fichier, blob illisible et suite verte."""
        v = VECTEURS["recoverySealed"]
        sk = X25519PrivateKey.from_private_bytes(
            bytes.fromhex(VECTEURS["recovery"]["x25519Seed"])
        )
        suite = hpke.Suite(hpke.KEM.X25519, hpke.KDF.HKDF_SHA256, hpke.AEAD.AES_256_GCM)
        blob = bytes.fromhex(v["blob"])
        info = bytes.fromhex(v["info"])
        assert blob[:6] == info[:6], "le blob porte l'en-tête écrit dans info"
        assert suite.decrypt(blob[6:], sk, info).hex() == v["amk"], (
            "l'AMK doit s'ouvrir avec l'info du vecteur seul"
        )
        assert (
            sk.public_key().public_bytes_raw().hex()
            == (VECTEURS["recovery"]["publicKey"])
        ), "la graine X25519 du vecteur donne la pk_rec du vecteur"

    def test_l_enveloppe_hpke_s_ouvre_par_dechiffrement_seul(self):
        """§2.12 — HPKE tire son aléa en interne : son vecteur se vérifie en
        ouvrant, avec R relue depuis le texte noté."""
        v = VECTEURS["recoverySealed"]
        r = rec.lire_cle_recuperation(VECTEURS["recovery"]["text"])
        amk = env.ouvrir_amk_recuperation(
            rec.cles_recuperation(r).cle_privee,
            bytes.fromhex(v["blob"]),
            account_id=v["accountId"],
            vault_version=v["vaultVersion"],
            plancher_vault_version=v["vaultVersion"],
        )
        assert amk.hex() == v["amk"], "l'AMK scellée doit se rouvrir avec R"

    def test_les_trois_ecritures_du_mot_de_passe_sont_distinctes(self):
        """§2.4 — un éditeur qui normaliserait le fichier en NFC viderait le
        vecteur NFD de son sens ; on vérifie qu'il porte bien trois écritures."""
        mots = VECTEURS["argon2id"]["passwords"]
        assert len({mots["nfc"], mots["nfd"], mots["fullwidth"]}) == 3, (
            "trois écritures"
        )
        for nom, mdp in mots.items():
            assert (
                cles.normaliser_mot_de_passe(mdp).hex()
                == (VECTEURS["argon2id"]["passwordUtf8"])
            ), f"{nom} doit se normaliser vers le même UTF-8"

    def test_padme_couvre_douze_longueurs(self):
        """§2.12 — Padmé sur 12 longueurs."""
        assert len(VECTEURS["padme"]) == 12, "12 longueurs"
        for v in VECTEURS["padme"]:
            assert env.padme(v["length"]) == v["padded"], f"padme({v['length']})"


class TestLesClesSontEnAnglais:
    @pytest.mark.parametrize("nom", ["object", "tombstone", "keyring"])
    def test_les_cles_du_clair_et_du_trousseau_sont_en_anglais(self, nom):
        """§2.5 et CLAUDE.md §3 — les clés sont fixées AVANT le premier
        vecteur : les renommer après rendrait illisible tout l'existant."""
        attendues = {
            "object": {"v", "collection", "id", "schema", "data"},
            "tombstone": {"v", "collection", "id", "schema", "deleted"},
            "keyring": {"v", "currentEpoch", "epochs", "idKey", "recoveryPublicKey"},
        }[nom]
        clair = json.loads(VECTEURS["plaintexts"][nom])
        assert set(clair) == attendues, f"clés du clair {nom}"
        assert all(_CAMEL.fullmatch(k) for k in clair), f"{nom} : camelCase anglais"
        if nom == "tombstone":
            assert set(clair["deleted"]) == {"deletedAt"}, "deletedAt en camelCase"

    def test_les_cles_du_fichier_de_vecteurs_sont_en_anglais(self):
        """CLAUDE.md §3 — le fichier sera relu par un autre langage."""

        def cles_de(noeud):
            if isinstance(noeud, dict):
                for k, v in noeud.items():
                    yield k
                    yield from cles_de(v)
            elif isinstance(noeud, list):
                for v in noeud:
                    yield from cles_de(v)

        mauvaises = [
            k for k in cles_de(VECTEURS) if not (_CAMEL.fullmatch(k) or k.isdigit())
        ]
        assert not mauvaises, f"clés hors camelCase : {mauvaises}"
