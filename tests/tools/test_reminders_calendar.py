"""Rappels et Calendrier : créer ce que l'utilisateur dicte, sans se tromper de jour.

Aucun AppleScript ne part vraiment ici : les doublures capturent les appels.
Ce que ces tests tiennent : les dates parlées passent par le même analyseur
que Succès, les dates AMBIGUËS sont refusées avec les deux propositions, la
date voyage en NOMBRES (année, mois, jour…) — jamais en texte que la langue
du système relirait à sa façon — et le texte dicté part en argv.
"""

from __future__ import annotations

from datetime import date

import pytest

from diapason.tools import app_actions
from diapason.tools.reminders_calendar import (
    CalendarAddTool,
    RemindersWriteTool,
    _date_parlee,
    _heure_parlee,
)


@pytest.fixture()
def espion(monkeypatch):
    appels: list[tuple] = []

    def faux(script, *args):
        appels.append((script, args))
        return True, "ok"

    # reminders_calendar importe _osascript depuis app_actions : c'est LÀ
    # qu'il faut poser la doublure.
    monkeypatch.setattr(app_actions, "_osascript", faux)
    import diapason.tools.reminders_calendar as rc

    monkeypatch.setattr(rc, "_osascript", faux)
    return appels


class TestDatesParlees:
    def test_demain_devient_une_date_exacte(self):
        jour, erreur = _date_parlee("demain")
        assert erreur == ""
        assert (
            jour
            == date.today()
            .replace(day=date.today().day)
            .fromordinal(date.today().toordinal() + 1)
            .isoformat()
        )

    def test_une_date_ambigue_est_refusee_avec_les_deux_choix(self):
        """« Vendredi prochain » peut désigner deux jours : un rendez-vous posé
        le mauvais jour est pire qu'une question de plus."""
        jour, erreur = _date_parlee("vendredi prochain")
        assert jour is None
        assert "deux jours" in erreur
        assert erreur.count("2026-") == 2

    def test_le_charabia_est_refuse(self):
        jour, erreur = _date_parlee("bleu turquoise")
        assert jour is None and "pas reconnu" in erreur

    @pytest.mark.parametrize(
        "dit,attendu",
        [
            ("15:00", (15, 0)),
            ("15 h", (15, 0)),
            ("15h30", (15, 30)),
            ("9 heures", (9, 0)),
            ("minuit et quart", (None,)),
        ],
    )
    def test_les_heures_orales(self, dit, attendu):
        r = _heure_parlee(dit)
        assert r[0] == attendu[0]
        if attendu[0] is not None:
            assert (r[0], r[1]) == attendu


class TestRappels:
    def test_creer_avec_echeance_envoie_la_date_en_nombres(self, espion):
        r = RemindersWriteTool().execute(
            action="create", name="Appeler le dentiste", date="2026-08-25", time="15 h"
        )
        assert r.success and "2026-08-25 à 15:00" in r.content
        script, args = espion[0]
        assert args == ("2026", "08", "25", "15", "0", "Appeler le dentiste")
        assert "Appeler" not in script, "le texte dicté ne s'interpole jamais"

    def test_sans_heure_dite_le_rappel_est_du_matin(self, espion):
        r = RemindersWriteTool().execute(
            action="create", name="Sortir les poubelles", date="2026-08-25"
        )
        assert r.success and "09:00" in r.content

    def test_sans_date_le_rappel_reste_sans_echeance(self, espion):
        r = RemindersWriteTool().execute(action="create", name="Penser à respirer")
        assert r.success and "pour le" not in r.content
        _, args = espion[0]
        assert args == ("Penser à respirer",)

    def test_cocher_un_rappel_absent_le_dit(self, monkeypatch):
        import diapason.tools.reminders_calendar as rc

        monkeypatch.setattr(rc, "_osascript", lambda s, *a: (True, "absent"))
        r = RemindersWriteTool().execute(action="complete", name="licorne")
        assert r.success is False and "Aucun rappel" in r.content


class TestCalendrier:
    def test_le_rendez_vous_part_avec_duree_et_titre_en_argv(self, espion):
        r = CalendarAddTool().execute(
            summary="Coiffeur", date="2026-08-25", time="10 h", duration_minutes=30
        )
        assert r.success
        _, args = espion[0]
        assert args == ("2026", "08", "25", "10", "0", "30", "", "Coiffeur")

    def test_la_duree_par_defaut_est_une_heure(self, espion):
        CalendarAddTool().execute(summary="X", date="2026-08-25", time="9 h")
        _, args = espion[0]
        assert args[5] == "60"

    def test_une_date_ambigue_n_ecrit_rien(self, espion):
        r = CalendarAddTool().execute(summary="X", date="vendredi prochain", time="9 h")
        assert r.success is False
        assert espion == [], "rien ne doit partir tant que le jour n'est pas sûr"

    def test_un_calendrier_inconnu_rend_la_liste(self, monkeypatch):
        import diapason.tools.reminders_calendar as rc

        monkeypatch.setattr(
            rc, "_osascript", lambda s, *a: (True, "?\nDomicile, Travail")
        )
        r = CalendarAddTool().execute(
            summary="X", date="2026-08-25", time="9 h", calendar="Boulot"
        )
        assert r.success is False
        assert "Domicile, Travail" in r.content
