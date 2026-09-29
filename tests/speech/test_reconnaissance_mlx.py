"""§100 : une panne d'oreille ne devient ni texte inventé ni son envoyé au cloud."""

import base64
import io
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from diapason.speech.realtime import reconnaissance_mlx as r


def test_le_vad_garde_la_marge_et_le_silence_ne_lance_pas_le_modele(monkeypatch):
    vad = pytest.importorskip("faster_whisper.vad")

    def reperer(audio, options):
        assert options.speech_pad_ms == 400, "ne pas recouper les débuts des mots"
        assert options.threshold == 0.5, "la détection du bruit reste active"
        np.testing.assert_array_equal(audio, np.array([0, 0.5, -0.5], dtype=np.float32))
        return [{"start": 1, "end": 3}]

    monkeypatch.setattr(vad, "get_speech_timestamps", reperer)
    assert (
        r.parole_seule(np.array([0, 16384, -16384], dtype="<i2").tobytes())
        == np.array([0.5, -0.5], dtype="<f4").tobytes()
    )
    assert r.parole_seule(b"") == b"", "pas de calcul sur un tampon vide"
    with pytest.raises(ValueError):
        r.parole_seule(b"1")
    monkeypatch.setattr(r, "parole_seule", lambda _: b"")
    oreille = r.ReconnaissanceMLX("fr")
    monkeypatch.setattr(oreille, "_demarrer", lambda: pytest.fail("silence transmis"))
    assert oreille.transcrire(b"\0\0") == "", (
        "le silence ne fait jamais chauffer le modèle"
    )


def test_le_transport_garde_la_langue_et_refuse_le_faux_merci(monkeypatch):
    oreille = r.ReconnaissanceMLX("fr")
    entree = io.BytesIO()
    oreille._processus = SimpleNamespace(stdin=entree)
    monkeypatch.setattr(oreille, "_demarrer", lambda: None)
    monkeypatch.setattr(r, "parole_seule", lambda _: b"\0" * 4)
    monkeypatch.setattr(
        oreille,
        "_lire",
        lambda: {
            "type": "transcript",
            "segments": [
                {
                    "text": "Diapason, dis-moi trois phrases.",
                    "noSpeechProb": 0.1,
                    "avgLogprob": -0.2,
                },
                {"text": "Merci.", "noSpeechProb": 0.95, "avgLogprob": -2},
            ],
        },
    )
    try:
        assert oreille.transcrire(b"\0\0") == "Diapason, dis-moi trois phrases."
        trame = json.loads(entree.getvalue())
        assert trame["language"] == "fr"
        assert "mwen" in trame["prompt"].lower(), (
            "l'oreille doit pouvoir écrire le kreyòl"
        )
        assert trame["partial"] is False, "la finale garde le décodage complet"
        assert base64.b64decode(trame["audio"]) == b"\0" * 4
        oreille.transcrire(b"\0\0", provisoire=True)
        partiel = json.loads(entree.getvalue().splitlines()[-1])
        assert partiel["partial"] is True, "le marquage traverse vraiment le tube"
    finally:
        oreille._processus = None


@pytest.mark.skipif(
    sys.platform == "win32", reason="L'oreille Metal utilise des tubes POSIX"
)
def test_un_processus_en_panne_est_ferme_avant_le_prochain_tour(monkeypatch):
    oreille = r.ReconnaissanceMLX()
    processus = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys;sys.stdin.readline();"
            'print("{\\"type\\":\\"error\\"}",flush=True)',
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    oreille._processus = processus
    monkeypatch.setattr(oreille, "_demarrer", lambda: None)
    monkeypatch.setattr(r, "parole_seule", lambda _: b"\0" * 4)
    try:
        with pytest.raises(RuntimeError, match="échoué"):
            oreille.transcrire(b"\0\0")
        assert processus.poll() is not None, "le calcul échoué est terminé"
        assert oreille._processus is None, "aucune vieille réponse réutilisable"
    finally:
        oreille.fermer()


def test_une_installation_absente_ne_telecharge_rien(monkeypatch):
    monkeypatch.setattr(r, "moteur_installe", lambda: False)
    monkeypatch.setattr(
        r.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("démarrage inattendu")
    )
    with pytest.raises(RuntimeError, match="pas installé"):
        r.ReconnaissanceMLX().preload()


def test_le_choix_de_l_oreille_ne_change_ni_le_modele_ni_la_voix(monkeypatch):
    from diapason.core.config import DiapasonConfig
    from diapason.speech.realtime import local_voice

    config = DiapasonConfig()
    config.speech.realtime.stt_backend = "mlx-whisper"
    config.speech.language = "fr"
    choix = (
        config.speech.realtime.model,
        config.speech.realtime.voice,
        config.speech.model,
    )
    appels = []
    modes = []

    class Oreille:
        def __init__(self, langue):
            appels.append(langue)

        def preload(self):
            appels.append("prêt")

        def transcrire(self, pcm, *, provisoire=False):
            modes.append(provisoire)
            return "Dis-moi trois phrases."

    monkeypatch.setattr(r, "ReconnaissanceMLX", Oreille)
    monkeypatch.setattr("diapason.core.config.load_config", lambda: config)
    monkeypatch.setattr(local_voice, "_SHARED", {})
    monkeypatch.setattr(local_voice, "polish_transcript", lambda t: t)
    transcrire = local_voice._default_stt()
    assert transcrire(b"audio") == "Dis-moi trois phrases."
    assert transcrire.partiel(b"audio") == "Dis-moi trois phrases."
    assert modes == [False, True], "seul le sous-titre reçoit le calcul borné"
    local_voice._default_stt()
    assert appels == ["fr", "prêt"], "le modèle se charge une fois"
    assert choix == (
        config.speech.realtime.model,
        config.speech.realtime.voice,
        config.speech.model,
    )


@pytest.fixture
def inference_factice(monkeypatch):
    class Inference:
        def logits(self, valeur):
            return valeur

    module = ModuleType("mlx_whisper.decoding")
    module.Inference = Inference
    monkeypatch.setitem(sys.modules, "mlx_whisper.decoding", module)
    return Inference


def test_le_brouillon_expire_entre_jetons_et_la_finale_retrouve_le_moteur(
    monkeypatch, inference_factice
):
    """§100 — le budget abandonne le brouillon, jamais les mots de la finale."""
    from diapason.speech.realtime import ouvrier_reconnaissance as ouvrier

    horloge = [0.0]
    monkeypatch.setattr(ouvrier.time, "monotonic", lambda: horloge[0])
    original = inference_factice.logits
    inference = inference_factice()
    with pytest.raises(ouvrier.BrouillonTropLent):
        with ouvrier.borner_brouillon(True):
            assert inference.logits("premier jeton") == "premier jeton"
            horloge[0] = ouvrier.BUDGET_BROUILLON_S
            inference.logits("ne doit pas être calculé")
    assert inference_factice.logits is original, "aucun budget ne fuit vers la finale"
    with ouvrier.borner_brouillon(False):
        horloge[0] += 100
        assert inference.logits("phrase entière") == "phrase entière"
    with pytest.raises(ValueError, match="moteur"):
        with ouvrier.borner_brouillon(True):
            raise ValueError("moteur en panne")
    assert inference_factice.logits is original, "restauration aussi après une panne"


def test_un_dernier_jeton_trop_long_ne_publie_pas_un_brouillon_perime(
    monkeypatch, inference_factice
):
    """§100 — une fin de boucle tardive n'échappe pas au budget provisoire."""
    from diapason.speech.realtime import ouvrier_reconnaissance as ouvrier

    horloge = [0.0]
    monkeypatch.setattr(ouvrier.time, "monotonic", lambda: horloge[0])
    original = inference_factice.logits
    with pytest.raises(ouvrier.BrouillonTropLent):
        with ouvrier.borner_brouillon(True):
            inference_factice().logits("dernier jeton")
            horloge[0] += ouvrier.BUDGET_BROUILLON_S + 0.1
    assert inference_factice.logits is original


@pytest.mark.parametrize("cas", ["final", "partial", "tronque", "douteux", "expire"])
def test_l_ouvrier_chauffe_avant_ready_sans_reduire_le_decodage_reel(
    tmp_path, monkeypatch, inference_factice, cas
):
    from diapason.speech.realtime import ouvrier_reconnaissance as ouvrier

    (tmp_path / "weights.safetensors").touch()
    mx = ModuleType("mlx.core")
    mx.float16 = "float16"
    mx.set_cache_limit = lambda _: None
    synchronisations = []
    mx.synchronize = lambda: synchronisations.append(True)
    mlx = ModuleType("mlx")
    mlx.core = mx
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)
    appels = []
    sortie = io.StringIO()
    paquet = np.array([0.2, -0.1], dtype="<f4").tobytes()
    horloge = [0.0]
    monkeypatch.setattr(ouvrier.time, "monotonic", lambda: horloge[0])
    original = inference_factice.logits

    def transcrire(audio, **options):
        appels.append(options)
        if len(appels) == 1:
            assert sortie.getvalue() == "", "READY doit attendre la chauffe"
            assert np.all(audio == 0), "pas de parole personnelle pour préchauffer"
            assert options["sample_len"] == 1
            return {"segments": []}
        if cas == "final" or len(appels) == 3:
            assert "sample_len" not in options and "temperature" not in options, (
                "la parole garde son décodage complet et les reprises natives"
            )
            assert inference_factice.logits is original
        else:
            assert options["temperature"] == 0 and options["sample_len"] == 17
        if cas == "expire" and len(appels) == 2:
            horloge[0] += ouvrier.BUDGET_BROUILLON_S + 0.1
            inference_factice().logits("brouillon à abandonner")
        np.testing.assert_array_equal(audio, np.frombuffer(paquet, dtype="<f4"))
        return {
            "segments": [
                {
                    "text": "Trois phrases.",
                    "no_speech_prob": 0.1,
                    "avg_logprob": -2 if cas == "douteux" else -0.2,
                    "tokens": [1] * (17 if cas == "tronque" else 3),
                }
            ]
        }

    module = ModuleType("mlx_whisper.transcribe")
    module.ModelHolder = SimpleNamespace(get_model=lambda *_: None)
    module.transcribe = transcrire
    monkeypatch.setitem(sys.modules, "mlx_whisper.transcribe", module)
    monkeypatch.setattr(sys, "argv", ["ouvrier", str(tmp_path)])
    monkeypatch.setattr(sys, "stdout", sortie)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "audio": base64.b64encode(paquet).decode(),
                    "language": "fr",
                    "partial": cas != "final",
                }
            )
            + "\n"
            + (
                json.dumps(
                    {"audio": base64.b64encode(paquet).decode(), "partial": False}
                )
                + "\n"
                if cas == "expire"
                else ""
            )
        ),
    )
    try:
        ouvrier.principal()
    finally:
        sys.stdout = sortie
    trames = [json.loads(t) for t in sortie.getvalue().splitlines()]
    assert [t["type"] for t in trames] == ["ready", "transcript"] + (
        ["transcript"] if cas == "expire" else []
    )
    if cas in ("douteux", "tronque", "expire"):
        assert trames[1]["segments"] == [], (
            "un brouillon incomplet ou peu sûr reste muet"
        )
    else:
        assert trames[1]["segments"][0]["text"] == "Trois phrases."
    if cas == "expire":
        assert synchronisations == [True], "pas de calcul GPU orphelin après abandon"
        assert trames[2]["segments"][0]["text"] == "Trois phrases."
        assert len(appels) == 3, "la finale réutilise le modèle chaud après expiration"
    else:
        assert not synchronisations
        assert len(appels) == 2, "une chauffe puis le vrai énoncé"
