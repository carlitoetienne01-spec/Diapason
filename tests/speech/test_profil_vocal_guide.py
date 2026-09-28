"""§78/§100 : aucun enregistrement implicite ni identité inventée (27/09/2026)."""

from unittest.mock import Mock

import numpy as np
import pytest

from diapason.speech.speaker_id import (
    ProfilVocalInvalide,
    SpeakerVerifier,
    mesurer_parole,
)


def son(duree=3.0, amplitude=4000):
    return (
        (np.sin(np.arange(int(duree * 16000)) * 0.08) * amplitude)
        .astype("<i2")
        .tobytes()
    )


@pytest.fixture()
def verificateur(tmp_path, monkeypatch):
    v = SpeakerVerifier(profile_path=tmp_path / "profil.npz")
    monkeypatch.setattr(
        v, "embed", Mock(return_value=np.array([1.0, 0.0], dtype=np.float32))
    )
    return v


class TestProfilGuide:
    def test_aucune_capture_ne_remplace_le_profil_avant_la_confirmation(
        self, verificateur
    ):
        """§78 : préparer une capture ne l'enrôle pas."""
        verificateur.preparer_echantillon(son(), 0)
        assert not verificateur.arme, "pas de profil avant confirmation"
        assert not verificateur._profile_path.exists(), "aucun fichier créé"
        assert verificateur.evaluer(son()).etat == "profileMissing", (
            "pas de passe-droit sans profil"
        )

    def test_un_profil_complet_est_durable_et_reconnait_un_essai(self, verificateur):
        """§100 : la confirmation vient du fichier effectivement écrit."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        relu = SpeakerVerifier(profile_path=verificateur._profile_path)
        assert relu.echantillons == 8, "les huit empreintes sont conservées"
        assert verificateur.evaluer(son(1.5)).reconnu, (
            "phrase courte avec score suffisant acceptée"
        )
        assert verificateur._profile_path.stat().st_mode & 0o077 == 0, (
            "empreinte privée"
        )
        with np.load(verificateur._profile_path) as donnees:
            assert donnees.files == ["embeddings"], "aucun audio brut conservé"

    @pytest.mark.parametrize("indice", [0, 3, 7])
    def test_une_autre_voix_ne_contamine_pas_le_profil(self, verificateur, indice):
        """§100 : incohérence entre captures, ancien profil intact."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        precedent = verificateur._profile_path.read_bytes()
        voix = [np.array([1.0, 0.0], dtype=np.float32) for _ in range(8)]
        voix[indice] = np.array([0.0, 1.0], dtype=np.float32)
        verificateur.embed.side_effect = voix
        with pytest.raises(ProfilVocalInvalide, match="differentVoice"):
            verificateur.remplacer_guide([son()] * 8, verificateur.revision)
        assert verificateur._profile_path.read_bytes() == precedent, (
            "ancien profil conservé"
        )

    def test_un_echec_disque_conserve_aussi_le_profil_en_memoire(
        self, verificateur, monkeypatch
    ):
        """§100 : un échec d'écriture ne s'annonce jamais enregistré."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        revision = verificateur.revision
        profil = verificateur._profil.copy()
        monkeypatch.setattr(
            "diapason.speech.speaker_id.os.replace", Mock(side_effect=OSError())
        )
        with pytest.raises(OSError):
            verificateur.remplacer_guide([son()] * 8, revision)
        assert verificateur.revision == revision, "ancien fichier conservé"
        assert np.array_equal(verificateur._profil, profil), (
            "ancienne mémoire conservée"
        )
        assert len(list(verificateur._profile_path.parent.iterdir())) == 1, (
            "temporaire effacé"
        )

    def test_deux_fenetres_ne_se_remplacent_pas_silencieusement(self, verificateur):
        """§100 : une révision ancienne exige une nouvelle confirmation."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        with pytest.raises(ProfilVocalInvalide, match="conflict"):
            verificateur.remplacer_guide([son()] * 8, "absent")

    @pytest.mark.parametrize(
        ("pcm", "indice", "motif"),
        [
            (son(0.4), 6, "tooShort"),
            (son(1.5), 0, "tooShort"),
            (b"\0" * 160000, 0, "tooQuiet"),
            (son(9), 0, "invalidSample"),
            (b"x" * 32001, 0, "tooQuiet"),
            (b"\xff\x7f" * 48000, 0, "clipped"),
        ],
    )
    def test_une_capture_inexploitable_ne_nourrit_pas_le_profil(
        self, verificateur, pcm, indice, motif
    ):
        """§78 : silence, saturation et formats invalides ne deviennent pas une voix."""
        with pytest.raises(ProfilVocalInvalide, match=motif):
            verificateur.preparer_echantillon(pcm, indice)
        assert verificateur.echantillons == 0, "rien enregistré"


class TestDouteVocal:
    def test_un_mot_court_atteint_le_moteur_sans_etre_allonge(
        self, tmp_path, monkeypatch
    ):
        """§100 : comparer le vrai son, pas répéter un phonème pour dépasser 1 s."""
        v = SpeakerVerifier(profile_path=tmp_path / "profil.npz")
        ex = Mock()
        ex.compute.return_value = [1.0, 0.0]
        monkeypatch.setattr(v, "_assurer_extracteur", lambda: ex)
        pcm = son(0.24)
        empreinte = v.embed(pcm)
        assert empreinte is not None, "le quart de seconde ne doit plus être écarté"
        rate, signal = ex.create_stream.return_value.accept_waveform.call_args.args
        assert rate == 16000, "fréquence native conservée"
        assert np.array_equal(signal, np.frombuffer(pcm, dtype="<i2") / 32768), (
            "aucun remplissage, répétition ou modification des mots"
        )

    @pytest.mark.parametrize(
        ("duree", "score", "etat"),
        [
            (0.18, 1.0, "insufficientAudio"),
            (0.24, 0.57, "recognized"),
            (0.26, 0.54, "recognized"),
            (0.66, 0.68, "recognized"),
            (0.4, 0.32, "insufficientAudio"),
            (1.7, 0.30, "insufficientAudio"),
            (1.88, 0.32, "insufficientAudio"),
            (1.5, 0.7, "recognized"),
            (3.0, 0.3, "notRecognized"),
            (3.0, 0.8, "recognized"),
        ],
    )
    def test_le_doute_ne_devient_jamais_une_autorisation(
        self, verificateur, duree, score, etat
    ):
        """§100 : distingue peu de parole et une voix différente, au même seuil."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        verificateur.embed.return_value = np.array(
            [score, np.sqrt(1 - score**2)], dtype=np.float32
        )
        verdict = verificateur.evaluer(son(duree))
        assert verdict.etat == etat, "le motif doit correspondre à la mesure"
        assert verdict.reconnu == (etat == "recognized"), (
            "seul un accord explicite autorise"
        )

    def test_un_moteur_indisponible_n_accorde_pas_de_droit(self, verificateur):
        """§100 : l'extraction impossible n'est plus un accord implicite."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        verificateur.embed.return_value = None
        assert verificateur.evaluer(son()).etat == "unavailable", (
            "pas de faux propriétaire"
        )
        assert not verificateur.verify(son())[1], "compatibilité fail-closed"

    def test_du_silence_ajoute_ne_rend_pas_un_mot_plus_fiable(self, verificateur):
        """§100 : mesurer la parole, pas les secondes de silence autour."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        verificateur.embed.return_value = np.array(
            [0.3, np.sqrt(0.91)], dtype=np.float32
        )
        pcm = b"\0" * 64000 + son(0.3) + b"\0" * 64000
        assert mesurer_parole(pcm) < 0.4, "seul le fragment audible compte"
        assert verificateur.evaluer(pcm).etat == "insufficientAudio", "aucun accord"

    @pytest.mark.parametrize("pcm", [b"", b"x", b"\0" * 128000, son(0.08)])
    def test_un_clic_ou_un_silence_ne_declenche_pas_la_comparaison(
        self, verificateur, pcm
    ):
        """§100 : pas de preuve d'identité avec du silence ou une impulsion."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        verificateur.embed.reset_mock()
        assert verificateur.evaluer(pcm).etat == "insufficientAudio", (
            "son inexploitable"
        )
        verificateur.embed.assert_not_called()

    def test_reconnaitre_un_mot_ne_relache_pas_l_apprentissage(self, verificateur):
        """§78 : la durée de vérification n'abaisse pas celle du profil."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        revision = verificateur.revision
        assert verificateur.evaluer(son(0.3)).reconnu, "le mot est comparé"
        assert not verificateur.enroll(son(0.3)), "pas d'enrôlement sur un phonème"
        with pytest.raises(ProfilVocalInvalide, match="tooShort"):
            verificateur.preparer_echantillon(son(0.3), 7)
        assert verificateur.revision == revision, "aucune mutation du profil"

    def test_une_voix_ne_profite_pas_du_mot_court_reconnu_juste_avant(
        self, verificateur
    ):
        """§100 : aucune confiance de session héritée d'une autre voix."""
        verificateur.remplacer_guide([son()] * 8, "absent")
        assert verificateur.evaluer(son(0.3)).reconnu, "première identité confirmée"
        verificateur.embed.return_value = np.array(
            [0.3, np.sqrt(0.91)], dtype=np.float32
        )
        assert not verificateur.evaluer(son(0.3)).reconnu, (
            "seconde identité non prouvée"
        )

    def test_un_profil_corrompu_ne_rouvre_pas_le_verrou(self, tmp_path):
        """§100 : NaN ou vecteur nul ne valent pas un profil."""
        cible = tmp_path / "profil.npz"
        np.savez(cible, embeddings=np.full((5, 2), np.nan))
        v = SpeakerVerifier(profile_path=cible)
        assert v.evaluer(son()).etat == "profileMissing", "profil invalide refusé"
