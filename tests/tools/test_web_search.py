"""Tests for the web search tool."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

from diapason.core.registry import ToolRegistry
from diapason.tools.web_search import WebSearchTool


@pytest.fixture
def recherche_de_repli(monkeypatch):
    """§100 : tester le repli sans dépendre d'un vrai moteur de recherche."""
    module = MagicMock()
    module.DDGS.return_value.text.return_value = [
        {"title": "Résultat témoin", "href": "https://example.com", "body": "Texte"}
    ]
    monkeypatch.setitem(sys.modules, "ddgs", module)
    return module.DDGS.return_value.text


class TestWebSearchTool:
    def test_spec_name_and_category(self):
        tool = WebSearchTool(api_key="test-key")
        assert tool.spec.name == "web_search"
        assert tool.spec.category == "search"

    def test_spec_requires_api_key_metadata(self):
        tool = WebSearchTool(api_key="test-key")
        assert tool.spec.metadata["requires_api_key"] == "TAVILY_API_KEY"

    def test_spec_parameters_require_query(self):
        tool = WebSearchTool(api_key="test-key")
        assert "query" in tool.spec.parameters["properties"]
        assert "query" in tool.spec.parameters["required"]

    def test_execute_no_query(self):
        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="")
        assert result.success is False
        assert "No query" in result.content

    def test_execute_no_query_param(self):
        tool = WebSearchTool(api_key="test-key")
        result = tool.execute()
        assert result.success is False
        assert "No query" in result.content

    def test_execute_no_api_key(self, monkeypatch, recherche_de_repli):
        """When no API key, falls back to DuckDuckGo."""
        tool = WebSearchTool(api_key=None)
        with patch.dict("os.environ", {}, clear=True):
            tool._api_key = None
            monkeypatch.delitem(sys.modules, "tavily", raising=False)
            result = tool.execute(query="test query")
        assert result.success is True
        assert result.metadata["engine"] == "brave/text", (
            "le premier moteur de la chaîne fixe qui a répondu est nommé"
        )
        assert recherche_de_repli.call_args_list[0] == call(
            "test query", max_results=5, backend="brave", region="ca-fr"
        ), "région du poste et premier moteur de la chaîne fixe"

    def test_execute_mocked_tavily(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Content about test.",
                },
                {
                    "title": "Result 2",
                    "url": "https://example.com/2",
                    "content": "More content.",
                },
            ]
        }
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client

        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                mock_errors = MagicMock()
                mock_errors.UsageLimitExceededError = Exception
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert "Result 1" in result.content
        assert "Result 2" in result.content
        assert result.metadata["numResults"] == 2, "camelCase sur le fil (CLAUDE.md §3)"
        assert [src["ref"] for src in result.metadata["sources"]] == [1, 2]

    def test_execute_tavily_error(self, monkeypatch, recherche_de_repli):
        """When Tavily errors (any error), falls back to DuckDuckGo."""
        import builtins
        from typing import Any

        original_import = builtins.__import__

        class TavilyError(Exception):
            def __init__(self, message: str):
                super().__init__(message)

        mock_client = MagicMock()
        mock_client.search.side_effect = TavilyError("API error")
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client

        def _mock_import(name: str, *args: Any, **kwargs: Any):
            if name == "tavily":
                return mock_tavily_module
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert result.metadata["engine"] == "brave/text", (
            "le premier moteur de la chaîne fixe qui a répondu est nommé"
        )
        assert recherche_de_repli.call_args_list[0] == call(
            "test query", max_results=5, backend="brave", region="ca-fr"
        ), "région du poste et premier moteur de la chaîne fixe"

    def test_execute_duckduckgo_fallback_format(self, monkeypatch):
        """DuckDuckGo fallback returns properly formatted results."""
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.side_effect = ImportError(
            "No module named 'tavily'"
        )
        monkeypatch.setitem(sys.modules, "tavily", mock_tavily_module)

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = [
            {
                "title": "DDG Result 1",
                "href": "https://example.com/1",
                "body": "Content 1",
            },
            {
                "title": "DDG Result 2",
                "href": "https://example.com/2",
                "body": "Content 2",
            },
        ]
        mock_ddgs_module = MagicMock()
        mock_ddgs_module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", mock_ddgs_module)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert "DDG Result 1" in result.content
        assert "DDG Result 2" in result.content
        assert "https://example.com/1" in result.content
        assert result.metadata["engine"] == "brave/text"
        assert result.content.startswith("[1] DDG Result 1 — example.com"), (
            "numéroté, avec le domaine, pour que le modèle cite [N]"
        )
        assert [s["ref"] for s in result.metadata["sources"]] == [1, 2]

    def test_max_results_parameter(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
        mock_errors = MagicMock()

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key", max_results=3)
        tool.execute(query="test", max_results=7)
        mock_client.search.assert_called_once_with(
            "test", max_results=7, search_depth="advanced", include_usage=True
        )

    def test_to_openai_function(self):
        tool = WebSearchTool(api_key="test-key")
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "web_search"
        assert "query" in fn["function"]["parameters"]["properties"]

    def test_execute_import_error(self, monkeypatch, recherche_de_repli):
        """When tavily-python not installed, falls back to DuckDuckGo."""
        monkeypatch.delitem(sys.modules, "tavily", raising=False)
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                raise ImportError("No module named 'tavily'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        assert result.metadata["engine"] == "brave/text", (
            "le premier moteur de la chaîne fixe qui a répondu est nommé"
        )
        assert recherche_de_repli.call_args_list[0] == call(
            "test query", max_results=5, backend="brave", region="ca-fr"
        ), "région du poste et premier moteur de la chaîne fixe"

    def test_empty_results(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
        mock_errors = MagicMock()

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="obscure query")
        assert result.success is True
        assert result.content == "No results found."

    def test_tool_id(self):
        tool = WebSearchTool(api_key="test-key")
        assert tool.tool_id == "web_search"

    def test_registry_registration(self):
        ToolRegistry.register_value("web_search", WebSearchTool)
        assert ToolRegistry.contains("web_search")

    def test_tavily_results_use_labeled_content_format(self, monkeypatch):
        """Regression for #390: results expose page CONTENT under labeled
        Source/Summary headings (so agents synthesize content, not echo
        URLs), and Tavily is queried with search_depth='advanced'."""
        import builtins

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Content about test.",
                },
            ]
        }
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                mock_errors = MagicMock()
                mock_errors.UsageLimitExceededError = Exception
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert result.success is True
        # Labeled structure with the page content surfaced.
        assert result.content.startswith("[1] Result 1 — example.com"), (
            "avec une clé aussi, numéroté : la consigne demande de citer [N]"
        )
        assert "Source: https://example.com/1" in result.content
        assert "Extrait: Content about test." in result.content
        # search_depth='advanced' is what pulls richer content from Tavily.
        _, kwargs = mock_client.search.call_args
        assert kwargs.get("search_depth") == "advanced"

    def test_tavily_falls_back_to_snippet_when_no_content(self, monkeypatch):
        """When a Tavily result lacks 'content', the 'snippet' field is used
        for the Summary rather than rendering an empty summary."""
        import builtins

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Snippet Only",
                    "url": "https://example.com/s",
                    "snippet": "Fallback snippet text.",
                },
            ]
        }
        mock_tavily_module = MagicMock()
        mock_tavily_module.TavilyClient.return_value = mock_client
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "tavily":
                return mock_tavily_module
            if name == "tavily.errors":
                mock_errors = MagicMock()
                mock_errors.UsageLimitExceededError = Exception
                return mock_errors
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="test query")
        assert "Extrait: Fallback snippet text." in result.content


# ---------------------------------------------------------------------------
# URL detection and fetching tests
# ---------------------------------------------------------------------------


class TestUrlDetection:
    def test_is_url_https(self):
        assert WebSearchTool._is_url("https://example.com") is True

    def test_is_url_http(self):
        assert WebSearchTool._is_url("http://example.com") is True

    def test_is_url_with_whitespace(self):
        assert WebSearchTool._is_url("  https://example.com  ") is True

    def test_is_url_plain_text(self):
        assert WebSearchTool._is_url("what are punic wars") is False

    def test_is_url_empty(self):
        assert WebSearchTool._is_url("") is False

    def test_extract_url_from_text(self):
        url = WebSearchTool._extract_url(
            "Summarize this: https://example.com/page please"
        )
        assert url == "https://example.com/page"

    def test_extract_url_none_when_absent(self):
        assert WebSearchTool._extract_url("no urls here") is None

    def test_extract_url_strips_trailing_punctuation(self):
        url = WebSearchTool._extract_url("See https://example.com/page.")
        assert url == "https://example.com/page"

    def test_extract_url_from_complex_text(self):
        url = WebSearchTool._extract_url(
            "Read https://arxiv.org/abs/2310.03714 and summarize"
        )
        assert url == "https://arxiv.org/abs/2310.03714"


class TestUrlNormalization:
    def test_arxiv_pdf_to_abs(self):
        url = WebSearchTool._normalize_url("https://arxiv.org/pdf/2310.03714")
        assert url == "https://arxiv.org/abs/2310.03714"

    def test_arxiv_pdf_with_extension(self):
        url = WebSearchTool._normalize_url("https://arxiv.org/pdf/2310.03714.pdf")
        assert url == "https://arxiv.org/abs/2310.03714"

    def test_non_arxiv_unchanged(self):
        url = WebSearchTool._normalize_url("https://example.com/page")
        assert url == "https://example.com/page"

    def test_arxiv_abs_unchanged(self):
        url = WebSearchTool._normalize_url("https://arxiv.org/abs/2310.03714")
        assert url == "https://arxiv.org/abs/2310.03714"


class TestUrlFetching:
    def _mock_ssrf(self, monkeypatch):
        """Stub out the SSRF check (requires Rust backend)."""
        import diapason.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: None)

    def test_fetch_url_success(self, monkeypatch):
        """Mocked HTTP GET returns HTML, stripped to text."""
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Hello world</p></body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com")
        assert "Hello world" in content

    def test_fetch_url_strips_scripts(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><script>var x=1;</script><body>Content</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com")
        assert "var x" not in content
        assert "Content" in content

    def test_fetch_url_truncates_long_content(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<p>" + "x" * 10000 + "</p>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com", max_chars=100)
        assert len(content) < 200
        assert "[Content truncated]" in content

    def test_fetch_url_pdf_content_type(self, monkeypatch):
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "%PDF-1.4 binary data"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        content = WebSearchTool._fetch_url("https://example.com/file.pdf")
        assert "PDF" in content
        assert "cannot be read" in content


class TestExecuteWithUrl:
    def _mock_ssrf(self, monkeypatch):
        """Stub out the SSRF check (requires Rust backend)."""
        import diapason.tools.web_search as _ws

        monkeypatch.setattr(_ws, "check_ssrf", lambda url: None)

    def test_execute_with_url_query(self, monkeypatch):
        """When query is a URL, fetch instead of search."""
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Page content here</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="https://example.com/article")
        assert result.success is True
        assert "Page content here" in result.content
        assert result.metadata.get("mode") == "fetch"

    def test_execute_with_embedded_url(self, monkeypatch):
        """When query contains a URL within text, detect and fetch it."""
        import httpx

        self._mock_ssrf(monkeypatch)
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Article text</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_resp))

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="Summarize https://example.com/article please")
        assert result.success is True
        assert result.metadata.get("mode") == "fetch"

    def test_execute_url_ssrf_blocked(self, monkeypatch):
        """SSRF check rejects unsafe URLs before any HTTP request."""
        import diapason.tools.web_search as _ws

        monkeypatch.setattr(
            _ws,
            "check_ssrf",
            lambda url: "private IP blocked",
        )

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="http://169.254.169.254/metadata")
        assert result.success is False
        assert "private IP blocked" in result.content

    def test_execute_url_fetch_failure(self, monkeypatch):
        """URL fetch failure returns error result."""
        import httpx

        self._mock_ssrf(monkeypatch)
        monkeypatch.setattr(
            httpx,
            "get",
            MagicMock(side_effect=httpx.HTTPError("Connection failed")),
        )

        tool = WebSearchTool(api_key="test-key")
        result = tool.execute(query="https://example.com/broken")
        assert result.success is False
        assert "Failed to fetch URL" in result.content


class TestLaRechercheDateeEtNommee:
    """20/09/2026 : cinq extraits sans date, région us-en, moteur au hasard."""

    @staticmethod
    def _outil(monkeypatch, moteurs):
        """Un DDGS dont chaque moteur répond selon `moteurs` (liste ou exception)."""
        mock_ddgs = MagicMock()

        def repondre(categorie):
            def _rep(query, **kw):
                reponse = moteurs.get((categorie, kw.get("backend")), [])
                if isinstance(reponse, Exception):
                    raise reponse
                if kw.get("page") == 2:
                    return []
                return reponse

            return _rep

        mock_ddgs.text.side_effect = repondre("text")
        mock_ddgs.news.side_effect = repondre("news")
        module = MagicMock()
        module.DDGS.return_value = mock_ddgs
        monkeypatch.setitem(sys.modules, "ddgs", module)
        monkeypatch.delitem(sys.modules, "tavily", raising=False)
        outil = WebSearchTool(api_key=None, region="ca-fr")
        outil._api_key = None
        return outil, mock_ddgs

    def test_les_actualites_passent_en_premier_avec_leur_date(self, monkeypatch):
        outil, ddgs = self._outil(
            monkeypatch,
            {
                ("news", "duckduckgo"): [
                    {
                        "title": "Carney assermenté",
                        "url": "https://ledevoir.com/a?utm_source=x",
                        "body": "…",
                        "date": "2026-09-18T10:00:00",
                        "source": "Le Devoir",
                    },
                    {
                        "title": "Doublon",
                        "url": "https://ledevoir.com/a/",
                        "body": "…",
                        "date": "2026-09-18",
                        "source": "Le Devoir",
                    },
                    {
                        "title": "France 24",
                        "url": "https://france24.com/b",
                        "body": "…",
                        "date": "2026-09-17",
                        "source": "France 24",
                    },
                ]
            },
        )
        resultat = outil.execute(
            query="premier ministre du Canada", news=True, recency="month"
        )
        assert resultat.success
        assert resultat.content.startswith(
            "[1] Carney assermenté — Le Devoir · 2026-09-18\nSource: https://ledevoir.com/a?utm_source=x"
        )
        assert "[2] France 24 — France 24 · 2026-09-17" in resultat.content
        assert "Doublon" not in resultat.content, "utm et barre finale : la même page"
        assert resultat.metadata["engine"] == "duckduckgo/news"
        assert resultat.metadata["plans"] == [
            {
                "engine": "duckduckgo/news",
                "region": "ca-fr",
                "timelimit": "m",
                "count": 2,
            }
        ], "la carte décrit le plan qui a répondu, pas un mélange de plans"
        assert ddgs.news.call_args_list[0].kwargs == {
            "max_results": 5,
            "backend": "duckduckgo",
            "region": "ca-fr",
            "timelimit": "m",
        }
        assert [s["sender"] for s in resultat.metadata["sources"]] == [
            "Le Devoir",
            "France 24",
        ]

    def test_un_moteur_muet_cede_au_suivant_et_les_filtres_se_relachent(
        self, monkeypatch
    ):
        # Sondé le 20/09 : duckduckgo (texte) refusait la région ca-fr.
        outil, ddgs = self._outil(
            monkeypatch,
            {
                ("text", "brave"): Exception("No results found."),
                ("text", "duckduckgo"): [],
                ("text", "yahoo"): [
                    {"title": "A", "href": "https://a.example/1", "body": "…"},
                    {"title": "B", "href": "https://a.example/2", "body": "…"},
                    {"title": "C", "href": "https://a.example/3", "body": "…"},
                ],
            },
        )
        resultat = outil.execute(query="taux directeur", recency="year")
        assert resultat.success
        assert resultat.metadata["engine"] == "yahoo/text"
        assert resultat.metadata["numResults"] == 3
        assert "[3] C — a.example" in resultat.content
        assert " · " not in resultat.content.split("\n")[0], (
            "sans date connue, aucune date inventée (§5)"
        )
        appels = [c.kwargs.get("backend") for c in ddgs.text.call_args_list]
        assert appels[:3] == ["brave", "duckduckgo", "yahoo"], "ordre fixe, nommé"

    def test_sans_aucun_resultat_le_vide_est_dit_tel_quel(self, monkeypatch):
        outil, _ = self._outil(monkeypatch, {})
        resultat = outil.execute(query="zzz", recency="day", news=True)
        assert resultat.success
        assert resultat.content == "No results found."
        assert resultat.metadata["numResults"] == 0
        assert resultat.metadata["sources"] == []

    def test_url_canonique_et_domaine(self):
        from diapason.tools.web_search import domaine, url_canonique

        assert url_canonique("https://WWW.Site.ca/page/?utm_campaign=x&b=2#frag") == (
            "https://www.site.ca/page?b=2"
        )
        assert url_canonique("https://site.ca/") == "https://site.ca/"
        assert domaine("https://www.ledevoir.com/x") == "ledevoir.com"
        assert domaine("pas une url") == ""


class TestLeBudgetEtLesPannes:
    """Revue du 20/09 : quinze appels en série, moteur mort repayé, panne dite vide."""

    def test_un_moteur_qui_leve_est_ecarte_pour_tous_les_plans(self, monkeypatch):
        appels = []

        def brave(query, **kw):
            appels.append(("brave", kw.get("timelimit"), kw.get("region")))
            raise TimeoutError("brave ne répond pas")

        def yahoo(query, **kw):
            appels.append(("yahoo", kw.get("timelimit"), kw.get("region")))
            return [{"title": "A", "href": "https://a.example/1", "body": "…"}]

        outil, _ = TestLaRechercheDateeEtNommee._outil(monkeypatch, {})
        mock_ddgs = sys.modules["ddgs"].DDGS.return_value

        def text(query, **kw):
            if kw.get("backend") == "brave":
                return brave(query, **kw)
            if kw.get("backend") == "yahoo":
                return yahoo(query, **kw)
            appels.append((kw.get("backend"), kw.get("timelimit"), kw.get("region")))
            return []

        mock_ddgs.text.side_effect = text
        resultat = outil.execute(query="q", recency="year")
        assert resultat.success and resultat.metadata["numResults"] == 1
        assert [a for a in appels if a[0] == "brave"] == [("brave", "y", "ca-fr")], (
            "un moteur qui lève n'est plus rappelé par les plans suivants"
        )

    def test_le_budget_borne_la_chaine(self, monkeypatch):
        from diapason.tools import web_search

        horloge = {"t": 0.0}
        monkeypatch.setattr(web_search, "BUDGET_S", 3.0)
        outil, _ = TestLaRechercheDateeEtNommee._outil(monkeypatch, {})
        mock_ddgs = sys.modules["ddgs"].DDGS.return_value
        appels = []

        def lent(query, **kw):
            appels.append(kw.get("backend"))
            horloge["t"] += 2.0  # chaque moteur coûte deux secondes fictives
            return []

        mock_ddgs.text.side_effect = lent
        mock_ddgs.news.side_effect = lent
        import time as _time

        monkeypatch.setattr(_time, "monotonic", lambda: horloge["t"])
        resultat = outil.execute(query="q", recency="year", news=True)
        assert resultat.success and resultat.content == "No results found."
        assert len(appels) <= 3, "le budget arrête la chaîne, pas l'exécuteur à 30 s"

    def test_aucun_moteur_joint_est_une_panne_pas_un_vide(self, monkeypatch):
        outil, _ = TestLaRechercheDateeEtNommee._outil(monkeypatch, {})
        mock_ddgs = sys.modules["ddgs"].DDGS.return_value
        mock_ddgs.text.side_effect = TimeoutError("réseau coupé")
        mock_ddgs.news.side_effect = TimeoutError("réseau coupé")
        resultat = outil.execute(query="q")
        assert resultat.success is False
        assert resultat.content.startswith("Search error: aucun moteur")

    def test_max_results_est_un_plafond(self, monkeypatch):
        outil, _ = TestLaRechercheDateeEtNommee._outil(
            monkeypatch,
            {
                ("text", "brave"): [
                    {"title": f"R{i}", "href": f"https://x.example/{i}", "body": "…"}
                    for i in range(5)
                ]
            },
        )
        resultat = outil.execute(query="q", max_results=2)
        assert resultat.metadata["numResults"] == 2

    def test_la_date_est_celle_du_poste(self, monkeypatch):
        from diapason.tools.web_search import date_locale

        assert date_locale("2026-09-18") == "2026-09-18"
        assert date_locale("") == ""
        from datetime import date as _date

        assert date_locale("il y a 3 h") == _date.today().isoformat(), (
            "un âge relatif devient une date ; « il y a 3 h » n'est pas un en-tête"
        )
        assert date_locale("il y a 2 jours") == (
            _date.fromordinal(_date.today().toordinal() - 2).isoformat()
        )
        # Un instant UTC se lit dans le fuseau du poste, jamais tronqué en UTC.
        from datetime import datetime, timezone

        instant = datetime(2026, 9, 21, 3, 50, tzinfo=timezone.utc)
        assert (
            date_locale(instant.isoformat()) == instant.astimezone().date().isoformat()
        )


class TestLaDateEnTeteDesExtraits:
    """21/09/2026 : brave (texte) ne date pas ses résultats, mais chaque extrait
    commence par l'âge de la page — « 19 hours ago - », « August 14, 2026 - ».
    Cinq extraits datés, aucune date dans l'en-tête : le modèle ne pouvait pas
    les départager et le code ne pouvait pas mesurer leur fraîcheur."""

    def test_un_age_relatif_se_compte_depuis_aujourd_hui(self):
        from datetime import date, timedelta

        from diapason.tools.web_search import date_en_tete

        aujourd_hui = date.today()
        assert date_en_tete("19 hours ago - In 2025, Carney campaigned.") == (
            aujourd_hui.isoformat(),
            "In 2025, Carney campaigned.",
        ), "des heures, c'est aujourd'hui"
        assert date_en_tete("2 days ago - Trudeau announced.") == (
            (aujourd_hui - timedelta(days=2)).isoformat(),
            "Trudeau announced.",
        )
        assert (
            date_en_tete("3 weeks ago — texte")[0]
            == (aujourd_hui - timedelta(days=21)).isoformat()
        )
        assert (
            date_en_tete("1 month ago - texte")[0]
            == (aujourd_hui - timedelta(days=30)).isoformat()
        ), "un mois vaut trente jours : un âge, pas une date"

    def test_une_date_absolue_anglaise(self):
        from diapason.tools.web_search import date_en_tete

        assert date_en_tete("August 14, 2026 - ↑ « À propos »") == (
            "2026-08-14",
            "↑ « À propos »",
        )

    def test_seule_la_forme_de_brave_est_un_en_tete(self):
        """Revue du 21/09 : « 14 mars 2025 - jour de l'assermentation » est du
        texte qui commence par une date, pas un en-tête — le lire comme tel
        datait la page du fait qu'elle raconte."""
        from diapason.tools.web_search import date_en_tete

        assert date_en_tete("14 mars 2025 - jour de l'assermentation") == (
            "",
            "14 mars 2025 - jour de l'assermentation",
        )
        assert date_en_tete("2026-09-02 · Annonce") == ("", "2026-09-02 · Annonce")

    def test_sans_en_tete_l_extrait_reste_entier(self):
        from diapason.tools.web_search import date_en_tete

        assert date_en_tete("Le 14 mars 2025, Carney a prêté serment.") == (
            "",
            "Le 14 mars 2025, Carney a prêté serment.",
        ), "une date au milieu d'une phrase n'est pas un en-tête"
        assert date_en_tete("") == ("", "")
        assert date_en_tete("06/17/2016 - Drupal") == ("", "06/17/2016 - Drupal"), (
            "une forme ambiguë n'est jamais devinée"
        )

    def test_les_resultats_texte_prennent_la_date_de_leur_extrait(self):
        from datetime import date

        from diapason.tools.web_search import _normaliser_resultats

        [texte, actualite] = _normaliser_resultats(
            [
                {"title": "A", "href": "https://a.ca", "body": "19 hours ago - Corps."},
                {
                    "title": "B",
                    "url": "https://b.ca",
                    "body": "2 days ago - Corps.",
                    "date": "2026-09-01T10:00:00+00:00",
                },
            ],
            "text",
        )
        assert texte["date"] == date.today().isoformat()
        assert texte["snippet"] == "Corps.", "l'en-tête ne se lit pas deux fois"
        assert actualite["date"] == "2026-09-01", (
            "une date fournie par le moteur gagne sur l'âge de l'extrait"
        )
        assert actualite["snippet"] == "2 days ago - Corps.", (
            "l'extrait d'un résultat déjà daté n'est pas retouché"
        )

    def test_la_date_apparait_dans_l_en_tete_numerote(self):
        from datetime import date

        from diapason.tools.web_search import _normaliser_resultats, formater

        bloc = formater(
            _normaliser_resultats(
                [
                    {
                        "title": "A",
                        "href": "https://a.ca/x",
                        "body": "5 days ago - Corps.",
                    }
                ],
                "text",
            )
        )
        attendu = date.fromordinal(date.today().toordinal() - 5).isoformat()
        assert bloc.splitlines()[0] == f"[1] A — a.ca · {attendu}", (
            "la date est dans l'en-tête que lit le modèle"
        )


class TestLaDateDeTavily:
    def test_le_rfc_2822_de_tavily_est_lu_entier(self):
        """Revue du 21/09 : « Tue, 11 Mar 2025 17:00:00 GMT » devenait
        « Tue, 11 Ma »."""
        from diapason.tools.web_search import date_locale

        assert date_locale("Tue, 11 Mar 2025 17:00:00 GMT") == "2025-03-11"
        assert date_locale("n'importe quoi") == "", (
            "une forme inconnue vaut pas de date"
        )
