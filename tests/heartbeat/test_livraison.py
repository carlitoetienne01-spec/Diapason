"""Le texte d'une routine doit atteindre quelqu'un.

``heartbeat/kinds.py`` calculait un drapeau ``delivered`` et rendait le texte à
son appelant. Personne ne l'envoyait nulle part : une routine pouvait tourner,
réussir, consigner son résultat, et n'atteindre personne. Diapason ne se taisait
pas faute d'avoir quelque chose à dire — il n'avait pas de bouche.
"""

from __future__ import annotations

import subprocess
from datetime import datetime

import pytest

from diapason.heartbeat.livraison import (
    echapper_applescript,
    journaliser,
    livrer,
    notifier_macos,
)


class TestEchappement:
    """Un guillemet dans un titre de tâche couperait la commande AppleScript."""

    def test_les_guillemets_sont_echappes(self):
        assert echapper_applescript('dis "bonjour"') == 'dis \\"bonjour\\"'

    def test_les_barres_obliques_sont_echappees_avant_les_guillemets(self):
        """Sinon on échapperait les barres qu'on vient d'ajouter."""
        assert echapper_applescript('a\\b"c') == 'a\\\\b\\"c'

    def test_les_sauts_de_ligne_deviennent_des_espaces(self):
        """``osascript -e`` prend UNE ligne ; un saut casse la commande."""
        assert "\n" not in echapper_applescript("un\ndeux\r\ntrois")

    def test_un_titre_reel_avec_apostrophe_passe(self):
        titre = "Continuer avec l'hébergement de l'application Olala"
        assert echapper_applescript(titre) == titre


class TestNotification:
    def _lanceur(self, code=0, err=""):
        appels = []

        def faux(cmd, **kw):
            appels.append(cmd)
            return subprocess.CompletedProcess(cmd, code, "", err)

        return faux, appels

    def test_le_script_porte_titre_corps_et_sous_titre(self, monkeypatch):
        faux, appels = self._lanceur()
        monkeypatch.setattr(subprocess, "run", faux)
        ok, _ = notifier_macos("Trois retards", "Olala, Taux Lakay")
        assert ok is True
        script = appels[0][-1]
        assert 'display notification "Olala, Taux Lakay"' in script
        assert 'with title "Trois retards"' in script
        assert 'subtitle "Diapason"' in script

    def test_un_echec_est_rapporte_sans_lever(self, monkeypatch):
        faux, _ = self._lanceur(code=1, err="boom")
        monkeypatch.setattr(subprocess, "run", faux)
        ok, detail = notifier_macos("T", "C")
        assert ok is False and "boom" in detail

    def test_hors_macos_on_le_dit_au_lieu_de_lever(self, monkeypatch):
        def absent(*a, **k):
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", absent)
        ok, detail = notifier_macos("T", "C")
        assert ok is False and "osascript" in detail

    def test_un_osascript_qui_se_fige_ne_gele_pas_la_routine(self, monkeypatch):
        def fige(*a, **k):
            raise subprocess.TimeoutExpired("osascript", 10)

        monkeypatch.setattr(subprocess, "run", fige)
        ok, detail = notifier_macos("T", "C")
        assert ok is False and "rendu la main" in detail


class TestJournal:
    def test_le_texte_est_ajoute_avec_son_horodatage(self, tmp_path):
        cible = tmp_path / "briefings.md"
        assert journaliser("Trois retards.", chemin=cible, quand=datetime(2026, 8, 22, 7, 0))
        contenu = cible.read_text(encoding="utf-8")
        assert "## 2026-08-22 07:00" in contenu
        assert "Trois retards." in contenu

    def test_le_journal_s_ajoute_sans_ecraser(self, tmp_path):
        cible = tmp_path / "briefings.md"
        journaliser("Premier", chemin=cible)
        journaliser("Second", chemin=cible)
        contenu = cible.read_text(encoding="utf-8")
        assert "Premier" in contenu and "Second" in contenu

    def test_un_chemin_impossible_ne_leve_pas(self, tmp_path):
        interdit = tmp_path / "fichier"
        interdit.write_text("je suis un fichier, pas un dossier")
        assert journaliser("X", chemin=interdit / "sous" / "b.md") is False


class TestLivrer:
    def test_les_deux_canaux_sont_empruntes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "diapason.heartbeat.livraison.notifier_macos", lambda *a, **k: (True, "")
        )
        r = livrer("T", "C", chemin_journal=tmp_path / "b.md")
        assert r.notifiee and r.journalisee and r.ok

    def test_une_notification_ratee_n_emporte_pas_le_journal(self, tmp_path, monkeypatch):
        """Le journal se relit ; c'est le filet quand la notification échoue."""
        monkeypatch.setattr(
            "diapason.heartbeat.livraison.notifier_macos",
            lambda *a, **k: (False, "refusé"),
        )
        r = livrer("T", "C", chemin_journal=tmp_path / "b.md")
        assert r.notifiee is False
        assert r.journalisee is True
        assert r.ok is True, "rien n'est perdu tant qu'un canal tient"

    def test_le_journal_est_ecrit_MEME_quand_la_notification_aboutit(
        self, tmp_path, monkeypatch
    ):
        """Une notification balayée sans être lue est perdue à jamais."""
        monkeypatch.setattr(
            "diapason.heartbeat.livraison.notifier_macos", lambda *a, **k: (True, "")
        )
        cible = tmp_path / "b.md"
        livrer("T", "Le corps", chemin_journal=cible)
        assert "Le corps" in cible.read_text(encoding="utf-8")

    @pytest.mark.parametrize("notifier", [True, False])
    def test_la_notification_peut_etre_coupee(self, tmp_path, monkeypatch, notifier):
        appelee = []
        monkeypatch.setattr(
            "diapason.heartbeat.livraison.notifier_macos",
            lambda *a, **k: (appelee.append(1), (True, ""))[1],
        )
        livrer("T", "C", notifier=notifier, chemin_journal=tmp_path / "b.md")
        assert bool(appelee) is notifier
