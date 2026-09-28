#!/usr/bin/env python3
"""Installation explicite de la voix masculine locale, sans toucher au venv produit."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MODELE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit"
REVISION = "37e955a1deb861c088ae5f3a67043185f3d1a60c"


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
    if not (root / "installed.json").exists():
        if args.model_source:
            shutil.copytree(args.model_source, root / "model", dirs_exist_ok=True)
        else:
            script = (
                "import os; os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'; "
                "from huggingface_hub import snapshot_download; "
                f"snapshot_download({MODELE!r}, revision={REVISION!r}, "
                f"local_dir={str(root / 'model')!r})"
            )
            subprocess.run([str(python), "-c", script], check=True)
    (root / "installed.json").write_text(
        json.dumps({"model": MODELE, "revision": REVISION}), encoding="utf-8"
    )
    print("Moteur installé. La voix par défaut n’a pas été modifiée.")


if __name__ == "__main__":
    main()
