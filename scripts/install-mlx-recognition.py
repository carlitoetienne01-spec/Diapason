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
# Les liens, eux, n'arrivent jamais jusqu'à la vérification : _sans_lien()
# les défait avant tout téléchargement et toute copie. Ce commentaire disait
# le 28/09/2026 qu'aucune écriture ne sortait de model/ parce que les deux
# noms sont à sa racine ; c'était faux pour le téléchargement : quand les
# métadonnées de local_dir manquent (installation par --model-source) ou sont
# plus vieilles que la cible, huggingface_hub recopie son cache PAR-DESSUS
# un weights.safetensors lié (shutil.copyfile), donc dans le fichier de
# l'utilisateur, que la vérification déclarait ensuite conforme.


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


def _liens(modele: Path) -> list[str]:
    if not modele.is_dir():
        return []
    return sorted(
        chemin.relative_to(modele).as_posix()
        for chemin in modele.rglob("*")
        if chemin.is_symlink()
    )


def _sans_lien(modele: Path, operation: str) -> None:
    # Tout lien sous model/, pas seulement les deux noms : le hub écrit aussi
    # ses métadonnées et ses verrous sous .cache/huggingface/. rglob ne
    # descend pas dans un dossier lié : chaque nom listé n'a de lien qu'à son
    # dernier maillon, et _retirer() défait ce lien sans toucher sa cible.
    liens = _liens(modele)
    for nom in liens:
        _retirer(modele / nom)
    if restes := _liens(modele):
        raise RuntimeError(
            f"Impossible de retirer {', '.join(restes)} (lien symbolique) : "
            "supprimez le lien lui-même, pas sa cible, puis relancez le "
            f"script. Rien n'a été {operation}."
        )
    if liens:
        print(
            "Lien symbolique retiré de model/, sa cible reste intacte : "
            + ", ".join(liens)
        )


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
    # La copie n'écrit que les deux noms, que _retirer() défait déjà un à
    # un ; les autres liens partent quand même, pour qu'une installation
    # réussie ne laisse aucun lien dans model/, quel que soit son chemin.
    _sans_lien(modele, "copié")
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
        _sans_lien(modele, "téléchargé")
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
