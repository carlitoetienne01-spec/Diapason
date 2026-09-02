"""Le simulateur, et le magasin qui garde ce qu'on a moissonné."""

from __future__ import annotations

from datetime import date

import pytest

from diapason.loterie.depot import DepotTirages
from diapason.loterie.lots import PRIX_PARTICIPATION
from diapason.loterie.simulation import (
    TIRAGES_MAX,
    GrilleInvalide,
    esperance_par_participation,
    simuler,
    valider_grille,
)
from diapason.loterie.tirages import Tirage


class TestLaGrilleQuOnRefuse:
    """Une grille fausse est refusée, jamais corrigée en douce."""

    def test_quatre_numeros_ne_font_pas_une_grille(self) -> None:
        with pytest.raises(GrilleInvalide):
            valider_grille([1, 2, 3, 4], 1)

    def test_un_doublon_est_refuse(self) -> None:
        with pytest.raises(GrilleInvalide):
            valider_grille([1, 1, 2, 3, 4], 1)

    def test_un_numero_hors_bornes_est_refuse(self) -> None:
        with pytest.raises(GrilleInvalide):
            valider_grille([1, 2, 3, 4, 50], 1)

    def test_un_grand_numero_hors_bornes_est_refuse(self) -> None:
        with pytest.raises(GrilleInvalide):
            valider_grille([1, 2, 3, 4, 5], 8)

    def test_la_grille_ressort_triee(self) -> None:
        assert valider_grille([37, 6, 28, 23, 34], 4) == (6, 23, 28, 34, 37)

    def test_trop_de_tirages_est_refuse(self) -> None:
        # Sans plafond, une demande de mille milliards ferait attendre le
        # serveur sans jamais dire pourquoi.
        with pytest.raises(GrilleInvalide):
            simuler([1, 2, 3, 4, 5], 1, TIRAGES_MAX + 1)


class TestLaSimulation:
    def test_la_meme_graine_donne_le_meme_resultat(self) -> None:
        a = simuler([7, 13, 22, 31, 44], 3, 2000, graine=42)
        b = simuler([7, 13, 22, 31, 44], 3, 2000, graine=42)
        assert a == b, (
            "sans reproductibilité, on ne saurait jamais si un écart vient du "
            "hasard ou d'un changement de code"
        )

    def test_deux_graines_donnent_deux_vies(self) -> None:
        a = simuler([7, 13, 22, 31, 44], 3, 5000, graine=1)
        b = simuler([7, 13, 22, 31, 44], 3, 5000, graine=2)
        assert a.gagne != b.gagne, "une simulation est UNE vie, pas la moyenne"

    def test_la_depense_est_le_prix_du_billet_fois_les_tirages(self) -> None:
        r = simuler([1, 2, 3, 4, 5], 1, 100, graine=0)
        assert r.depense == 100 * PRIX_PARTICIPATION

    def test_une_vie_de_jeu_se_solde_par_une_perte(self) -> None:
        # Cinquante ans à deux billets par semaine. Ce n'est pas une opinion
        # sur le jeu : c'est ce que rendent les cotes publiées.
        r = simuler([7, 13, 22, 31, 44], 3, 5200, graine=1)
        assert r.solde < 0
        assert r.depense == 15_600

    def test_l_esperance_est_la_moitie_de_la_mise(self) -> None:
        esperance = esperance_par_participation()
        assert 0.45 < esperance / PRIX_PARTICIPATION < 0.55, (
            f"{esperance:.3f} $ rendus pour {PRIX_PARTICIPATION} $ misés"
        )

    def test_sur_beaucoup_de_tirages_le_gain_moyen_rejoint_l_esperance(self) -> None:
        # La preuve que la simulation et le calcul parlent du même jeu. Les
        # gros lots sont si rares qu'ils ne tombent pas ici : on compare donc
        # ce qui est atteignable, hors des deux catégories à rente.
        r = simuler([7, 13, 22, 31, 44], 3, 200_000, graine=11)
        moyen = r.gagne / r.tirages
        assert 0.5 < moyen < 1.4, f"gain moyen simulé : {moyen:.3f} $"


class TestLeMagasin:
    def test_moissonner_deux_fois_ne_duplique_pas(self, tmp_path) -> None:
        depot = DepotTirages(tmp_path / "l.db")
        tirages = [
            Tirage(jour=date(2026, 8, 31), numeros=(6, 23, 28, 34, 37), grand_numero=4)
        ]
        assert depot.enregistrer(tirages) == 1
        assert depot.enregistrer(tirages) == 0, (
            "le jour est la clé : rejouer une moisson ne doit rien créer"
        )
        assert depot.compte() == 1

    def test_les_tirages_ressortent_du_plus_ancien_au_plus_recent(
        self, tmp_path
    ) -> None:
        depot = DepotTirages(tmp_path / "l.db")
        depot.enregistrer(
            [
                Tirage(jour=date(2026, 8, 31), numeros=(1, 2, 3, 4, 5), grand_numero=1),
                Tirage(
                    jour=date(2016, 10, 20), numeros=(6, 7, 8, 9, 10), grand_numero=2
                ),
            ]
        )
        tous = depot.tous()
        assert [t.jour for t in tous] == [date(2016, 10, 20), date(2026, 8, 31)]

    def test_un_tirage_relu_est_identique_a_celui_qu_on_a_pose(self, tmp_path) -> None:
        depot = DepotTirages(tmp_path / "l.db")
        pose = Tirage(
            jour=date(2026, 8, 31), numeros=(6, 23, 28, 34, 37), grand_numero=4
        )
        depot.enregistrer([pose])
        assert depot.tous() == [pose]

    def test_un_magasin_vide_n_a_pas_de_dernier_jour(self, tmp_path) -> None:
        assert DepotTirages(tmp_path / "l.db").dernier_jour() is None
