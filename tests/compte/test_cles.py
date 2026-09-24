"""Les clés du compte : normalisations, étirement, rôles, identifiants.

Conception : ``docs/development/compte-chiffre.md`` §2.2 à §2.4 et §2.6,
étape 1 du §6. Argon2id aux vrais paramètres coûte 0,5 s : seul le vecteur
de contrat le paie (``test_vecteurs``) ; ici, tout passe à 64 Kio.
"""

from __future__ import annotations

import threading
import time
from types import MappingProxyType

import pytest

from diapason.compte import cles

KDF_SALT = bytes(range(32))


def _k_mdp_bon_marche(mot_de_passe: str) -> bytes:
    return cles._etirer_avec_parametres(
        cles.normaliser_mot_de_passe(mot_de_passe),
        b"sel-de-test-16oo",
        memory_cost=64,
        iterations=1,
        lanes=1,
    )


class TestLaNormalisation:
    def test_nfc_nfd_et_pleine_chasse_donnent_les_memes_cles(self, monkeypatch):
        """§2.4 — un « é » saisi en NFD sous macOS et en NFC sous Windows
        donnait deux clés : le même mot de passe n'ouvrait pas le même compte
        d'un appareil à l'autre. Chemin public, à 64 Kio : les vrais
        paramètres sont figés par le vecteur de contrat, une seule fois."""
        monkeypatch.setattr(cles, "VERSIONS_KDF", MappingProxyType({1: (64, 1, 1)}))
        # Échappements : un éditeur qui normalise en NFC effacerait l'écart.
        nfc = "Caf\u00e9 cr\u00e8me, \u00e9t\u00e9 2026 !"
        nfd = "Cafe\u0301 cre\u0300me, e\u0301te\u0301 2026 !"
        pleine_chasse = (
            "\uff23\uff41\uff46\u00e9\u3000\uff43\uff52\u00e8\uff4d\uff45\uff0c"
            "\u3000\u00e9\uff54\u00e9\u3000\uff12\uff10\uff12\uff16\u3000\uff01"
        )
        assert len({nfc, nfd, pleine_chasse}) == 3, "trois écritures distinctes"
        resultats = [
            cles.deriver_cles_mot_de_passe(p, "alice@exemple.org", KDF_SALT, 1)
            for p in (nfc, nfd, pleine_chasse)
        ]
        assert resultats[0] == resultats[1] == resultats[2], (
            "NFC, NFD et pleine chasse doivent donner les mêmes authKey et KEK"
        )

    def test_le_mot_de_passe_garde_ses_espaces(self):
        """§2.4 — NFKC SANS strip : une espace finale fait partie du secret ;
        la retirer ferait accepter un mot de passe que la personne n'a pas tapé."""
        assert cles.normaliser_mot_de_passe(" secret ") == b" secret ", (
            "les espaces de tête et de fin doivent être conservés"
        )

    def test_le_courriel_est_nfkc_strip_lower(self):
        """§2.4 — le courriel entre dans le sel : « Alice@X » et « alice@x »
        doivent donner la même clé, sinon une majuscule verrouille le compte."""
        assert (
            cles.normaliser_courriel("  Ａｌｉｃｅ@Exemple.ORG ") == "alice@exemple.org"
        ), "le courriel doit être normalisé en NFKC, sans espaces, en minuscules"

    @pytest.mark.parametrize(
        "mauvais", ["a@", "a@@b.c", "sans-arobase", "a b@c.d", "x" * 250 + "@a.bc"]
    )
    def test_un_courriel_mal_forme_est_refuse(self, mauvais):
        """§2.4 — 3 à 254 caractères, un seul @, aucun espace."""
        with pytest.raises(cles.CourrielInvalide) as exc:
            cles.normaliser_courriel(mauvais)
        assert exc.value.code == "emailInvalid", "le code doit être emailInvalid"

    def test_le_sel_depend_du_courriel(self):
        """§2.2 — ``E`` est dans le sel : un serveur qui servirait le même
        kdfSalt à tous n'obtiendrait pas un dictionnaire commun."""
        assert cles.sel_argon2("a@x.org", KDF_SALT) != cles.sel_argon2(
            "b@x.org", KDF_SALT
        ), "deux adresses doivent donner deux sels Argon2id"
        assert cles.sel_argon2(" A@X.org", KDF_SALT) == cles.sel_argon2(
            "a@x.org", KDF_SALT
        ), "le sel doit se calculer sur le courriel normalisé"

    def test_un_kdf_salt_de_mauvaise_longueur_est_refuse(self):
        """§2.2 — kdfSalt est un HMAC de 32 o ; un serveur qui en servirait
        un vide réduirait le sel au seul courriel."""
        with pytest.raises(ValueError):
            cles.sel_argon2("a@x.org", b"")


class TestLesReglesDuMotDePasse:
    def test_douze_caracteres_suffisent(self):
        """D5 — le minimum est 12 caractères après NFKC."""
        cles.verifier_mot_de_passe("douze carac.", "alice@exemple.org")

    def test_onze_caracteres_sont_refuses(self):
        """D5 et A5 — un mot de passe court tombe hors ligne en quelques semaines."""
        with pytest.raises(cles.MotDePasseRefuse) as exc:
            cles.verifier_mot_de_passe("onze carac.", "alice@exemple.org")
        assert exc.value.code == "passwordTooShort", "le code doit dire trop court"

    def test_plus_de_1024_caracteres_sont_refuses(self):
        """D5 — la borne haute protège Argon2id d'une entrée démesurée."""
        with pytest.raises(cles.MotDePasseRefuse) as exc:
            cles.verifier_mot_de_passe("x" * 1025, "alice@exemple.org")
        assert exc.value.code == "passwordTooLong", "le code doit dire trop long"

    def test_la_partie_locale_de_l_adresse_est_refusee(self):
        """D5 — « carlito2026!!! » pour carlito@… se devine en premier."""
        with pytest.raises(cles.MotDePasseRefuse) as exc:
            cles.verifier_mot_de_passe("Carlito-2026-!!", "carlito@exemple.org")
        assert exc.value.code == "passwordContainsEmail", (
            "le code doit dire que le mot de passe contient l'adresse"
        )

    def test_mille_vingt_quatre_caracteres_suffisent(self):
        """D5 — la borne haute est incluse : 1 024 caractères après NFKC."""
        cles.verifier_mot_de_passe("x" * 1024, "alice@exemple.org")

    def test_une_partie_locale_courte_s_applique_a_la_lettre(self):
        """D5 et §2.4 — « ne doit pas contenir la partie locale », sans
        seuil : la première passe en inventait un (4 caractères) que la
        conception ne porte pas. L'assouplir revient à Carlito."""
        with pytest.raises(cles.MotDePasseRefuse) as exc:
            cles.verifier_mot_de_passe("enjoy the rain", "jo@exemple.org")
        assert exc.value.code == "passwordContainsEmail", (
            "la partie locale « jo » est dans « enjoy » : D5 refuse"
        )

    def test_une_partie_locale_vide_ne_refuse_pas_tout(self):
        """§2.4 — « @ab » est une adresse admise ; la chaîne vide est
        contenue partout, et sans garde tout mot de passe serait refusé."""
        cles.verifier_mot_de_passe("un mot de passe long", "@ab")


class TestLesClesDeRole:
    def test_auth_key_differe_de_la_kek(self):
        """§2.2 — le VPS reçoit authKey à chaque connexion ; si elle valait
        la KEK, il ouvrirait l'enveloppe de l'AMK."""
        role = cles.cles_de_role(_k_mdp_bon_marche("un mot de passe long"))
        assert role.auth_key != role.kek, "authKey et KEK doivent différer"
        assert len(role.auth_key) == len(role.kek) == 32, "les deux font 32 o"

    def test_les_cles_ne_s_impriment_pas(self):
        """§2.10 — un ``logger.debug(cles)`` ne doit écrire aucune clé. La
        première passe comparait à ``kek.hex()``, que ``repr`` n'écrit
        jamais : le test passait même sans ``repr=False``."""
        role = cles.cles_de_role(_k_mdp_bon_marche("un mot de passe long"))
        texte = repr(role)
        for nom, valeur in (("auth_key", role.auth_key), ("kek", role.kek)):
            assert repr(valeur) not in texte, f"repr ne doit pas contenir {nom}"
            assert f"{nom}=" not in texte, f"repr ne doit pas nommer {nom}"

    def test_deux_mots_de_passe_donnent_deux_kek(self):
        """§2.2 — sanité : la KEK dépend du mot de passe."""
        a = cles.cles_de_role(_k_mdp_bon_marche("premier mot de passe"))
        b = cles.cles_de_role(_k_mdp_bon_marche("second mot de passe"))
        assert a.kek != b.kek, "deux mots de passe doivent donner deux KEK"


class TestLeDeclassement:
    @pytest.mark.parametrize("version", [0, -1, 2, 99, True, "1", 1.0, None])
    def test_une_version_inconnue_ou_inferieure_est_refusee(self, version):
        """§2.3 et §4.12 — un VPS hostile qui servirait kdfVersion 0 (ou
        ``true``, que Python confond avec 1) imposerait un Argon2 faible."""
        with pytest.raises(cles.DeclassementKdf) as exc:
            cles.parametres_kdf(version)
        assert exc.value.code == "kdfDowngrade", "le code doit être kdfDowngrade"

    def test_le_chemin_public_refuse_avant_d_etirer(self, monkeypatch):
        """§2.3 — le refus tombe AVANT Argon2id : aucun calcul à bas coût.
        Un Argon2id factice échoue s'il est construit (la première passe
        mesurait un temps, sensible à la charge de la machine)."""
        appels = []
        monkeypatch.setattr(cles, "Argon2id", lambda **kw: appels.append(kw))
        with pytest.raises(cles.DeclassementKdf):
            cles.deriver_cles_mot_de_passe(
                "un mot de passe long", "a@x.org", KDF_SALT, 0
            )
        assert not appels, "le refus ne doit pas lancer Argon2id"

    def test_etirer_a_parametres_libres_n_est_pas_public(self):
        """§2.3 et §4.12 — une fonction publique qui étire aux paramètres
        qu'on lui passe est un chemin de déclassement tout prêt pour
        l'étape 8 ; seul ``etirer_mot_de_passe`` est public."""
        assert not hasattr(cles, "etirer_avec_parametres"), (
            "l'étirement à paramètres libres doit rester privé"
        )

    def test_la_table_des_versions_est_en_lecture_seule(self):
        """§2.3 — le client fige VERSIONS_KDF ; personne ne doit pouvoir y
        ajouter une version faible à l'exécution."""
        with pytest.raises(TypeError):
            cles.VERSIONS_KDF[0] = (8, 1, 1)  # type: ignore[index]
        assert dict(cles.VERSIONS_KDF) == {1: (262144, 3, 4)}, "D2 : 256 Mio, t=3, p=4"

    def test_une_seule_derivation_a_la_fois(self, monkeypatch):
        """§2.3 — deux dérivations de 256 Mio en parallèle doubleraient
        l'empreinte mémoire du serveur local."""
        en_cours, maximum = [0], [0]
        verrou = threading.Lock()

        class FausseArgon:
            def __init__(self, **_):
                pass

            def derive(self, _):
                with verrou:
                    en_cours[0] += 1
                    maximum[0] = max(maximum[0], en_cours[0])
                time.sleep(0.05)
                with verrou:
                    en_cours[0] -= 1
                return bytes(32)

        monkeypatch.setattr(cles, "Argon2id", FausseArgon)
        fils = [
            threading.Thread(
                target=cles.etirer_mot_de_passe,
                args=("un mot de passe long", "a@x.org", KDF_SALT, 1),
            )
            for _ in range(3)
        ]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        assert maximum[0] == 1, "deux Argon2id ne doivent jamais tourner ensemble"


class TestLesIdentifiants:
    def test_object_id_est_stable_et_opaque(self):
        """§2.6 — deux appareils doivent nommer pareil la même conversation."""
        k_id = bytes([7]) * 32
        a = cles.identifiant_objet(k_id, "conversations", "abc")
        assert a == cles.identifiant_objet(k_id, "conversations", "abc"), "stable"
        assert len(a) == 22 and "=" not in a, "16 o en base64url sans remplissage"
        assert "abc" not in a, "l'id local ne doit pas transparaître"

    def test_le_separateur_empeche_les_collisions(self):
        """§2.6 — sans le \\0, (« ab », « c ») et (« a », « bc ») se confondraient."""
        k_id = bytes([7]) * 32
        assert cles.identifiant_objet(k_id, "ab", "c") != cles.identifiant_objet(
            k_id, "a", "bc"
        ), "le séparateur \\0 doit distinguer collection et id"

    @pytest.mark.parametrize("collection, id_local", [("a\0b", "c"), ("a", "b\0c")])
    def test_un_zero_dans_collection_ou_id_est_refuse(self, collection, id_local):
        """§2.6 — (« a\\0b », « c ») et (« a », « b\\0c ») donnaient le même
        message HMAC, donc le même objectId : deux objets se seraient écrasés."""
        with pytest.raises(ValueError, match="\\\\0"):
            cles.identifiant_objet(bytes([7]) * 32, collection, id_local)

    def test_piece_id_depend_de_l_epoque(self):
        """§2.2 — tiré d'une clé fixe, ``/pieces/missing`` répondrait
        « présente » après une rotation et l'image resterait sous la DEK
        compromise."""
        image = b"\x89PNG" + bytes(100)
        p1 = cles.identifiant_piece(cles.cle_piece(bytes([1]) * 32), image)
        p2 = cles.identifiant_piece(cles.cle_piece(bytes([2]) * 32), image)
        assert p1 != p2, (
            "la même image doit changer d'identifiant d'une époque à l'autre"
        )
