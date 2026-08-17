"""L'âge d'un message, dit sans mentir.

Le briefing du matin lit ces mots à voix haute : « Marie vient de vous
écrire » n'est pas la même information que « Marie vous a écrit ce matin ».
La faute était invisible parce qu'elle valait exactement le décalage du
fuseau — un nombre plausible, jamais absurde, et donc jamais suspect.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from diapason.tools.digest_collect import _time_ago


def utc_ago(**kwargs) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kwargs)


class TestUnHorodatageUtcEstLuCommeTel:
    """Tous les connecteurs rendent de l'UTC. C'est le cas qui comptait."""

    @pytest.mark.parametrize(
        "hours,expected",
        [(1, "1h ago"), (2, "2h ago"), (3, "3h ago"), (4, "4h ago"), (6, "6h ago")],
    )
    def test_les_heures_sont_justes(self, hours, expected):
        # Avant : tout ce qui avait moins de quatre heures rendait « just now »
        # sur une machine à UTC-4, parce que le fuseau était arraché sans
        # conversion puis comparé à l'heure locale.
        assert _time_ago(utc_ago(hours=hours)) == expected

    def test_les_minutes_aussi(self):
        assert _time_ago(utc_ago(minutes=30)) == "30m ago"
        assert _time_ago(utc_ago(minutes=5)) == "5m ago"

    def test_just_now_est_reserve_a_ce_qui_vient_d_arriver(self):
        assert _time_ago(utc_ago(seconds=20)) == "just now"

    def test_les_jours(self):
        assert _time_ago(utc_ago(days=2)) == "2d ago"


class TestLesFormesQuiCassaient:
    def test_un_horodatage_sans_fuseau_est_suppose_utc(self):
        """C'est ce que rendent les connecteurs ; le supposer local serait
        refaire le même pari dans l'autre sens."""
        naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
        assert _time_ago(naive) == "3h ago"

    def test_un_autre_fuseau_donne_le_meme_age(self):
        """L'âge d'un message ne dépend pas du fuseau où il a été écrit."""
        from datetime import timedelta as td

        tokyo = timezone(td(hours=9))
        assert _time_ago(datetime.now(tokyo) - timedelta(hours=2)) == "2h ago"

    def test_un_horodatage_futur_le_dit_au_lieu_de_le_masquer(self):
        """Le `max(0, ...)` d'avant transformait un futur en « just now » —
        il masquait précisément le signe négatif qui aurait rendu le défaut
        visible le jour où quelqu'un l'aurait cherché."""
        assert _time_ago(datetime.now(timezone.utc) + timedelta(hours=1)) == (
            "in the future"
        )
