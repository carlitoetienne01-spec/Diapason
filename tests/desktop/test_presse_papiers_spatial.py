"""Le presse-papiers spatial : ce qu'on tient, et ce qu'on ne tient pas.

Spatial Mesh, gestes, phase 5 — 25 août 2026. Le §2 du cahier : ne jamais
confondre l'effet visuel et l'architecture. Fermer le poing ne déplace
aucun octet — il désigne ce que l'écran affiche et le retient.
"""

from __future__ import annotations

import pytest

from diapason.desktop import contexte_app as ca
from diapason.desktop import presse_papiers_spatial as pp


@pytest.fixture(autouse=True)
def _table_rase():
    ca.oublier()
    pp.vider()
    yield
    ca.oublier()
    pp.vider()


class TestAttraper:
    def test_on_attrape_ce_que_l_ecran_affiche(self):
        ca.poser_contexte(
            "/succes/projects",
            ressource_type="project",
            ressource_id="p1",
            ressource_titre="Zéro à Héro",
        )
        objet = pp.attraper()
        assert objet.type == "project" and objet.id == "p1"
        assert objet.titre == "Zéro à Héro"

    def test_sans_element_selectionne_on_attrape_l_ecran(self):
        """« Reprends ça là-bas » a un sens même sans élément précis."""
        ca.poser_contexte("/succes/notes")
        objet = pp.attraper()
        assert objet.type == "screen" and objet.titre == "les Notes"

    def test_sans_contexte_la_main_se_referme_sur_du_vide(self):
        """Attraper au hasard un objet que l'utilisateur ne regardait pas
        serait pire que ne rien attraper."""
        assert pp.attraper() is None
        assert pp.tenu() is None

    def test_on_transporte_une_identite_pas_une_copie(self):
        """§19 : une tâche n'est pas sérialisée puis renvoyée. C'est ce qui
        distingue un handoff d'une duplication."""
        ca.poser_contexte(
            "/succes/notes",
            ressource_type="note",
            ressource_id="n7",
            ressource_titre="Idées",
        )
        contenu = pp.attraper().to_dict()
        assert set(contenu) == {"type", "id", "title", "screen"}
        assert "body" not in contenu and "content" not in contenu


class TestAttraperUnVraiFichier:
    """§41 et §82 : le geste peut désigner un fichier, sans avaler ses octets."""

    def test_le_fichier_prepare_prime_sur_l_ecran(self, tmp_path):
        fichier = tmp_path / "photo été.jpg"
        fichier.write_bytes(b"jpeg-factice")
        ca.poser_contexte("/succes/projects")

        prepare = pp.preparer_fichier(fichier)
        objet = pp.attraper()

        assert prepare.type == "file" and objet.type == "file"
        assert objet.titre == "photo été.jpg"
        assert objet.taille == len(b"jpeg-factice")
        assert objet.type_mime == "image/jpeg"
        assert objet.chemin == str(fichier.resolve())
        assert pp.fichier_prepare() is None, (
            "une préparation consommée ne doit pas se faire réattraper en boucle"
        )

    def test_le_chemin_local_ne_passe_jamais_dans_le_json(self, tmp_path):
        fichier = tmp_path / "secret.mp4"
        fichier.write_bytes(b"video")
        public = pp.preparer_fichier(fichier).to_dict()

        assert public["type"] == "file"
        assert public["sizeBytes"] == 5
        assert public["mimeType"] == "video/mp4"
        assert "chemin" not in public and "path" not in public
        assert str(tmp_path) not in str(public)

    def test_un_dossier_est_refuse_avant_d_etre_affiche(self, tmp_path):
        with pytest.raises(ValueError, match="pas un dossier"):
            pp.preparer_fichier(tmp_path)
        assert pp.fichier_prepare() is None

    def test_un_fichier_disparu_n_est_plus_promis(self, tmp_path):
        fichier = tmp_path / "éphémère.txt"
        fichier.write_text("ici", encoding="utf-8")
        pp.preparer_fichier(fichier)
        fichier.unlink()
        assert pp.fichier_prepare() is None

    def test_une_preparation_expire_sans_etre_attrapee(self, tmp_path, monkeypatch):
        fichier = tmp_path / "attente.mov"
        fichier.write_bytes(b"video")
        pp.preparer_fichier(fichier)
        depart = pp._prepare.quand
        monkeypatch.setattr(
            pp.time,
            "monotonic",
            lambda: depart + pp.PREPARATION_TTL_S + 1,
        )
        assert pp.fichier_prepare() is None


class TestLacher:
    def test_lacher_rend_l_objet_et_ouvre_la_main(self):
        ca.poser_contexte(
            "/succes/projects",
            ressource_type="project",
            ressource_id="p1",
            ressource_titre="X",
        )
        pp.attraper()
        assert pp.lacher().id == "p1"
        assert pp.tenu() is None, "la main doit être vide après avoir lâché"

    def test_lacher_deux_fois_ne_rend_rien_la_seconde(self):
        ca.poser_contexte("/succes/notes")
        pp.attraper()
        assert pp.lacher() is not None
        assert pp.lacher() is None


class TestCeQuiSePerd:
    def test_un_objet_tenu_trop_longtemps_est_oublie(self, monkeypatch):
        """Un objet attrapé et jamais déposé n'a pas à hanter la session."""
        ca.poser_contexte("/succes/notes")
        pp.attraper()
        assert pp.tenu() is not None
        import time as _t

        depart = _t.monotonic()
        monkeypatch.setattr(pp.time, "monotonic", lambda: depart + pp.TTL_S + 1)
        assert pp.tenu() is None

    def test_vider_est_immediat(self):
        ca.poser_contexte("/succes/notes")
        pp.attraper()
        pp.vider()
        assert pp.tenu() is None
