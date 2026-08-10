"""The four structural gates of local-only mode.

The census found 297 outbound sites. Guarding them one by one would be
unmaintainable and would be bypassed by the first module added next month, so
the contract is carried by *structure*: the base classes that a whole
subsystem cannot avoid, plus two functions that own the remaining families.

What each test proves is that the guard is installed by the CLASS, not by a
dispatcher. ``ToolExecutor`` is already bypassed today by three modules that
call ``Tool().execute(...)`` directly — so every tool test below calls
``execute`` directly too. If the guard only lived in the dispatcher, they
would all pass while the product still leaked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, Optional
from unittest.mock import patch

import pytest

from openjarvis.channels._stubs import BaseChannel
from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.local_mode import LocalOnlyError
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_LOAD_CONFIG = "openjarvis.core.config.load_config"


@dataclass
class _Privacy:
    local_only: bool


@dataclass
class _Cfg:
    privacy: _Privacy


def _mode(local: bool):
    """Patch the config that `local_only()` loads when given none."""
    return patch(_LOAD_CONFIG, return_value=_Cfg(privacy=_Privacy(local_only=local)))


# ── Doubles ──────────────────────────────────────────────────────────────────


class _Tool(BaseTool):
    """Records whether its body ran — the only thing worth asserting."""

    tool_id = "probe"
    is_local = True

    def __init__(self) -> None:
        self.ran = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="probe", description="probe")

    def execute(self, **params: Any) -> ToolResult:
        self.ran = True
        return ToolResult(tool_name="probe", content="did the work", success=True)


class _RemoteTool(_Tool):
    tool_id = "remote_probe"
    is_local = False


class _Connector(BaseConnector):
    connector_id = "probe"
    display_name = "Probe"
    auth_type = "local"
    is_local = True

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        yield Document(doc_id="1", source="probe", doc_type="note", content="body")

    def sync_status(self) -> SyncStatus:
        return SyncStatus()


class _RemoteConnector(_Connector):
    connector_id = "remote_probe"
    is_local = False


# ── Gate 1: tools ────────────────────────────────────────────────────────────


def test_remote_tool_body_never_runs_under_local_only():
    tool = _RemoteTool()
    with _mode(True):
        result = tool.execute()
    assert tool.ran is False
    assert result.success is False
    assert result.metadata.get("nothing_left_the_machine") is True


def test_local_tool_still_runs_under_local_only():
    tool = _Tool()
    with _mode(True):
        result = tool.execute()
    assert tool.ran is True
    assert result.success is True


def test_remote_tool_runs_when_local_only_is_off():
    tool = _RemoteTool()
    with _mode(False):
        result = tool.execute()
    assert tool.ran is True
    assert result.success is True


def test_the_guard_is_installed_once_not_per_inheritance_level():
    """A subclass that does not redefine execute must not be wrapped twice."""

    class _Grandchild(_RemoteTool):
        tool_id = "grandchild"

    tool = _Grandchild()
    with _mode(True):
        assert tool.execute().success is False
    assert tool.ran is False


def test_mail_and_messages_send_are_declared_remote():
    """Driving Mail.app locally still makes the CONTENT leave.

    Both tools declared is_local=True, which exempted the most explicit send
    in the product from the boundary guard and from local-only alike.
    """
    from openjarvis.tools.voice_mac_tools import MailSendTool, MessagesSendTool

    assert MailSendTool.is_local is False
    assert MessagesSendTool.is_local is False


# ── Gate 2: connectors ───────────────────────────────────────────────────────


def test_remote_connector_yields_nothing_under_local_only():
    with _mode(True):
        assert list(_RemoteConnector().sync()) == []


def test_local_connector_still_yields_under_local_only():
    with _mode(True):
        docs = list(_Connector().sync())
    assert len(docs) == 1


def test_remote_connector_yields_when_local_only_is_off():
    with _mode(False):
        assert len(list(_RemoteConnector().sync())) == 1


def test_locality_is_not_read_from_auth_type():
    """`auth_type="local"` means "no login", not "on this machine".

    hackernews queries hacker-news.firebaseio.com and news_rss fetches remote
    feeds, yet both declare auth_type="local". Deriving locality from it would
    have opened the exact hole this gate exists to close.
    """
    # Imported directly rather than through ConnectorRegistry: the root
    # conftest clears every registry between tests, and registration happens
    # once at import time.
    from openjarvis.connectors.apple_health import AppleHealthConnector
    from openjarvis.connectors.hackernews import HackerNewsConnector
    from openjarvis.connectors.imessage import IMessageConnector
    from openjarvis.connectors.news_rss import NewsRSSConnector
    from openjarvis.connectors.obsidian import ObsidianConnector
    from openjarvis.connectors.weather import WeatherConnector

    for cls in (HackerNewsConnector, NewsRSSConnector, WeatherConnector):
        assert cls.is_local is False, cls.__name__
    for cls in (AppleHealthConnector, IMessageConnector, ObsidianConnector):
        assert cls.is_local is True, cls.__name__


def test_a_connector_that_claims_nothing_is_treated_as_remote():
    """Fail-closed: locality must be claimed, never assumed."""
    assert BaseConnector.is_local is False


# ── Gate 3: realtime voice ───────────────────────────────────────────────────


def test_realtime_voice_is_refused_under_local_only():
    """Raw microphone PCM streamed continuously — the gravest path."""
    from openjarvis.speech.realtime.factory import create_realtime_session

    with _mode(True):
        with pytest.raises(LocalOnlyError):
            create_realtime_session("openai")


def test_realtime_refusal_precedes_provider_dispatch():
    """Even an unknown provider is refused, so no constructor is reached."""
    from openjarvis.speech.realtime.factory import create_realtime_session

    with _mode(True):
        with pytest.raises(LocalOnlyError):
            create_realtime_session("does-not-exist")


# ── Gate 4: the server's own cloud path ──────────────────────────────────────


def test_stream_cloud_is_refused_under_local_only():
    """This module speaks httpx directly, so the engine gate misses it."""
    from openjarvis.server.cloud_router import stream_cloud

    async def _drain() -> None:
        async for _ in stream_cloud("gpt-4o", []):
            pass

    with _mode(True):
        with pytest.raises(LocalOnlyError):
            asyncio.run(_drain())


# ── Gate 5: channels ─────────────────────────────────────────────────────────


class _Channel(BaseChannel):
    channel_id = "probe"
    is_local = True

    def connect(self) -> None:
        return "CONNECTED"

    def disconnect(self) -> None:
        pass

    def send(self, channel, content, *, conversation_id="", metadata=None):
        return "SENT"

    def status(self):
        from openjarvis.channels._stubs import ChannelStatus

        return ChannelStatus.CONNECTED

    def list_channels(self):
        return []

    def on_message(self, handler) -> None:
        pass


class _RemoteChannel(_Channel):
    channel_id = "remote_probe"
    is_local = False

    def send(self, channel, content, *, conversation_id="", metadata=None):
        return "SENT"

    def connect(self) -> None:
        return "CONNECTED"


def test_remote_channel_send_is_refused_without_raising():
    """Returns False rather than raising: a daemon loop must not fall over."""
    with _mode(True):
        assert _RemoteChannel().send("chan", "hello") is False


def test_remote_channel_connect_is_refused_too():
    """Guarding send alone would leave the standing gateway open.

    A Discord or Slack adapter holds a websocket to a third party for as long
    as the daemon runs — an outbound connection whether or not a message is
    ever sent.
    """
    with _mode(True):
        assert _RemoteChannel().connect() is None


def test_local_channel_is_untouched():
    with _mode(True):
        assert _Channel().send("chan", "hello") == "SENT"
        assert _Channel().connect() == "CONNECTED"


def test_remote_channel_works_when_local_only_is_off():
    with _mode(False):
        assert _RemoteChannel().send("chan", "hello") == "SENT"


def test_channels_are_remote_unless_they_claim_otherwise():
    assert BaseChannel.is_local is False


# ── Gate 6: telemetry ────────────────────────────────────────────────────────


def test_analytics_is_disabled_by_local_only():
    """`[analytics] enabled` ships True with a hard-coded PostHog key.

    Anonymous counters are still a packet leaving on every launch, which is a
    caveat rather than a promise. The predicate is the whole gate:
    AnalyticsClient consults it before building the SDK client.
    """
    from openjarvis.analytics.identity import is_analytics_enabled
    from openjarvis.core.config import AnalyticsConfig

    cfg = AnalyticsConfig()
    cfg.enabled = True

    with _mode(True):
        assert is_analytics_enabled(cfg) is False
    with _mode(False):
        assert is_analytics_enabled(cfg) is True


def test_local_only_does_not_re_enable_analytics_the_user_turned_off():
    from openjarvis.analytics.identity import is_analytics_enabled
    from openjarvis.core.config import AnalyticsConfig

    cfg = AnalyticsConfig()
    cfg.enabled = False
    with _mode(False):
        assert is_analytics_enabled(cfg) is False


# ── Gate 7: hybrid agents ────────────────────────────────────────────────────


def test_hybrid_cloud_call_is_refused_even_when_called_unbound():
    """conductor.py and minions.py call these methods unbound.

    A guard on the `_call_cloud` dispatcher alone would be routinely skipped,
    which is why the functions themselves are replaced on the class.
    """
    from openjarvis.agents.hybrid._base import LocalCloudAgent

    with _mode(True):
        with pytest.raises(LocalOnlyError):
            LocalCloudAgent._call_anthropic("model", user="hello")
        with pytest.raises(LocalOnlyError):
            LocalCloudAgent._call_cloud("model", user="hello")


def test_hybrid_methods_stay_staticmethods_after_wrapping():
    """Re-wrapping matters: without it the descriptor turns them into methods."""
    from openjarvis.agents.hybrid._base import LocalCloudAgent

    for name in ("_call_anthropic", "_call_openai", "_call_vllm"):
        assert isinstance(LocalCloudAgent.__dict__[name], staticmethod), name


def test_hybrid_vllm_is_judged_on_its_endpoint():
    """A purely local paradigm must keep working under local-only."""
    from openjarvis.agents.hybrid._base import LocalCloudAgent

    with _mode(True):
        with pytest.raises(LocalOnlyError):
            LocalCloudAgent._call_vllm("model", "http://1.2.3.4:8000", user="hello")

        # Loopback passes the gate. The OpenAI client is stubbed out: the
        # constructor being reached at all is the proof that the guard
        # delegated instead of refusing — and it keeps the test off the
        # network, which cost 105s per run when it was real.
        built = {}

        def _fake_openai(**kwargs):
            built.update(kwargs)
            raise RuntimeError("stubbed transport")

        with patch("openai.OpenAI", _fake_openai):
            with pytest.raises(RuntimeError, match="stubbed transport"):
                LocalCloudAgent._call_vllm(
                    "model", "http://127.0.0.1:8000", user="hello"
                )
        assert built["base_url"] == "http://127.0.0.1:8000"
