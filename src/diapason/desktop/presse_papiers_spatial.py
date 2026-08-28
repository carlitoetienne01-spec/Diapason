"""Ce qu'on tient dans la main — le presse-papiers spatial (§17, §22).

Spatial Mesh, gestes, phase 5 — 25 août 2026. Le geste exprime une
INTENTION ; il ne transporte rien. Fermer le poing ne déplace aucun octet :
il désigne ce que l'écran affiche à cet instant — ou le fichier explicitement
préparé dans le dialogue natif — et le retient, le temps d'un geste. Ouvrir
la main dit où le déposer.

Le §2 du cahier des charges le dit mieux que moi : ne jamais confondre
l'effet visuel et l'architecture. Ici, le presse-papiers est la seule
mémoire du geste, et elle est volatile, minuscule, et honnête — elle ne
contient jamais les octets d'un fichier, seulement son chemin local vérifié,
que le transfert relira par morceaux après le choix de l'appareil.
"""

from __future__ import annotations

import logging
import mimetypes
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Un objet attrapé et jamais déposé n'a pas à hanter la session : on le
# tient le temps d'un geste, pas le temps d'une journée.
TTL_S = 120.0
# Un fichier choisi puis jamais attrapé ne doit pas rester désigné toute la
# journée. Dix minutes laissent le temps d'ouvrir le mode et de se placer,
# sans transformer un chemin local en état persistant caché.
PREPARATION_TTL_S = 600.0


@dataclass(frozen=True, slots=True)
class ObjetSpatial:
    """Ce qui a été attrapé — une IDENTITÉ, jamais une copie (§19).

    Une tâche n'est pas sérialisée puis renvoyée : on transporte son type
    et son identifiant, et l'appareil d'arrivée va chercher la ressource
    par ses propres moyens. C'est ce qui distingue un handoff d'une
    duplication.
    """

    type: str  # "project" | "note" | "task" | "screen" | "file"
    id: str
    titre: str
    ecran: str = ""
    quand: float = 0.0
    # Le chemin ne passe JAMAIS sur le fil ni dans le contexte du modèle. Il
    # reste dans ce processus, uniquement pour que l'émetteur puisse relire
    # le fichier par morceaux une fois la cible choisie.
    chemin: str = ""
    taille: int = 0
    type_mime: str = ""

    @property
    def frais(self) -> bool:
        return (time.monotonic() - self.quand) < TTL_S

    def to_dict(self) -> dict:
        public = {
            "type": self.type,
            "id": self.id,
            "title": self.titre,
            "screen": self.ecran,
        }
        if self.type == "file":
            public.update(
                {
                    "sizeBytes": self.taille,
                    "mimeType": self.type_mime,
                }
            )
        return public


_tenu: Optional[ObjetSpatial] = None
_prepare: Optional[ObjetSpatial] = None


def preparer_fichier(chemin: Path | str) -> ObjetSpatial:
    """Désigner UN fichier local que le prochain poing pourra attraper.

    Le choix vient du dialogue natif de l'application. On vérifie tout de
    même ici : une chaîne reçue par HTTP n'est jamais une preuve qu'un fichier
    existe, qu'il est régulier, ni qu'il respecte le plafond du transfert.
    """
    global _prepare

    from diapason.mesh.transfert import TAILLE_MAX_DEFAUT

    try:
        resolu = Path(chemin).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Ce fichier n'existe plus.") from exc
    if not resolu.is_file():
        raise ValueError("Choisis un fichier, pas un dossier.")
    taille = resolu.stat().st_size
    if taille > TAILLE_MAX_DEFAUT:
        raise ValueError("Ce fichier dépasse la limite de 2 Gio.")
    _prepare = ObjetSpatial(
        type="file",
        # Un jeton opaque, jamais le chemin. L'interface a besoin d'une clé
        # stable pour son rendu, pas de savoir où vit le fichier.
        id=f"file_{secrets.token_urlsafe(9)}",
        titre=resolu.name,
        quand=time.monotonic(),
        chemin=str(resolu),
        taille=taille,
        type_mime=mimetypes.guess_type(resolu.name)[0] or "",
    )
    return _prepare


def fichier_prepare() -> Optional[ObjetSpatial]:
    """Le fichier prêt à être attrapé, s'il n'a pas été oublié."""
    global _prepare
    if _prepare is None:
        return None
    if (time.monotonic() - _prepare.quand) >= PREPARATION_TTL_S:
        _prepare = None
        return None
    # Le fichier peut disparaître entre le dialogue et le geste. Le garder
    # affiché « prêt » dans ce cas serait une promesse déjà fausse.
    if not Path(_prepare.chemin).is_file():
        _prepare = None
        return None
    return _prepare


def oublier_fichier_prepare() -> None:
    global _prepare
    _prepare = None


def attraper() -> Optional[ObjetSpatial]:
    """Prendre ce que l'écran affiche à cet instant — ou rien.

    Rien n'est deviné : sans contexte d'application frais, la main se
    referme sur du vide, et le dire vaut mieux qu'attraper au hasard un
    objet que l'utilisateur ne regardait pas.
    """
    global _prepare, _tenu
    prepare = fichier_prepare()
    if prepare is not None:
        _tenu = ObjetSpatial(
            type=prepare.type,
            id=prepare.id,
            titre=prepare.titre,
            quand=time.monotonic(),
            chemin=prepare.chemin,
            taille=prepare.taille,
            type_mime=prepare.type_mime,
        )
        _prepare = None
        logger.info("attrapé : fichier « %s » (%d octets)", _tenu.titre, _tenu.taille)
        return _tenu
    from diapason.desktop.contexte_app import dernier_contexte

    vue = dernier_contexte()
    if vue is None:
        _tenu = None
        return None
    if vue.ressource_id and vue.ressource_type:
        _tenu = ObjetSpatial(
            type=vue.ressource_type,
            id=vue.ressource_id,
            titre=vue.ressource_titre or vue.ressource_id,
            ecran=vue.ecran,
            quand=time.monotonic(),
        )
    else:
        # Aucun élément sélectionné : c'est l'ÉCRAN qu'on attrape. « Reprends
        # ça là-bas » a un sens même sans élément précis.
        _tenu = ObjetSpatial(
            type="screen",
            id=vue.chemin,
            titre=vue.ecran,
            ecran=vue.ecran,
            quand=time.monotonic(),
        )
    logger.info("attrapé : %s « %s »", _tenu.type, _tenu.titre)
    return _tenu


def tenu() -> Optional[ObjetSpatial]:
    """Ce qui est tenu, s'il est encore frais."""
    if _tenu is not None and _tenu.frais:
        return _tenu
    return None


def lacher() -> Optional[ObjetSpatial]:
    """Rendre ce qui était tenu, et ouvrir la main."""
    global _tenu
    objet, _tenu = tenu(), None
    return objet


def vider() -> None:
    global _prepare, _tenu
    _tenu = None
    _prepare = None


def decrire(objet: ObjetSpatial) -> str:
    """Ce qui est dans la main, en une phrase, pour le contexte du modèle.

    Miroir strict de ``contexte_app.decrire`` : même préfixe court, mêmes
    guillemets, une seule phrase, aucun impératif. Le contexte ÉNONCE un
    fait ; l'instruction, elle, vit dans la description de l'outil.

    Le « (geste) » n'est pas décoratif. Ces deux phrases se suivent souvent
    dans le même contexte, et « Dans la main » et « Dans Diapason » se
    ressemblent assez pour que le modèle envoie l'un en croyant l'autre —
    c'est exactement le défaut que ce raccordement existe pour corriger.
    """
    if objet.type == "screen":
        return f"Dans la main (geste) : l'écran {objet.titre}."
    if objet.type == "file":
        return f"Dans la main (geste) : le fichier « {objet.titre} »."
    quoi = {
        "project": "le projet",
        "note": "la note",
        "task": "la tâche",
    }.get(objet.type, "l'élément")
    return f"Dans la main (geste) : {quoi} « {objet.titre} »."


__all__ = [
    "ObjetSpatial",
    "PREPARATION_TTL_S",
    "TTL_S",
    "attraper",
    "decrire",
    "fichier_prepare",
    "lacher",
    "oublier_fichier_prepare",
    "preparer_fichier",
    "tenu",
    "vider",
]
