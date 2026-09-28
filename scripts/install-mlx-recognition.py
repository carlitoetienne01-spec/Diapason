#!/usr/bin/env python3
"""Installer explicitement l'oreille Metal dans son venv, sans changer le défaut."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
# Pas de refus des fichiers hors table ici, contrairement à la voix Orion
# (install-expressive-voices.py) : mlx-whisper 0.4.3 ouvre config.json et
# weights.safetensors PAR LEUR NOM (load_models.load_model), weights.npz
# seulement si weights.safetensors manque — ce que la vérification refuse et
# que moteur_installe() exclut —, et son tokenizer vient de ses propres
# assets. Aucun glob : un fichier de trop dans model/ n'est jamais lu.
# Pas de refus des liens non plus (vérifié le 28/09/2026, quand la voix Orion
# effaçait un fichier extérieur à travers model/speech_tokenizer lié) : les
# deux noms sont à la racine de model/, aucun dossier lié ne peut s'intercaler
# entre model/ et eux, et _retirer() défait un lien sans toucher sa cible.
# Aucune suppression ni aucune copie ne sort donc de model/.


def _empreinte(chemin: Path) -> str | None:
    try:
        with chemin.open("rb") as fichier:
            return hashlib.file_digest(fichier, "sha256").hexdigest()
    except OSError:
        # 28/09/2026 : rien n'était capté. Un fichier absent ou en chmod 000
        # levait hors de la vérification, sous l'ancien témoin intact.
        return None


def _non_conformes(dossier: Path) -> list[str]:
    return [
        nom
        for nom, attendu in EMPREINTES.items()
        if _empreinte(dossier / nom) != attendu
    ]


def _retirer(chemin: Path) -> None:
    try:
        if chemin.is_dir() and not chemin.is_symlink():
            shutil.rmtree(chemin)
        else:
            chemin.unlink(missing_ok=True)
    except OSError:
        pass  # verifier() nomme ce qui reste, et demande de le retirer


def verifier(modele: Path) -> None:
    refuses = _non_conformes(modele)
    if not refuses:
        return
    # 28/09/2026 : le fichier refusé restait en place, et huggingface_hub le
    # resservait sans le retélécharger (ses métadonnées de local_dir portent
    # la bonne révision) : chaque relance le refusait de nouveau.
    for nom in refuses:
        _retirer(modele / nom)
    restants = [nom for nom in refuses if os.path.lexists(modele / nom)]
    suite = (
        f"Impossible de retirer {', '.join(restants)} : supprimez-les, puis "
        "relancez le script."
        if restants
        else "Ces fichiers ont été retirés : relancez le script pour les "
        "retélécharger (ou --model-source avec une copie saine)."
    )
    raise RuntimeError(
        "Modèle refusé — empreinte invalide ou fichier absent/illisible : "
        f"{', '.join(refuses)}. {suite}"
    )


def copier(source: Path, modele: Path, temoin: Path) -> None:
    # 28/09/2026 : la copie écrasait l'installation avant de vérifier quoi que
    # ce soit, une source fausse remplaçait donc des poids sains. Elle est
    # vérifiée AVANT qu'un seul fichier ne soit remplacé.
    refuses = _non_conformes(source)
    if refuses:
        raise RuntimeError(
            "Copie source refusée, rien n'a été remplacé — empreinte invalide "
            "ou fichier absent/illisible : " + ", ".join(refuses)
        )
    # Une copie interrompue laisserait un modèle à moitié remplacé sous un
    # témoin qui dirait le contraire.
    temoin.unlink(missing_ok=True)
    modele.mkdir(parents=True, exist_ok=True)
    for nom in EMPREINTES:
        # Un fichier en lecture seule (copy2 recopie le mode de sa source)
        # faisait lever PermissionError à copy2 : le poids refusé ne se
        # remplaçait plus depuis une copie saine.
        _retirer(modele / nom)
        shutil.copy2(source / nom, modele / nom)


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
    temoin = racine / "installed.json"
    # 28/09/2026 : un refus laissait l'ancien installed.json, et
    # reconnaissance_mlx.moteur_installe() disait l'oreille prête sur un
    # fichier qu'on venait de refuser (§5). Le témoin tombe désormais avant
    # que le modèle ne change et n'est réécrit qu'après vérification : un
    # téléchargement, une copie ou une vérification qui échoue ne laisse rien
    # dire « installé ».
    if args.model_source:
        copier(args.model_source, modele, temoin)
    else:
        temoin.unlink(missing_ok=True)
        script = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({MODELE!r}, revision={REVISION!r}, "
            f"local_dir={str(modele)!r}, token=False, "
            f"allow_patterns={list(EMPREINTES)!r})"
        )
        subprocess.run([str(python), "-c", script], check=True)
    verifier(modele)
    temoin.write_text(
        json.dumps({"model": MODELE, "revision": REVISION, "sha256": EMPREINTES})
    )
    print("Reconnaissance installée et vérifiée ; choix du moteur inchangé.")


if __name__ == "__main__":
    main()
