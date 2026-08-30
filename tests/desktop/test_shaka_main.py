"""Le geste 🤙 — pouce et auriculaire tendus, capture sans bande basse."""

from diapason.desktop.gestes_main import Point
from diapason.desktop.shaka_main import shaka_geste


def _shaka(*, ecart_pince: float = 0.50) -> list[Point]:
    """Géométrie synthétique : trois doigts repliés, pouce + auriculaire tendus."""
    return [
        Point("indexMCP", 0.42, 0.7),
        Point("indexTip", 0.42, 0.62),
        Point("middleMCP", 0.49, 0.7),
        Point("middleTip", 0.49, 0.62),
        Point("ringMCP", 0.56, 0.7),
        Point("ringTip", 0.56, 0.62),
        Point("littleMCP", 0.62, 0.7),
        Point("littleTip", 0.62, 0.25),
        Point("thumbCMC", 0.35, 0.75),
        Point("thumbTip", 0.42 - ecart_pince, 0.25),
    ]


class TestShakaGeste:
    def test_la_pose_shaka_est_reconnue(self):
        assert shaka_geste(_shaka()) is True

    def test_un_poing_n_est_pas_un_shaka(self):
        main = _shaka()
        main = [p for p in main if p.nom != "littleTip"]
        main.append(Point("littleTip", 0.62, 0.62))
        assert shaka_geste(main) is False

    def test_une_pince_n_est_pas_un_shaka(self):
        main = _shaka()
        main = [p for p in main if p.nom != "thumbTip"]
        main.append(Point("thumbTip", 0.42, 0.62))
        assert shaka_geste(main) is False

    def test_un_index_tendu_n_est_pas_un_shaka(self):
        main = _shaka()
        main = [p for p in main if p.nom != "indexTip"]
        main.append(Point("indexTip", 0.42, 0.25))
        assert shaka_geste(main) is False
