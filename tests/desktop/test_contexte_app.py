"""Le cliché de l'écran courant : ce qui traverse, et ce qui se tait.

Spatial Mesh, handoff — 25 août 2026. « Continue ce projet sur mon
téléphone » n'avait aucun référent pour « ce projet ». Ce cliché en est un
— mais il ne porte QUE ce que le maillage sait réellement rouvrir.
"""

from __future__ import annotations

import pytest

from diapason.desktop import contexte_app as ca


@pytest.fixture(autouse=True)
def _table_rase():
    ca.oublier()
    yield
    ca.oublier()


class TestCeQuiEntre:
    def test_un_ecran_connu_avec_sa_ressource(self):
        vue = ca.poser_contexte(
            "/succes/projects",
            ressource_type="project",
            ressource_id="p1",
            ressource_titre="Zéro à Héro",
        )
        assert vue is not None
        assert ca.decrire(vue) == (
            "Dans Diapason : les Projets, le projet « Zéro à Héro » ouvert(e)."
        )

    def test_un_ecran_sans_ressource_reste_un_ecran(self):
        vue = ca.poser_contexte("/succes/notes")
        assert ca.decrire(vue) == "Dans Diapason : les Notes."

    def test_un_ecran_inconnu_efface_au_lieu_de_mentir(self):
        """Un cliché périmé qu'on garderait mentirait au tour suivant."""
        ca.poser_contexte(
            "/succes/projects",
            ressource_type="project",
            ressource_id="p1",
            ressource_titre="X",
        )
        assert ca.dernier_contexte() is not None
        assert ca.poser_contexte("/une-page-inconnue") is None
        assert ca.dernier_contexte() is None

    def test_une_ressource_non_selectionnable_est_ecartee(self):
        """Le maillage ne sait mettre en évidence qu'un projet, une note ou
        une tâche. Annoncer une dépense « ouverte » serait une promesse que
        rien ne tiendrait."""
        vue = ca.poser_contexte(
            "/succes/finances",
            ressource_type="transaction",
            ressource_id="t9",
            ressource_titre="Loyer",
        )
        assert vue.ressource_id == ""
        assert "Loyer" not in ca.decrire(vue)

    def test_les_champs_sont_bornes(self):
        vue = ca.poser_contexte(
            "/succes/notes",
            ressource_type="note",
            ressource_id="n" * 500,
            ressource_titre="t" * 500,
        )
        assert len(vue.ressource_id) <= 120
        assert len(vue.ressource_titre) <= 120


class TestFraicheur:
    def test_un_cliche_perime_ne_se_lit_plus(self, monkeypatch):
        """Trois minutes plus tard, l'utilisateur a changé d'écran ou fermé
        l'onglet : ne rien dire vaut mieux que dire une vieille chose."""
        ca.poser_contexte("/succes/notes")
        assert ca.dernier_contexte() is not None
        import time as _t

        depart = _t.monotonic()
        monkeypatch.setattr(ca.time, "monotonic", lambda: depart + ca.TTL_S + 1)
        assert ca.dernier_contexte() is None

    def test_oublier_est_immediat(self):
        ca.poser_contexte("/succes/notes")
        ca.oublier()
        assert ca.dernier_contexte() is None
