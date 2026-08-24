"""« Qu'est-ce que j'ai jeudi ? » répond sur JEUDI (Atlas, 24 août 2026).

Avant : seuls today/tomorrow étaient compris — tout le reste retombait en
silence sur aujourd'hui et donnait le mauvais jour avec aplomb.
"""

from __future__ import annotations

from datetime import date

from diapason.tools.voice_mac_tools import (
    _calendar_events_applescript,
    interpreter_quand,
)

# un dimanche : les calculs de semaine s'y piègent le plus facilement
DIMANCHE = date(2026, 8, 23)


class TestInterpreterQuand:
    def test_les_classiques(self):
        assert interpreter_quand("aujourd'hui", DIMANCHE) == (0, 1, "aujourd'hui")
        assert interpreter_quand("demain", DIMANCHE) == (1, 1, "demain")
        assert interpreter_quand("après-demain", DIMANCHE) == (2, 1, "après-demain")

    def test_un_jour_de_semaine_vise_sa_prochaine_occurrence(self):
        assert interpreter_quand("jeudi", DIMANCHE) == (4, 1, "jeudi")
        assert interpreter_quand("lundi", DIMANCHE) == (1, 1, "lundi")
        # le jour même : « dimanche » = aujourd'hui, « dimanche prochain » = +7
        assert interpreter_quand("dimanche", DIMANCHE) == (0, 1, "dimanche")
        assert interpreter_quand("dimanche prochain", DIMANCHE) == (7, 1, "dimanche")

    def test_les_plages(self):
        assert interpreter_quand("semaine", DIMANCHE) == (0, 7, "les 7 prochains jours")
        assert interpreter_quand("la semaine prochaine", DIMANCHE) == (
            1, 7, "la semaine prochaine",
        )
        assert interpreter_quand("ce week-end", DIMANCHE) == (6, 2, "le week-end")

    def test_une_date_precise(self):
        assert interpreter_quand("2026-08-28", DIMANCHE) == (5, 1, "28/08")

    def test_l_illisible_s_avoue(self):
        assert interpreter_quand("à la saint-glinglin", DIMANCHE) is None


class TestGabarit:
    def test_une_plage_porte_ses_dates(self):
        script = _calendar_events_applescript(1, 7, "la semaine prochaine")
        assert "set dayOffset to 1" in script
        assert "(7 * days)" in script
        assert "day of s" in script  # chaque ligne dit son jour

    def test_un_seul_jour_reste_sobre(self):
        script = _calendar_events_applescript(0, 1, "aujourd'hui")
        assert "day of s" not in script
