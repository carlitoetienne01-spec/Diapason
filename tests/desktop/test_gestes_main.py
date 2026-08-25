"""Le moteur de gestes : ce qu'il reconnaît, et surtout ce qu'il refuse.

Spatial Mesh, gestes — 25 août 2026. La règle qui structure tout (§11) :
ne jamais déclencher depuis une seule image. Une main qui passe devant
l'objectif ressemble à un poing pendant deux ou trois images — c'est ainsi
qu'un document part tout seul.

Les mains de ces tests sont synthétiques et c'est le but : la fiabilité
d'un geste se teste sans caméra, sans lumière, et sans main humaine.
"""

from __future__ import annotations

import pytest

from diapason.desktop.gestes_main import (
    Etat,
    MoteurDeGestes,
    Point,
    Pose,
    Seuils,
    mesurer,
)


def _main(*, ouverture: float = 1.0, pince: float = 1.0) -> list[Point]:
    """Une main synthétique, paramétrée par son ouverture.

    ``ouverture`` = 1.0 : doigts tendus. 0.2 : poing. La paume fait
    toujours 0,2 de large, donc tout est rapporté à une taille stable.
    """
    points = [Point(POIGNET := "wrist", 0.5, 0.9)]
    points.append(Point("indexMCP", 0.42, 0.7))
    points.append(Point("littleMCP", 0.62, 0.7))  # paume = 0.2
    # Un doigt tendu place son bout à ~2× la paume du poignet.
    portee = 0.2 * (0.6 + 3.0 * ouverture)
    for i, doigt in enumerate(("index", "middle", "ring", "little")):
        base = 0.42 + i * 0.066
        points.append(Point(f"{doigt}MCP", base, 0.7))
        points.append(Point(f"{doigt}Tip", base, 0.9 - portee))
    points.append(Point("thumbCMC", 0.38, 0.82))
    # Le pouce : sa distance à l'index fait la pince.
    points.append(Point("thumbTip", 0.42 - 0.2 * pince, 0.9 - portee))
    return points


class TestMesures:
    def test_une_main_ouverte_et_un_poing_se_distinguent(self):
        ouverte = mesurer(_main(ouverture=1.0))
        poing = mesurer(_main(ouverture=0.1))
        assert ouverte.repliement > poing.repliement
        assert ouverte.doigts_tendus > poing.doigts_tendus

    def test_les_mesures_ne_dependent_pas_de_la_distance(self):
        """Une main près de l'objectif et une main au fond de la pièce
        doivent donner les mêmes nombres : sinon aucun seuil ne tient."""
        proche = mesurer(_main(ouverture=1.0))
        # La même main, deux fois plus petite (plus loin).
        loin = mesurer([Point(p.nom, 0.5 + (p.x - 0.5) / 2, 0.9 + (p.y - 0.9) / 2)
                        for p in _main(ouverture=1.0)])
        assert abs(proche.repliement - loin.repliement) < 0.05

    def test_une_main_incomplete_ne_se_mesure_pas(self):
        """Deviner sur une main à moitié vue produirait des gestes fantômes."""
        assert mesurer([Point("wrist", 0.5, 0.9)]) is None
        assert mesurer([]) is None


class TestUneSeuleImageNeSuffitJamais:
    """§11 — LA règle. Sans elle, une main qui passe envoie un document."""

    def test_un_poing_sur_une_image_ne_declenche_rien(self):
        moteur = MoteurDeGestes()
        for _ in range(10):
            moteur.observer(_main(ouverture=1.0))
        assert moteur.etat is Etat.PAUME_STABLE
        # UNE image de poing : rien ne doit bouger.
        assert moteur.observer(_main(ouverture=0.1)) is Etat.PAUME_STABLE

    def test_il_faut_le_nombre_d_images_configure(self):
        moteur = MoteurDeGestes(Seuils(images_stables=4))
        for _ in range(10):
            moteur.observer(_main(ouverture=1.0))
        # Les trois premières images de poing ne peuvent RIEN déclencher :
        # c'est le minimum garanti par images_stables, avant même le lissage.
        for i in range(3):
            assert moteur.observer(_main(ouverture=0.1)) is Etat.PAUME_STABLE, (
                f"image {i + 1} : trop tôt pour croire"
            )

    def test_une_main_qui_traverse_le_champ_ne_saisit_rien(self):
        """Le cas réel : quelqu'un passe la main, deux images ressemblent à
        un poing, puis plus rien."""
        moteur = MoteurDeGestes()
        for _ in range(10):
            moteur.observer(_main(ouverture=1.0))
        moteur.observer(_main(ouverture=0.1))
        moteur.observer(_main(ouverture=0.1))
        moteur.observer(None)  # la main sort du champ
        assert moteur.etat is not Etat.SAISI


class TestLeGesteComplet:
    def _stabiliser(self, moteur, ouverture, n=12, t0=0.0):
        for i in range(n):
            moteur.observer(_main(ouverture=ouverture), maintenant=t0 + i * 0.05)
        return moteur.etat

    def test_ouvrir_fermer_ouvrir_donne_saisir_puis_relacher(self):
        moteur = MoteurDeGestes()
        assert self._stabiliser(moteur, 1.0) is Etat.PAUME_STABLE
        assert self._stabiliser(moteur, 0.1, t0=1.0) is Etat.SAISI
        assert self._stabiliser(moteur, 1.0, t0=2.0) is Etat.RELACHE

    def test_apres_un_geste_le_temps_de_repos_empeche_le_rebond(self):
        """Sans repos, ouvrir la main après un « attraper » déclencherait
        immédiatement un « relâcher », puis l'inverse, en boucle."""
        moteur = MoteurDeGestes(Seuils(repos_ms=800))
        self._stabiliser(moteur, 1.0)
        self._stabiliser(moteur, 0.1, t0=1.0)
        self._stabiliser(moteur, 1.0, t0=2.0)
        assert moteur.etat is Etat.RELACHE
        # Refermer tout de suite : le repos doit tenir l'état.
        self._stabiliser(moteur, 0.1, t0=2.1)
        assert moteur.etat is Etat.RELACHE, "le repos doit absorber le rebond"


class TestPerteEtAnnulation:
    def test_une_main_perdue_pendant_la_saisie_annule(self):
        """Figer l'état laisserait un objet « attrapé » que personne ne
        tient — et le prochain relâchement le déposerait n'importe où."""
        moteur = MoteurDeGestes(Seuils(trou_de_suivi_ms=300))
        for i in range(12):
            moteur.observer(_main(ouverture=1.0), maintenant=i * 0.05)
        for i in range(12):
            moteur.observer(_main(ouverture=0.1), maintenant=1.0 + i * 0.05)
        assert moteur.etat is Etat.SAISI
        moteur.observer(None, maintenant=2.0)  # plus rien pendant 700 ms
        assert moteur.etat is Etat.PERDU

    def test_une_main_absente_au_repos_ne_produit_rien(self):
        moteur = MoteurDeGestes()
        for _ in range(10):
            assert moteur.observer(None) is Etat.REPOS


class TestHysteresis:
    def test_une_main_a_la_frontiere_ne_fait_pas_osciller_l_etat(self):
        """Sans hystérésis, une main qui hésite change d'état dix fois par
        seconde — et chaque changement serait une action."""
        seuils = Seuils(fermeture_entree=0.55, fermeture_sortie=0.70)
        moteur = MoteurDeGestes(seuils)
        for i in range(12):
            moteur.observer(_main(ouverture=1.0), maintenant=i * 0.05)
        for i in range(12):
            moteur.observer(_main(ouverture=0.1), maintenant=1.0 + i * 0.05)
        assert moteur.etat is Etat.SAISI
        # Une main juste au-dessus du seuil d'entrée ne doit PAS rouvrir :
        # il faut franchir le seuil de sortie, plus haut.
        etats = set()
        for i in range(8):
            etats.add(moteur.observer(_main(ouverture=0.30), maintenant=2.0 + i * 0.05))
        assert etats == {Etat.SAISI}, f"l'état a oscillé : {etats}"


class TestReglages:
    def test_tous_les_seuils_vivent_au_meme_endroit(self):
        """§13 : pas de nombres magiques dispersés dans le code."""
        champs = set(Seuils.__dataclass_fields__)
        assert {
            "confiance_minimale",
            "fermeture_entree",
            "fermeture_sortie",
            "images_stables",
            "trou_de_suivi_ms",
            "repos_ms",
            "lissage",
        } <= champs

    def test_une_confiance_trop_faible_ne_produit_aucune_pose(self):
        moteur = MoteurDeGestes(Seuils(confiance_minimale=0.9))
        flous = [Point(p.nom, p.x, p.y, confiance=0.3) for p in _main(ouverture=1.0)]
        for _ in range(8):
            moteur.observer(flous)
        assert moteur.etat in (Etat.REPOS, Etat.MAIN_VUE)


class TestLatenceMesuree:
    """§141 : les gestes ne sont finis que quand leur coût est MESURÉ.

    La latence n'est pas un défaut à cacher : c'est le prix de ne pas
    déclencher sur une main qui passe. Elle est donc chiffrée ici, et un
    réglage qui la ferait exploser fera rougir ce test.
    """

    def _images_pour_saisir(self, seuils=None):
        moteur = MoteurDeGestes(seuils)
        for i in range(15):
            moteur.observer(_main(ouverture=1.0), maintenant=i * 0.05)
        assert moteur.etat is Etat.PAUME_STABLE
        for i in range(30):
            if moteur.observer(_main(ouverture=0.1), maintenant=2.0 + i * 0.05) is Etat.SAISI:
                return i + 1
        return 99

    def test_saisir_coute_moins_de_dix_images(self):
        images = self._images_pour_saisir()
        assert images <= 10, f"{images} images, soit {images / 15:.2f} s à 15 im/s"

    def test_le_minimum_reste_celui_des_images_stables(self):
        """Quel que soit le lissage, on ne descend jamais sous le nombre
        d'images de confirmation : c'est la garantie anti-faux-positif."""
        images = self._images_pour_saisir(Seuils(lissage=0.0, images_stables=4))
        assert images >= 4

    def test_un_lissage_extreme_est_visible_dans_la_mesure(self):
        """Un réglage qui rendrait les gestes inutilisables doit se voir."""
        assert self._images_pour_saisir(Seuils(lissage=0.95)) > 10
