"""Garde du dossier connecteurs : aucun test ne lit les VRAIS jetons.

Constaté le 24 août 2026, en connectant Google pour de bon : cinq tests
affirmaient « pas connecté » et sont devenus faux le jour où l'utilisateur
s'est connecté — ils lisaient ~/.diapason/connectors/. Un test qui dépend
de l'état réel de la machine ne teste rien ; il photographie.

Même remède que le profil vocal : un répertoire de jetons temporaire par
test. Un test qui veut des identifiants les écrit lui-même dedans.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isoler_les_jetons(tmp_path, monkeypatch):
    faux = tmp_path / "connectors"
    faux.mkdir(parents=True, exist_ok=True)

    from diapason.connectors import oauth

    monkeypatch.setattr(oauth, "_CONNECTORS_DIR", faux)
    # Les connecteurs figent leur chemin par défaut à l'import : on le
    # repointe module par module, sur ceux qui en déclarent un.
    import importlib

    for module, attribut in (
        ("gmail", "_DEFAULT_CREDENTIALS_PATH"),
        ("gcalendar", "_DEFAULT_CREDENTIALS_PATH"),
        ("gcontacts", "_DEFAULT_CREDENTIALS_PATH"),
        ("gdrive", "_DEFAULT_CREDENTIALS_PATH"),
        ("google_tasks", "_DEFAULT_CREDENTIALS_PATH"),
    ):
        try:
            mod = importlib.import_module(f"diapason.connectors.{module}")
        except ImportError:
            continue
        if hasattr(mod, attribut):
            monkeypatch.setattr(mod, attribut, str(faux / f"{module}.json"))
    yield
