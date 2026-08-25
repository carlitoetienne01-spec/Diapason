"""Installer à la demande : Homebrew d'abord, l'App Store en repli.

Aucune vraie installation ici : les doublures capturent les commandes. Ce que
ces tests tiennent : pas de doublon (déjà installée → on ouvre), le cask part
détaché avec sa notification de fin, l'App Store est le repli, et l'outil
exige l'accord de l'utilisateur — installer du logiciel sur une phrase
peut-être mal transcrite mérite un clic.
"""

from __future__ import annotations

import subprocess

from diapason.tools import app_install as mod
from diapason.tools.app_install import AppInstallTool, _chercher_cask


def test_l_outil_exige_l_accord():
    assert AppInstallTool().spec.requires_confirmation is True


def test_sans_nom_le_refus_est_franc():
    r = AppInstallTool().execute(name="  ")
    assert r.success is False


def test_deja_installee_on_ouvre_au_lieu_de_reinstaller(monkeypatch):
    from diapason.desktop.app_index import APP_INDEX

    monkeypatch.setattr(APP_INDEX, "lookup", lambda n: "VLC")
    ouverts = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: (ouverts.append(cmd), subprocess.CompletedProcess(cmd, 0))[1],
    )
    r = AppInstallTool().execute(name="vlc")
    assert r.success and "déjà installée" in r.content
    assert ouverts == [["open", "-a", "VLC"]]


def test_le_cask_part_detache_avec_sa_notification(monkeypatch):
    from diapason.desktop.app_index import APP_INDEX

    monkeypatch.setattr(APP_INDEX, "lookup", lambda n: None)
    monkeypatch.setattr(mod, "_chercher_cask", lambda n: "vlc")
    monkeypatch.setattr(mod, "_brew", lambda: "/opt/homebrew/bin/brew")
    lances = []

    class FauxPopen:
        def __init__(self, cmd, **kw):
            lances.append((cmd, kw))

    monkeypatch.setattr(subprocess, "Popen", FauxPopen)
    r = AppInstallTool().execute(name="VLC")
    assert r.success and "arrière-plan" in r.content
    ((cmd, kw),) = lances
    commande = cmd[-1]
    assert "brew install --cask vlc" in commande
    assert "display notification" in commande, "la fin doit s'annoncer"
    assert kw.get("start_new_session") is True, "détaché : la conversation continue"


def test_sans_cask_l_app_store_s_ouvre(monkeypatch):
    from diapason.desktop.app_index import APP_INDEX

    monkeypatch.setattr(APP_INDEX, "lookup", lambda n: None)
    monkeypatch.setattr(mod, "_chercher_cask", lambda n: None)
    ouverts = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: (ouverts.append(cmd), subprocess.CompletedProcess(cmd, 0))[1],
    )
    r = AppInstallTool().execute(name="Un Logiciel Rare")
    assert r.success and "App Store" in r.content
    assert "MZSearch" in ouverts[0][1]


class TestChercherCask:
    """« zoom » rend aussi gzdoom et photozoom-pro : seul l'exact compte."""

    def _brew_factice(self, sortie):
        def run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout=sortie, stderr="")

        return run

    def test_seul_le_nom_exact_est_retenu(self, monkeypatch):
        monkeypatch.setattr(mod, "_brew", lambda: "brew")
        monkeypatch.setattr(
            subprocess, "run", self._brew_factice("gzdoom\nphotozoom-pro\nzoom\n")
        )
        assert _chercher_cask("zoom") == "zoom"

    def test_les_tirets_se_plient(self, monkeypatch):
        monkeypatch.setattr(mod, "_brew", lambda: "brew")
        monkeypatch.setattr(
            subprocess, "run", self._brew_factice("google-chrome\ngoogle-chrome@beta\n")
        )
        assert _chercher_cask("google chrome") == "google-chrome"

    def test_un_a_peu_pres_est_refuse(self, monkeypatch):
        """Installer le mauvais logiciel est pire que renvoyer à l'App Store."""
        monkeypatch.setattr(mod, "_brew", lambda: "brew")
        monkeypatch.setattr(
            subprocess, "run", self._brew_factice("gzdoom\nphotozoom-pro\n")
        )
        assert _chercher_cask("zoom") is None
