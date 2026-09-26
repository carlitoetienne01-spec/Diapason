"""Le dépôt mobile se désigne par ``DIAPASON_MOBILE`` (26/09/2026).

Sans elle, une passe lancée avec un ``HOME`` de banc cherchait le dépôt
dans le foyer jetable : 25 échecs sans rapport avec le code. Et la preuve
« à l'octet » ne pouvait porter que sur l'arbre vivant, qu'une autre
session peut être en train de muter.
"""

from __future__ import annotations

import pathlib

from _depot_mobile import VARIABLE, depot_mobile


class TestLeDepotMobileSeDesigne:
    def test_la_variable_l_emporte_sur_le_foyer(self, monkeypatch, tmp_path):
        monkeypatch.setenv(VARIABLE, str(tmp_path / "copie"))
        monkeypatch.setenv("HOME", "/nulle/part")
        assert depot_mobile() == tmp_path / "copie", (
            "une copie désignée doit être lue, quel que soit HOME"
        )

    def test_sans_elle_l_emplacement_habituel(self, monkeypatch):
        monkeypatch.delenv(VARIABLE, raising=False)
        assert depot_mobile() == pathlib.Path.home() / "Projets/diapason_mobile"

    def test_une_variable_vide_ne_designe_pas_la_racine(self, monkeypatch):
        monkeypatch.setenv(VARIABLE, "  ")
        assert depot_mobile() == pathlib.Path.home() / "Projets/diapason_mobile", (
            "une variable vide aurait fait lire le dossier courant"
        )
