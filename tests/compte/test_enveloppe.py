"""Le format d'enveloppe DPE1 : AAD, rembourrage, refus.

Conception : ``docs/development/compte-chiffre.md`` §2.5, §4.4 et §4.12,
étape 1 du §6. Chaque refus ici est un blob qu'un VPS hostile pourrait
servir : permuté, retouché, tronqué ou ramené d'une restauration.
"""

from __future__ import annotations

import struct

import pytest

from diapason.compte import enveloppe as env

DEK = bytes([1]) * 32
KEK = bytes([3]) * 32
K_NOMS = bytes([4]) * 32
CONTEXTE = {"account_id": "acc_1", "incarnation": 1, "object_id": "obj_1", "rev": 5}


def _objet(clair: bytes = b'{"v":1}', **surcharge) -> bytes:
    contexte = {**CONTEXTE, **surcharge}
    return env.sceller_objet(DEK, clair, key_epoch=2, **contexte)


def _ouvrir(blob: bytes, **surcharge) -> bytes:
    return env.ouvrir_objet(DEK, blob, **{**CONTEXTE, **surcharge})


class TestPadme:
    def test_padme_est_idempotent(self):
        """§2.5 — le VPS vérifie « taille − 66 ∈ Padmé » : une valeur de
        Padmé doit être son propre arrondi, sinon il refuserait nos blobs."""
        for longueur in list(range(1, 20000)) + [2**20 + 1, 10**7 + 3]:
            p = env.padme(longueur)
            assert env.padme(p) == p, f"padme({p}) doit valoir {p}"

    def test_le_surcout_ne_depasse_pas_douze_pour_cent(self):
        """§2.5 — Padmé borne le surcoût à 12 % ; au-delà, un rembourrage
        maison gaspillerait le quota de chacun."""
        for longueur in range(1, 1 << 17):
            p = env.padme(longueur)
            assert p >= longueur, "padme ne rétrécit jamais"
            assert (p - longueur) / longueur <= 0.12, f"surcoût > 12 % pour {longueur}"

    def test_padme_de_zero_est_refuse_par_sa_garde(self):
        """§2.5 — la formule n'a pas de sens pour 0. Sans la garde, Python
        lève déjà ``ValueError`` (décalage négatif) : la première passe ne
        testait donc rien ; on exige le message de la garde."""
        with pytest.raises(ValueError, match="longueur doit être ≥ 1"):
            env.padme(0)

    def test_un_clair_vide_fait_un_cadre_de_quatre_octets(self):
        """§2.5 — le cas réel de L = 0 : le cadre est l'uint32 seul."""
        assert env.taille_cadre(0, 0) == 4, "padme(4 + 0) = 4"
        assert env.desencadrer(env.encadrer(b"", 0), 0) == b"", "aller-retour vide"


class TestLeCadre:
    def test_les_zeros_finaux_d_un_binaire_sont_preserves(self):
        """§2.5 — ``rstrip(b"\\x00")`` (scellement.py:444-456) mangeait les
        derniers octets d'une image ; la longueur en tête dit où finit le clair."""
        image = b"\x89PNG\r\n\x1a\n" + bytes(range(1, 50)) + bytes(16)
        blob = env.sceller_piece(
            DEK, image, account_id="acc_1", incarnation=1, piece_id="p_1", key_epoch=2
        )
        ouvert = env.ouvrir_piece(
            DEK, blob, account_id="acc_1", incarnation=1, piece_id="p_1"
        )
        assert ouvert == image, "les 16 zéros finaux de l'image doivent survivre"

    def test_un_objet_court_a_la_taille_du_plancher(self):
        """§2.5 — plancher de 1 024 o : une conversation d'une ligne ne se
        distingue pas d'une conversation de dix."""
        assert len(_objet()) == 1024 + 66, "1 024 + 66 o"

    def test_une_piece_courte_a_la_taille_du_plancher(self):
        """§2.5 — plancher de 4 096 o pour une pièce."""
        blob = env.sceller_piece(
            DEK, b"x", account_id="acc_1", incarnation=1, piece_id="p_1", key_epoch=2
        )
        assert len(blob) == 4096 + 66, "4 096 + 66 o"

    def test_un_objet_long_est_arrondi_par_padme(self):
        """§2.5 — ce que le VPS vérifie : taille − 66 est une valeur de Padmé."""
        blob = _objet(b"x" * 5000)
        assert env.padme(len(blob) - env.SURCOUT) == len(blob) - env.SURCOUT, (
            "taille − 66 doit être une valeur de Padmé"
        )

    def test_des_zeros_de_rembourrage_non_nuls_sont_refuses(self):
        """§2.5 — les zéros sont VÉRIFIÉS : un rembourrage qui porterait des
        octets serait un canal caché, ou un cadre fabriqué."""
        cadre = bytearray(env.encadrer(b"clair", env.PLANCHER_OBJET))
        cadre[-1] = 1
        champs = {
            "a": "acc_1",
            "e": 2,
            "i": 1,
            "o": "obj_1",
            "r": 5,
            "t": "object",
            "v": 1,
        }
        blob = env._chiffrer(env.TYPE_OBJET, DEK, bytes(cadre), champs, 2, None, None)
        with pytest.raises(env.EnveloppeIllisible):
            _ouvrir(blob)

    def test_un_cadre_plus_grand_que_padme_est_refuse(self):
        """§2.5 — la taille du cadre est imposée par Padmé : un cadre bien
        formé mais allongé de zéros est un canal caché, ou une taille que le
        VPS n'aurait pas dû accepter."""
        cadre = env.encadrer(b"clair", env.PLANCHER_OBJET) + bytes(1024)
        champs = {
            "a": "acc_1",
            "e": 2,
            "i": 1,
            "o": "obj_1",
            "r": 5,
            "t": "object",
            "v": 1,
        }
        blob = env._chiffrer(env.TYPE_OBJET, DEK, cadre, champs, 2, None, None)
        with pytest.raises(env.EnveloppeIllisible):
            _ouvrir(blob)

    def test_une_longueur_de_cadre_mentie_est_refusee(self):
        """§2.5 — une longueur en tête qui déborde du cadre ne doit pas lire
        au-delà, ni rendre un clair tronqué."""
        cadre = struct.pack(">I", 2000) + bytes(1020)
        with pytest.raises(env.EnveloppeIllisible):
            env.desencadrer(cadre, env.PLANCHER_OBJET)


class TestAadCanonique:
    def test_elle_est_triee_compacte_et_utf8(self):
        """§2.5 — deux appareils doivent recalculer la même AAD, octet pour octet."""
        assert env.aad_canonique({"t": "é", "a": "x", "e": 1}) == (
            '{"a":"x","e":1,"t":"é"}'.encode()
        ), "JSON trié, compact, UTF-8 non échappé"

    @pytest.mark.parametrize("valeur", [1.5, b"octets", True, None, [1], {"x": 1}])
    def test_tout_autre_type_que_chaine_ou_entier_leve_type_error(self, valeur):
        """§2.5 — ``identity.canonical_bytes`` et son ``default=str`` auraient
        scellé ``"b'…'"`` en silence ; un float s'écrit différemment d'un
        langage à l'autre. Le message est exigé : sans la garde, ``json``
        lève lui-même ``TypeError`` sur des octets, et le test ne gardait
        rien pour ce cas."""
        with pytest.raises(TypeError, match="valeur d'AAD refusée"):
            env.aad_canonique({"a": valeur})


class TestLesRefus:
    def test_l_aller_retour_fonctionne(self):
        """§2.5 — sans permutation, le blob s'ouvre : sinon chaque refus
        ci-dessous prouverait seulement que rien ne s'ouvre jamais."""
        assert _ouvrir(_objet(b"bonjour")) == b"bonjour", "le clair doit revenir"

    @pytest.mark.parametrize(
        "permutation",
        [
            {"object_id": "obj_2"},
            {"account_id": "acc_2"},
            {"incarnation": 2},
            {"rev": 4},
        ],
        ids=["objet", "compte", "incarnation", "revision"],
    )
    def test_un_blob_permute_est_refuse(self, permutation):
        """§4.12 — un VPS qui échange deux blobs, prend celui d'un autre
        compte, d'avant une réinitialisation ou présente la révision 3 comme
        la 5 : l'AAD le refuse."""
        with pytest.raises(env.EnveloppeIllisible):
            _ouvrir(_objet(), **permutation)

    @pytest.mark.parametrize("position", [0, 1, 2, 5, 6, 37, 38, 49, 50, -1])
    def test_un_octet_modifie_est_refuse(self, position):
        """§4.12 — l'en-tête (format, type, époque, sel, nonce) est dans
        l'AAD ; le chiffré et le tag sont authentifiés."""
        blob = bytearray(_objet())
        blob[position] ^= 0x01
        with pytest.raises(env.EnveloppeIllisible):
            _ouvrir(bytes(blob))

    @pytest.mark.parametrize("longueur", [0, 3, 6, 49, 69, 1089])
    def test_un_blob_tronque_est_refuse(self, longueur):
        """§4.3 — un blob coupé par un transfert ou un disque plein doit
        finir en quarantaine, pas en exception imprévue."""
        with pytest.raises(env.EnveloppeIllisible):
            _ouvrir(_objet()[:longueur])

    def test_un_objet_n_ouvre_pas_comme_une_piece(self):
        """§2.5 — le type est dans l'en-tête et dans l'info de la sous-clé."""
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_piece(
                DEK, _objet(), account_id="acc_1", incarnation=1, piece_id="obj_1"
            )

    def test_une_autre_dek_est_refusee(self):
        """§2.8 — la DEK d'une autre époque n'ouvre pas le blob."""
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_objet(bytes([9]) * 32, _objet(), **CONTEXTE)

    def test_un_account_id_non_textuel_est_refuse(self):
        """§2.5 — un accountId en entier donnerait une AAD valide mais que
        l'appareil suivant recalculerait autrement : illisible, sans erreur
        à l'écriture."""
        with pytest.raises(TypeError):
            env.sceller_objet(
                DEK,
                b"x",
                account_id=1,
                incarnation=1,
                object_id="o",
                rev=1,
                key_epoch=1,
            )


class TestLAlea:
    def test_le_chemin_par_defaut_tire_un_sel_et_un_nonce_neufs(self):
        """§2.3 — une sous-clé par message : deux scellements du même clair
        ne doivent jamais partager sel ni nonce."""
        a, b = _objet(b"meme"), _objet(b"meme")
        assert a[6:38] != b[6:38], "le sel doit être neuf à chaque scellement"
        assert a[38:50] != b[38:50], "le nonce doit être neuf à chaque scellement"

    def test_l_alea_injecte_rend_le_scellement_deterministe(self):
        """§2.12 — les vecteurs de contrat exigent sel et nonce injectables."""
        sel, nonce = bytes(32), bytes(12)
        a = _objet(b"meme", sel=sel, nonce=nonce)
        assert a == _objet(b"meme", sel=sel, nonce=nonce), "même alea, même blob"

    def test_un_alea_de_mauvaise_longueur_est_refuse(self):
        """§2.5 — un nonce de 8 o décalerait tout l'en-tête."""
        with pytest.raises(ValueError):
            _objet(nonce=bytes(8))


class TestLAmkSousLaKek:
    def test_l_aller_retour_rend_l_amk(self):
        """§2.5 — type 03 : 66 + 4 + 32 o, et l'AMK revient."""
        amk = bytes([5]) * 32
        blob = env.envelopper_amk(
            KEK, amk, account_id="acc_1", kdf_version=1, vault_version=3
        )
        assert len(blob) == 102, "une AMK sous KEK fait 102 o"
        assert (
            env.ouvrir_amk(
                KEK,
                blob,
                account_id="acc_1",
                kdf_version=1,
                vault_version=3,
                plancher_vault_version=3,
            )
            == amk
        ), "l'AMK doit revenir"

    def test_une_enveloppe_sous_le_plancher_est_refusee(self):
        """§4.4 — une restauration du VPS ramène l'enveloppe d'hier avec sa
        vraie vaultVersion ; elle s'ouvrirait avec l'ancien mot de passe."""
        blob = env.envelopper_amk(
            KEK, bytes(32), account_id="acc_1", kdf_version=1, vault_version=1
        )
        with pytest.raises(env.CleServeurPerimee) as exc:
            env.ouvrir_amk(
                KEK,
                blob,
                account_id="acc_1",
                kdf_version=1,
                vault_version=1,
                plancher_vault_version=2,
            )
        assert exc.value.code == "serverKeyStale", "le code doit être serverKeyStale"

    def test_le_plancher_passe_avant_tout_essai_de_cle(self):
        """§4.4 et §4.12 — « serverKeyStale AVANT d'essayer la clé » : avec
        une KEK fausse et une version sous le plancher, c'est le plancher
        qui parle. Essayer d'abord dirait « mot de passe incorrect » à qui
        tape le bon, face à un coffre restauré."""
        blob = env.envelopper_amk(
            KEK, bytes(32), account_id="acc_1", kdf_version=1, vault_version=1
        )
        with pytest.raises(env.CleServeurPerimee):
            env.ouvrir_amk(
                bytes([9]) * 32,
                blob,
                account_id="acc_1",
                kdf_version=1,
                vault_version=1,
                plancher_vault_version=2,
            )

    def test_une_enveloppe_reetiquetee_au_dessus_du_plancher_est_refusee(self):
        """§2.5 — ``w`` est dans l'AAD : la même enveloppe présentée comme
        vaultVersion 2 ne s'ouvre pas."""
        blob = env.envelopper_amk(
            KEK, bytes(32), account_id="acc_1", kdf_version=1, vault_version=1
        )
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_amk(
                KEK,
                blob,
                account_id="acc_1",
                kdf_version=1,
                vault_version=2,
                plancher_vault_version=2,
            )

    def test_un_kdf_declasse_est_refuse_a_l_ouverture(self):
        """§4.12 — une enveloppe annoncée sous kdfVersion 0 est refusée."""
        blob = env.envelopper_amk(
            KEK, bytes(32), account_id="acc_1", kdf_version=1, vault_version=1
        )
        with pytest.raises(env.ErreurCompte) as exc:
            env.ouvrir_amk(
                KEK,
                blob,
                account_id="acc_1",
                kdf_version=0,
                vault_version=1,
                plancher_vault_version=1,
            )
        assert exc.value.code == "kdfDowngrade", "le code doit être kdfDowngrade"


class TestLeNomDAppareil:
    def test_il_est_lie_a_sa_session(self):
        """§2.5 — un nom d'appareil déplacé sur une autre session mentirait
        dans la liste des appareils connectés."""
        blob = env.sceller_nom_appareil(
            K_NOMS, "MacBook", account_id="acc_1", session_id="s1", key_epoch=1
        )
        assert (
            env.ouvrir_nom_appareil(K_NOMS, blob, account_id="acc_1", session_id="s1")
            == "MacBook"
        ), "le nom doit se rouvrir sur sa propre session"
        with pytest.raises(env.EnveloppeIllisible):
            env.ouvrir_nom_appareil(K_NOMS, blob, account_id="acc_1", session_id="s2")


class TestLeClair:
    def test_ses_cles_sont_en_anglais(self):
        """§2.5 et CLAUDE.md §3 — un champ en français se lirait
        ``undefined`` côté TypeScript, en silence."""
        vivant = env.clair_objet("conversations", "x", {})
        tombale = env.clair_tombale("conversations", "x", 1790000000000)
        assert set(vivant) == {"v", "collection", "id", "schema", "data"}, (
            "clés du clair vivant"
        )
        assert set(tombale) == {"v", "collection", "id", "schema", "deleted"}, (
            "clés de la tombale"
        )
        assert tombale["deleted"] == {"deletedAt": 1790000000000}, (
            "deletedAt en camelCase"
        )

    def test_un_clair_bien_forme_est_lu(self):
        """§2.5 — les deux formes de la conception passent : sinon chaque
        refus ci-dessus prouverait seulement que rien ne passe."""
        for forme in (
            env.clair_objet("conversations", "x", {"a": 1}),
            env.clair_tombale("conversations", "x", 1790000000000),
        ):
            assert env.lire_clair(env.encoder_clair(forme)) == forme, "forme lue"

    @pytest.mark.parametrize(
        "clair",
        [
            b"pas du json",
            b"[]",
            b'{"v":2,"collection":"c","id":"i","data":{}}',
            b'{"v":1,"collection":"c","id":"i","schema":1}',
            b'{"v":true,"collection":"c","id":"i","schema":1,"data":{}}',
            b'{"v":1.0,"collection":"c","id":"i","schema":1,"data":{}}',
            b'{"v":1,"collection":"c","id":"i","data":{}}',
            b'{"v":1,"collection":"c","id":"i","schema":true,"data":{}}',
            b'{"v":1,"collection":"c","id":"i","schema":1,"data":{},"id":"j"}',
        ],
        ids=[
            "non-json",
            "liste",
            "version-2",
            "ni-data-ni-deleted",
            "version-bool",
            "version-flottante",
            "schema-absent",
            "schema-bool",
            "cle-en-double",
        ],
    )
    def test_un_clair_mal_forme_est_refuse(self, clair):
        """§4.3 — version ou forme inconnue : l'objet va dans ``inconnus``,
        il n'est pas ingéré à moitié. ``true`` et ``1.0`` ne sont pas la
        version 1, et une clé en double se lirait différemment selon
        l'analyseur (24/09/2026)."""
        with pytest.raises(env.ClairInvalide):
            env.lire_clair(clair)
