"""Le nom PARLÉ doit trouver l'application SUR DISQUE.

macOS affiche des noms français dans le Finder mais range les applications
sous leur nom anglais — « Musique » est Music.app, « Réglages Système » est
System Settings.app — et ``open -a`` n'accepte que le nom sur disque.
Constaté le 23 août 2026 : « ouvre-moi Apple TV » échouait (l'application
s'appelle TV.app), et tout nom français échouait avec elle. L'assistant est
parlé en français ; sans cette résolution, la moitié du Mac lui était fermée.
"""

from __future__ import annotations

import pytest

from diapason.desktop.app_index import MacAppIndex

_INSTALLEES = (
    "TV",
    "Music",
    "System Settings",
    "Calendar",
    "Maps",
    "Preview",
    "Podcasts",
    "VoiceMemos",
    "Phone",
    "Terminal",
    "QuickTime Player",
    "Safari",
    "Photo Booth",
    "Visual Studio Code",
)


@pytest.fixture()
def index(monkeypatch):
    idx = MacAppIndex()
    monkeypatch.setattr(idx, "_scan", staticmethod(lambda: _INSTALLEES))
    return idx


@pytest.mark.parametrize(
    "parle,attendu",
    [
        ("Apple TV", "TV"),
        ("apple tv", "TV"),
        ("télé", "TV"),
        ("Musique", "Music"),
        ("Apple Music", "Music"),
        ("Réglages", "System Settings"),
        ("réglages système", "System Settings"),
        ("préférences système", "System Settings"),
        ("Calendrier", "Calendar"),
        ("Plans", "Maps"),
        ("Aperçu", "Preview"),
        ("Balados", "Podcasts"),
    ],
)
def test_le_nom_francais_trouve_l_application(index, parle, attendu):
    assert index.resolve(parle) == attendu


def test_l_alias_retrouve_un_nom_de_fichier_colle(index):
    """« Voice Memos » est VoiceMemos.app sur disque : l'alias doit recoller."""
    assert index.resolve("Dictaphone") == "VoiceMemos"


def test_un_mot_au_milieu_d_un_autre_ne_mord_pas(index):
    """« phone » vit au milieu de « dictaphone » : l'inclusion brute rendait
    Phone.app pour le Dictaphone."""
    assert index.resolve("dictaphone") != "Phone"


def test_le_nom_exact_gagne_toujours(index):
    assert index.resolve("Safari") == "Safari"
    assert index.resolve("Photo Booth") == "Photo Booth"


def test_le_nom_partiel_trouve_le_plus_court(index):
    assert index.resolve("QuickTime") == "QuickTime Player"
    assert index.resolve("visual studio") == "Visual Studio Code"


def test_un_inconnu_est_rendu_tel_quel_pour_launch_services(index):
    """Launch Services connaît des applications hors des dossiers balayés."""
    assert index.resolve("Blender") == "Blender"


def test_le_suffixe_app_est_toléré(index):
    assert index.resolve("Musique.app") == "Music"
