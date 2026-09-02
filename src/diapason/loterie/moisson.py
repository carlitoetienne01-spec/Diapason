"""Aller chercher l'historique, poliment.

Les sources officielles — Loto-Québec, OLG — rendent leurs résultats en
JavaScript, sans export : elles ne se récupèrent pas sans piloter un
navigateur. L'archive utilisée ici est un TIERS qui sert le même historique en
HTML brut. Elle n'est pas crue sur parole : `validation.controler` la confronte
aux fréquences publiées par Loto-Québec, et rien ne s'affiche sans cet accord.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from diapason.loterie.depot import DepotTirages
from diapason.loterie.tirages import Tirage, analyser_page

logger = logging.getLogger(__name__)

SOURCE = "https://www.lotto-8.com/canada/listltoCADG.asp"
#: 45 pages couvraient l'historique complet le 31 août 2026. La moisson
#: s'arrête d'elle-même sur une page vide ; ce nombre n'est qu'un plafond.
PAGES_MAX = 60
#: Une seconde entre deux pages. Quarante-cinq pages en quarante-cinq
#: secondes ne dérange personne ; les enchaîner aussi vite que possible, si.
REPOS_S = 1.0
_ENTETES = {
    "User-Agent": "Diapason/1.0 (assistant personnel local ; usage personnel)",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
}


@dataclass(frozen=True, slots=True)
class Recolte:
    pages_lues: int
    tirages_lus: int
    tirages_neufs: int
    arret: str


def _page(indice: int) -> str:
    return f"{SOURCE}?indexpage={indice}&orderby=new"


async def moissonner(
    depot: DepotTirages,
    pages: int = PAGES_MAX,
    repos_s: float = REPOS_S,
    client: httpx.AsyncClient | None = None,
) -> Recolte:
    """Lire les pages une à une jusqu'à n'apprendre plus rien.

    ARRÊT SUR PAGE STÉRILE, pas sur un compteur : le jour où l'archive gagnera
    une page, la moisson la prendra sans qu'on touche à une constante ; le jour
    où elle en perdra une, elle s'arrêtera au lieu de battre le vide.
    """
    propre = client is None
    http = client or httpx.AsyncClient(timeout=20.0, headers=_ENTETES)
    lues = 0
    lus = 0
    neufs = 0
    arret = f"plafond de {pages} pages atteint"
    try:
        for indice in range(1, pages + 1):
            if indice > 1:
                await asyncio.sleep(repos_s)
            try:
                reponse = await http.get(_page(indice))
                # UN 404 APRÈS DES PAGES LUES EST UNE FIN, PAS UNE PANNE.
                # L'archive s'arrête à sa dernière page et rend 404 au-delà.
                # Le compter comme une erreur ferait afficher « page illisible »
                # à chaque moisson réussie — un rouge permanent ne signale plus
                # rien. Sur la PREMIÈRE page, en revanche, c'est bien une panne.
                if reponse.status_code == 404 and lues > 0:
                    arret = f"fin de l'archive à la page {indice - 1}"
                    break
                reponse.raise_for_status()
            except httpx.HTTPError as exc:
                arret = f"page {indice} illisible : {exc}"
                break
            lues += 1
            tirages = analyser_page(reponse.text)
            if not tirages:
                arret = f"page {indice} sans aucun tirage — fin de l'archive"
                break
            lus += len(tirages)
            avant = neufs
            # `enregistrer` écrit sur le disque. Dans une coroutine, un appel
            # bloquant s'exécute SUR LA BOUCLE et gèle tout le serveur — le
            # WebSocket vocal, le flux du chat, la cloche d'approbation. Quatre
            # cent cinquante écritures SQLite y suffiraient largement.
            neufs += await asyncio.to_thread(depot.enregistrer, tirages)
            if neufs == avant and indice > 1:
                arret = f"page {indice} n'apportait rien de neuf"
                break
    finally:
        if propre:
            await http.aclose()
    logger.info("moisson loterie : %d pages, %d tirages, %d neufs", lues, lus, neufs)
    return Recolte(pages_lues=lues, tirages_lus=lus, tirages_neufs=neufs, arret=arret)


def tirages_du_depot(depot: DepotTirages) -> list[Tirage]:
    return depot.tous()
