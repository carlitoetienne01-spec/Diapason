"""§5 — la voix Orion ne se dit installée que sur des poids vérifiés.

28/09/2026 : ``scripts/install-expressive-voices.py`` tirait 2,3 Go de poids
à une révision fixée sans vérifier ce qui arrivait, quand
``install-mlx-recognition.py`` vérifie chacun des siens. Un poids altéré
était chargé tel quel par l'ouvrier, et ``moteur_installe()`` le disait prêt.

Sans réseau : le dépôt Hugging Face est un faux module, les poids quelques
octets dont le test pose l'empreinte. Le dernier test lit la VRAIE table.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

from diapason.speech.realtime.voix_expressive import moteur_installe

RACINE = Path(__file__).resolve().parents[2]

CONTENUS = {
    "config.json": b'{"model_type": "qwen3_tts"}',
    "model.safetensors": b"poids du locuteur",
    "speech_tokenizer/model.safetensors": b"poids du codec",
}


def _installeur():
    spec = importlib.util.spec_from_file_location(
        "install_expressive_voices", RACINE / "scripts/install-expressive-voices.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ecrire(dossier: Path, contenus: dict[str, bytes]) -> None:
    for nom, octets in contenus.items():
        (dossier / nom).parent.mkdir(parents=True, exist_ok=True)
        (dossier / nom).write_bytes(octets)


class _Banc:
    """Le script entier, avec uv, la plateforme et le Hub remplacés."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.installeur = _installeur()
        self.racine = tmp_path / "maison/voices/qwen3"
        self.modele = self.racine / "model"
        self.temoin = self.racine / "installed.json"
        self.source = tmp_path / "source"
        self.depot = dict(CONTENUS)
        self.telechargements: list[dict] = []
        self._monkeypatch = monkeypatch
        monkeypatch.setattr(
            self.installeur,
            "EMPREINTES",
            {nom: hashlib.sha256(o).hexdigest() for nom, o in CONTENUS.items()},
        )
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
        monkeypatch.setenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        monkeypatch.setattr(self.installeur.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(self.installeur.platform, "machine", lambda: "arm64")
        monkeypatch.setattr(self.installeur.shutil, "which", lambda nom: "/opt/uv")
        monkeypatch.setattr(self.installeur.subprocess, "run", self._executer)
        monkeypatch.setitem(
            sys.modules,
            "huggingface_hub",
            types.SimpleNamespace(snapshot_download=self._snapshot_download),
        )
        (self.racine / "runtime/bin").mkdir(parents=True)
        (self.racine / "runtime/bin/python").write_text("")

    def _executer(self, commande, **options) -> None:
        # uv venv et uv pip install ne font rien ; le téléchargement, lui,
        # exécute le VRAI extrait du script contre le faux Hub.
        if commande[1:2] == ["-c"]:
            exec(commande[2], {})

    def _snapshot_download(self, repo, *, revision, local_dir, allow_patterns=None):
        self.telechargements.append(
            {"repo": repo, "revision": revision, "allow_patterns": allow_patterns}
        )
        _ecrire(
            Path(local_dir),
            {
                nom: octets
                for nom, octets in self.depot.items()
                if allow_patterns is None
                or any(fnmatch.fnmatch(nom, motif) for motif in allow_patterns)
            },
        )

    def lancer(self, *arguments: str) -> None:
        self._monkeypatch.setattr(
            sys, "argv", ["install-expressive-voices.py", *arguments]
        )
        self.installeur.main()


@pytest.fixture
def banc(tmp_path, monkeypatch) -> _Banc:
    return _Banc(tmp_path, monkeypatch)


class TestEmpreintesDeLaVoixOrion:
    def test_une_copie_conforme_est_installee_et_son_temoin_porte_les_empreintes(
        self, banc
    ):
        """§5 — le témoin dit ce qui a été vérifié, et seulement cela.

        Le chargeur de mlx-audio prend TOUT *.safetensors du dossier : un
        fichier de trop dans la source serait chargé sans avoir été vérifié.
        """
        _ecrire(banc.source, {**CONTENUS, "intrus.safetensors": b"inconnu"})

        banc.lancer("--model-source", str(banc.source))

        temoin = json.loads(banc.temoin.read_text(encoding="utf-8"))
        assert temoin["sha256"] == banc.installeur.EMPREINTES, (
            "le témoin doit porter les empreintes vérifiées"
        )
        assert temoin["revision"] == banc.installeur.REVISION, "révision perdue"
        assert not (banc.modele / "intrus.safetensors").exists(), (
            "un fichier hors de la table ne doit pas entrer dans le modèle"
        )
        assert moteur_installe(), "une copie conforme doit rendre la voix disponible"

    def test_un_poids_falsifie_est_refuse_et_rien_ne_dit_installe(self, banc):
        """§5 — un poids altéré ne doit jamais donner une voix « disponible »."""
        _ecrire(
            banc.source,
            {**CONTENUS, "speech_tokenizer/model.safetensors": b"poids du codeX"},
        )

        with pytest.raises(RuntimeError, match="speech_tokenizer/model.safetensors"):
            banc.lancer("--model-source", str(banc.source))

        assert not banc.temoin.exists(), "aucun témoin pour un poids refusé"
        assert not moteur_installe(), "la voix ne doit pas se dire installée"

    def test_un_fichier_manquant_est_refuse_comme_un_fichier_altere(self, banc):
        """§5 — l'absence d'un fichier vérifié n'est pas une réussite."""
        banc.depot.pop("config.json")

        with pytest.raises(RuntimeError, match="config.json"):
            banc.lancer()

        assert not banc.temoin.exists(), "aucun témoin pour un modèle incomplet"

    def test_relancer_sur_une_installation_alteree_retire_le_temoin(self, banc):
        """§5 — l'ancien témoin disait « installé » sur un poids refusé."""
        _ecrire(banc.source, CONTENUS)
        banc.lancer("--model-source", str(banc.source))
        assert moteur_installe(), "précondition : la première installation passe"
        (banc.modele / "model.safetensors").write_bytes(b"poids du locuteuR")

        with pytest.raises(RuntimeError, match="model.safetensors"):
            banc.lancer()

        assert not banc.temoin.exists(), "le témoin d'un modèle altéré doit tomber"
        assert not moteur_installe(), "la voix doit cesser de se dire disponible"

    def test_un_poids_refuse_en_lecture_seule_se_remplace_depuis_une_copie_saine(
        self, banc
    ):
        """§5 — le refus doit laisser un chemin de réparation.

        Les poids installés sont en lecture seule : copier par-dessus levait
        PermissionError, et le modèle refusé ne se réparait plus.
        """
        _ecrire(banc.modele, {**CONTENUS, "model.safetensors": b"poids du locuteuR"})
        (banc.modele / "model.safetensors").chmod(0o444)
        _ecrire(banc.source, CONTENUS)

        banc.lancer("--model-source", str(banc.source))

        assert (banc.modele / "model.safetensors").read_bytes() == CONTENUS[
            "model.safetensors"
        ], "la copie saine doit remplacer le poids refusé"
        assert moteur_installe(), "le modèle réparé doit être rendu disponible"

    def test_le_telechargement_ne_tire_que_les_fichiers_verifies_a_la_revision_fixee(
        self, banc
    ):
        """§5 — ce qui arrive du réseau est ce qui est vérifié, rien d'autre."""
        banc.depot["README.md"] = b"# carte du modele"

        banc.lancer()

        (telechargement,) = banc.telechargements
        assert telechargement["repo"] == banc.installeur.MODELE, "mauvais dépôt"
        assert telechargement["revision"] == banc.installeur.REVISION, (
            "la révision doit rester fixée"
        )
        assert not (banc.modele / "README.md").exists(), (
            "un fichier hors de la table ne doit pas être téléchargé"
        )
        assert moteur_installe(), "un téléchargement conforme rend la voix disponible"

    def test_un_telechargement_altere_est_refuse(self, banc):
        """§5 — la révision fixe ce qu'on demande, pas ce qui arrive."""
        banc.depot["model.safetensors"] = b"poids substitue"

        with pytest.raises(RuntimeError, match="model.safetensors"):
            banc.lancer()

        assert not banc.temoin.exists(), "aucun témoin pour un poids substitué"
        assert not moteur_installe(), "la voix ne doit pas se dire installée"


class TestLaVraieTable:
    def test_elle_couvre_ce_que_le_moteur_exige_pour_se_dire_installe(self):
        """§5 — un fichier que moteur_installe() exige doit être vérifié.

        Ajouter un fichier à ce contrôle sans l'épingler ici rouvrirait le
        défaut : la voix se dirait prête sur un fichier jamais vérifié.
        """
        table = _installeur().EMPREINTES
        exiges = {
            "config.json",
            "model.safetensors",
            "speech_tokenizer/model.safetensors",
        }
        assert exiges <= set(table), f"non épinglés : {exiges - set(table)}"
        for nom, empreinte in table.items():
            assert re.fullmatch(r"[0-9a-f]{64}", empreinte), (
                f"{nom} : une empreinte SHA-256 fait 64 chiffres hexadécimaux"
            )
