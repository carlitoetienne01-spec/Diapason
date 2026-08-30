"""L'arbitre choisit un vocabulaire ; il n'exécute aucune action."""

from diapason.desktop.arbitre_geste import ArbitreDeGeste, Vocabulaire
from diapason.desktop.gestes_main import Point


def _index() -> list[Point]:
    return [
        Point("wrist", 0.5, 0.9),
        Point("indexMCP", 0.42, 0.7),
        Point("indexTip", 0.42, 0.25),
        Point("middleMCP", 0.49, 0.7),
        Point("middleTip", 0.49, 0.58),
        Point("ringMCP", 0.56, 0.7),
        Point("ringTip", 0.56, 0.58),
        Point("littleMCP", 0.62, 0.7),
        Point("littleTip", 0.62, 0.58),
        Point("thumbTip", 0.24, 0.25),
    ]


def _poing() -> list[Point]:
    return [
        Point("wrist", 0.5, 0.9),
        Point("indexMCP", 0.42, 0.7),
        Point("indexTip", 0.42, 0.62),
        Point("middleMCP", 0.49, 0.7),
        Point("middleTip", 0.49, 0.62),
        Point("ringMCP", 0.56, 0.7),
        Point("ringTip", 0.56, 0.62),
        Point("littleMCP", 0.62, 0.7),
        Point("littleTip", 0.62, 0.62),
        Point("thumbTip", 0.40, 0.64),
    ]


def _paume() -> list[Point]:
    return [
        Point("wrist", 0.5, 0.9),
        Point("indexMCP", 0.42, 0.7),
        Point("indexTip", 0.42, 0.25),
        Point("middleMCP", 0.49, 0.7),
        Point("middleTip", 0.49, 0.25),
        Point("ringMCP", 0.56, 0.7),
        Point("ringTip", 0.56, 0.25),
        Point("littleMCP", 0.62, 0.7),
        Point("littleTip", 0.62, 0.25),
        Point("thumbTip", 0.28, 0.40),
    ]


def _shaka() -> list[Point]:
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
        Point("thumbTip", 0.08, 0.25),
    ]


class TestLArbitreConfirmeAvantDeChanger:
    def test_une_seule_image_d_index_reste_sur_le_transfert(self):
        """§11 — une silhouette d'index ne vole pas le poing."""
        arbitre = ArbitreDeGeste()
        assert arbitre.observer(_index()) is Vocabulaire.TRANSFERT

    def test_trois_images_d_index_donnent_le_pointeur(self):
        arbitre = ArbitreDeGeste()
        for _ in range(2):
            assert arbitre.observer(_index()) is Vocabulaire.TRANSFERT
        assert arbitre.observer(_index()) is Vocabulaire.POINTEUR

    def test_un_poing_reste_sur_le_transfert(self):
        arbitre = ArbitreDeGeste()
        for _ in range(4):
            assert arbitre.observer(_poing()) is Vocabulaire.TRANSFERT

    def test_une_paume_ouverte_est_un_transfert(self):
        arbitre = ArbitreDeGeste()
        for _ in range(4):
            lecture = arbitre.observer(_paume())
        assert lecture is Vocabulaire.TRANSFERT

    def test_une_paume_ouverte_en_pointeur_reste_pointeur(self):
        """Sinon le retournement apps bascule en transfert et n'existe jamais."""
        arbitre = ArbitreDeGeste()
        for _ in range(3):
            arbitre.observer(_index())
        assert arbitre.observer(_index()) is Vocabulaire.POINTEUR
        for _ in range(4):
            assert arbitre.observer(_paume()) is Vocabulaire.POINTEUR, (
                "la paume ouverte sert au flip, pas au dépôt"
            )

    def test_un_objet_tenu_interdit_le_pointeur(self):
        """Un index levé pendant qu'on tient un fichier n'est pas un clic."""
        arbitre = ArbitreDeGeste()
        for _ in range(3):
            arbitre.observer(_index())
        assert arbitre.observer(_index()) is Vocabulaire.POINTEUR
        assert arbitre.observer(_index(), tenu=True) is Vocabulaire.TRANSFERT, (
            "la main pleine reste au transfert"
        )

    def test_un_shaka_en_pointeur_reste_pointeur(self):
        """L'index replié du 🤙 ne doit pas basculer en transfert."""
        arbitre = ArbitreDeGeste()
        for _ in range(3):
            arbitre.observer(_index())
        assert arbitre.observer(_shaka()) is Vocabulaire.POINTEUR

    def test_une_pince_confirmee_ne_bascule_pas(self):
        arbitre = ArbitreDeGeste()
        for _ in range(3):
            arbitre.observer(_index())
        assert (
            arbitre.observer(_poing(), pince_confirmee=True) is Vocabulaire.POINTEUR
        ), "relâcher le contact ne doit pas envoyer un fichier"
