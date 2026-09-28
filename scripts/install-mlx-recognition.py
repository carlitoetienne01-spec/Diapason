#!/usr/bin/env python3
"""Installer explicitement l'oreille Metal dans son venv, sans changer le défaut."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MODELE = "mlx-community/whisper-large-v3-turbo"
REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
EMPREINTES = {
    "weights.safetensors": (
        "951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6"
    ),
    "config.json": "b34fc29e4e11e0a25e812775dd67f4dd16fc2c8eb43d28ae25ff7d660ecb6379",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-source", type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Cette oreille requiert un Mac Apple Silicon.")
    from diapason.core.paths import get_config_dir

    racine = get_config_dir() / "speech" / "whisper-mlx"
    racine.mkdir(parents=True, exist_ok=True)
    python = racine / "runtime/bin/python"
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv est requis pour le venv isolé.")
    if not python.exists():
        subprocess.run(
            [uv, "venv", "--python", sys.executable, str(racine / "runtime")],
            check=True,
        )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "mlx-whisper==0.4.3",
            "mlx==0.32.2",
            "numpy==2.5.3",
        ],
        check=True,
    )
    modele = racine / "model"
    if args.model_source:
        modele.mkdir(exist_ok=True)
        for nom in EMPREINTES:
            shutil.copy2(args.model_source / nom, modele / nom)
    else:
        script = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({MODELE!r}, revision={REVISION!r}, "
            f"local_dir={str(modele)!r}, token=False, "
            f"allow_patterns={list(EMPREINTES)!r})"
        )
        subprocess.run([str(python), "-c", script], check=True)
    for nom, attendu in EMPREINTES.items():
        with (modele / nom).open("rb") as fichier:
            obtenu = hashlib.file_digest(fichier, "sha256").hexdigest()
        if obtenu != attendu:
            raise RuntimeError(f"Empreinte du fichier {nom} invalide")
    (racine / "installed.json").write_text(
        json.dumps({"model": MODELE, "revision": REVISION, "sha256": EMPREINTES})
    )
    print("Reconnaissance installée et vérifiée ; choix du moteur inchangé.")


if __name__ == "__main__":
    main()
