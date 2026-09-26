"""Ce qu'une collection fournit au moteur de synchronisation (§4.8).

Conception : ``docs/development/compte-chiffre.md`` §4.3 (le cycle), §4.7
(conversations et pièces) et §4.8 (ajouter une collection).

Le moteur ne connaît AUCUNE application : il range des clairs
``{"v":1,"collection":…,"id":…,"schema":…,"data"|"deleted":…}`` sous un
``objectId`` opaque. Tout ce qui sait ce qu'est une conversation vit dans
l'adaptateur qui implémente :class:`Collection` — sa projection, sa règle
de fusion, sa façon de poser une tombale.

Les méthodes des pièces (``pieces``, ``detacher``, ``rattacher``, ``trous``,
``combler``) ont ici une implémentation neutre : une collection sans pièces
n'a rien à en dire. ``conversations`` les implémente (étape 11, §4.7).

**Trois formes d'un même clair** (étape 11, 24/09/2026) :

- **attachée** — ce que le magasin porte : ``clair_local``, l'export, et
  l'empreinte ``H(clair)`` que ``connus`` retient. Indépendante de l'époque :
  une rotation ne rend aucune conversation « différente » d'elle-même ;
- **détachée** — ce qui est scellé : chaque image remplacée par
  ``"diapason-piece:<pieceId>"`` sous l'époque COURANTE. :meth:`detacher`
  ne s'appelle qu'au scellement ;
- **trouée** — une forme attachée où les images d'un message restent des
  références parce qu'une pièce manque (404, §4.7 « dégradé ») : tout le
  message garde ses références, jamais un mélange. Le magasin ne voit
  JAMAIS de référence (``ingerer`` retire les images d'un message troué) ;
  le moteur retient les trous et les rend par :meth:`combler` avant
  d'empreindre ou de pousser — c'est ce qui fait qu'un appareil dégradé
  n'efface pas l'image du serveur.

Pourquoi l'empreinte se prend sur la forme attachée : prise sur ce que le
serveur rend sans rattacher, elle aurait différé de la copie locale à
chaque tirage d'une conversation illustrée, qui serait repartie à chaque
cycle ; prise sur la forme détachée, elle dépendrait de l'époque, et une
rotation aurait fait repousser d'un coup toutes les conversations
illustrées au lieu de « la prochaine poussée » du §4.7.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Changement", "Collection"]


@dataclass(frozen=True)
class Changement:
    """Une écriture locale que l'export doit considérer.

    ``clair`` est le clair PROJETÉ tel que la collection le pousserait —
    lu dans la même transaction que ``seq``, pour que l'export ne relise
    pas une version plus récente que le curseur qu'il va poser.
    ``supprime_le_ms`` vaut ``deletedAt`` pour une tombale, ``None`` sinon.
    """

    id_local: str
    clair: dict[str, Any] = field(repr=False)
    supprime_le_ms: int | None = None


class Collection(ABC):
    """L'interface du §4.8 : ``nom``, ``schema``, ``changements_depuis``,
    ``clair_local``, ``ingerer``, ``pieces``, ``detacher``, ``rattacher``.

    S'y ajoutent trois lectures dont le moteur a besoin pour dire la vérité
    à l'écran (§100) : :meth:`date_de`, :meth:`a_des_donnees` et
    :meth:`en_attente_depuis`.
    """

    nom: str
    schema: int

    @abstractmethod
    def changements_depuis(self, seq: int) -> tuple[list[Changement], int]:
        """Les écritures de numéro ``> seq`` et le numéro où poser le curseur.

        Le numéro rendu couvre tout ce qui est rendu : une écriture qui
        arrive pendant la lecture prend un numéro plus grand et sera vue à
        l'export suivant — jamais sautée.
        """

    @abstractmethod
    def clair_local(self, id_local: str) -> dict[str, Any] | None:
        """Le clair projeté de la copie LOCALE (vivante ou tombale), ou
        ``None`` si l'objet n'existe plus ici (tombale purgée, jamais vu)."""

    @abstractmethod
    def ingerer(self, clair: dict[str, Any]) -> None:
        """Fusionne un clair venu du serveur avec la copie locale, par la
        règle de la collection. Lève ``ClairInvalide`` sur un clair dont la
        forme de ``data`` n'est pas celle de la collection."""

    @abstractmethod
    def date_de(self, clair: dict[str, Any]) -> int:
        """La date de Lamport d'un clair vivant (``updatedAt`` pour une
        conversation) : ce que les planchers de suppression comparent."""

    @abstractmethod
    def a_des_donnees(self) -> bool:
        """Des données locales existent-elles (``needsConsent``, §3.11 P3) ?"""

    @abstractmethod
    def en_attente_depuis(self, seq: int) -> set[str]:
        """Les identifiants écrits après ``seq`` et pas encore exportés :
        ils comptent dans ``pendingCount``. Sans eux, une vue qui écrit une
        seconde avant la fermeture de l'app aurait lu « 0 en attente »
        pendant les 5 s de calme du moteur — et la fermeture n'aurait pas
        poussé (P10)."""

    def pieces(self, clair: dict[str, Any]) -> list[str]:
        """Les ``pieceId`` qu'un clair détaché ou troué référence."""
        return []

    def detacher(
        self, clair: dict[str, Any], nommer: Callable[[bytes], str]
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        """La forme détachée, et le clair de chaque pièce par ``pieceId``.

        ``nommer`` rend le ``pieceId`` d'un clair de pièce sous une époque
        que choisit le moteur. Une référence déjà présente (un message
        troué, rendu par :meth:`combler`) reste telle quelle."""
        return clair, {}

    def rattacher(
        self, clair: dict[str, Any], fournir: Callable[[str], bytes | None]
    ) -> dict[str, Any]:
        """Réinjecte chaque pièce à l'identique ; ``fournir`` rend le clair
        d'une pièce, ou ``None`` si elle manque. Un message dont une pièce
        manque garde TOUTES ses références (forme trouée)."""
        return clair

    def trous(self, clair: dict[str, Any]) -> dict[str, list[Any]]:
        """Ce qui reste troué dans un clair rattaché, à retenir hors du
        magasin : une clé opaque au moteur → ce que :meth:`combler` remet."""
        return {}

    def combler(
        self, clair: dict[str, Any], trous: dict[str, list[Any]]
    ) -> dict[str, Any]:
        """Remet les trous dans un clair attaché lu du magasin."""
        return clair

    def fermer(self) -> None:
        """Libère ce que la collection a ouvert pour ses lectures."""
