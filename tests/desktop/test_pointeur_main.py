"""Le pointeur de la main : bouger n'autorise jamais un clic fantôme."""

from diapason.desktop.gestes_main import Point
from diapason.desktop.pointeur_main import ActionPointeur, MoteurDePointeur


def _index(*, x: float = 0.42, y: float = 0.25, pince: bool = False) -> list[Point]:
    points = [
        Point("wrist", 0.5, 0.9),
        Point("indexMCP", 0.42, 0.7),
        Point("indexTip", x, y),
        Point("middleMCP", 0.49, 0.7),
        Point("middleTip", 0.49, 0.58),
        Point("ringMCP", 0.56, 0.7),
        Point("ringTip", 0.56, 0.58),
        Point("littleMCP", 0.62, 0.7),
        Point("littleTip", 0.62, 0.58),
        Point("thumbTip", x + (0.02 if pince else -0.18), y),
    ]
    return points


def _stabiliser(moteur: MoteurDePointeur, *, t0: float = 0.0):
    lecture = None
    for image in range(3):
        lecture = moteur.observer(_index(), maintenant=t0 + image * 0.05)
    return lecture


class TestPointerEstUnePoseDistincte:
    def test_trois_images_sont_requises_avant_de_bouger(self):
        """§11 — une silhouette d'index sur une image ne déplace rien."""
        moteur = MoteurDePointeur()
        assert moteur.observer(_index(), maintenant=0.0).actif is False
        assert moteur.observer(_index(), maintenant=0.05).actif is False
        lecture = moteur.observer(_index(), maintenant=0.10)
        assert lecture.actif is True
        assert lecture.action is ActionPointeur.DEPLACER

    def test_une_paume_ouverte_n_est_pas_un_pointeur(self):
        """Les autres doigts tendus appartiennent au transfert, pas au curseur."""
        main = _index()
        for doigt, x in (("middle", 0.49), ("ring", 0.56), ("little", 0.62)):
            main = [p for p in main if p.nom != f"{doigt}Tip"]
            main.append(Point(f"{doigt}Tip", x, 0.25))
        moteur = MoteurDePointeur()
        for image in range(5):
            lecture = moteur.observer(main, maintenant=image * 0.05)
        assert lecture.actif is False

    def test_la_main_perdue_fige_sans_cliquer(self):
        """Une disparition pendant un pincement est une annulation, jamais un clic."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.25)
        lecture = moteur.observer(None, maintenant=0.30)
        assert lecture.actif is False
        assert lecture.action is ActionPointeur.AUCUNE


class TestLePincement:
    def test_une_seule_image_pincee_ne_clique_pas(self):
        """§11 — même un contact pouce-index doit être confirmé."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        lecture = moteur.observer(_index(), maintenant=0.25)
        assert lecture.action is ActionPointeur.DEPLACER

    def test_un_pincement_bref_clique_a_la_liberation(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.25)
        lecture = moteur.observer(_index(), maintenant=0.30)
        assert lecture.action is ActionPointeur.CLIQUER

    def test_deux_pincements_rapides_ouvrent_par_double_clic(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        for instant in (0.20, 0.25):
            moteur.observer(_index(pince=True), maintenant=instant)
        premier = moteur.observer(_index(), maintenant=0.30)
        assert premier.action is ActionPointeur.CLIQUER
        for instant in (0.45, 0.50):
            moteur.observer(_index(pince=True), maintenant=instant)
        lecture = moteur.observer(_index(), maintenant=0.55)
        assert lecture.action is ActionPointeur.DOUBLE_CLIQUER


class TestLeDefilement:
    def test_maintenir_puis_descendre_defile_vers_le_bas(self):
        """Le maintien distingue le défilement d'un clic ordinaire."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.30)
        lecture = moteur.observer(_index(y=0.40, pince=True), maintenant=0.65)
        assert lecture.action is ActionPointeur.DEFILER
        assert lecture.defilement_y < 0, "descendre l'index doit descendre la page"

    def test_relacher_apres_defilement_ne_clique_pas(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.30)
        moteur.observer(_index(y=0.40, pince=True), maintenant=0.65)
        lecture = moteur.observer(_index(y=0.40), maintenant=0.70)
        assert lecture.action is ActionPointeur.DEPLACER


class TestLesCoordonnees:
    def test_la_camera_est_rendue_comme_un_miroir(self):
        moteur = MoteurDePointeur()
        gauche = None
        for image in range(3):
            gauche = moteur.observer(_index(x=0.80), maintenant=image * 0.05)
        moteur.reinitialiser()
        droite = None
        for image in range(3):
            droite = moteur.observer(_index(x=0.20), maintenant=1.0 + image * 0.05)
        assert gauche.x < droite.x, (
            "la droite de la main doit rester la droite à l'écran"
        )
