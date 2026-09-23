"""P6 (21/09/2026) : la page officielle du sujet, lue en complément de la
recherche — jamais devinée, jamais à la place de la recherche."""

from datetime import date

import pytest

from diapason.server.sources_officielles import (
    VILLES,
    carte_officielle,
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


class TestLaCarteQuandLaRechercheAvaitDejaLaPage:
    """22/09/2026. P6 promettait « officiel · consultée le <aujourd'hui> ».
    Elle ne le tenait QUE lorsque la recherche avait échoué : sinon la page
    figurait déjà parmi les résultats, `renumeroter` la dédoublonnait,
    `nouvelles` sortait vide, et tout le bloc qui pose l'étiquette sautait.
    Constaté en direct sur « Quel est le taux directeur ? » : la Banque du
    Canada, lue par le code à l'instant, s'affichait comme une source
    ordinaire datée de dix-huit mois."""

    @staticmethod
    def page_du_taux():
        page = page_officielle("Quel est le taux directeur ?")
        assert page is not None
        return page

    def test_la_pastille_deja_rendue_par_la_recherche_est_retrouvee(self):
        page = self.page_du_taux()
        deja = [
            {
                "ref": 1,
                "title": "Taux directeur - Banque du Canada",
                "url": page.url,
                "date": "2025-03-12",
                "sender": "banqueducanada.ca",
                "snippet": "Le taux cible du financement à un jour…",
            },
            {"ref": 2, "title": "Un article", "url": "https://exemple.ca/a"},
        ]
        carte, ref = carte_officielle(page, [], deja)
        assert ref == 1, "la carte garde SA pastille, pas une neuve"
        assert carte is not None and carte["official"] is True
        assert carte["date"] == date.today().isoformat(), (
            "une page vivante est datée du jour de sa lecture"
        )

    def test_la_fusion_garde_ce_que_la_recherche_avait_apporte(self):
        """Une carte officielle ne porte que six champs ; une source de
        recherche en porte davantage, et son `title` alimente le score de
        `sources_prometteuses`, qui décide quelle page relire."""
        page = self.page_du_taux()
        deja = [{"ref": 1, "title": "x", "url": page.url, "snippet": "à garder"}]
        carte, _ = carte_officielle(page, [], deja)
        assert carte is not None and carte["snippet"] == "à garder"

    def test_une_autre_page_lue_du_meme_tour_n_est_pas_prise_pour_elle(self):
        """La page du poste peut déjà être dans la liste : seule l'URL
        canonique de CETTE page compte (§34 — on ne devine pas)."""
        page = self.page_du_taux()
        deja = [
            {
                "ref": 1,
                "title": "Premier ministre du Canada — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada",
            },
        ]
        assert carte_officielle(page, [], deja) == (None, None)

    def test_sans_rien_de_connu_ni_de_neuf_la_carte_n_existe_pas(self):
        assert carte_officielle(self.page_du_taux(), [], []) == (None, None)

    def test_une_pastille_neuve_garde_le_comportement_d_avant(self):
        page = self.page_du_taux()
        nouvelles = [{"ref": 7, "title": "Taux directeur", "url": page.url}]
        carte, ref = carte_officielle(page, nouvelles, [], "Taux directeur")
        assert ref == 7 and carte is not None and carte["official"] is True

    def test_le_titre_lu_traverse_les_deux_chemins(self):
        """Sans cela, pm.gc.ca s'afficherait différemment selon que la
        recherche l'avait rendu ou non — deux étiquettes pour une page."""
        pm = page_officielle("Qui est le premier ministre du Canada ?")
        assert pm is not None
        attendu = "Premier ministre du Canada : Le très honorable Mark Carney"
        neuve, _ = carte_officielle(
            pm, [{"ref": 1, "url": pm.url}], [], "Le très honorable Mark Carney"
        )
        connue, _ = carte_officielle(
            pm, [], [{"ref": 1, "url": pm.url}], "Le très honorable Mark Carney"
        )
        assert neuve is not None and connue is not None
        assert neuve["title"] == connue["title"] == attendu
