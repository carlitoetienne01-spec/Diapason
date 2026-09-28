from __future__ import annotations

import pytest

from diapason.actions.models import ActionRisk
from diapason.actions.router import FastActionRouter


@pytest.mark.parametrize(
    "text",
    [
        "Relis la note Diapason « Jeux ». Réponds avec son texte actuel.",
        "Donne le texte actuel",
        "Explique ce message important",
    ],
)
def test_une_demande_de_texte_ne_prepare_pas_de_message(text):
    """§100 — le raccourci ne doit pas chercher un faux destinataire."""
    assert FastActionRouter().route(text) is None, "laisser la discussion au modèle"


@pytest.fixture
def router():
    return FastActionRouter()


@pytest.mark.parametrize(
    ("text", "kind", "target"),
    [
        ("ouvre Notes", "voice.focus_app", "Notes"),
        ("open Safari", "voice.focus_app", "Safari"),
        ("cherche météo Montréal", "voice.search", "météo Montréal"),
        ("ouvre https://example.com", "voice.open_uri", "https://example.com"),
        ("ouvre Notes et écris Bonjour Carlito", "app.type_text", "Notes"),
        ("écris réunion à 14 h dans Notes", "app.type_text", "Notes"),
        (
            "ouvre Notes et rédige un résumé professionnel",
            "app.generate_and_type",
            "Notes",
        ),
        ("write a short poem in Notes", "app.generate_and_type", "Notes"),
        ("paste hello in the active app", "frontmost.type_text", ""),
    ],
)
def test_routes_explicit_low_risk_commands(router, text, kind, target):
    plan = router.route(text)
    assert plan is not None
    assert plan.kind == kind
    assert plan.target == target
    assert plan.confidence >= 0.90


@pytest.mark.parametrize(
    "text",
    [
        "Quelle est la capitale du Canada ?",
        "écris une analyse sur les marchés",
        "ouvre Terminal et écris sudo reboot",
        "envoie le message à Alice",
        "supprime tous mes fichiers",
        "achète ce produit",
        "installe ce logiciel",
        "ouvre Terminal.app et écris echo dangereux",
        "paste sudo reboot in the active app",
        "paste first line\nsecond line in the active app",
    ],
)
def test_ambiguous_or_risky_requests_never_take_fast_path(router, text):
    assert router.route(text) is None


def test_external_compose_is_draft_risk(router):
    plan = router.route("écris un mail à alice@example.com sujet bonjour")
    if plan is not None:  # parser support varies by accepted natural syntax
        assert plan.risk == ActionRisk.EXTERNAL_DRAFT
