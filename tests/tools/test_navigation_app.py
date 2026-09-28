"""§100 : une commande remise n'est pas une page affichée."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from diapason.tools import navigation_app as nav
from diapason.vie.store import VieError


class TestNavigation:
    def test_ecrire_dans_une_page_ne_tape_pas_dans_une_app_approximative(self):
        """§100 : le rédacteur interne doit recevoir une commande composite."""
        from diapason.actions.router import FastActionRouter

        assert (
            FastActionRouter().route("Ouvre la page Notes de Diapason et écris Bonjour")
            is None
        ), "aucune frappe dans une application choisie approximativement"

    @pytest.mark.parametrize(
        "texte",
        [
            "Ouvre la page Finances de Diapason.",
            "Affiche les finances dans Diapason",
            "Diapason, ouvre les finances",
            "Va dans la section Finances",
        ],
    )
    def test_la_page_n_est_pas_une_application(self, texte):
        """§100 : ne pas confondre afficher la page et lancer le programme."""
        from diapason.actions.router import FastActionRouter

        action = FastActionRouter().route(texte)
        assert action.kind == "voice.app_page" and action.target == "finances", (
            "destination interne précise"
        )

    @pytest.mark.parametrize(
        "texte",
        [
            "Ouvre Notes",
            "Ouvre Diapason",
            "Ouvre Safari",
            "Ouvre Finances dans Diapason puis supprime mon compte",
        ],
    )
    def test_les_autres_intentions_restent_distinctes(self, texte):
        """§34 : ne pas avaler une autre action ni une commande composite."""
        assert nav.page_demandee(texte) is None, "laisser la cible initiale intacte"

    def test_pages_alignees_sur_interface(self):
        """§82 : toutes les pages de l'interface sont atteignables."""
        source = Path("frontend/src/features/roue/pagesRoue.ts").read_text()
        chemins = set(re.findall(r"chemin: '([^']+)'", source))
        assert set(nav.PAGES.values()) == chemins, "ni page oubliée, ni page inventée"

    def test_aucune_fenetre_aucune_navigation(self, monkeypatch):
        """§100 : ne pas garder une commande qui ouvrirait plus tard."""
        monkeypatch.setattr(nav, "shell_is_collecting", lambda: False)
        with pytest.raises(VieError, match="Aucune fenêtre"):
            nav.naviguer("finances")

    def test_attendre_la_vue_receptrice(self, monkeypatch):
        """§100 : l'affichage confirmé vient de l'interface."""
        vues = iter([None, SimpleNamespace(chemin="/vie/finances", quand=float("inf"))])
        envoyes = []
        monkeypatch.setattr(nav, "shell_is_collecting", lambda: True)
        monkeypatch.setattr(nav, "dernier_contexte", lambda: next(vues))
        monkeypatch.setattr(
            nav, "push_shell_event", lambda e: envoyes.append(e) or True
        )
        assert nav.naviguer("finances")["displayed"], "la vue confirme"
        assert envoyes[0]["appPath"] == "/vie/finances", "destination exacte"

    def test_pas_de_faux_succes_sans_vue(self, monkeypatch):
        """§100 : accepter en file ne prouve pas l'affichage."""
        horloge = iter([0, 5])
        monkeypatch.setattr(nav, "shell_is_collecting", lambda: True)
        monkeypatch.setattr(nav, "dernier_contexte", lambda: None)
        monkeypatch.setattr(nav, "push_shell_event", lambda e: True)
        monkeypatch.setattr(nav.time, "monotonic", lambda: next(horloge))
        with pytest.raises(VieError, match="pas confirmé"):
            nav.naviguer("notes")
