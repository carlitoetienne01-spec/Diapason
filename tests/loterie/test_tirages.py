"""Lire une archive sans jamais deviner.

§5 du cahier : ne jamais faire semblant. Une ligne mal lue produirait des
statistiques fausses présentées avec la même assurance que les vraies — c'est
le seul défaut de ce module qui pourrait tromper quelqu'un.
"""

from __future__ import annotations

from datetime import date

import pytest

from diapason.loterie.tirages import (
    COMBINAISONS,
    GRAND_NUMERO_MAX,
    NUMERO_MAX,
    Tirage,
    TirageInvalide,
    analyser_page,
)

# La forme exacte servie par l'archive, relevée le 31 août 2026.
LIGNE = """
<tr style="text-align:center; background-color: #C1DDF2;">
    <td class="date-cell" style="border-style: groove;">{jour}/{mois}<br>{an}({j})</td>
    <td class="number-cell" style="font-weight:800;">{numeros}</td>
    <td class="bonus-cell" style="padding:25px 0;">{grand}</td>
</tr>
"""


def page(lignes: str) -> str:
    return f'<table id="ltotable">{lignes}</table>'


class TestLaGrilleDuJeu:
    """Cinq numéros parmi 49, un Grand Numéro parmi 7."""

    def test_le_nombre_de_combinaisons_recoupe_la_cote_publiee(self) -> None:
        # Le jeu annonce « 1 chance sur 13 348 188 ». Si notre calcul ne
        # tombait pas dessus, tout le reste — cotes, espérance, simulation —
        # serait faux d'un facteur inconnu.
        assert COMBINAISONS == 13_348_188


class TestUneLigneDArchive:
    def test_lit_un_tirage_reel(self) -> None:
        html = page(
            LIGNE.format(
                jour="31",
                mois="08",
                an="26",
                j="MON",
                numeros="06,&nbsp;23,&nbsp;28,&nbsp;34,&nbsp;37",
                grand="04",
            )
        )
        (tirage,) = analyser_page(html)
        assert tirage.jour == date(2026, 8, 31)
        assert tirage.numeros == (6, 23, 28, 34, 37), (
            "ce sont les numéros publiés par Loto-Québec le 31 août 2026 : "
            "s'ils changent, c'est la lecture qui est fausse"
        )
        assert tirage.grand_numero == 4

    def test_deux_chiffres_d_annee_valent_le_siecle_courant(self) -> None:
        html = page(
            LIGNE.format(
                jour="20",
                mois="10",
                an="16",
                j="THU",
                numeros="08,&nbsp;14,&nbsp;18,&nbsp;35,&nbsp;37",
                grand="05",
            )
        )
        (tirage,) = analyser_page(html)
        assert tirage.jour == date(2016, 10, 20), (
            "le tout premier tirage du jeu ; le lire en 1916 décalerait tout "
            "l'historique d'un siècle sans que rien ne le signale"
        )

    def test_les_numeros_ressortent_tries(self) -> None:
        html = page(
            LIGNE.format(
                jour="01",
                mois="02",
                an="20",
                j="MON",
                numeros="37,&nbsp;06,&nbsp;28,&nbsp;23,&nbsp;34",
                grand="1",
            )
        )
        (tirage,) = analyser_page(html)
        assert tirage.numeros == (6, 23, 28, 34, 37), (
            "sans tri, deux tirages identiques dans un ordre différent "
            "compteraient pour deux"
        )


class TestCeQuOnRefuseDeLire:
    """Une ligne douteuse est sautée, jamais devinée."""

    def test_une_ligne_a_quatre_numeros_est_sautee(self) -> None:
        html = page(
            LIGNE.format(
                jour="31",
                mois="08",
                an="26",
                j="MON",
                numeros="06,&nbsp;23,&nbsp;28,&nbsp;34",
                grand="04",
            )
        )
        assert analyser_page(html) == [], (
            "compléter une ligne incomplète inventerait un tirage qui n'a "
            "jamais eu lieu"
        )

    def test_un_grand_numero_hors_bornes_est_saute(self) -> None:
        html = page(
            LIGNE.format(
                jour="31",
                mois="08",
                an="26",
                j="MON",
                numeros="06,&nbsp;23,&nbsp;28,&nbsp;34,&nbsp;37",
                grand="09",
            )
        )
        assert analyser_page(html) == []

    def test_les_encarts_de_la_page_ne_produisent_rien(self) -> None:
        # Une page d'archives porte des tableaux de mise en page et des
        # publicités. Les prendre pour des tirages fausserait les fréquences.
        html = (
            '<table style="margin:auto;"><tr><td><iframe src="pub"></iframe>'
            "</td></tr></table>"
        )
        assert analyser_page(html) == []

    def test_une_page_vide_ne_leve_pas(self) -> None:
        # La moisson s'arrête SUR une page vide : si l'analyse levait, elle
        # s'arrêterait sur une exception au lieu d'une fin d'archive.
        assert analyser_page("") == []


class TestUnTirageRefuseDExisterFaux:
    def test_un_doublon_est_refuse(self) -> None:
        with pytest.raises(TirageInvalide):
            Tirage(jour=date(2026, 1, 1), numeros=(1, 1, 2, 3, 4), grand_numero=1)

    def test_un_numero_hors_bornes_est_refuse(self) -> None:
        with pytest.raises(TirageInvalide):
            Tirage(
                jour=date(2026, 1, 1),
                numeros=(1, 2, 3, 4, NUMERO_MAX + 1),
                grand_numero=1,
            )

    def test_un_grand_numero_hors_bornes_est_refuse(self) -> None:
        with pytest.raises(TirageInvalide):
            Tirage(
                jour=date(2026, 1, 1),
                numeros=(1, 2, 3, 4, 5),
                grand_numero=GRAND_NUMERO_MAX + 1,
            )

    def test_des_numeros_non_tries_sont_refuses(self) -> None:
        with pytest.raises(TirageInvalide):
            Tirage(jour=date(2026, 1, 1), numeros=(5, 4, 3, 2, 1), grand_numero=1)
