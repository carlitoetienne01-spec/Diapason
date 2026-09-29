"""29/09/2026 : la prévision ne valait que pour les villes de la table
canadienne. « Quel temps à Lyon ? » avec Ottawa en config ne lisait rien,
et la config ne doit pas prendre la place d'une ville nommée."""

import json

import pytest

from diapason.server.meteo_ouverte import lire_prevision_ouverte, ville_hors_table


class TestLaVilleEcrite:
    @pytest.mark.parametrize(
        ("question", "attendu"),
        [
            ("Quel temps fait-il à Tombouctou ?", "Tombouctou"),
            ("Quel temps fait-il à New York ?", "New York"),
            ("Météo à Tokyo", "Tokyo"),
            ("What's the weather in Lisbon?", "Lisbon"),
            ("prévision pour Lyon demain", "Lyon"),
            ("météo à lyon", "lyon"),
            ("Quel temps fait-il à Ottawa ?", ""),
            ("Quel temps fait-il ce soir ?", ""),
            ("Météo en France", ""),
            ("Quelle température il fait à présentement ?", ""),
        ],
    )
    def test_une_ville_nommee_hors_table_est_retenue(self, question, attendu):
        assert ville_hors_table(question) == attendu, (
            "la ville écrite compte, pas seulement la table canadienne"
        )

    def test_la_config_ne_remplace_pas_la_ville_nommee(self):
        assert ville_hors_table("Quel temps fait-il à Paris ?") == "Paris", (
            "Ottawa en config ne répond pas à la place de Paris"
        )


class TestLaPrevision:
    def test_lyon_donne_le_degre_et_le_pays(self):
        vues: list[str] = []

        def obtenir(url: str) -> str:
            vues.append(url)
            if "search" in url:
                return json.dumps(
                    {
                        "results": [
                            {
                                "name": "Lyon",
                                "country": "France",
                                "latitude": 45.75,
                                "longitude": 4.85,
                            }
                        ]
                    }
                )
            return json.dumps({"current": {"temperature_2m": 18.2, "weather_code": 2}})

        texte = lire_prevision_ouverte("Quel temps fait-il à Lyon ?", obtenir=obtenir)
        assert any("Lyon" in url for url in vues), "le nom demandé est géocodé"
        assert "Lyon" in texte and "France" in texte
        assert "18,2 °C" in texte, "le degré lu doit être dans le texte"
        assert "Open-Meteo" in texte
        assert "Ottawa" not in texte

    def test_sans_resultat_rien_n_est_invente(self):
        def obtenir(url: str) -> str:
            return json.dumps({"results": []}) if "search" in url else "{}"

        assert (
            lire_prevision_ouverte("Quel temps fait-il à Nullepart ?", obtenir=obtenir)
            == ""
        ), "une ville introuvable ne reçoit pas la prévision d'une autre"

    def test_une_panne_reseau_ne_devine_pas(self):
        def obtenir(url: str) -> str:
            raise OSError("réseau coupé")

        assert (
            lire_prevision_ouverte("Quel temps fait-il à Tokyo ?", obtenir=obtenir)
            == ""
        )


def test_la_derniere_url_de_meteo_donne_les_coordonnees(tmp_path):
    import sqlite3

    from diapason.server.meteo_systeme import coordonnees_meteo_mac, phrase_ici

    base = tmp_path / "Cache.db"
    connexion = sqlite3.connect(base)
    connexion.execute(
        "CREATE TABLE cfurl_cache_response("
        "entry_ID INTEGER PRIMARY KEY, request_key TEXT)"
    )
    connexion.execute(
        "INSERT INTO cfurl_cache_response(request_key) VALUES (?)",
        ("https://weatherkit.apple.com/api/v2/weather/fr-CA/45.420/-75.690?x=1",),
    )
    connexion.execute(
        "INSERT INTO cfurl_cache_response(request_key) VALUES (?)",
        ("https://weatherkit.apple.com/api/v2/weather/fr-CA/45.448/-73.433?x=1",),
    )
    connexion.commit()
    connexion.close()
    assert coordonnees_meteo_mac(base) == (45.448, -73.433), (
        "la dernière prévision ouverte, pas une ville plus ancienne"
    )

    def obtenir(url: str) -> str:
        if "nominatim" in url:
            return json.dumps(
                {"address": {"town": "Boucherville", "country": "Canada"}}
            )
        return json.dumps({"current": {"temperature_2m": 14.2, "weather_code": 0}})

    assert (
        phrase_ici(
            "Quelle température il fait à présentement ?",
            localiser=lambda: coordonnees_meteo_mac(base),
            obtenir=obtenir,
        )
        == "À Boucherville, il fait 14,2 °C."
    )
    assert (
        phrase_ici("Quel temps fait-il à Lyon ?", localiser=lambda: (1.0, 2.0)) == ""
    ), "une ville nommée ne cède pas la place au Mac"
