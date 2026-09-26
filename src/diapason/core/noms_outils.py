"""Les noms canoniques des outils, et les anciens noms qui y mènent.

25/09/2026, étape 7 du plan de la phase 1b (docs/development/
diapason-mobile.md) : les sept outils ``succes_*`` s'appellent ``vie_*``. Or
leurs anciens noms sont écrits ailleurs que dans le code : dans les agents
sauvegardés (``agents.db``), dans ``config.toml``, dans ``SOUL.md`` (qui en
nomme quatre au modèle), dans l'historique des conversations, et dans la
trame WebSocket d'un client vocal pas encore reconstruit. Chacun de ces
endroits écartait un nom inconnu sans un mot : un agent qui citait
``succes_tasks`` aurait perdu l'outil, et le modèle aurait lu « Unknown
tool ».

Trois règles :

- **traduire à l'entrée**, partout où un nom arrive du disque, du réseau ou
  du modèle (:func:`nom_canonique`) ;
- **traduire AVANT le plafond** : une liste venue d'un client se confronte
  au plafond du serveur une fois traduite — restreindre, jamais élargir ;
- **jamais dans le catalogue** : un ancien nom n'est ni enregistré ni montré
  au modèle. Deux outils identiques sous deux noms feraient hésiter le 9b.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Mapping
from types import MappingProxyType

logger = logging.getLogger(__name__)

ALIAS_OUTILS: Mapping[str, str] = MappingProxyType(
    {
        "succes_tasks": "vie_tasks",
        "succes_workspace": "vie_workspace",
        "succes_continuity": "vie_continuity",
        "succes_finances": "vie_finances",
        "succes_delete_task": "vie_delete_task",
        "succes_delete_item": "vie_delete_item",
        "succes_delete_continuity": "vie_delete_continuity",
    }
)


def nom_canonique(nom: str) -> str:
    """Le nom sous lequel l'outil est enregistré ; ``nom`` s'il n'a pas d'alias."""
    return ALIAS_OUTILS.get(nom, nom)


def noms_canoniques(noms: Iterable[str]) -> list[str]:
    """Traduits, dans l'ordre, sans doublon.

    Une liste qui cite l'ancien ET le nouveau nom (un agent édité à moitié)
    ne doit pas recevoir l'outil deux fois.
    """
    vus: set[str] = set()
    sortie: list[str] = []
    for nom in noms:
        canonique = nom_canonique(nom)
        if canonique not in vus:
            vus.add(canonique)
            sortie.append(canonique)
    return sortie


_signales: set[tuple[str, str]] = set()
_verrou = threading.Lock()


def signaler_outil_inconnu(lieu: str, nom: str) -> None:
    """Un nom d'outil écarté : un WARNING, une fois par lieu et par nom.

    Avant le 25/09/2026, quatre endroits (l'exécuteur d'agents, la trousse du
    chat, le constructeur du système, la liste vocale) écartaient un nom
    inconnu en silence, ou au niveau DEBUG que personne ne lit. Une fois par
    processus suffit : la liste vocale se recalcule à chaque session, et un
    journal qui répète la même ligne apprend à ne plus être lu.
    """
    cle = (lieu, nom)
    with _verrou:
        if cle in _signales:
            return
        _signales.add(cle)
    logger.warning(
        "outil %r écarté (%s) : aucun outil de ce nom n'est enregistré", nom, lieu
    )


__all__ = [
    "ALIAS_OUTILS",
    "nom_canonique",
    "noms_canoniques",
    "signaler_outil_inconnu",
]
