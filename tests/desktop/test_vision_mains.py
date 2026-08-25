"""Le pont Vision : des pixels aux points, et rien d'autre.

Spatial Mesh, gestes — 25 août 2026. Ce module ne décide de rien ; les
tests vérifient donc surtout qu'il TRADUIT fidèlement et qu'il ne ment
jamais sur ce qu'il n'a pas vu.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Vision est une API macOS"
)

from diapason.desktop import vision_mains as vm  # noqa: E402


class TestDisponibilite:
    def test_vision_repond_sur_cette_machine(self):
        assert vm.disponible() is True

    def test_les_vingt_et_un_points_sont_traduits(self):
        """Le moteur de gestes ne connaît que ces noms : un oubli dans la
        table le rendrait aveugle à un doigt entier, en silence."""
        attendus = {
            "wrist",
            *(f"{d}{a}" for d in ("index", "middle", "ring", "little")
              for a in ("MCP", "PIP", "DIP", "Tip")),
            "thumbCMC", "thumbMP", "thumbIP", "thumbTip",
        }
        assert set(vm._NOMS.values()) == attendus
        assert len(vm._NOMS) == 21


class TestSurUneVraieImage:
    """Le pipeline tourne pour de vrai — pas de simulacre."""

    @pytest.fixture()
    def image(self, tmp_path):
        chemin = tmp_path / "ecran.jpg"
        subprocess.run(
            ["screencapture", "-x", "-t", "jpg", str(chemin)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["sips", "-Z", "640", str(chemin), "--out", str(chemin)],
            check=True,
            capture_output=True,
        )
        return chemin

    def test_une_image_sans_main_ne_produit_aucune_main(self, image):
        """Inventer une main sur un écran de code serait la pire des
        régressions : chaque geste fantôme est une action non voulue."""
        assert vm.mains_dans_le_fichier(str(image)) == []

    def test_la_detection_tient_le_temps_reel(self, image):
        """Mesuré le 25 août 2026 : 4 ms par image en taille caméra, soit
        plus de deux cents images par seconde possibles. Ce test garde
        l'ordre de grandeur — une régression qui le ferait tomber sous
        quinze images par seconde rendrait les gestes inutilisables."""
        import time

        t0 = time.monotonic()
        for _ in range(5):
            vm.mains_dans_le_fichier(str(image))
        ms = (time.monotonic() - t0) * 1000 / 5
        assert ms < 66, f"{ms:.0f} ms par image : moins de 15 images/s"


class TestContrat:
    def test_le_pont_ne_decide_de_rien(self):
        """Toute la logique de geste vit ailleurs : ce module n'a ni seuil,
        ni état, ni notion de pose. Le vérifier empêche la dérive."""
        source = (
            __import__("pathlib").Path(vm.__file__).read_text(encoding="utf-8")
        )
        for interdit in ("Seuils", "Etat.", "images_stables", "hysteresis"):
            assert interdit not in source, (
                f"« {interdit} » est apparu dans le pont : la logique de "
                "geste doit rester dans gestes_main"
            )
