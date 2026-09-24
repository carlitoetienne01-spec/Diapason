"""Le journal d'événements, et la restauration logique qui le rejoue.

Conception : ``docs/development/compte-chiffre.md`` §3.3 et §3.10.

``/var/lib/diapason/evenements.jsonl`` vit HORS de la base, en ajout seul,
chaque ligne suivie d'un ``fsync``. Il reçoit chaque création et chaque
suppression de compte, chaque révocation de session, chaque
``vault/commit`` et chaque ``reset/complete`` — avec la ligne de sécurité
COMPLÈTE après le changement, sur-chiffrée par ``CLE_REPOS`` — et, depuis
le 24/09/2026, chaque ``reset/confirm`` et ``reset/cancel`` : sans eux, une
restauration ressuscitait une réinitialisation annulée (§3.6).

La ligne est écrite DANS la transaction, avant le ``COMMIT`` : une panne du
journal annule donc le changement (``reset/complete`` atomique). Si c'est
le ``COMMIT`` qui échoue ensuite, une entrée ``entryAborted`` marque la
ligne déjà écrite, et le rejeu la saute.

Pourquoi : une copie de ``comptes.db`` d'hier, restaurée telle quelle,
ramènerait l'ancien mot de passe (le coffre d'hier), les sessions d'un
appareil perdu révoqué ce matin, et un compte supprimé cet après-midi. La
restauration copie la base PUIS rejoue le journal postérieur : le coffre
redevient celui d'aujourd'hui, le compte supprimé l'est de nouveau.

Le rejeu est IDEMPOTENT et se règle sur des versions, pas sur des heures :
un événement ne s'applique que s'il est plus récent que la copie, au sens
de ``(incarnation, vaultVersion)``. Rejouer un ``reset/complete`` antérieur
à la copie effacerait sinon les objets poussés depuis.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from diapason_comptes.base import (
    COLONNES_COMPTE,
    Base,
    Compte,
    ecrire_compte,
    global_seq,
    lire_compte,
)
from diapason_comptes.secrets_serveur import SecretsServeur

VERSION_JOURNAL = 1

CREATION = "accountCreated"
SUPPRESSION = "accountDeleted"
REVOCATION = "sessionRevoked"
COFFRE = "vaultCommit"
REINITIALISATION = "resetComplete"
REINIT_PREVUE = "resetScheduled"
REINIT_ANNULEE = "resetCancelled"
ANNULATION = "entryAborted"

_COLONNES_OCTETS = frozenset(f.name for f in fields(Compte) if "bytes" in str(f.type))


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).decode("ascii")


def _de_b64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte.encode("ascii"))


def _ligne_json(compte: Compte) -> bytes:
    ligne: dict[str, Any] = {}
    for nom in COLONNES_COMPTE:
        valeur = getattr(compte, nom)
        ligne[nom] = _b64(valeur) if isinstance(valeur, bytes) else valeur
    return json.dumps(ligne, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _compte_de_json(octets: bytes) -> Compte:
    ligne = json.loads(octets.decode("utf-8"))
    valeurs = {}
    for nom in COLONNES_COMPTE:
        valeur = ligne[nom]
        if nom in _COLONNES_OCTETS and valeur is not None:
            valeur = _de_b64(valeur)
        valeurs[nom] = valeur
    return Compte(**valeurs)


def _ecrire_atomiquement(chemin: Path, entrees: list[dict[str, Any]]) -> None:
    """Fichier temporaire, ``fsync``, ``os.replace`` : jamais de demi-journal."""
    temporaire = chemin.with_name(chemin.name + ".tmp")
    fd = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        for entree in entrees:
            os.write(
                fd,
                (
                    json.dumps(entree, sort_keys=True, separators=(",", ":")) + "\n"
                ).encode(),
            )
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporaire, chemin)


class Journal:
    """``evenements.jsonl`` : ajout seul, ``fsync`` à chaque ligne.

    ``base`` : la base dont les transactions portent les lignes écrites.
    Une ligne écrite dans une transaction qui n'est pas validée est marquée
    ``entryAborted`` (voir :meth:`Base.si_annulee`).
    """

    def __init__(
        self, chemin: Path, secrets_: SecretsServeur, base: Base | None = None
    ) -> None:
        self.chemin = Path(chemin)
        self._secrets = secrets_
        self._base = base
        self._verrou = threading.Lock()
        self.chemin.parent.mkdir(parents=True, exist_ok=True)

    def _ecrire(self, entree: dict[str, Any]) -> None:
        ligne = json.dumps(entree, sort_keys=True, separators=(",", ":")) + "\n"
        with self._verrou:
            # 0600 même hors de systemd (``UMask=0077``) : le journal porte
            # les coffres sur-chiffrés, pas moins sensibles que la base.
            fd = os.open(self.chemin, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, ligne.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)

    def _ajouter(self, entree: dict[str, Any]) -> None:
        self._ecrire(entree)
        if self._base is not None:
            ref, t = entree["id"], entree["t"]
            self._base.si_annulee(
                lambda: self._ecrire(
                    {"v": VERSION_JOURNAL, "type": ANNULATION, "t": t, "ref": ref}
                )
            )

    def _entree(self, type_: str, compte_id: str, maintenant: int, seq: int) -> dict:
        return {
            "v": VERSION_JOURNAL,
            # ``g`` (globalSeq) ne suffit pas à nommer une ligne : une
            # transaction annulée rend son numéro à la suivante.
            "id": secrets.token_hex(8),
            "type": type_,
            "t": maintenant,
            "g": seq,
            "accountId": compte_id,
        }

    def ligne_de_securite(
        self, type_: str, compte: Compte, maintenant: int, seq: int, **extra: Any
    ) -> None:
        """Création, coffre ou réinitialisation : la ligne complète APRÈS."""
        entree = self._entree(type_, compte.id, maintenant, seq)
        entree["row"] = _b64(
            self._secrets.sceller(compte.id, "journal|" + type_, _ligne_json(compte))
        )
        entree.update(extra)
        self._ajouter(entree)

    def suppression(self, compte: Compte, maintenant: int, seq: int) -> None:
        """L'index HMAC, jamais l'adresse (§3.3)."""
        entree = self._entree(SUPPRESSION, compte.id, maintenant, seq)
        entree["emailIndex"] = compte.courriel_index.hex()
        self._ajouter(entree)

    def revocations(
        self, compte_id: str, hashes: list[bytes], maintenant: int, seq: int
    ) -> None:
        if not hashes:
            return
        entree = self._entree(REVOCATION, compte_id, maintenant, seq)
        entree["sessionHashes"] = sorted(h.hex() for h in hashes)
        self._ajouter(entree)

    def reinitialisation(self, compte: Compte, maintenant: int, seq: int) -> None:
        """``reset/confirm`` (attente posée) ou ``reset/cancel`` (levée).

        Le rejeu ne s'applique qu'à la même ``incarnation`` : une attente
        posée avant un ``reset/complete`` ne revient pas sur le compte neuf.
        """
        prevue = compte.reinit_demandee_ms is not None
        entree = self._entree(
            REINIT_PREVUE if prevue else REINIT_ANNULEE, compte.id, maintenant, seq
        )
        entree["incarnation"] = compte.incarnation
        if prevue:
            entree["requestedAt"] = compte.reinit_demandee_ms
            entree["effectiveAt"] = compte.reinit_effective_ms
        self._ajouter(entree)

    def oublier(self, compte_id: str) -> int:
        """Retire les lignes d'un compte SUPPRIMÉ, sauf ``accountDeleted``.

        §3.3 : du compte supprimé, le journal ne garde que l'index HMAC.
        Ses lignes ``accountCreated`` et ``vaultCommit`` portaient l'adresse,
        scellée sous ``CLE_REPOS`` — sur le même disque — jusqu'à ce qu'une
        sauvegarde réussie tronque le journal, ce qui peut ne jamais venir.
        La restauration n'en a plus besoin : ``accountDeleted`` suffit à
        effacer le compte d'une copie antérieure, et un compte né après la
        copie n'y figure pas. Rend le nombre de lignes retirées.
        """
        with self._verrou:
            entrees = list(lire(self.chemin))
            gardees = [
                e
                for e in entrees
                if e.get("accountId") != compte_id or e.get("type") == SUPPRESSION
            ]
            if len(gardees) != len(entrees):
                _ecrire_atomiquement(self.chemin, gardees)
        return len(entrees) - len(gardees)


def lire(chemin: Path) -> Iterator[dict[str, Any]]:
    """Les entrées dans l'ordre d'écriture. Une dernière ligne tronquée (une
    coupure pendant ``write``) est ignorée ; une ligne illisible AILLEURS lève,
    parce qu'un journal corrompu au milieu ne peut pas être rejoué sans
    mentir sur ce qu'il contient."""
    if not Path(chemin).exists():
        return
    lignes = Path(chemin).read_bytes().split(b"\n")
    for numero, brut in enumerate(lignes):
        if not brut.strip():
            continue
        try:
            yield json.loads(brut)
        except ValueError:
            if numero == len(lignes) - 1:
                return
            raise


def tronquer(chemin: Path, avant_ms: int) -> int:
    """Garde les entrées de ``t >= avant_ms`` ; rend le nombre retiré.

    ``sauvegarder.py`` (étape 7) l'appelle avec « dernière sauvegarde valide
    moins 1 jour » (§3.3). Réécriture atomique : fichier temporaire,
    ``fsync``, ``os.replace``.
    """
    chemin = Path(chemin)
    entrees = list(lire(chemin))
    gardees = [e for e in entrees if e.get("t", 0) >= avant_ms]
    _ecrire_atomiquement(chemin, gardees)
    return len(entrees) - len(gardees)


# ----------------------------------------------------------------------
# Restauration logique (§3.10)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class RapportRestauration:
    appliques: int
    ignores: int
    generation: str
    global_seq: int
    # ``globalSeq`` de la base remplacée, ou ``None`` si elle manquait ou
    # était illisible : le plancher n'a alors été que le journal.
    global_seq_remplacee: int | None = None


def _global_seq_de(chemin: Path) -> int | None:
    """``globalSeq`` d'une base, lue sans l'écrire ; ``None`` si elle manque
    ou ne se lit pas (on restaure souvent PARCE QU'elle est abîmée)."""
    if not chemin.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
        try:
            return global_seq(conn)
        finally:
            conn.close()
    except (sqlite3.Error, LookupError, ValueError):
        return None


def _plus_recent(evenement: Compte, copie: Compte | None) -> bool:
    if copie is None:
        return True
    return (evenement.incarnation, evenement.version_coffre) > (
        copie.incarnation,
        copie.version_coffre,
    )


def _rejouer(
    conn: sqlite3.Connection, entree: dict[str, Any], secrets_: SecretsServeur
) -> bool:
    type_ = entree.get("type")
    compte_id = entree.get("accountId")
    if type_ == SUPPRESSION:
        # ``ON DELETE CASCADE`` : sessions, objets, pièces partent avec lui.
        curseur = conn.execute("DELETE FROM comptes WHERE id = ?", (compte_id,))
        conn.execute(
            "DELETE FROM codes WHERE courriel_index = ?",
            (bytes.fromhex(entree["emailIndex"]),),
        )
        return curseur.rowcount > 0
    if type_ == REVOCATION:
        for hash_hex in entree.get("sessionHashes", []):
            conn.execute(
                "DELETE FROM sessions WHERE jeton_hash = ?", (bytes.fromhex(hash_hex),)
            )
        return True
    if type_ in (REINIT_PREVUE, REINIT_ANNULEE):
        prevue = type_ == REINIT_PREVUE
        curseur = conn.execute(
            "UPDATE comptes SET reinit_demandee_ms = ?, reinit_effective_ms = ? "
            "WHERE id = ? AND incarnation = ?",
            (
                entree["requestedAt"] if prevue else None,
                entree["effectiveAt"] if prevue else None,
                compte_id,
                entree["incarnation"],
            ),
        )
        return curseur.rowcount > 0
    if type_ not in (CREATION, COFFRE, REINITIALISATION):
        raise ValueError(f"type d'événement inconnu : {type_!r}")
    evenement = _compte_de_json(
        secrets_.ouvrir(compte_id, "journal|" + type_, _de_b64(entree["row"]))
    )
    copie = lire_compte(conn, compte_id)
    if not _plus_recent(evenement, copie):
        return False
    if type_ == REINITIALISATION:
        conn.execute("DELETE FROM objets WHERE compte_id = ?", (compte_id,))
        conn.execute("DELETE FROM pieces WHERE compte_id = ?", (compte_id,))
    if copie is not None and type_ != REINITIALISATION:
        # Le journal porte la ligne de SÉCURITÉ ; ``seq`` et ``octets``
        # décrivent les objets de la copie, qui restent ceux de la copie.
        # ``reinit_*`` sont repris tels que la ligne les porte : toute
        # modification ultérieure a son entrée (``resetScheduled``,
        # ``resetCancelled``) et le rejeu suit l'ordre du journal.
        evenement = Compte(
            **{
                **{n: getattr(evenement, n) for n in COLONNES_COMPTE},
                "seq": copie.seq,
                "octets": copie.octets,
            }
        )
    # Un autre compte a pu prendre l'index entre-temps (supprimé puis recréé
    # avec la même adresse) : l'ordre du journal fait foi, le plus récent
    # gagne, l'autre ligne est un compte que le journal a déjà supprimé.
    conn.execute(
        "DELETE FROM comptes WHERE courriel_index = ? AND id != ?",
        (evenement.courriel_index, compte_id),
    )
    ecrire_compte(conn, evenement)
    return True


def restaurer(
    copie: Path, cible: Path, journal: Path, secrets_: SecretsServeur
) -> RapportRestauration:
    """Restaure ``copie`` vers ``cible`` et rejoue ``journal`` par-dessus.

    Le service doit être ARRÊTÉ. Étapes du §3.10 : 1) copie ; 2) rejeu du
    journal postérieur ; 3) ``sessions`` et ``jetons_temporaires`` vidés ;
    4) nouvelle ``generation``. ``globalSeq`` repart au-dessus de la copie,
    du journal ET de la base remplacée : un appareil qui compare y verrait
    sinon un recul, et conclurait à un retour arrière de toute la machine.

    La base remplacée compte parce que ni les poussées ni les pièces
    n'écrivent au journal. Jusqu'au 24/09/2026, vingt poussées après la
    copie faisaient retomber ``globalSeq`` de 22 à 3, et chaque appareil
    passait en ``serverRolledBack`` — rotation obligatoire pour tous.
    """
    copie, cible = Path(copie), Path(cible)
    seq_remplacee = _global_seq_de(cible)
    temporaire = cible.with_name(cible.name + ".restauration")
    for chemin in (
        temporaire,
        Path(str(temporaire) + "-wal"),
        Path(str(temporaire) + "-shm"),
    ):
        chemin.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{copie}?mode=ro", uri=True)
    destination = sqlite3.connect(str(temporaire))
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()

    base = Base(temporaire)
    appliques = ignores = 0
    seq_max = 0
    entrees = list(lire(journal))
    annulees = {e["ref"] for e in entrees if e.get("type") == ANNULATION}
    try:
        with base.transaction() as conn:
            for entree in entrees:
                if entree.get("type") == ANNULATION:
                    continue
                seq_max = max(seq_max, int(entree.get("g", 0)))
                if entree.get("id") in annulees:
                    ignores += 1
                elif _rejouer(conn, entree, secrets_):
                    appliques += 1
                else:
                    ignores += 1
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM jetons_temporaires")
            nouvelle = secrets.token_hex(16)
            conn.execute(
                "UPDATE meta SET valeur = ? WHERE cle = 'generation'", (nouvelle,)
            )
            seq = max(global_seq(conn), seq_max, seq_remplacee or 0) + 1
            conn.execute(
                "UPDATE meta SET valeur = ? WHERE cle = 'globalSeq'", (str(seq),)
            )
        base.point_de_controle()
    finally:
        base.fermer()
    for suffixe in ("-wal", "-shm"):
        Path(str(cible) + suffixe).unlink(missing_ok=True)
        Path(str(temporaire) + suffixe).unlink(missing_ok=True)
    # 0600 quel que soit l'umask de l'appelant : ``UMask=0077`` est celui de
    # l'unité systemd, pas d'un shell ``sudo -u diapason``. Jusqu'au
    # 24/09/2026, la base restaurée sortait en 0644 sur un VPS partagé.
    os.chmod(temporaire, 0o600)
    os.replace(temporaire, cible)
    return RapportRestauration(
        appliques=appliques,
        ignores=ignores,
        generation=nouvelle,
        global_seq=seq,
        global_seq_remplacee=seq_remplacee,
    )
