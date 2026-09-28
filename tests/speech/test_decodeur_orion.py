"""§100 — un raccord rapide ne change ni le son ni le timbre du tour suivant."""

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from diapason.speech.realtime import decodeur_orion as d


@pytest.fixture
def tableaux(monkeypatch):
    mx = ModuleType("mlx.core")
    mx.array = np.array
    mx.zeros = np.zeros
    mx.concatenate = np.concatenate
    mx.eval = lambda *_: None
    mlx = ModuleType("mlx")
    mlx.core = mx
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    monkeypatch.setattr(d, "_AMORCE", None)


@pytest.mark.parametrize("biais", [None, np.array([7.0])])
def test_le_raccord_progressif_garde_exactement_la_convolution_complete(
    tableaux, biais
):
    """§100 — le report ajoutait le biais une deuxième fois au raccord."""

    class Convolution:
        bias = biais

        def __call__(self, x):
            sortie = np.zeros((1, (x.shape[1] - 1) * 2 + 4, 1))
            noyau = np.array([1.0, 2.0, 3.0, 4.0])
            for i, valeur in enumerate(x[0, :, 0]):
                sortie[0, i * 2 : i * 2 + 4, 0] += valeur * noyau
            return sortie + (0 if self.bias is None else self.bias)

    couche = SimpleNamespace(conv=Convolution(), _overflow=None, trim_right=2)
    entree = np.array([2.0, 4.0, -1.0, 3.0]).reshape(1, -1, 1)
    attendu = couche.conv(entree)[:, :-2, :]
    obtenu = np.concatenate(
        [
            d.raccorder_sur_echantillonnage(couche, entree[:, :2, :]),
            d.raccorder_sur_echantillonnage(couche, entree[:, 2:3, :]),
            d.raccorder_sur_echantillonnage(couche, entree[:, 3:, :]),
        ],
        axis=1,
    )
    np.testing.assert_array_equal(
        obtenu, attendu, err_msg="aucun double biais aux deux raccords"
    )


def test_le_cache_ne_conserve_que_la_reference_et_le_bloc_garde_son_contexte(
    tableaux, monkeypatch
):
    """§100 — ni contamination entre phrases ni continuité inventée après 300 codes."""

    class Modele:
        decoder = []
        total_upsample = 1

        def __init__(self):
            self._buffer = None
            self._transformer_cache = None
            self.pre_transformer = SimpleNamespace(
                make_cache=lambda: [SimpleNamespace(state=(np.zeros(1), np.zeros(1)))]
            )
            self.appels = []

        def reset_streaming_state(self):
            self._buffer = None
            self._transformer_cache = None

        def named_modules(self):
            return [("racine", self)]

    def pas(self, codes):
        moteur = self.decodeur
        moteur.appels.append(codes.shape[2])
        if moteur._transformer_cache is None:
            moteur._transformer_cache = moteur.pre_transformer.make_cache()
        if moteur._buffer is None:
            moteur._buffer = np.zeros(1)
        moteur._buffer += codes.sum()
        moteur._transformer_cache[0].state[0][:] += codes.sum()
        return np.zeros((1, 1, codes.shape[2]))

    monkeypatch.setattr(d.DecodeurOrion, "_pas", pas)
    moteur = Modele()
    reference = np.ones((1, 16, 90))
    premiere = d.DecodeurOrion(moteur, reference)
    assert moteur.appels == [90], "préparer toute la référence avant le premier son"
    premiere.decoder(np.ones((1, 16, 235)))
    assert moteur.appels == [90, 210, 25, 25], (
        "le bloc natif s'arrête à 300 puis reprend avec 25 codes à gauche"
    )
    premiere.fermer()
    deuxieme = d.DecodeurOrion(moteur, reference)
    assert moteur.appels == [90, 210, 25, 25], "aucun recalcul de la référence fixe"
    assert moteur._buffer[0] == reference.sum(), "la première phrase n'a pas fui"
    assert moteur._transformer_cache[0].state[0][0] == reference.sum()
    deuxieme.fermer()
    d.DecodeurOrion(moteur, reference * 2)
    assert moteur.appels[-1] == 90 and len(moteur.appels) == 5, (
        "une référence modifiée doit recalculer le timbre"
    )
    autre = Modele()
    d.DecodeurOrion(autre, reference * 2)
    assert autre.appels == [90], "un autre modèle ne reprend jamais le cache du premier"
    dernier = d.DecodeurOrion(autre, reference * 2)
    son = dernier.decoder(np.ones((1, 16, 8)), termine=True)
    assert autre.appels[-1] == d.CODES_MINIMUM, (
        "la dernière queue utilise un noyau stable"
    )
    assert son.shape[-1] == 8, "les compléments de calcul ne doivent jamais être joués"
    with pytest.raises(ValueError, match="terminée"):
        dernier.decoder(np.ones((1, 16, 1)))
    suivant = d.DecodeurOrion(autre, reference * 2)
    debut = suivant.decoder(np.ones((1, 16, 216)))
    assert debut.shape[-1] == 210, "les six codes du bloc suivant restent en attente"
    fin = suivant.decoder(np.zeros((1, 16, 0)), termine=True)
    assert fin.shape[-1] == 6, "une fin sans nouveau code vide quand même la queue"
