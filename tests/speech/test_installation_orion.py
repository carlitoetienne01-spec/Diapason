"""§5 — la voix Orion ne se dit installée que sur des poids vérifiés.

28/09/2026 : ``scripts/install-expressive-voices.py`` tirait 2,3 Go de poids
à une révision fixée sans vérifier ce qui arrivait, quand
``install-mlx-recognition.py`` vérifie chacun des siens. Un poids altéré
était chargé tel quel par l'ouvrier, et ``moteur_installe()`` le disait prêt.

Sans réseau : le dépôt Hugging Face est un faux module, les poids quelques
octets dont le test pose l'empreinte. Un seul test exerce le VRAI
huggingface_hub, son accès au Hub remplacé et les sockets coupés, pour le
raccourci de local_dir qui resservait un fichier refusé. TestLaVraieTable lit
la VRAIE table.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import socket
import sys
import types
from pathlib import Path

import pytest

from diapason.speech.realtime.voix_expressive import moteur_installe

RACINE = Path(__file__).resolve().parents[2]

METADONNEE_DU_HUB = b"revision\netag\nhorodatage\n"

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


def _table(contenus: dict[str, bytes]) -> dict[str, str]:
    return {nom: hashlib.sha256(o).hexdigest() for nom, o in contenus.items()}


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
        monkeypatch.setattr(self.installeur, "EMPREINTES", _table(CONTENUS))
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
        tires = {
            nom: octets
            for nom, octets in self.depot.items()
            if allow_patterns is None
            or any(fnmatch.fnmatch(nom, motif) for motif in allow_patterns)
        }
        _ecrire(Path(local_dir), tires)
        # Comme le vrai hub : sa tenue de livres dans local_dir, qu'aucun
        # chargeur ne lit et que la vérification ne doit pas prendre pour un
        # intrus.
        _ecrire(
            Path(local_dir) / ".cache/huggingface",
            {
                ".gitignore": b"*",
                **{f"download/{nom}.metadata": METADONNEE_DU_HUB for nom in tires},
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
        assert (
            banc.modele / ".cache/huggingface/download/config.json.metadata"
        ).is_file(), "précondition : la tenue du hub est bien présente à côté des poids"
        assert moteur_installe(), "un téléchargement conforme rend la voix disponible"

    def test_un_telechargement_altere_est_refuse(self, banc):
        """§5 — la révision fixe ce qu'on demande, pas ce qui arrive."""
        banc.depot["model.safetensors"] = b"poids substitue"

        with pytest.raises(RuntimeError, match="model.safetensors"):
            banc.lancer()

        assert not banc.temoin.exists(), "aucun témoin pour un poids substitué"
        assert not moteur_installe(), "la voix ne doit pas se dire installée"


class TestCeQueLeChargeurLirait:
    """28/09/2026 : la relance ne vérifiait que les douze noms de la table."""

    @pytest.mark.parametrize(
        "intrus",
        [
            ("intrus.safetensors", "speech_tokenizer/intrus.safetensors"),
            # Ce que l'ancienne version du script tirait, et qui dort encore
            # dans le modèle installé sur le Mac de Carlito.
            (".gitattributes", "README.md"),
        ],
        ids=["poids-intrus", "restes-de-l-ancien-script"],
    )
    def test_un_fichier_hors_table_est_refuse_a_la_relance_puis_retire(
        self, banc, intrus
    ):
        """§5 — mlx-audio charge TOUT *.safetensors de model/ et du codec.

        Un intrus posé à côté des poids vérifiés était chargé par l'ouvrier,
        et la relance réécrivait le témoin « installé et vérifié ».
        """
        _ecrire(banc.source, CONTENUS)
        banc.lancer("--model-source", str(banc.source))
        _ecrire(banc.modele, dict.fromkeys(intrus, b"inconnu"))

        with pytest.raises(RuntimeError, match="hors de la table") as refus:
            banc.lancer()

        assert ", ".join(intrus) in str(refus.value), (
            f"le refus doit nommer chaque intrus : {refus.value}"
        )
        assert "relancez" in str(refus.value), "le refus doit dire comment en sortir"
        assert not banc.temoin.exists(), "le témoin d'un modèle refusé doit tomber"
        assert not moteur_installe(), "la voix ne doit pas se dire disponible"
        assert not any((banc.modele / nom).exists() for nom in intrus), (
            "un intrus laissé en place ferait refuser chaque relance"
        )
        banc.lancer()
        assert moteur_installe(), "la relance conseillée doit suffire à réparer"

    def test_un_poids_illisible_a_la_relance_retire_le_temoin(self, banc):
        """§5 — une lecture impossible est un refus, pas une exception qui fuit.

        Seule FileNotFoundError était captée : un poids en chmod 000 levait
        PermissionError hors de la vérification, sous un témoin intact.
        """
        if os.geteuid() == 0:
            pytest.skip("root lit un fichier en chmod 000")
        _ecrire(banc.source, CONTENUS)
        banc.lancer("--model-source", str(banc.source))
        (banc.modele / "speech_tokenizer/model.safetensors").chmod(0)

        with pytest.raises(RuntimeError, match="speech_tokenizer/model.safetensors"):
            banc.lancer()

        assert not banc.temoin.exists(), "aucun témoin sur un poids illisible"
        assert not moteur_installe(), "la voix ne doit pas se dire disponible"

    def test_une_copie_saine_repare_en_un_lancement_une_installation_alteree(
        self, banc
    ):
        """§5 — --model-source était ignoré tant que le témoin existait.

        Réparer demandait deux lancements, et le premier refusait sans rien
        copier ni rien suggérer.
        """
        _ecrire(banc.source, CONTENUS)
        banc.lancer("--model-source", str(banc.source))
        poids = banc.modele / "model.safetensors"
        poids.write_bytes(b"poids du locuteuR")
        poids.chmod(0o444)

        banc.lancer("--model-source", str(banc.source))

        assert poids.read_bytes() == CONTENUS["model.safetensors"], (
            "la copie saine doit remplacer le poids altéré dès ce lancement"
        )
        assert moteur_installe(), "le modèle réparé doit être rendu disponible"

    def test_une_source_alteree_ne_touche_pas_une_installation_saine(
        self, banc, tmp_path
    ):
        """§5 — copier par-dessus une installation ne doit pas l'abîmer.

        Maintenant que --model-source copie même sur une installation
        existante, une source fausse remplacerait des poids sains avant
        d'être refusée.
        """
        _ecrire(banc.source, CONTENUS)
        banc.lancer("--model-source", str(banc.source))
        mauvaise = tmp_path / "mauvaise"
        _ecrire(
            mauvaise,
            {**CONTENUS, "speech_tokenizer/model.safetensors": b"poids du codeX"},
        )

        with pytest.raises(RuntimeError, match="rien n'a été remplacé"):
            banc.lancer("--model-source", str(mauvaise))

        for nom, octets in CONTENUS.items():
            assert (banc.modele / nom).read_bytes() == octets, (
                f"{nom} : une source refusée ne doit rien remplacer"
            )
        assert moteur_installe(), "l'installation saine doit rester disponible"

    def test_une_copie_interrompue_ne_laisse_aucun_temoin(self, banc, monkeypatch):
        """§5 — un modèle à moitié remplacé n'est plus celui qu'on a vérifié.

        La copie remplace les fichiers un à un : interrompue (disque plein),
        elle laisserait l'ancien témoin sur un mélange de deux modèles.
        """
        _ecrire(banc.source, CONTENUS)
        banc.lancer("--model-source", str(banc.source))
        copier = banc.installeur.shutil.copy2

        def disque_plein(source, cible):
            if Path(source).name == "model.safetensors":
                raise OSError(28, "No space left on device")
            return copier(source, cible)

        monkeypatch.setattr(banc.installeur.shutil, "copy2", disque_plein)

        with pytest.raises(OSError, match="No space left"):
            banc.lancer("--model-source", str(banc.source))

        assert not banc.temoin.exists(), "aucun témoin sur une copie interrompue"
        assert not moteur_installe(), "la voix ne doit pas se dire disponible"


class TestUnFichierRefuseEstRetelecharge:
    def test_le_vrai_hub_ne_ressert_plus_un_fichier_refuse(self, tmp_path, monkeypatch):
        """§5 — refuser un fichier sans le retirer bloquait l'installation.

        huggingface_hub rend un fichier de local_dir sans interroger le Hub
        quand ses métadonnées portent la révision demandée : un config.json
        altéré sur le disque était resservi à chaque relance, et chaque
        relance le refusait avec un message qui ne disait pas comment sortir.
        """
        pytest.importorskip("huggingface_hub")
        from huggingface_hub import file_download, hf_hub_download
        from huggingface_hub._local_folder import write_download_metadata

        class ReseauDemande(Exception):
            pass

        def reseau(**_):
            raise ReseauDemande

        def aucune_connexion(*_, **__):
            raise AssertionError("aucun réseau dans ce test")

        monkeypatch.setattr(file_download, "_get_metadata_or_catch_error", reseau)
        monkeypatch.setattr(socket.socket, "connect", aucune_connexion)
        installeur = _installeur()
        monkeypatch.setattr(installeur, "EMPREINTES", _table(CONTENUS))
        modele = tmp_path / "model"
        temoin = tmp_path / "installed.json"
        altere = b'{"altere": true}'
        _ecrire(modele, {**CONTENUS, "config.json": altere})
        for nom in CONTENUS:
            write_download_metadata(
                modele, nom, commit_hash=installeur.REVISION, etag="0" * 40
            )
        temoin.write_text("{}", encoding="utf-8")

        def servir() -> bytes:
            chemin = hf_hub_download(
                installeur.MODELE,
                "config.json",
                revision=installeur.REVISION,
                local_dir=modele,
                token=False,
            )
            return Path(chemin).read_bytes()

        assert servir() == altere, (
            "précondition : le vrai hub ressert le fichier altéré sans le Hub"
        )

        with pytest.raises(RuntimeError, match="config.json") as refus:
            installeur.verifier(modele, temoin)

        assert ".cache" not in str(refus.value), "la tenue du hub n'est pas un intrus"
        assert not temoin.exists(), "aucun témoin sur un fichier refusé"
        with pytest.raises(ReseauDemande):
            servir()


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

    def test_elle_est_exactement_les_douze_fichiers_que_le_chargeur_lit(self):
        """§5 — la table est AUSSI la liste de téléchargement et de copie.

        Un nom retiré de la table ne serait plus tiré : sans vocab.json ni
        merges.txt, AutoTokenizer échoue, post_load_hook de mlx-audio avale
        l'erreur (« Could not load tokenizer »), et la voix se dit installée
        sur une synthèse cassée. Ce sont les quatorze fichiers du dépôt à
        REVISION, moins README.md et .gitattributes que rien ne lit.
        """
        assert set(_installeur().EMPREINTES) == {
            "config.json",
            "generation_config.json",
            "merges.txt",
            "model.safetensors",
            "model.safetensors.index.json",
            "preprocessor_config.json",
            "speech_tokenizer/config.json",
            "speech_tokenizer/configuration.json",
            "speech_tokenizer/model.safetensors",
            "speech_tokenizer/preprocessor_config.json",
            "tokenizer_config.json",
            "vocab.json",
        }, "la table doit couvrir exactement ce que mlx-audio et AutoTokenizer lisent"
