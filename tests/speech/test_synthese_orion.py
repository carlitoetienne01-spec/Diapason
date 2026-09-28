"""§100 — un calcul trop lent ne doit pas réintroduire une lecture trouée."""

import pytest

from diapason.speech.realtime.synthese_orion import (
    CODES_PAR_PREFIXE,
    cout_prochain_prefixe,
    prefixe_assez_rapide,
    taille_prochain_prefixe,
)


@pytest.mark.parametrize(
    ("calcul", "audio", "autorise"),
    [(1.2, 1.92, True), (1.8, 1.92, False), (2.4, 1.92, False), (-1, 1.92, False)],
)
def test_une_reserve_audio_couvre_le_calcul_et_sa_marge(calcul, audio, autorise):
    assert prefixe_assez_rapide(calcul, audio) is autorise, (
        "un moteur plus lent que la lecture doit garder le tampon complet"
    )


def test_le_prefill_unique_ne_condamne_pas_une_suite_rapide():
    durees = [1.5] + [0.01] * 23
    prochain = cout_prochain_prefixe(durees, 0.7)
    assert prefixe_assez_rapide(prochain, 1.92), (
        "la réserve doit couvrir la suite, pas repayer le démarrage déjà achevé"
    )
    assert not prefixe_assez_rapide(cout_prochain_prefixe([0.1] * 12, 0.7), 1.92), (
        "une génération vraiment trop lente reste tamponnée"
    )


def test_le_lot_grandit_avant_que_le_decodeur_long_vide_la_reserve():
    assert taille_prochain_prefixe([0.025] * 12, 0.4) == CODES_PAR_PREFIXE
    long = taille_prochain_prefixe([0.025] * 12, 1.3)
    assert long > 24, "le décodage long doit être amorti sur davantage de son"
    assert long * 0.025 + 1.3 * 1.2 <= long * 0.08 * 0.85, (
        "le lot doit reconstituer la marge audio de 15 %"
    )
    assert taille_prochain_prefixe([0.1] * 12, 9) == 96, (
        "une forte charge ne crée pas un lot arbitrairement grand"
    )


def test_un_demarrage_lent_peut_accumuler_sa_reserve_sans_tout_retenir():
    durees = [0.035] * 12
    taille = taille_prochain_prefixe(durees, 0.7)
    cout = cout_prochain_prefixe(durees, 0.7, taille)
    assert prefixe_assez_rapide(cout, taille * 0.08), (
        "le rythme suivant est soutenable avec un lot adapté"
    )
    assert not prefixe_assez_rapide(cout, 24 * 0.08), "le premier lot reste trop court"
    assert prefixe_assez_rapide(cout, 48 * 0.08), (
        "le deuxième lot suffit : ne pas retenir la fin de toute la phrase"
    )
