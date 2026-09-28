"""§100 — le budget d'un brouillon ne dégrade pas la phrase finale native."""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.live
def test_un_brouillon_abandonne_ne_modifie_pas_la_transcription_finale():
    runtime = Path.home() / ".diapason/speech/whisper-mlx/runtime/bin/python"
    modele = runtime.parents[2] / "model"
    if not runtime.is_file() or not modele.is_dir():
        pytest.skip("La reconnaissance MLX locale n'est pas installée")
    racine = Path(__file__).resolve().parents[2]
    script = r"""
import json, sys, time
from pathlib import Path
import mlx.core as mx
from mlx_whisper.audio import load_audio
from mlx_whisper.transcribe import transcribe
sys.path.insert(0, sys.argv[1])
import ouvrier_reconnaissance as ouvrier
mx.set_cache_limit(256*1024*1024)
# Référence synthétique livrée avec Orion, aucun son du microphone.
audio = load_audio(str(Path(sys.argv[1]) / 'voix/voix-posee-v2.wav'))
options = dict(path_or_hf_repo=sys.argv[2], language='fr',
               condition_on_previous_text=False, verbose=None)
temoin = transcribe(audio, **options)['text']
mesures = []
for budget, secondes in [(0.0, 0.8), (1.0, 0.8), (1.0, 2.0)]:
    ouvrier.BUDGET_BROUILLON_S = budget
    debut = time.monotonic()
    expire = False
    try:
        with ouvrier.borner_brouillon(True):
            transcribe(audio[:int(secondes*16000)], temperature=0,
                       sample_len=16+int(secondes*16), **options)
    except ouvrier.BrouillonTropLent:
        mx.synchronize()
        expire = True
    mesures.append(dict(budgetS=budget, dureeS=time.monotonic()-debut,
                        expire=expire))
with ouvrier.borner_brouillon(False):
    finale = transcribe(audio, **options)['text']
print('RESULTAT=' + json.dumps(dict(identique=temoin == finale,
    mots=len(finale.split()), mesures=mesures)), flush=True)
"""
    resultat = subprocess.run(
        [
            str(runtime),
            "-c",
            script,
            str(racine / "src/diapason/speech/realtime"),
            str(modele),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "HF_HUB_OFFLINE": "1"},
    )
    assert resultat.returncode == 0, resultat.stderr[-1500:]
    ligne = next(s for s in resultat.stdout.splitlines() if s.startswith("RESULTAT="))
    comparaison = json.loads(ligne.removeprefix("RESULTAT="))
    assert comparaison["mesures"][0]["expire"], "le vrai décodeur exerce l'abandon"
    assert comparaison["identique"], "les mots de la finale restent identiques"
    assert comparaison["mots"] > 15, (
        "comparer deux textes vides serait une fausse preuve"
    )
    # Le noyau GPU actif n'est pas interruptible : sa durée dépend de la
    # charge du Mac. Les temps sont rapportés, pas remplacés par une promesse.
    print(json.dumps(comparaison, ensure_ascii=False))
