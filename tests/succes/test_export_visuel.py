"""§5 : les exports restent des documents, jamais du code actif."""

import base64
from pathlib import Path

import pytest

from diapason.succes.export_visuel import verifier_export
from diapason.succes.photos import SuccesPhotosStore
from diapason.succes.store import SuccesError


def dessin(corps):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        + corps
        + "</svg>"
    ).encode()


class TestExportVisuel:
    def test_un_dessin_et_un_png_s_enregistrent_sans_conversion(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        for extension, data in [
            (".svg", dessin('<rect width="20" height="20"/>')),
            (".png", b"\x89PNG\r\n\x1a\n"),
        ]:
            chemin = tmp_path / ("dessin" + extension)
            resultat = SuccesPhotosStore.write_export(
                str(chemin), base64.b64encode(data).decode()
            )
            assert chemin.read_bytes() == data, "l'export doit conserver ses octets"
            assert resultat["bytes"] == len(data), "le succès est mesuré après écriture"

    @pytest.mark.parametrize(
        "corps",
        [
            "<script>alert(1)</script>",
            "<foreignObject/>",
            '<rect onload="alert(1)"/>',
            '<image href="https://example.com/x"/>',
            '<use href="/secret"/>',
            '<style>@import "https://example.com";</style>',
            '<rect fill="url(//example.com/x)"/>',
        ],
    )
    def test_un_svg_actif_ou_externe_est_refuse(self, corps):
        with pytest.raises(SuccesError):
            verifier_export(dessin(corps), ".svg")

    def test_les_fleches_et_degrades_internes_restent_exportables(self):
        verifier_export(
            dessin('<defs><marker id="f"/></defs><path marker-end="url(#f)"/>'), ".svg"
        )

    def test_un_lien_symbolique_ne_peut_pas_sortir_du_dossier_personnel(
        self, tmp_path, monkeypatch
    ):
        maison = tmp_path / "maison"
        maison.mkdir()
        dehors = tmp_path / "prive.svg"
        dehors.write_text("original")
        lien = maison / "dessin.svg"
        lien.symlink_to(dehors)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: maison))
        with pytest.raises(SuccesError, match="lien symbolique"):
            SuccesPhotosStore.write_export(
                str(lien), base64.b64encode(dessin("")).decode()
            )
        assert dehors.read_text() == "original", (
            "aucun fichier visé par un lien n'est modifié"
        )
