"""Ouvrir une copie SVG validée dans l'éditeur local explicitement demandé."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from diapason.core.paths import get_data_dir
from diapason.succes.export_visuel import verifier_export
from diapason.succes.store import SuccesError

router = APIRouter(prefix="/v1/visuals", tags=["visuals"])


def trouver_inkscape() -> str | None:
    trouve = shutil.which("inkscape")
    if trouve:
        return trouve
    candidats: list[Path] = []
    if sys.platform == "darwin":
        candidats = [Path("/Applications/Inkscape.app/Contents/MacOS/inkscape")]
    elif sys.platform == "win32":
        candidats = [
            Path(base) / "Inkscape" / "bin" / "inkscape.exe"
            for cle in ("ProgramFiles", "ProgramFiles(x86)")
            if (base := os.environ.get(cle))
        ]
    return next((str(p) for p in candidats if p.is_file()), None)


class CopieSVG(BaseModel):
    model_config = ConfigDict(extra="forbid")
    svg: str = Field(max_length=500_000)


@router.get("/inkscape")
def disponibilite_inkscape():
    return {"available": trouver_inkscape() is not None}


@router.post("/inkscape")
def ouvrir_inkscape(demande: CopieSVG):
    donnees = demande.svg.encode("utf-8")
    try:
        verifier_export(donnees, ".svg")
    except SuccesError as exc:
        raise HTTPException(422, str(exc)) from exc
    executable = trouver_inkscape()
    if executable is None:
        raise HTTPException(503, "Inkscape n’est pas installé.")
    dossier = get_data_dir() / "visuals"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / f"diapason-{uuid4().hex}.svg"
    # Une copie unique : l'éditeur ne réécrit ni le chat ni un document choisi
    # par un autre appel ; aucun argument ou programme fourni par le modèle.
    with fichier.open("xb") as sortie:
        sortie.write(donnees)
    try:
        subprocess.Popen(
            [executable, str(fichier)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        fichier.unlink(missing_ok=True)
        raise HTTPException(503, "L’éditeur n’a pas pu être lancé.") from exc
    # §100 : création du processus, pas une confirmation de fenêtre affichée.
    return {"status": "openingRequested"}
