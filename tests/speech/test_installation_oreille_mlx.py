"""§5 — l'oreille MLX ne se dit installée que sur des poids vérifiés.

28/09/2026 : ``scripts/install-mlx-recognition.py`` vérifiait ses deux
fichiers, mais un refus laissait l'ancien ``installed.json`` en place, et
``reconnaissance_mlx.moteur_installe()`` le lisait pour dire l'oreille prête.
Le fichier refusé restait aussi sur le disque, où huggingface_hub le
resservait à chaque relance sans rien retélécharger.

Sans réseau : le faux Hub garde, comme le vrai, un fichier déjà présent dans
local_dir à la révision demandée.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from diapason.speech.realtime.reconnaissance_mlx import moteur_installe

RACINE = Path(__file__).resolve().parents[2]

CONTENUS = {
    "weights.safetensors": b"poids de l'oreille",
    "config.json": b'{"n_mels": 128}',
}


def _installeur():
    spec = importlib.util.spec_from_file_location(
        "install_mlx_recognition", RACINE / "scripts/install-mlx-recognition.py"
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
        self.racine = tmp_path / "maison/speech/whisper-mlx"
        self.modele = self.racine / "model"
        self.temoin = self.racine / "installed.json"
        self.source = tmp_path / "source"
        self.depot = dict(CONTENUS)
        self.hub_en_panne = False
        self._monkeypatch = monkeypatch
        monkeypatch.setattr(
            self.installeur,
            "EMPREINTES",
            {nom: hashlib.sha256(o).hexdigest() for nom, o in CONTENUS.items()},
        )
        monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "maison"))
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
            if self.hub_en_panne:
                raise subprocess.CalledProcessError(1, commande)
            exec(commande[2], {})

    def _snapshot_download(self, repo, *, revision, local_dir, **options):
        # Comme le vrai hub pour local_dir : un fichier déjà là, dont les
        # métadonnées portent la révision demandée, est rendu tel quel.
        _ecrire(
            Path(local_dir),
            {
                nom: octets
                for nom, octets in self.depot.items()
                if nom in options["allow_patterns"]
                and not (Path(local_dir) / nom).exists()
            },
        )

    def lancer(self, *arguments: str) -> None:
        self._monkeypatch.setattr(
            sys, "argv", ["install-mlx-recognition.py", *arguments]
        )
        self.installeur.main()


@pytest.fixture
def banc(tmp_path, monkeypatch) -> _Banc:
    return _Banc(tmp_path, monkeypatch)


class TestLeTemoinDeLOreilleMLX:
    def test_un_telechargement_conforme_ecrit_un_temoin_qui_porte_les_empreintes(
        self, banc
    ):
        """§5 — précondition des suivants : le chemin nominal reste intact."""
        banc.lancer()

        temoin = json.loads(banc.temoin.read_text(encoding="utf-8"))
        assert temoin["sha256"] == banc.installeur.EMPREINTES, (
            "le témoin doit porter les empreintes vérifiées"
        )
        assert moteur_installe(), "un modèle conforme rend l'oreille disponible"

    def test_un_poids_altere_a_la_relance_retire_le_temoin_puis_se_retelecharge(
        self, banc
    ):
        """§5 — un refus laissait l'ancien témoin dire « installé ».

        Et le poids refusé restait en place : le hub le resservait, chaque
        relance le refusait de nouveau, sans issue.
        """
        banc.lancer()
        (banc.modele / "weights.safetensors").write_bytes(b"poids de l'oreillE")

        with pytest.raises(RuntimeError, match="weights.safetensors") as refus:
            banc.lancer()

        assert not banc.temoin.exists(), "le témoin d'un poids refusé doit tomber"
        assert not moteur_installe(), "l'oreille ne doit pas se dire disponible"
        assert "relancez" in str(refus.value), "le refus doit dire comment en sortir"
        banc.lancer()
        assert (banc.modele / "weights.safetensors").read_bytes() == CONTENUS[
            "weights.safetensors"
        ], "la relance conseillée doit retélécharger le poids refusé"
        assert moteur_installe(), "le modèle réparé doit être rendu disponible"

    def test_un_fichier_illisible_est_un_refus_et_non_une_exception_qui_fuit(
        self, banc
    ):
        """§5 — une PermissionError sortait sous un témoin intact."""
        if os.geteuid() == 0:
            pytest.skip("root lit un fichier en chmod 000")
        banc.lancer()
        (banc.modele / "config.json").chmod(0)

        with pytest.raises(RuntimeError, match="config.json"):
            banc.lancer()

        assert not banc.temoin.exists(), "aucun témoin sur un fichier illisible"
        assert not moteur_installe(), "l'oreille ne doit pas se dire disponible"

    def test_un_telechargement_echoue_ne_laisse_aucun_temoin(self, banc):
        """§5 — un téléchargement interrompu peut avoir remplacé un fichier.

        Le fichier remplacé n'a pas été vérifié : l'ancien témoin ne le
        couvre plus.
        """
        banc.lancer()
        banc.hub_en_panne = True

        with pytest.raises(subprocess.CalledProcessError):
            banc.lancer()

        assert not banc.temoin.exists(), "aucun témoin après un échec"
        assert not moteur_installe(), "l'oreille ne doit pas se dire disponible"


class TestRienNeSortDuDossierDeLOreille:
    def test_un_poids_lie_refuse_perd_son_lien_et_jamais_sa_cible(self, banc, tmp_path):
        """§5 — la voix Orion effaçait un fichier extérieur à travers un lien.

        Ici les deux noms sont à la racine de model/ : seul le lien peut
        être refusé, et c'est lui, pas sa cible, qui doit partir. Un
        _retirer() qui résoudrait le chemin effacerait le fichier de
        l'utilisateur.
        """
        banc.lancer()
        exterieur = tmp_path / "ailleurs/poids.safetensors"
        _ecrire(exterieur.parent, {exterieur.name: b"un autre poids, precieux"})
        (banc.modele / "weights.safetensors").unlink()
        (banc.modele / "weights.safetensors").symlink_to(exterieur)

        with pytest.raises(RuntimeError, match="weights.safetensors"):
            banc.lancer()

        assert exterieur.read_bytes() == b"un autre poids, precieux", (
            "un fichier hors de model/ ne doit jamais être effacé"
        )
        assert not moteur_installe(), "l'oreille ne doit pas se dire disponible"
        banc.lancer()
        assert not (banc.modele / "weights.safetensors").is_symlink(), (
            "la relance doit reposer un vrai fichier à la place du lien"
        )
        assert moteur_installe(), "le modèle réparé doit être rendu disponible"
        assert exterieur.read_bytes() == b"un autre poids, precieux", (
            "la relance ne doit rien écrire derrière l'ancien lien"
        )


class TestLaCopieLocaleDeLOreille:
    def test_une_copie_saine_remplace_un_poids_en_lecture_seule(self, banc):
        """§5 — copy2 par-dessus un poids en r--r--r-- levait PermissionError.

        Le poids refusé ne se remplaçait plus depuis une copie saine.
        """
        _ecrire(banc.modele, {**CONTENUS, "weights.safetensors": b"poids altere"})
        (banc.modele / "weights.safetensors").chmod(0o444)
        _ecrire(banc.source, CONTENUS)

        banc.lancer("--model-source", str(banc.source))

        assert (banc.modele / "weights.safetensors").read_bytes() == CONTENUS[
            "weights.safetensors"
        ], "la copie saine doit remplacer le poids refusé"
        assert moteur_installe(), "le modèle réparé doit être rendu disponible"

    def test_une_source_alteree_ne_touche_pas_une_installation_saine(
        self, banc, tmp_path
    ):
        """§5 — la copie écrasait des poids sains avant de refuser la source."""
        banc.lancer()
        mauvaise = tmp_path / "mauvaise"
        _ecrire(mauvaise, {**CONTENUS, "weights.safetensors": b"poids altere"})

        with pytest.raises(RuntimeError, match="rien n'a été remplacé"):
            banc.lancer("--model-source", str(mauvaise))

        for nom, octets in CONTENUS.items():
            assert (banc.modele / nom).read_bytes() == octets, (
                f"{nom} : une source refusée ne doit rien remplacer"
            )
        assert moteur_installe(), "l'installation saine doit rester disponible"

    def test_une_copie_interrompue_ne_laisse_aucun_temoin(self, banc, monkeypatch):
        """§5 — un modèle à moitié remplacé n'est plus celui qu'on a vérifié."""
        banc.lancer()
        _ecrire(banc.source, CONTENUS)
        copier = banc.installeur.shutil.copy2

        def disque_plein(source, cible):
            if Path(source).name == "config.json":
                raise OSError(28, "No space left on device")
            return copier(source, cible)

        monkeypatch.setattr(banc.installeur.shutil, "copy2", disque_plein)

        with pytest.raises(OSError, match="No space left"):
            banc.lancer("--model-source", str(banc.source))

        assert not banc.temoin.exists(), "aucun témoin sur une copie interrompue"
