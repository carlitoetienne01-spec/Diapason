"""L'empreinte vocale du propriétaire — pour ne répondre qu'à LUI.

Demandé le 23 août 2026, après la garde d'adresse : « je veux absolument la
reconnaissance de ma voix. » La garde par le nom filtre le film et le bruit ;
elle ne filtre pas un tiers qui DIT « Diapason ». L'empreinte, si.

Tout est local : le modèle d'empreinte (ONNX, ~40 Mo) tourne sur cette
machine, le profil vit dans ~/.diapason/voice_profile.npz, et rien ne part
nulle part. Mesuré avant d'être retenu : deux voix distinctes se séparent
nettement (même voix 0,65-0,82 de similarité, voix différentes 0,30-0,39,
11 ms par empreinte).

Le profil se prépare explicitement dans Réglages → Voix. Les anciens profils
restent lisibles. Même un mot bref est comparé au profil lorsqu'il contient
assez de son exploitable ; une comparaison incertaine reste signalée sans
imposer une répétition.
Le seuil de comparaison reste inchangé ; aucune confiance de session ne
permet à une autre voix de profiter du tour précédent.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

SEUIL = 0.45
ECHANTILLONS_REQUIS = 5
ECHANTILLONS_MAX = 12
# 27/09/2026 : les refus observés portaient sur 1,70 et 1,88 s. En dessous
# de 2 s, un score insuffisant demande davantage de parole, sans abaisser
# le seuil. Une seconde reste requise pour APPRENDRE une réponse courte.
DUREE_MIN_S = 1.0
DUREE_COURTE_S = 2.0
# 27/09/2026 : la même limite d'une seconde empêchait de VÉRIFIER « oui »
# et « non », avant même de comparer les empreintes. Le banc natif les
# distingue dès 240 ms, au seuil existant. On conserve le plancher de
# 200 ms audibles du contrôle d'énergie ; silence et clics restent exclus.
DUREE_VERIFICATION_MIN_S = 0.2
# Cinq phrases variées et trois réponses courtes : le profil précédent
# n'avait que cinq tours automatiques, sans contrôle de leur provenance.
PHRASES_GUIDEES = 8
DUREE_MAX_S = 8.0


@dataclass(frozen=True)
class VerdictVocal:
    etat: str
    score: float | None = None

    @property
    def reconnu(self) -> bool:
        return self.etat == "recognized"


class ProfilVocalInvalide(ValueError):
    def __init__(self, motif: str, indice: int | None = None) -> None:
        super().__init__(motif)
        self.motif = motif
        self.indice = indice


def mesurer_parole(pcm16: bytes, rate: int = 16000) -> float:
    """Durée entre première et dernière énergie audible, pas durée du silence.

    Ce contrôle de capture n'est pas un détecteur d'identité ni de langage.
    Les empreintes font toujours la vérification d'identité ensuite.
    """
    if rate != 16000 or len(pcm16) % 2 or not pcm16:
        return 0.0
    signal = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768
    taille = rate // 50  # Trames de 20 ms : un clic isolé ne devient pas 1 s.
    signal = signal[: len(signal) // taille * taille]
    if not len(signal):
        return 0.0
    energie = np.sqrt(np.mean(signal.reshape(-1, taille) ** 2, axis=1))
    # -50 dB environ : silence numérique et très faible souffle sont écartés,
    # sans relever le gain du micro ni changer la reconnaissance des mots.
    indices = np.flatnonzero(energie > 0.003)
    if len(indices) < round(DUREE_VERIFICATION_MIN_S * 50):
        return 0.0
    return float((indices[-1] - indices[0] + 1) / 50)


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
    """Empreintes et verdicts locaux ; à appeler hors de la boucle ASGI."""

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
        self._verrou = threading.RLock()
        self._profil: Optional[np.ndarray] = None  # (n, dim), lignes normées
        self._charger_profil()

    # ── infrastructure ────────────────────────────────────────────────────
    def _charger_profil(self) -> None:
        try:
            if self._profile_path.exists():
                with np.load(self._profile_path, allow_pickle=False) as donnees:
                    profil = np.asarray(donnees["embeddings"], dtype=np.float32)
                if (
                    profil.ndim != 2
                    or not 0 < len(profil) <= ECHANTILLONS_MAX
                    or profil.shape[1] == 0
                    or not np.isfinite(profil).all()
                    or not np.allclose(np.linalg.norm(profil, axis=1), 1, atol=0.01)
                ):
                    raise ValueError("empreintes invalides")
                self._profil = profil
        except Exception:  # noqa: BLE001 - un profil corrompu n'accorde aucun droit
            logger.warning("profil vocal illisible", exc_info=True)
            self._profil = None

    @property
    def revision(self) -> str:
        try:
            return hashlib.sha256(self._profile_path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return "absent"

    def _sauver_profil(self, profil: np.ndarray) -> None:
        # 27/09/2026 : annuler ou rater le parcours guidé ne doit jamais
        # détruire l'ancienne voix. Seul un fichier complet remplace le profil.
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        fd, chemin = tempfile.mkstemp(dir=self._profile_path.parent, suffix=".npz")
        try:
            with os.fdopen(fd, "wb") as fichier:
                np.savez(fichier, embeddings=profil)
                fichier.flush()
                os.fsync(fichier.fileno())
            os.replace(chemin, self._profile_path)
            self._profil = profil
        finally:
            Path(chemin).unlink(missing_ok=True)

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
        """Sans modèle disponible, aucun verdict positif ne peut être rendu."""
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
        if (
            rate != 16000
            or len(pcm16) % 2
            or len(pcm16) < int(DUREE_VERIFICATION_MIN_S * rate) * 2
        ):
            return None
        try:
            ex = self._assurer_extracteur()
            if ex is None:
                return None
            sig = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
            st = ex.create_stream()
            st.accept_waveform(rate, sig)
            st.input_finished()
            v = np.asarray(ex.compute(st), dtype=np.float32)
            n = float(np.linalg.norm(v))
            return v / n if n > 0 and np.isfinite(v).all() else None
        except Exception:  # noqa: BLE001 - une empreinte ratée n'arrête rien
            logger.debug("empreinte impossible", exc_info=True)
            return None

    # ── le cycle de vie du profil ─────────────────────────────────────────
    @property
    def echantillons(self) -> int:
        return 0 if self._profil is None else int(self._profil.shape[0])

    @property
    def arme(self) -> bool:
        """Le profil contient au moins cinq empreintes."""
        return self.echantillons >= ECHANTILLONS_REQUIS

    def enroll(self, pcm16: bytes, rate: int = 16000) -> bool:
        """Compatibilité pour les bancs ; le dialogue ne s'enrôle plus tout seul."""
        if mesurer_parole(pcm16, rate) < DUREE_MIN_S:
            return False
        v = self.embed(pcm16, rate)
        if v is None:
            return False
        with self._verrou:
            if self.echantillons >= ECHANTILLONS_MAX:
                return False
            profil = (
                v[None, :] if self._profil is None else np.vstack([self._profil, v])
            )
            self._sauver_profil(profil)
        return True

    def evaluer(self, pcm16: bytes, rate: int = 16000) -> VerdictVocal:
        with self._verrou:
            profil = self._profil
        if profil is None or len(profil) < ECHANTILLONS_REQUIS:
            return VerdictVocal("profileMissing")
        duree = mesurer_parole(pcm16, rate)
        if duree < DUREE_VERIFICATION_MIN_S:
            return VerdictVocal("insufficientAudio")
        v = self.embed(pcm16, rate)
        if v is None or v.shape != profil.shape[1:]:
            return VerdictVocal("unavailable")
        score = float(np.max(profil @ v))
        if score >= self._seuil:
            return VerdictVocal("recognized", score)
        return VerdictVocal(
            "insufficientAudio" if duree < DUREE_COURTE_S else "notRecognized", score
        )

    def verify(self, pcm16: bytes, rate: int = 16000) -> tuple[float, bool]:
        verdict = self.evaluer(pcm16, rate)
        return verdict.score or 0.0, verdict.reconnu

    def preparer_echantillon(self, pcm16: bytes, indice: int) -> np.ndarray:
        if not 0 <= indice < PHRASES_GUIDEES or len(pcm16) > 16000 * 2 * DUREE_MAX_S:
            raise ProfilVocalInvalide("invalidSample", indice)
        duree = mesurer_parole(pcm16)
        if duree == 0:
            raise ProfilVocalInvalide("tooQuiet", indice)
        if duree < (DUREE_COURTE_S if indice < ECHANTILLONS_REQUIS else DUREE_MIN_S):
            raise ProfilVocalInvalide("tooShort", indice)
        signal = np.frombuffer(pcm16, dtype="<i2").astype(np.float32)
        if np.mean(np.abs(signal) >= 32700) > 0.01:
            # Plus de 1 % de sommets écrêtés : réenregistrer à moindre volume.
            raise ProfilVocalInvalide("clipped", indice)
        v = self.embed(pcm16)
        if v is None:
            raise ProfilVocalInvalide("unavailable", indice)
        return v

    def remplacer_guide(self, echantillons: list[bytes], revision: str) -> None:
        if len(echantillons) != PHRASES_GUIDEES:
            raise ProfilVocalInvalide("incomplete")
        empreintes = [
            self.preparer_echantillon(pcm, i) for i, pcm in enumerate(echantillons)
        ]
        profil = np.stack(empreintes)
        # Les cinq phrases longues doivent être cohérentes entre elles :
        # une première capture étrangère ne doit pas devenir l'ancre du profil.
        scores = profil @ profil.T
        for i in range(ECHANTILLONS_REQUIS):
            voisins = np.delete(scores[i, :ECHANTILLONS_REQUIS], i)
            if np.count_nonzero(voisins >= self._seuil) < 3:
                raise ProfilVocalInvalide("differentVoice", i)
        for i in range(ECHANTILLONS_REQUIS, PHRASES_GUIDEES):
            if np.max(scores[i, :ECHANTILLONS_REQUIS]) < self._seuil:
                raise ProfilVocalInvalide("differentVoice", i)
        with self._verrou:
            if self.revision != revision:
                raise ProfilVocalInvalide("conflict")
            self._sauver_profil(profil)

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
