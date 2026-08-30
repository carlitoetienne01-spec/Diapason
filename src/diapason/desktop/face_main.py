"""Paume face à la caméra, ou dos de la main — sans toucher à l'OS.

Le retournement (paume → dos) change d'application. Vision ne donne pas
de normale 3D fiable ici : on lit le sens de parcours poignet → index →
auriculaire, croisé avec la latéralité (main gauche / droite).
"""

from __future__ import annotations

from typing import Optional, Sequence

from diapason.desktop.gestes_main import Point


def face_paume_vers_camera(
    points: Sequence[Point],
    lateralite: str,
) -> Optional[bool]:
    """True = paume vers la caméra, False = dos, None = indécidable.

    Pour une main DROITE paume vers soi, les bases index→auriculaire tournent
    dans le sens inverse des aiguilles (après notre retournement de y). Une
    main GAUCHE inverse le signe. Sans latéralité connue, on refuse plutôt
    que de deviner (§34).
    """
    if lateralite not in ("left", "right"):
        return None
    par_nom = {p.nom: p for p in points}
    poignet = par_nom.get("wrist")
    index = par_nom.get("indexMCP")
    auriculaire = par_nom.get("littleMCP")
    if poignet is None or index is None or auriculaire is None:
        return None
    if min(poignet.confiance, index.confiance, auriculaire.confiance) < 0.25:
        return None
    # Produit vectoriel 2D : signe = sens de parcours dans le plan image.
    vx1 = index.x - poignet.x
    vy1 = index.y - poignet.y
    vx2 = auriculaire.x - poignet.x
    vy2 = auriculaire.y - poignet.y
    croix = vx1 * vy2 - vy1 * vx2
    if abs(croix) < 1e-5:
        return None
    # Convention calée sur une géométrie de test (main droite, paume face
    # caméra, doigts vers le haut de l'écran) : croix > 0. La main gauche
    # inverse.
    if lateralite == "right":
        return croix > 0.0
    return croix < 0.0


__all__ = ["face_paume_vers_camera"]
