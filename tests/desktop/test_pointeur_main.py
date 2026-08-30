"""Le pointeur de la main : bouger n'autorise jamais un clic fantôme."""

from diapason.desktop.gestes_main import Point
from diapason.desktop.pointeur_main import (
    ActionPointeur,
    MoteurDePointeur,
    SeuilsPointeur,
)


def _index(
    *,
    x: float = 0.42,
    y: float = 0.25,
    pince: bool = False,
    ecart_pince: float = 0.02,
) -> list[Point]:
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
        Point("thumbTip", x + (ecart_pince if pince else -0.18), y),
    ]
    return points


def _stabiliser(moteur: MoteurDePointeur, *, t0: float = 0.0):
    lecture = None
    for image in range(3):
        lecture = moteur.observer(_index(), maintenant=t0 + image * 0.05)
    return lecture


def _confiance(points: list[Point], noms: set[str], valeur: float) -> list[Point]:
    return [
        Point(p.nom, p.x, p.y, confiance=valeur if p.nom in noms else p.confiance)
        for p in points
    ]


def _relacher(
    moteur: MoteurDePointeur,
    *,
    maintenant: float,
    main: list[Point] | None = None,
):
    moteur.observer(main or _index(), maintenant=maintenant)
    return moteur.observer(main or _index(), maintenant=maintenant + 0.05)


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

    def test_un_doigt_replie_incertain_ne_fait_pas_perdre_l_index(self):
        """Vision voit mal une phalange cachée ; deux confirmations suffisent."""
        moteur = MoteurDePointeur()
        main = _confiance(_index(), {"middleTip"}, 0.10)
        for image in range(3):
            lecture = moteur.observer(main, maintenant=image * 0.05)
        assert lecture.actif is True
        assert lecture.action is ActionPointeur.DEPLACER

    def test_une_main_un_peu_tournee_reste_un_pointeur(self):
        """La perspective rétrécit la paume sans déplier les autres doigts."""
        main = _index()
        for doigt, x in (("middle", 0.49), ("ring", 0.56), ("little", 0.62)):
            main = [p for p in main if p.nom != f"{doigt}Tip"]
            main.append(Point(f"{doigt}Tip", x, 0.38))
        moteur = MoteurDePointeur()
        for image in range(3):
            lecture = moteur.observer(main, maintenant=image * 0.05)
        assert lecture.actif is True

    def test_une_image_incertaine_ne_recommence_pas_trois_images(self):
        """Un hoquet de Vision fige une image, puis le suivi reprend aussitôt."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        floue = _confiance(_index(), {"indexTip"}, 0.10)
        assert moteur.observer(floue, maintenant=0.15).actif is False
        reprise = moteur.observer(_index(x=0.50), maintenant=0.20)
        assert reprise.actif is True
        assert reprise.action is ActionPointeur.DEPLACER

    def test_une_perte_longue_exige_une_nouvelle_acquisition(self):
        """Après 280 ms sans main, une position ancienne n'est plus crédible."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(None, maintenant=0.15)
        moteur.observer(None, maintenant=0.44)
        reprise = moteur.observer(_index(), maintenant=0.45)
        assert reprise.actif is False

    def test_une_paume_ouverte_apres_l_index_reste_pour_le_retournement(self):
        """Une paume acquise ne coupe plus le pointeur : elle lit le flip apps."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        main = _index()
        for doigt, x in (("middle", 0.49), ("ring", 0.56), ("little", 0.62)):
            main = [p for p in main if p.nom != f"{doigt}Tip"]
            main.append(Point(f"{doigt}Tip", x, 0.25))
        lecture = moteur.observer(main, maintenant=0.15)
        assert lecture.actif is True
        assert lecture.action is ActionPointeur.DEPLACER


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
        lecture = _relacher(moteur, maintenant=0.30)
        assert lecture.action is ActionPointeur.CLIQUER

    def test_deux_pincements_rapides_ouvrent_par_double_clic(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        for instant in (0.20, 0.25):
            moteur.observer(_index(pince=True), maintenant=instant)
        premier = _relacher(moteur, maintenant=0.30)
        assert premier.action is ActionPointeur.CLIQUER
        for instant in (0.50, 0.55):
            moteur.observer(_index(pince=True), maintenant=instant)
        lecture = _relacher(moteur, maintenant=0.60)
        assert lecture.action is ActionPointeur.DOUBLE_CLIQUER

    def test_un_index_un_peu_plie_pendant_la_pince_reste_suivi(self):
        """Pincer plie naturellement l'index sans signifier que la main est perdue."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(y=0.46, pince=True), maintenant=0.20)
        lecture = moteur.observer(_index(y=0.46, pince=True), maintenant=0.25)
        assert lecture.actif is True
        assert lecture.pince is True
        relache = _relacher(moteur, maintenant=0.30)
        assert relache.action is ActionPointeur.CLIQUER

    def test_une_perte_pendant_la_pince_annule_le_clic(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.25)
        moteur.observer(None, maintenant=0.30)
        relache = moteur.observer(_index(), maintenant=0.35)
        assert relache.action is ActionPointeur.DEPLACER

    def test_le_contact_reel_n_exige_plus_des_bouts_superposes(self):
        """Le seuil mesuré au banc reconnaît 0,55 largeur de paume."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        for instant in (0.20, 0.25):
            lecture = moteur.observer(
                _index(pince=True, ecart_pince=0.11),
                maintenant=instant,
            )
        assert lecture.pince is True
        assert _relacher(moteur, maintenant=0.30).action is ActionPointeur.CLIQUER

    def test_le_pouce_masque_cent_quarante_ms_ne_casse_pas_le_contact(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.25)
        masque = _confiance(_index(pince=True), {"thumbTip"}, 0.05)
        lecture = moteur.observer(masque, maintenant=0.32)
        assert lecture.pince is True
        moteur.observer(_index(pince=True), maintenant=0.36)
        assert _relacher(moteur, maintenant=0.40).action is ActionPointeur.CLIQUER

    def test_un_pincement_stationnaire_long_clique_quand_meme(self):
        """Viser un bouton prend plus de 480 ms ; ce n'est pas un abandon."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.25)
        moteur.observer(_index(pince=True), maintenant=0.90)
        lecture = _relacher(moteur, maintenant=0.95)
        assert lecture.action is ActionPointeur.CLIQUER, (
            "un pincement tenu sans bouger doit encore cliquer au relâchement"
        )

    def test_approcher_la_pince_ne_perd_pas_l_index(self):
        """L'index se plie avant le contact ; perdre le suivi ici tue le clic."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        lecture = moteur.observer(
            _index(y=0.50, pince=True, ecart_pince=0.18),
            maintenant=0.20,
        )
        assert lecture.actif is True, "approcher le pouce ne doit pas figer le curseur"

    def test_le_clic_vise_avant_que_le_pouce_deforme_l_index(self):
        """Le contact décale l'index mesuré — le clic reste sur la visée ouverte."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(x=0.50, y=0.40), maintenant=0.15)
        moteur.observer(_index(x=0.50, y=0.40), maintenant=0.18)
        for instant in (0.20, 0.25):
            moteur.observer(_index(x=0.62, y=0.55, pince=True), maintenant=instant)
        lecture = _relacher(moteur, maintenant=0.30, main=_index(x=0.62, y=0.55))
        assert lecture.action is ActionPointeur.CLIQUER
        assert abs(lecture.x - 0.50) < 0.04, (
            "le clic doit viser là où l'index était ouvert"
        )
        assert abs(lecture.y - 0.40) < 0.04, (
            "le clic doit viser là où l'index était ouvert"
        )

    def test_le_clic_reste_la_ou_on_a_pince(self):
        """Relâcher décale l'index ; le clic ne doit pas suivre ce saut."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        pince = None
        for instant in (0.20, 0.25):
            pince = moteur.observer(
                _index(x=0.42, y=0.30, pince=True),
                maintenant=instant,
            )
        lecture = _relacher(
            moteur,
            maintenant=0.30,
            main=_index(x=0.58, y=0.50),
        )
        assert lecture.action is ActionPointeur.CLIQUER
        assert abs(lecture.x - pince.x) < 0.02, "le clic doit rester sur la cible"
        assert abs(lecture.y - pince.y) < 0.02, "le clic doit rester sur la cible"

    def test_la_proximite_guide_avant_le_contact(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        loin = moteur.observer(_index(), maintenant=0.20)
        proche = moteur.observer(
            _index(pince=True, ecart_pince=0.14),
            maintenant=0.25,
        )
        assert proche.proximite_pince > loin.proximite_pince


class TestLeDefilement:
    def test_maintenir_puis_descendre_defile_vers_le_bas(self):
        """Le maintien distingue le défilement d'un clic ordinaire."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.30)
        # 500 ms de maintien + ~20 % d'écran, vertical dominant.
        lecture = moteur.observer(_index(y=0.45, pince=True), maintenant=0.75)
        assert lecture.action is ActionPointeur.DEFILER
        assert lecture.defilement_y < 0, "descendre l'index doit descendre la page"

    def test_relacher_apres_defilement_ne_clique_pas(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(pince=True), maintenant=0.20)
        moteur.observer(_index(pince=True), maintenant=0.30)
        moteur.observer(_index(y=0.45, pince=True), maintenant=0.75)
        lecture = _relacher(moteur, maintenant=0.80, main=_index(y=0.45))
        assert lecture.action is not ActionPointeur.CLIQUER
        assert lecture.action is not ActionPointeur.DOUBLE_CLIQUER

    def test_un_petit_tremblement_pendant_la_pince_clique_encore(self):
        """Viser un onglet bouge un peu la main — ce n'est pas un scroll."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(y=0.28, pince=True), maintenant=0.20)
        moteur.observer(_index(y=0.28, pince=True), maintenant=0.25)
        moteur.observer(_index(y=0.30, pince=True), maintenant=0.80)
        lecture = _relacher(moteur, maintenant=0.85, main=_index(y=0.30))
        assert lecture.action is ActionPointeur.CLIQUER, (
            "un micro-mouvement ne doit pas armer le défilement"
        )

    def test_une_derive_horizontale_courte_reste_un_clic(self):
        """Un petit glissement avant 500 ms ne change pas d'app."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(x=0.42, pince=True), maintenant=0.20)
        moteur.observer(_index(x=0.42, pince=True), maintenant=0.25)
        moteur.observer(_index(x=0.48, y=0.28, pince=True), maintenant=0.40)
        lecture = _relacher(moteur, maintenant=0.45, main=_index(x=0.48, y=0.28))
        assert lecture.action is ActionPointeur.CLIQUER

    def test_pendant_la_pince_le_curseur_reste_a_l_ancre(self):
        """Le MOVE pendant la pince faisait rater les onglets (29 août 2026)."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(x=0.42, y=0.30, pince=True), maintenant=0.20)
        verrou = moteur.observer(_index(x=0.42, y=0.30, pince=True), maintenant=0.25)
        derive = moteur.observer(_index(x=0.55, y=0.45, pince=True), maintenant=0.40)
        assert derive.action is ActionPointeur.AUCUNE
        assert abs(derive.x - verrou.x) < 0.02
        assert abs(derive.y - verrou.y) < 0.02


def _shaka(*, ecart_pince: float = 0.50) -> list[Point]:
    """Geste 🤙 : index/majeur/annulaire repliés, pouce + auriculaire tendus."""
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


def _index_bas(
    *,
    x: float = 0.50,
    y: float = 0.80,
    pince: bool = False,
    ecart_pince: float = 0.02,
) -> list[Point]:
    """Main basse dans le cadre : index tendu vers le bas de l'écran."""
    return [
        Point("wrist", 0.5, 0.92),
        Point("indexMCP", 0.42, 0.50),
        Point("indexTip", x, y),
        Point("middleMCP", 0.49, 0.50),
        Point("middleTip", 0.49, 0.62),
        Point("ringMCP", 0.56, 0.50),
        Point("ringTip", 0.56, 0.62),
        Point("littleMCP", 0.62, 0.50),
        Point("littleTip", 0.62, 0.62),
        Point("thumbTip", x + (ecart_pince if pince else -0.18), y),
    ]


def _paume_ouverte() -> list[Point]:
    """Main droite, paume vers la caméra, doigts tendus."""
    return [
        Point("wrist", 0.5, 0.88),
        Point("indexMCP", 0.40, 0.60),
        Point("indexTip", 0.36, 0.18),
        Point("middleMCP", 0.48, 0.60),
        Point("middleTip", 0.48, 0.15),
        Point("ringMCP", 0.56, 0.60),
        Point("ringTip", 0.58, 0.18),
        Point("littleMCP", 0.64, 0.60),
        Point("littleTip", 0.68, 0.22),
        Point("thumbTip", 0.26, 0.48),
    ]


def _dos_de_main() -> list[Point]:
    """Même main droite, dos vers la caméra (bases index/auriculaire inversées)."""
    return [
        Point("wrist", 0.5, 0.88),
        Point("indexMCP", 0.64, 0.60),
        Point("indexTip", 0.68, 0.18),
        Point("middleMCP", 0.56, 0.60),
        Point("middleTip", 0.56, 0.15),
        Point("ringMCP", 0.48, 0.60),
        Point("ringTip", 0.46, 0.18),
        Point("littleMCP", 0.40, 0.60),
        Point("littleTip", 0.36, 0.22),
        Point("thumbTip", 0.74, 0.48),
    ]


class TestLesActionsBureau:
    """Gestes bureau : flip paume/dos pour les apps ; bord pour Spaces."""

    def test_pince_puis_glisser_horizontal_au_centre_ne_change_plus_d_app(self):
        """Les apps passent par le retournement ; la glissade centre était
        un pis-aller."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        moteur.observer(_index(x=0.50, y=0.40, pince=True), maintenant=0.20)
        moteur.observer(_index(x=0.50, y=0.40, pince=True), maintenant=0.30)
        lecture = moteur.observer(_index(x=0.25, y=0.40, pince=True), maintenant=0.75)
        assert lecture.action is not ActionPointeur.APP_SUIVANTE
        assert lecture.action is not ActionPointeur.APP_PRECEDENTE

    def test_pince_depuis_le_bord_gauche_change_de_space(self):
        moteur = MoteurDePointeur()
        for t in (0.0, 0.05, 0.10, 0.15, 0.20):
            moteur.observer(_index(x=0.95, y=0.40), maintenant=t)
        moteur.observer(_index(x=0.95, y=0.40, pince=True), maintenant=0.25)
        moteur.observer(_index(x=0.95, y=0.40, pince=True), maintenant=0.30)
        lecture = moteur.observer(_index(x=0.55, y=0.40, pince=True), maintenant=0.85)
        assert lecture.action is ActionPointeur.SPACE_SUIVANT

    def test_paume_puis_dos_change_d_app(self):
        """§82 — paume ouverte face caméra, puis retournement → app suivante."""
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        t = 0.20
        for _ in range(3):
            moteur.observer(_paume_ouverte(), maintenant=t, lateralite="right")
            t += 0.05
        actions = []
        for _ in range(4):
            lecture = moteur.observer(_dos_de_main(), maintenant=t, lateralite="right")
            actions.append(lecture.action)
            t += 0.05
        assert ActionPointeur.APP_SUIVANTE in actions

    def test_dos_puis_paume_revient_a_l_app_precedente(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        t = 0.20
        for _ in range(3):
            moteur.observer(_dos_de_main(), maintenant=t, lateralite="right")
            t += 0.05
        actions = []
        for _ in range(4):
            lecture = moteur.observer(
                _paume_ouverte(), maintenant=t, lateralite="right"
            )
            actions.append(lecture.action)
            t += 0.05
        assert ActionPointeur.APP_PRECEDENTE in actions

    def test_maintien_bas_gauche_minimise(self):
        moteur = MoteurDePointeur()
        for t in (0.0, 0.05, 0.10, 0.15, 0.20):
            moteur.observer(_index_bas(x=0.92), maintenant=t)
        moteur.observer(_index_bas(x=0.92, pince=True), maintenant=0.25)
        moteur.observer(_index_bas(x=0.92, pince=True), maintenant=0.30)
        lecture = moteur.observer(_index_bas(x=0.92, pince=True), maintenant=1.15)
        assert lecture.action is ActionPointeur.MINIMISER_DEVANT

    def test_maintien_bas_droit_ferme(self):
        moteur = MoteurDePointeur()
        for t in (0.0, 0.05, 0.10, 0.15, 0.20):
            moteur.observer(_index_bas(x=0.08), maintenant=t)
        moteur.observer(_index_bas(x=0.08, pince=True), maintenant=0.25)
        moteur.observer(_index_bas(x=0.08, pince=True), maintenant=0.30)
        lecture = moteur.observer(_index_bas(x=0.08, pince=True), maintenant=1.15)
        assert lecture.action is ActionPointeur.FERMER_DEVANT

    def test_maintien_bas_centre_ne_capture_plus(self):
        """Le centre bas n'est plus une capture — c'est le geste 🤙."""
        moteur = MoteurDePointeur()
        for t in (0.0, 0.05, 0.10, 0.15, 0.20):
            moteur.observer(_index_bas(x=0.50), maintenant=t)
        moteur.observer(_index_bas(x=0.50, pince=True), maintenant=0.25)
        moteur.observer(_index_bas(x=0.50, pince=True), maintenant=0.30)
        lecture = moteur.observer(_index_bas(x=0.50, pince=True), maintenant=1.15)
        assert lecture.action is not ActionPointeur.CAPTURE_ECRAN

    def test_shaka_capture_l_ecran(self):
        moteur = MoteurDePointeur(
            SeuilsPointeur(maintien_shaka_s=0.10, repos_bureau_s=0.0)
        )
        _stabiliser(moteur)
        t = 0.20
        actions = []
        for _ in range(4):
            actions.append(moteur.observer(_shaka(), maintenant=t).action)
            t += 0.05
        assert ActionPointeur.CAPTURE_ECRAN in actions

    def test_shaka_seul_sans_index_prealable(self):
        """Le 🤙 peut acquérir le pointeur et capturer sans index tendu avant."""
        moteur = MoteurDePointeur(
            SeuilsPointeur(maintien_shaka_s=0.10, repos_bureau_s=0.0)
        )
        t = 0.0
        actions = []
        for _ in range(8):
            lecture = moteur.observer(_shaka(), maintenant=t)
            actions.append(lecture.action)
            t += 0.05
        assert ActionPointeur.CAPTURE_ECRAN in actions

    def test_maintien_en_haut_ne_ferme_pas(self):
        """Les onglets du haut restent des clics, jamais fermer/minimiser."""
        moteur = MoteurDePointeur()
        for t in (0.0, 0.05, 0.10, 0.15, 0.20):
            moteur.observer(_index(x=0.08, y=0.12), maintenant=t)
        moteur.observer(_index(x=0.08, y=0.12, pince=True), maintenant=0.25)
        moteur.observer(_index(x=0.08, y=0.12, pince=True), maintenant=0.30)
        moteur.observer(_index(x=0.08, y=0.12, pince=True), maintenant=1.15)
        lecture = _relacher(moteur, maintenant=1.20, main=_index(x=0.08, y=0.12))
        assert lecture.action is ActionPointeur.CLIQUER


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

    def test_le_tremblement_est_reduit_sans_figer_le_curseur(self):
        moteur = MoteurDePointeur()
        _stabiliser(moteur)
        sorties = []
        for image, x in enumerate((0.414, 0.426) * 5, start=3):
            lecture = moteur.observer(_index(x=x), maintenant=image * 0.05)
            sorties.append(lecture.x)
        assert max(sorties) - min(sorties) < 0.012

    def test_un_grand_mouvement_ouvre_le_filtre_adaptatif(self):
        moteur = MoteurDePointeur()
        avant = _stabiliser(moteur)
        apres = moteur.observer(_index(x=0.20), maintenant=0.15)
        assert apres.x - avant.x > 0.12, "le lissage ne doit pas poursuivre la main"
