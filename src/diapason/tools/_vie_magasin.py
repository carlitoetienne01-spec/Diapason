"""Le magasin des outils vie, construit au premier usage.

25/09/2026 : les outils construisaient leur magasin dans ``__init__``. La
trousse du chat les instancie tous d'un coup, dans un seul ``try`` : une
base de vie illisible — ou deux bases pleines (``DeuxBasesVie``) — faisait
tomber la trousse ENTIÈRE, et le chat répondait sans aucun outil, pas même
la météo, avec une seule ligne WARNING pour le dire. Construit au premier
appel, le magasin ne peut plus coûter que l'outil qui s'en sert, et l'erreur
remonte en résultat d'outil que le modèle lit et répète.
"""

from __future__ import annotations

from typing import Any, Callable


class MagasinParesseux:
    """Fournit ``self._store`` ; la sous-classe pose ``_magasin`` et ``_fabrique``."""

    _magasin: Any
    _fabrique: Callable[[], Any]

    @property
    def _store(self) -> Any:
        if self._magasin is None:
            self._magasin = self._fabrique()
        return self._magasin
