"""Figures locales à partir de données bornées, jamais de Python fourni au chat."""

from __future__ import annotations

import io
import textwrap
import threading
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

Nombre = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1e12, le=1e12)]
Texte = Annotated[str, Field(strict=True, max_length=120)]
Vecteur = Annotated[list[Nombre], Field(min_length=1, max_length=300)]
Couleur = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Serie(Strict):
    name: Texte
    x: Vecteur
    y: Vecteur | None = None
    errorY: Vecteur | None = None


class FigureScientifique(Strict):
    title: Annotated[str, Field(strict=True, min_length=1, max_length=180)]
    type: Literal["line", "scatter", "histogram", "heatmap"]
    xLabel: Texte = ""
    yLabel: Texte = ""
    series: Annotated[list[Serie], Field(max_length=6)] = []
    bins: Annotated[int, Field(strict=True, ge=2, le=60)] = 12
    matrix: (
        Annotated[
            list[Annotated[list[Nombre], Field(min_length=1, max_length=20)]],
            Field(min_length=1, max_length=20),
        ]
        | None
    ) = None
    xLabels: Annotated[list[Texte], Field(max_length=20)] | None = None
    yLabels: Annotated[list[Texte], Field(max_length=20)] | None = None
    source: Annotated[str, Field(strict=True, max_length=500)] | None = None
    sample: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def verifier_dimensions(self):
        if not self.title.strip():
            raise ValueError("Le titre est vide.")
        if self.type == "heatmap":
            m = self.matrix
            if not m or self.series or any(len(ligne) != len(m[0]) for ligne in m):
                raise ValueError("La matrice doit être rectangulaire, sans séries.")
            if self.xLabels is not None and len(self.xLabels) != len(m[0]):
                raise ValueError("Libellés X incohérents.")
            if self.yLabels is not None and len(self.yLabels) != len(m):
                raise ValueError("Libellés Y incohérents.")
        else:
            if not self.series or any(
                v is not None for v in (self.matrix, self.xLabels, self.yLabels)
            ):
                raise ValueError("Séries attendues, sans matrice.")
            # 300 points au total : borne aussi les barres d'erreur et le SVG
            # conservé/exporté (2500 éléments maximum), pas seulement le JSON.
            if sum(len(s.x) for s in self.series) > 300:
                raise ValueError("Trop de points.")
            for s in self.series:
                if self.type == "histogram":
                    if s.y is not None or s.errorY is not None:
                        raise ValueError(
                            "Un histogramme prend les observations dans x."
                        )
                elif s.y is None or len(s.x) != len(s.y):
                    raise ValueError("Chaque X doit avoir son Y.")
                if s.errorY is not None and (
                    len(s.errorY) != len(s.x) or any(n < 0 for n in s.errorY)
                ):
                    raise ValueError("Incertitudes positives, une par point.")
        return self


class PaletteFigure(Strict):
    background: Couleur
    text: Couleur
    accent: Couleur
    border: Couleur
    mono: bool = False


class DemandeFigure(Strict):
    figure: FigureScientifique
    palette: PaletteFigure
    locale: Literal["fr", "en"] = "fr"


router = APIRouter(prefix="/v1/visuals", tags=["visuals"])
_VERROU = threading.Lock()


@lru_cache(maxsize=16)  # 16 × 500 Ko au plus ; relecture/thème n'infèrent rien.
def dessiner_figure(requete_json: str) -> dict:
    from matplotlib import rc_context
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.figure import Figure

    demande = DemandeFigure.model_validate_json(requete_json)
    d, p = demande.figure, demande.palette
    # Matplotlib partage rcParams entre fils. Un import pyplot ouvrirait en
    # outre une fenêtre macOS depuis un worker : Figure + SVG restent hors GUI.
    with (
        _VERROU,
        rc_context(
            {
                "svg.fonttype": "none",
                "svg.hashsalt": "diapason",
                "text.usetex": False,
                "text.parse_math": False,
                "font.family": "DejaVu Sans Mono" if p.mono else "DejaVu Sans",
            }
        ),
    ):
        fig = Figure(figsize=(8, 5.8), facecolor=p.background)
        FigureCanvasSVG(fig)
        ax = fig.add_axes((0.14, 0.28, 0.75, 0.52), facecolor=p.background)
        couleurs = [p.accent, "#4287ab", "#ac7449", "#8470a6", "#58956b", "#b56576"]
        ax.tick_params(colors=p.text, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(p.border)
        ax.set_xlabel(textwrap.fill(d.xLabel, 60), color=p.text, fontsize=10)
        ax.set_ylabel(textwrap.fill(d.yLabel, 32), color=p.text, fontsize=10)
        if d.type == "heatmap":
            carte = LinearSegmentedColormap.from_list(
                "diapason", [p.background, p.accent]
            )
            image = ax.pcolormesh(d.matrix, cmap=carte, rasterized=False)
            ax.invert_yaxis()
            if d.xLabels:
                ax.set_xticks(
                    [i + 0.5 for i in range(len(d.xLabels))],
                    d.xLabels,
                    rotation=45,
                    ha="right",
                )
            if d.yLabels:
                ax.set_yticks([i + 0.5 for i in range(len(d.yLabels))], d.yLabels)
            barre = fig.colorbar(image, ax=ax, pad=0.03)
            if barre.solids is not None:
                barre.solids.set_rasterized(False)
            barre.ax.tick_params(colors=p.text)
        else:
            observations = [n for s in d.series for n in s.x]
            debut, fin = min(observations), max(observations)
            if debut == fin:
                debut, fin = debut - 0.5, fin + 0.5
            bornes = [debut + (fin - debut) * i / d.bins for i in range(d.bins + 1)]
            for i, s in enumerate(d.series):
                couleur = couleurs[i]
                if d.type == "histogram":
                    ax.hist(s.x, bins=bornes, color=couleur, alpha=0.65, label=s.name)
                elif s.errorY is not None:
                    ax.errorbar(
                        s.x,
                        s.y,
                        yerr=s.errorY,
                        color=couleur,
                        fmt="o-" if d.type == "line" else "o",
                        capsize=3,
                        label=s.name,
                    )
                elif d.type == "line":
                    ax.plot(s.x, s.y, color=couleur, label=s.name)
                else:
                    ax.scatter(s.x, s.y, color=couleur, label=s.name, s=24)
            ax.grid(alpha=0.2, color=p.border)
            fig.legend(
                loc="lower center",
                bbox_to_anchor=(0.5, 0.12),
                ncol=2,
                fontsize=8,
                facecolor=p.background,
                labelcolor=p.text,
                edgecolor=p.border,
            )
        fig.suptitle(textwrap.fill(d.title, 65), color=p.text, fontsize=13, y=0.97)
        origine = (
            ("Données d’exemple · " if demande.locale == "fr" else "Example data · ")
            if d.sample
            else ""
        )
        origine += (
            (
                ("Origine indiquée : " if demande.locale == "fr" else "Stated origin: ")
                + d.source
            )
            if d.source
            else (
                "Origine non précisée"
                if demande.locale == "fr"
                else "Origin not specified"
            )
        )
        fig.text(
            0.06,
            0.02,
            textwrap.fill(origine, 100),
            fontsize=7,
            color=p.text,
            va="bottom",
        )
        sortie = io.StringIO()
        fig.savefig(sortie, format="svg", metadata={"Date": None}, bbox_inches="tight")
        fig.clear()
    # La déclaration DOCTYPE et les métadonnées RDF sont émises par le moteur,
    # pas par le modèle. Les enlever permet de garder le même export sûr.
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    racine = ET.fromstring(sortie.getvalue())
    for el in list(racine):
        if el.tag.endswith("}metadata"):
            racine.remove(el)
    titre = ET.SubElement(racine, "{http://www.w3.org/2000/svg}title")
    titre.text = d.title
    svg = ET.tostring(racine, encoding="unicode")
    if len(svg.encode()) > 500_000 or len(list(racine.iter())) > 2500:
        raise ValueError("Figure trop complexe.")
    return {"svg": svg}


@router.post("/matplotlib")
def rendre_matplotlib(demande: DemandeFigure):
    """§5 : rendu réel ; route synchrone pour ne pas bloquer le flux du chat."""
    try:
        return dessiner_figure(demande.model_dump_json())
    except ImportError as exc:
        raise HTTPException(
            503, "Le moteur scientifique n’est pas disponible."
        ) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, "Cette figure ne peut pas être tracée.") from exc
