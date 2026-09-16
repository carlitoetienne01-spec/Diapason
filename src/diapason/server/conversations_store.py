"""Magasin SQLite des conversations du chat (~/.diapason/conversations.db).

Le serveur est la source de vérité : l'historique vivait dans le
localStorage du frontend, cloisonné par origine, et la fenêtre principale
(tauri://localhost) et le mini-panneau (http://127.0.0.1:8000) portaient
donc chacun le leur — deux historiques qui divergeaient en silence
(16 sept. 2026).

Deux choix de conception, chacun né d'un défaut trouvé en revue le même
jour :

- **Le curseur des clients est un numéro d'écriture (``seq``), pas une
  heure.** Un premier jet filtrait ``updated_at > since`` sur l'heure du
  CONTENU fournie par le client : une conversation poussée en retard (vue
  fermée puis rouverte, serveur relancé pendant la poussée) arrivait avec
  son vieux ``updatedAt`` et restait invisible à jamais aux vues dont le
  curseur avait déjà dépassé cette heure. Chaque écriture prend ici un
  numéro monotone ; un client qui demande ``since=N`` reçoit tout ce qui a
  été écrit après, quelle que soit l'heure que porte le contenu.

- **La fusion se fait au grain du MESSAGE, pas de la conversation.** Un
  dernier-écrit-gagne sur la conversation entière faisait perdre des
  messages dès que deux vues touchaient le même fil dans la fenêtre de
  synchronisation (une question envoyée depuis le mini-panneau pendant
  que la fenêtre principale finissait de recevoir sa réponse) : la copie
  la plus récente écrasait l'autre, question et réponse comprises.
  :func:`fusionner_conversations` fait l'union des messages par identité,
  et le frontend applique la MÊME règle (``convSync.ts``) : quel que soit
  l'ordre des poussées, toutes les vues convergent vers le même résultat.

Les messages restent opaques pour le serveur hors de leur identité (``id``,
ou ``role@timestamp`` pour les historiques d'avant l'identifiant). Une
suppression laisse une pierre tombale (``deleted_at`` non NULL) dont title
et messages sont vidés — une suppression qui garde le texte n'est pas une
suppression.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from diapason.core.paths import get_config_dir

# 30 jours avant de purger une pierre tombale : assez pour qu'un appareil
# éteint des semaines — pc-bureau — se rallume, tire l'historique et
# apprenne la suppression avant qu'elle ne disparaisse du registre. Plus
# court, la conversation supprimée « ressusciterait » depuis la copie
# locale de l'appareil revenu ; plus long n'achète rien, la fusion est
# idempotente.
_RETENTION_TOMBALES_JOURS = 30

_CREATE_CONVERSATIONS = """\
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT    PRIMARY KEY,
    title      TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    model      TEXT    NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0,
    messages   TEXT    NOT NULL DEFAULT '[]',
    deleted_at INTEGER,
    seq        INTEGER NOT NULL
);
"""

_CREATE_INDEX_SEQ = (
    "CREATE INDEX IF NOT EXISTS idx_conversations_seq ON conversations(seq)"
)

# Le compteur vit dans sa propre table, PAS dans MAX(seq) : la purge des
# tombales retire des lignes, et si la ligne purgée portait le plus grand
# numéro, la prochaine écriture le réutiliserait — un client dont le
# curseur vaut ce numéro ne la verrait jamais.
_CREATE_COMPTEUR = """\
CREATE TABLE IF NOT EXISTS compteur (
    nom    TEXT    PRIMARY KEY,
    valeur INTEGER NOT NULL
);
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def sans_substituts(texte: str) -> str:
    """Remplace tout substitut UTF-16 isolé par U+FFFD.

    ``JSON.stringify`` (bien-formé depuis ES2019) échappe un demi-surrogat
    collé dans un message en ``\\ud800`` — JSON valide — que ``json.loads``
    rend en ``str`` Python porteuse d'un surrogat isolé. Stocké tel quel,
    sqlite3 refusait de l'encoder en UTF-8 : 500 sur chaque poussée de la
    conversation, qui ne se synchronisait plus jamais (constaté en revue le
    16 sept. 2026).
    """
    return texte.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


# ----------------------------------------------------------------------
# Fusion — la même règle que convSync.ts, à la lettre
# ----------------------------------------------------------------------


def cle_message(message: Dict[str, Any]) -> str:
    """Identité d'un message : son ``id``, sinon ``role@timestamp``.

    Les historiques d'avant l'identifiant n'en portent pas ; sans repli,
    deux copies du même message se seraient dupliquées à chaque fusion.
    """
    ident = message.get("id")
    if isinstance(ident, str) and ident:
        return ident
    return f"{message.get('role', '')}@{message.get('timestamp', 0)}"


def _rang_role(message: Dict[str, Any]) -> int:
    # Dans une paire écrite à la même milliseconde, la question précède la
    # réponse.
    return 0 if message.get("role") == "user" else 1


def _nombre(valeur: Any) -> float:
    return valeur if isinstance(valeur, (int, float)) else 0


def _meilleur_message(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Entre deux versions du même message, garde la plus complète.

    Le contenu d'une réponse ne fait que croître pendant le flux — une
    copie partielle poussée pour que l'autre vue voie la réponse arriver ne
    doit jamais écraser la copie finale, quelle que soit la vue qui a écrit
    la conversation en dernier. Puis le nombre de champs (la copie finale
    porte usage, télémétrie, appels d'outils), puis l'ordre lexicographique
    du contenu pour que les deux côtés tranchent pareil.
    """
    contenu_a = a.get("content", "") if isinstance(a.get("content"), str) else ""
    contenu_b = b.get("content", "") if isinstance(b.get("content"), str) else ""
    if len(contenu_a) != len(contenu_b):
        return a if len(contenu_a) > len(contenu_b) else b
    if len(a) != len(b):
        return a if len(a) > len(b) else b
    if contenu_a != contenu_b:
        return a if contenu_a > contenu_b else b
    return a


def _prime(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Vrai si ``a`` fournit les métadonnées (titre, épingle, modèle).

    L'écriture la plus récente gagne ; sur égalité de ``updatedAt`` (deux
    vues à la même milliseconde), un ordre total explicite pour que le
    serveur et chaque client désignent la même copie.
    """
    if a["updatedAt"] != b["updatedAt"]:
        return a["updatedAt"] > b["updatedAt"]
    if len(a["messages"]) != len(b["messages"]):
        return len(a["messages"]) > len(b["messages"])
    if a["title"] != b["title"]:
        return a["title"] > b["title"]
    if bool(a.get("pinned")) != bool(b.get("pinned")):
        return bool(a.get("pinned"))
    if a["model"] != b["model"]:
        return a["model"] > b["model"]
    return True


def fusionner_messages(
    des_a: List[Dict[str, Any]], des_b: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Union par identité, la version la plus complète par message, dans
    l'ordre du temps (puis question avant réponse, puis identité)."""
    par_cle: Dict[str, Dict[str, Any]] = {}
    for message in des_b:
        par_cle[cle_message(message)] = message
    for message in des_a:
        cle = cle_message(message)
        autre = par_cle.get(cle)
        par_cle[cle] = message if autre is None else _meilleur_message(message, autre)
    return sorted(
        par_cle.values(),
        key=lambda m: (_nombre(m.get("timestamp")), _rang_role(m), cle_message(m)),
    )


def fusionner_conversations(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Jointure commutative et idempotente de deux copies d'une conversation.

    Les métadonnées viennent de la copie qui prime, les messages sont
    l'union des deux, ``updatedAt`` le plus haut, ``createdAt`` le plus bas.
    Re-fusionner le résultat avec l'une des entrées rend le résultat.
    """
    gagnante, perdante = (a, b) if _prime(a, b) else (b, a)
    return {
        "id": gagnante["id"],
        "title": gagnante["title"],
        "createdAt": min(int(a["createdAt"]), int(b["createdAt"])),
        "updatedAt": max(int(a["updatedAt"]), int(b["updatedAt"])),
        "model": gagnante["model"],
        "pinned": bool(gagnante.get("pinned")),
        "messages": fusionner_messages(gagnante["messages"], perdante["messages"]),
    }


# ----------------------------------------------------------------------
# Le magasin
# ----------------------------------------------------------------------


class ConversationsStore:
    """Conversations vivantes et pierres tombales, numérotées par écriture.

    Toutes les vues tournent sur la même machine : les horloges sont
    identiques, ``updatedAt`` / ``deletedAt`` (ms epoch) suffisent pour
    départager deux versions d'un même objet. Mais l'ORDRE dans lequel le
    serveur apprend les choses, lui, n'a rien à voir avec ces heures — d'où
    ``seq``.
    """

    def __init__(self, db_path: str | Path = "") -> None:
        # Un chemin qui n'est ni str ni Path est refusé AVANT d'ouvrir quoi
        # que ce soit : ``Path(MagicMock())`` rend « MagicMock/<nom>/<id> »
        # via __fspath__, et 42 vraies bases SQLite ont déjà dormi à la
        # racine du dépôt pour cette raison (piège documenté du dépôt).
        if db_path and not isinstance(db_path, (str, Path)):
            raise TypeError(
                f"db_path doit être str ou Path, pas {type(db_path).__name__}"
            )
        if not db_path:
            db_path = str(get_config_dir() / "conversations.db")
        else:
            db_path = str(db_path)
        if db_path != ":memory:":
            from diapason.security.file_utils import secure_create

            secure_create(Path(db_path))
        self.chemin = db_path
        # check_same_thread=False + WAL : les routes tournent en ``def``
        # synchrone dans le pool de fils de Starlette, jamais sur le fil qui
        # a ouvert la connexion. Le verrou sérialise les écritures.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(_CREATE_CONVERSATIONS)
        self._db.execute(_CREATE_INDEX_SEQ)
        self._db.execute(_CREATE_COMPTEUR)
        self._db.execute(
            "INSERT OR IGNORE INTO compteur (nom, valeur) VALUES ('seq', 0)"
        )
        self._db.commit()
        self._purge_old_tombstones()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(
        self, since: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
        """Rend (vivantes, tombales, seq) écrites APRÈS le numéro ``since``.

        Sans ``since`` : tout — vivantes et toutes les tombales non purgées.
        ``seq`` est le dernier numéro attribué : tout ce qui porte un numéro
        inférieur ou égal est dans la réponse (ou plus vieux que ``since``),
        le client peut donc y poser son curseur.
        """
        with self._lock:
            if since is None:
                vivantes = self._db.execute(
                    "SELECT * FROM conversations WHERE deleted_at IS NULL "
                    "ORDER BY updated_at DESC"
                ).fetchall()
                tombales = self._db.execute(
                    "SELECT id, deleted_at FROM conversations "
                    "WHERE deleted_at IS NOT NULL"
                ).fetchall()
            else:
                vivantes = self._db.execute(
                    "SELECT * FROM conversations "
                    "WHERE deleted_at IS NULL AND seq > ? "
                    "ORDER BY updated_at DESC",
                    (since,),
                ).fetchall()
                tombales = self._db.execute(
                    "SELECT id, deleted_at FROM conversations "
                    "WHERE deleted_at IS NOT NULL AND seq > ?",
                    (since,),
                ).fetchall()
            seq = self._seq_courant()
        return (
            [self._row_to_conversation(row) for row in vivantes],
            [{"id": row["id"], "deletedAt": row["deleted_at"]} for row in tombales],
            seq,
        )

    def upsert(self, conv: Dict[str, Any]) -> Dict[str, Any]:
        """Fusionne la copie reçue avec la copie stockée. Rend ce que le
        client doit croire désormais.

        - tombale avec ``deletedAt >= conv.updatedAt`` : reste supprimée,
          rend ``{"deleted": True, "deletedAt": int}`` — une suppression qui
          ressuscite parce qu'un autre appareil a poussé sa vieille copie
          serait un mensonge (§100).
        - vivante : la fusion des deux (union des messages, métadonnées de
          la plus récente) est stockée si elle diffère de la copie stockée,
          rend ``{"conversation": <copie stockée>}``. Une fusion sans effet
          n'écrit rien et ne consomme pas de numéro : les autres vues n'ont
          rien à apprendre.
        - inconnue, ou tombale plus vieille : stockée telle quelle (la
          tombale est effacée), rend ``{"conversation": <telle que stockée>}``.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv["id"],)
            ).fetchone()
            updated_at = int(conv["updatedAt"])
            if row is not None and row["deleted_at"] is not None:
                if row["deleted_at"] >= updated_at:
                    return {"deleted": True, "deletedAt": row["deleted_at"]}
                a_stocker = conv
            elif row is not None:
                stockee = self._row_to_conversation(row)
                a_stocker = fusionner_conversations(stockee, conv)
                if a_stocker == stockee:
                    return {"conversation": stockee}
            else:
                a_stocker = conv
            self._ecrire(a_stocker)
            stored = self._db.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv["id"],)
            ).fetchone()
        return {"conversation": self._row_to_conversation(stored)}

    def delete(self, conversation_id: str) -> int:
        """Pose une pierre tombale et rend son ``deletedAt`` (ms).

        Idempotent, même pour un id inconnu : re-supprimer ce qui n'existe
        pas doit réussir, sinon deux appareils qui suppriment la même
        conversation verraient le second échouer pour rien. La tombale vide
        title et messages — une suppression qui garde le texte n'est pas
        une suppression.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT deleted_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            existing = row["deleted_at"] if row is not None else None
            deleted_at = max(_now_ms(), existing or 0)
            seq = self._prochain_seq()
            self._db.execute(
                "INSERT INTO conversations "
                "(id, title, created_at, updated_at, model, pinned, messages, "
                "deleted_at, seq) VALUES (?, '', 0, 0, '', 0, '[]', ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title = '', messages = '[]', pinned = 0, "
                "deleted_at = excluded.deleted_at, seq = excluded.seq",
                (conversation_id, deleted_at, seq),
            )
            self._db.commit()
        return deleted_at

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _seq_courant(self) -> int:
        row = self._db.execute(
            "SELECT valeur FROM compteur WHERE nom = 'seq'"
        ).fetchone()
        return int(row["valeur"]) if row is not None else 0

    def _prochain_seq(self) -> int:
        self._db.execute("UPDATE compteur SET valeur = valeur + 1 WHERE nom = 'seq'")
        return self._seq_courant()

    def _ecrire(self, conv: Dict[str, Any]) -> None:
        seq = self._prochain_seq()
        self._db.execute(
            "INSERT INTO conversations "
            "(id, title, created_at, updated_at, model, pinned, messages, "
            "deleted_at, seq) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title = excluded.title, created_at = excluded.created_at, "
            "updated_at = excluded.updated_at, model = excluded.model, "
            "pinned = excluded.pinned, messages = excluded.messages, "
            "deleted_at = NULL, seq = excluded.seq",
            (
                conv["id"],
                sans_substituts(conv["title"]),
                int(conv["createdAt"]),
                int(conv["updatedAt"]),
                sans_substituts(conv["model"]),
                1 if conv.get("pinned") else 0,
                sans_substituts(
                    json.dumps(conv.get("messages", []), ensure_ascii=False)
                ),
                seq,
            ),
        )
        self._db.commit()

    def _purge_old_tombstones(self) -> None:
        seuil = _now_ms() - _RETENTION_TOMBALES_JOURS * 24 * 3600 * 1000
        with self._lock:
            self._db.execute(
                "DELETE FROM conversations "
                "WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (seuil,),
            )
            self._db.commit()

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> Dict[str, Any]:
        # camelCase sur le fil, TOUJOURS : un champ snake_case se lit
        # ``undefined`` côté TypeScript, en silence (règle du dépôt).
        return {
            "id": row["id"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "model": row["model"],
            "pinned": bool(row["pinned"]),
            "messages": json.loads(row["messages"]),
        }
