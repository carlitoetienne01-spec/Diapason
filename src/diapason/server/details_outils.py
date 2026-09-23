"""Ce qu'une carte d'outil doit pouvoir dire, chat et voix (22/09/2026).

`web_search` sait depuis le 20/09 quel moteur a répondu — `engine` vaut
« brave/news », le moteur ET son vertical — et combien de résultats il a
rendus. Rien ne le faisait traverser : la carte affichait « web_search ·
0,8 s », le terminal une ligne `OK` verte. Une recherche VIDE se lisait
donc exactement comme une qui en rend huit, et la réponse bâtie sur ce vide
ne s'annonçait pas (§5).

Le calcul vit ICI, une seule fois, parce que ses deux pièges le méritent :
`0` doit passer — c'est même le cas pour lequel tout ceci existe — et
`isinstance(True, int)` est vrai en Python, donc un drapeau deviendrait
« 1 rés. ». Deux copies de ces deux règles finiraient par diverger, et
c'est celle qu'on oublierait qui mentirait.

Les deux chemins ne portent pas leur résultat de la même façon : le chat
manipule un `ToolResult` (attribut `.metadata`), la boucle vocale des dicts
(`{"ok", "content", "metadata"}`). Les deux entrent ici.
"""

from __future__ import annotations

from typing import Any


def details_du_fil(resultat: Any) -> dict[str, Any]:
    """Le moteur et le nombre de résultats, ou {} quand ça ne s'applique pas.

    Les clés sont recopiées telles quelles : elles sont déjà en anglais
    camelCase dans la métadonnée, donc sur le fil aussi (CLAUDE.md). Le
    modèle, lui, n'a pas à lire ça — il lit déjà le texte numéroté.
    """
    if isinstance(resultat, dict):
        meta = resultat.get("metadata")
    else:
        meta = getattr(resultat, "metadata", None)
    if not isinstance(meta, dict):
        return {}
    details: dict[str, Any] = {}
    moteur = meta.get("engine")
    if isinstance(moteur, str) and moteur:
        details["engine"] = moteur
    nombre = meta.get("numResults")
    # `0` compte ; un booléen n'est pas un compte.
    if isinstance(nombre, int) and not isinstance(nombre, bool):
        details["numResults"] = nombre
    return details


__all__ = ["details_du_fil"]
