"""Métadonnées de cartable, sans transporter le document dans la liste."""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from hashlib import sha256
from html.parser import HTMLParser
from threading import Lock
from typing import Any, Mapping

# Même estimation textuelle que notePages.ts, jamais le nombre mesuré par
# l'éditeur. 19/09/2026 : les cartables chargeaient 1,1 Mo de HTML pour cela.
_CAPACITES = {
    "a4": 2800,
    "letter": 2800,
    "a5": 1400,
    "wide": 1900,
    "narrow": 2200,
    "full": 3000,
    "reading": 2400,
}
_SAUT = re.compile(
    r"""<hr[^>]*class=["'][^"']*succes-page-break[^"']*["'][^>]*>""", re.I
)
# 19/09/2026 : reparcourir 1,1 Mo de HTML coûtait 23 ms par lecture, même
# sans frappe. Une empreinte du CONTENU évite un cache périmé si deux écritures
# partagent une date. 256 entrées : quelques dizaines de Ko, aucun HTML retenu.
_CACHE_MAX = 256
_cache_pages: OrderedDict[tuple[bytes, int], int] = OrderedDict()
_cache_lock = Lock()


class _Texte(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.morceaux: list[str] = []

    def handle_data(self, data: str) -> None:
        self.morceaux.append(data)


def _calculer_pages(contenu: str, capacite: int) -> int:
    pages = 0
    for morceau in _SAUT.split(contenu):
        texte = _Texte()
        texte.feed(morceau)
        texte.close()
        normalise = " ".join("".join(texte.morceaux).split())
        # JS compte les unités UTF-16, donc deux pour un emoji hors BMP.
        longueur = len(normalise.encode("utf-16-le", errors="surrogatepass")) // 2
        pages += max(1, math.ceil(longueur / capacite))
    return max(1, pages)


def _pages(contenu: str, capacite: int) -> int:
    cle = (sha256(contenu.encode("utf-8", errors="surrogatepass")).digest(), capacite)
    with _cache_lock:
        pages = _cache_pages.get(cle)
        if pages is not None:
            _cache_pages.move_to_end(cle)
            return pages
    pages = _calculer_pages(contenu, capacite)
    with _cache_lock:
        _cache_pages[cle] = pages
        _cache_pages.move_to_end(cle)
        if len(_cache_pages) > _CACHE_MAX:
            _cache_pages.popitem(last=False)
    return pages


def resumer_note(note: Mapping[str, Any]) -> dict[str, Any]:
    capacite = _CAPACITES.get(str(note.get("pageFormat")), 2800)
    return {k: v for k, v in note.items() if k != "content"} | {
        "pageCountEstimate": _pages(str(note.get("content") or ""), capacite)
    }
