#!/usr/bin/env python3
"""Génère les vecteurs de contrat du compte chiffré.

Conception : ``docs/development/compte-chiffre.md`` §2.12. Un format de
chiffrement qui change d'un octet rend illisible tout ce qui a été écrit
avant — sur chaque appareil et sur le VPS — sans que rien ne le signale
avant le premier déverrouillage raté. Ces vecteurs figent chaque dérivation
et chaque enveloppe ; ``tests/compte/test_vecteurs.py`` vérifie que le code
les reproduit encore, octet pour octet.

Régénérer dans le MÊME commit que tout changement de format :

    .venv/bin/python scripts/gen_vecteurs_compte.py

Toutes les entrées « aléatoires » sont tirées de ``SHA-256("vecteur/" ‖
étiquette)`` : la régénération est déterministe. Seule exception, l'enveloppe
HPKE de type 06 : HPKE tire son aléa en interne, son blob ne se vérifie que
par déchiffrement. Le script garde donc le blob existant tant qu'il s'ouvre
encore sur l'AMK attendue, et n'en frappe un neuf que sinon.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from diapason.compte import cles, enveloppe, recuperation, trousseau  # noqa: E402

DESTINATION = Path(__file__).resolve().parent.parent / "tests" / "contract"
DESTINATION = DESTINATION / "vecteurs_compte.json"

COURRIEL = "  Alice.Martin@Exemple.ORG "
# « Café crème, été 2026 ! » : un é en NFC, le même en NFD (e + U+0301), et
# une version pleine chasse (U+FF21…, espace idéographique U+3000) que NFKC
# ramène à la même chaîne.
# Écrits en échappements : un éditeur qui normalise en NFC effacerait sinon
# l'écart entre les trois sans que rien ne le montre (24/09/2026).
MOT_DE_PASSE_NFC = "Caf\u00e9 cr\u00e8me, \u00e9t\u00e9 2026 !"
MOT_DE_PASSE_NFD = "Cafe\u0301 cre\u0300me, e\u0301te\u0301 2026 !"
MOT_DE_PASSE_PLEINE_CHASSE = (
    "\uff23\uff41\uff46\u00e9\u3000\uff43\uff52\u00e8\uff4d\uff45\uff0c"
    "\u3000\u00e9\uff54\u00e9\u3000\uff12\uff10\uff12\uff16\u3000\uff01"
)
ACCOUNT_ID = "acc_vecteur_0001"
INCARNATION = 1
SESSION_ID = "ses_vecteur_0001"
COLLECTION = "conversations"
ID_LOCAL = "conv-vecteur-1"
# Longueurs de Padmé : petites, frontières de puissances de 2, et au-delà du
# plancher d'une pièce.
LONGUEURS_PADME = [1, 5, 9, 17, 100, 1000, 1024, 1025, 4096, 5000, 65537, 1000000]
# Une « image » qui finit par des zéros : ils doivent survivre (jamais de rstrip).
PIECE = b"\x89PNG\r\n\x1a\n" + bytes(range(1, 40)) + b"\x00\x00\x00\x00"


def fixe(etiquette: str, longueur: int = 32) -> bytes:
    return hashlib.sha256(b"vecteur/" + etiquette.encode("ascii")).digest()[:longueur]


def _hex(octets: bytes) -> str:
    return octets.hex()


def _vecteur_enveloppe(nom, type_, cle_base, clair, champs, blob, sel, nonce):
    en_tete = blob[: enveloppe.LONGUEUR_EN_TETE]
    return {
        "name": nom,
        "type": type_,
        "baseKey": _hex(cle_base),
        "salt": _hex(sel),
        "nonce": _hex(nonce),
        "subkey": _hex(enveloppe.sous_cle(cle_base, type_, sel)),
        "aadFields": champs,
        "aad": _hex(enveloppe.aad(en_tete, champs)),
        "plaintext": _hex(clair),
        "blob": _hex(blob),
    }


def _hpke(amk: bytes, r: bytes, vault_version: int, existant: str | None) -> str:
    cle_privee = recuperation.cles_recuperation(r).cle_privee
    if existant is not None:
        try:
            if (
                enveloppe.ouvrir_amk_recuperation(
                    cle_privee,
                    bytes.fromhex(existant),
                    account_id=ACCOUNT_ID,
                    vault_version=vault_version,
                    plancher_vault_version=vault_version,
                )
                == amk
            ):
                return existant
        except (enveloppe.EnveloppeIllisible, ValueError):
            pass
    pk = recuperation.cles_recuperation(r).cle_publique
    return _hex(
        enveloppe.sceller_amk_recuperation(
            pk, amk, account_id=ACCOUNT_ID, vault_version=vault_version
        )
    )


def calculer_vecteurs(hpke_existant: str | None = None) -> dict:
    # --- Argon2id aux vrais paramètres, trois écritures du même mot de passe.
    # Argon2id est déterministe : trois UTF-8 égaux donnent trois K_mdp
    # égaux. La première passe (24/09/2026) en lançait trois, soit 1 s de
    # plus par exécution de la suite pour ne rien prouver de plus.
    utf8 = {
        cles.normaliser_mot_de_passe(mdp)
        for mdp in (MOT_DE_PASSE_NFC, MOT_DE_PASSE_NFD, MOT_DE_PASSE_PLEINE_CHASSE)
    }
    if len(utf8) != 1:
        raise SystemExit("NFC, NFD et pleine chasse divergent : normalisation cassée")
    kdf_salt = fixe("kdfSalt")
    k = cles.etirer_mot_de_passe(MOT_DE_PASSE_NFC, COURRIEL, kdf_salt, 1)
    role = cles.cles_de_role(k)

    # --- Clés tirées de l'AMK, des DEK et de R
    amk = fixe("amk")
    dek_1, dek_2 = fixe("dek1"), fixe("dek2")
    id_key = fixe("idKey")
    r = fixe("recoveryKey", recuperation.LONGUEUR_R)
    rec = recuperation.cles_recuperation(r)
    k_trousseau = cles.cle_trousseau(amk)
    k_noms = cles.cle_noms_appareils(amk)

    # --- Trousseau à deux époques
    t = trousseau.Trousseau(
        current_epoch=2,
        epochs={1: dek_1, 2: dek_2},
        id_key=id_key,
        recovery_public_key=rec.cle_publique,
    )
    clair_trousseau = trousseau.serialiser(t)

    # --- Clair d'objet et identifiants
    clair_vivant = enveloppe.encoder_clair(
        enveloppe.clair_objet(
            COLLECTION,
            ID_LOCAL,
            {"id": ID_LOCAL, "title": "Vecteur", "updatedAt": 1790000000000},
        )
    )
    clair_tombale = enveloppe.encoder_clair(
        enveloppe.clair_tombale(COLLECTION, ID_LOCAL, 1790000000000)
    )
    object_id = cles.identifiant_objet(id_key, COLLECTION, ID_LOCAL)
    piece_id_1 = cles.identifiant_piece(cles.cle_piece(dek_1), PIECE)
    piece_id_2 = cles.identifiant_piece(cles.cle_piece(dek_2), PIECE)

    # --- Enveloppes 01 à 05, sel et nonce injectés
    enveloppes = []

    def ajouter(nom, type_, cle_base, clair, champs, fabrique):
        sel, nonce = fixe(f"sel/{nom}"), fixe(f"nonce/{nom}", 12)
        blob = fabrique(sel, nonce)
        enveloppes.append(
            _vecteur_enveloppe(nom, type_, cle_base, clair, champs, blob, sel, nonce)
        )

    ajouter(
        "object",
        enveloppe.TYPE_OBJET,
        dek_2,
        clair_vivant,
        {
            "a": ACCOUNT_ID,
            "e": 2,
            "i": INCARNATION,
            "o": object_id,
            "r": 3,
            "t": "object",
            "v": 1,
        },
        lambda s, n: enveloppe.sceller_objet(
            dek_2,
            clair_vivant,
            account_id=ACCOUNT_ID,
            incarnation=INCARNATION,
            object_id=object_id,
            rev=3,
            key_epoch=2,
            sel=s,
            nonce=n,
        ),
    )
    ajouter(
        "attachment",
        enveloppe.TYPE_PIECE,
        dek_2,
        PIECE,
        {
            "a": ACCOUNT_ID,
            "e": 2,
            "i": INCARNATION,
            "o": piece_id_2,
            "t": "attachment",
            "v": 1,
        },
        lambda s, n: enveloppe.sceller_piece(
            dek_2,
            PIECE,
            account_id=ACCOUNT_ID,
            incarnation=INCARNATION,
            piece_id=piece_id_2,
            key_epoch=2,
            sel=s,
            nonce=n,
        ),
    )
    ajouter(
        "amkPassword",
        enveloppe.TYPE_AMK_MOT_DE_PASSE,
        role.kek,
        amk,
        {"a": ACCOUNT_ID, "k": 1, "t": "amk", "u": "password", "w": 2},
        lambda s, n: enveloppe.envelopper_amk(
            role.kek,
            amk,
            account_id=ACCOUNT_ID,
            kdf_version=1,
            vault_version=2,
            sel=s,
            nonce=n,
        ),
    )
    nom_appareil = "MacBook de Vecteur"
    ajouter(
        "deviceName",
        enveloppe.TYPE_NOM_APPAREIL,
        k_noms,
        nom_appareil.encode("utf-8"),
        {"a": ACCOUNT_ID, "s": SESSION_ID, "t": "deviceName", "v": 1},
        lambda s, n: enveloppe.sceller_nom_appareil(
            k_noms,
            nom_appareil,
            account_id=ACCOUNT_ID,
            session_id=SESSION_ID,
            key_epoch=2,
            sel=s,
            nonce=n,
        ),
    )
    ajouter(
        "keyring",
        enveloppe.TYPE_TROUSSEAU,
        k_trousseau,
        clair_trousseau,
        {"a": ACCOUNT_ID, "r": 2, "t": "keyring", "v": 1, "w": 2},
        lambda s, n: enveloppe.sceller_trousseau_brut(
            k_trousseau,
            clair_trousseau,
            account_id=ACCOUNT_ID,
            keyring_version=2,
            vault_version=2,
            sel=s,
            nonce=n,
        ),
    )

    return {
        "comment": (
            "Vecteurs de contrat du compte chiffré (docs/development/"
            "compte-chiffre.md §2.12). Généré par scripts/gen_vecteurs_compte.py ;"
            " ne pas éditer à la main."
        ),
        "kdf": {
            "minVersion": cles.KDF_VERSION_MIN,
            "versions": {
                str(v): {
                    "memoryCost": m,
                    "iterations": i,
                    "lanes": p,
                    "length": cles.LONGUEUR_CLE,
                }
                for v, (m, i, p) in cles.VERSIONS_KDF.items()
            },
        },
        "argon2id": {
            "email": COURRIEL,
            "emailNormalized": cles.normaliser_courriel(COURRIEL),
            "kdfSalt": _hex(kdf_salt),
            "salt": _hex(cles.sel_argon2(COURRIEL, kdf_salt)),
            "kdfVersion": 1,
            "passwords": {
                "nfc": MOT_DE_PASSE_NFC,
                "nfd": MOT_DE_PASSE_NFD,
                "fullwidth": MOT_DE_PASSE_PLEINE_CHASSE,
            },
            "passwordUtf8": _hex(cles.normaliser_mot_de_passe(MOT_DE_PASSE_NFC)),
            "kMdp": _hex(k),
            "authKey": _hex(role.auth_key),
            "kek": _hex(role.kek),
        },
        "hkdf": {
            "amk": _hex(amk),
            "keyringKey": _hex(k_trousseau),
            "deviceNamesKey": _hex(k_noms),
            "dek1": _hex(dek_1),
            "dek2": _hex(dek_2),
            "pieceKey1": _hex(cles.cle_piece(dek_1)),
            "pieceKey2": _hex(cles.cle_piece(dek_2)),
        },
        "recovery": {
            "r": _hex(r),
            "check": _hex(recuperation.controle(r)),
            "text": recuperation.formater_cle_recuperation(r),
            "recoveryAuthKey": _hex(rec.recovery_auth_key),
            "x25519Seed": _hex(cles.hkdf(r, cles.INFO_RECUPERATION_X25519)),
            "publicKey": _hex(rec.cle_publique),
        },
        "identifiers": {
            "idKey": _hex(id_key),
            "collection": COLLECTION,
            "localId": ID_LOCAL,
            "objectId": object_id,
            "attachment": _hex(PIECE),
            "pieceIdEpoch1": piece_id_1,
            "pieceIdEpoch2": piece_id_2,
        },
        "padme": [{"length": n, "padded": enveloppe.padme(n)} for n in LONGUEURS_PADME],
        "plaintexts": {
            "object": clair_vivant.decode("utf-8"),
            "tombstone": clair_tombale.decode("utf-8"),
            "keyring": clair_trousseau.decode("utf-8"),
        },
        "envelopes": enveloppes,
        "recoverySealed": {
            "type": enveloppe.TYPE_AMK_RECUPERATION,
            "accountId": ACCOUNT_ID,
            "vaultVersion": 2,
            "amk": _hex(amk),
            # Pris du code, jamais recalculé à part : la première passe
            # l'écrivait en dur, et un ``info`` changé dans ``enveloppe``
            # laissait ici un ``info`` périmé sans qu'aucun test ne rougisse
            # (24/09/2026).
            "info": _hex(enveloppe.info_recuperation(ACCOUNT_ID, 2)),
            "blob": _hpke(amk, r, 2, hpke_existant),
        },
    }


def serialiser_vecteurs(vecteurs: dict) -> bytes:
    """Les octets exacts du fichier : le test les compare à ceux du disque."""
    return (json.dumps(vecteurs, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> None:
    existant = None
    if DESTINATION.exists():
        ancien = json.loads(DESTINATION.read_text(encoding="utf-8"))
        existant = ancien.get("recoverySealed", {}).get("blob")
    DESTINATION.write_bytes(serialiser_vecteurs(calculer_vecteurs(existant)))
    print(f"écrit : {DESTINATION}")


if __name__ == "__main__":
    main()
