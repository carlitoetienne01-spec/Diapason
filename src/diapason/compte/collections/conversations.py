"""La collection ``conversations`` : le magasin du chat, vu par le moteur.

Conception : ``docs/development/compte-chiffre.md`` §4.7, §4.6 et §2.5.

Le moteur est un SECOND client de ``ConversationsStore`` (§4.1), à côté des
deux vues. Il écrit par les mêmes portes qu'elles — ``upsert`` pour une
copie vivante, ``appliquer_tombale`` pour une suppression venue d'ailleurs —
et la règle de fusion ne change donc pas : ``fusionner_conversations`` est
une jointure, et pousser toujours la jointure de ce qu'on a et de ce qu'on a
vu fait converger les appareils.

La projection (:func:`projeter`) retire ``messages[].audio`` : son URL
désigne la machine elle-même (``InputArea.tsx``), et elle ne dirait rien
ailleurs. L'empreinte se calcule sur la projection ; sans cela, l'appareil
qui porte l'audio verrait toujours sa copie différer de celle du serveur, et
repousserait la même conversation à chaque cycle.

Les lectures par identifiant passent par une connexion SQLite en LECTURE
SEULE, à part : le magasin n'expose que ``list``, qui décode toutes les
conversations, et une poussée relit chaque objet au moment de le sceller.

**Pièces (étape 11, §4.7).** Chaque chaîne ``data:`` de ``messages[].images``
devient une pièce (``compte/pieces.py``). Un message dont une pièce manque
est « troué » : dans le clair, il garde toutes ses références ; dans le
magasin, il n'a plus de champ ``images`` du tout. Tout ou rien par message,
et le CHAMP retiré plutôt que la liste vidée, pour une raison de fusion :
``_meilleur_message`` départage deux versions d'un même message par la
longueur du contenu, puis par le NOMBRE de champs, puis par l'ordre des
arguments. Une liste d'images raccourcie aurait laissé la version trouée
gagner contre la version complète, à égalité de champs, dès qu'elle était
la copie stockée — l'image ne revenait jamais. Sans le champ, la version
complète a un champ de plus et gagne quel que soit l'ordre.

Une référence n'entre jamais dans le magasin : la vue l'afficherait comme
une image cassée, et ``pieces_jointes.normaliser`` refuserait toute la
requête du chat au premier message qui la porte.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from diapason.compte.collections.base import Changement, Collection
from diapason.compte.enveloppe import (
    SCHEMA_CONVERSATIONS,
    ClairInvalide,
    clair_objet,
    clair_tombale,
)
from diapason.compte.pieces import (
    PieceIllisible,
    deballer,
    detachable,
    emballer,
    identifiant_de,
    reference,
)
from diapason.server.conversations_store import cle_message

__all__ = ["CollectionConversations", "projeter"]

NOM = "conversations"

# La plus grande date qu'un entier SQLite porte (int64) : le magasin refuse
# au-delà, et une date plus grande venue d'un clair ferait lever
# ``OverflowError`` au milieu d'une écriture (conversations_store.py).
_ENTIER_MAX = 2**63 - 1


def _message_projete(message: Any) -> Any:
    if isinstance(message, dict) and "audio" in message:
        return {cle: valeur for cle, valeur in message.items() if cle != "audio"}
    return message


def projeter(conversation: dict[str, Any]) -> dict[str, Any]:
    """Le ``data`` d'un clair de conversation : la copie locale sans ce qui
    n'a de sens que sur cette machine. ``id`` n'y est pas — il est dans le
    clair, à côté de ``collection``."""
    return {
        "title": conversation["title"],
        "createdAt": int(conversation["createdAt"]),
        "updatedAt": int(conversation["updatedAt"]),
        "model": conversation["model"],
        "pinned": bool(conversation.get("pinned")),
        "messages": [_message_projete(m) for m in conversation.get("messages", [])],
    }


def _entier(valeur: Any, nom: str) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise ClairInvalide(f"{nom} n'est pas un entier")
    if not 0 <= valeur <= _ENTIER_MAX:
        raise ClairInvalide(f"{nom} hors de [0, 2^63 - 1]")
    return valeur


def _conversation_de(clair: dict[str, Any]) -> dict[str, Any]:
    """Vérifie la FORME d'un ``data`` venu du serveur avant de l'écrire.

    Le clair a été authentifié (AAD), mais par une DEK qu'un appareil perdu
    peut encore détenir (§2.11 bis) : un titre qui ne serait pas une chaîne
    ferait lever le magasin au milieu d'une transaction.
    """
    data = clair.get("data")
    if not isinstance(data, dict):
        raise ClairInvalide("data n'est pas un objet")
    titre, modele = data.get("title"), data.get("model")
    if not isinstance(titre, str) or not isinstance(modele, str):
        raise ClairInvalide("title ou model n'est pas une chaîne")
    messages = data.get("messages")
    if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
        raise ClairInvalide("messages n'est pas une liste d'objets")
    epingle = data.get("pinned", False)
    if not isinstance(epingle, bool):
        raise ClairInvalide("pinned n'est pas un booléen")
    return {
        "id": clair["id"],
        "title": titre,
        "createdAt": _entier(data.get("createdAt"), "createdAt"),
        "updatedAt": _entier(data.get("updatedAt"), "updatedAt"),
        "model": modele,
        "pinned": epingle,
        "messages": [_sans_trou(m) for m in messages],
    }


def _images(message: Any) -> list[Any] | None:
    if not isinstance(message, dict):
        return None
    images = message.get("images")
    return images if isinstance(images, list) else None


def _troue(message: Any) -> bool:
    """Un message dont les images portent encore une référence."""
    images = _images(message)
    return images is not None and any(identifiant_de(v) for v in images)


def _sans_trou(message: dict[str, Any]) -> dict[str, Any]:
    """Le message tel qu'il entre dans le magasin : sans ``images`` s'il est
    troué (voir la docstring du module)."""
    if not _troue(message):
        return message
    return {cle: valeur for cle, valeur in message.items() if cle != "images"}


def _avec_messages(clair: dict[str, Any], messages: list[Any]) -> dict[str, Any]:
    return {**clair, "data": {**clair["data"], "messages": messages}}


def _messages(clair: dict[str, Any]) -> list[Any] | None:
    data = clair.get("data")
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    return messages if isinstance(messages, list) else None


class CollectionConversations(Collection):
    nom = NOM
    schema = SCHEMA_CONVERSATIONS

    def __init__(self, magasin: Any) -> None:
        chemin = getattr(magasin, "chemin", "")
        # Un magasin en mémoire n'a pas de fichier à rouvrir en lecture : le
        # moteur ne saurait pas relire ce qu'il pousse. Refusé ici plutôt
        # qu'à la première poussée.
        if not isinstance(chemin, str) or not chemin or chemin == ":memory:":
            raise ValueError("la synchronisation exige un magasin sur disque")
        self._magasin = magasin
        self._chemin = chemin
        self._verrou = threading.Lock()
        self._lecture: sqlite3.Connection | None = None

    # --- Lecture seule --------------------------------------------------

    def _connexion(self) -> sqlite3.Connection:
        if self._lecture is None:
            uri = Path(self._chemin).resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5.0)
            conn.row_factory = sqlite3.Row
            self._lecture = conn
        return self._lecture

    def fermer(self) -> None:
        with self._verrou:
            if self._lecture is not None:
                self._lecture.close()
                self._lecture = None

    # --- L'interface du §4.8 --------------------------------------------

    def changements_depuis(self, seq: int) -> tuple[list[Changement], int]:
        vivantes, tombales, nouveau = self._magasin.list(since=seq)
        changements = [
            Changement(c["id"], clair_objet(NOM, c["id"], projeter(c)))
            for c in vivantes
            # Une conversation vierge n'est pas une conversation : la liste
            # du bundle la saute (``discussions.ts:57``), et la pousser ferait
            # apparaître des fils vides sur les autres appareils.
            if c.get("messages")
        ]
        changements.extend(
            Changement(
                t["id"],
                clair_tombale(NOM, t["id"], int(t["deletedAt"])),
                supprime_le_ms=int(t["deletedAt"]),
            )
            for t in tombales
        )
        return changements, int(nouveau)

    def clair_local(self, id_local: str) -> dict[str, Any] | None:
        with self._verrou:
            ligne = (
                self._connexion()
                .execute("SELECT * FROM conversations WHERE id = ?", (id_local,))
                .fetchone()
            )
        if ligne is None:
            return None
        if ligne["deleted_at"] is not None:
            return clair_tombale(NOM, id_local, int(ligne["deleted_at"]))
        conversation = {
            "title": ligne["title"],
            "createdAt": ligne["created_at"],
            "updatedAt": ligne["updated_at"],
            "model": ligne["model"],
            "pinned": bool(ligne["pinned"]),
            "messages": json.loads(ligne["messages"]),
        }
        return clair_objet(NOM, id_local, projeter(conversation))

    def ingerer(self, clair: dict[str, Any]) -> None:
        deleted = clair.get("deleted")
        if deleted is not None:
            if not isinstance(deleted, dict):
                raise ClairInvalide("deleted n'est pas un objet")
            date = _entier(deleted.get("deletedAt"), "deletedAt")
            self._magasin.appliquer_tombale(clair["id"], date)
            return
        self._magasin.upsert(_conversation_de(clair))

    def date_de(self, clair: dict[str, Any]) -> int:
        data = clair.get("data")
        if not isinstance(data, dict):
            raise ClairInvalide("data n'est pas un objet")
        return _entier(data.get("updatedAt"), "updatedAt")

    # --- Pièces (§4.7) --------------------------------------------------

    def pieces(self, clair: dict[str, Any]) -> list[str]:
        identifiants: list[str] = []
        for message in _messages(clair) or []:
            for valeur in _images(message) or []:
                piece_id = identifiant_de(valeur)
                if piece_id is not None and piece_id not in identifiants:
                    identifiants.append(piece_id)
        return identifiants

    def detacher(
        self, clair: dict[str, Any], nommer: Callable[[bytes], str]
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        messages = _messages(clair)
        if not messages:
            return clair, {}
        pieces: dict[str, bytes] = {}
        sortie: list[Any] = []
        change = False
        for message in messages:
            images = _images(message)
            if not images or not any(detachable(v) for v in images):
                sortie.append(message)
                continue
            detachees: list[Any] = []
            for valeur in images:
                if not detachable(valeur):
                    detachees.append(valeur)
                    continue
                try:
                    octets = emballer(valeur)
                except UnicodeEncodeError:
                    # Un substitut isolé : l'image reste dans l'objet, où
                    # le scellement la refusera comme avant les pièces.
                    detachees.append(valeur)
                    continue
                piece_id = nommer(octets)
                pieces[piece_id] = octets
                detachees.append(reference(piece_id))
            sortie.append({**message, "images": detachees})
            change = True
        if not change:
            return clair, {}
        return _avec_messages(clair, sortie), pieces

    def rattacher(
        self, clair: dict[str, Any], fournir: Callable[[str], bytes | None]
    ) -> dict[str, Any]:
        messages = _messages(clair)
        if not messages:
            return clair
        # Une même image jointe deux fois ne se demande qu'une fois.
        memoire: dict[str, str | None] = {}

        def image_de(piece_id: str) -> str | None:
            if piece_id not in memoire:
                octets = fournir(piece_id)
                try:
                    memoire[piece_id] = None if octets is None else deballer(octets)
                except PieceIllisible:
                    memoire[piece_id] = None
            return memoire[piece_id]

        sortie: list[Any] = []
        change = False
        for message in messages:
            if not _troue(message):
                sortie.append(message)
                continue
            rattachees: list[Any] = []
            for valeur in _images(message) or []:
                piece_id = identifiant_de(valeur)
                if piece_id is None:
                    rattachees.append(valeur)
                    continue
                image = image_de(piece_id)
                if image is None:
                    # Tout ou rien : le message reste troué en entier.
                    rattachees = []
                    break
                rattachees.append(image)
            if rattachees:
                sortie.append({**message, "images": rattachees})
                change = True
            else:
                sortie.append(message)
        return _avec_messages(clair, sortie) if change else clair

    def trous(self, clair: dict[str, Any]) -> dict[str, list[Any]]:
        return {
            cle_message(m): list(_images(m) or [])
            for m in _messages(clair) or []
            if _troue(m)
        }

    def combler(
        self, clair: dict[str, Any], trous: dict[str, list[Any]]
    ) -> dict[str, Any]:
        messages = _messages(clair)
        if not trous or not messages:
            return clair
        sortie: list[Any] = []
        change = False
        for message in messages:
            if (
                isinstance(message, dict)
                and "images" not in message
                and cle_message(message) in trous
            ):
                sortie.append({**message, "images": list(trous[cle_message(message)])})
                change = True
            else:
                sortie.append(message)
        return _avec_messages(clair, sortie) if change else clair

    # --- Lectures pour l'écran --------------------------------------------

    def a_des_donnees(self) -> bool:
        with self._verrou:
            ligne = (
                self._connexion()
                .execute(
                    "SELECT 1 FROM conversations "
                    "WHERE deleted_at IS NULL AND messages != '[]' LIMIT 1"
                )
                .fetchone()
            )
        return ligne is not None

    def en_attente_depuis(self, seq: int) -> set[str]:
        with self._verrou:
            lignes = (
                self._connexion()
                .execute(
                    "SELECT id FROM conversations WHERE seq > ? "
                    "AND (deleted_at IS NOT NULL OR messages != '[]')",
                    (seq,),
                )
                .fetchall()
            )
        return {ligne["id"] for ligne in lignes}
