"""Paume ou dos face à la caméra — sans latéralité, on refuse."""

from diapason.desktop.face_main import face_paume_vers_camera
from diapason.desktop.gestes_main import Point


def _main_droite_paume() -> list[Point]:
    # Doigts vers le haut : index à gauche du poignet, auriculaire à droite.
    return [
        Point("wrist", 0.5, 0.8),
        Point("indexMCP", 0.4, 0.5),
        Point("littleMCP", 0.6, 0.5),
    ]


def _main_droite_dos() -> list[Point]:
    return [
        Point("wrist", 0.5, 0.8),
        Point("indexMCP", 0.6, 0.5),
        Point("littleMCP", 0.4, 0.5),
    ]


class TestFacePaumeVersCamera:
    def test_main_droite_paume_est_reconnue(self):
        assert face_paume_vers_camera(_main_droite_paume(), "right") is True

    def test_main_droite_dos_est_reconnu(self):
        assert face_paume_vers_camera(_main_droite_dos(), "right") is False

    def test_main_gauche_inverse_le_signe(self):
        """Sans inversion, une main gauche paume serait lue comme un dos."""
        assert face_paume_vers_camera(_main_droite_paume(), "left") is False
        assert face_paume_vers_camera(_main_droite_dos(), "left") is True

    def test_sans_lateralite_on_refuse(self):
        """§34 — ne jamais deviner gauche ou droite."""
        assert face_paume_vers_camera(_main_droite_paume(), "unknown") is None
