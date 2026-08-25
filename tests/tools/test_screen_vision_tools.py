"""Tests for screen capture + screen_describe tool."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from diapason.tools.screen_vision_tools import (
    ScreenDescribeTool,
    reset_rate_limit_for_tests,
)


def test_screencapture_darwin_argv(tmp_path: Path):
    from diapason.desktop import screen_capture as sc

    out = tmp_path / "shot.png"
    out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    with patch("diapason.desktop.screen_capture.sys.platform", "darwin"):
        with patch(
            "diapason.desktop.screen_capture.shutil.which",
            return_value="/usr/sbin/screencapture",
        ):
            with patch("diapason.desktop.screen_capture.tempfile.mkstemp") as mk:
                mk.return_value = (3, str(out))
                with patch("diapason.desktop.screen_capture.os.close"):
                    with patch("diapason.desktop.screen_capture.subprocess.run") as run:
                        run.return_value = SimpleNamespace(
                            returncode=0, stdout="", stderr=""
                        )
                        # keep file so getsize works
                        path = sc.capture_screen_to_temp(monitor=2)
    assert path == str(out)
    cmd = run.call_args[0][0]
    assert cmd[0] == "screencapture"
    assert "-x" in cmd
    assert "-D" in cmd and "2" in cmd


def test_screen_describe_disabled():
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    with patch(
        "diapason.tools.screen_vision_tools._vision_config",
        return_value=SimpleNamespace(enabled=False),
    ):
        result = tool.execute(question="what is this?")
    assert result.success is False
    assert "disabled" in result.content.lower()


def test_screen_describe_local_ok():
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    cfg = SimpleNamespace(
        enabled=True,
        monitor=1,
        max_dimension=1280,
        keep_temp=False,
        allow_cloud=False,
        model="gemma3:4b",
        engine="ollama",
        rate_limit_ms=0,
    )
    engine = MagicMock()
    engine.engine_id = "ollama"
    engine.is_cloud = False
    engine.generate.return_value = {"content": "A terminal window with code."}

    fake_cfg = MagicMock()
    fake_cfg.engine.default = "ollama"
    fake_cfg.intelligence.default_model = "gemma3:4b"

    with patch("diapason.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "diapason.tools.screen_vision_tools.capture_screen_b64",
            return_value=(
                base64.b64encode(b"png").decode(),
                {"bytes": 3, "monitor": 1},
            ),
        ):
            with patch("diapason.core.config.load_config", return_value=fake_cfg):
                with patch(
                    "diapason.engine._discovery.get_engine",
                    return_value=("ollama", engine),
                ):
                    result = tool.execute(question="What do you see?")
    assert result.success
    assert "terminal" in result.content.lower()
    assert result.metadata.get("local") is True
    engine.generate.assert_called_once()
    msgs = engine.generate.call_args[0][0]
    assert msgs[0].images


def test_screen_describe_blocks_cloud():
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    cfg = SimpleNamespace(
        enabled=True,
        monitor=1,
        max_dimension=1280,
        keep_temp=False,
        allow_cloud=False,
        model="gpt-4o",
        engine="openai",
        rate_limit_ms=0,
    )
    engine = MagicMock()
    engine.engine_id = "openai"
    engine.is_cloud = True

    fake_cfg = MagicMock()
    fake_cfg.engine.default = "openai"
    fake_cfg.intelligence.default_model = "gpt-4o"

    with patch("diapason.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "diapason.tools.screen_vision_tools.capture_screen_b64",
            return_value=("YQ==", {"bytes": 1}),
        ):
            with patch("diapason.core.config.load_config", return_value=fake_cfg):
                with patch(
                    "diapason.engine._discovery.get_engine",
                    return_value=("ollama", engine),
                ):
                    result = tool.execute(question="see?")
    assert result.success is False
    assert "refusing" in result.content.lower() or "non-local" in result.content.lower()
    engine.generate.assert_not_called()


def test_screen_describe_rate_limit():
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    cfg = SimpleNamespace(
        enabled=True,
        monitor=1,
        max_dimension=1280,
        keep_temp=False,
        allow_cloud=False,
        model="gemma3:4b",
        engine="ollama",
        rate_limit_ms=60_000,
    )
    engine = MagicMock()
    engine.engine_id = "ollama"
    engine.is_cloud = False
    engine.generate.return_value = {"content": "ok"}
    fake_cfg = MagicMock()
    fake_cfg.engine.default = "ollama"
    fake_cfg.intelligence.default_model = "gemma3:4b"

    with patch("diapason.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "diapason.tools.screen_vision_tools.capture_screen_b64",
            return_value=("YQ==", {"bytes": 1}),
        ):
            with patch("diapason.core.config.load_config", return_value=fake_cfg):
                with patch(
                    "diapason.engine._discovery.get_engine",
                    return_value=("ollama", engine),
                ):
                    first = tool.execute(question="a")
                    second = tool.execute(question="b")
    assert first.success
    assert second.success is False
    assert second.metadata.get("rate_limited") is True


def test_voice_allowlist_includes_screen_describe():
    import diapason.tools.screen_vision_tools  # noqa: F401
    from diapason.speech.realtime.tools import (
        DEFAULT_VOICE_TOOL_IDS,
        list_voice_tool_ids,
    )

    assert "screen_describe" in DEFAULT_VOICE_TOOL_IDS
    assert "screen_describe" in list_voice_tool_ids()


# ── Authorise first, capture second ──────────────────────────────────────────
#
# `test_screen_describe_blocks_cloud` above proves the screenshot is not SENT
# to a remote engine. It does not prove it was never TAKEN — and it was:
# capture_screen_b64 ran first, writing the whole screen to a temp file via
# capture_screen_to_temp, and the refusal came afterwards. Refusing after the
# fact protects the network and not the disk.
#
# These tests assert the stronger property: on a refused request, the capture
# function is never called at all.


_VISION_CFG = "diapason.tools.screen_vision_tools._vision_config"
_CAPTURE = "diapason.tools.screen_vision_tools.capture_screen_b64"
_GET_ENGINE = "diapason.engine._discovery.get_engine"
_LOAD_CFG = "diapason.core.config.load_config"


def _refusing_cfg(**overrides) -> SimpleNamespace:
    base = dict(
        enabled=True,
        monitor=1,
        max_dimension=1280,
        keep_temp=False,
        allow_cloud=False,
        model="gpt-4o",
        engine="openai",
        rate_limit_ms=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_refused_cloud_request_never_captures_the_screen():
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    engine = MagicMock()
    engine.engine_id = "openai"
    engine.is_cloud = True

    fake_cfg = MagicMock()
    fake_cfg.engine.default = "openai"
    fake_cfg.intelligence.default_model = "gpt-4o"

    with patch(_VISION_CFG, return_value=_refusing_cfg()):
        with patch(_CAPTURE) as capture:
            with patch("diapason.core.config.load_config", return_value=fake_cfg):
                with patch(_GET_ENGINE, return_value=("ollama", engine)):
                    result = tool.execute(question="see?")

    assert result.success is False
    capture.assert_not_called()
    assert result.metadata.get("captured") is False
    engine.generate.assert_not_called()


def test_missing_model_never_captures_the_screen():
    """Same principle for the other refusal: no artifact for a dead request."""
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    engine = MagicMock()
    engine.engine_id = "ollama"
    engine.is_cloud = False

    fake_cfg = MagicMock()
    fake_cfg.engine.default = "ollama"
    fake_cfg.intelligence.default_model = ""

    with patch(
        "diapason.tools.screen_vision_tools._vision_config",
        return_value=_refusing_cfg(model="", engine="ollama"),
    ):
        with patch(_CAPTURE) as capture:
            with patch("diapason.core.config.load_config", return_value=fake_cfg):
                with patch(_GET_ENGINE, return_value=("ollama", engine)):
                    result = tool.execute(question="see?")

    assert result.success is False
    assert "model" in result.content.lower()
    capture.assert_not_called()


def test_local_only_overrides_allow_cloud():
    """[privacy] local_only outranks [desktop.vision] allow_cloud."""
    reset_rate_limit_for_tests()
    tool = ScreenDescribeTool()
    engine = MagicMock()
    engine.engine_id = "openai"
    engine.is_cloud = True

    fake_cfg = MagicMock()
    fake_cfg.engine.default = "openai"
    fake_cfg.intelligence.default_model = "gpt-4o"
    fake_cfg.privacy.local_only = True

    # allow_cloud = True would previously have been enough to send.
    with patch(
        "diapason.tools.screen_vision_tools._vision_config",
        return_value=_refusing_cfg(allow_cloud=True),
    ):
        with patch(_CAPTURE) as capture:
            with patch("diapason.core.config.load_config", return_value=fake_cfg):
                with patch(_GET_ENGINE, return_value=("ollama", engine)):
                    result = tool.execute(question="see?")

    assert result.success is False
    capture.assert_not_called()
    engine.generate.assert_not_called()


class TestLectureDuTexteExact:
    """« Lis ce qui est écrit » : l'OCR natif rend les caractères eux-mêmes,
    là où gemma3:4b paraphrase (Atlas, 24 août 2026). Zéro créneau Ollama."""

    def _cfg(self, enabled=True):
        class _Cfg:
            pass

        c = _Cfg()
        c.enabled = enabled
        # 0 retomberait sur 1500 via le `or` du code : -1 désarme vraiment.
        c.rate_limit_ms = -1
        c.monitor = 1
        return c

    def test_desactive_refuse_avant_toute_capture(self, monkeypatch):
        import diapason.tools.screen_vision_tools as svt

        monkeypatch.setattr(svt, "_vision_config", lambda: self._cfg(enabled=False))
        with patch("diapason.desktop.screen_capture.capture_screen_to_temp") as capture:
            r = svt.read_screen_text()
        assert not r.success and "disabled" in r.content
        capture.assert_not_called()

    def test_vision_absent_nomme_le_remede(self, monkeypatch):
        import diapason.tools.screen_vision_tools as svt

        monkeypatch.setattr(svt, "_vision_config", lambda: self._cfg())
        with patch("diapason.desktop.ocr.ocr_available", return_value=False):
            r = svt.read_screen_text()
        assert not r.success
        assert "pyobjc-framework-Vision" in r.content

    def test_les_lignes_reviennent_dans_l_ordre_et_le_temp_meurt(
        self, monkeypatch, tmp_path
    ):
        import diapason.tools.screen_vision_tools as svt

        monkeypatch.setattr(svt, "_vision_config", lambda: self._cfg())
        capture = tmp_path / "ecran.png"
        capture.write_bytes(b"\x89PNG")
        with (
            patch("diapason.desktop.ocr.ocr_available", return_value=True),
            patch(
                "diapason.desktop.screen_capture.capture_screen_to_temp",
                return_value=str(capture),
            ),
            patch(
                "diapason.desktop.ocr.recognize_text",
                return_value=[
                    {"text": "Erreur 403", "confidence": 0.99, "x": 0.1, "y": 0.9},
                    {"text": "Réessayer", "confidence": 0.95, "x": 0.1, "y": 0.4},
                ],
            ),
        ):
            r = svt.read_screen_text()
        assert r.success
        assert r.content == "Erreur 403\nRéessayer"
        assert r.metadata["engine"] == "apple-vision"
        assert not capture.exists()  # le fichier temporaire meurt au finally

    def test_un_ecran_sans_texte_l_avoue(self, monkeypatch, tmp_path):
        import diapason.tools.screen_vision_tools as svt

        monkeypatch.setattr(svt, "_vision_config", lambda: self._cfg())
        capture = tmp_path / "ecran.png"
        capture.write_bytes(b"\x89PNG")
        with (
            patch("diapason.desktop.ocr.ocr_available", return_value=True),
            patch(
                "diapason.desktop.screen_capture.capture_screen_to_temp",
                return_value=str(capture),
            ),
            patch("diapason.desktop.ocr.recognize_text", return_value=[]),
        ):
            r = svt.read_screen_text()
        assert r.success and "No readable text" in r.content

    def test_present_dans_les_deux_trousses(self):
        from diapason.server.routes import _TROUSSE_ASSISTANT
        from diapason.speech.realtime.tools import (
            DEFAULT_VOICE_TOOL_IDS,
            list_voice_tool_ids,
        )

        assert "screen_read_text" in _TROUSSE_ASSISTANT
        assert "screen_read_text" in DEFAULT_VOICE_TOOL_IDS
        assert "screen_read_text" in list_voice_tool_ids()


class TestTramesInchangees:
    """La boucle de partage ne repaie pas gemma3:4b pour un écran immobile :
    trame identique = description du cache, zéro créneau Ollama (-np 1)."""

    def test_une_trame_identique_ne_reveille_pas_le_modele(self, monkeypatch):
        import diapason.tools.screen_vision_tools as svt

        monkeypatch.setattr(svt, "_derniere_empreinte_partage", "")
        monkeypatch.setattr(svt, "_derniere_description_partage", "")
        cfg = SimpleNamespace(
            enabled=True,
            rate_limit_ms=-1,
            monitor=1,
            max_dimension=1280,
            keep_temp=False,
            allow_cloud=False,
            model="gemma3:4b",
            engine="ollama",
        )
        monkeypatch.setattr(svt, "_vision_config", lambda: cfg)
        moteur = MagicMock()
        moteur.engine_id = "ollama"
        moteur.is_cloud = False
        moteur.generate.return_value = {"content": "Un éditeur de code."}
        fake_cfg = MagicMock()
        fake_cfg.engine.default = "ollama"
        fake_cfg.intelligence.default_model = "gemma3:4b"
        with (
            patch(
                "diapason.tools.screen_vision_tools.capture_screen_b64",
                return_value=("MEMEIMAGE", {}),
            ),
            patch("diapason.core.config.load_config", return_value=fake_cfg),
            patch(
                "diapason.engine._discovery.get_engine",
                return_value=("ollama", moteur),
            ),
        ):
            premier = svt.describe_screen(skip_rate_limit=True)
            second = svt.describe_screen(skip_rate_limit=True)
        assert premier.success and second.success
        assert second.content == "Un éditeur de code."
        assert second.metadata.get("unchanged") is True
        assert moteur.generate.call_count == 1, (
            "écran inchangé = pas de seconde inférence"
        )

    def test_un_appel_direct_n_est_jamais_deduplique(self, monkeypatch):
        """skip_rate_limit=False (screen_describe à la demande) : l'usager
        veut un regard FRAIS, la dédup ne s'applique qu'à la boucle."""
        import diapason.tools.screen_vision_tools as svt

        monkeypatch.setattr(svt, "_derniere_empreinte_partage", "")
        monkeypatch.setattr(svt, "_derniere_description_partage", "")
        cfg = SimpleNamespace(
            enabled=True,
            rate_limit_ms=-1,
            monitor=1,
            max_dimension=1280,
            keep_temp=False,
            allow_cloud=False,
            model="gemma3:4b",
            engine="ollama",
        )
        monkeypatch.setattr(svt, "_vision_config", lambda: cfg)
        moteur = MagicMock()
        moteur.engine_id = "ollama"
        moteur.is_cloud = False
        moteur.generate.return_value = {"content": "Pareil."}
        fake_cfg = MagicMock()
        fake_cfg.engine.default = "ollama"
        fake_cfg.intelligence.default_model = "gemma3:4b"
        with (
            patch(
                "diapason.tools.screen_vision_tools.capture_screen_b64",
                return_value=("MEMEIMAGE", {}),
            ),
            patch("diapason.core.config.load_config", return_value=fake_cfg),
            patch(
                "diapason.engine._discovery.get_engine",
                return_value=("ollama", moteur),
            ),
        ):
            svt.describe_screen(skip_rate_limit=False)
            svt.describe_screen(skip_rate_limit=False)
        assert moteur.generate.call_count == 2
