"""La voix doit demander l'accord avant une action sensible.

``execute_voice_tool`` appelait ``tool.execute(**args)`` EN DIRECT. Elle
sautait ``ToolExecutor``, et avec lui la politique de capacités, le
garde-frontière, le limiteur de débit et la confirmation.

Or ``mail_send`` et ``messages_send`` figurent dans la liste vocale : une
phrase mal comprise pouvait envoyer un courriel ou un SMS au nom de Carlito
sans que rien ne lui soit demandé. Le commentaire « never auto-send from live
voice — drafts only » ne protégeait que ``mail_compose``.
"""

from __future__ import annotations

import pytest

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.speech.realtime import tools as voix
from diapason.tools._stubs import BaseTool, ToolSpec


class _OutilSensible(BaseTool):
    """Un outil qui exige un accord, comme mail_send."""

    tool_id = "essai_envoi"
    appels: list[dict] = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="essai_envoi",
            description="Envoie quelque chose.",
            parameters={"type": "object", "properties": {}},
            requires_confirmation=True,
        )

    def execute(self, **params):
        _OutilSensible.appels.append(params)
        return ToolResult(tool_name="essai_envoi", content="envoyé", success=True)


class _OutilLibre(BaseTool):
    tool_id = "essai_lecture"
    appels: list[dict] = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="essai_lecture",
            description="Lit quelque chose.",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params):
        _OutilLibre.appels.append(params)
        return ToolResult(tool_name="essai_lecture", content="lu", success=True)


@pytest.fixture(autouse=True)
def _greffe(monkeypatch):
    _OutilSensible.appels.clear()
    _OutilLibre.appels.clear()
    # ``getattr`` plutôt qu'un accès direct : contre l'ancien code, ce cache
    # n'existe pas, et le test central doit alors échouer sur le COMPORTEMENT
    # — un envoi parti sans accord — pas sur un attribut manquant.
    getattr(voix, "_executeurs", {}).clear()
    ToolRegistry.register_value("essai_envoi", _OutilSensible)
    ToolRegistry.register_value("essai_lecture", _OutilLibre)
    # ``_ensure_desktop_tools_loaded`` importe tout le bureau ; inutile ici et
    # lent. Les deux outils d'essai sont déjà dans le registre.
    monkeypatch.setattr(voix, "_ensure_desktop_tools_loaded", lambda: None)
    yield
    getattr(voix, "_executeurs", {}).clear()


def _refuser(_prompt: str) -> bool:
    return False


def _accepter(_prompt: str) -> bool:
    return True


def test_un_outil_sensible_ne_part_pas_sans_accord(monkeypatch):
    monkeypatch.setattr(
        "diapason.server.approval_bridge.tool_confirm_callback",
        lambda *a, **k: _refuser,
    )
    r = voix.execute_voice_tool("essai_envoi", {}, allowed=["essai_envoi"])
    assert r["ok"] is False
    assert _OutilSensible.appels == [], (
        "l'envoi est parti sans que rien ne soit demandé"
    )


def test_un_outil_sensible_part_apres_accord(monkeypatch):
    monkeypatch.setattr(
        "diapason.server.approval_bridge.tool_confirm_callback",
        lambda *a, **k: _accepter,
    )
    r = voix.execute_voice_tool("essai_envoi", {}, allowed=["essai_envoi"])
    assert r["ok"] is True
    assert len(_OutilSensible.appels) == 1


def test_un_outil_de_lecture_n_est_jamais_ralenti(monkeypatch):
    """Lire l'agenda ne doit rien demander : la voix serait inutilisable."""

    def _jamais(_prompt: str) -> bool:
        raise AssertionError("un outil de lecture ne doit pas demander d'accord")

    monkeypatch.setattr(
        "diapason.server.approval_bridge.tool_confirm_callback",
        lambda *a, **k: _jamais,
    )
    r = voix.execute_voice_tool("essai_lecture", {}, allowed=["essai_lecture"])
    assert r["ok"] is True
    assert len(_OutilLibre.appels) == 1


def test_un_outil_hors_liste_reste_refuse():
    """La liste d'autorisation demeure la première barrière."""
    r = voix.execute_voice_tool("shell_exec", {}, allowed=["essai_lecture"])
    assert r["ok"] is False
    assert "not allowed" in r["error"]


def test_l_executeur_est_construit_une_seule_fois(monkeypatch):
    assert hasattr(voix, "_executeurs"), "la voix passe désormais par un ToolExecutor"
    monkeypatch.setattr(
        "diapason.server.approval_bridge.tool_confirm_callback",
        lambda *a, **k: _accepter,
    )
    voix.execute_voice_tool("essai_lecture", {}, allowed=["essai_lecture"])
    premier = voix._executeurs[("essai_lecture",)]
    voix.execute_voice_tool("essai_lecture", {}, allowed=["essai_lecture"])
    assert voix._executeurs[("essai_lecture",)] is premier


def test_le_delai_vocal_est_plus_court_que_celui_du_chat():
    """Deux minutes de silence dans une conversation parlée, c'est une panne."""
    from diapason.server.approval_bridge import DEFAULT_WAIT_S

    assert voix.VOICE_APPROVAL_WAIT_S < DEFAULT_WAIT_S


def test_mail_send_et_messages_send_exigent_toujours_un_accord():
    """Le cœur du défaut, sur les vrais outils cette fois — sans les exécuter."""
    import diapason.tools  # noqa: F401
    from diapason.tools._stubs import _CONFIRMATION_CAPABILITIES

    for nom in ("mail_send", "messages_send"):
        assert nom in voix.DEFAULT_VOICE_TOOL_IDS, f"{nom} est bien offert à la voix"
    assert _CONFIRMATION_CAPABILITIES, "la liste des capacités sensibles existe"
