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

    intent = parse_smart_intent("envoie un message à +15551234567 disant Salut ça va")
    assert intent.kind == KIND_MESSAGES_COMPOSE
    assert "+15551234567" in intent.to
    assert "salut" in intent.body.lower()


def test_email_intent_en():
    from diapason.desktop.smart_intents import KIND_MAIL_COMPOSE, parse_smart_intent

    intent = parse_smart_intent("email bob@example.com about the invoice")
    assert intent.kind == KIND_MAIL_COMPOSE
    assert intent.to == "bob@example.com"


def test_ouvre_mails_ouvre_l_application_installee():
    """Retourné le 23 août 2026 — l'ancien test verrouillait le défaut vécu.

    « Ouvre mes mails » partait sur mail.google.com dans un navigateur alors
    que Mail.app est installée ; pour l'utilisateur, « Mail ne s'ouvre pas ».
    L'application installée gagne ; le web n'est que le repli de qui dit
    « gmail ». La règle Gmail n'attrape donc plus la forme française."""
    from diapason.desktop.smart_intents import KIND_GMAIL, parse_smart_intent

    intent = parse_smart_intent("ouvre mes mails")
    assert intent.kind != KIND_GMAIL

    a = parse_voice_command("ouvre mes mails")
    assert a.kind == "focus_app"
    assert a.target == "Mail"


def test_gmail_nomme_va_toujours_au_web():
    """Qui DIT « gmail » veut le site — ce chemin-là ne bouge pas."""
    from diapason.desktop.smart_intents import KIND_GMAIL, parse_smart_intent

    intent = parse_smart_intent("ouvre gmail")
    assert intent.kind == KIND_GMAIL
    assert "mail.google" in intent.url


def test_voice_command_mail_compose():
    a = parse_voice_command("compose email to ada@example.com about Hello")
    assert a.kind == "mail_compose"
    assert a.target == "ada@example.com"


# ---------------------------------------------------------------------------
# « joue X » must PLAY, not strand the user on a results page
# ---------------------------------------------------------------------------


def test_youtube_play_carries_the_action():
    intent = parse_smart_intent("joue la vidéo Papaoutai de Stromae sur youtube")
    assert intent.kind == KIND_YOUTUBE
    assert intent.action == "play"
    # Leading filler goes ("la vidéo"), the title's own words stay.
    assert intent.query == "papaoutai de stromae"


def test_titles_keep_their_inner_articles():
    # The old cleaner stripped articles EVERYWHERE: this searched
    # for "vie en rose" already, but "sous le vent" lost its "le".
    intent = parse_smart_intent("joue la chanson Sous le vent sur youtube")
    assert intent.query == "sous le vent"


def test_search_still_searches():
    intent = parse_smart_intent("cherche jazz sur youtube")
    assert intent.kind == KIND_YOUTUBE
    assert intent.action == "search"


def test_a_full_url_is_never_hijacked_to_the_home_page():
    # An LLM-built search URL used to fall through every phrase regex and
    # come back as https://www.youtube.com — the model's work silently lost.
    url = "https://www.youtube.com/results?search_query=papaoutai"
    intent = parse_smart_intent(url)
    assert intent.kind == KIND_URL
    assert intent.url == url


def test_www_urls_gain_a_scheme():
    intent = parse_smart_intent("www.youtube.com/watch?v=abc123def45")
    assert intent.kind == KIND_URL
    assert intent.url == "https://www.youtube.com/watch?v=abc123def45"


# ---------------------------------------------------------------------------
# Top-result resolution (network mocked out)
# ---------------------------------------------------------------------------


def test_resolver_returns_the_first_organic_video():
    from diapason.desktop.smart_intents import resolve_youtube_watch_url

    seen = {}

    def fetch(url):
        seen["url"] = url
        # Ads use other renderers; the first videoRenderer is the top hit.
        return (
            '"adSlotRenderer":{"x":1},'
            '"videoRenderer":{"videoId":"dQw4w9WgXcQ","title":1},'
            '"videoRenderer":{"videoId":"AAAAAAAAAAA"}'
        )

    got = resolve_youtube_watch_url("papaoutai stromae", fetch=fetch)
    assert got == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert "search_query=papaoutai+stromae" in seen["url"]


def test_resolver_failure_degrades_to_empty():
    from diapason.desktop.smart_intents import resolve_youtube_watch_url

    def boom(url):
        raise OSError("offline")

    assert resolve_youtube_watch_url("x", fetch=boom) == ""
    assert resolve_youtube_watch_url("x", fetch=lambda u: "no json here") == ""


def test_execute_play_opens_the_watch_url():
    import diapason.desktop.smart_intents as si

    intent = parse_smart_intent("joue papaoutai sur youtube")
    opened = []

    def fake_open(url, browser=""):
        opened.append(url)
        from diapason.core.types import ToolResult

        return ToolResult(tool_name="open_uri", content=f"Opened {url}", success=True)

    with patch.object(
        si,
        "resolve_youtube_watch_url",
        return_value="https://www.youtube.com/watch?v=abc12345678",
    ):
        with patch("diapason.tools.desktop_tools.open_in_browser", fake_open):
            result = si.execute_smart_intent(intent)

    assert opened == ["https://www.youtube.com/watch?v=abc12345678"]
    assert result.success
    assert "Playing top YouTube result" in result.content


def test_execute_play_falls_back_to_results_page():
    import diapason.desktop.smart_intents as si

    intent = parse_smart_intent("joue papaoutai sur youtube")
    opened = []

    def fake_open(url, browser=""):
        opened.append(url)
        from diapason.core.types import ToolResult

        return ToolResult(tool_name="open_uri", content=f"Opened {url}", success=True)

    with patch.object(si, "resolve_youtube_watch_url", return_value=""):
        with patch("diapason.tools.desktop_tools.open_in_browser", fake_open):
            result = si.execute_smart_intent(intent)

    assert opened and "results?search_query=" in opened[0]
    # Honest: the model must not announce playback that did not start.
    assert "SEARCH RESULTS" in result.content


def test_spotify_missing_falls_back_to_youtube_playback():
    import diapason.desktop.smart_intents as si
    from diapason.core.types import ToolResult

    intent = parse_smart_intent("joue du stromae sur spotify")
    assert intent.kind == KIND_SPOTIFY

    opened = []

    def fake_open(url, browser=""):
        opened.append(url)
        return ToolResult(tool_name="open_uri", content=f"Opened {url}", success=True)

    missing = ToolResult(
        tool_name="spotify_play",
        content="Spotify is not installed on this Mac.",
        success=False,
        metadata={"spotify_missing": True},
    )
    with patch(
        "diapason.tools.voice_mac_tools.SpotifyPlayTool.execute", return_value=missing
    ):
        with patch.object(
            si,
            "resolve_youtube_watch_url",
            return_value="https://www.youtube.com/watch?v=xyz98765432",
        ):
            with patch("diapason.tools.desktop_tools.open_in_browser", fake_open):
                result = si.execute_smart_intent(intent)

    assert opened == ["https://www.youtube.com/watch?v=xyz98765432"]
    assert result.success
    assert "YouTube" in result.content


def test_spotify_other_failures_do_not_fall_back():
    import diapason.desktop.smart_intents as si
    from diapason.core.types import ToolResult

    intent = parse_smart_intent("joue du stromae sur spotify")
    broken = ToolResult(
        tool_name="spotify_play", content="osascript died", success=False
    )
    with patch(
        "diapason.tools.voice_mac_tools.SpotifyPlayTool.execute", return_value=broken
    ):
        result = si.execute_smart_intent(intent)
    assert result is broken


def test_ecoute_and_mets_also_play():
    # « écoute X sur youtube » fell through every phrase regex and landed
    # on the home page — the query silently lost.
    for verb in ("écoute", "mets", "lance"):
        intent = parse_smart_intent(f"{verb} papaoutai sur youtube")
        assert intent.kind == KIND_YOUTUBE, verb
        assert intent.action == "play", verb
        assert intent.query == "papaoutai", verb


def test_spotify_missing_search_never_autoplays():
    # A mere SEARCH must not turn into an unexpected YouTube autoplay.
    import diapason.desktop.smart_intents as si
    from diapason.core.types import ToolResult

    intent = parse_smart_intent("cherche du stromae sur spotify")
    assert intent.kind == KIND_SPOTIFY
    assert intent.action != "play"

    missing = ToolResult(
        tool_name="spotify_play",
        content="Spotify is not installed on this Mac.",
        success=False,
        metadata={"spotify_missing": True},
    )
    with patch(
        "diapason.tools.voice_mac_tools.SpotifyPlayTool.execute", return_value=missing
    ):
        result = si.execute_smart_intent(intent)
    assert result is missing  # reported honestly, nothing auto-opened


def test_titles_made_of_articles_survive():
    # The blind head-cascade turned « La La Land » into a search for "land".
    intent = parse_smart_intent("joue La La Land sur youtube")
    assert intent.query == "la la land"


def test_leading_article_before_a_real_title_survives():
    intent = parse_smart_intent("joue The Weeknd sur youtube")
    assert intent.query == "the weeknd"


def test_article_runs_leading_to_filler_still_stripped():
    intent = parse_smart_intent("joue de la musique kompa sur youtube")
    assert intent.query == "kompa"


def test_mets_pause_is_not_a_play_request():
    # « mets la vidéo en pause sur youtube » must not PLAY a video
    # literally titled "pause".
    intent = parse_smart_intent("mets la vidéo en pause sur youtube")
    assert intent.action != "play" or intent.kind != KIND_YOUTUBE


def test_search_with_play_words_inside_stays_a_search():
    # asked_to_play used to sniff the whole phrase: « cherche listen de
    # beyoncé sur spotify » became an autoplay.
    intent = parse_smart_intent("cherche listen de beyoncé sur spotify")
    assert intent.kind == KIND_SPOTIFY
    assert intent.action == "search"
    assert "listen" in intent.query


# ---------------------------------------------------------------------------
# Spoken padding — the phrases people actually SAY
# ---------------------------------------------------------------------------


def test_spoken_padding_does_not_become_the_search_query():
    # The exact utterance from the field: every pattern missed it, the
    # catch-all then SEARCHED the padding itself.
    intent = parse_smart_intent(
        "Ouvre-moi YouTube sur mon navigateur et joue-moi la chanson Papa Ok."
    )
    assert intent.kind == KIND_YOUTUBE
    assert intent.action == "play"
    assert intent.query == "papa ok"


def test_play_verb_after_the_youtube_mention():
    intent = parse_smart_intent("ouvre youtube et joue du kompa")
    assert intent.kind == KIND_YOUTUBE
    assert intent.action == "play"
    assert "kompa" in intent.query


def test_titles_keep_their_own_moi():
    # « -moi » only strips after a COMMAND verb; it belongs to this title.
    intent = parse_smart_intent("joue Laisse-moi sur youtube")
    assert intent.query == "laisse-moi"


class TestMusiqueGenerique:
    """Constaté au chat le 23 août 2026 : « joue-moi de la musique sur
    youtube depuis mon navigateur » cherchait littéralement « depuis mon
    navigateur », et « met de la musique » se faisait répondre un refus."""

    def test_depuis_mon_navigateur_est_du_remplissage(self):
        intent = parse_smart_intent(
            "Joue moi de la musique sur Youtube depuis mon navigateur"
        )
        assert intent.kind == "youtube"
        assert intent.action == "play_mix"
        assert intent.query == "musique"

    def test_de_la_musique_sur_youtube_lance_la_radio(self):
        # « Que ça joue, n'importe quelle musique » : l'intention est une
        # lecture en radio, jamais une simple page d'accueil.
        intent = parse_smart_intent("joue de la musique sur youtube")
        assert intent.action == "play_mix"
        assert intent.url == "https://music.youtube.com"  # le repli seulement

    def test_la_radio_enchaine_les_titres(self):
        from diapason.desktop.smart_intents import resolve_youtube_watch_url

        page = '"videoRenderer": {"videoId": "abc123XYZ_-"'
        url = resolve_youtube_watch_url("musique", fetch=lambda _u: page, mix=True)
        assert url == "https://www.youtube.com/watch?v=abc123XYZ_-&list=RDabc123XYZ_-"
        url = resolve_youtube_watch_url("musique", fetch=lambda _u: page)
        assert url == "https://www.youtube.com/watch?v=abc123XYZ_-"

    def test_mets_de_la_musique_ouvre_le_juke_box(self):
        for phrase in (
            "mets de la musique",
            "met de la musique",
            "lance de la musique",
        ):
            intent = parse_smart_intent(phrase)
            assert intent.kind == "app" and intent.app == "Spotify", phrase

    def test_un_vrai_titre_reste_une_lecture(self):
        intent = parse_smart_intent("joue Papaoutai de Stromae sur youtube")
        assert intent.action == "play"
        assert intent.query == "papaoutai de stromae"

    def test_la_pause_n_est_ni_une_recherche_ni_une_ouverture(self):
        intent = parse_smart_intent("mets la musique en pause")
        assert intent.kind not in {"spotify", "app"}
