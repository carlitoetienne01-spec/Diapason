"""§5/100 : chiffres conservés, rendu vectoriel réel, aucun code exécuté."""

import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from diapason.server.graphiques_scientifiques import (
    DemandeFigure,
    FigureScientifique,
    dessiner_figure,
    router,
)
from diapason.succes.export_visuel import verifier_export

PALETTE = {
    "background": "#17231b",
    "text": "#d0f0c0",
    "accent": "#4de89d",
    "border": "#446644",
}


def figure(type="scatter"):
    return {
        "title": "Distance & durée",
        "type": type,
        "series": [
            {
                "name": "Essai",
                "x": [1, 2, 3],
                **(
                    {}
                    if type == "histogram"
                    else {"y": [3, 4, 6], "errorY": [0.1, 0.2, 0.3]}
                ),
            }
        ],
        "xLabel": "Temps (s)",
        "sample": True,
        "source": "Exemple fictif",
    }


@pytest.mark.parametrize("type", ["line", "scatter", "histogram", "heatmap"])
def test_chaque_figure_produit_un_svg_exportable(type):
    contenu = (
        figure(type)
        if type != "heatmap"
        else {
            "title": "Matrice",
            "type": type,
            "matrix": [[1, 2], [3, 4]],
            "xLabels": ["A", "B"],
            "yLabels": ["C", "D"],
            "sample": True,
        }
    )
    demande = DemandeFigure(figure=contenu, palette=PALETTE)
    svg = dessiner_figure(demande.model_dump_json())["svg"]
    verifier_export(svg.encode(), ".svg")
    assert "#4de89d" in svg, "le thème doit atteindre le vrai moteur"
    assert "Données d’exemple" in svg, "la simulation doit suivre l’export"
    assert "image" not in [e.tag.split("}")[-1] for e in ET.fromstring(svg).iter()], (
        "le SVG reste vectoriel"
    )
    assert "<!DOCTYPE" not in svg, "le lecteur partagé refuse les déclarations"


@pytest.mark.parametrize(
    "mutation",
    [
        {"series": [{"name": "X", "x": [1, 2], "y": [1]}]},
        {"series": [{"name": "X", "x": [True], "y": [1]}]},
        {"series": [{"name": "X", "x": [float("nan")], "y": [1]}]},
        {"series": [{"name": "X", "x": [1], "y": [1], "errorY": [-1]}]},
        {"series": [{"name": "X", "x": [1] * 151, "y": [1] * 151}] * 2},
        {"code": "__import__('os').system('false')"},
        {"type": "heatmap", "series": [], "matrix": [[1, 2], [3]]},
        {"type": "heatmap", "series": [], "matrix": [[1, 2]], "xLabels": ["a"]},
        {"bins": 100000},
        {"title": " "},
        {"sample": "false"},
    ],
)
def test_les_donnees_invalides_ne_parviennent_pas_au_moteur(mutation):
    with pytest.raises(ValidationError):
        FigureScientifique.model_validate({**figure(), **mutation})


def test_la_limite_de_points_reste_exportable_avec_incertitudes():
    d = figure()
    d["series"] = [
        {
            "name": "300 points",
            "x": list(range(300)),
            "y": list(range(300)),
            "errorY": [0.5] * 300,
        }
    ]
    svg = dessiner_figure(DemandeFigure(figure=d, palette=PALETTE).model_dump_json())[
        "svg"
    ]
    verifier_export(svg.encode(), ".svg")
    assert len(list(ET.fromstring(svg).iter())) <= 2500, (
        "les plafonds d’entrée et de sortie doivent s’accorder"
    )


def test_le_texte_reste_du_texte_et_les_rendus_paralleles_gardent_leur_palette():
    def rendre(couleur):
        d = {**figure(), "title": "<script>alert(1)</script> $x$"}
        return dessiner_figure(
            DemandeFigure(
                figure=d, palette={**PALETTE, "accent": couleur}
            ).model_dump_json()
        )["svg"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        svg1, svg2 = list(pool.map(rendre, ["#112233", "#aabbcc"]))
    assert "#112233" in svg1 and "#aabbcc" not in svg1, (
        "rcParams ne doivent pas mélanger les thèmes"
    )
    assert "#aabbcc" in svg2, "le second rendu garde sa palette"
    assert "<script>" not in svg1, "le titre ne devient jamais un élément actif"


def test_la_route_valide_le_corps_et_reutilise_le_rendu():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    d = {"figure": figure(), "palette": PALETTE}
    assert (
        client.post(
            "/v1/visuals/matplotlib", json={**d, "code": "print(1)"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/visuals/matplotlib",
            json={**d, "palette": {**PALETTE, "accent": "url(https://x)"}},
        ).status_code
        == 422
    )
    dessiner_figure.cache_clear()
    r = client.post("/v1/visuals/matplotlib", json=d)
    suivant = client.post("/v1/visuals/matplotlib", json=d)
    assert r.status_code == 200 and r.json() == suivant.json(), (
        "une relecture ne change pas le dessin"
    )
    assert dessiner_figure.cache_info().hits == 1, (
        "le moteur n’est pas relancé à chaque relecture"
    )
    assert FigureScientifique.model_validate(d["figure"]).series[0].y == [3, 4, 6], (
        "les mesures restent exactes"
    )
    assert json.loads(DemandeFigure(**d).model_dump_json())["figure"]["sample"] is True
