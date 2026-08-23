"""La perception du bureau : lecture, cache, description française."""

from __future__ import annotations

import diapason.desktop.etat_bureau as eb
from diapason.desktop.etat_bureau import EtatBureau, decrire, etat_du_bureau, interpreter

SORTIE = "App Store\nSafari|Notes|WhatsApp|App Store\n"


def _sans_cache(monkeypatch):
    monkeypatch.setattr(eb, "_cache", None)


class TestInterpreter:
    def test_le_premier_plan_et_les_apps_se_lisent(self):
        etat = interpreter(SORTIE)
        assert etat.premier_plan == "App Store"
        assert etat.en_marche == ("Safari", "Notes", "WhatsApp", "App Store")

    def test_une_sortie_vide_rend_none(self):
        assert interpreter("") is None
        assert interpreter("\n") is None


class TestCache:
    def test_le_cliche_frais_ne_relit_pas(self, monkeypatch):
        _sans_cache(monkeypatch)
        lectures = []

        def runner(_s):
            lectures.append(1)
            return SORTIE

        pendule = {"t": 100.0}
        horloge = lambda: pendule["t"]  # noqa: E731
        monkeypatch.setattr("time.monotonic", horloge)
        etat_du_bureau(runner=runner, horloge=horloge)
        pendule["t"] += 2.0
        etat_du_bureau(runner=runner, horloge=horloge)
        assert len(lectures) == 1
        pendule["t"] += 10.0
        etat_du_bureau(runner=runner, horloge=horloge)
        assert len(lectures) == 2

    def test_une_lecture_en_panne_garde_le_vieux_cliche(self, monkeypatch):
        _sans_cache(monkeypatch)

        def casse(_s):
            raise RuntimeError("osascript grognon")

        pendule = {"t": 100.0}
        horloge = lambda: pendule["t"]  # noqa: E731
        monkeypatch.setattr("time.monotonic", horloge)
        etat_du_bureau(runner=lambda _s: SORTIE, horloge=horloge)
        pendule["t"] += 60.0
        etat = etat_du_bureau(runner=casse, horloge=horloge)
        assert etat is not None and etat.premier_plan == "App Store"


class TestDecrire:
    def test_une_phrase_francaise_prete_pour_le_contexte(self):
        etat = EtatBureau("App Store", ("Safari", "Notes", "App Store"), 0.0)
        assert decrire(etat) == (
            "État du bureau : au premier plan, App Store. "
            "Aussi en marche : Safari, Notes."
        )

    def test_la_liste_longue_se_coupe_et_se_compte(self):
        etat = EtatBureau("Safari", tuple(f"App{i}" for i in range(20)), 0.0)
        texte = decrire(etat, limite=3)
        assert "App0, App1, App2 (+17)" in texte
