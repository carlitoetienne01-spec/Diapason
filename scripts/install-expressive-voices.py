#!/usr/bin/env python3
"""Installation explicite de la voix masculine locale, sans toucher au venv produit."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MODELE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit"
REVISION = "37e955a1deb861c088ae5f3a67043185f3d1a60c"
# 28/09/2026 : ce script tirait 2,3 Go de poids sans en vérifier un octet,
# quand install-mlx-recognition.py vérifie chacun des siens. La révision fixe
# ce qu'on DEMANDE, pas ce qui ARRIVE : un cache ou un miroir altéré aurait été
# chargé tel quel par l'ouvrier, et moteur_installe() l'aurait dit installé.
# Les deux poids viennent du champ lfs.oid de l'API Hugging Face pour REVISION ;
# les dix autres n'y ont qu'un sha1 git, confronté à la copie installée sur le
# Mac de Carlito avant d'en tirer le SHA-256 — les quatorze fichiers
# concordaient. Douze, pas trois : ce sont les motifs que mlx-audio lui-même
# télécharge (*.json, *.safetensors, *.txt). Son chargeur prend TOUT
# *.safetensors du dossier et AutoTokenizer lit vocab.json et merges.txt.
# README.md et .gitattributes, que rien ne lit, ne sont plus téléchargés.
EMPREINTES = {
    "config.json": "36477d07e2ac89f79c1410a9782ed69860fbfcc871edea1728624389072e25fd",
    "generation_config.json": (
        "f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa"
    ),
    "merges.txt": "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
    "model.safetensors": (
        "ac973aa38ec79d4b4b52bf858948f0d47dd909aa4bcd383f5b900e277410fdb5"
    ),
    "model.safetensors.index.json": (
        "2b71cbd2c84cb59d0d71383cc55166ad7108180bfd7e47d2e3a6698f3721abfb"
    ),
    "preprocessor_config.json": (
        "efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119"
    ),
    "speech_tokenizer/config.json": (
        "ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167"
    ),
    "speech_tokenizer/configuration.json": (
        "6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd"
    ),
    "speech_tokenizer/model.safetensors": (
        "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"
    ),
    "speech_tokenizer/preprocessor_config.json": (
        "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb"
    ),
    "tokenizer_config.json": (
        "dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670"
    ),
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
}


def verifier(modele: Path, temoin: Path) -> None:
    for nom, attendu in EMPREINTES.items():
        try:
            with (modele / nom).open("rb") as fichier:
                obtenu = hashlib.file_digest(fichier, "sha256").hexdigest()
        except FileNotFoundError:
            obtenu = None
        if obtenu != attendu:
            # Relancer sur une installation existante re-vérifie ses poids.
            # Laisser l'ancien témoin ferait dire « installé » à
            # moteur_installe() sur un fichier qu'on vient de refuser (§5).
            temoin.unlink(missing_ok=True)
            raise RuntimeError(f"Empreinte du fichier {nom} invalide")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-source", type=Path, help="Copie locale déjà téléchargée"
    )
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Ce moteur requiert un Mac Apple Silicon.")
    from diapason.core.paths import get_config_dir

    root = get_config_dir() / "voices/qwen3"
    root.mkdir(parents=True, exist_ok=True)
    python = root / "runtime/bin/python"
    modele = root / "model"
    temoin = root / "installed.json"
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv doit être installé pour préparer le venv séparé.")
    if not python.exists():
        subprocess.run(
            [uv, "venv", "--python", sys.executable, str(root / "runtime")], check=True
        )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "mlx-audio==0.5.6",
            "soundfile==0.13.1",
        ],
        check=True,
    )
    if not temoin.exists():
        if args.model_source:
            for nom in EMPREINTES:
                cible = modele / nom
                cible.parent.mkdir(parents=True, exist_ok=True)
                # Les poids installés sont en lecture seule (r--r--r--,
                # constaté le 28/09/2026) : copy2 par-dessus lève
                # PermissionError, et un fichier refusé ne pouvait plus être
                # remplacé depuis une copie saine.
                cible.unlink(missing_ok=True)
                shutil.copy2(args.model_source / nom, cible)
        else:
            script = (
                "import os; os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'; "
                "from huggingface_hub import snapshot_download; "
                f"snapshot_download({MODELE!r}, revision={REVISION!r}, "
                f"local_dir={str(modele)!r}, "
                f"allow_patterns={list(EMPREINTES)!r})"
            )
            subprocess.run([str(python), "-c", script], check=True)
    verifier(modele, temoin)
    temoin.write_text(
        json.dumps({"model": MODELE, "revision": REVISION, "sha256": EMPREINTES}),
        encoding="utf-8",
    )
    print("Moteur installé et vérifié. La voix par défaut n’a pas été modifiée.")


if __name__ == "__main__":
    main()
