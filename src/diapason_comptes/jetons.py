"""Sessions, codes à six chiffres et jetons temporaires.

Conception : ``docs/development/compte-chiffre.md`` §3.3, §3.5 et §3.7.

Le serveur ne garde d'un jeton que son SHA-256 (motif ``vie/sync.py``) :
une copie de ``comptes.db`` ne donne aucune session. D'un code, il ne garde
qu'un HMAC poivré : six chiffres se devinent en un million d'essais, un
SHA-256 nu les rendrait tous en une seconde à qui vole la base.

Consommation atomique : un code ou un jeton est consommé par UN SEUL
``UPDATE … WHERE consomme_ms IS NULL AND expire_ms >= ?`` (modèle
``mesh/registry.py``). Deux requêtes simultanées avec le même code : une
seule voit ``rowcount == 1``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from dataclasses import dataclass

from diapason_comptes.base import JOUR_MS, jour
from diapason_comptes.secrets_serveur import SecretsServeur
from diapason_comptes.validation import PREFIXE_SESSION, b64url, de_b64url

# ----------------------------------------------------------------------
# Durées
# ----------------------------------------------------------------------

# §3.7 : 90 jours d'inactivité, glissants. Un portable rangé un trimestre
# redemande le mot de passe ; un appareil utilisé chaque semaine, jamais.
DUREE_SESSION_MS = 90 * JOUR_MS
# « Sessions expirées : purgées dans login » (§3.1). Purger à l'expiration
# même ferait répondre ``sessionRevoked`` à un appareil revenu le lendemain
# — et ``sessionRevoked`` efface l'AMK mémorisée (§3.7), là où
# ``sessionExpired`` redemande seulement le mot de passe. Trente jours de
# grâce gardent la bonne réponse pour un retour tardif.
GRACE_PURGE_SESSION_MS = 30 * JOUR_MS
# §3.5 : six chiffres, 15 min, 5 essais. 5 essais sur 10^6 : une chance
# sur 200 000 par code, et au plus 10 codes par adresse et par jour.
DUREE_CODE_MS = 15 * 60_000
ESSAIS_CODE_MAX = 5
# Le jeton d'inscription vit entre ``verify`` et ``complete`` : le temps de
# choisir un mot de passe, d'étirer Argon2id et de recopier la clé de
# récupération. 30 min, comme ``R`` en mémoire du serveur local (§2.7).
DUREE_JETON_INSCRIPTION_MS = 30 * 60_000
# §3.4 : 10 min, à usage unique, entre ``recovery/unwrap`` et
# ``vault/commit``.
DUREE_JETON_RECUPERATION_MS = 10 * 60_000

# Au plus 50 sessions par compte. ``/login`` en crée une à chaque appel ;
# sans plafond, un titulaire qui boucle faisait grossir ``sessions`` et la
# réponse de ``GET /sessions`` sans limite (24/09/2026). Une personne a
# rarement plus de dix appareils : 50 laisse cinq réinstallations de chacun
# dans les 90 jours qu'une session met à expirer.
SESSIONS_MAX_PAR_COMPTE = 50

PREFIXE_INSCRIPTION = "dpi1_"
PREFIXE_RECUPERATION = "dpr1_"

BUTS_CODE = ("inscription", "coffre", "reinitialisation")


def empreinte(jeton: str) -> bytes:
    return hashlib.sha256(jeton.encode("ascii")).digest()


# ----------------------------------------------------------------------
# Sessions
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    id: str
    compte_id: str
    jeton_hash: bytes


class SessionRefusee(Exception):
    """``sessionRevoked`` ou ``sessionExpired`` (§3.4)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def creer_session(
    conn: sqlite3.Connection, compte_id: str, maintenant: int
) -> tuple[str, str]:
    """Rend ``(sessionId, sessionToken)`` ; seul le SHA-256 du jeton reste."""
    session_id = str(uuid.uuid4())
    jeton = PREFIXE_SESSION + b64url(secrets.token_bytes(32))
    conn.execute(
        "INSERT INTO sessions (id, compte_id, jeton_hash, nom_chiffre, cree_jour, "
        "vu_jour, expire_ms) VALUES (?, ?, ?, NULL, ?, ?, ?)",
        (
            session_id,
            compte_id,
            empreinte(jeton),
            jour(maintenant),
            jour(maintenant),
            maintenant + DUREE_SESSION_MS,
        ),
    )
    return session_id, jeton


def authentifier(
    conn: sqlite3.Connection, jeton: str | None, maintenant: int
) -> Session:
    """La session du jeton, prolongée ; sinon ``SessionRefusee``.

    Un jeton inconnu vaut ``sessionRevoked`` : il a été révoqué, purgé, ou
    son compte supprimé, et dans tous ces cas l'appareil doit effacer ce
    qu'il garde (§3.7). Le schéma ne garde aucune tombale de session, si
    bien que ``accountDeleted`` ne se distingue pas ici d'une révocation.
    """
    if jeton is None:
        raise SessionRefusee("sessionRevoked")
    hash_ = empreinte(jeton)
    ligne = conn.execute(
        "SELECT id, compte_id, vu_jour, expire_ms FROM sessions WHERE jeton_hash = ?",
        (hash_,),
    ).fetchone()
    if ligne is None:
        raise SessionRefusee("sessionRevoked")
    session_id, compte_id, vu, expire_ms = ligne
    if expire_ms < maintenant:
        raise SessionRefusee("sessionExpired")
    # Une écriture par jour et par session, pas une par requête : ``vu_jour``
    # n'a que le jour, et la prolongation d'un jour de plus ne change rien
    # aux 90 jours.
    if vu != jour(maintenant):
        conn.execute(
            "UPDATE sessions SET vu_jour = ?, expire_ms = ? WHERE id = ?",
            (jour(maintenant), maintenant + DUREE_SESSION_MS, session_id),
        )
    return Session(id=session_id, compte_id=compte_id, jeton_hash=hash_)


def revoquer_sessions(
    conn: sqlite3.Connection, compte_id: str, *, sauf: str | None = None
) -> list[bytes]:
    """Supprime les sessions du compte (sauf une) et rend leurs hachés, que
    le journal d'événements garde pour une restauration (§3.3)."""
    lignes = conn.execute(
        "SELECT id, jeton_hash FROM sessions WHERE compte_id = ?", (compte_id,)
    ).fetchall()
    revoques = [hash_ for id_, hash_ in lignes if id_ != sauf]
    conn.execute(
        "DELETE FROM sessions WHERE compte_id = ? AND id IS NOT ?", (compte_id, sauf)
    )
    return revoques


def borner_sessions(conn: sqlite3.Connection, compte_id: str) -> None:
    """Garde les ``SESSIONS_MAX_PAR_COMPTE`` sessions vues le plus récemment."""
    conn.execute(
        "DELETE FROM sessions WHERE compte_id = ? AND id NOT IN ("
        "SELECT id FROM sessions WHERE compte_id = ? "
        "ORDER BY vu_jour DESC, cree_jour DESC, rowid DESC LIMIT ?)",
        (compte_id, compte_id, SESSIONS_MAX_PAR_COMPTE),
    )


def purger_sessions_expirees(
    conn: sqlite3.Connection, compte_id: str, maintenant: int
) -> None:
    conn.execute(
        "DELETE FROM sessions WHERE compte_id = ? AND expire_ms < ?",
        (compte_id, maintenant - GRACE_PURGE_SESSION_MS),
    )


def sessions_vues_depuis(
    conn: sqlite3.Connection, compte_id: str, depuis_jour: int
) -> bool:
    ligne = conn.execute(
        "SELECT 1 FROM sessions WHERE compte_id = ? AND vu_jour >= ? LIMIT 1",
        (compte_id, depuis_jour),
    ).fetchone()
    return ligne is not None


# ----------------------------------------------------------------------
# Codes à six chiffres
# ----------------------------------------------------------------------


def _mac_code(secrets_: SecretsServeur, index: bytes, but: str, code: str) -> bytes:
    return secrets_.mac(b"code", index + b"\0" + but.encode() + b"\0" + code.encode())


def purger_expires(conn: sqlite3.Connection, maintenant: int) -> None:
    """« Codes et jetons expirés : purgés à chaque création » (§3.1)."""
    conn.execute("DELETE FROM codes WHERE expire_ms < ?", (maintenant,))
    conn.execute("DELETE FROM jetons_temporaires WHERE expire_ms < ?", (maintenant,))


def nouveau_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def enregistrer_code(
    conn: sqlite3.Connection,
    secrets_: SecretsServeur,
    index: bytes,
    but: str,
    code: str,
    maintenant: int,
) -> None:
    """Remplace tout code antérieur du même but : un seul vivant à la fois,
    avec ses 5 essais remis à zéro."""
    purger_expires(conn, maintenant)
    conn.execute(
        "INSERT OR REPLACE INTO codes (courriel_index, but, code_mac, expire_ms, "
        "essais, consomme_ms) VALUES (?, ?, ?, ?, 0, NULL)",
        (index, but, _mac_code(secrets_, index, but, code), maintenant + DUREE_CODE_MS),
    )


def consommer_code(
    conn: sqlite3.Connection,
    secrets_: SecretsServeur,
    index: bytes,
    but: str,
    code: str,
    maintenant: int,
) -> bool:
    """Vrai si ``code`` est le bon, vivant, et que CETTE requête l'a consommé.

    Le HMAC du code reçu est calculé même quand aucun code n'existe : une
    adresse inconnue coûte le même temps qu'une adresse connue (§3.5).
    """
    recu = _mac_code(secrets_, index, but, code)
    ligne = conn.execute(
        "SELECT code_mac FROM codes WHERE courriel_index = ? AND but = ? "
        "AND consomme_ms IS NULL AND expire_ms >= ? AND essais < ?",
        (index, but, maintenant, ESSAIS_CODE_MAX),
    ).fetchone()
    if ligne is None or not hmac.compare_digest(ligne[0], recu):
        if ligne is not None:
            conn.execute(
                "UPDATE codes SET essais = essais + 1 WHERE courriel_index = ? "
                "AND but = ? AND consomme_ms IS NULL",
                (index, but),
            )
        return False
    curseur = conn.execute(
        "UPDATE codes SET consomme_ms = ? WHERE courriel_index = ? AND but = ? "
        "AND consomme_ms IS NULL AND expire_ms >= ? AND essais < ? AND code_mac = ?",
        (maintenant, index, but, maintenant, ESSAIS_CODE_MAX, recu),
    )
    return curseur.rowcount == 1


# ----------------------------------------------------------------------
# Jetons temporaires (inscription, récupération)
# ----------------------------------------------------------------------


def creer_jeton_inscription(
    conn: sqlite3.Connection,
    secrets_: SecretsServeur,
    index: bytes,
    compte_id: str,
    courriel: str,
    maintenant: int,
) -> str:
    """``dpi1_`` ‖ 32 o d'aléa ‖ l'adresse sur-chiffrée.

    ``signup/complete`` ne reçoit pas l'adresse (§3.4) mais doit la
    sur-chiffrer dans ``courriel_chiffre``. Le schéma n'a pas de colonne
    pour la garder entre ``verify`` et ``complete`` : c'est le jeton
    lui-même qui la porte, scellée sous la clé de repos. Le client la
    connaît déjà ; un tiers ne peut pas l'ouvrir.
    """
    purger_expires(conn, maintenant)
    scelle = secrets_.sceller(compte_id, "signupToken", courriel.encode("utf-8"))
    jeton = PREFIXE_INSCRIPTION + b64url(secrets.token_bytes(32) + scelle)
    conn.execute(
        "INSERT INTO jetons_temporaires (hash, but, courriel_index, compte_id, "
        "expire_ms, consomme_ms) VALUES (?, 'inscription', ?, ?, ?, NULL)",
        (empreinte(jeton), index, compte_id, maintenant + DUREE_JETON_INSCRIPTION_MS),
    )
    return jeton


def invalider_preuves(
    conn: sqlite3.Connection, compte_id: str, courriel_index: bytes
) -> None:
    """Après une rotation ou une réinitialisation : les jetons de
    récupération et les codes du coffre émis AVANT ne prouvent plus rien.

    Jusqu'au 24/09/2026, un jeton de ``recovery/unwrap`` survivait dix
    minutes à la rotation que le propriétaire fait précisément parce que
    sa clé a fuité, et à ``reset/complete`` : l'attaquant le rejouait avec
    des versions faciles à deviner et reprenait le compte.
    """
    conn.execute(
        "DELETE FROM jetons_temporaires WHERE compte_id = ? AND but = 'recuperation'",
        (compte_id,),
    )
    conn.execute(
        "DELETE FROM codes WHERE courriel_index = ? AND but = 'coffre'",
        (courriel_index,),
    )


def creer_jeton_recuperation(
    conn: sqlite3.Connection, index: bytes, compte_id: str, maintenant: int
) -> str:
    purger_expires(conn, maintenant)
    jeton = PREFIXE_RECUPERATION + b64url(secrets.token_bytes(32))
    conn.execute(
        "INSERT INTO jetons_temporaires (hash, but, courriel_index, compte_id, "
        "expire_ms, consomme_ms) VALUES (?, 'recuperation', ?, ?, ?, NULL)",
        (empreinte(jeton), index, compte_id, maintenant + DUREE_JETON_RECUPERATION_MS),
    )
    return jeton


@dataclass(frozen=True)
class JetonConsomme:
    courriel_index: bytes
    compte_id: str
    jeton: str


def consommer_jeton(
    conn: sqlite3.Connection, jeton: object, but: str, maintenant: int
) -> JetonConsomme | None:
    prefixe = PREFIXE_INSCRIPTION if but == "inscription" else PREFIXE_RECUPERATION
    if not isinstance(jeton, str) or not jeton.startswith(prefixe) or len(jeton) > 512:
        return None
    hash_ = empreinte(jeton)
    ligne = conn.execute(
        "SELECT courriel_index, compte_id FROM jetons_temporaires WHERE hash = ? "
        "AND but = ?",
        (hash_, but),
    ).fetchone()
    if ligne is None:
        return None
    curseur = conn.execute(
        "UPDATE jetons_temporaires SET consomme_ms = ? WHERE hash = ? AND but = ? "
        "AND consomme_ms IS NULL AND expire_ms >= ?",
        (maintenant, hash_, but, maintenant),
    )
    if curseur.rowcount != 1:
        return None
    return JetonConsomme(courriel_index=ligne[0], compte_id=ligne[1], jeton=jeton)


def courriel_du_jeton_inscription(
    secrets_: SecretsServeur, jeton: JetonConsomme
) -> str | None:
    octets = de_b64url(jeton.jeton[len(PREFIXE_INSCRIPTION) :])
    if octets is None or len(octets) <= 32:
        return None
    try:
        return secrets_.ouvrir(jeton.compte_id, "signupToken", octets[32:]).decode(
            "utf-8"
        )
    # ``InvalidTag`` vit dans ``cryptography.exceptions``, que ce paquet
    # n'importe pas (D19) : tag refusé et version retirée donnent le même
    # refus, sans rien dire de plus au porteur du jeton.
    except Exception:
        return None
