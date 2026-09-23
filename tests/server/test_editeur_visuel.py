"""§5, §100 : Inkscape n'est lancé qu'avec une copie sûre, sans faux succès."""

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.server import editeur_visuel as editeur

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<path d="M0 0h5"/></svg>'
)


def client():
    app = FastAPI()
    app.include_router(editeur.router)
    return TestClient(app)


def test_un_editeur_absent_ne_promet_pas_une_ouverture(monkeypatch):
    monkeypatch.setattr(editeur, "trouver_inkscape", lambda: None)
    c = client()
    assert c.get("/v1/visuals/inkscape").json() == {"available": False}
    assert c.post("/v1/visuals/inkscape", json={"svg": SVG}).status_code == 503


def test_la_copie_est_unique_et_les_actions_svg_sont_refusees(monkeypatch, tmp_path):
    monkeypatch.setattr(editeur, "trouver_inkscape", lambda: "/trusted/inkscape")
    monkeypatch.setattr(editeur, "get_data_dir", lambda: tmp_path)
    ouvrir = Mock()
    monkeypatch.setattr(editeur.subprocess, "Popen", ouvrir)
    c = client()
    for svg in [
        SVG.replace("<path", "<script>alert(1)</script><path"),
        SVG.replace('d="M0 0h5"', 'href="https://x"'),
    ]:
        assert c.post("/v1/visuals/inkscape", json={"svg": svg}).status_code == 422
    ouvrir.assert_not_called()
    assert (
        c.post(
            "/v1/visuals/inkscape", json={"svg": SVG, "executable": "evil"}
        ).status_code
        == 422
    )
    for _ in range(2):
        assert c.post("/v1/visuals/inkscape", json={"svg": SVG}).json() == {
            "status": "openingRequested"
        }
    fichiers = list((tmp_path / "visuals").glob("*.svg"))
    assert len(fichiers) == 2, "chaque clic crée une copie indépendante"
    assert all(p.read_text() == SVG for p in fichiers)
    args = ouvrir.call_args.args[0]
    assert args[0] == "/trusted/inkscape" and len(args) == 2
    assert "shell" not in ouvrir.call_args.kwargs, "aucune commande shell"


def test_un_echec_de_lancement_est_signale_et_nettoye(monkeypatch, tmp_path):
    monkeypatch.setattr(editeur, "trouver_inkscape", lambda: "/trusted/inkscape")
    monkeypatch.setattr(editeur, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        editeur.subprocess, "Popen", Mock(side_effect=OSError("failed"))
    )
    assert client().post("/v1/visuals/inkscape", json={"svg": SVG}).status_code == 503
    assert not list((tmp_path / "visuals").glob("*.svg"))
