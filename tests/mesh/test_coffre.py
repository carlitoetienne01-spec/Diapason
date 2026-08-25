"""Le chiffrement de session : ce qu'il protège, et ce qu'il refuse.

Spatial Mesh, phase 3 — 25 août 2026. Les commandes du maillage sont
signées, pas chiffrées : savoir qui parle suffit pour « ouvre cet écran ».
Un document personnel qui traverse un Wi-Fi partagé, non.
"""

from __future__ import annotations

import pytest

from diapason.mesh import coffre


@pytest.fixture()
def paire():
    """Deux appareils qui viennent de s'accorder sur une session."""
    emetteur = coffre.nouvelle_demi_cle()
    recepteur = coffre.nouvelle_demi_cle()
    sid = "sess_test"
    return (
        coffre.cle_de_session(emetteur, recepteur.publique_b64, sid),
        coffre.cle_de_session(recepteur, emetteur.publique_b64, sid),
    )


class TestAccordDeCle:
    def test_les_deux_cotes_derivent_la_meme_cle(self, paire):
        cle_a, cle_b = paire
        assert cle_a == cle_b
        assert len(cle_a) == 32

    def test_deux_sessions_n_ont_jamais_la_meme_cle(self):
        """L'identifiant de session est le sel : deux transferts entre les
        mêmes appareils ne partagent rien."""
        a, b = coffre.nouvelle_demi_cle(), coffre.nouvelle_demi_cle()
        k1 = coffre.cle_de_session(a, b.publique_b64, "sess_1")
        k2 = coffre.cle_de_session(a, b.publique_b64, "sess_2")
        assert k1 != k2

    def test_la_cle_privee_ne_sort_jamais(self):
        demi = coffre.nouvelle_demi_cle()
        assert demi.privee not in demi.publique
        # Ce qu'on publie ne permet pas de reconstruire ce qu'on garde.
        assert len(demi.publique) == 32 and len(demi.privee) == 32

    @pytest.mark.parametrize("mauvaise", ["", "pas-du-base64!!", "YWJj"])
    def test_une_cle_publique_illisible_est_refusee(self, mauvaise):
        demi = coffre.nouvelle_demi_cle()
        with pytest.raises(ValueError):
            coffre.cle_de_session(demi, mauvaise, "s")


class TestScellement:
    def test_un_morceau_scelle_puis_descelle_revient_intact(self, paire):
        cle_a, cle_b = paire
        clair = b"le contenu confidentiel du fichier"
        assert coffre.desceller(cle_b, 7, coffre.sceller(cle_a, 7, clair)) == clair

    def test_le_scelle_ne_ressemble_pas_au_clair(self, paire):
        cle_a, _ = paire
        clair = b"mot de passe : soleil"
        scelle = coffre.sceller(cle_a, 0, clair)
        assert clair not in scelle
        assert b"soleil" not in scelle

    def test_un_morceau_deplace_devient_illisible(self, paire):
        """L'index est authentifié : réordonner les morceaux casse le
        déchiffrement au lieu de produire un fichier silencieusement faux."""
        cle_a, cle_b = paire
        scelle = coffre.sceller(cle_a, 3, b"contenu")
        with pytest.raises(ValueError, match="mauvaise place|altéré"):
            coffre.desceller(cle_b, 4, scelle)

    def test_un_octet_modifie_devient_illisible(self, paire):
        cle_a, cle_b = paire
        scelle = bytearray(coffre.sceller(cle_a, 0, b"contenu honnete"))
        scelle[5] ^= 0x01
        with pytest.raises(ValueError):
            coffre.desceller(cle_b, 0, bytes(scelle))

    def test_une_autre_session_ne_dechiffre_rien(self):
        """Un espion qui rejouerait le trafic d'une session dans une autre
        n'obtient rien."""
        a, b = coffre.nouvelle_demi_cle(), coffre.nouvelle_demi_cle()
        cle1 = coffre.cle_de_session(a, b.publique_b64, "s1")
        cle2 = coffre.cle_de_session(a, b.publique_b64, "s2")
        with pytest.raises(ValueError):
            coffre.desceller(cle2, 0, coffre.sceller(cle1, 0, b"secret"))

    def test_deux_morceaux_n_ont_jamais_le_meme_nonce(self, paire):
        """Réutiliser un nonce est la seule façon de casser GCM. Le nôtre
        est l'index, donc unique par construction dans une session."""
        cle_a, _ = paire
        clair = b"identique"
        a = coffre.sceller(cle_a, 0, clair)
        b = coffre.sceller(cle_a, 1, clair)
        assert a != b, "le même clair à deux index doit donner deux scellés"

    def test_un_index_absurde_est_refuse(self, paire):
        cle_a, _ = paire
        with pytest.raises(ValueError):
            coffre.sceller(cle_a, -1, b"x")


class TestDisponibilite:
    def test_le_coffre_est_disponible_ici(self):
        """cryptography est une dépendance de BASE : « le maillage ne peut
        pas traiter sa propre identité comme optionnelle »."""
        assert coffre.disponible() is True
