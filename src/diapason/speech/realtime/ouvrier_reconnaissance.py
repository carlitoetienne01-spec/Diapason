"""Ouvrier privé Whisper MLX : aucun micro, aucun téléchargement implicite."""

from __future__ import annotations

import base64
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# 27/09/2026 : un brouillon de 0,8 s gardait le décodeur 8,16 s, malgré
# sa limite de jetons. Une seconde couvre les brouillons chauds usuels
# (~0,6 s) ; au-delà on laisse la place à la phrase entière. Ce budget
# coopératif ne peut pas interrompre un noyau Metal déjà lancé.
BUDGET_BROUILLON_S = 1.0
_INVITE_MAX = 240


def options_de_requete(requete: dict, *, provisoire: bool, limite: int) -> dict:
    """Options Whisper. L'amorce kreyòl passe, une chaîne trop longue non."""
    options = {"temperature": 0.0, "sample_len": limite} if provisoire else {}
    invite = requete.get("prompt")
    if isinstance(invite, str):
        invite = invite.strip()
        if invite and len(invite) <= _INVITE_MAX:
            options["initial_prompt"] = invite
    return options


class BrouillonTropLent(Exception):
    """Abandon sans erreur utilisateur d'un sous-titre devenu trop coûteux."""


@contextmanager
def borner_brouillon(provisoire: bool):
    if not provisoire:
        yield
        return

    from mlx_whisper.decoding import Inference

    fin = time.monotonic() + BUDGET_BROUILLON_S
    original = Inference.logits

    def verifier():
        if time.monotonic() >= fin:
            raise BrouillonTropLent

    def logits(instance, *args, **kwargs):
        verifier()
        return original(instance, *args, **kwargs)

    # Cet ouvrier privé ne traite qu'une requête à la fois. La substitution
    # est bornée au brouillon ; la finale retrouve la méthode native, même
    # si le brouillon expire ou que le moteur lève une autre erreur.
    Inference.logits = logits
    try:
        yield
        verifier()
    finally:
        Inference.logits = original


def principal() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    modele = Path(sys.argv[1])
    if not (modele / "weights.safetensors").is_file():
        raise ValueError("Poids locaux absents")
    sortie = sys.stdout
    sys.stdout = sys.stderr
    import mlx.core as mx
    import numpy as np
    from mlx_whisper.transcribe import ModelHolder, transcribe

    # Même borne des buffers libres que la voix : 256 Mio ; pas de limite
    # sur les poids actifs ni sur la précision du décodage.
    mx.set_cache_limit(256 * 1024 * 1024)
    ModelHolder.get_model(str(modele), mx.float16)
    # 27/09/2026 : READY annonçait les poids chargés, mais le premier
    # partiel payait encore 5,7 s de préparation contre ~0,6 s ensuite.
    # Compiler encodeur/décodeur avant d'écouter, sur du silence synthétique.
    # Un seul jeton suffit à chauffer ; ces options ne servent PAS à la parole.
    transcribe(
        np.zeros(16000, dtype=np.float32),
        path_or_hf_repo=str(modele),
        language="fr",
        temperature=0.0,
        sample_len=1,
        condition_on_previous_text=False,
        verbose=None,
    )

    def emettre(trame: dict) -> None:
        sortie.write(json.dumps(trame) + "\n")
        sortie.flush()

    emettre({"type": "ready"})
    for ligne in sys.stdin:
        try:
            requete = json.loads(ligne)
            audio = np.frombuffer(
                base64.b64decode(requete["audio"], validate=True), dtype="<f4"
            )
            if not len(audio) or not np.isfinite(audio).all():
                raise ValueError("Son invalide")
            # 27/09/2026 : 0,82 s de son incomplet occupaient Metal 15,7 s
            # au détriment de la finale. Un brouillon n'a pas à explorer les
            # six températures. 16 jetons/s + 16 de marge couvrent largement
            # la parole usuelle ; si cette borne est atteinte, on ne montre
            # RIEN et on ne déclare surtout pas la phrase complète.
            provisoire = requete.get("partial") is True
            limite = min(448, 16 + math.ceil(len(audio) / 16000 * 16))
            options = options_de_requete(requete, provisoire=provisoire, limite=limite)
            try:
                with borner_brouillon(provisoire):
                    resultat = transcribe(
                        audio,
                        path_or_hf_repo=str(modele),
                        language=requete.get("language"),
                        condition_on_previous_text=False,
                        verbose=None,
                        **options,
                    )
            except BrouillonTropLent:
                # Finir les noyaux déjà soumis avant d'accepter la finale :
                # abandonner le Python ne doit pas laisser un calcul GPU
                # caché en concurrence avec le prochain tour.
                mx.synchronize()
                emettre({"type": "transcript", "segments": []})
                continue
            segments = resultat.get("segments", [])
            if provisoire and (
                any(len(s.get("tokens", [])) >= limite for s in segments)
                or any(
                    s.get("avg_logprob", -2) < -1
                    or s.get("no_speech_prob", 1) > 0.6
                    or s.get("compression_ratio", 0) > 2.4
                    for s in segments
                )
            ):
                segments = []
            emettre(
                {
                    "type": "transcript",
                    "segments": [
                        {
                            "text": s["text"],
                            "noSpeechProb": s.get("no_speech_prob"),
                            "avgLogprob": s.get("avg_logprob"),
                        }
                        for s in segments
                    ],
                }
            )
        except Exception:
            # Ni texte reconnu ni son du micro dans les journaux.
            emettre({"type": "error"})


if __name__ == "__main__":
    principal()
