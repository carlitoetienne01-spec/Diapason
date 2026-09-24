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
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from diapason.core.paths import get_config_dir

logger = logging.getLogger(__name__)

# 30 jours avant de purger une pierre tombale : assez pour qu'un appareil
# éteint des semaines — pc-bureau — se rallume, tire l'historique et
# apprenne la suppression avant qu'elle ne disparaisse du registre. Plus
# court, la conversation supprimée « ressusciterait » depuis la copie
# locale de l'appareil revenu ; plus long n'achète rien, la fusion est
# idempotente.
#
# Ces 30 jours ne suffisent plus dès qu'un compte synchronise (24/09/2026) :
# un appareil éteint 40 jours n'a jamais PU confirmer la suppression au
# serveur de compte, et la purger à l'âge seul la rendait à la première
# copie distante tirée. Avec un compte, l'âge est nécessaire mais pas
# suffisant — ``peut_purger`` (voir ``ConversationsStore``) a le dernier mot.
_RETENTION_TOMBALES_JOURS = 30

# Signatures des deux crochets posés par le moteur de synchronisation
# (docs/development/compte-chiffre.md §4.3 et §4.6). Tous deux valent None
# tant qu'aucun compte n'existe, et le magasin se comporte alors exactement
# comme avant eux.
PeutPurger = Callable[[str, int], bool]
SurEcriture = Callable[[int], None]

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

# Quand une tombale DISTANTE a été posée ici, en heure locale. Sans elle,
# l'âge de purge se mesurait sur ``deleted_at``, la date de l'appareil qui
# a supprimé : une suppression faite hors ligne sur pc-bureau et arrivée
# 40 jours plus tard était « vieille » dès son arrivée, purgée au
# redémarrage suivant avant qu'une vue fermée l'ait apprise — et la
# première retouche de cette vue recréait la conversation (contre-épreuve
# du 24/09/2026). Les 30 jours de rétention doivent courir sur l'horloge
# de CE magasin. Table à part plutôt que colonne : le dépôt n'a aucune
# migration SQLite, et une table ``IF NOT EXISTS`` se crée à l'ouverture
# d'une base ancienne. Une tombale locale n'y a pas de ligne : ``delete``
# la date déjà au moins « maintenant ».
_CREATE_TOMBALES_POSEES = """\
CREATE TABLE IF NOT EXISTS tombales_posees (
    id          TEXT    PRIMARY KEY,
    posee_le_ms INTEGER NOT NULL
);
"""

# Le plus grand entier que SQLite stocke (int64). Une date au-delà levait
# OverflowError : ``delete`` d'une copie poussée avec ``updatedAt =
# 2**63 - 1`` calculait ``updatedAt + 1`` et la route répondait 500 — la
# conversation devenait impossible à supprimer (contre-épreuve du
# 24/09/2026).
_ENTIER_SQLITE_MAX = 2**63 - 1

# §2.10 : l'état du compte vit dans ``get_config_dir()/compte/etat.key``,
# à côté de ``conversations.db``. Sa présence dit qu'un compte existe.
_ETAT_DU_COMPTE = Path("compte") / "etat.key"

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

    Plusieurs horloges écrivent ici. Les deux vues de cette machine partagent
    la sienne, mais le moteur de synchronisation (compte-chiffre.md §4)
    apporte des copies datées par d'autres appareils, dont l'horloge peut
    avancer ou retarder de plusieurs minutes. ``updatedAt`` / ``deletedAt``
    (ms epoch) ne sont donc pas des heures comparables d'un appareil à
    l'autre ; ce sont des dates de Lamport par conversation (§4.9) :

    - chaque vue date une mutation ``max(maintenant, précédente + 1)`` sur
      une copie déjà fusionnée (``store.ts``) : une écriture qui en a VU une
      autre la dépasse toujours, quelle que soit l'horloge qui a daté la
      première ;
    - :meth:`delete` date sa tombale au-dessus de la copie stockée qu'elle
      efface : une suppression l'emporte sur ce qu'elle a vu, même si cette
      copie venait d'un appareil en avance d'un jour ;
    - seules deux écritures vraiment concurrentes (aucune n'a vu l'autre) se
      départagent sur l'horloge brute, et l'appareil en avance gagne.

    Ce que ce dernier point coûte, dit tel quel : entre deux MODIFICATIONS
    concurrentes, les messages s'unissent et seules les métadonnées (titre,
    épingle, modèle) suivent l'horloge en avance. Entre une SUPPRESSION et
    une modification concurrentes, c'est tout ou rien : une tombale datée
    par un appareil en avance de 3 h efface les messages écrits ailleurs
    jusqu'à 3 h APRÈS elle en temps réel (figé par
    ``test_conversations_store.py``). §4.6 promet l'inverse (« une
    modification faite sans avoir vu la suppression ressuscite ») et §4.9
    borne l'effet du décalage aux métadonnées : l'écart est à trancher à
    l'étape 10, et la tombale devra alors porter ce qu'elle a vu.

    Rien ne l'affiche encore. L'étape 10 (compte-chiffre.md §4.9) ajoutera
    ``clockSkewMs``, mesuré par le moteur sur l'en-tête ``Date``, et un
    bandeau au-delà de 120 s ; aujourd'hui aucun des deux n'existe.

    ``seq`` est l'ORDRE dans lequel ce magasin apprend les choses — sans
    rapport avec ces dates, et jamais comparé d'un appareil à l'autre.

    Deux crochets branchent le moteur ; aucun code ne les pose encore
    (étape 10). ``sur_ecriture(seq)`` est appelé après chaque écriture pour
    réveiller le moteur (§4.3) ; on peut le poser à tout moment.
    ``peut_purger(id, deleted_at)`` borne la purge des tombales par la
    confirmation du serveur de compte (§4.6) ; il n'agit qu'au moment d'une
    purge, et le constructeur en fait une. Le moteur qui le pose après
    l'ouverture (``create_app`` ouvre le magasin sans crochet) appelle donc
    :meth:`purger_tombales` ensuite. Entre-temps, si un compte existe
    (``compte/etat.key`` à côté de la base), la purge sans crochet ne purge
    RIEN : l'âge seul n'autorise plus rien dès qu'un compte synchronise.
    """

    def __init__(
        self,
        db_path: str | Path = "",
        *,
        peut_purger: Optional[PeutPurger] = None,
        sur_ecriture: Optional[SurEcriture] = None,
    ) -> None:
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
        self.peut_purger: Optional[PeutPurger] = peut_purger
        self.sur_ecriture: Optional[SurEcriture] = sur_ecriture
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
        self._db.execute(_CREATE_TOMBALES_POSEES)
        self._db.execute(
            "INSERT OR IGNORE INTO compteur (nom, valeur) VALUES ('seq', 0)"
        )
        self._db.commit()
        self.purger_tombales()

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

        Toute écriture réelle appelle ``sur_ecriture`` ; une fusion sans
        effet, non.
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
            seq = self._ecrire(a_stocker)
            stored = self._db.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv["id"],)
            ).fetchone()
        self._signaler_ecriture(seq)
        return {"conversation": self._row_to_conversation(stored)}

    def appliquer_tombale(
        self, conversation_id: str, deleted_at: int
    ) -> Dict[str, Any]:
        """Applique une suppression venue d'un autre appareil (§4.6).

        La règle est celle d':meth:`upsert`, à la lettre, vue de l'autre
        côté : la tombale gagne si ``deleted_at >= updatedAt`` de la copie
        stockée. Une tombale distante ANCIENNE — l'autre appareil a supprimé
        une version que celle-ci a déjà dépassée — perd : effacer une
        modification que la suppression n'avait pas vue défait un choix
        postérieur de l'utilisateur.

        - vivante plus récente que la tombale : rien n'est écrit, rend
          ``{"conversation": <copie stockée>}`` ;
        - vivante plus ancienne, ou inconnue : tombale posée à ``deleted_at``
          (la date de l'appareil qui a supprimé, pas la nôtre — sinon la
          même suppression porterait une date par appareil et les copies ne
          convergeraient jamais), title et messages vidés ;
        - déjà tombale : garde la plus haute des deux dates ; n'écrit que si
          la distante est plus haute.

        Rend ``{"deleted": True, "deletedAt": int}`` dans les deux derniers
        cas, la forme d':meth:`upsert`.

        Une tombale posée ici retient aussi l'heure LOCALE de sa pose : c'est
        elle, et non ``deleted_at``, qui fait courir les 30 jours de
        rétention (voir ``_CREATE_TOMBALES_POSEES``).
        """
        if not isinstance(conversation_id, str) or not conversation_id:
            raise TypeError("conversation_id doit être une chaîne non vide")
        # Ni bool (True vaut 1 ms), ni float : une date flottante finirait
        # dans une enveloppe signée, et Python et Dart ne l'écrivent pas
        # pareil (CLAUDE.md §4, règle 1).
        if isinstance(deleted_at, bool) or not isinstance(deleted_at, int):
            raise TypeError(
                f"deleted_at doit être un entier, pas {type(deleted_at).__name__}"
            )
        # Hors de [0, int64] SQLite lève OverflowError au milieu de
        # l'écriture ; refusée ici, la date ne touche pas la base.
        if not 0 <= deleted_at <= _ENTIER_SQLITE_MAX:
            raise ValueError(
                f"deleted_at doit être dans [0, {_ENTIER_SQLITE_MAX}], pas {deleted_at}"
            )
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row is not None and row["deleted_at"] is None:
                if deleted_at < row["updated_at"]:
                    return {"conversation": self._row_to_conversation(row)}
            elif row is not None and row["deleted_at"] >= deleted_at:
                return {"deleted": True, "deletedAt": row["deleted_at"]}
            seq = self._poser_tombale(conversation_id, deleted_at, _now_ms())
        self._signaler_ecriture(seq)
        return {"deleted": True, "deletedAt": deleted_at}

    def delete(self, conversation_id: str) -> int:
        """Pose une pierre tombale et rend son ``deletedAt`` (ms).

        Idempotent, même pour un id inconnu : re-supprimer ce qui n'existe
        pas doit réussir, sinon deux appareils qui suppriment la même
        conversation verraient le second échouer pour rien. La tombale vide
        title et messages — une suppression qui garde le texte n'est pas
        une suppression.

        Datée ``max(maintenant, tombale existante, updatedAt stocké + 1)``.
        Jusqu'au 24/09/2026 elle l'était ``max(maintenant, existante)`` : une
        copie arrivée d'un appareil en avance d'une heure portait un
        ``updatedAt`` plus haut que « maintenant », la tombale perdait
        contre la copie même qu'elle venait d'effacer, et la prochaine
        poussée de cette copie ressuscitait la conversation. Sur une seule
        horloge, ``updatedAt + 1`` ne dépasse « maintenant » que dans la
        milliseconde d'une rafale : la date reste celle d'avant.

        À la borne d'int64, ``updatedAt + 1`` ne se stocke plus : la tombale
        prend alors ``updatedAt`` lui-même, qui gagne encore puisque la
        règle d'upsert donne l'égalité à la suppression.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT deleted_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            existing = row["deleted_at"] if row is not None else None
            vue = 0
            if row is not None:
                stockee = row["updated_at"]
                vue = stockee + 1 if stockee < _ENTIER_SQLITE_MAX else stockee
            maintenant = _now_ms()
            deleted_at = max(maintenant, existing or 0, vue)
            seq = self._poser_tombale(conversation_id, deleted_at, maintenant)
        self._signaler_ecriture(seq)
        return deleted_at

    def purger_tombales(self) -> int:
        """Purge les tombales de plus de 30 jours que la règle autorise ;
        rend le nombre de tombales purgées.

        Le constructeur l'appelle. Jusqu'au 24/09/2026 la purge ne vivait
        QUE là : un ``peut_purger`` posé après l'ouverture — ce que fera le
        moteur, puisque ``create_app`` ouvre le magasin sans crochet —
        n'était jamais consulté, et chaque redémarrage purgeait à l'âge seul
        une tombale que le serveur de compte n'avait pas confirmée
        (contre-épreuve du 24/09/2026). Le moteur l'appelle donc après avoir
        posé le crochet.

        - avec ``peut_purger`` : l'âge est nécessaire, le crochet décide
          (§4.6) ; seul ``True`` vaut accord ;
        - sans crochet et sans compte : l'âge suffit, la règle d'avant ;
        - sans crochet mais avec un compte : rien. Le crochet n'est pas
          encore posé, et purger à l'âge seul est précisément le défaut que
          §4.6 interdit.

        L'âge se mesure sur ``max(deleted_at, posée ici)`` : une tombale
        distante déjà vieille à son arrivée a 30 jours pour atteindre les
        vues de cette machine.
        """
        peut_purger = self.peut_purger
        if peut_purger is None and self._compte_present():
            return 0
        seuil = _now_ms() - _RETENTION_TOMBALES_JOURS * 24 * 3600 * 1000
        with self._lock:
            candidates = [
                (ligne["id"], ligne["deleted_at"])
                for ligne in self._db.execute(
                    "SELECT c.id, c.deleted_at FROM conversations AS c "
                    "LEFT JOIN tombales_posees AS p ON p.id = c.id "
                    "WHERE c.deleted_at IS NOT NULL "
                    "AND MAX(c.deleted_at, COALESCE(p.posee_le_ms, 0)) < ?",
                    (seuil,),
                ).fetchall()
            ]
            if peut_purger is None:
                return self._effacer_tombales(candidates)
        # ``peut_purger`` est interrogé HORS du verrou : il lit l'état du
        # moteur (sortants, connus, planchers), et un moteur qui relirait le
        # magasin depuis ce rappel se bloquerait sur notre propre verrou.
        a_purger: List[Tuple[str, int]] = []
        for conversation_id, deleted_at in candidates:
            try:
                # ``is True`` et non la véracité : un rappel qui rend autre
                # chose qu'un booléen (un MagicMock, un objet) ne vaut pas
                # confirmation. Garder une tombale ne coûte que 60 octets ;
                # la purger à tort ressuscite une conversation.
                accord = peut_purger(conversation_id, deleted_at) is True
            except Exception:
                logger.exception(
                    "peut_purger a échoué ; la tombale %s est gardée",
                    conversation_id,
                )
                accord = False
            if accord:
                a_purger.append((conversation_id, deleted_at))
        if not a_purger:
            return 0
        with self._lock:
            return self._effacer_tombales(a_purger)

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

    def _compte_present(self) -> bool:
        if self.chemin == ":memory:":
            return False
        return (Path(self.chemin).parent / _ETAT_DU_COMPTE).exists()

    def _annuler_si_echec(self) -> None:
        # Une écriture qui lève après ``_prochain_seq`` laissait la
        # transaction ouverte : le compteur incrémenté était visible de
        # ``list`` sur cette connexion, puis commité par l'écriture suivante
        # (contre-épreuve du 24/09/2026). Rien de ce qui a échoué ne reste.
        self._db.rollback()

    def _poser_tombale(
        self, conversation_id: str, deleted_at: int, maintenant: int
    ) -> int:
        """Écrit la tombale sous le verrou et rend son numéro d'écriture.

        ``maintenant`` est l'heure locale que l'appelant a déjà lue :
        relue ici, elle dépasserait d'une milliseconde la ``deleted_at``
        que :meth:`delete` venait d'y aligner, et chaque suppression locale
        aurait gagné une ligne ``tombales_posees`` inutile.
        """
        try:
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
            if deleted_at < maintenant:
                # Plus vieille que son arrivée : c'est l'heure de pose qui
                # fera courir la rétention.
                self._db.execute(
                    "INSERT OR REPLACE INTO tombales_posees (id, posee_le_ms) "
                    "VALUES (?, ?)",
                    (conversation_id, maintenant),
                )
            else:
                self._db.execute(
                    "DELETE FROM tombales_posees WHERE id = ?", (conversation_id,)
                )
            self._db.commit()
        except BaseException:
            self._annuler_si_echec()
            raise
        return seq

    def _signaler_ecriture(self, seq: int) -> None:
        """Appelle ``sur_ecriture`` HORS du verrou, après le commit.

        Hors du verrou : le crochet peut relire le magasin (le moteur le
        fera) et un ``threading.Lock`` non réentrant se bloquerait sur
        lui-même. Après le commit : un réveil qui précède l'écriture ferait
        exporter l'état d'avant, et le moteur se rendormirait sur une
        écriture qu'il n'a pas vue.
        """
        crochet = self.sur_ecriture
        if crochet is None:
            return
        try:
            crochet(seq)
        except Exception:
            # L'écriture est déjà commitée : faire échouer la route dirait
            # au client « non enregistré » alors que ça l'est (§100). Le
            # moteur la retrouvera au prochain export, le seq l'y attend.
            logger.exception("sur_ecriture a échoué après l'écriture n°%d", seq)

    def _ecrire(self, conv: Dict[str, Any]) -> int:
        try:
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
            # Ressuscitée : l'heure de pose de son ancienne tombale ne doit
            # pas dater une tombale future.
            self._db.execute("DELETE FROM tombales_posees WHERE id = ?", (conv["id"],))
            self._db.commit()
        except BaseException:
            self._annuler_si_echec()
            raise
        return seq

    def _effacer_tombales(self, a_purger: List[Tuple[str, int]]) -> int:
        """Efface ces tombales sous le verrou déjà tenu ; rend leur nombre.

        La même tombale seulement (``AND deleted_at = ?``) : entre la
        lecture des candidates et ici, ``peut_purger`` a tourné hors du
        verrou, et une poussée a pu ressusciter la conversation ou une
        suppression la redater. L'accord donné ne portait pas sur ce nouvel
        état — sans cette garde, la purge emportait une conversation VIVANTE.
        """
        if not a_purger:
            return 0
        avant = self._db.total_changes
        try:
            self._db.executemany(
                "DELETE FROM conversations "
                "WHERE id = ? AND deleted_at IS NOT NULL AND deleted_at = ?",
                a_purger,
            )
            purgees = self._db.total_changes - avant
            self._db.execute(
                "DELETE FROM tombales_posees WHERE id NOT IN "
                "(SELECT id FROM conversations WHERE deleted_at IS NOT NULL)"
            )
            self._db.commit()
        except BaseException:
            self._annuler_si_echec()
            raise
        return purgees

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
