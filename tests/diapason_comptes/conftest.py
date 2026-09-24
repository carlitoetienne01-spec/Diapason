"""Un service de comptes en mémoire, un faux expéditeur, une horloge à la main.

Conception : ``docs/development/compte-chiffre.md`` §3 et étape 4 du §6.
Aucun courriel réel ne part d'ici, aucune lecture de ``/etc/diapason``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from diapason_comptes.app import creer_app, creer_contexte
from diapason_comptes.courriel import FileCourriels
from diapason_comptes.secrets_serveur import Configuration, SecretsServeur
from tests.diapason_comptes._outils import (
    FauxExpediteur,
    Horloge,
    Service,
    secrets_de_test,
)


@pytest.fixture
def fabrique(tmp_path: Path) -> Iterator[Callable[..., Service]]:
    """Construit un service ; plusieurs par test si besoin (restauration)."""
    crees: list[Service] = []

    def construire(
        *,
        secrets: SecretsServeur | None = None,
        budget_codes: int = 1000,
        budget_securite: int = 1000,
        inscriptions: bool = True,
        espace_libre: Callable[[Path], int] = lambda _chemin: 100 * 10**9,
        horloge: Horloge | None = None,
        expediteur: FauxExpediteur | None = None,
        file_courriels: Callable[[FauxExpediteur], FileCourriels] | None = None,
        raise_server_exceptions: bool = True,
        dossier: Path | None = None,
    ) -> Service:
        dossier = dossier or tmp_path
        configuration = Configuration(
            chemin_base=dossier / "comptes.db",
            chemin_journal=dossier / "evenements.jsonl",
            budget_codes_jour=budget_codes,
            budget_securite_jour=budget_securite,
            inscriptions_ouvertes=inscriptions,
        )
        secrets = secrets or secrets_de_test()
        horloge = horloge or Horloge()
        expediteur = expediteur or FauxExpediteur()
        ctx = creer_contexte(
            configuration,
            secrets,
            expediteur,
            origine_publique="https://exemple.invalid",
            horloge=horloge,
            espace_libre=espace_libre,
            file_courriels=file_courriels(expediteur) if file_courriels else None,
        )
        app = creer_app(ctx)
        service = Service(
            ctx=ctx,
            app=app,
            client=TestClient(app, raise_server_exceptions=raise_server_exceptions),
            horloge=horloge,
            expediteur=expediteur,
            configuration=configuration,
            secrets=secrets,
        )
        crees.append(service)
        return service

    yield construire
    for service in crees:
        service.expediteur.relache.set()
        try:
            service.ctx.fermer()
        except Exception:  # déjà fermé par le test (restauration)
            pass


@pytest.fixture
def service(fabrique: Callable[..., Service]) -> Service:
    return fabrique()
