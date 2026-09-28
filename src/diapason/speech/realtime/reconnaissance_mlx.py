"""Reconnaissance locale sur Metal, isolée des dépendances du serveur."""

from __future__ import annotations

import atexit
import base64
import json
import os
import platform
import select
import subprocess
import threading
import time
from pathlib import Path

from diapason.core.paths import get_config_dir
from diapason.speech.faster_whisper import est_hallucination


def dossier_moteur() -> Path:
    return get_config_dir() / "speech" / "whisper-mlx"


def moteur_installe() -> bool:
    racine = dossier_moteur()
    return (
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and all(
            (racine / p).is_file()
            for p in (
                "runtime/bin/python",
                "model/config.json",
                "model/weights.safetensors",
                "installed.json",
            )
        )
    )


def parole_seule(pcm: bytes) -> bytes:
    """Même filtre Silero et marge de mots que l'oreille CTranslate2."""
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if len(pcm) % 2:
        raise ValueError("PCM vocal incomplet")
    audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    if not len(audio):
        return b""
    segments = get_speech_timestamps(
        audio,
        VadOptions(
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=160,
            speech_pad_ms=400,
        ),
    )
    if not segments:
        return b""
    return (
        np.concatenate([audio[s["start"] : s["end"]] for s in segments])
        .astype("<f4")
        .tobytes()
    )


class ReconnaissanceMLX:
    """Un modèle partagé ; aucun son ne quitte les tubes locaux."""

    def __init__(self, langue: str = "") -> None:
        self.langue = langue if langue and langue != "auto" else None
        self._processus: subprocess.Popen | None = None
        self._verrou = threading.Lock()
        self._recu = bytearray()
        atexit.register(self.fermer)

    def _lire(self) -> dict:
        assert self._processus is not None and self._processus.stdout is not None
        # 90 s tolèrent le premier chargement ; une panne ferme l'ouvrier,
        # jamais une lecture ancienne recyclée en transcription du tour suivant.
        fin = time.monotonic() + 90
        fd = self._processus.stdout.fileno()
        while b"\n" not in self._recu:
            reste = fin - time.monotonic()
            if reste <= 0 or not select.select([fd], [], [], reste)[0]:
                raise TimeoutError("La reconnaissance locale ne répond pas.")
            bloc = os.read(fd, 65536)
            if not bloc:
                raise RuntimeError("La reconnaissance locale s’est arrêtée.")
            self._recu.extend(bloc)
            if len(self._recu) > 1024 * 1024:
                raise ValueError("Transcription locale trop volumineuse")
        ligne, _, suite = self._recu.partition(b"\n")
        self._recu = bytearray(suite)
        resultat = json.loads(ligne)
        if not isinstance(resultat, dict) or resultat.get("type") == "error":
            raise RuntimeError("La reconnaissance locale a échoué.")
        return resultat

    def _arreter(self) -> None:
        processus, self._processus = self._processus, None
        self._recu.clear()
        if processus is None:
            return
        if processus.poll() is None:
            processus.kill()
        processus.wait()
        for tube in (processus.stdin, processus.stdout):
            if tube is not None:
                tube.close()

    def fermer(self) -> None:
        with self._verrou:
            self._arreter()

    def _demarrer(self) -> None:
        if self._processus is not None and self._processus.poll() is None:
            return
        self._arreter()
        if not moteur_installe():
            raise RuntimeError("Le moteur de reconnaissance MLX n’est pas installé.")
        racine = dossier_moteur()
        self._processus = subprocess.Popen(
            [
                str(racine / "runtime/bin/python"),
                "-u",
                str(Path(__file__).with_name("ouvrier_reconnaissance.py")),
                str(racine / "model"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={
                **os.environ,
                "HF_HUB_OFFLINE": "1",
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            },
        )
        if self._lire().get("type") != "ready":
            raise RuntimeError("Le moteur de reconnaissance n’est pas prêt.")

    def preload(self) -> None:
        with self._verrou:
            try:
                self._demarrer()
            except BaseException:
                self._arreter()
                raise

    def transcrire(self, pcm: bytes, *, provisoire: bool = False) -> str:
        audio = parole_seule(pcm)
        if not audio:
            return ""
        with self._verrou:
            try:
                self._demarrer()
                assert self._processus is not None and self._processus.stdin is not None
                trame = {
                    "audio": base64.b64encode(audio).decode(),
                    "language": self.langue,
                    "partial": provisoire,
                }
                self._processus.stdin.write((json.dumps(trame) + "\n").encode())
                self._processus.stdin.flush()
                resultat = self._lire()
                if resultat.get("type") != "transcript":
                    raise ValueError("Trame de reconnaissance inattendue")
                segments = resultat["segments"]
                if not isinstance(segments, list) or any(
                    not isinstance(s, dict) or not isinstance(s.get("text"), str)
                    for s in segments
                ):
                    raise ValueError("Segments de reconnaissance invalides")
                return "".join(
                    s["text"]
                    for s in segments
                    if not est_hallucination(s.get("noSpeechProb"), s.get("avgLogprob"))
                ).strip()
            except BaseException:
                self._arreter()
                raise
