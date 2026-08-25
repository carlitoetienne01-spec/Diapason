"""L'ancre « MAINTENANT » doit être écrite en français.

``strftime('%A %d %B %Y')`` rend « Saturday 22 August 2026 » : une date
ANGLAISE au milieu d'une phrase française, dans le bloc même qui fait autorité
sur tout le contexte. C'est la première chose que lit un modèle à qui l'on
demande de répondre en français, et Carlito rapportait justement des réponses
qui basculaient vers l'anglais.

Le locale du processus ne corrige rien de façon fiable : ``setlocale`` est un
état global, et sur cette machine ``getlocale(LC_TIME)`` rend ``(None, None)``.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("fastapi")

from diapason.server.routes import _JOURS, _MOIS, _now_anchor  # noqa: E402

_MOTS_ANGLAIS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "January",
    "February",
    "March",
    "April",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def test_l_ancre_ne_contient_aucun_mot_anglais():
    ancre = _now_anchor()
    trouves = [m for m in _MOTS_ANGLAIS if m in ancre]
    assert not trouves, f"date anglaise dans une phrase française : {trouves}"


def test_l_ancre_nomme_le_jour_et_le_mois_en_francais():
    ancre = _now_anchor()
    assert any(j in ancre for j in _JOURS), "aucun jour français"
    assert any(m in ancre for m in _MOIS), "aucun mois français"


def test_les_tables_sont_completes_et_dans_l_ordre():
    assert len(_JOURS) == 7 and _JOURS[0] == "lundi", "weekday() compte lundi = 0"
    assert len(_MOIS) == 12 and _MOIS[7] == "août", "month - 1 indexe la table"


def test_l_ancre_garde_le_fuseau_et_l_iso():
    """Sans fuseau, « 14:30 » ne désigne rien ; l'ISO reste lisible par machine."""
    ancre = _now_anchor()
    assert "UTC" in ancre
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ancre)
