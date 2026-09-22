"""Tests for the research_loop agent — focused on loop invariants.

The fixtures use a minimal mock engine so these tests are fast and don't
require a running Ollama daemon.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from diapason.agents.research_loop import (
    SEARCH_TOOL_SPEC,
    SYSTEM_PROMPT,
    ResearchAgent,
    _hit_url,
    build_sources_for_client,
    renumber_citations,
    shape_results_for_model,
)
from diapason.connectors.hybrid_search import SearchHit


class _MockEngine:
    """Engine stub that lets a test script the per-call response.

    ``responses`` is a list of dicts in ``OllamaEngine.generate`` shape
    (``content``, ``tool_calls``, ``usage``); each call to ``generate``
    consumes the next entry. When the script runs out, the engine repeats
    the final entry — handy for "loop forever" mock behaviors.
    """

    def __init__(self, responses: List[Dict[str, Any]]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def generate(
        self,
        messages: Sequence,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        num_ctx: int = 8192,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append({"tools": tools, "messages": list(messages)})
        if self._responses:
            return (
                self._responses.pop(0)
                if len(self._responses) > 1
                else self._responses[0]
            )
        return {"content": "", "tool_calls": [], "usage": {}}


def _search_call(call_id: str, query: str = "anything") -> Dict[str, Any]:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "name": "search",
                "arguments": json.dumps({"query": query}),
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _text_response(text: str) -> Dict[str, Any]:
    return {
        "content": text,
        "tool_calls": [],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


@pytest.fixture()
def stub_search() -> MagicMock:
    """A HybridSearch stand-in whose .search() returns an empty hit list."""
    s = MagicMock()
    s.search.return_value = []
    return s


def test_forced_synthesis_when_budget_exhausts(stub_search: MagicMock) -> None:
    """Loop exits cleanly with a synthesis even when the model keeps tool-calling.

    With max_iterations=1, the budget is exhausted after a single search.
    The next engine call receives ``tools=None`` and is expected to produce
    a text answer; the new forced-synthesis fallback then makes one more
    no-tools call to ensure we always return something usable.
    """
    # Force the loop to fall through to the new forced-synthesis path: every
    # in-loop iteration returns a tool call (so we never take an early text
    # return), and the final post-loop call returns text.
    engine = _MockEngine(
        responses=[
            _search_call("call-1"),
            _search_call("call-2"),
            _text_response("Here is what I found: nothing usable."),
        ]
    )

    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=1)
    result = agent.run("test query")

    assert "Here is what I found" in result.answer
    assert "loop exhausted" not in result.answer.lower()
    # The final call was made with tools=None (the forced-synthesis path).
    assert engine.calls[-1]["tools"] is None
    assert all(t.tool_name == "search" for t in result.tool_calls)


def test_forced_synthesis_returns_sentinel_when_model_stays_silent(
    stub_search: MagicMock,
) -> None:
    """If even the forced final call returns no text, surface a clear sentinel.

    This is the gracefully-degraded case: the loop did its best but the model
    refused to emit text. The contract is still that ``answer`` is a non-empty
    string the caller can show to the user.
    """
    engine = _MockEngine(
        responses=[
            _search_call("call-1"),
            _search_call("call-2"),
            {"content": "", "tool_calls": [], "usage": {}},  # silent forced call
        ]
    )

    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=1)
    result = agent.run("test query")

    assert result.answer  # non-empty
    assert "no synthesis available" in result.answer.lower()


def test_first_turn_text_response_returns_directly(stub_search: MagicMock) -> None:
    """When the model produces text on the very first turn, return it as-is."""
    engine = _MockEngine(responses=[_text_response("Quick answer.")])
    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=5)
    result = agent.run("hello")
    assert result.answer == "Quick answer."
    assert result.tool_calls == []
    # Only one engine call needed.
    assert len(engine.calls) == 1


def test_clarify_before_any_search_is_rejected(stub_search: MagicMock) -> None:
    """clarify() invoked before a search call must return a runtime error result.

    The system prompt asks the planner to search first, but the loop also
    enforces this at runtime so a non-compliant planner can't surprise the
    user with a pre-emptive clarification.
    """
    clarify_calls: List[str] = []

    def fake_clarify(q: str) -> str:
        clarify_calls.append(q)
        return "user response"

    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "clarify",
                        "arguments": json.dumps({"question": "who?"}),
                    }
                ],
                "usage": {},
            },
            _text_response("Final."),
        ]
    )

    agent = ResearchAgent(
        engine,
        stub_search,
        model="mock",
        max_iterations=5,
        clarify_handler=fake_clarify,
    )
    result = agent.run("vague query")

    # Handler must not have been called because the dispatch returned an error.
    assert clarify_calls == []
    # No clarify invocation recorded.
    assert all(t.tool_name != "clarify" for t in result.tool_calls)
    assert result.answer == "Final."


# ---------------------------------------------------------------------------
# _hit_url — Slack permalink reconstruction
# ---------------------------------------------------------------------------


def test_hit_url_slack_full_workspace() -> None:
    """A workspace-qualified doc_id produces an ``{team}.slack.com`` permalink."""
    url = _hit_url("slack", "slack:acme:C123:1710500000.000100")
    assert url == "https://acme.slack.com/archives/C123/p1710500000000100"


def test_hit_url_slack_legacy_two_segment_doc_id() -> None:
    """Legacy ``slack:{channel}:{ts}`` ids fall back to the docless form."""
    url = _hit_url("slack", "slack:C123:1710500000.000100")
    assert url == "https://slack.com/archives/C123/p1710500000000100"


def test_hit_url_slack_empty_team_domain() -> None:
    """Empty workspace segment still produces a usable docless permalink."""
    url = _hit_url("slack", "slack::C123:1710500000.000100")
    assert url == "https://slack.com/archives/C123/p1710500000000100"


def test_hit_url_unknown_source_returns_empty() -> None:
    """Unsupported sources don't get a guessed URL."""
    assert _hit_url("notion", "notion:abc") == ""
    assert _hit_url("", "") == ""


def _mk_hit(
    *,
    source: str = "granola",
    document_id: str = "granola:not_abc12345678901",
    url: str = "",
    title: str = "Sprint Planning",
) -> SearchHit:
    """Tiny SearchHit factory for URL-routing tests."""
    return SearchHit(
        chunk_id="c1",
        document_id=document_id,
        chunk_idx=0,
        title=title,
        content_snippet="...",
        source=source,
        timestamp="2024-03-15T10:00:00",
        participants=["alice@co.com"],
        score=0.5,
        bm25_score=0.5,
        vector_score=0.5,
        url=url,
    )


def test_build_sources_prefers_stored_url_over_reconstruction() -> None:
    """When the connector stored a URL, the client gets it verbatim.

    The doc_id-based reconstruction is a *fallback* — sources like Granola
    that supply the URL at ingest time must surface it unchanged.
    """
    stored = "https://notes.granola.ai/d/e98b5d85-ff57-46ac-a0ce-849fc68d086f"
    sources = build_sources_for_client([_mk_hit(url=stored)])
    assert sources[0]["url"] == stored


def test_build_sources_falls_back_to_reconstruction_when_url_missing() -> None:
    """Slack/Gmail still work without a stored URL — reconstructed from doc_id."""
    sources = build_sources_for_client(
        [
            _mk_hit(
                source="slack",
                document_id="slack:acme:C123:1710500000.000100",
                url="",
                title="#general",
            )
        ]
    )
    assert sources[0]["url"] == "https://acme.slack.com/archives/C123/p1710500000000100"


def test_hit_url_granola_not_reconstructible() -> None:
    """Granola doc_ids cannot reconstruct a web URL.

    The Granola web app uses a UUID that is different from the API
    ``note_id`` embedded in our doc_id. Citation URLs for Granola must
    come from the stored ``SearchHit.url`` (populated at ingest time from
    the API's ``web_url`` field). ``_hit_url`` therefore returns empty.
    """
    assert _hit_url("granola", "granola:not_abc12345678901") == ""
    assert _hit_url("granola", "granola:") == ""
    assert _hit_url("granola", "") == ""


# ---------------------------------------------------------------------------
# Sources filter — propagated through _execute_search to HybridSearch.search
# ---------------------------------------------------------------------------


def test_search_with_sources_filter_is_passed_through(
    stub_search: MagicMock,
) -> None:
    """A search tool call carrying ``sources=['granola']`` reaches HybridSearch.

    Without this propagation, "tell me about my Granola notes" returns Gmail
    emails that mention Granola instead of actual meeting notes.
    """
    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "name": "search",
                        "arguments": json.dumps(
                            {
                                "query": "recent meetings",
                                "sources": ["granola"],
                            }
                        ),
                    }
                ],
                "usage": {},
            },
            _text_response("Here are your recent meetings."),
        ]
    )

    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=2)
    result = agent.run("tell me about my recent meetings from Granola")

    stub_search.search.assert_called_once()
    kwargs = stub_search.search.call_args.kwargs
    assert kwargs.get("sources") == ["granola"]
    # And the loop terminates with the synthesized answer.
    assert "Here are your recent meetings." in result.answer


def test_search_sources_coerces_scalar_to_list(stub_search: MagicMock) -> None:
    """If the model sends ``sources='slack'`` (string), wrap it as ``['slack']``."""
    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "name": "search",
                        "arguments": json.dumps(
                            {"query": "anything", "sources": "slack"}
                        ),
                    }
                ],
                "usage": {},
            },
            _text_response("done"),
        ]
    )
    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=2)
    agent.run("anything in slack")

    kwargs = stub_search.search.call_args.kwargs
    assert kwargs.get("sources") == ["slack"]


# ---------------------------------------------------------------------------
# Prompt + tool schema — the planner must see the sources directive
# ---------------------------------------------------------------------------


def test_tool_schema_sources_lists_known_connectors() -> None:
    """The ``sources`` parameter description enumerates the common connector IDs.

    Without explicit IDs in the description the planner makes up names like
    "Granola" or "Slack workspace" instead of the lowercase connector IDs the
    backend filter actually matches against.
    """
    sources_prop = SEARCH_TOOL_SPEC["function"]["parameters"]["properties"]["sources"]
    desc = sources_prop["description"]
    for connector_id in ("granola", "slack", "gmail", "notion"):
        assert connector_id in desc


def test_system_prompt_mandates_sources_extraction() -> None:
    """The system prompt has a directive telling the planner to extract sources.

    Without it, the model treats "from my Granola notes" as a topical cue
    rather than a hard filter, and returns email about Granola instead of
    Granola records.
    """
    assert "sources=" in SYSTEM_PROMPT
    # Synonym mapping for the most-common alias.
    assert "granola" in SYSTEM_PROMPT.lower()
    assert "meeting notes" in SYSTEM_PROMPT.lower()
    # The dynamic placeholder is what's interpolated per-run.
    assert "{available_sources}" in SYSTEM_PROMPT


def test_system_prompt_routes_upcoming_calendar_as_structured_search() -> None:
    """Upcoming calendar requests need source/time filters, not just keywords."""
    assert 'sources=["gcalendar"]' in SYSTEM_PROMPT
    assert 'time_range={{"start": "{today}"}}' in SYSTEM_PROMPT
    assert 'query=""' in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Dynamic available_sources — only list what the user actually has connected
# ---------------------------------------------------------------------------


def test_available_sources_override_appears_in_prompt(
    stub_search: MagicMock,
) -> None:
    """An explicit override is injected into the system prompt verbatim.

    Without this the agent will reference disconnected sources ("I couldn't
    find anything in Notion or Apple Notes") even when those connectors
    have never been wired up.
    """
    engine = _MockEngine(responses=[_text_response("ok")])
    agent = ResearchAgent(
        engine,
        stub_search,
        model="mock",
        max_iterations=1,
        available_sources=["gmail", "slack", "granola"],
    )
    agent.run("hi")
    sys_content = engine.calls[0]["messages"][0].content
    # The connected-sources blurb is interpolated verbatim.
    assert "gmail, slack, granola" in sys_content
    # And the prompt no longer hard-codes a static "Valid IDs include..."
    # enumeration of unconnected sources — those that aren't in the
    # available_sources list shouldn't appear in any *listing*. (Rule 4a
    # still uses Notion as a *narrative example* of how to handle an
    # unconnected source, which is intentional.)
    assert "obsidian" not in sys_content.lower()
    assert "apple_notes" not in sys_content.lower()
    assert "gdrive" not in sys_content.lower()


def test_available_sources_fall_back_to_store(stub_search: MagicMock) -> None:
    """When no override is given, the agent queries the KnowledgeStore.

    Mirrors the live wiring used by the SSE research router: a HybridSearch
    instance that exposes a ``_store`` with ``distinct_sources()``.
    """
    fake_store = MagicMock()
    fake_store.distinct_sources.return_value = ["granola", "slack"]
    stub_search._store = fake_store

    engine = _MockEngine(responses=[_text_response("ok")])
    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=1)
    agent.run("hi")

    fake_store.distinct_sources.assert_called_once()
    sys_content = engine.calls[0]["messages"][0].content
    assert "granola, slack" in sys_content


def test_available_sources_empty_message_when_nothing_connected(
    stub_search: MagicMock,
) -> None:
    """No connected sources surfaces a clear message instead of a stray {}.

    A missing placeholder would crash `str.format`; a broken format would
    leave a raw ``{available_sources}`` in the prompt. Both are bad UX —
    the test pins the friendly fallback string.
    """
    stub_search._store = None
    engine = _MockEngine(responses=[_text_response("ok")])
    agent = ResearchAgent(
        engine,
        stub_search,
        model="mock",
        max_iterations=1,
        available_sources=[],
    )
    agent.run("hi")
    sys_content = engine.calls[0]["messages"][0].content
    assert "no connected sources" in sys_content
    assert "{available_sources}" not in sys_content


# ---------------------------------------------------------------------------
# Ref offsetting + citation renumbering
# ---------------------------------------------------------------------------


def test_shape_results_for_model_respects_ref_offset() -> None:
    """Multi-search runs hand the model globally unique refs.

    Without offsets, two searches each emit refs 1..20 and the model can't
    disambiguate ``[5]`` across calls — which breaks the renumbering pass
    that runs over the final synthesis.
    """
    hits = [_mk_hit(title=f"t{i}", document_id=f"granola:{i}") for i in range(3)]
    shaped = shape_results_for_model(hits, ref_offset=20)
    refs = [h["ref"] for h in shaped["hits"]]
    assert refs == [21, 22, 23]


def test_build_sources_for_client_respects_ref_offset() -> None:
    """``build_sources_for_client`` agrees with ``shape_results_for_model``."""
    hits = [_mk_hit(title=f"t{i}", document_id=f"granola:{i}") for i in range(3)]
    sources = build_sources_for_client(hits, ref_offset=10)
    assert [s["ref"] for s in sources] == [11, 12, 13]
    # And the connector source is carried so the renumbered final list
    # can show "Granola • Sprint Planning" style chips.
    assert all(s["source"] == "granola" for s in sources)


def test_renumber_citations_first_appearance_order() -> None:
    """Citations are renumbered by first-appearance order in the text."""
    text = "First [7]. Then [3] and again [7]. Finally [12]."
    ref_to_source = {
        3: {"ref": 3, "title": "B"},
        7: {"ref": 7, "title": "A"},
        12: {"ref": 12, "title": "C"},
    }
    new_text, sources = renumber_citations(text, ref_to_source)
    # Order of appearance: 7 → 1, 3 → 2, 12 → 3 (the repeat of 7 keeps its ref).
    assert new_text == "First [1]. Then [2] and again [1]. Finally [3]."
    assert [s["ref"] for s in sources] == [1, 2, 3]
    assert [s["title"] for s in sources] == ["A", "B", "C"]


def test_renumber_citations_drops_uncited_sources() -> None:
    """Sources the synthesis never cited are excluded from the final list.

    The frontend would otherwise show citation chips for hits the model
    silently ignored, which clutters the panel and misleads about what
    the answer actually relied on.
    """
    text = "Only one citation here [5]."
    ref_to_source = {
        1: {"ref": 1, "title": "uncited-A"},
        5: {"ref": 5, "title": "cited"},
        9: {"ref": 9, "title": "uncited-B"},
    }
    new_text, sources = renumber_citations(text, ref_to_source)
    assert new_text == "Only one citation here [1]."
    assert len(sources) == 1
    assert sources[0]["title"] == "cited"


def test_renumber_citations_unknown_ref_left_alone() -> None:
    """A ``[N]`` whose ref isn't in the map is left as-is.

    Defensive: a hallucinated citation shouldn't blow up renumbering or
    silently disappear — the user sees the broken cite and can ask why.
    """
    text = "Real [3], hallucinated [99]."
    ref_to_source = {3: {"ref": 3, "title": "Real"}}
    new_text, sources = renumber_citations(text, ref_to_source)
    assert new_text == "Real [1], hallucinated [99]."
    assert [s["title"] for s in sources] == ["Real"]


# ---------------------------------------------------------------------------
# End-to-end: final_answer event carries renumbered text + sources
# ---------------------------------------------------------------------------


def test_final_answer_event_carries_renumbered_sources(
    stub_search: MagicMock,
) -> None:
    """The ``final_answer`` event includes the deduped, renumbered sources.

    Drives the same renumbering pipeline that's wired into the SSE router's
    ``done`` frame — when this test passes the frontend will receive a
    clean ``[1]..[K]`` numbering aligned with a single sources list.
    """
    # Two hits returned by the search. The synthesis cites the second one
    # twice and the first one once, in the order [2] [1] [2].
    hit_a = _mk_hit(title="A", document_id="granola:a", url="https://a")
    hit_b = _mk_hit(title="B", document_id="granola:b", url="https://b")
    stub_search.search.return_value = [hit_a, hit_b]

    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "name": "search",
                        "arguments": json.dumps({"query": "topic"}),
                    }
                ],
                "usage": {},
            },
            _text_response("First [2], then [1], then [2] again."),
        ]
    )

    captured: list[dict] = []

    def on_event(ev: dict) -> None:
        captured.append(ev)

    agent = ResearchAgent(
        engine,
        stub_search,
        model="mock",
        max_iterations=2,
        on_event=on_event,
        available_sources=["granola"],
    )
    result = agent.run("anything")

    # The synthesis is renumbered by first appearance: [2]→[1], [1]→[2].
    assert result.answer == "First [1], then [2], then [1] again."

    final = next(ev for ev in captured if ev["type"] == "final_answer")
    assert final["text"] == "First [1], then [2], then [1] again."
    # Two cited sources, in the order they appeared in the synthesis.
    assert [s["ref"] for s in final["sources"]] == [1, 2]
    assert [s["title"] for s in final["sources"]] == ["B", "A"]


# ---------------------------------------------------------------------------
# 22/09/2026 : le web, les tours d'avant, les indices
# ---------------------------------------------------------------------------


def _web_call(call_id: str, query: str, **extra: Any) -> Dict[str, Any]:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "name": "web_search",
                "arguments": json.dumps({"query": query, **extra}),
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class TestLeWebDansLaRechercheApprofondie:
    """« Fais-moi une recherche [sur] des sites web de jeux de programmation »
    sous la recherche approfondie recevait « votre corpus n'a rien », puis une
    liste de mémoire avec un site inventé ; « Donne-moi les liens de ces
    sites » rendait des liens tirés des courriels (22/09/2026)."""

    def test_sans_web_le_planificateur_ne_voit_pas_l_outil(self, stub_search):
        from diapason.agents.research_loop import WebHit, WebSearcher  # noqa: F401

        engine = _MockEngine([_text_response("Rien dans le corpus.")])
        ResearchAgent(engine, stub_search, model="mock").run("q")
        noms = [t["function"]["name"] for t in engine.calls[0]["tools"]]
        assert noms == ["search", "clarify"]
        assert "web" not in engine.calls[0]["messages"][0].content.split("\n")[0]

    def test_avec_web_l_outil_est_offert_et_ses_resultats_cites(self, stub_search):
        from diapason.agents.research_loop import WebHit

        appels: List[Any] = []

        def web(query: str, recency: Any, news: bool) -> List[WebHit]:
            appels.append((query, recency, news))
            return [
                WebHit(
                    title="CodinGame",
                    url="https://www.codingame.com/",
                    site="codingame.com",
                    date="2026-09-01",
                    snippet="Learn by playing.",
                ),
                WebHit(
                    title="Codewars",
                    url="https://www.codewars.com/",
                    site="codewars.com",
                ),
            ]

        engine = _MockEngine(
            [
                _web_call("w1", "programming games websites", recency="year"),
                _text_response("CodinGame [1] et Codewars [2]."),
            ]
        )
        evenements: List[Dict[str, Any]] = []
        agent = ResearchAgent(
            engine,
            stub_search,
            model="mock",
            web_search=web,
            on_event=evenements.append,
        )
        result = agent.run(
            "Fais-moi une recherche de sites web de jeux de programmation"
        )
        noms = [t["function"]["name"] for t in engine.calls[0]["tools"]]
        assert noms == ["search", "web_search", "clarify"]
        assert appels == [("programming games websites", "year", False)]
        assert "web_search(query, recency=None, news=False)" in (
            engine.calls[0]["messages"][0].content
        )
        assert "Web rules:" in engine.calls[0]["messages"][0].content
        assert result.answer == "CodinGame [1] et Codewars [2]."
        assert result.tool_calls[0].tool_name == "web_search"
        assert result.tool_calls[0].num_results == 2
        appel = next(e for e in evenements if e["type"] == "search_call")
        assert appel["arguments"]["tool"] == "web_search"
        resultat = next(e for e in evenements if e["type"] == "search_result")
        assert resultat["tool"] == "web_search"
        assert resultat["sources"][0] == {
            "ref": 1,
            "title": "CodinGame",
            "sender": "codingame.com",
            "date": "2026-09-01",
            "source": "web",
            "source_id": "",
            "url": "https://www.codingame.com/",
        }, "la source web a la forme des sources du corpus, avec son URL"
        outil = next(m for m in engine.calls[1]["messages"] if m.role.value == "tool")
        lu = json.loads(outil.content)
        assert lu["hits"][0]["url"] == "https://www.codingame.com/"
        assert lu["hits"][0]["snippet"] == "Learn by playing."
        final = next(e for e in evenements if e["type"] == "final_answer")
        assert [s["url"] for s in final["sources"]] == [
            "https://www.codingame.com/",
            "https://www.codewars.com/",
        ]

    def test_les_numeros_se_suivent_entre_corpus_et_web(self, stub_search):
        from diapason.agents.research_loop import WebHit

        stub_search.search.return_value = [
            _mk_hit(source="gmail", document_id="gmail:abc", title="Un courriel")
        ]
        engine = _MockEngine(
            [
                _search_call("s1", "jeux"),
                _web_call("w1", "jeux de programmation"),
                _text_response("Le courriel [1] et le site [2]."),
            ]
        )
        agent = ResearchAgent(
            engine,
            stub_search,
            model="mock",
            web_search=lambda q, r, n: [WebHit(title="Site", url="https://s.io/")],
        )
        result = agent.run("q")
        assert result.answer == "Le courriel [1] et le site [2]."
        outil_web = [m for m in engine.calls[2]["messages"] if m.role.value == "tool"][
            -1
        ]
        assert json.loads(outil_web.content)["hits"][0]["ref"] == 2

    def test_un_echec_du_web_est_une_erreur_lue_par_le_modele_pas_zero_resultat(
        self, stub_search
    ):
        """Revue du 22/09 : moteurs en panne → « 0 résultat », et le modèle
        concluait « le web n'a rien » (§100)."""

        def web(q, r, n):
            raise RuntimeError("réseau injoignable")

        engine = _MockEngine(
            [_web_call("w1", "x"), _text_response("Je n'ai pas pu chercher.")]
        )
        evenements: List[Dict[str, Any]] = []
        agent = ResearchAgent(
            engine,
            stub_search,
            model="mock",
            web_search=web,
            on_event=evenements.append,
        )
        result = agent.run("q")
        assert result.tool_calls == [], "un appel qui n'a pas eu lieu ne compte pas"
        outil = next(m for m in engine.calls[1]["messages"] if m.role.value == "tool")
        lu = json.loads(outil.content)
        assert "web_search failed: RuntimeError: réseau injoignable" in lu["error"]
        assert "never say the web has nothing" in lu["error"]
        assert "num_results" not in lu
        resultat = next(e for e in evenements if e["type"] == "search_result")
        assert resultat["error"] == "RuntimeError: réseau injoignable"
        assert "num_hits" not in resultat, "pas de « 0 results » pour un pas raté"

    def test_une_requete_vide_ne_cherche_pas_ne_debite_pas_n_affiche_rien(
        self, stub_search
    ):
        appels: List[Any] = []
        engine = _MockEngine(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {"id": "w1", "name": "web_search", "arguments": "{pas du json"}
                    ],
                    "usage": {},
                },
                _text_response("ok"),
            ]
        )
        evenements: List[Dict[str, Any]] = []
        agent = ResearchAgent(
            engine,
            stub_search,
            model="mock",
            web_search=lambda q, r, n: appels.append(q) or [],
            on_event=evenements.append,
        )
        result = agent.run("q")
        assert appels == [] and result.tool_calls == []
        assert [e["type"] for e in evenements] == ["final_answer"]
        outil = next(m for m in engine.calls[1]["messages"] if m.role.value == "tool")
        assert json.loads(outil.content) == {
            "error": "web_search needs a non-empty query"
        }

    def test_web_search_sans_outil_branche_est_un_outil_inconnu(self, stub_search):
        engine = _MockEngine([_web_call("w1", "x"), _text_response("ok")])
        ResearchAgent(engine, stub_search, model="mock").run("q")
        outil = next(m for m in engine.calls[1]["messages"] if m.role.value == "tool")
        assert "unknown tool 'web_search'" in outil.content
        assert "'search', 'clarify'" in outil.content

    def test_clarify_apres_une_recherche_web_est_permis(self, stub_search):
        from diapason.agents.research_loop import WebHit

        engine = _MockEngine(
            [
                _web_call("w1", "x"),
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "name": "clarify",
                            "arguments": json.dumps({"question": "Lequel ?"}),
                        }
                    ],
                    "usage": {},
                },
                _text_response("ok"),
            ]
        )
        agent = ResearchAgent(
            engine,
            stub_search,
            model="mock",
            web_search=lambda q, r, n: [WebHit(title="S", url="https://s.io/")],
            clarify_handler=lambda q: "celui-là",
        )
        agent.run("q")
        outil = [m for m in engine.calls[2]["messages"] if m.role.value == "tool"][-1]
        assert json.loads(outil.content)["user_response"] == "celui-là"


class TestLesToursDAvantEtLesIndices:
    def test_l_historique_precede_la_question_et_les_indices_la_suivent(
        self, stub_search
    ):
        from diapason.core.types import Message, Role

        engine = _MockEngine([_text_response("ok")])
        agent = ResearchAgent(engine, stub_search, model="mock")
        agent.run(
            "Donne-moi les liens de ces sites",
            history=[
                Message(role=Role.USER, content="Des sites de jeux de programmation ?"),
                Message(role=Role.ASSISTANT, content="CodinGame, Codewars."),
                Message(role=Role.SYSTEM, content="pas repris"),
                Message(role=Role.ASSISTANT, content="   "),
            ],
            hints=["« ces sites » : CodinGame, Codewars.", "  ", "web"],
        )
        roles = [(m.role.value, m.content) for m in engine.calls[0]["messages"]]
        assert roles[1:] == [
            ("user", "Des sites de jeux de programmation ?"),
            ("assistant", "CodinGame, Codewars."),
            ("user", "Donne-moi les liens de ces sites"),
            ("system", "« ces sites » : CodinGame, Codewars."),
            ("system", "web"),
        ], "système, tours d'avant, question, indices — rien de vide"

    def test_sans_historique_ni_indice_rien_ne_change(self, stub_search):
        engine = _MockEngine([_text_response("ok")])
        ResearchAgent(engine, stub_search, model="mock").run("q")
        assert [m.role.value for m in engine.calls[0]["messages"]] == ["system", "user"]

    def test_la_synthese_rappelle_qu_une_suite_porte_sur_le_sujet_d_avant(
        self, stub_search
    ):
        engine = _MockEngine([_text_response("ok")])
        ResearchAgent(engine, stub_search, model="mock").run("q")
        assert "A follow-up" in engine.calls[0]["messages"][0].content
