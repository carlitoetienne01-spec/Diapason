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

import json
import pathlib
import sys
import tempfile
from typing import Any

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


def rendre(etat: dict[str, Any]) -> str:
    """Le fichier ``vie_rappels.json`` pour cet ``etat``, octet pour octet."""
    with tempfile.TemporaryDirectory() as dossier:
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
