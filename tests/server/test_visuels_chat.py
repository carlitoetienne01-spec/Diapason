"""§5 : seul un client capable de rendre les visuels les annonce au modèle."""

from unittest.mock import MagicMock

import pytest

from diapason.core.types import Message, Role
from diapason.server.models import ChatCompletionRequest
from diapason.server.visuels_chat import (
    CONSIGNE_VISUELS,
    EXEMPLE_IKIGAI,
    instruire_visuels,
)


class TestVisuelsDuChat:
    @pytest.mark.parametrize(
        "demande",
        [
            "fait moi un diagramme ikigai en 3D",
            "Dessine un schéma Ikigaï en relief",
            "Draw an ikigai diagram in 3D",
        ],
    )
    def test_ikigai_recoit_un_contrat_a_quatre_dimensions(self, demande):
        origine = [Message(role=Role.USER, content=demande)]
        resultat = instruire_visuels(origine)
        assert EXEMPLE_IKIGAI in resultat[0].content, (
            "§5 : un point 3D ne remplace pas les ensembles demandés"
        )
        assert resultat[-1].content == demande, "la demande n'est pas réécrite"

    def test_l_exemple_ikigai_ne_contamine_pas_la_demande_suivante(self):
        resultat = instruire_visuels(
            [
                Message(role=Role.USER, content="Diagramme Ikigai en 3D"),
                Message(role=Role.ASSISTANT, content="Le voici"),
                Message(role=Role.USER, content="Trace une mesure au point 0,0,0"),
            ]
        )
        assert EXEMPLE_IKIGAI not in resultat[0].content, (
            "les mesures légitimes restent des graphiques numériques"
        )

    def test_la_consigne_preserve_l_identite_et_l_historique(self):
        origine = [
            Message(role=Role.SYSTEM, content="Identité"),
            Message(role=Role.USER, content="Dessine"),
        ]
        resultat = instruire_visuels(origine)
        assert resultat[0].content.startswith("Identité"), "l'identité reste en place"
        assert CONSIGNE_VISUELS in resultat[0].content, (
            "le contrat de rendu atteint le modèle"
        )
        assert origine[0].content == "Identité", (
            "le cache de conversation ne doit pas être muté"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("active", [False, True])
    async def test_la_route_stream_transmet_la_capacite_du_client(
        self, monkeypatch, active
    ):
        from diapason.server.routes import _handle_stream

        vus = []

        async def flux(model, messages, temperature, max_tokens):
            vus.extend(messages)
            yield (
                '```svg\n<svg xmlns="http://www.w3.org/2000/svg"'
                ' viewBox="0 0 10 10"/>\n```'
            )

        monkeypatch.setattr("diapason.server.cloud_router.stream_cloud", flux)
        requete = ChatCompletionRequest(
            model="gpt-test",
            stream=True,
            visuals=active,
            messages=[{"role": "user", "content": "Dessine"}],
        )
        reponse = await _handle_stream(MagicMock(), requete.model, requete)
        corps = "".join([part async for part in reponse.body_iterator])
        assert "[DONE]" in corps, "le flux doit terminer normalement"
        assert any(CONSIGNE_VISUELS in (m.content or "") for m in vus) == active, (
            "un client texte ne reçoit pas le contrat graphique"
        )


@pytest.mark.parametrize(
    "texte",
    [
        "Dessine le cycle de l'eau",
        "Trace une courbe",
        "Draw a diagram",
        "Illustre ce concept",
        "fait moi un diagramme ikigai en 3D",
    ],
)
def test_la_creation_visuelle_garde_le_modele_choisi(texte):
    from diapason.server.tour_leger import est_un_tour_leger

    assert not est_un_tour_leger([Message(role=Role.USER, content=texte)]), (
        "un dessin n'est pas une question factuelle à rerouter vers le petit modèle"
    )
