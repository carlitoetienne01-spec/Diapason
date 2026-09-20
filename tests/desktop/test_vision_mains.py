"""Le pont Vision : des pixels aux points, et rien d'autre.

Spatial Mesh, gestes — 25 août 2026. Ce module ne décide de rien ; les
tests vérifient donc surtout qu'il TRADUIT fidèlement et qu'il ne ment
jamais sur ce qu'il n'a pas vu.
"""

from __future__ import annotations

import struct
import sys
import zlib

import pytest


def _vision_indisponible() -> bool:
    """macOS ne suffit pas : encore faut-il que `pyobjc-Vision` soit installé.

    Constaté le 26 août 2026, première exécution de CI depuis deux jours :
    quatre tests d'ici ont échoué sur un runner macOS. La garde ne regardait
    que la plateforme, or `pyobjc-framework-Vision` vit dans l'extra
    `desktop`, que la CI n'installe pas. Un macOS sans Vision passait donc
    la garde et cassait au premier appel.
    """
    if sys.platform != "darwin":
        return True
    from diapason.desktop.vision_mains import disponible

    return not disponible()


pytestmark = pytest.mark.skipif(
    _vision_indisponible(),
    reason="Vision indisponible : API macOS, extra `desktop` requis",
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
            *(
                f"{d}{a}"
                for d in ("index", "middle", "ring", "little")
                for a in ("MCP", "PIP", "DIP", "Tip")
            ),
            "thumbCMC",
            "thumbMP",
            "thumbIP",
            "thumbTip",
        }
        assert set(vm._NOMS.values()) == attendus
        assert len(vm._NOMS) == 21


class TestSurUneVraieImage:
    """Le pipeline tourne pour de vrai — pas de simulacre."""

    @pytest.fixture()
    def image(self, tmp_path):
        # 19/09/2026 : une capture du bureau n'est pas une image « sans
        # main » connue. Son contenu change et rendait le test aléatoire.
        # PNG RGB fixe de 640×400 : fond sombre et lignes de code stylisées,
        # générés sans capteur ni bibliothèque graphique supplémentaire.
        largeur, hauteur = 640, 400
        pixels = bytearray([24, 28, 32]) * (largeur * hauteur)
        for ligne in range(20):
            x = 28 + (ligne % 3) * 16
            y = 24 + ligne * 17
            longueur = 100 + (ligne * 73) % 360
            couleur = bytes((92 + ligne % 4 * 24, 140, 162))
            for dy in range(3):
                debut = ((y + dy) * largeur + x) * 3
                pixels[debut : debut + longueur * 3] = couleur * longueur

        def bloc(nom, contenu):
            return (
                struct.pack(">I", len(contenu))
                + nom
                + contenu
                + struct.pack(">I", zlib.crc32(nom + contenu))
            )

        lignes = b"".join(
            b"\x00" + pixels[y * largeur * 3 : (y + 1) * largeur * 3]
            for y in range(hauteur)
        )
        chemin = tmp_path / "code-sans-main.png"
        chemin.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(lignes))
            + bloc(b"IEND", b"")
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
        source = __import__("pathlib").Path(vm.__file__).read_text(encoding="utf-8")
        for interdit in ("Seuils", "Etat.", "images_stables", "hysteresis"):
            assert interdit not in source, (
                f"« {interdit} » est apparu dans le pont : la logique de "
                "geste doit rester dans gestes_main"
            )


class TestLeContratAvecVision:
    """Le trou qui a laissé passer un bug jusqu'à la caméra de Carlito.

    Les tests ne regardaient que des images SANS main : la fonction qui lit
    les points n'était donc jamais atteinte, et deux noms inventés y
    dormaient — « recognizedPointsForGroupName_error_ » (qui n'existe pas)
    et le groupe « VNHLKAll » (qui s'appelle « VNIPOAll »). Ces tests
    vérifient le contrat AVEC le framework, sans avoir besoin d'une main.
    """

    def test_la_methode_de_lecture_existe_vraiment(self):
        import Vision

        assert hasattr(
            Vision.VNHumanHandPoseObservation,
            "recognizedPointsForJointsGroupName_error_",
        ), "le nom de la méthode a changé : le pont ne lira plus aucun point"

    def test_la_constante_du_groupe_existe_vraiment(self):
        import Vision

        groupe = Vision.VNHumanHandPoseObservationJointsGroupNameAll
        assert isinstance(groupe, str) and groupe

    def test_les_vingt_et_une_cles_sont_celles_de_vision(self):
        """Une clé inventée rendrait Diapason aveugle à un doigt entier, en
        silence — le point serait simplement absent du dictionnaire."""
        import Vision

        reelles = {
            getattr(Vision, nom)
            for nom in dir(Vision)
            if nom.startswith("VNHumanHandPoseObservationJointName")
            and isinstance(getattr(Vision, nom, None), str)
        }
        assert set(vm._NOMS) == reelles

    def test_le_pont_lit_les_constantes_au_lieu_de_les_recopier(self):
        """Recopier une constante, c'est parier qu'elle ne changera pas."""
        import pathlib

        source = pathlib.Path(vm.__file__).read_text(encoding="utf-8")
        assert "VNHumanHandPoseObservationJointsGroupNameAll" in source
        assert '"VNHLKAll"' not in source
