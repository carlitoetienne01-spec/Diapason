"""L'appareil photo de la pile de photos tient à un seul attribut.

26/09/2026, phase 5 (docs/development/diapason-mobile.md). Sur le
téléphone, la coquille décide des sources proposées (appareil photo,
galerie, fichiers) d'après l'``accept`` du champ que la page touche. Celui
de ``PilesPhotos.tsx`` (``image/*,.heic,.heif``) donne les trois ; un
``.heic,.heif`` seul retirerait l'appareil photo de la pile.

Contre-épreuve du même jour : le test Dart (``test/coquille/
fichiers_coquille_test.dart``, dépôt mobile) recopiait cet ``accept`` en dur
au lieu de le lire. ``accept=".heic,.heif"`` dans PilesPhotos.tsx laissait
vitest, ``flutter test`` et les tests de contrat verts. Ici, les deux
copies sont confrontées : changer l'une sans l'autre rougit. Hors CI, un
dépôt mobile absent est un ÉCHEC, pas un saut.
"""

from __future__ import annotations

import os
import pathlib
import re

import pytest
from _depot_mobile import depot_mobile

RACINE = pathlib.Path(__file__).resolve().parents[2]
PILES = RACINE / "frontend/src/features/vie/PilesPhotos.tsx"
TEST_DART = "test/coquille/fichiers_coquille_test.dart"


def _en_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _accept_du_bundle() -> list[str]:
    return re.findall(r'accept="([^"]*)"', PILES.read_text(encoding="utf-8"))


def _accept_de_la_coquille() -> list[str]:
    chemin = depot_mobile() / TEST_DART
    try:
        source = chemin.read_text(encoding="utf-8")
    except OSError:
        if _en_ci():
            pytest.skip(f"{chemin} absent du runner de CI")
        pytest.fail(f"{chemin} introuvable ; hors CI, son absence n'est pas un saut.")
    trouve = re.search(r"const acceptDeLaPile = \['([^']*)'\];", source)
    assert trouve, f"acceptDeLaPile introuvable dans {chemin}"
    return [trouve.group(1)]


class TestLAcceptDeLaPileEstLeMemeDesDeuxCotes:
    def test_la_pile_a_un_seul_champ_de_fichier_et_il_accepte_toute_image(self):
        accepts = _accept_du_bundle()
        assert accepts == ["image/*,.heic,.heif"], (
            "l'accept de PilesPhotos.tsx a changé : la coquille décide de "
            "l'appareil photo d'après lui — mets à jour acceptDeLaPile dans "
            f"{TEST_DART} (dépôt mobile) dans le même geste : {accepts}"
        )

    def test_la_coquille_eprouve_l_accept_que_le_bundle_porte_vraiment(self):
        assert _accept_de_la_coquille() == _accept_du_bundle(), (
            "le test Dart éprouve un accept que la pile ne porte plus"
        )
