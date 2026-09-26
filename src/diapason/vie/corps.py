"""Les corps de requête que PLUSIEURS modules de routes se partagent.

Un seul pour l'instant, et il est ici pour une raison précise.

``routes.py`` définit ses modèles au niveau du module, et ``finances_routes.py``
aussi — mais ce dernier déclare ses routes DANS une fonction,
``register_finances_routes()``, à laquelle ``DeleteBody`` arrivait en
paramètre. Or le fichier porte ``from __future__ import annotations`` : toute
annotation devient une chaîne, et FastAPI résout ``"DeleteBody"`` contre les
globales du MODULE où la fonction est définie — jamais contre ses variables
locales. Le nom n'y était pas.

Conséquence, constatée le 26 août 2026 : ``GET /openapi.json`` rendait **500**
sur tout le dépôt, et la documentation d'API était donc cassée sans que
personne ne s'en aperçoive, parce que rien ne la demandait. Les six routes
``delete_*`` des Finances suffisaient à emporter le schéma entier.

Un module partagé plutôt qu'une classe dupliquée dans chaque fichier : deux
classes de même nom produiraient deux schémas OpenAPI, ``DeleteBody`` et
``DeleteBody-Input``, pour une seule et même forme. Et plutôt qu'un import
croisé entre ``routes.py`` et ``finances_routes.py``, qui ne tiendrait que
tant que personne n'importe le second en premier.
"""

from __future__ import annotations

from pydantic import BaseModel


class DeleteBody(BaseModel):
    """Confirmer une suppression, et savoir qui l'a demandée.

    ``confirmed`` vaut False par défaut : une suppression ne s'obtient pas en
    oubliant un champ.
    """

    confirmed: bool = False
    opId: str | None = None


__all__ = ["DeleteBody"]
