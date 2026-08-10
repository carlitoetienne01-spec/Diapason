"""Tests for screen capture + screen_describe tool."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openjarvis.tools.screen_vision_tools import (
    ScreenDescribeTool,
    reset_rate_limit_for_tests,
)


def test_screencapture_darwin_argv(tmp_path: Path):
    from openjarvis.desktop import screen_capture as sc

    out = tmp_path / "shot.png"
    out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    with patch("openjarvis.desktop.screen_capture.sys.platform", "darwin"):
        with patch("openjarvis.desktop.screen_capture.shutil.which", return_value="/usr/sbin/screencapture"):
            with patch("openjarvis.desktop.screen_capture.tempfile.mkstemp") as mk:
                mk.return_value = (3, str(out))
                with patch("openjarvis.desktop.screen_capture.os.close"):
                    with patch("openjarvis.desktop.screen_capture.subprocess.run") as run:
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
        "openjarvis.tools.screen_vision_tools._vision_config",
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

    with patch("openjarvis.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "openjarvis.tools.screen_vision_tools.capture_screen_b64",
            return_value=(base64.b64encode(b"png").decode(), {"bytes": 3, "monitor": 1}),
        ):
            with patch("openjarvis.core.config.load_config", return_value=fake_cfg):
                with patch(
                    "openjarvis.engine._discovery.get_engine", return_value=engine
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

    with patch("openjarvis.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "openjarvis.tools.screen_vision_tools.capture_screen_b64",
            return_value=("YQ==", {"bytes": 1}),
        ):
            with patch("openjarvis.core.config.load_config", return_value=fake_cfg):
                with patch(
                    "openjarvis.engine._discovery.get_engine", return_value=engine
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

    with patch("openjarvis.tools.screen_vision_tools._vision_config", return_value=cfg):
        with patch(
            "openjarvis.tools.screen_vision_tools.capture_screen_b64",
            return_value=("YQ==", {"bytes": 1}),
        ):
            with patch("openjarvis.core.config.load_config", return_value=fake_cfg):
                with patch(
                    "openjarvis.engine._discovery.get_engine", return_value=engine
                ):
                    first = tool.execute(question="a")
                    second = tool.execute(question="b")
    assert first.success
    assert second.success is False
    assert second.metadata.get("rate_limited") is True


def test_voice_allowlist_includes_screen_describe():
    import openjarvis.tools.screen_vision_tools  # noqa: F401
    from openjarvis.speech.realtime.tools import (
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


_VISION_CFG = "openjarvis.tools.screen_vision_tools._vision_config"
_CAPTURE = "openjarvis.tools.screen_vision_tools.capture_screen_b64"
_GET_ENGINE = "openjarvis.engine._discovery.get_engine"
_LOAD_CFG = "openjarvis.core.config.load_config"


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
            with patch("openjarvis.core.config.load_config", return_value=fake_cfg):
                with patch(_GET_ENGINE, return_value=engine):
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
        "openjarvis.tools.screen_vision_tools._vision_config",
        return_value=_refusing_cfg(model="", engine="ollama"),
    ):
        with patch(_CAPTURE) as capture:
            with patch("openjarvis.core.config.load_config", return_value=fake_cfg):
                with patch(_GET_ENGINE, return_value=engine):
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
        "openjarvis.tools.screen_vision_tools._vision_config",
        return_value=_refusing_cfg(allow_cloud=True),
    ):
        with patch(_CAPTURE) as capture:
            with patch("openjarvis.core.config.load_config", return_value=fake_cfg):
                with patch(_GET_ENGINE, return_value=engine):
                    result = tool.execute(question="see?")

    assert result.success is False
    capture.assert_not_called()
    engine.generate.assert_not_called()
