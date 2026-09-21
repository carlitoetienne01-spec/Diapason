"""P6 (21/09/2026) : la page officielle du sujet, lue en complément de la
recherche — jamais devinée, jamais à la place de la recherche."""

from datetime import date

import pytest

from diapason.server.sources_officielles import (
    VILLES,
    entete_officielle,
    page_officielle,
    source_officielle,
    ville_de,
)


class TestLaVille:
    @pytest.mark.parametrize(
        ("question", "attendu"),
        [
            ("Va-t-il pleuvoir à Montréal ?", "montreal"),
            ("La météo à Trois-Rivières demain", "trois-rivieres"),
            ("Quel temps fait-il à québec ?", "quebec"),
            ("Quel temps fait-il ce soir ?", "ottawa"),
            ("Quel temps fait-il à Tombouctou ?", ""),
            ("Quel temps fait-il à Paris ?", ""),
        ],
        ids=[
            "montreal",
            "accents-et-tiret",
            "minuscules",
            "config",
            "inconnue",
            "paris",
        ],
    )
    def test_la_ville_de_la_question_puis_celle_de_la_config(self, question, attendu):
        assert ville_de(question, "Ottawa") == attendu

    def test_sans_config_aucune_ville_devinee(self):
        assert ville_de("Quel temps fait-il ce soir ?") == "", "§34 : on ne devine pas"
        assert ville_de("Quel temps fait-il ce soir ?", "Paris") == "", (
            "une ville de config hors de la table ne vaut rien"
        )

    def test_la_table_a_des_coordonnees_plausibles(self):
        for cle, (lat, lon, nom) in VILLES.items():
            assert 41 <= lat <= 84 and -142 <= lon <= -52, (cle, lat, lon)
            assert nom


class TestLaPageOfficielle:
    def test_la_meteo_d_environnement_canada(self):
        page = page_officielle("Va-t-il pleuvoir demain à Gatineau ?")
        assert page is not None
        assert (
            page.url
            == "https://meteo.gc.ca/fr/location/index.html?coords=45.477,-75.701"
        )
        assert page.domaine == "meteo.gc.ca" and "Gatineau" in page.titre
        assert page.focus.startswith("ce soir cette nuit demain"), (
            "les fenêtres du lecteur se posent sur la prévision du soir et du lendemain"
        )

    def test_le_taux_directeur_de_la_banque_du_canada(self):
        page = page_officielle("Quel est le taux directeur ?")
        assert page is not None and page.domaine == "banqueducanada.ca"

    def test_rien_pour_le_reste(self):
        assert page_officielle("Qui est le premier ministre du Canada ?") is None
        assert page_officielle("Quel est le prix du bitcoin ?") is None
        assert page_officielle("Quel temps fait-il ce soir ?") is None, "sans ville"

    def test_l_en_tete_et_la_source_sont_datees_du_jour(self):
        page = page_officielle("météo Ottawa")
        assert page is not None
        entete = entete_officielle(page, 3)
        assert entete.startswith("[3] Ottawa — Prévision 7 jours, Environnement Canada")
        assert f"source officielle · consultée le {date.today().isoformat()}" in entete
        assert source_officielle(page, 3) == {
            "ref": 3,
            "title": page.titre,
            "url": page.url,
            "date": date.today().isoformat(),
            "sender": "meteo.gc.ca",
            "official": True,
        }
