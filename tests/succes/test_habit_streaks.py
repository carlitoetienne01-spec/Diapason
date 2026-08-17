"""Ce qu'une série d'habitudes doit dire, et quand.

Deux nombres, deux questions différentes. La série COURANTE répond « où
j'en suis » ; le bilan répond « qu'est-ce que j'ai réussi de mieux ». Les
confondre efface le meilleur mois de quelqu'un de l'écran fait pour s'en
souvenir.
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from diapason.succes.continuity import SuccesContinuityStore


@pytest.fixture
def store():
    return SuccesContinuityStore(db_path=Path(tempfile.mkdtemp()) / "succes.db")


def daily_habit(store, name: str, *, started_days_ago: int = 90) -> dict:
    return store.create_habit(
        {
            "name": name,
            "frequency": "daily",
            # La date de début compte : un journal antérieur au démarrage
            # n'est pas dû, donc ne compte pas dans la série.
            "startDate": (date.today() - timedelta(days=started_days_ago)).isoformat(),
        }
    )


def tick(store, habit_id: str, days_ago: int) -> None:
    store.set_habit_done(
        habit_id,
        done=True,
        log_date=(date.today() - timedelta(days=days_ago)).isoformat(),
    )


class TestLeJourEnCoursNeRomptPasLaSerie:
    """Le défaut le plus décourageant : quarante jours affichés « 0 » chaque
    matin, jusqu'à ce qu'on coche la case."""

    def test_la_serie_tient_avant_d_avoir_coche_aujourd_hui(self, store):
        habit = daily_habit(store, "Marcher")
        for i in range(1, 41):
            tick(store, habit["id"], i)
        assert store.get_habit(habit["id"])["streak"] == 40

    def test_cocher_aujourd_hui_ajoute_la_journee(self, store):
        habit = daily_habit(store, "Marcher")
        for i in range(1, 41):
            tick(store, habit["id"], i)
        tick(store, habit["id"], 0)
        assert store.get_habit(habit["id"])["streak"] == 41

    def test_un_vrai_oubli_rompt_bien_la_serie(self, store):
        """Le jour en cours est enjambé parce qu'il n'est pas écoulé. Hier
        l'est : l'oublier casse, et ce test garde la correction d'être une
        indulgence générale."""
        habit = daily_habit(store, "Lire")
        for i in range(2, 41):  # hier manque
            tick(store, habit["id"], i)
        assert store.get_habit(habit["id"])["streak"] == 0

    def test_une_habitude_jamais_tenue_reste_a_zero(self, store):
        habit = daily_habit(store, "Courir")
        assert store.get_habit(habit["id"])["streak"] == 0


class TestLeBilanRegardeEnArriere:
    def test_il_retrouve_la_meilleure_serie_meme_abandonnee(self, store):
        """Quelqu'un qui a tenu soixante jours puis s'est arrêté lisait « 0 » :
        le bilan prenait le maximum des séries EN COURS."""
        year = date.today().year
        habit = store.create_habit(
            {
                "name": "Marcher",
                "frequency": "daily",
                "startDate": date(year, 1, 1).isoformat(),
            }
        )
        start = date(year, 3, 1)
        for i in range(60):
            store.set_habit_done(
                habit["id"], done=True, log_date=(start + timedelta(days=i)).isoformat()
            )

        assert store.get_habit(habit["id"])["streak"] == 0
        review = store.year_review(year)
        assert review["catalog"]["longestHabitStreak"] == 60

    def test_il_garde_la_plus_longue_de_plusieurs_series(self, store):
        year = date.today().year
        habit = store.create_habit(
            {
                "name": "Lire",
                "frequency": "daily",
                "startDate": date(year, 1, 1).isoformat(),
            }
        )
        for start, length in ((date(year, 2, 1), 12), (date(year, 5, 1), 31)):
            for i in range(length):
                store.set_habit_done(
                    habit["id"],
                    done=True,
                    log_date=(start + timedelta(days=i)).isoformat(),
                )
        assert store.year_review(year)["catalog"]["longestHabitStreak"] == 31

    def test_sans_habitude_tenue_le_bilan_dit_zero(self, store):
        year = date.today().year
        daily_habit(store, "Méditer")
        assert store.year_review(year)["catalog"]["longestHabitStreak"] == 0
