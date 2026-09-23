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

    def test_le_premier_ministre_du_canada_a_sa_page(self):
        """Le défaut fondateur du chantier : « Justin Trudeau [3] », cité,
        daté, faux — aucun des cinq extraits ne nommait le titulaire. Le
        Cabinet du Premier ministre titre sa page du nom de celui-ci."""
        for question in (
            "Qui est le premier ministre du Canada ?",
            "Who is the prime minister of Canada?",
            "Le premier ministre canadien est qui en ce moment",
        ):
            page = page_officielle(question)
            assert page is not None, question
            assert page.domaine == "pm.gc.ca"
            assert page.titre_de_la_page, "le titre de cette page EST le fait"

    def test_un_premier_ministre_sans_pays_ne_devine_pas(self):
        """§34 : un « premier ministre » nu peut être celui du Québec, de la
        France ou du Japon. La recherche générale lui reste seule."""
        assert page_officielle("Qui est le premier ministre du Québec ?") is None
        assert page_officielle("Qui est le premier ministre ?") is None
        assert page_officielle("Qui est le premier ministre du Japon ?") is None

    def test_les_taux_de_change_quotidiens(self):
        for question in (
            "Quel est le taux de change du dollar américain ?",
            "Combien vaut un euro en dollars canadiens ?",
            "Quel est le cours du yen aujourd'hui ?",
        ):
            page = page_officielle(question)
            assert page is not None, question
            assert page.domaine == "banqueducanada.ca"
            assert "taux-de-change" in page.url

    def test_le_taux_directeur_n_est_pas_un_taux_de_change(self):
        page = page_officielle("Quel est le taux directeur ?")
        assert page is not None and "politique-monetaire" in page.url

    def test_rien_pour_le_reste(self):
        assert page_officielle("Quel est le prix du bitcoin ?") is None
        assert page_officielle("Quel temps fait-il ce soir ?") is None, "sans ville"
        assert page_officielle("Combien vaut ma maison ?") is None

    def test_le_titre_lu_rejoint_l_etiquette_quand_il_porte_le_fait(self):
        """Écraser le titre de pm.gc.ca jetait la réponse ; le garder seul ne
        dirait pas de quel poste il s'agit."""
        page = page_officielle("Qui est le premier ministre du Canada ?")
        assert page is not None
        entete = entete_officielle(page, 2, "Le très honorable Mark Carney")
        assert entete.startswith(
            "[2] Premier ministre du Canada : Le très honorable Mark Carney — pm.gc.ca"
        )
        assert source_officielle(page, 2, "Le très honorable Mark Carney")["title"] == (
            "Premier ministre du Canada : Le très honorable Mark Carney"
        )

    def test_sans_titre_lu_l_etiquette_tient_seule(self):
        """Une page qui ne rend pas de titre ne doit pas laisser un « : » nu."""
        page = page_officielle("Qui est le premier ministre du Canada ?")
        assert page is not None
        assert entete_officielle(page, 1, "   ").startswith(
            "[1] Premier ministre du Canada — pm.gc.ca"
        )

    def test_le_titre_lu_ne_change_rien_a_une_page_etiquetee(self):
        """La météo garde son étiquette : le titre de la page dit « Météo -
        Environnement Canada », qui ne dit pas quelle ville on lit."""
        page = page_officielle("météo Ottawa")
        assert page is not None
        assert "Météo - Environnement Canada" not in entete_officielle(
            page, 1, "Météo - Environnement Canada"
        )

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
