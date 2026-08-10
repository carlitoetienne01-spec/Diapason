"""Tests for welcome sequence wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.desktop.welcome_runner import WelcomeClapSettings, run_welcome_sequence


def test_run_welcome_calls_tools():
    settings = WelcomeClapSettings(
        song_uri="https://example.com/song",
        claude_url="https://claude.test",
        binance_url="https://binance.test",
        welcome_phrase="Hi",
        elevenlabs_voice_id="vid",
        after_song_delay_s=0.0,
    )

    with (
        patch("openjarvis.tools.desktop_tools.OpenUriTool") as OpenUri,
        patch("openjarvis.tools.desktop_tools.OpenBrowserOnMonitorTool") as Chrome,
        patch("openjarvis.tools.desktop_tools.FocusAppTool") as Focus,
        patch("openjarvis.tools.desktop_tools.PlayAudioFileTool") as Play,
        patch("openjarvis.tools.text_to_speech.TextToSpeechTool") as TTS,
    ):
        for cls in (OpenUri, Chrome, Focus, Play, TTS):
            inst = MagicMock()
            inst.execute.return_value = MagicMock(success=True, content="/tmp/a.mp3")
            cls.return_value = inst

        results = run_welcome_sequence(settings)
        assert "song" in results
        assert "claude" in results
        assert "binance" in results
        assert "tts" in results
        assert "cursor" in results
        OpenUri.return_value.execute.assert_called()
        TTS.return_value.execute.assert_called()
