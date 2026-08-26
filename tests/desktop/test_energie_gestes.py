"""L'état d'énergie du mode gestes (§83).

Spatial Mesh, gestes — 25 août 2026. Le §78 empêche la caméra de guetter en
permanence ; le §83 lui interdit de coûter le même prix qu'on s'en serve ou
non. La cadence était figée à douze images par seconde du premier instant au
désarmement : armer le mode puis aller lire un document, c'était filmer une
chaise pendant dix minutes au plein tarif.
"""

from __future__ import annotations

from diapason.desktop.energie_gestes import (
    CADENCE_ACTIVE,
    CADENCE_ECONOMIE,
    CADENCE_PRETE,
    SANS_MAIN_AVANT_VEILLE_S,
    Energie,
    batterie,
    cadence,
    etat_energie,
    oublier_la_batterie,
)


class TestCeQueLEtatDit:
    def test_desarmee_la_camera_est_eteinte(self):
        assert etat_energie(armee=False, depuis_derniere_main_s=None) is Energie.ETEINT
        assert cadence(Energie.ETEINT) == 0

    def test_armee_sans_avoir_jamais_vu_de_main_on_veille(self):
        """Une session qu'on vient d'armer n'est pas active : elle attend."""
        assert etat_energie(armee=True, depuis_derniere_main_s=None) is Energie.PRET

    def test_une_main_vue_a_l_instant_rend_actif(self):
        assert etat_energie(armee=True, depuis_derniere_main_s=0.0) is Energie.ACTIF

    def test_apres_le_silence_on_retombe_en_veille(self):
        limite = SANS_MAIN_AVANT_VEILLE_S
        assert etat_energie(armee=True, depuis_derniere_main_s=limite) is Energie.ACTIF
        apres = etat_energie(armee=True, depuis_derniere_main_s=limite + 0.1)
        assert apres is Energie.PRET

    def test_la_batterie_basse_l_emporte_sur_tout(self):
        """Y compris sur une main vue à l'instant : c'est le point du §83."""
        assert (
            etat_energie(
                armee=True,
                depuis_derniere_main_s=0.0,
                sur_batterie=True,
                batterie_pct=10,
            )
            is Energie.ECONOMIE
        )

    def test_une_batterie_pleine_ne_bride_rien(self):
        assert (
            etat_energie(
                armee=True,
                depuis_derniere_main_s=0.0,
                sur_batterie=True,
                batterie_pct=90,
            )
            is Energie.ACTIF
        )

    def test_sur_secteur_le_pourcentage_ne_bride_pas(self):
        """Branché à 5 %, la machine se recharge : rien à économiser."""
        assert (
            etat_energie(
                armee=True,
                depuis_derniere_main_s=0.0,
                sur_batterie=False,
                batterie_pct=5,
            )
            is Energie.ACTIF
        )


class TestLaCadenceQuiEnDecoule:
    def test_veiller_coute_quatre_fois_moins_qu_agir(self):
        assert cadence(Energie.PRET) * 4 == CADENCE_ACTIVE
        assert CADENCE_PRETE < CADENCE_ACTIVE

    def test_l_economie_est_le_moins_cher_des_etats_allumes(self):
        allumes = (CADENCE_ACTIVE, CADENCE_PRETE, CADENCE_ECONOMIE)
        assert CADENCE_ECONOMIE == min(allumes)
        assert CADENCE_ECONOMIE > 0, (
            "une cadence nulle serait une caméra éteinte, pas économe : "
            "le mode resterait armé sans jamais voir une main revenir"
        )

    def test_aucun_etat_allume_ne_rend_une_cadence_nulle(self):
        for etat in (Energie.PRET, Energie.ACTIF, Energie.ECONOMIE):
            assert cadence(etat) > 0, f"{etat} filmerait sans jamais capturer"


class TestLaBatterieNeSeLitPasDouzeFoisParSeconde:
    """`pmset` est un sous-processus : l'appeler à chaque image coûterait
    bien plus que ce que cet état fait économiser."""

    def test_la_mesure_est_gardee_en_cache(self, monkeypatch):
        appels = []

        def _fausse_lecture():
            appels.append(1)
            return (55, True)

        import diapason.heartbeat.tick as tick

        monkeypatch.setattr(tick, "lire_batterie", _fausse_lecture)
        oublier_la_batterie()
        for i in range(12):
            assert batterie(maintenant=100.0 + i * 0.08) == (55, True)
        assert len(appels) == 1, "douze images, une seule lecture de pmset"
        oublier_la_batterie()

    def test_le_cache_expire_pour_voir_un_cable_rebranche(self, monkeypatch):
        appels = []

        def _fausse_lecture():
            appels.append(1)
            return (55, len(appels) == 1)

        import diapason.heartbeat.tick as tick

        monkeypatch.setattr(tick, "lire_batterie", _fausse_lecture)
        oublier_la_batterie()
        assert batterie(maintenant=0.0) == (55, True)
        assert batterie(maintenant=31.0) == (55, False)
        assert len(appels) == 2
        oublier_la_batterie()

    def test_une_machine_sans_batterie_n_est_pas_une_panne(self, monkeypatch):
        import diapason.heartbeat.tick as tick

        def _echec():
            raise OSError("pmset introuvable")

        monkeypatch.setattr(tick, "lire_batterie", _echec)
        oublier_la_batterie()
        assert batterie(maintenant=0.0) is None
        oublier_la_batterie()
