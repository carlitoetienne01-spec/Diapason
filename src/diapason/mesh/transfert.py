"""Le transfert de fichiers entre appareils : le cœur, sans réseau.

Spatial Mesh, phase 3 — 25 août 2026. Le maillage était un maillage de
COMMANDES : des enveloppes sans état, courtes, qui expirent. Un fichier ne
rentre pas là-dedans, et le cahier des charges l'interdit explicitement —
ajouter un champ à l'enveloppe signée invaliderait toutes les signatures du
client mobile. Le transfert a donc sa propre session, son propre cycle de
vie, ses propres routes.

Ce module ne parle à personne : il décrit un transfert, découpe, vérifie,
assainit, et recoud. Tout ce qui touche au réseau ou au disque est injecté
ou vit ailleurs, pour que la logique se teste sans machine en face.

Trois règles qui viennent de vraies erreurs :

1. **Jamais tout en mémoire.** Un fichier d'un gigaoctet lu d'un bloc, c'est
   un gigaoctet de RAM sur une machine qui fait tourner un modèle de langue.
2. **Le nom reçu est une donnée hostile**, pas un chemin. « ../../.ssh/
   authorized_keys » est un nom de fichier parfaitement valide côté
   émetteur.
3. **Rien n'est visible avant d'être entier.** Un fichier partiel qui porte
   déjà son nom final sera ouvert par quelqu'un, un jour, au milieu d'un
   transfert.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Un mégaoctet : assez grand pour que la reprise ne recommence pas trop, assez
# petit pour tenir en mémoire sans y penser, et pour qu'une barre de
# progression avance visiblement.
TAILLE_MORCEAU = 1024 * 1024

# Au-delà, on refuse AVANT de commencer plutôt que de remplir le disque puis
# de s'excuser. Le réglage est dans la config ; ceci est le garde-fou dur.
TAILLE_MAX_DEFAUT = 2 * 1024 * 1024 * 1024  # 2 Gio

_NOM_MAX = 120

# Ce qui ne doit jamais arriver dans un nom de fichier reçu. Le point de
# départ est une liste de refus, pas une liste d'autorisations : un nom qui
# ne survit pas au nettoyage devient « fichier », il n'est jamais deviné.
_INTERDITS = re.compile(r'[/\\\x00-\x1f\x7f:*?"<>|]')
_POINTS_EN_TETE = re.compile(r"^\.+")


def assainir_nom(brut: str) -> str:
    """Un nom de fichier sûr, dérivé d'un nom reçu qu'on suppose hostile.

    « ../../.ssh/authorized_keys » est un nom parfaitement valide pour
    l'émetteur : c'est au récepteur de refuser d'y croire.
    """
    nom = "".join(
        caractere
        for caractere in unicodedata.normalize("NFC", str(brut or ""))
        # Les contrôles bidi et caractères invisibles ne sont pas des
        # séparateurs, donc la regex historique les laissait traverser. Un
        # `rapport\u202egnp.exe` pouvait alors se présenter visuellement comme
        # une image tandis que le disque conservait un exécutable.
        if unicodedata.category(caractere) != "Cf"
    ).strip()
    # Le séparateur d'abord : on ne garde que le dernier segment, quelle que
    # soit la convention de l'émetteur.
    nom = nom.replace("\\", "/").split("/")[-1]
    nom = _INTERDITS.sub("_", nom)
    # Un nom qui commence par un point se cache ; un nom qui n'est QUE des
    # points remonte l'arborescence.
    nom = _POINTS_EN_TETE.sub("", nom).strip(" .")
    if not nom:
        return "fichier"
    if len(nom) > _NOM_MAX:
        tige, point, extension = nom.rpartition(".")
        if point and 0 < len(extension) <= 10:
            garde = _NOM_MAX - len(extension) - 1
            nom = f"{tige[:garde]}.{extension}"
        else:
            nom = nom[:_NOM_MAX]
    return nom


def nom_libre(dossier: Path, nom: str) -> Path:
    """Un chemin qui n'écrase rien : « photo.jpg », puis « photo (2).jpg ».

    Écraser un fichier existant serait une perte de données décidée par
    quelqu'un d'autre que son propriétaire.
    """
    cible = dossier / nom
    if not cible.exists():
        return cible
    tige, point, extension = nom.rpartition(".")
    if not point:
        tige, extension = nom, ""
    for i in range(2, 1000):
        candidat = f"{tige} ({i}){'.' + extension if extension else ''}"
        cible = dossier / candidat
        if not cible.exists():
            return cible
    raise ValueError("Trop de fichiers portent déjà ce nom.")


@dataclass(frozen=True, slots=True)
class Manifeste:
    """Ce qu'on annonce AVANT d'envoyer un octet.

    Le récepteur décide sur cette annonce seule : trop gros, nom refusé,
    déjà présent. Refuser après coup, c'est avoir déjà payé le transfert.
    """

    nom: str
    taille: int
    hachage: str  # sha256 du fichier entier, en hexadécimal
    type_mime: str = ""
    morceaux: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.nom,
            "size": self.taille,
            "sha256": self.hachage,
            "mimeType": self.type_mime,
            "chunks": self.morceaux,
        }

    @classmethod
    def from_dict(cls, brut: dict) -> "Manifeste":
        # Les tailles sont des ENTIERS, toujours : un flottant dans une
        # charge signée s'écrit « 1e-07 » d'un côté et « 1e-7 » de l'autre.
        return cls(
            nom=str(brut.get("name") or ""),
            taille=int(brut.get("size") or 0),
            hachage=str(brut.get("sha256") or ""),
            type_mime=str(brut.get("mimeType") or ""),
            morceaux=int(brut.get("chunks") or 0),
        )


def nombre_de_morceaux(taille: int, taille_morceau: int = TAILLE_MORCEAU) -> int:
    if taille <= 0:
        return 0
    return (taille + taille_morceau - 1) // taille_morceau


def decrire_fichier(chemin: Path, *, taille_morceau: int = TAILLE_MORCEAU) -> Manifeste:
    """Le manifeste d'un fichier local — lu par blocs, jamais d'un coup."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ValueError(f"{chemin} n'est pas un fichier.")
    taille = chemin.stat().st_size
    sha = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(taille_morceau), b""):
            sha.update(bloc)
    import mimetypes

    return Manifeste(
        nom=assainir_nom(chemin.name),
        taille=taille,
        hachage=sha.hexdigest(),
        type_mime=mimetypes.guess_type(chemin.name)[0] or "",
        morceaux=nombre_de_morceaux(taille, taille_morceau),
    )


def lire_morceaux(
    chemin: Path, *, taille_morceau: int = TAILLE_MORCEAU
) -> Iterator[tuple[int, bytes]]:
    """(index, octets) — un fichier ne passe jamais entièrement en mémoire."""
    with open(chemin, "rb") as f:
        index = 0
        while True:
            bloc = f.read(taille_morceau)
            if not bloc:
                return
            yield index, bloc
            index += 1


class RefusDeTransfert(ValueError):
    """Le transfert est refusé, et le message dit pourquoi à un humain."""


def verifier_le_manifeste(
    manifeste: Manifeste, *, taille_max: int = TAILLE_MAX_DEFAUT
) -> None:
    """Tout ce qu'on peut refuser AVANT le premier octet."""
    if manifeste.taille < 0:
        raise RefusDeTransfert("Taille de fichier absurde.")
    if manifeste.taille > taille_max:
        gio = taille_max / (1024**3)
        raise RefusDeTransfert(f"Ce fichier dépasse la limite de {gio:.1f} Gio.")
    if len(manifeste.hachage) != 64 or not re.fullmatch(
        r"[0-9a-f]{64}", manifeste.hachage
    ):
        raise RefusDeTransfert("Empreinte de fichier illisible.")
    if manifeste.morceaux != nombre_de_morceaux(manifeste.taille):
        raise RefusDeTransfert("Le découpage annoncé ne correspond pas à la taille.")


@dataclass
class Reception:
    """Un transfert en cours de réception, repris là où il s'était arrêté.

    Les morceaux vont dans un fichier « .partiel » qui ne porte PAS le nom
    final : rien n'est visible avant d'être entier et vérifié.
    """

    manifeste: Manifeste
    dossier: Path
    partiel: Path
    recus: set[int] = field(default_factory=set)
    taille_morceau: int = TAILLE_MORCEAU

    @property
    def complet(self) -> bool:
        return len(self.recus) >= self.manifeste.morceaux

    @property
    def manquants(self) -> list[int]:
        """Ce que l'émetteur doit (re)envoyer — la reprise tient là-dedans."""
        return [i for i in range(self.manifeste.morceaux) if i not in self.recus]

    def ecrire(self, index: int, octets: bytes) -> None:
        """Poser un morceau à sa place. Rejouer le même morceau est inoffensif."""
        if index < 0 or index >= self.manifeste.morceaux:
            raise RefusDeTransfert(f"Morceau {index} hors du fichier annoncé.")
        attendu = self.taille_morceau
        dernier = index == self.manifeste.morceaux - 1
        if not dernier and len(octets) != attendu:
            raise RefusDeTransfert(
                f"Morceau {index} de taille inattendue ({len(octets)})."
            )
        if dernier:
            reste = self.manifeste.taille - index * attendu
            if len(octets) != reste:
                raise RefusDeTransfert("Dernier morceau de taille inattendue.")
        self.partiel.parent.mkdir(parents=True, exist_ok=True)
        # Ouverture en r+b pour écrire à la position exacte : les morceaux
        # peuvent arriver dans le désordre après une reprise.
        mode = "r+b" if self.partiel.exists() else "wb"
        with open(self.partiel, mode) as f:
            f.seek(index * attendu)
            f.write(octets)
        self.recus.add(index)

    def finaliser(self) -> Path:
        """Vérifier l'intégrité, puis rendre le fichier visible d'un seul coup.

        L'empreinte est recalculée sur ce qui est RÉELLEMENT sur le disque :
        faire confiance au compte des morceaux reviendrait à croire
        l'émetteur sur parole.
        """
        if not self.complet:
            raise RefusDeTransfert(
                f"Transfert incomplet : {len(self.manquants)} morceau(x) manquant(s)."
            )
        taille_reelle = self.partiel.stat().st_size
        if taille_reelle != self.manifeste.taille:
            raise RefusDeTransfert(
                f"Taille finale {taille_reelle}, annoncée {self.manifeste.taille}."
            )
        sha = hashlib.sha256()
        with open(self.partiel, "rb") as f:
            for bloc in iter(lambda: f.read(TAILLE_MORCEAU), b""):
                sha.update(bloc)
        if sha.hexdigest() != self.manifeste.hachage:
            self.partiel.unlink(missing_ok=True)
            raise RefusDeTransfert(
                "Le fichier reçu ne correspond pas à son empreinte — "
                "transfert abandonné."
            )
        cible = nom_libre(self.dossier, assainir_nom(self.manifeste.nom))
        # Jamais exécutable : un fichier reçu du réseau ne s'exécute pas, et
        # ne doit même pas pouvoir le prétendre.
        os.chmod(self.partiel, 0o600)
        os.replace(self.partiel, cible)  # atomique sur le même système
        return cible

    def abandonner(self) -> None:
        self.partiel.unlink(missing_ok=True)
        self.recus.clear()


def ouvrir_reception(
    manifeste: Manifeste,
    dossier: Path,
    *,
    session_id: str,
    taille_max: int = TAILLE_MAX_DEFAUT,
    taille_morceau: int = TAILLE_MORCEAU,
) -> Reception:
    """Préparer la réception d'un fichier annoncé — refus avant tout octet."""
    verifier_le_manifeste(manifeste, taille_max=taille_max)
    dossier = Path(dossier)
    dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Le fichier partiel porte l'identifiant de session, pas le nom annoncé :
    # deux transferts du même nom ne se marchent pas dessus, et rien ne
    # ressemble au fichier final avant qu'il ne le soit.
    partiel = dossier / f".{session_id}.partiel"
    return Reception(
        manifeste=manifeste,
        dossier=dossier,
        partiel=partiel,
        taille_morceau=taille_morceau,
    )


def deja_present(
    manifeste: Manifeste, dossier: Path, *, taille_morceau: int = TAILLE_MORCEAU
) -> Optional[Path]:
    """Le fichier est-il déjà là, au même contenu ? (§45, déduplication.)

    Compare les empreintes, jamais les noms : deux fichiers de même nom
    peuvent différer, et deux noms différents porter le même contenu.
    """
    dossier = Path(dossier)
    if not dossier.is_dir():
        return None
    for candidat in dossier.iterdir():
        if not candidat.is_file() or candidat.name.startswith("."):
            continue
        if candidat.stat().st_size != manifeste.taille:
            continue  # la taille écarte l'essentiel sans rien lire
        sha = hashlib.sha256()
        with open(candidat, "rb") as f:
            for bloc in iter(lambda: f.read(taille_morceau), b""):
                sha.update(bloc)
        if sha.hexdigest() == manifeste.hachage:
            return candidat
    return None


__all__ = [
    "Manifeste",
    "Reception",
    "RefusDeTransfert",
    "TAILLE_MAX_DEFAUT",
    "TAILLE_MORCEAU",
    "assainir_nom",
    "deja_present",
    "decrire_fichier",
    "lire_morceaux",
    "nom_libre",
    "nombre_de_morceaux",
    "ouvrir_reception",
    "verifier_le_manifeste",
]
