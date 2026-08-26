"""L'empreinte vocale : n'écouter que la voix du propriétaire.

Ces tests utilisent le VRAI modèle d'empreinte quand il est sur la machine
(40 Mo dans ~/.diapason/models/speaker), et des chemins temporaires pour le
profil — jamais celui du propriétaire : à la première exécution de la suite,
les bancs vocaux avaient enrôlé leur bruit synthétique dans le vrai profil,
et l'assistant serait devenu sourd à son maître.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

# La reconnaissance du locuteur repose sur `sherpa-onnx`, qui vit dans
# l'extra `speech`. Sans lui, ces tests levaient ModuleNotFoundError au lieu
# de se sauter — six échecs à la première exécution de CI, le 26 août 2026.
# (Et cette bibliothèque perd ses dylibs à chaque `uv sync` : voir le
# Makefile, qui la réinstalle explicitement.)
pytest.importorskip("sherpa_onnx", reason="extra `speech` requis")

from diapason.speech.speaker_id import (  # noqa: E402
    ECHANTILLONS_REQUIS,
    SpeakerVerifier,
)

_MODELE = Path.home() / ".diapason/models/speaker/nemo_en_titanet_small.onnx"
_S = Path(
    "/private/tmp/claude-501/-Users-carlito-e-Projets-Diapason/"
    "067c629a-298a-45ce-89d6-5922dcc6e52b/scratchpad"
)

pytestmark = pytest.mark.skipif(
    not _MODELE.exists() or not (_S / "v_Thomas_1.wav").exists(),
    reason="modèle d'empreinte ou échantillons absents",
)


def _pcm(chemin: Path) -> bytes:
    w = wave.open(str(chemin))
    return w.readframes(w.getnframes())


@pytest.fixture()
def verifier(tmp_path):
    return SpeakerVerifier(model_path=_MODELE, profile_path=tmp_path / "profil.npz")


class TestCycleDeVie:
    def test_sans_profil_le_verrou_dort_et_tout_passe(self, verifier):
        """Le doute profite au propriétaire : pas armé = pas de rejet."""
        assert verifier.arme is False
        score, ok = verifier.verify(_pcm(_S / "v_Amelie_1.wav"))
        assert ok is True

    def test_le_verrou_s_arme_au_cinquieme_echantillon(self, verifier):
        sons = ["v_Thomas_1.wav", "v_Thomas_2.wav", "v_Thomas_3.wav"]
        for i in range(ECHANTILLONS_REQUIS):
            assert verifier.enroll(_pcm(_S / sons[i % 3])) is True
        assert verifier.arme is True

    def test_le_profil_survit_a_un_redemarrage(self, tmp_path):
        chemin = tmp_path / "profil.npz"
        v1 = SpeakerVerifier(model_path=_MODELE, profile_path=chemin)
        for _ in range(ECHANTILLONS_REQUIS):
            v1.enroll(_pcm(_S / "v_Thomas_1.wav"))
        v2 = SpeakerVerifier(model_path=_MODELE, profile_path=chemin)
        assert v2.arme is True

    def test_reset_efface_tout(self, verifier):
        for _ in range(ECHANTILLONS_REQUIS):
            verifier.enroll(_pcm(_S / "v_Thomas_1.wav"))
        verifier.reset()
        assert verifier.echantillons == 0


class TestLeVerdict:
    @pytest.fixture()
    def arme_sur_thomas(self, verifier):
        for n in (
            "v_Thomas_1.wav",
            "v_Thomas_2.wav",
            "v_Thomas_3.wav",
            "v_Thomas_1.wav",
            "v_Thomas_2.wav",
        ):
            verifier.enroll(_pcm(_S / n))
        assert verifier.arme
        return verifier

    def test_la_voix_du_proprietaire_passe(self, arme_sur_thomas):
        score, ok = arme_sur_thomas.verify(_pcm(_S / "v_Thomas_3.wav"))
        assert ok is True, f"le propriétaire rejeté (score {score:.2f})"

    def test_une_autre_voix_est_rejetee(self, arme_sur_thomas):
        """Le cœur de la demande : un tiers disant « Diapason » est ignoré."""
        score, ok = arme_sur_thomas.verify(_pcm(_S / "v_Amelie_1.wav"))
        assert ok is False, f"une voix étrangère acceptée (score {score:.2f})"

    def test_un_tour_trop_court_profite_au_proprietaire(self, arme_sur_thomas):
        score, ok = arme_sur_thomas.verify(b"\x00\x00" * 800)  # 50 ms
        assert ok is True, "un fragment inexploitable ne doit pas rendre sourd"
