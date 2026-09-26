"""La voix du Mac, parlée depuis le téléphone — bornée comme la Discussion.

Phase 4 du plan mobile (26/09/2026). La Discussion du téléphone est bornée à
OUTILS_DU_TELEPHONE (core/origine_telephone.py) ; la voix, elle, avait
quatre chemins vers le Mac qui ne passaient pas par ce plafond, ou le
contournaient par le prompt :

- le chemin rapide (``_try_fast_voice_action``) ouvre des apps, des
  adresses et des recherches SANS ToolExecutor ;
- chaque tour lit l'app au premier plan, la page ouverte dans Diapason, le
  résumé du partage d'écran et ce que la main tient — l'écran du Mac, récité
  à l'oral ;
- les schémas d'outils et TOOL_ORAL_HINT apprenaient au modèle open_anything
  et screen_read_text ;
- un fournisseur distant (?provider=gemini) a sa propre boucle d'outils.

Ici, la marque de la passerelle est posée par une enveloppe ASGI minimale ;
la preuve par la vraie passerelle vit dans tests/server/test_passerelle_tailnet.py.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from diapason.core.origine_telephone import (  # noqa: E402
    OUTILS_DU_TELEPHONE,
    marquer_le_telephone,
)
from diapason.core.types import ToolResult  # noqa: E402
from diapason.server.voice_live_routes import voice_live_router  # noqa: E402
from diapason.speech.realtime import local_voice  # noqa: E402
from diapason.speech.realtime.local_voice import LocalVoiceSession  # noqa: E402
from diapason.speech.realtime.oral_prompt import build_live_agent_template  # noqa: E402
from diapason.speech.realtime.tools import (  # noqa: E402
    DEFAULT_VOICE_TOOL_IDS,
    outils_vocaux_du_telephone,
)
from diapason.tools._stubs import BaseTool, ToolSpec  # noqa: E402

_OUTILS_DU_MAC = ("clipboard_read", "screen_read_text", "open_anything", "mail_send")


class _Journal:
    """Ce que les outils espions ont vraiment fait."""

    executions: list[str] = []


def _espion(nom: str) -> type[BaseTool]:
    class _Espion(BaseTool):
        tool_id = nom

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name=nom, description=f"espion {nom}")

        def execute(self, **_params) -> ToolResult:
            _Journal.executions.append(nom)
            return ToolResult(tool_name=nom, content="CONTENU DU MAC", success=True)

    return _Espion


@pytest.fixture(autouse=True)
def espions(monkeypatch):
    """Les vrais outils du Mac remplacés par des espions, et l'exécuteur de
    la voix reconstruit (il est mis en cache par liste d'outils)."""
    from diapason.core.registry import ToolRegistry
    from diapason.speech.realtime import tools

    _Journal.executions = []
    monkeypatch.setattr(tools, "_executeurs", {})
    for nom in (*_OUTILS_DU_MAC, "current_time"):
        ToolRegistry.register_value(nom, _espion(nom))
    yield


def _seance(**options) -> LocalVoiceSession:
    options.setdefault("stt", lambda _a: "")
    options.setdefault("llm", lambda _m: None)
    options.setdefault("tts", lambda _t: b"")
    return LocalVoiceSession(**options)


def _du_telephone(**options) -> LocalVoiceSession:
    with marquer_le_telephone():
        return _seance(**options)


class TestLaTrousseDuTelephone:
    def test_elle_ne_garde_que_les_outils_permis_au_telephone(self):
        seance = _du_telephone()
        assert seance._enable_tools is True
        assert seance._allowed_tools, "la voix du téléphone n'a plus aucun outil"
        hors_plafond = set(seance._allowed_tools) - OUTILS_DU_TELEPHONE
        assert not hors_plafond, f"outils du Mac offerts au téléphone : {hors_plafond}"
        for nom in _OUTILS_DU_MAC:
            assert nom not in seance._allowed_tools

    def test_une_demande_qui_ne_nomme_que_des_outils_du_mac_coupe_les_outils(self):
        """Une liste vide se lit ailleurs « le défaut », donc TOUT : la
        trame tools: "clipboard_read" aurait rendu la trousse entière."""
        seance = _du_telephone(allowed_tools=["clipboard_read", "screen_read_text"])
        assert seance._enable_tools is False
        assert seance._allowed_tools == []

    def test_sur_le_mac_la_trousse_ne_change_pas(self):
        seance = _seance()
        assert seance._allowed_tools is None, "le Mac garde le défaut de la voix"
        assert seance._enable_tools is True

    def test_la_liste_explicite_n_est_jamais_none(self):
        assert outils_vocaux_du_telephone(None) == [
            t for t in DEFAULT_VOICE_TOOL_IDS if t in OUTILS_DU_TELEPHONE
        ]
        assert outils_vocaux_du_telephone(["mail_send"]) == []


class TestLeFilDeLExecuteur:
    @pytest.mark.asyncio
    async def test_un_outil_du_mac_reste_refuse_meme_dans_un_fil_a_nu(self):
        """Un threading.Thread ne copie aucun contexte : sans la marque
        reposée par l'exécuteur de la séance, ToolExecutor aurait cru
        l'appel venu du Mac. On élargit exprès la liste de la séance pour
        éprouver la seconde barrière seule."""
        seance = _du_telephone()
        assert await seance._warm() is True
        seance._allowed_tools = ["clipboard_read"]
        rendu: dict = {}
        fil = threading.Thread(
            target=lambda: rendu.update(seance._tool_executor("clipboard_read", {}))
        )
        fil.start()
        fil.join(5)
        assert _Journal.executions == [], "le presse-papiers du Mac a été lu"
        assert rendu.get("ok") is False, rendu
        assert "téléphone" in str(rendu.get("content")), rendu


class TestLeCheminRapide:
    @pytest.mark.asyncio
    async def test_ouvre_safari_ne_part_pas_sur_le_mac(self, monkeypatch):
        """« Diapason, ouvre Safari », dit au téléphone, ouvrait Safari sur
        le Mac : le chemin rapide appelle execute_voice_action en direct."""
        from diapason.desktop import voice_commands

        ouvertures: list = []
        monkeypatch.setattr(
            voice_commands,
            "execute_voice_action",
            lambda action: ouvertures.append(action) or {"handled": True},
        )
        seance = _du_telephone()
        assert (
            await seance._try_fast_voice_action("ouvre Safari", turn_started=0.0)
            is False
        )
        assert ouvertures == [], "une app s'est ouverte sur le Mac depuis le téléphone"

        mac = _seance()
        await mac._try_fast_voice_action("ouvre Safari", turn_started=0.0)
        assert ouvertures, "témoin : sur le Mac, le chemin rapide agit"


class TestLesPerceptionsDuMac:
    def _poser_le_mac(self, monkeypatch):
        import diapason.desktop.etat_bureau as eb
        from diapason.desktop.etat_bureau import EtatBureau

        monkeypatch.setattr(eb, "_cache", EtatBureau("Safari", ("Safari", "Mail"), 0.0))

    def test_le_tour_du_telephone_ne_recite_pas_le_bureau_du_mac(self, monkeypatch):
        self._poser_le_mac(monkeypatch)
        messages = _du_telephone()._turn_messages("qu'est-ce qui est ouvert ?")
        texte = " ".join(str(m.get("content")) for m in messages)
        assert "Safari" not in texte, "l'app au premier plan du Mac a atteint le tour"
        assert messages[-1] == {"role": "user", "content": "qu'est-ce qui est ouvert ?"}

    def test_temoin_sur_le_mac_le_cliche_entre(self, monkeypatch):
        self._poser_le_mac(monkeypatch)
        messages = _seance()._turn_messages("qu'est-ce qui est ouvert ?")
        assert any("Safari" in str(m.get("content")) for m in messages)


class TestLePromptEtLesFournisseurs:
    def test_le_prompt_du_telephone_n_apprend_aucun_outil_du_mac(self):
        prompt = build_live_agent_template(enable_tools=True, telephone=True)
        for nom in ("screen_read_text", "open_anything", "clipboard_read", "mail_send"):
            assert f"**{nom}**" not in prompt, f"le prompt apprend {nom} au téléphone"
        assert "phone" in prompt.lower()

    def test_la_seance_du_telephone_compose_le_prompt_du_telephone(self):
        seance = _du_telephone(instructions="")
        assert "**open_anything**" not in seance._system_prompt()

    @pytest.mark.parametrize("fournisseur", ["gemini", "openai"])
    def test_un_fournisseur_distant_est_refuse_au_telephone(self, fournisseur):
        """Le fournisseur vient du CLIENT : ?provider=gemini aurait envoyé
        le micro du téléphone chez Google, avec une boucle d'outils qui n'a
        pas les gardes de la séance locale."""
        from diapason.speech.realtime.factory import create_realtime_session

        with marquer_le_telephone(), pytest.raises(ValueError, match="téléphone"):
            create_realtime_session(fournisseur)


# ── la route entière, marquée comme la passerelle la marque ──────────────


def _llm_qui_demande(outil: str):
    tours: list[list[dict]] = []

    def llm(messages):
        tours.append(messages)
        file: asyncio.Queue = asyncio.Queue()
        if len(tours) == 1:
            file.put_nowait(("tools", [{"function": {"name": outil, "arguments": {}}}]))
        else:
            file.put_nowait("Je ne peux pas depuis le téléphone.")
        file.put_nowait(None)
        return file

    return llm, tours


def _app(monkeypatch, llm, *, marquer: bool):
    monkeypatch.setattr(local_voice, "ollama_reachable", lambda *_a, **_k: True)

    class _SeanceDeBanc(LocalVoiceSession):
        def __init__(self, **options):
            super().__init__(
                stt=lambda _a: "", llm=llm, tts=lambda _t: b"\x00\x00" * 240, **options
            )

    monkeypatch.setattr(local_voice, "LocalVoiceSession", _SeanceDeBanc)
    app = FastAPI()
    app.state.api_key = ""
    app.include_router(voice_live_router)
    if not marquer:
        return app

    async def passerelle(scope, receive, send):
        with marquer_le_telephone():
            await app(scope, receive, send)

    return passerelle


def _parler(client: TestClient, texte: str) -> list[dict]:
    with client.websocket_connect("/v1/voice/live") as ws:
        ws.send_json(
            {
                "type": "start",
                "provider": "local",
                "include_memory": False,
                # Le client demande les outils du Mac : restreindre, jamais élargir.
                "tools": "clipboard_read,screen_read_text,current_time",
            }
        )
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "text", "text": texte})
        recus = []
        while True:
            message = ws.receive_json()
            recus.append(message)
            if message["type"] == "transcript" and message["role"] == "assistant":
                if message.get("final"):
                    break
            if message["type"] in ("error", "closed") or len(recus) > 50:
                break
        ws.send_json({"type": "stop"})
    return recus


class TestLaRouteDuTelephone:
    def test_le_presse_papiers_du_mac_ne_se_lit_pas_a_la_voix_du_telephone(
        self, monkeypatch
    ):
        llm, tours = _llm_qui_demande("clipboard_read")
        client = TestClient(_app(monkeypatch, llm, marquer=True))
        recus = _parler(client, "Diapason, qu'est-ce que j'ai copié ?")

        outils = [m for m in recus if m["type"] == "tool"]
        assert outils and outils[0]["name"] == "clipboard_read"
        assert outils[0]["ok"] is False, "l'outil du Mac a répondu au téléphone"
        assert _Journal.executions == [], "le presse-papiers du Mac a été lu"
        assert tours, "le modèle n'a jamais été appelé"

    def test_temoin_sur_la_boucle_locale_le_meme_tour_lit_le_presse_papiers(
        self, monkeypatch
    ):
        llm, _ = _llm_qui_demande("clipboard_read")
        client = TestClient(_app(monkeypatch, llm, marquer=False))
        recus = _parler(client, "Diapason, qu'est-ce que j'ai copié ?")
        outils = [m for m in recus if m["type"] == "tool"]
        assert outils and outils[0]["ok"] is True, recus
        assert _Journal.executions == ["clipboard_read"]
