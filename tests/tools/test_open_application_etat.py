"""open_application regarde avant, vérifie après, et parle vrai."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

import diapason.desktop.etat_bureau as eb
from diapason.desktop.etat_bureau import EtatBureau
from diapason.tools.desktop_tools import open_application

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")


def _etat(premier, en_marche):
    return EtatBureau(premier, tuple(en_marche), 0.0)


def _ouvrir(monkeypatch, *, etat, devant_apres, run_ok=True):
    monkeypatch.setattr(eb, "etat_du_bureau", lambda **_k: etat)
    monkeypatch.setattr(eb, "premier_plan", lambda *a, **_k: devant_apres)
    ordres = []
    with patch("diapason.tools.desktop_tools._run") as run:
        run.side_effect = lambda cmd, **_k: (
            ordres.append(cmd),
            MagicMock(returncode=0 if run_ok else 1, stderr=""),
        )[1]
        with patch(
            "diapason.tools.desktop_tools.resolve_mac_app_name",
            lambda n: "App Store",
        ):
            resultat = open_application("app store", attente_s=0)
    return resultat, ordres


def test_deja_devant_se_constate_sans_geste(monkeypatch):
    resultat, ordres = _ouvrir(
        monkeypatch,
        etat=_etat("App Store", ["Safari", "App Store"]),
        devant_apres="App Store",
    )
    assert resultat.success
    assert resultat.content == "App Store est déjà devant toi."
    assert resultat.metadata["etat"] == "deja_devant"
    assert ordres == []  # aucun open, aucun osascript : rien à faire


def test_en_marche_se_remet_devant_et_se_verifie(monkeypatch):
    resultat, ordres = _ouvrir(
        monkeypatch,
        etat=_etat("Safari", ["Safari", "App Store"]),
        devant_apres="App Store",
    )
    assert resultat.content == "App Store est devant toi."
    assert resultat.metadata["etat"] == "remise_devant"
    assert resultat.metadata["verifie"] is True
    assert ordres and ordres[0][:2] == ["open", "-a"]


def test_l_echec_de_mise_devant_s_avoue(monkeypatch):
    resultat, _ = _ouvrir(
        monkeypatch,
        etat=_etat("Safari", ["Safari", "App Store"]),
        devant_apres="Safari",  # macOS a refusé : Safari est resté devant
    )
    assert resultat.success
    assert "une autre fenêtre est restée devant" in resultat.content
    assert resultat.metadata["verifie"] is False


def test_une_app_eteinte_se_lance(monkeypatch):
    resultat, _ = _ouvrir(
        monkeypatch,
        etat=_etat("Safari", ["Safari"]),
        devant_apres="App Store",
    )
    assert resultat.content == "App Store est lancé et devant toi."
    assert resultat.metadata["etat"] == "lancee"
