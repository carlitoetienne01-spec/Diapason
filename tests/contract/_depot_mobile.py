"""Où vit le dépôt ``diapason_mobile`` pour les tests de contrat qui en
lisent les fichiers communs (fixtures, vecteurs, sources Dart).

26/09/2026, contre-épreuve : cinq fichiers écrivaient chacun
``Path.home() / "Projets/diapason_mobile"``. Une passe lancée avec un
``HOME`` de banc (le foyer jetable d'un serveur de test) rendait 25 échecs
et 2 erreurs sans rapport avec le code ; et l'on ne pouvait pas désigner
une copie propre du dépôt — un ``git archive`` d'un commit donné — quand
l'arbre vivant porte le chantier non commité d'une autre session.

``DIAPASON_MOBILE`` désigne le dépôt ; sans elle, l'emplacement habituel.
"""

from __future__ import annotations

import os
import pathlib

VARIABLE = "DIAPASON_MOBILE"


def depot_mobile() -> pathlib.Path:
    brut = os.environ.get(VARIABLE, "").strip()
    if brut:
        return pathlib.Path(brut).expanduser()
    return pathlib.Path.home() / "Projets/diapason_mobile"
