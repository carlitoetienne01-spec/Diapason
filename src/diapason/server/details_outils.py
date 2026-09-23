"""Ce qu'une carte d'outil doit pouvoir dire, chat et voix (22/09/2026).

`web_search` sait depuis le 20/09 quel moteur a répondu — `engine` vaut
« brave/news », le moteur ET son vertical — et combien de résultats il a
rendus. Rien ne le faisait traverser : la carte affichait « web_search ·
0,8 s », le terminal une ligne `OK` verte. Une recherche VIDE se lisait
donc exactement comme une qui en rend huit, et la réponse bâtie sur ce vide
ne s'annonçait pas (§5).

Une recherche vide n'a PAS de moteur : `_ddgs_search` ne retient un plan
que s'il a rendu quelque chose (`if not resultats: continue`, web_search.py
:427), donc `numResults == 0` implique `plans == []` implique `engine ==
""`. La ligne d'une recherche vide se lit « web_search · 0 rés. », jamais
« web_search · brave/news · 0 rés. » — cette dernière est une chaîne que le
système ne peut pas produire, et l'avoir écrite en exemple dans le premier
commit était une fiction.

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
        meta, reussi = resultat.get("metadata"), bool(resultat.get("ok"))
    else:
        meta = getattr(resultat, "metadata", None)
        reussi = bool(getattr(resultat, "success", False))
    # Un outil qui a ÉCHOUÉ n'a pas de compte : il a une panne. Quand aucun
    # moteur n'est joignable, `web_search` rend success=False avec
    # `{"engine": "", "numResults": 0}` (web_search.py:640) — sans cette
    # garde, la ligne du terminal écrivait « FAIL web_search · 0 rés. », le
    # zéro peint comme un vide, c'est-à-dire « cherché, rien trouvé » pour un
    # tour où RIEN n'a été cherché. Le dépôt a déjà tranché cette distinction
    # dans web_search.py : « Zéro moteur joint, c'est une panne ; des moteurs
    # qui répondent vide, c'est un vide. » (22/09/2026, revue du soir.)
    if not reussi or not isinstance(meta, dict):
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
