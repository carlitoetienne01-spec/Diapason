"""Tests for Diapason-style smart browser/app intents (FR + EN)."""

from __future__ import annotations

from unittest.mock import patch

from diapason.desktop.smart_intents import (
    KIND_AMAZON,
    KIND_APP,
    KIND_NONE,
    KIND_SPOTIFY,
    KIND_URL,
    KIND_YOUTUBE,
    parse_smart_intent,
)
from diapason.desktop.voice_commands import parse_voice_command


def test_youtube_search_fr():
    intent = parse_smart_intent("ouvre youtube et cherche chats mignons")
    assert intent.kind == KIND_YOUTUBE
    assert "chats" in intent.query
    assert "youtube.com/results" in intent.url
    assert "chats" in intent.url or "search_query=" in intent.url


def test_youtube_search_en():
    intent = parse_smart_intent("open YouTube and search for cooking pasta")
    assert intent.kind == KIND_YOUTUBE
    assert "cooking" in intent.query or "pasta" in intent.query
    assert "search_query=" in intent.url


def test_youtube_on_site_fr():
    intent = parse_smart_intent("cherche jazz sur youtube")
    assert intent.kind == KIND_YOUTUBE
    assert "jazz" in intent.query


def test_youtube_home():
    intent = parse_smart_intent("ouvre youtube")
    assert intent.kind == KIND_URL
    assert intent.url == "https://www.youtube.com"


def test_spotify_play_fr():
    intent = parse_smart_intent("joue Daft Punk sur Spotify")
    assert intent.kind == KIND_SPOTIFY
    assert "daft" in intent.query.lower()
    assert intent.url.startswith("spotify:search:")


def test_spotify_search_en():
    intent = parse_smart_intent("play lo-fi on Spotify")
    assert intent.kind == KIND_SPOTIFY
    assert "lo-fi" in intent.query or "lo" in intent.query


def test_spotify_app_only():
    intent = parse_smart_intent("ouvre Spotify")
    assert intent.kind == KIND_APP
    assert intent.app == "Spotify"


def test_amazon_search_fr():
    intent = parse_smart_intent("cherche casque bluetooth sur amazon")
    assert intent.kind == KIND_AMAZON
    assert "casque" in intent.query
    assert "amazon.com/s" in intent.url


def test_amazon_search_en():
    intent = parse_smart_intent("amazon search wireless mouse")
    assert intent.kind == KIND_AMAZON
    assert "mouse" in intent.query or "wireless" in intent.query


def test_netflix_and_gmail():
    assert parse_smart_intent("ouvre netflix").url == "https://www.netflix.com"
    assert "mail.google" in parse_smart_intent("ouvre gmail").url


def test_native_app():
    intent = parse_smart_intent("ouvre Chrome")
    assert intent.kind == KIND_APP
    assert intent.app == "Google Chrome"


def test_no_match():
    assert parse_smart_intent("quelle heure est-il").kind == KIND_NONE


def test_voice_command_routes_youtube():
    a = parse_voice_command("ouvre youtube et cherche cats")
    assert a.kind == "open_uri"
    assert "youtube.com/results" in a.target


def test_voice_command_routes_spotify():
    a = parse_voice_command("joue rock sur Spotify")
    assert a.kind == "spotify"
    assert "rock" in a.target.lower()


def test_open_anything_uses_smart_youtube():
    from diapason.tools.desktop_tools import OpenAnythingTool

    tool = OpenAnythingTool()
    with patch("diapason.tools.desktop_tools.sys.platform", "darwin"):
        with patch("diapason.tools.desktop_tools._run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            result = tool.execute(
                target="open YouTube and search for cats", kind="auto"
            )
    assert result.success
    assert (result.metadata or {}).get("smart_kind") == KIND_YOUTUBE
    cmd = run.call_args[0][0]
    assert any("youtube.com" in str(c) for c in cmd)


def test_mail_compose_intent_fr():
    from diapason.desktop.smart_intents import KIND_MAIL_COMPOSE, parse_smart_intent

    intent = parse_smart_intent(
        "écris un mail à ada@example.com sujet Reunion disant On se voit demain"
    )
    assert intent.kind == KIND_MAIL_COMPOSE
    assert intent.to == "ada@example.com"


def test_messages_compose_intent_fr():
    from diapason.desktop.smart_intents import (
        KIND_MESSAGES_COMPOSE,
        parse_smart_intent,
    )

    intent = parse_smart_intent(
        "envoie un message à +15551234567 disant Salut ça va"
    )
    assert intent.kind == KIND_MESSAGES_COMPOSE
    assert "+15551234567" in intent.to
    assert "salut" in intent.body.lower()


def test_email_intent_en():
    from diapason.desktop.smart_intents import KIND_MAIL_COMPOSE, parse_smart_intent

    intent = parse_smart_intent("email bob@example.com about the invoice")
    assert intent.kind == KIND_MAIL_COMPOSE
    assert intent.to == "bob@example.com"


def test_ouvre_mails_still_gmail():
    from diapason.desktop.smart_intents import KIND_GMAIL, parse_smart_intent

    intent = parse_smart_intent("ouvre mes mails")
    assert intent.kind == KIND_GMAIL
    assert "mail.google" in intent.url


def test_voice_command_mail_compose():
    a = parse_voice_command("compose email to ada@example.com about Hello")
    assert a.kind == "mail_compose"
    assert a.target == "ada@example.com"
