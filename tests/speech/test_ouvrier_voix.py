"""§100 : le timbre choisi reste la référence, et une phrase échouée reste muette."""

from __future__ import annotations

import base64
import io
import json
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from diapason.speech.realtime import ouvrier_voix


@pytest.fixture
def moteur(monkeypatch):
    graines = []
    mx = ModuleType("mlx.core")
    mx.eval = lambda _: None
    mx.random = SimpleNamespace(seed=graines.append)
    mx.limites_cache = []
    mx.set_cache_limit = mx.limites_cache.append
    mlx = ModuleType("mlx")
    mlx.core = mx
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    appels = []

    class Modele:
        resultats = []

        def generate(self, **options):
            appels.append(options)
            yield from self.resultats

    return Modele(), appels, graines


def rendu(audio, frequence=24000, jetons=30):
    return SimpleNamespace(
        audio=np.array(audio), sample_rate=frequence, token_count=jetons
    )


def test_les_phrases_gardent_la_reference_sans_heriter_du_son_precedent(moteur):
    modele, appels, graines = moteur
    modele.resultats = [rendu([0, 0.25, -0.25])]
    for voix, texte in [
        ("qwen3-b", "Bonjour."),
        ("qwen3-b", "Ça va ?"),
        ("qwen3-b", "Continuons."),
    ]:
        ouvrier_voix.synthetiser(modele, voix, texte)
    assert appels[0]["ref_audio"] == appels[2]["ref_audio"], (
        "revenir à B reprend sa référence, jamais un rendu généré ou celle de A"
    )
    assert appels[0]["ref_audio"] == appels[1]["ref_audio"], "un seul timbre conservé"
    assert graines == [84, 84, 84], "une phrase précédente ne change pas l'aléa de B"
    assert all(c["stream"] is False for c in appels), (
        "le décodeur complet doit amorcer sa voix avec les codes de la référence"
    )
    assert [c["text"] for c in appels] == ["Bonjour.", "Ça va ?", "Continuons."], (
        "stabiliser le timbre ne réécrit ni les mots ni la ponctuation expressive"
    )


@pytest.mark.parametrize(
    "resultats",
    [
        [],
        [rendu([np.nan])],
        [rendu([0.1], frequence=16000)],
        [rendu([0.1], jetons=900)],
    ],
)
def test_un_rendu_vide_corrompu_ou_tronque_ne_se_joue_pas(moteur, resultats):
    modele, _, _ = moteur
    modele.resultats = resultats
    with pytest.raises(ValueError):
        ouvrier_voix.synthetiser(modele, "qwen3-b", "Bonjour.")


def test_le_transport_decoupe_sans_perdre_ni_reordonner_les_echantillons(
    moteur, monkeypatch
):
    modele, _, _ = moteur
    valeurs = np.linspace(-0.75, 0.75, 26001, dtype=np.float32)
    modele.resultats = [rendu(valeurs)]
    utilitaires = ModuleType("mlx_audio.tts.utils")

    def charger(_):
        assert sys.modules["mlx.core"].limites_cache == [256 * 1024 * 1024], (
            "borner les buffers libres avant de charger et de préchauffer la voix"
        )
        return modele

    utilitaires.load_model = charger
    monkeypatch.setitem(sys.modules, "mlx_audio.tts.utils", utilitaires)
    # Le vrai graphe MLX est comparé à PCM identique sur le banc natif ;
    # ce test isole le transport, avec un modèle sans décodeur neuronal.
    monkeypatch.setattr(ouvrier_voix, "borner_intermediaires", lambda _: None)
    monkeypatch.setattr(
        ouvrier_voix,
        "generer_morceaux",
        lambda modele, voix, texte, mesures=None: iter(
            [ouvrier_voix.synthetiser(modele, voix, texte)]
        ),
    )
    monkeypatch.setattr(sys, "argv", ["ouvrier", "modele-local"])
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '{"type":"ping"}\n'
            + json.dumps({"voice": "qwen3-b", "text": "Bonjour."})
            + '\n{"type":"ping"}\n'
        ),
    )
    sortie = io.StringIO()
    monkeypatch.setattr(sys, "stdout", sortie)
    try:
        ouvrier_voix.principal()
    finally:
        sys.stdout = sortie
    trames = [json.loads(ligne) for ligne in sortie.getvalue().splitlines()]
    assert [t["type"] for t in trames] == [
        "ready",
        "ready",
        "audio",
        "audio",
        "audio",
        "done",
        "ready",
    ], "les sondes répondent sans déclencher une synthèse ni rejouer le son"
    assert len(moteur[1]) == 1, "seul le texte demandé est synthétisé"
    morceaux = [base64.b64decode(t["data"]) for t in trames if t["type"] == "audio"]
    assert len(morceaux) == 3, "la phrase ne doit pas dépasser la taille des trames"
    assert all(len(p) <= 23040 for p in morceaux), "paquets bornés à 480 ms"
    assert b"".join(morceaux) == (valeurs * 32767).astype("<i2").tobytes(), (
        "la segmentation réseau ne doit introduire ni trou, ni duplication, ni gain"
    )
