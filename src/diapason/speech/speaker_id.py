"""L'empreinte vocale du propriétaire — pour ne répondre qu'à LUI.

Demandé le 23 août 2026, après la garde d'adresse : « je veux absolument la
reconnaissance de ma voix. » La garde par le nom filtre le film et le bruit ;
elle ne filtre pas un tiers qui DIT « Diapason ». L'empreinte, si.

Tout est local : le modèle d'empreinte (ONNX, ~40 Mo) tourne sur cette
machine, le profil vit dans ~/.diapason/voice_profile.npz, et rien ne part
nulle part. Mesuré avant d'être retenu : deux voix distinctes se séparent
nettement (même voix 0,65-0,82 de similarité, voix différentes 0,30-0,39,
11 ms par empreinte).

L'ENRÔLEMENT est silencieux : les premiers tours ADRESSÉS d'une session — le
nom prononcé, ou la fenêtre d'engagement — nourrissent le profil. Au
cinquième, le verrou s'arme. Pas de cérémonie : la voix qui dit « Diapason »
est celle du propriétaire. ``diapason voice reset`` efface et réapprend.

Le seuil (0,45) penche vers ACCEPTER le propriétaire : un faux rejet rend
l'assistant sourd à son maître — pire que l'état d'avant. La comparaison
prend le MAXIMUM contre chaque échantillon enrôlé, plus robuste qu'un seul
centroïde quand la voix varie (matin, rhume, distance du micro).
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

SEUIL = 0.45
ECHANTILLONS_REQUIS = 5
ECHANTILLONS_MAX = 12
# Sous une seconde de parole, l'empreinte est du bruit.
DUREE_MIN_S = 1.0

_MODELE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/nemo_en_titanet_small.onnx"
)


def _chemin_modele() -> Path:
    from diapason.core.paths import get_config_dir

    return get_config_dir() / "models" / "speaker" / "nemo_en_titanet_small.onnx"


def _chemin_profil() -> Path:
    from diapason.core.paths import get_config_dir

    return get_config_dir() / "voice_profile.npz"


class SpeakerVerifier:
    """Empreintes et verdicts. Paresseux, verrouillé, jamais bloquant."""

    def __init__(
        self,
        *,
        model_path: Path | None = None,
        profile_path: Path | None = None,
        seuil: float = SEUIL,
    ) -> None:
        self._model_path = model_path or _chemin_modele()
        self._profile_path = profile_path or _chemin_profil()
        self._seuil = seuil
        self._extracteur = None
        self._verrou = threading.Lock()
        self._profil: Optional[np.ndarray] = None  # (n, dim), lignes normées
        self._charger_profil()

    # ── infrastructure ────────────────────────────────────────────────────
    def _charger_profil(self) -> None:
        try:
            if self._profile_path.exists():
                donnees = np.load(self._profile_path)
                self._profil = np.asarray(donnees["embeddings"], dtype=np.float32)
        except Exception:  # noqa: BLE001 - un profil corrompu = pas de profil
            logger.warning("profil vocal illisible — reparti de zéro", exc_info=True)
            self._profil = None

    def _sauver_profil(self) -> None:
        try:
            self._profile_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(self._profile_path, embeddings=self._profil)
        except Exception:  # noqa: BLE001
            logger.warning("profil vocal non sauvé", exc_info=True)

    def _assurer_extracteur(self):
        if self._extracteur is not None:
            return self._extracteur
        with self._verrou:
            if self._extracteur is not None:
                return self._extracteur
            if not self._model_path.exists():
                self._telecharger_modele()
            if not self._model_path.exists():
                return None
            import sherpa_onnx

            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self._model_path), num_threads=2
            )
            self._extracteur = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            return self._extracteur

    def _telecharger_modele(self) -> None:
        """Best-effort : sans modèle, le verrou reste simplement inactif."""
        try:
            self._model_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("téléchargement du modèle d'empreinte vocale (~40 Mo)…")
            tmp = self._model_path.with_suffix(".part")
            urllib.request.urlretrieve(_MODELE_URL, tmp)  # noqa: S310 - URL fixe
            tmp.rename(self._model_path)
        except Exception:  # noqa: BLE001
            logger.warning("modèle d'empreinte indisponible", exc_info=True)

    # ── l'empreinte ───────────────────────────────────────────────────────
    def embed(self, pcm16: bytes, rate: int = 16000) -> Optional[np.ndarray]:
        if len(pcm16) < int(DUREE_MIN_S * rate) * 2:
            return None
        ex = self._assurer_extracteur()
        if ex is None:
            return None
        try:
            sig = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
            st = ex.create_stream()
            st.accept_waveform(rate, sig)
            st.input_finished()
            v = np.asarray(ex.compute(st), dtype=np.float32)
            n = float(np.linalg.norm(v))
            return v / n if n > 0 else None
        except Exception:  # noqa: BLE001 - une empreinte ratée n'arrête rien
            logger.debug("empreinte impossible", exc_info=True)
            return None

    # ── le cycle de vie du profil ─────────────────────────────────────────
    @property
    def echantillons(self) -> int:
        return 0 if self._profil is None else int(self._profil.shape[0])

    @property
    def arme(self) -> bool:
        """Le verrou n'agit qu'une fois le profil suffisamment nourri."""
        return self.echantillons >= ECHANTILLONS_REQUIS

    def enroll(self, pcm16: bytes, rate: int = 16000) -> bool:
        v = self.embed(pcm16, rate)
        if v is None:
            return False
        with self._verrou:
            if self._profil is None:
                self._profil = v[None, :]
            elif self._profil.shape[0] < ECHANTILLONS_MAX:
                self._profil = np.vstack([self._profil, v])
            else:
                return False
            self._sauver_profil()
        return True

    def verify(self, pcm16: bytes, rate: int = 16000) -> tuple[float, bool]:
        """(score, est-le-propriétaire). Sans profil armé : (1.0, True).

        Le doute — extraction impossible, tour trop court — profite au
        PROPRIÉTAIRE : un faux rejet rend l'assistant sourd à son maître.
        """
        if not self.arme:
            return 1.0, True
        v = self.embed(pcm16, rate)
        if v is None or self._profil is None:
            return 1.0, True
        score = float(np.max(self._profil @ v))
        return score, score >= self._seuil

    def reset(self) -> None:
        with self._verrou:
            self._profil = None
            try:
                self._profile_path.unlink(missing_ok=True)
            except OSError:
                pass


_partage: Optional[SpeakerVerifier] = None
_partage_verrou = threading.Lock()


def get_verifier() -> SpeakerVerifier:
    global _partage
    if _partage is None:
        with _partage_verrou:
            if _partage is None:
                _partage = SpeakerVerifier()
    return _partage


__all__ = [
    "DUREE_MIN_S",
    "ECHANTILLONS_MAX",
    "ECHANTILLONS_REQUIS",
    "SEUIL",
    "SpeakerVerifier",
    "get_verifier",
]
