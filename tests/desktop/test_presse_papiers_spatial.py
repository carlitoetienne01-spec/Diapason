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
