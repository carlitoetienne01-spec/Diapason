"""Le scellement des commandes — les primitives, avant tout appelant.

Étape 1 du plan du 26 août 2026. Rien dans le dépôt n'appelle encore ce
module : ces tests vérifient la cryptographie seule, pour que les étapes
suivantes se posent sur un socle déjà éprouvé plutôt que de tout mêler.

La vérification la plus importante n'est pas ici mais dans
``tests/mesh/test_coffre.py``, qui passe **sans une seule modification** :
c'est la preuve que les trois mots-clés ajoutés à ``coffre.py`` sont neutres
et que le transfert de fichiers ne bouge pas d'un bit.
"""

from __future__ import annotations

import os
import stat

import pytest

from diapason.mesh import scellement


@pytest.fixture(autouse=True)
def _chez_soi(tmp_path, monkeypatch):
    """Chaque test frappe ses propres clés, dans son propre dossier.

    Sans cela un test écrirait dans ``~/.diapason`` de qui lance la suite —
    et la clé de scellement de sa vraie machine deviendrait celle d'un test.
    """
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
    yield


def _associe(quoi: bytes = b"en-tete-de-routage") -> bytes:
    return quoi


class TestLaCleLocale:
    def test_elle_nait_en_0600_dans_un_dossier_0700(self):
        paire = scellement.paire_locale()
        assert len(paire.privee) == 32
        assert len(paire.publique) == 32

        chemin = scellement._chemin("seal_key")
        assert chemin.exists()
        assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600, "la clé est lisible"
        assert stat.S_IMODE(os.stat(chemin.parent).st_mode) == 0o700

    def test_elle_ne_se_reforge_pas_a_chaque_appel(self):
        """Deux clés pour une machine, ce serait deux machines pour ses pairs."""
        assert scellement.paire_locale().privee == scellement.paire_locale().privee

    def test_le_kid_designe_sans_reveler(self):
        paire = scellement.paire_locale()
        empreinte = scellement.kid(paire.publique)
        assert len(empreinte) == 8
        assert all(c in "0123456789abcdef" for c in empreinte)
        assert empreinte != paire.publique_b64[:8]


class TestLeRenouvellement:
    def test_l_ancienne_reste_dechiffrable(self):
        """Une commande mise en file AVANT le renouvellement doit encore
        pouvoir s'ouvrir quand elle est enfin livrée."""
        avant = scellement.paire_locale()
        scellement.renouveler()
        apres = scellement.paire_locale()

        assert apres.privee != avant.privee, "la clé n'a pas changé"
        precedente = scellement.paire_precedente()
        assert precedente is not None
        assert precedente.privee == avant.privee

    def test_la_retention_couvre_l_attente_en_file(self):
        """INVARIANT : sans lui, une commande devient indéchiffrable pendant
        qu'elle attend son destinataire."""
        from diapason.mesh.commands import QUEUED_TTL_MS

        assert scellement.RETENTION_PRECEDENTE_MS > QUEUED_TTL_MS

    def test_oublier_efface_les_deux(self):
        scellement.paire_locale()
        scellement.renouveler()
        scellement.oublier_locale()
        assert not scellement._chemin("seal_key").exists()
        assert not scellement._chemin("seal_key.prev").exists()
        assert scellement.paire_precedente() is None


class TestUnAllerRetour:
    def _pair(self):
        """Une machine « distante » : sa paire, dont on n'a que la publique."""
        from diapason.mesh.coffre import nouvelle_demi_cle

        return nouvelle_demi_cle()

    def test_ce_qui_est_scelle_se_rouvre(self, monkeypatch, tmp_path):
        # On scelle VERS notre propre clé locale, pour pouvoir rouvrir ici.
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "notifications.show",
            {"title": "Rendez-vous à 14 h", "body": "chez le notaire"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-1",
            associe=_associe(),
        )
        assert set(scelle) == {"s", "e", "k"}

        outil, arguments, confirmation = scellement.ouvrir_contenu(
            scelle, command_id="cmd-1", associe=_associe()
        )
        assert outil == "notifications.show"
        assert arguments == {"title": "Rendez-vous à 14 h", "body": "chez le notaire"}
        assert confirmation is False

    def test_le_contenu_n_apparait_nulle_part_en_clair(self):
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "desktop.open",
            {"target": "https://exemple.test/rapport-confidentiel"},
            True,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-2",
            associe=_associe(),
        )
        entier = str(scelle)
        assert "desktop.open" not in entier
        assert "rapport-confidentiel" not in entier
        assert "exemple.test" not in entier

    def test_deux_sceaux_du_meme_clair_different(self):
        """Une moitié éphémère neuve à chaque fois : deux commandes
        identiques ne doivent pas produire deux chiffrés identiques, sans
        quoi un observateur les reconnaîtrait."""
        moi = scellement.paire_locale()
        args = dict(
            cle_pair_b64=moi.publique_b64, command_id="cmd-3", associe=_associe()
        )
        un = scellement.contenu_scelle("app.open", {"x": 1}, False, **args)
        deux = scellement.contenu_scelle("app.open", {"x": 1}, False, **args)
        assert un["s"] != deux["s"]
        assert un["e"] != deux["e"]

    def test_la_longueur_ne_trahit_pas_le_verbe(self):
        """Le catalogue ne compte que cinq entrées : sans rembourrage, la
        taille du chiffré désignerait l'outil."""
        moi = scellement.paire_locale()
        tailles = set()
        for outil, arguments in (
            ("app.open", {}),
            ("notifications.show", {"title": "x"}),
            ("desktop.open", {"target": "https://un-peu-plus-long.test/a/b"}),
        ):
            scelle = scellement.contenu_scelle(
                outil,
                arguments,
                False,
                cle_pair_b64=moi.publique_b64,
                command_id="cmd-4",
                associe=_associe(),
            )
            import base64

            tailles.add(len(base64.b64decode(scelle["s"])))
        assert len(tailles) == 1, f"tailles distinctes : {sorted(tailles)}"


class TestCeQuiDoitEchouer:
    def test_un_seul_octet_de_contexte_change_ferme_le_sceau(self):
        """Le blob est collé à SON enveloppe : le déplacer d'une commande à
        une autre casse le tag avant que la signature ait son mot à dire."""
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {"screen": "projets"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-5",
            associe=b"en-tete-A",
        )
        with pytest.raises(ValueError):
            scellement.ouvrir_contenu(scelle, command_id="cmd-5", associe=b"en-tete-B")

    def test_un_autre_identifiant_de_commande_ferme_le_sceau(self):
        """L'identifiant est le sel : le changer change la clé dérivée."""
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {"screen": "projets"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-6",
            associe=_associe(),
        )
        with pytest.raises(ValueError):
            scellement.ouvrir_contenu(
                scelle, command_id="cmd-AUTRE", associe=_associe()
            )

    def test_un_sceau_pour_une_cle_qu_on_n_a_plus_le_dit(self):
        """Deux renouvellements : la clé d'origine n'est plus ni courante ni
        précédente. Le refus doit nommer la cause, pas échouer au hasard."""
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-7",
            associe=_associe(),
        )
        scellement.renouveler()
        scellement.renouveler()
        with pytest.raises(ValueError, match="que cette machine n'a plus"):
            scellement.ouvrir_contenu(scelle, command_id="cmd-7", associe=_associe())

    def test_la_cle_precedente_ouvre_encore(self):
        moi = scellement.paire_locale()
        scelle = scellement.contenu_scelle(
            "app.open",
            {"screen": "notes"},
            False,
            cle_pair_b64=moi.publique_b64,
            command_id="cmd-8",
            associe=_associe(),
        )
        scellement.renouveler()
        outil, arguments, _ = scellement.ouvrir_contenu(
            scelle, command_id="cmd-8", associe=_associe()
        )
        assert outil == "app.open" and arguments == {"screen": "notes"}


class TestLeTransfertDeFichiersNeBougePas:
    """Les trois mots-clés ajoutés à ``coffre.py`` doivent être NEUTRES.

    ``tests/mesh/test_coffre.py`` passe sans modification, ce qui le prouve
    déjà par le comportement. Ce test le prouve par les octets.
    """

    def test_sans_contexte_les_octets_authentifies_sont_ceux_d_avant(self):
        from diapason.mesh.coffre import _authentifie

        for index in (0, 1, 42, 999):
            assert _authentifie(index, b"") == str(index).encode("ascii")

    def test_avec_contexte_ils_different(self):
        from diapason.mesh.coffre import _authentifie

        assert _authentifie(0, b"X") != _authentifie(0, b"")
