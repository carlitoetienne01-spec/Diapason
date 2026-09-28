"""§100 — banc opt-in du vrai moteur, sans micro, lecture ni téléchargement."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.live
def test_le_flux_orion_preserve_le_son_court_et_long():
    racine = Path(__file__).resolve().parents[2]
    runtime = Path.home() / ".diapason/voices/qwen3/runtime/bin/python"
    modele = Path.home() / ".diapason/voices/qwen3/model"
    if not runtime.is_file() or not modele.is_dir():
        pytest.skip("Le moteur Orion local n'est pas installé")
    script = r"""
import json, sys, time
from pathlib import Path
import mlx.core as mx
import numpy as np
from mlx_audio.tts.utils import load_model
sys.path.insert(0, sys.argv[1])
import ouvrier_voix as ouvrier
from synthese_orion import generer
mx.set_cache_limit(ouvrier.CACHE_MAX_OCTETS)
modele = load_model(sys.argv[2])
ouvrier.borner_intermediaires(modele)
reference = str(Path(ouvrier.__file__).parent / "voix" / ouvrier.REFERENCES["qwen3-b"])
ouvrier.synthetiser(modele, "qwen3-b", "Bonjour.")
textes = [
    "Oui, prends ton temps.",
    "Tu peux écouter cinq minutes, puis répéter une phrase qui te plaît.",
    "Pour apprendre l'anglais régulièrement sans te décourager, commence par "
    "écouter un court dialogue adapté à ton niveau, choisis ensuite quelques "
    "expressions utiles que tu répètes à voix haute en respectant les pauses "
    "et les accents, puis réutilise ces expressions dans une petite histoire "
    "personnelle que tu raconteras le lendemain en essayant de te souvenir "
    "des mots sans regarder tes notes, avant de comparer ta version avec le "
    "dialogue original pour repérer les progrès et les points à retravailler "
    "tranquillement.",
]
resultats = []
for texte in textes:
    attendu = ouvrier.synthetiser(modele, "qwen3-b", texte)
    debut = time.monotonic()
    morceaux, arrivages = [], []
    for morceau in generer(modele, texte, reference, ouvrier.TEXTE_REFERENCE):
        morceaux.append(morceau)
        arrivages.append(time.monotonic() - debut)
    obtenu = b"".join(morceaux)
    fin_lecture, trous = arrivages[0], []
    for arrivee, morceau in zip(arrivages, morceaux):
        if arrivee > fin_lecture:
            trous.append(arrivee - fin_lecture)
        fin_lecture = max(fin_lecture, arrivee) + len(morceau)/48000
    a = np.frombuffer(attendu, dtype="<i2").astype("int32")
    b = np.frombuffer(obtenu, dtype="<i2").astype("int32")
    resultats.append({
        "longueurEgale": len(a) == len(b),
        "ecartMax": int(np.abs(a-b).max()) if len(a) == len(b) else None,
        "identique": attendu == obtenu,
        "audioS": len(a)/24000,
        "premierS": arrivages[0],
        "totalS": arrivages[-1],
        "trousS": trous,
    })
# Une phrase arrêtée après le premier son doit libérer ses buffers ;
# seule la référence fixe peut survivre au tour suivant.
interrompu = generer(modele, textes[-1], reference, ouvrier.TEXTE_REFERENCE)
next(interrompu)
interrompu.close()
apres_arret = b"".join(generer(modele, textes[1], reference, ouvrier.TEXTE_REFERENCE))
attendu = ouvrier.synthetiser(modele, "qwen3-b", textes[1])
assert apres_arret == attendu, "une phrase interrompue contamine le timbre suivant"
print("RESULTAT=" + json.dumps(resultats), flush=True)
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
        timeout=180,
        env={**os.environ, "HF_HUB_OFFLINE": "1"},
    )
    assert resultat.returncode == 0, resultat.stderr[-1500:]
    ligne = next(s for s in resultat.stdout.splitlines() if s.startswith("RESULTAT="))
    comparaisons = json.loads(ligne.removeprefix("RESULTAT="))
    assert all(c["longueurEgale"] for c in comparaisons), "ni mot ni échantillon perdu"
    assert all(c["identique"] for c in comparaisons[:2]), "PCM court inchangé"
    # Au passage d'un bloc natif de 300 codes, les produits matriciels sur
    # des tailles différentes arrondissent jusqu'à deux niveaux PCM16 :
    # 2/32767, mesurés le 27/09/2026. Ce n'est pas une tolérance au timbre.
    assert comparaisons[-1]["ecartMax"] <= 2, "le contexte complet du timbre est gardé"
    print(json.dumps(comparaisons, ensure_ascii=False))
