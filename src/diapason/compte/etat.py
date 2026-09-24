"""L'état local du compte : ``compte/etat.key``.

Conception : ``docs/development/compte-chiffre.md`` §4.2 (le schéma), §4.4
(les planchers), §2.10 (où vit chaque clé) et §6 bis (``incarnation_max``).

SQLite en ``journal_mode=DELETE`` et ``secure_delete=ON``. Le suffixe
``.key`` fait refuser le fichier par ``file_read`` (``file_policy.py:17``),
qui ne filtre que le nom ; ``shell_exec`` contourne cette politique de
toute façon (A7), et on ne promet rien de plus.

Le fichier n'existe QUE s'il y a un compte. ``ConversationsStore`` lit sa
présence (``_compte_present``) pour cesser de purger les tombales à l'âge
seul : un ``etat.key`` créé par un simple sondage de ``/v1/account/status``,
ou par « Plus tard » au premier lancement, aurait bloqué la purge chez
quelqu'un qui n'a jamais eu de compte. Le drapeau du premier lancement vit
donc à part, dans ``compte/accueil.json`` (écart du §3.11 P1, 24/09/2026).

Toutes les tables du §4.2 naissent ici, y compris celles que seul le moteur
de synchronisation (étape 10) remplira : aucune base de ce dépôt n'a de
migration (CLAUDE.md §5), un schéma complet dès la naissance évite d'en
écrire une.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path

from diapason.compte.cles import ErreurCompte, entier
from diapason.compte.gardien import CheminRefuse, DossierCompte

__all__ = [
    "NOM_ETAT",
    "NOM_ACCUEIL",
    "EnveloppeLocale",
    "EtatLocal",
    "Planchers",
    "RetourArriereServeur",
    "marquer_accueil",
    "accueil_fait",
]

NOM_ETAT = "etat.key"
NOM_ACCUEIL = "accueil.json"


class RetourArriereServeur(ErreurCompte):
    """Le serveur annonce une incarnation, ou un coffre, sous ce que cet
    appareil a déjà vu pour le même compte (§3.10, §6 bis)."""

    code = "serverRolledBack"


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS etat (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL)",
    # §4.2, plus ``account_id`` et ``incarnation_max`` (§6 bis, exigé de
    # l'étape 8). Sans ``incarnation_max``, un VPS qui rejouait le coffre
    # d'avant une réinitialisation annonçait aussi l'incarnation d'avant :
    # ouverte avec SA valeur, l'AAD concordait (contre-épreuve du
    # 24/09/2026). Sans ``account_id``, les planchers d'un compte auraient
    # servi à juger ceux d'un autre.
    "CREATE TABLE IF NOT EXISTS planchers_compte ("
    " id INTEGER PRIMARY KEY CHECK (id = 1),"
    " account_id TEXT NOT NULL,"
    " incarnation_max INTEGER NOT NULL,"
    " vault_version_max INTEGER NOT NULL,"
    " keyring_version_max INTEGER NOT NULL,"
    " key_epoch_max INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS enveloppe_locale ("
    " id INTEGER PRIMARY KEY CHECK (id = 1),"
    " kdf_version INTEGER NOT NULL, sel_kdf BLOB NOT NULL, amk_mdp BLOB NOT NULL,"
    " trousseau BLOB NOT NULL, version_coffre INTEGER NOT NULL,"
    " version_trousseau INTEGER NOT NULL)",
    # Tout ce qui suit porte (account_id, incarnation) : l'étape 10 le vide
    # quand l'un change (§4.3, étape 0 du cycle).
    "CREATE TABLE IF NOT EXISTS connus (account_id TEXT, incarnation INTEGER,"
    " collection TEXT, id_local TEXT, object_id TEXT NOT NULL,"
    " rev_max INTEGER NOT NULL, seq INTEGER NOT NULL, empreinte BLOB,"
    " illisible INTEGER NOT NULL DEFAULT 0, degrade INTEGER NOT NULL DEFAULT 0,"
    " PRIMARY KEY (account_id, incarnation, collection, id_local))",
    "CREATE TABLE IF NOT EXISTS curseurs_export (account_id TEXT,"
    " incarnation INTEGER, collection TEXT, seq_local INTEGER NOT NULL,"
    " PRIMARY KEY (account_id, incarnation, collection))",
    "CREATE TABLE IF NOT EXISTS sortants (account_id TEXT, incarnation INTEGER,"
    " collection TEXT, id_local TEXT, supprime_le_ms INTEGER,"
    " empreinte_poussee BLOB, tentatives INTEGER NOT NULL DEFAULT 0,"
    " prochain_essai_ms INTEGER NOT NULL DEFAULT 0, derniere_erreur TEXT,"
    " PRIMARY KEY (account_id, incarnation, collection, id_local))",
    "CREATE TABLE IF NOT EXISTS quarantaine (account_id TEXT, incarnation INTEGER,"
    " object_id TEXT, motif TEXT NOT NULL, empreinte BLOB,"
    " depuis_ms INTEGER NOT NULL, PRIMARY KEY (account_id, incarnation, object_id))",
    "CREATE TABLE IF NOT EXISTS inconnus (account_id TEXT, incarnation INTEGER,"
    " object_id TEXT, rev INTEGER, seq INTEGER, blob BLOB,"
    " PRIMARY KEY (account_id, incarnation, object_id))",
    "CREATE TABLE IF NOT EXISTS pieces_connues (account_id TEXT,"
    " incarnation INTEGER, key_epoch INTEGER, piece_id TEXT,"
    " PRIMARY KEY (account_id, incarnation, key_epoch, piece_id))",
    "CREATE TABLE IF NOT EXISTS a_reprendre (account_id TEXT, incarnation INTEGER,"
    " object_id TEXT, motif TEXT, prochain_essai_ms INTEGER,"
    " PRIMARY KEY (account_id, incarnation, object_id))",
    "CREATE TABLE IF NOT EXISTS planchers_suppression (account_id TEXT,"
    " collection TEXT, id_local TEXT, deleted_at INTEGER NOT NULL,"
    " PRIMARY KEY (account_id, collection, id_local))",
)


@dataclass(frozen=True)
class Planchers:
    """Ce qu'aucune valeur serveur ne fait reculer pour un même compte (§4.4)."""

    account_id: str
    incarnation_max: int
    vault_version_max: int
    keyring_version_max: int
    key_epoch_max: int


@dataclass(frozen=True)
class EnveloppeLocale:
    """Le coffre tel que cet appareil l'a vu en dernier : il permet de
    déverrouiller HORS LIGNE (§2.10)."""

    kdf_version: int
    sel_kdf: bytes = field(repr=False)
    amk_mdp: bytes = field(repr=False)
    trousseau: bytes = field(repr=False)
    version_coffre: int
    version_trousseau: int


def _dans_le_dossier(dossier: DossierCompte, nom: str) -> Path:
    """Le chemin d'un fichier de ``compte/``, revalidé à chaque usage.

    ``DossierCompte`` ne se construit que par ``preparer_dossier_compte`` ;
    on vérifie quand même que ce qu'on ouvre est un dossier réel, à nous :
    ``Path(MagicMock())`` a déjà fait dormir 42 bases SQLite à la racine du
    dépôt (CLAUDE.md §5), et ici ce serait une clé.
    """
    if not isinstance(dossier, DossierCompte):
        raise CheminRefuse(f"dossier du compte de type {type(dossier).__name__}")
    chemin = dossier.chemin
    try:
        etat = os.lstat(chemin)
    except FileNotFoundError:
        raise CheminRefuse(f"dossier du compte disparu : {chemin}") from None
    if stat.S_ISLNK(etat.st_mode) or not stat.S_ISDIR(etat.st_mode):
        raise CheminRefuse(f"dossier du compte qui n'est pas un dossier : {chemin}")
    return chemin / nom


def _creer_prive(chemin: Path) -> None:
    """Crée le fichier en 0600 AVANT que SQLite ne l'ouvre en 0644 (umask)."""
    drapeaux = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        drapeaux |= os.O_NOFOLLOW
    try:
        os.close(os.open(chemin, drapeaux, 0o600))
    except FileExistsError:
        infos = os.lstat(chemin)
        if stat.S_ISLNK(infos.st_mode) or not stat.S_ISREG(infos.st_mode):
            raise CheminRefuse(f"fichier d'état qui n'est pas un fichier : {chemin}")


class EtatLocal:
    """``compte/etat.key``, ouvert au premier besoin d'ÉCRIRE.

    Les lectures sur un fichier absent rendent « rien » sans le créer.
    ``check_same_thread=False`` et un verrou : les routes locales sont des
    ``def`` que Starlette exécute dans des fils différents.
    """

    def __init__(self, dossier: DossierCompte) -> None:
        self._dossier = dossier
        self._chemin = _dans_le_dossier(dossier, NOM_ETAT)
        self._verrou = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @property
    def chemin(self) -> Path:
        return self._chemin

    def existe(self) -> bool:
        return self._chemin.exists()

    # --- Connexion -----------------------------------------------------

    def _ouvrir(self, *, creer: bool) -> sqlite3.Connection | None:
        if self._conn is not None:
            return self._conn
        chemin = _dans_le_dossier(self._dossier, NOM_ETAT)
        if not chemin.exists():
            if not creer:
                return None
            _creer_prive(chemin)
        conn = sqlite3.connect(str(chemin), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=DELETE")
        # Une enveloppe effacée (déconnexion, session révoquée) ne doit pas
        # rester lisible dans les pages libres du fichier.
        conn.execute("PRAGMA secure_delete=ON")
        with conn:
            for instruction in _SCHEMA:
                conn.execute(instruction)
        self._conn = conn
        return conn

    def fermer(self) -> None:
        with self._verrou:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --- Clés-valeurs --------------------------------------------------

    def tout(self) -> dict[str, str]:
        with self._verrou:
            conn = self._ouvrir(creer=False)
            if conn is None:
                return {}
            return dict(conn.execute("SELECT cle, valeur FROM etat").fetchall())

    def lire(self, cle: str) -> str | None:
        return self.tout().get(cle)

    def ecrire(self, **valeurs: str | int | bool | None) -> None:
        """``None`` efface la clé. Les booléens s'écrivent ``1``/``0``."""
        with self._verrou:
            conn = self._ouvrir(creer=True)
            assert conn is not None
            with conn:
                for cle, valeur in valeurs.items():
                    if valeur is None:
                        conn.execute("DELETE FROM etat WHERE cle = ?", (cle,))
                        continue
                    if isinstance(valeur, bool):
                        texte = "1" if valeur else "0"
                    else:
                        texte = str(valeur)
                    conn.execute(
                        "INSERT INTO etat (cle, valeur) VALUES (?, ?) "
                        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                        (cle, texte),
                    )

    # --- Planchers (§4.4, §6 bis) --------------------------------------

    def planchers(self) -> Planchers | None:
        with self._verrou:
            conn = self._ouvrir(creer=False)
            if conn is None:
                return None
            ligne = conn.execute(
                "SELECT account_id, incarnation_max, vault_version_max,"
                " keyring_version_max, key_epoch_max FROM planchers_compte"
                " WHERE id = 1"
            ).fetchone()
        return None if ligne is None else Planchers(*ligne)

    def planchers_pour(self, account_id: str, incarnation: int) -> Planchers:
        """Les planchers qui jugeront un coffre de ``(account_id, incarnation)``.

        Lève :class:`RetourArriereServeur` si l'incarnation annoncée est
        INFÉRIEURE à celle que cet appareil a déjà vue pour ce compte — et
        cela AVANT tout essai de clé : sinon le rejeu d'un coffre d'avant
        la réinitialisation se lisait ``envelopeUnreadable``, indiscernable
        d'un mauvais mot de passe (§6 bis). Une incarnation SUPÉRIEURE, ou
        un autre compte, repart de planchers nuls : c'est une incarnation
        neuve, dont le coffre recommence à la version 1.
        """
        entier(incarnation, "incarnation", minimum=1)
        actuels = self.planchers()
        if actuels is None or actuels.account_id != account_id:
            return Planchers(account_id, incarnation, 0, 0, 0)
        if incarnation < actuels.incarnation_max:
            raise RetourArriereServeur(
                f"incarnation {incarnation} sous celle déjà vue "
                f"({actuels.incarnation_max})"
            )
        if incarnation > actuels.incarnation_max:
            return Planchers(account_id, incarnation, 0, 0, 0)
        return actuels

    def relever_planchers(
        self,
        account_id: str,
        incarnation: int,
        *,
        vault_version: int,
        keyring_version: int,
        key_epoch: int,
    ) -> Planchers:
        """Monte les planchers — jamais ne les descend pour un même
        ``(compte, incarnation)``. Une incarnation neuve les remplace."""
        with self._verrou:
            base = self.planchers_pour(account_id, incarnation)
            nouveaux = Planchers(
                account_id=account_id,
                incarnation_max=incarnation,
                vault_version_max=max(base.vault_version_max, vault_version),
                keyring_version_max=max(base.keyring_version_max, keyring_version),
                key_epoch_max=max(base.key_epoch_max, key_epoch),
            )
            conn = self._ouvrir(creer=True)
            assert conn is not None
            with conn:
                conn.execute(
                    "INSERT INTO planchers_compte (id, account_id, incarnation_max,"
                    " vault_version_max, keyring_version_max, key_epoch_max)"
                    " VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                    " account_id = excluded.account_id,"
                    " incarnation_max = excluded.incarnation_max,"
                    " vault_version_max = excluded.vault_version_max,"
                    " keyring_version_max = excluded.keyring_version_max,"
                    " key_epoch_max = excluded.key_epoch_max",
                    (
                        nouveaux.account_id,
                        nouveaux.incarnation_max,
                        nouveaux.vault_version_max,
                        nouveaux.keyring_version_max,
                        nouveaux.key_epoch_max,
                    ),
                )
            return nouveaux

    # --- Enveloppe locale ----------------------------------------------

    def enveloppe_locale(self) -> EnveloppeLocale | None:
        with self._verrou:
            conn = self._ouvrir(creer=False)
            if conn is None:
                return None
            ligne = conn.execute(
                "SELECT kdf_version, sel_kdf, amk_mdp, trousseau, version_coffre,"
                " version_trousseau FROM enveloppe_locale WHERE id = 1"
            ).fetchone()
        if ligne is None:
            return None
        return EnveloppeLocale(
            kdf_version=ligne[0],
            sel_kdf=bytes(ligne[1]),
            amk_mdp=bytes(ligne[2]),
            trousseau=bytes(ligne[3]),
            version_coffre=ligne[4],
            version_trousseau=ligne[5],
        )

    def ranger_enveloppe_locale(self, enveloppe: EnveloppeLocale) -> None:
        with self._verrou:
            conn = self._ouvrir(creer=True)
            assert conn is not None
            with conn:
                conn.execute(
                    "INSERT INTO enveloppe_locale (id, kdf_version, sel_kdf, amk_mdp,"
                    " trousseau, version_coffre, version_trousseau)"
                    " VALUES (1, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                    " kdf_version = excluded.kdf_version, sel_kdf = excluded.sel_kdf,"
                    " amk_mdp = excluded.amk_mdp, trousseau = excluded.trousseau,"
                    " version_coffre = excluded.version_coffre,"
                    " version_trousseau = excluded.version_trousseau",
                    (
                        enveloppe.kdf_version,
                        enveloppe.sel_kdf,
                        enveloppe.amk_mdp,
                        enveloppe.trousseau,
                        enveloppe.version_coffre,
                        enveloppe.version_trousseau,
                    ),
                )

    def effacer_enveloppe_locale(self) -> None:
        with self._verrou:
            conn = self._ouvrir(creer=False)
            if conn is None:
                return
            with conn:
                conn.execute("DELETE FROM enveloppe_locale")

    # --- Tout effacer --------------------------------------------------

    def detruire(self) -> None:
        """Déconnexion, suppression, autre compte : « vide tout » (§4.4).

        Le fichier disparaît, pas seulement ses lignes : sa seule présence
        dit au magasin des conversations qu'un compte existe, et bloque la
        purge des tombales à l'âge (``conversations_store._compte_present``).
        """
        with self._verrou:
            conn = self._ouvrir(creer=False)
            if conn is not None:
                with conn:
                    for table in (
                        "etat",
                        "planchers_compte",
                        "enveloppe_locale",
                        "connus",
                        "curseurs_export",
                        "sortants",
                        "quarantaine",
                        "inconnus",
                        "pieces_connues",
                        "a_reprendre",
                        "planchers_suppression",
                    ):
                        conn.execute(f"DELETE FROM {table}")
                conn.close()
                self._conn = None
            for suffixe in ("", "-journal"):
                try:
                    os.unlink(str(self._chemin) + suffixe)
                except FileNotFoundError:
                    pass


# ----------------------------------------------------------------------
# Le premier lancement (§3.11 P1, D13)
# ----------------------------------------------------------------------


def accueil_fait(dossier: DossierCompte) -> bool:
    try:
        chemin = _dans_le_dossier(dossier, NOM_ACCUEIL)
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError, CheminRefuse):
        return False
    return isinstance(contenu, dict) and contenu.get("onboarding") == "done"


def marquer_accueil(dossier: DossierCompte) -> None:
    """« Plus tard » ou fin de l'activation : l'écran ne revient pas.

    Dans ``compte/`` et jamais dans le ``localStorage`` : la fenêtre
    (``tauri://localhost``) et le mini-panneau (``127.0.0.1:8000``) ne le
    partagent pas, et l'écran se serait montré une fois par origine.
    """
    chemin = _dans_le_dossier(dossier, NOM_ACCUEIL)
    provisoire = chemin.with_name(NOM_ACCUEIL + ".provisoire")
    drapeaux = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        drapeaux |= os.O_NOFOLLOW
    descripteur = os.open(provisoire, drapeaux, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        fichier.write(json.dumps({"onboarding": "done"}))
    os.replace(provisoire, chemin)
