"""§5 : seul un client capable de rendre les visuels les annonce au modèle."""

from unittest.mock import MagicMock

import pytest

from diapason.core.types import Message, Role
from diapason.server.models import ChatCompletionRequest
from diapason.server.visuels_chat import CONSIGNE_VISUELS, instruire_visuels


class TestVisuelsDuChat:
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
    ],
)
def test_la_creation_visuelle_garde_le_modele_choisi(texte):
    from diapason.server.tour_leger import est_un_tour_leger

    assert not est_un_tour_leger([Message(role=Role.USER, content=texte)]), (
        "un dessin n'est pas une question factuelle à rerouter vers le petit modèle"
    )
