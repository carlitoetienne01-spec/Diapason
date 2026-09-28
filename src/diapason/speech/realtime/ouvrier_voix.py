"""Exécutable privé du venv MLX : texte → morceaux PCM, jamais d'accès au micro."""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

TEXTE_REFERENCE = (
    "On peut y aller tranquillement. Dis-moi ce que tu veux apprendre aujourd'hui, "
    "et on choisira ensemble un exercice simple."
)
REFERENCES = {"qwen3-b": "voix-posee-v2.wav"}
# 480 ms à 24 kHz mono PCM16 : on garde les mêmes trames de transport
# (23 040 octets), même quand le décodeur rend une phrase entière.
OCTETS_PAR_MORCEAU = 23040
# 27/09/2026 : le cache MLX pouvait garder 8,48 Go de buffers LIBRES et
# pousser le total à 11,31 Go pendant une phrase. 256 Mio le ramènent à
# environ 384 Mo (reprise à l'allocation suivante), total 6,90 Go. Sur
# quatre rendus comparés, PCM identique ; 5,55–5,98 s au lieu de 6,90–8,22.
# Cette borne ne limite ni les poids actifs ni le contexte du modèle.
CACHE_MAX_OCTETS = 256 * 1024 * 1024


def borner_intermediaires(modele) -> None:
    """Matérialiser les couches sans fragmenter le contexte audio décodé."""
    import mlx.core as mx
    import mlx.nn as nn

    class CoucheEvaluee(nn.Module):
        def __init__(self, couche):
            super().__init__()
            self.couche = couche

        def __call__(self, entree):
            sortie = self.couche(entree)
            mx.eval(sortie)
            return sortie

    # 27/09/2026 : évaluer tout le graphe gardait 1,17–1,40 Go de plus
    # au pic. Sur quatre phrases, huit comparaisons donnent le même PCM.
    # Le gain porte sur la mémoire ; le banc isolé est légèrement plus lent.
    # MLX Audio 0.5.6 (version de l'installeur) enveloppe le décodeur
    # dans mx.compile, mais garde
    # chunked_decode lié au module natif. On conserve ses blocs et toute
    # la référence ; seul l'instant d'évaluation des couches change.
    decodeur = modele.speech_tokenizer.decoder.chunked_decode.__self__
    decodeur.decoder = [CoucheEvaluee(couche) for couche in decodeur.decoder]


def synthetiser(modele, voix: str, texte: str) -> bytes:
    """Une référence fixe, un décodage complet ; aucun son partiel sur erreur."""
    import mlx.core as mx
    import numpy as np

    reference = Path(__file__).parent / "voix" / REFERENCES[voix]
    mx.random.seed(84)
    audio = []
    # 27/09/2026 : MLX Audio 0.5.6 amorce son décodeur complet avec les
    # codes de la référence, contrairement à streaming_step. Sur six
    # rendus A/B, la similarité au timbre de référence monte dans les six
    # cas, à durée identique. La phrase est déjà tamponnée côté serveur :
    # décoder par paquets n'apportait donc plus de première syllabe rapide.
    # Température inchangée : stabiliser le décodage ne fige pas la prosodie.
    for morceau in modele.generate(
        text=texte,
        ref_audio=str(reference),
        ref_text=TEXTE_REFERENCE,
        lang_code="French",
        stream=False,
        temperature=0.6,
        max_tokens=900,
        verbose=False,
    ):
        mx.eval(morceau.audio)
        if morceau.sample_rate != 24000 or morceau.token_count >= 900:
            raise ValueError("Synthèse incomplète ou fréquence inattendue")
        valeurs = np.asarray(morceau.audio).reshape(-1)
        if not np.isfinite(valeurs).all():
            raise ValueError("Audio non fini")
        audio.append((np.clip(valeurs, -1, 1) * 32767).astype("<i2").tobytes())
    pcm = b"".join(audio)
    if not pcm:
        raise ValueError("Synthèse vide")
    return pcm


def generer_morceaux(modele, voix: str, texte: str, mesures=None):
    # L'ouvrier est lancé par chemin dans son venv privé, sans importer
    # le serveur ni ses dépendances dans le processus MLX.
    from synthese_orion import generer

    yield from generer(
        modele,
        texte,
        str(Path(__file__).parent / "voix" / REFERENCES[voix]),
        TEXTE_REFERENCE,
        mesures,
    )


def principal() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    sortie = sys.stdout
    # Les messages des dépendances ne sont pas des trames audio.
    sys.stdout = sys.stderr
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model

    mx.set_cache_limit(CACHE_MAX_OCTETS)

    def emettre(trame: dict) -> None:
        sortie.write(json.dumps(trame) + "\n")
        sortie.flush()

    modele = load_model(sys.argv[1])
    borner_intermediaires(modele)
    emettre({"type": "ready"})
    for ligne in sys.stdin:
        try:
            requete = json.loads(ligne)
            if requete.get("type") == "ping":
                emettre({"type": "ready"})
                continue
            voix, texte = requete["voice"], requete["text"]
            if (
                voix not in REFERENCES
                or not isinstance(texte, str)
                or not 0 < len(texte) <= 4000
            ):
                raise ValueError("Requête vocale invalide")
            mesures = {}
            premier = True
            for pcm in generer_morceaux(modele, voix, texte, mesures):
                for debut in range(0, len(pcm), OCTETS_PAR_MORCEAU):
                    emettre(
                        {
                            "type": "audio",
                            "sampleRate": 24000,
                            "timing": mesures if premier else {},
                            "data": base64.b64encode(
                                pcm[debut : debut + OCTETS_PAR_MORCEAU]
                            ).decode("ascii"),
                        }
                    )
                    premier = False
            emettre({"type": "done"})
        except Exception:
            emettre({"type": "error"})


if __name__ == "__main__":
    principal()
