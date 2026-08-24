"""Le filet anti-promesse partagé — phrase par phrase, offres exclues.

Le filet original (voix, 23 août 2026) attrapait aussi les OFFRES :
« veux-tu que je cherche ? » sommait le modèle qui venait poliment de
proposer. L'affinement du 24 août les libère, dans les deux régimes.
"""

from __future__ import annotations

import pytest

from diapason.core.promesse import est_une_promesse_sans_acte


class TestCeQuiSomme:
    @pytest.mark.parametrize(
        "texte",
        [
            "D'accord, je cherche tes tâches.",
            "Je vais ouvrir Safari.",
            "Je m'en occupe.",
            "La recherche est relancée.",
            "C'est fait.",
            "Les résultats s'affichent.",
        ],
    )
    def test_annonces_et_accomplis_somment_partout(self, texte):
        assert est_une_promesse_sans_acte(texte)
        assert est_une_promesse_sans_acte(texte, ecrit=True)

    def test_a_l_oral_seulement(self):
        # « Un instant » est la promesse-type à l'oral, de la prose au chat.
        assert est_une_promesse_sans_acte("Un instant.")
        assert not est_une_promesse_sans_acte(
            "Un instant de patience est utile.", ecrit=True
        )
        # « est ouverte » : mensonge à l'oral, cliché du bureau légitime au chat.
        assert est_une_promesse_sans_acte("Safari est ouverte.")
        assert not est_une_promesse_sans_acte(
            "Safari est ouvert au premier plan.", ecrit=True
        )


class TestCeQuiResteLibre:
    @pytest.mark.parametrize(
        "texte",
        [
            "Veux-tu que je cherche ?",
            "Je peux le faire si tu veux.",
            "Si tu veux, je cherche.",
            "Souhaites-tu que j'ouvre le dossier ?",
        ],
    )
    def test_les_offres_ne_somment_jamais(self, texte):
        assert not est_une_promesse_sans_acte(texte)
        assert not est_une_promesse_sans_acte(texte, ecrit=True)

    def test_le_discours_ecrit_est_libre(self):
        assert not est_une_promesse_sans_acte(
            "Je note que tu préfères le matin.", ecrit=True
        )
        assert not est_une_promesse_sans_acte(
            "Quand c'est fait, dis-le-moi.", ecrit=True
        )

    def test_phrase_par_phrase_pas_en_bloc(self):
        """Une offre dans une phrase n'immunise pas la promesse d'à côté."""
        assert est_une_promesse_sans_acte(
            "Je peux t'aider si tu veux. Je cherche tes tâches."
        )

    def test_le_vide_ne_somme_pas(self):
        assert not est_une_promesse_sans_acte("")
        assert not est_une_promesse_sans_acte(None)
