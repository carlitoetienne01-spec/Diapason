"""Les règles d'écriture du chat : présentes, bien placées, jamais doublées."""

from __future__ import annotations

from diapason.core.types import Message, Role
from diapason.prompt.regles_ecrites import REGLES_ECRITES, habiller_pour_le_chat
from diapason.server.routes import _ensure_identity_prompt


class TestHabiller:
    def test_l_identite_precede_la_maniere(self):
        habille = habiller_pour_le_chat("Tu es Diapason.")
        assert habille.startswith("Tu es Diapason.")
        assert habille.endswith(REGLES_ECRITES)

    def test_un_gabarit_vide_garde_au_moins_la_maniere(self):
        assert habiller_pour_le_chat("") == REGLES_ECRITES
        assert habiller_pour_le_chat("   ") == REGLES_ECRITES


class TestDansLeChat:
    def test_le_chat_recoit_les_regles_d_ecriture(self):
        messages = [Message(role=Role.USER, content="Bonjour")]
        prepares = _ensure_identity_prompt(messages, None, client_supplied_system=False)
        identite = prepares[0].content
        assert prepares[0].role == Role.SYSTEM
        assert "Manière d'écrire" in identite
        assert "La première phrase répond" in identite

    def test_un_system_du_client_ne_recoit_rien(self):
        # Un client qui fournit son propre cadrage garde la main : ni
        # identité ni règles — seule l'horloge est préfixée.
        messages = [
            Message(role=Role.SYSTEM, content="Cadrage du client."),
            Message(role=Role.USER, content="Bonjour"),
        ]
        prepares = _ensure_identity_prompt(messages, None, client_supplied_system=True)
        assert not any("Manière d'écrire" in (m.content or "") for m in prepares[:1])
        assert prepares[0].role == Role.SYSTEM  # l'ancre horaire
        assert "MAINTENANT" in prepares[0].content
