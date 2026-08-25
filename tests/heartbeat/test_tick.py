"""La veille de jour : trois regards, jamais deux fois la même alerte."""

from __future__ import annotations

from datetime import datetime

import pytest

from diapason.heartbeat.tick import (
    cron_correspond,
    echu_depuis,
    etat_batterie,
    evenements_imminents,
    faire_le_tick,
)

MIDI = datetime(2026, 8, 24, 12, 0)


class TestMiniCron:
    def test_les_formes_admises(self):
        assert cron_correspond("0 12 * * *", MIDI)
        assert cron_correspond("*/15 * * * *", MIDI)
        assert cron_correspond("0,30 12 * * 1", MIDI)  # lundi
        assert not cron_correspond("30 12 * * *", MIDI)
        assert not cron_correspond("0 12 * * 0", MIDI)  # dimanche

    def test_l_illisible_est_refuse_bruyamment(self):
        with pytest.raises(ValueError):
            cron_correspond("bientôt", MIDI)
        with pytest.raises(ValueError):
            cron_correspond("0 12 * *", MIDI)  # 4 champs

    def test_echu_couvre_la_fenetre_et_pas_plus(self):
        d1145 = datetime(2026, 8, 24, 11, 45)
        assert echu_depuis("0 12 * * *", d1145, MIDI)
        assert not echu_depuis("44 11 * * *", d1145, MIDI)  # avant la fenêtre
        # un tick endormi 2 jours ne rattrape que 4 heures
        avant_hier = datetime(2026, 8, 22, 12, 0)
        assert not echu_depuis("0 3 * * *", avant_hier, MIDI)


class TestAgenda:
    def test_la_fenetre_retient_l_imminent(self):
        contenu = (
            "Events for aujourd'hui:\n12:10 — Dentiste\n14:30 — Marche\n11:50 — Passé"
        )
        imminents = evenements_imminents(contenu, MIDI)
        assert [(t, r) for _c, r, t in imminents] == [("Dentiste", 10)]

    def test_le_meme_evenement_ne_sonne_qu_une_fois(self, tmp_path):
        contenu = "12:10 — Dentiste"
        notifications = []
        for _ in range(2):
            faire_le_tick(
                MIDI,
                workspace=tmp_path,
                agenda=lambda: contenu,
                batterie=lambda: None,
                notifier=lambda t, c: notifications.append((t, c)),
                routines=[],
            )
        assert notifications == [("Rendez-vous", "dans 10 min : Dentiste")]


class TestBatterie:
    def test_pmset_se_lit(self):
        sortie = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=123)\t9%; discharging; 0:42 remaining"  # noqa: E501 - sortie réelle de pmset, reproduite telle quelle
        assert etat_batterie(sortie) == (9, True)
        assert etat_batterie("garbage") is None

    def test_l_alerte_part_une_fois_et_se_rearme_a_la_charge(self, tmp_path):
        notifications = []
        mesures = iter([(9, True), (8, True), (50, False), (12, True)])

        def batterie():
            return next(mesures)

        for _ in range(4):
            faire_le_tick(
                MIDI,
                workspace=tmp_path,
                agenda=lambda: "",
                batterie=batterie,
                notifier=lambda t, c: notifications.append((t, c)),
                routines=[],
            )
        assert notifications == [
            ("Batterie", "9 % — pense au chargeur."),
            ("Batterie", "12 % — pense au chargeur."),
        ]


class TestRappels:
    def test_un_rappel_du_part_et_s_enregistre(self, tmp_path):
        class Routine:
            id = "cafe"
            name = "Pause café"
            kind = "reminder"
            enabled = True
            schedule = "0 12 * * *"
            payload = {"message": "Va marcher cinq minutes."}

        notifications = []
        passage = faire_le_tick(
            MIDI,
            workspace=tmp_path,
            agenda=lambda: "",
            batterie=lambda: None,
            notifier=lambda t, c: notifications.append((t, c)),
            routines=[Routine()],
        )
        assert passage.rappels_livres == 1
        assert notifications == [("Rappel", "Va marcher cinq minutes.")]

    def test_un_horaire_illisible_se_signale_sans_bloquer(self, tmp_path):
        class Routine:
            id = "brise"
            name = "Brisée"
            kind = "reminder"
            enabled = True
            schedule = "bientôt"
            payload = {}

        passage = faire_le_tick(
            MIDI,
            workspace=tmp_path,
            agenda=lambda: "",
            batterie=lambda: None,
            notifier=lambda _t, _c: None,
            routines=[Routine()],
        )
        assert passage.rappels_livres == 0
        assert any("illisible" in e for e in passage.erreurs)
