"""Contrat d'identité de la bannière affichée au démarrage."""

from diapason.cli._banner import _WORDMARK


class TestBanniereDiapason:
    """Le terminal doit annoncer le produit actuel, jamais son ancêtre."""

    def test_le_mot_symbole_est_diapason(self):
        """Le renommage doit atteindre le premier pixel textuel du §5."""
        assert _WORDMARK == (
            " ____  ___    _    ____   _    ____   ___  _   _ ",
            "|  _ \\|_ _|  / \\  |  _ \\ / \\  / ___| / _ \\| \\ | |",
            "| | | || |  / _ \\ | |_) / _ \\ \\___ \\| | | |  \\| |",
            "| |_| || | / ___ \\|  __/ ___ \\ ___) | |_| | |\\  |",
            "|____/|___/_/   \\_\\_| /_/   \\_\\____/ \\___/|_| \\_|",
        ), "la bannière de démarrage doit dessiner DIAPASON"
