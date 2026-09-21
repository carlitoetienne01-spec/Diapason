"""Web search tool — Tavily API with DuckDuckGo fallback.

20 septembre 2026 : « Qui est le président actuel du Canada ? » cherchait
avec les réglages par défaut de ddgs — région ``us-en``, aucune fraîcheur,
pas de vertical actualités, cinq extraits sans date, moteur tiré au hasard
(``backend="auto"``). La page Wikipédia de Trudeau sortait en tête, et le 9b
ne pouvait pas « dater l'information » : aucune date ne lui arrivait. Les
résultats portent désormais un numéro, un domaine et une date quand elle
existe ; la région suit la config, la fraîcheur et le vertical actualités se
demandent par paramètre, et le moteur qui a répondu est nommé.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.security.ssrf import check_ssrf
from diapason.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# ca-fr : Carlito est à Ottawa et écrit en français ; ``us-en`` classait la
# page anglaise de Trudeau devant tout. DIAPASON_SEARCH_REGION pour un autre
# poste. Le repli sans région reste en fin de chaîne.
REGION_PAR_DEFAUT = "ca-fr"
# Un ordre fixe, pour qu'une même question rende les mêmes sources et que
# l'on sache qui a répondu. Sondé le 20/09 : duckduckgo (texte) refusait la
# région ca-fr (« No results found »), brave répondait ; les trois moteurs
# d'actualités rendaient des dates.
MOTEURS_TEXTE = ("brave", "duckduckgo", "yahoo", "mojeek")
MOTEURS_ACTUALITES = ("duckduckgo", "bing", "yahoo")
FRAICHEURS = {"day": "d", "week": "w", "month": "m", "year": "y"}
# Sous trois résultats, une seconde page du même moteur ; jamais plus.
MINIMUM_UTILE = 3
# Revue du 20/09 : quatre moteurs × trois plans + pages 2 faisaient jusqu'à
# quinze appels en série (60–75 s) qu'un exécuteur à 30 s tranchait sans un
# mot, et un moteur mort repayait ses 5 s à chaque plan. Un budget global,
# un timeout par appel, et un moteur qui lève est écarté pour tous les plans.
BUDGET_S = 12.0
TIMEOUT_MOTEUR_S = 5
# La variante actualités d'une requête texte (P4, 21/09) : trois résultats
# de plus au plus — huit résultats font ~3 200 caractères, sous les 4 000
# que le chat garde d'un résultat d'outil.
VARIANTE_RESULTATS = 3
_UTM = re.compile(r"^(?:utm_|fbclid|gclid|ref$)", re.I)


def url_canonique(url: str) -> str:
    """La même page sous deux habits (schéma, utm, ordre des paramètres,
    fragment, barre finale) compte une fois."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(parts.query) if not _UTM.match(k))
    )
    chemin = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), chemin, query, ""))


def domaine(url: str) -> str:
    try:
        hote = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    return hote[4:] if hote.startswith("www.") else hote


def date_locale(brute: str) -> str:
    """AAAA-MM-JJ dans le fuseau du poste ; ddgs rend de l'UTC.

    Revue du 20/09 : « 1 hour ago » lu à 23:50 à Ottawa donnait le lendemain.
    Revue du 21/09 : la ``published_date`` de Tavily est en RFC 2822 (« Tue,
    11 Mar 2025 17:00:00 GMT ») et devenait « Tue, 11 Ma » — une forme que
    l'analyseur de web_read ne lit pas vaut « pas de date ».
    """
    texte = str(brute or "").strip()
    if not texte:
        return ""
    try:
        from datetime import datetime

        instant = datetime.fromisoformat(texte.replace("Z", "+00:00"))
    except ValueError:
        age, _reste = date_en_tete(texte + " - ")
        if age:
            return age
        from diapason.tools.web_read import date_iso

        return date_iso(texte)
    if instant.tzinfo is not None:
        instant = instant.astimezone()
    return instant.date().isoformat()


# 21/09/2026 : les extraits de brave (texte) commencent par l'âge de la
# page — « 19 hours ago - », « August 14, 2026 - », « 2 days ago - » — et
# ddgs ne remplit ``date`` que pour les actualités. Cinq résultats sur
# « premier ministre du Canada 2026 » portaient tous une date dans leur
# extrait et aucune dans leur en-tête : le modèle ne pouvait pas les
# départager, et le code ne pouvait pas mesurer leur fraîcheur.
_AGE_RELATIF = re.compile(
    r"^\s*(?:(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago|"
    r"il y a\s+(\d+)\s+(s|sec|min|h|heures?|j|jours?|semaines?|mois|ans?))"
    r"\s*[-—·:]\s+",
    re.I,
)
# Seule la forme que brave émet (« August 14, 2026 - ») : un extrait qui
# COMMENCE par une date française ou ISO (« 14 mars 2025 - jour de
# l'assermentation… ») est du texte, pas un en-tête (revue du 21/09).
_DATE_EN_TETE = re.compile(r"^\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s+-\s+")
_JOURS_PAR_UNITE = {
    "second": 0,
    "minute": 0,
    "hour": 0,
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
    "s": 0,
    "sec": 0,
    "min": 0,
    "h": 0,
    "heure": 0,
    "j": 1,
    "jour": 1,
    "semaine": 7,
    "mois": 30,
    "an": 365,
}


def _singulier(unite: str) -> str:
    """« heures » → « heure », « jours » → « jour » ; « s » et « mois » restent."""
    unite = unite.lower()
    return unite if unite in ("s", "mois") else unite.rstrip("s")


def date_en_tete(extrait: str) -> tuple[str, str]:
    """(date AAAA-MM-JJ ou "", extrait sans son en-tête de date).

    Un âge relatif (« 2 days ago ») se compte depuis aujourd'hui, au jour
    près ; un mois vaut trente jours et un an trois cent soixante-cinq : c'est
    l'âge que brave affiche, pas une date de publication, et il sert à
    mesurer la fraîcheur, pas à la citer au jour près.
    """
    texte = str(extrait or "")
    m = _AGE_RELATIF.match(texte)
    if m:
        from datetime import date, timedelta

        nombre, unite = (
            (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        )
        jours = int(nombre) * _JOURS_PAR_UNITE[_singulier(unite)]
        return (date.today() - timedelta(days=jours)).isoformat(), texte[m.end() :]
    m = _DATE_EN_TETE.match(texte)
    if m:
        from diapason.tools.web_read import date_iso

        iso = date_iso(m.group(1))
        if iso:
            return iso, texte[m.end() :]
    return "", texte


def _normaliser_resultats(brut: list[dict[str, Any]], categorie: str) -> list[dict]:
    resultats = []
    for r in brut or ():
        url = str(r.get("url") or r.get("href") or "").strip()
        if not url:
            continue
        extrait = str(r.get("body") or r.get("content") or "").strip()
        date = date_locale(r.get("date"))
        if not date:
            date, extrait = date_en_tete(extrait)
        resultats.append(
            {
                "title": str(r.get("title") or "Sans titre").strip(),
                "url": url,
                "snippet": extrait.strip(),
                "date": date,
                "source": str(r.get("source") or "").strip() or domaine(url),
                "kind": "news" if categorie == "news" else "web",
            }
        )
    return resultats


def dedoublonner(resultats: list[dict]) -> list[dict]:
    vus: set[str] = set()
    propres = []
    for r in resultats:
        cle = url_canonique(r["url"])
        if cle in vus:
            continue
        vus.add(cle)
        propres.append(r)
    return propres


def sources_de(resultats: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "ref": i,
            "title": r["title"],
            "url": r["url"],
            "date": r["date"],
            "sender": r["source"],
        }
        for i, r in enumerate(resultats, 1)
    ]


def formater(resultats: list[dict]) -> str:
    """Numéroté [N] pour que le modèle cite ; date et domaine s'ils existent."""
    blocs = []
    for i, r in enumerate(resultats, 1):
        entete = f"[{i}] {r['title']} — {r['source']}"
        if r.get("date"):
            entete += f" · {r['date']}"
        blocs.append(f"{entete}\nSource: {r['url']}\nExtrait: {r['snippet']}")
    return "\n\n".join(blocs)


@ToolRegistry.register("web_search")
class WebSearchTool(BaseTool):
    """Search the web via Tavily API."""

    tool_id = "web_search"
    is_local = False

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        region: str | None = None,
    ):
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")
        self._max_results = max_results
        self._region = (
            region or os.environ.get("DIAPASON_SEARCH_REGION") or REGION_PAR_DEFAUT
        )

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description=(
                "Search the web for current information."
                " Returns numbered results [N] with source and date;"
                " cite them by number."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return.",
                    },
                    "recency": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "Only results from the last day/week/month/year",
                    },
                    "news": {
                        "type": "boolean",
                        "description": "Search news outlets first (dated articles).",
                    },
                },
                "required": ["query"],
            },
            category="search",
            metadata={"requires_api_key": "TAVILY_API_KEY", "fallback": "duckduckgo"},
        )

    @staticmethod
    def _is_url(text: str) -> bool:
        """Check if text is a URL."""
        stripped = text.strip()
        return stripped.startswith("http://") or stripped.startswith("https://")

    @staticmethod
    def _extract_url(text: str) -> str | None:
        """Extract the first URL from text, if any."""
        import re as _re

        match = _re.search(r"https?://[^\s,;\"'<>]+", text)
        return match.group(0).rstrip(".,;)") if match else None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Convert known PDF URLs to their HTML equivalents."""
        import re as _re

        # arxiv: /pdf/ID → /abs/ID (abstract page with full metadata)
        m = _re.match(r"(https?://arxiv\.org)/pdf/(.+?)(?:\.pdf)?$", url)
        if m:
            return f"{m.group(1)}/abs/{m.group(2)}"
        return url

    @staticmethod
    def _fetch_url(url: str, max_chars: int = 6000) -> str:
        """Fetch a URL and return extracted text content."""
        import re as _re

        import httpx

        url = WebSearchTool._normalize_url(url)
        ssrf_error = check_ssrf(url)
        if ssrf_error:
            raise ValueError(ssrf_error)
        resp = httpx.get(
            url.strip(),
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Diapason/1.0; +https://github.com/diapason)"
            },
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" in content_type:
            return (
                "[This URL points to a PDF file which"
                f" cannot be read directly. URL: {url}]"
            )
        html = resp.text
        # Strip script/style tags and their contents
        html = _re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            "",
            html,
            flags=_re.DOTALL | _re.IGNORECASE,
        )
        # Strip HTML tags
        text = _re.sub(r"<[^>]+>", " ", html)
        # Collapse whitespace
        text = _re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[Content truncated]"
        return text

    def _ddgs_search(
        self,
        query: str,
        max_results: int,
        *,
        fraicheur: str | None = None,
        actualites: bool = False,
        seulement_actualites: bool = False,
    ) -> tuple[list[dict], list[dict[str, Any]], int]:
        """Résultats, plans qui ont répondu, nombre de moteurs joints.

        Chaîne de plans, du plus précis au plus large : actualités puis texte,
        avec fraîcheur et région, puis sans fraîcheur, puis sans région. Un
        moteur qui lève est écarté pour tous les plans suivants ; le budget
        BUDGET_S borne l'ensemble. Le premier plan qui rend quelque chose
        gagne, complété d'une seconde page sous trois résultats. Chaque plan
        retenu est décrit (moteur, catégorie, filtres, nombre) : la carte ne
        prête pas les filtres d'un plan au moteur d'un autre. Zéro moteur
        joint, c'est une panne ; des moteurs qui répondent vide, c'est un vide.
        """
        import time

        from ddgs import DDGS

        ddgs = DDGS(timeout=TIMEOUT_MOTEUR_S)
        depart = time.monotonic()
        plans: list[tuple[str, tuple[str, ...], str | None, str | None]] = []
        if actualites:
            plans.append(("news", MOTEURS_ACTUALITES, fraicheur, self._region))
        if not seulement_actualites:
            # La variante actualités d'une requête texte (P4) ne redescend
            # pas sur le web général : la principale s'en charge déjà.
            plans.append(("text", MOTEURS_TEXTE, fraicheur, self._region))
            if fraicheur:
                plans.append(("text", MOTEURS_TEXTE, None, self._region))
            plans.append(("text", MOTEURS_TEXTE, None, None))
        retenus: list[dict] = []
        plans_retenus: list[dict[str, Any]] = []
        morts: set[str] = set()
        joints = 0
        for categorie, moteurs, tl, region in plans:
            if time.monotonic() - depart > BUDGET_S:
                break
            for moteur in moteurs:
                if (categorie, moteur) in morts:
                    continue
                if time.monotonic() - depart > BUDGET_S:
                    break
                options: dict[str, Any] = {
                    "max_results": max_results,
                    "backend": moteur,
                }
                if region:
                    options["region"] = region
                if tl:
                    options["timelimit"] = tl
                try:
                    brut = list(getattr(ddgs, categorie)(query, **options) or [])
                except Exception as exc:  # noqa: BLE001 - un moteur muet cède au suivant
                    logger.debug("web_search %s/%s : %s", categorie, moteur, exc)
                    # « No results found » est une réponse vide, pas une panne.
                    if "no results" in str(exc).lower():
                        joints += 1
                    else:
                        morts.add((categorie, moteur))
                    continue
                joints += 1
                resultats = dedoublonner(_normaliser_resultats(brut, categorie))
                if not resultats:
                    continue
                if len(resultats) < MINIMUM_UTILE and max_results >= MINIMUM_UTILE:
                    try:
                        suite = list(
                            getattr(ddgs, categorie)(query, page=2, **options) or []
                        )
                        resultats = dedoublonner(
                            resultats + _normaliser_resultats(suite, categorie)
                        )
                    except Exception:  # noqa: BLE001 - la seconde page est un bonus
                        pass
                avant = len(retenus)
                retenus = dedoublonner(retenus + resultats)
                plans_retenus.append(
                    {
                        "engine": f"{moteur}/{categorie}",
                        "region": region,
                        "timelimit": tl,
                        "count": len(retenus) - avant,
                    }
                )
                break
            if len(retenus) >= MINIMUM_UTILE:
                break
        return retenus[:max_results], plans_retenus, joints

    def _rechercher_avec_variante(
        self,
        query: str,
        max_results: int,
        *,
        fraicheur: str | None,
        actualites: bool,
    ) -> tuple[list[dict], list[dict[str, Any]], int]:
        """La requête, et EN PARALLÈLE sa variante mécanique (P4 du jury,
        21/09/2026) : une requête texte reçoit aussi le vertical actualités —
        des articles datés, quand le web général rend trois pages du même
        site. Jamais une reformulation par le modèle, qui dérive du sens.
        Bornée : une variante, VARIANTE_RESULTATS résultats, le même budget ;
        l'échec de la variante ne coûte rien. Les pages vues par les deux
        passent en tête — c'est ce que deux requêtes s'accordent à dire.
        """
        if actualites:
            return self._ddgs_search(
                query, max_results, fraicheur=fraicheur, actualites=True
            )
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            principale = pool.submit(
                self._ddgs_search,
                query,
                max_results,
                fraicheur=fraicheur,
                actualites=False,
            )
            variante = pool.submit(
                self._ddgs_search,
                query,
                VARIANTE_RESULTATS,
                fraicheur=fraicheur,
                actualites=True,
                seulement_actualites=True,
            )
            resultats, plans, joints = principale.result()
            try:
                autres, plans_variante, joints_variante = variante.result(
                    timeout=BUDGET_S
                )
            except Exception as exc:  # noqa: BLE001 - la variante est un bonus
                logger.debug("web_search variante : %s", exc)
                return resultats, plans, joints
        joints += joints_variante
        if not autres:
            return resultats, plans, joints
        # Les plans d'actualités de la variante ne servent que leurs
        # résultats (le premier plan est celui de la requête principale,
        # jamais un prêt de filtres d'un plan à l'autre).
        plans = plans + [{**pl, "variant": True} for pl in plans_variante]
        cles = {url_canonique(r["url"]) for r in resultats}
        communs = [r for r in autres if url_canonique(r["url"]) in cles]
        # Une page vue par les deux requêtes passe en tête, sous sa forme
        # datée (celle des actualités) quand la principale n'en avait pas.
        if communs:
            dates = {url_canonique(r["url"]): r.get("date") for r in communs}
            for r in resultats:
                if not r.get("date") and dates.get(url_canonique(r["url"])):
                    r["date"] = dates[url_canonique(r["url"])]
            communes = {url_canonique(r["url"]) for r in communs}
            resultats.sort(key=lambda r: url_canonique(r["url"]) not in communes)
        fusion = dedoublonner(resultats + autres)
        return fusion[: max_results + VARIANTE_RESULTATS], plans, joints

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="web_search",
                content="No query provided.",
                success=False,
            )

        # If the query contains a URL, read it instead of searching. 21/09/2026 :
        # l'ancien mode « fetch » (regex <[^>]+> sur tout le HTML, 6 000
        # caractères de menu) rendait la page sans sources ni numéro — le
        # lecteur de web_read donne le texte principal, les dates, et une
        # source [1] que l'interface sait afficher.
        url = self._extract_url(query) if not self._is_url(query) else query.strip()
        if url:
            try:
                from diapason.tools.web_read import WebReadTool

                lecture = WebReadTool().execute(
                    url=url, focus=query.replace(url, " ").strip()
                )
                return ToolResult(
                    tool_name="web_search",
                    content=lecture.content,
                    success=lecture.success,
                    metadata={**(lecture.metadata or {}), "mode": "fetch"},
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="web_search",
                    content=f"Failed to fetch URL: {exc}",
                    success=False,
                )

        max_results = params.get("max_results", self._max_results)
        fraicheur = FRAICHEURS.get(str(params.get("recency") or "").lower())
        actualites = bool(params.get("news"))

        try:
            if not self._api_key:
                # Sans clé, Tavily ne peut pas répondre — mais le simple fait
                # que le paquet soit installé suffisait à ce que ce chemin
                # s'essaie (constaté le 24 août 2026, après une resynchro du
                # venv) : DuckDuckGo directement.
                raise ImportError("no tavily api key")
            from tavily import TavilyClient

            client = TavilyClient(api_key=self._api_key)
            options: dict[str, Any] = {
                "max_results": max_results,
                "search_depth": "advanced",
                "include_usage": True,
            }
            # Revue du 20/09 : avec une clé, recency/news étaient annoncés
            # dans la carte et jamais transmis. Tavily les connaît sous
            # time_range et topic.
            if fraicheur:
                options["time_range"] = str(params.get("recency")).lower()
            if actualites:
                options["topic"] = "news"
            response = client.search(query, **options)
            results = dedoublonner(
                _normaliser_resultats(
                    [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "body": r.get("content") or r.get("snippet"),
                            "date": r.get("published_date"),
                        }
                        for r in response.get("results", [])
                    ],
                    "news" if actualites else "text",
                )
            )
            return ToolResult(
                tool_name="web_search",
                content=formater(results) or "No results found.",
                success=True,
                metadata={
                    "numResults": len(results),
                    "engine": "tavily",
                    "credits": (response.get("usage") or {}).get("credits"),
                    "sources": sources_de(results),
                },
            )
        except Exception as exc:
            logger.debug(
                "Tavily error (%s), falling back to DuckDuckGo", type(exc).__name__
            )

        try:
            resultats, plans, joints = self._rechercher_avec_variante(
                query,
                max_results,
                fraicheur=fraicheur,
                actualites=actualites,
            )
            if not resultats and not joints:
                return ToolResult(
                    tool_name="web_search",
                    content="Search error: aucun moteur n'a répondu (réseau ?).",
                    success=False,
                    metadata={"engine": "", "numResults": 0, "plans": []},
                )
            return ToolResult(
                tool_name="web_search",
                content=formater(resultats) or "No results found.",
                success=True,
                metadata={
                    "engine": plans[0]["engine"] if plans else "",
                    "numResults": len(resultats),
                    "plans": plans,
                    # Pour l'interface (pastilles [N] cliquables) — jamais
                    # recopié au modèle, qui lit déjà le texte numéroté.
                    "sources": sources_de(resultats),
                },
            )
        except ImportError:
            return ToolResult(
                tool_name="web_search",
                content=(
                    "tavily-python not installed and ddgs not available."
                    " Install with: pip install tavily-python ddgs"
                ),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="web_search",
                content=f"Search error: {exc}",
                success=False,
            )


__all__ = ["WebSearchTool"]
