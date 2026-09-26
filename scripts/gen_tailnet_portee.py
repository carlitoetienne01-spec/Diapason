#!/usr/bin/env python
"""Régénère l'instantané de ce que le téléphone atteint par le tailnet.

    .venv/bin/python scripts/gen_tailnet_portee.py

26/09/2026, phase 2 du plan mobile (étape 3). ``tests/contract/
tailnet_portee.json`` classe CHAQUE route de l'application : ouverte,
session ou refusée. Une route ajoutée par une autre session, que personne
n'a classée pour le téléphone, fait échouer le test de contrat — et reste
refusée par la passerelle tant qu'on ne l'a pas écrite dans
``src/diapason/server/portee_tailnet.py``.

À lancer dans le MÊME commit que la route ou le classement qui a bougé.
Régénérer ne classe rien : une route non classée apparaît ici avec la
valeur null, et le test la refuse encore.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

RACINE = Path(__file__).resolve().parents[1]
SORTIE = RACINE / "tests" / "contract" / "tailnet_portee.json"


def app_maximale(dossier: Path):  # noqa: ANN201
    """L'application avec TOUTES ses routes, y compris les conditionnelles.

    Trois familles n'existent que selon l'installation : les routes du
    gestionnaire d'agents (``agent_manager``), les webhooks
    (``webhook_config``) et le bundle (``server/static`` construit). Un
    instantané pris sans elles laisserait le rattrape-tout du bundle — la
    porte même de la WebView — hors de tout classement.

    Le foyer est *dossier* : ``create_app`` ouvre la base des conversations
    et lit la configuration, et rien de ceci ne doit toucher ``~/.diapason``.
    """
    import diapason.server.app as module

    faux = dossier / "serveur"
    (faux / "static" / "assets").mkdir(parents=True, exist_ok=True)
    (faux / "static" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    ancien = module.__file__
    # create_app cherche le bundle à côté de son propre fichier : on lui
    # montre un bundle factice le temps de la construction.
    module.__file__ = str(faux / "app.py")
    try:
        return module.create_app(
            MagicMock(),
            "modele-de-banc",
            api_key="banc-" + "0" * 40,
            agent_manager=MagicMock(),
            webhook_config={"twilio_auth_token": "banc"},
        )
    finally:
        module.__file__ = ancien


def portee(dossier: Path) -> dict[str, str | None]:
    from diapason.server.portee_tailnet import portee_de_l_app

    return portee_de_l_app(app_maximale(dossier))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="portee-tailnet-") as brut:
        dossier = Path(brut)
        foyer = dossier / "foyer"
        foyer.mkdir()
        os.environ["DIAPASON_HOME"] = str(foyer)
        os.environ["DIAPASON_NO_UPDATE_CHECK"] = "1"
        table = portee(dossier)
    SORTIE.write_text(
        json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    non_classees = sorted(cle for cle, classe in table.items() if classe is None)
    print(f"{len(table)} routes classées dans {SORTIE.relative_to(RACINE)}")
    if non_classees:
        print(f"{len(non_classees)} NON classées (le test les refusera) :")
        for cle in non_classees:
            print(f"  {cle}")


if __name__ == "__main__":
    main()
