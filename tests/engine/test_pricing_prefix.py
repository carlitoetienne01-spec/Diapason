"""Le bon tarif pour le bon modèle.

La table contient à la fois ``gpt-4o`` et ``gpt-4o-mini``. Une variante datée
— ``gpt-4o-mini-2024-07-18``, la forme que renvoient les API en production —
n'a pas d'entrée exacte et tombe dans le balayage par préfixe. Celui-ci
prenait la **première** correspondance dans l'ordre d'insertion, donc
``gpt-4o`` : seize fois le vrai prix, sur un chiffre présenté à l'utilisateur
comme sa dépense.
"""

from __future__ import annotations

import logging

import pytest

from diapason.engine.cloud import PRICING, estimate_cost, resolve_pricing

M = 1_000_000


def prix_attendu(cle: str) -> float:
    return PRICING[cle][0] + PRICING[cle][1]


class TestLePlusLongPrefixeGagne:
    @pytest.mark.parametrize(
        "demande,tarif_attendu",
        [
            # Surfacturé ×16,7 : payait le tarif gpt-4o complet.
            ("gpt-4o-mini-2024-07-18", "gpt-4o-mini"),
            # Surfacturé ×17,8.
            ("gpt-5-mini-2025-08-07", "gpt-5-mini"),
            # Sous-facturé de moitié, l'erreur dans l'autre sens.
            ("MiniMax-M2.7-highspeed-v2", "MiniMax-M2.7-highspeed"),
            ("MiniMax-M2.5-highspeed-beta", "MiniMax-M2.5-highspeed"),
        ],
    )
    def test_une_variante_datee_paie_son_propre_tarif(self, demande, tarif_attendu):
        assert estimate_cost(demande, M, M) == pytest.approx(
            prix_attendu(tarif_attendu)
        )

    def test_une_variante_sans_rival_garde_son_prefixe(self, demande=None):
        """Le témoin : gpt-4o n'a pas de plus long préfixe concurrent ici."""
        assert estimate_cost("gpt-4o-2024-01-01", M, M) == pytest.approx(
            prix_attendu("gpt-4o")
        )

    def test_une_correspondance_exacte_prime_toujours(self):
        for cle in PRICING:
            assert resolve_pricing(cle) == PRICING[cle], cle


class TestUnModeleInconnuNeSeFaitPlusPasserPourGratuit:
    def test_il_ne_rend_aucun_tarif(self):
        assert resolve_pricing("un-modele-qui-nexiste-pas") is None

    def test_le_zero_est_annonce(self, caplog):
        """0,00 $ reste la valeur — une douzaine d'appelants et le schéma de
        télémétrie en dépendent — mais il cesse d'être muet : « gratuit » et
        « je ne connais pas le prix » ne sont pas la même information."""
        with caplog.at_level(logging.WARNING):
            assert estimate_cost("un-modele-qui-nexiste-pas", M, M) == 0.0
        assert any("No pricing entry" in r.message for r in caplog.records)

    def test_un_modele_connu_ne_declenche_aucun_avertissement(self, caplog):
        with caplog.at_level(logging.WARNING):
            estimate_cost("gpt-4o", M, M)
        assert not [r for r in caplog.records if "No pricing entry" in r.message]
