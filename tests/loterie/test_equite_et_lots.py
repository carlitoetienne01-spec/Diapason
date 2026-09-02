"""Le test qui répond à la vraie question, et la table des lots qui la chiffre.

« Est-il possible d'avoir des chiffres fiables à jouer ? » — la réponse tient
dans `examiner`. Si ce test se trompait, tout le module dirait le contraire de la
vérité avec la même assurance.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from fractions import Fraction

from diapason.loterie import reference
from diapason.loterie.equite import examiner, frequences
from diapason.loterie.lots import (
    PROBABILITES,
    TABLE,
    categorie,
    probabilite_de_gagner,
)
from diapason.loterie.tirages import GRAND_NUMERO_MAX, NUMERO_MAX, Tirage
from diapason.loterie.validation import controler


def tirages_equitables(combien: int, graine: int = 7) -> list[Tirage]:
    alea = random.Random(graine)
    jour = date(2016, 10, 20)
    sortie = []
    for i in range(combien):
        sortie.append(
            Tirage(
                jour=jour + timedelta(days=i * 3),
                numeros=tuple(sorted(alea.sample(range(1, NUMERO_MAX + 1), 5))),
                grand_numero=alea.randint(1, GRAND_NUMERO_MAX),
            )
        )
    return sortie


class TestLesCotesSontRecalculees:
    """Recopier les cotes publiées, c'est faire confiance. On les recalcule."""

    def test_le_gros_lot_tombe_sur_la_cote_publiee(self) -> None:
        assert round(1 / float(PROBABILITES[(5, True)])) == 13_348_188

    def test_les_cotes_publiees_sont_retrouvees(self) -> None:
        # Sept catégories dont la cote publiée doit tomber au chiffre près.
        publiees = {
            (5, True): 13_348_188,
            (5, False): 2_224_698,
            (4, True): 60_674,
            (4, False): 10_112,
            (3, True): 1_411,
            (3, False): 235,
            (2, True): 101,
        }
        for cle, attendu in publiees.items():
            calcule = round(1 / float(PROBABILITES[cle]))
            assert calcule == attendu, (
                f"catégorie {cle} : calculé 1 sur {calcule}, publié 1 sur {attendu}"
            )

    def test_le_lot_du_grand_numero_seul_est_compte_par_categorie(self) -> None:
        # Le jeu annonce « 1 sur 7 » pour le Grand Numéro : c'est la cote de le
        # TROUVER, quel que soit le reste. La cote de gagner CE lot — le Grand
        # Numéro et aucun numéro régulier — vaut 1 sur 12,29. Compter 1 sur 7
        # ferait dépasser 1 à la somme des probabilités.
        assert round(1 / float(PROBABILITES[(0, True)]), 2) == 12.29

    def test_la_somme_des_probabilites_ne_depasse_pas_un(self) -> None:
        total = sum(PROBABILITES.values(), Fraction(0))
        assert total < 1, "des catégories qui se chevauchent compteraient double"
        assert round(1 / float(total), 2) == 6.79

    def test_une_grille_perdante_ne_rend_pas_un_lot_a_zero(self) -> None:
        assert categorie(2, False) is None, (
            "un lot à 0 $ ferait afficher « vous avez gagné 0 $ » à un billet "
            "qui n'a rien gagné"
        )

    def test_chaque_lot_de_la_table_a_une_probabilite(self) -> None:
        for lot in TABLE:
            assert (lot.bons, lot.grand) in PROBABILITES

    def test_gagner_quelque_chose_reste_rare(self) -> None:
        assert 0.14 < float(probabilite_de_gagner()) < 0.15


class TestLeTestDEquite:
    def test_se_tait_en_dessous_de_cent_tirages(self) -> None:
        assert examiner(tirages_equitables(99)) is None, (
            "annoncer « équitable » sur quatre-vingt-dix-neuf tirages serait "
            "la fausse assurance que ce module combat"
        )

    def test_reconnait_un_tirage_equitable(self) -> None:
        verdict = examiner(tirages_equitables(1030))
        assert verdict is not None
        assert verdict.equitable, f"p = {verdict.valeur_p}"
        assert verdict.tirages == 1030

    def test_demasque_un_tirage_truque(self) -> None:
        # Un dé pipé : le 7 sort dans un tirage sur deux. Si le test ne le
        # voyait pas, son « équitable » sur les vraies données ne vaudrait rien.
        alea = random.Random(3)
        truques = []
        jour = date(2016, 10, 20)
        for i in range(1030):
            autres = alea.sample([n for n in range(1, 50) if n != 7], 4)
            numeros = (
                sorted([7, *autres])
                if i % 2 == 0
                else sorted(alea.sample(range(1, 50), 5))
            )
            truques.append(
                Tirage(
                    jour=jour + timedelta(days=i * 3),
                    numeros=tuple(numeros),
                    grand_numero=alea.randint(1, 7),
                )
            )
        verdict = examiner(truques)
        assert verdict is not None
        assert not verdict.equitable, (
            "un numéro sortant une fois sur deux DOIT être détecté, sinon le "
            "test ne prouve rien quand il dit « équitable »"
        )

    def test_le_plus_frequent_est_toujours_a_deux_ecarts_types(self) -> None:
        # Le chiffre qui désarme l'idée de « numéro chaud » : sur 49 numéros
        # parfaitement équitables, le plus sorti l'est d'environ deux
        # écarts-types. Le voir ne prouve donc rien.
        verdict = examiner(tirages_equitables(1030))
        assert verdict is not None
        assert 1.8 < verdict.ecart_max_attendu < 2.3

    def test_les_quarante_neuf_numeros_sont_comptes_meme_absents(self) -> None:
        freq = frequences([])
        assert len(freq) == NUMERO_MAX
        assert set(freq.values()) == {0}


class TestLInstantanéOfficiel:
    def test_la_somme_des_frequences_officielles_est_coherente(self) -> None:
        # 5 numéros x 1 030 tirages = 5 150. Si la table relevée ne tombait pas
        # dessus, elle aurait été mal recopiée — et tout le contrôle croisé
        # reposerait sur des chiffres faux.
        assert sum(reference.FREQUENCES.values()) == 5 * reference.TIRAGES

    def test_les_quarante_neuf_numeros_y_sont(self) -> None:
        assert sorted(reference.FREQUENCES) == list(range(1, NUMERO_MAX + 1))

    def test_le_controle_refuse_une_moisson_incomplete(self) -> None:
        controle = controler(tirages_equitables(500))
        assert not controle.concordant
        assert "500" in controle.raison

    def test_le_controle_refuse_des_frequences_qui_divergent(self) -> None:
        # Mille trente tirages équitables mais différents des vrais : le compte
        # est bon, les fréquences non. C'est exactement le cas qu'il faut
        # attraper — une source qui sert le bon NOMBRE de mauvais tirages.
        controle = controler(tirages_equitables(1030))
        assert controle.tirages_moissonnes == 1030
        assert not controle.concordant
        assert controle.ecarts, "des fréquences inventées doivent diverger"
