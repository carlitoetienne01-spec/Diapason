"""Ce que le Mac rend pour les rappels du téléphone, après l'import de sa Life OS.

26/09/2026, phase 3 étape 9 (docs/development/diapason-mobile.md). Après
l'import, le planificateur de notifications du téléphone ne lit plus son
``LifeOsState`` : il lit ``/v1/vie`` par un adaptateur
(``lib/services/vie/rappels_du_mac.dart``). La preuve qu'il rend les mêmes
heures exige les DEUX moitiés réelles :

- ``test/rappels/etat_rappels.json``, écrit par le vrai ``LifeOsState.toJson()``
  (``test/rappels/etat_rappels_test.dart``) ;
- ``test/rappels/vie_rappels.json``, écrit ICI : cet état importé par la vraie
  route ``POST /v1/vie/import/legacy``, puis relu par les trois routes que
  l'adaptateur appelle, telles quelles.

Une réponse de ``/v1/vie`` écrite à la main par le Dart aurait porté l'idée
que le Dart se fait du Mac. ``tests/contract/test_vie_rappels.py`` refait ce
fichier en mémoire et exige qu'il soit identique à celui du dépôt mobile.

    .venv/bin/python scripts/gen_vie_rappels.py [racine/du/depot/mobile]
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import sys
import tempfile
from datetime import date
from typing import Any
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.vie.routes import monter, set_store_for_tests
from diapason.vie.sync import VieSyncStore

MOBILE = pathlib.Path.home() / "Projets/diapason_mobile"
ETAT = "test/rappels/etat_rappels.json"
SORTIE = "test/rappels/vie_rappels.json"

# La plage des coches que l'adaptateur demanderait le 27/09/2026 (120 jours
# en arrière, les 14 jours planifiés en avant — ``LecteurDesRappels.lire``,
# que le test Dart appelle avec ce jour-là). L'adaptateur, lui, la calcule
# depuis le jour courant.
COCHES_DU = "2026-05-30"
COCHES_AU = "2026-10-11"

# Les trois lectures de l'adaptateur (``LecteurDesRappels.lire``), dans
# l'ordre où il les fait.
LECTURES = (
    ("taches", "/v1/vie/tasks", {"include_done": "false"}),
    ("habitudes", "/v1/vie/habits", {}),
    ("coches", "/v1/vie/habits/logs", {"from": COCHES_DU, "to": COCHES_AU}),
)


# Le jour que simule ``adaptateur_rappels_test.dart`` (``aujourdhui:
# DateTime(2026, 9, 27)``). 27/09/2026 : sans lui, ``GET /v1/vie/habits``
# datait sa réponse du jour RÉEL (``date``, ``done`` du jour) — le fichier
# engendré le 26 ne concordait déjà pas avec le test Dart, et le cliquet
# rougissait à chaque minuit, une habitude passant de cochée à non cochée.
JOUR = date(2026, 9, 27)


# Les modules du domaine qui lisent ``date.today()`` : ``workspace`` date les
# habitudes (``GET /v1/vie/habits``), ``store`` et ``continuity`` les tâches
# et les archives. Figer seulement ``continuity`` (premier jet) laissait
# passer le jour réel par ``workspace``.
MODULES_DATES = (
    "diapason.vie.workspace",
    "diapason.vie.store",
    "diapason.vie.continuity",
)


class _JourFige(date):
    @classmethod
    def today(cls) -> date:  # type: ignore[override]
        return JOUR


def figer_le_jour(classe: type[date] = _JourFige) -> contextlib.ExitStack:
    """Remplace ``date`` par ``classe`` dans chaque module de ``MODULES_DATES``."""
    pile = contextlib.ExitStack()
    for module in MODULES_DATES:
        pile.enter_context(mock.patch(f"{module}.date", classe))
    return pile


def rendre(etat: dict[str, Any]) -> str:
    """Le fichier ``vie_rappels.json`` pour cet ``etat``, octet pour octet,
    au jour ``JOUR`` quel que soit le jour réel."""
    with figer_le_jour(), tempfile.TemporaryDirectory() as dossier:
        magasin = VieSyncStore(pathlib.Path(dossier) / "vie.db")
        set_store_for_tests(magasin)
        try:
            app = FastAPI()
            monter(app)
            client = TestClient(app)
            import_ = client.post(
                "/v1/vie/import/legacy",
                json={"snapshot": etat, "source": "Diapason mobile — rappels"},
            )
            import_.raise_for_status()
            reponses: dict[str, Any] = {}
            for nom, chemin, requete in LECTURES:
                r = client.get(chemin, params=requete)
                r.raise_for_status()
                reponses[nom] = {
                    "chemin": chemin,
                    "requete": requete,
                    "corps": r.json(),
                }
        finally:
            set_store_for_tests(None)
    return json.dumps(reponses, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    racine = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else MOBILE
    etat = json.loads((racine / ETAT).read_text(encoding="utf-8"))
    (racine / SORTIE).write_text(rendre(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE}")


if __name__ == "__main__":
    main()
