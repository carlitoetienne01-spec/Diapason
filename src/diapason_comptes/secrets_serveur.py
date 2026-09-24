"""Les secrets du serveur, et la configuration lue au démarrage.

Conception : ``docs/development/compte-chiffre.md`` §3.2.

``/etc/diapason/comptes.env`` est généré SUR le VPS (``umask 077``) et ne
transite jamais par le Mac. systemd le passe en environnement ; ce module
le lit, refuse de démarrer s'il manque un secret ou si un secret n'a pas
32 o, et ne journalise que la PRÉSENCE de chacun.

Trois familles de secrets :

- ``COMPTES_POIVRE_<v>`` — HMAC : vérificateurs, index de courriel, codes,
  limites. Chaque usage a son domaine (``"auth\\0"``, ``"courriel\\0"``…) :
  un HMAC calculé pour l'un ne vaut jamais pour l'autre.
- ``COMPTES_CLE_REPOS_<v>`` — AES-256-GCM au repos : courriel, enveloppes,
  trousseau, journal. AAD = ``accountId|colonne`` : une enveloppe recopiée
  d'un compte à l'autre, ou d'une colonne à l'autre, ne s'ouvre plus.
- ``COMPTES_GRAINE_SEL`` — le ``kdfSalt`` déterministe. JAMAIS tournée.

Chaque valeur poivrée ou sur-chiffrée porte en tête l'octet de la version
de secret qui l'a produite. Une rotation (``COMPTES_SECRETS_VERSION`` + 1)
ne rend donc rien illisible : l'ancienne version reste déclarée le temps
que chaque compte soit réécrit à sa connexion suivante (§3.2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_journal = logging.getLogger("diapason_comptes.secrets")

LONGUEUR_SECRET = 32
LONGUEUR_NONCE = 12

VAR_VERSION = "COMPTES_SECRETS_VERSION"
PREFIXE_POIVRE = "COMPTES_POIVRE_"
PREFIXE_CLE_REPOS = "COMPTES_CLE_REPOS_"
VAR_GRAINE_SEL = "COMPTES_GRAINE_SEL"

# Un octet de version en tête de chaque valeur : 255 rotations suffisent à
# la vie du service, et un octet de plus par colonne ne coûte rien.
VERSION_MAX = 255


class SecretsAbsents(RuntimeError):
    """Le service refuse de démarrer. Le message nomme la variable fautive,
    jamais sa valeur : il finit dans journald, que l'on garde 7 jours."""


def _decoder_secret(env: Mapping[str, str], nom: str) -> bytes:
    brut = env.get(nom)
    if brut is None or not brut.strip():
        raise SecretsAbsents(f"{nom} manque dans l'environnement (comptes.env)")
    texte = brut.strip()
    try:
        # ``validate=True`` : sans lui, ``b64decode`` saute en silence tout
        # caractère hors alphabet, et un secret tronqué au copier-coller
        # pourrait encore faire 32 o — mais d'autres 32 o.
        octets = base64.b64decode(texte + "=" * (-len(texte) % 4), validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretsAbsents(f"{nom} n'est pas du base64") from exc
    if len(octets) != LONGUEUR_SECRET:
        raise SecretsAbsents(f"{nom} doit faire {LONGUEUR_SECRET} o une fois décodé")
    return octets


@dataclass(frozen=True)
class SecretsServeur:
    """Les secrets déchiffrés. ``repr`` ne montre que les versions."""

    version: int
    poivres: Mapping[int, bytes] = field(repr=False)
    cles_repos: Mapping[int, bytes] = field(repr=False)
    graine_sel: bytes = field(repr=False)

    # --- HMAC poivrés -------------------------------------------------

    def _poivre(self, version: int) -> bytes:
        try:
            return self.poivres[version]
        except KeyError as exc:
            raise SecretsAbsents(
                f"{PREFIXE_POIVRE}{version} n'est plus déclaré"
            ) from exc

    def mac(
        self, domaine: bytes, donnees: bytes, *, version: int | None = None
    ) -> bytes:
        """``version ‖ HMAC(POIVRE_v, domaine ‖ "\\0" ‖ données)``."""
        v = self.version if version is None else version
        brut = hmac.new(self._poivre(v), domaine + b"\0" + donnees, hashlib.sha256)
        return bytes([v]) + brut.digest()

    def macs_candidats(self, domaine: bytes, donnees: bytes) -> list[bytes]:
        """Un MAC par version de poivre encore déclarée, la courante d'abord.

        Pour retrouver un compte dont l'index a été calculé avant une
        rotation. Le nombre de HMAC ne dépend que des versions déclarées,
        jamais de l'existence du compte : aucune différence de temps.
        """
        versions = [self.version] + sorted(
            (v for v in self.poivres if v != self.version), reverse=True
        )
        return [self.mac(domaine, donnees, version=v) for v in versions]

    def verifier_mac(
        self, stocke: bytes | None, domaine: bytes, donnees: bytes
    ) -> bool:
        """Compare en temps constant ; ``False`` pour une valeur absente."""
        if not stocke or stocke[0] not in self.poivres:
            return False
        attendu = self.mac(domaine, donnees, version=stocke[0])
        return hmac.compare_digest(stocke, attendu)

    # --- Index, vérificateurs, sel ------------------------------------

    def indices_courriel(self, courriel: str) -> list[bytes]:
        """``HMAC(POIVRE, "courriel\\0" ‖ E)`` sous chaque version déclarée."""
        return self.macs_candidats(b"courriel", courriel.encode("utf-8"))

    def index_courriel(self, courriel: str) -> bytes:
        return self.mac(b"courriel", courriel.encode("utf-8"))

    def verificateur_auth(self, compte_id: str, auth_key: bytes) -> bytes:
        """``HMAC(POIVRE, "auth\\0" ‖ accountId ‖ authKey)`` (§2.2).

        ``accountId`` est un UUID de 36 caractères : la concaténation sans
        séparateur reste sans ambiguïté.
        """
        return self.mac(b"auth", compte_id.encode("ascii") + auth_key)

    def verificateur_recuperation(self, compte_id: str, auth_key: bytes) -> bytes:
        return self.mac(b"recuperation", compte_id.encode("ascii") + auth_key)

    def kdf_salt(self, courriel: str) -> bytes:
        """Le ``kdfSalt`` déterministe : ``HMAC(GRAINE_SEL, "sel\\0" ‖ E)``.

        Le §2.2 écrit ``HMAC(GRAINE_SEL, "sel\\0" ‖ HMAC(POIVRE, …))`` ; le
        poivre, lui, TOURNE (§3.2). Avec cette formule, une rotation aurait
        changé le sel des adresses INCONNUES pendant que celui des comptes,
        gardé dans ``sel_kdf``, restait fixe : sonder ``login/params`` avant
        et après une rotation aurait séparé les adresses inscrites des
        autres — ce que le §2.2 interdit en toutes lettres (24/09/2026). Le
        sel ne dépend donc que de la graine, jamais tournée.
        """
        return hmac.new(
            self.graine_sel, b"sel\0" + courriel.encode("utf-8"), hashlib.sha256
        ).digest()

    # --- Sur-chiffrement au repos -------------------------------------

    def sceller(self, compte_id: str, colonne: str, donnees: bytes) -> bytes:
        """``version ‖ nonce ‖ AES-256-GCM(CLE_REPOS_v, AAD = accountId|colonne)``."""
        nonce = os.urandom(LONGUEUR_NONCE)
        aad = f"{compte_id}|{colonne}".encode()
        chiffre = AESGCM(self.cles_repos[self.version]).encrypt(nonce, donnees, aad)
        return bytes([self.version]) + nonce + chiffre

    def ouvrir(self, compte_id: str, colonne: str, blob: bytes) -> bytes:
        version = blob[0]
        try:
            cle = self.cles_repos[version]
        except KeyError as exc:
            raise SecretsAbsents(
                f"{PREFIXE_CLE_REPOS}{version} n'est plus déclaré"
            ) from exc
        nonce = blob[1 : 1 + LONGUEUR_NONCE]
        aad = f"{compte_id}|{colonne}".encode()
        return AESGCM(cle).decrypt(nonce, blob[1 + LONGUEUR_NONCE :], aad)

    def version_de(self, blob: bytes | None) -> int | None:
        return None if not blob else blob[0]


def charger_secrets(env: Mapping[str, str]) -> SecretsServeur:
    """Lit ``comptes.env`` tel que systemd l'a passé en environnement.

    La version courante doit avoir son poivre ET sa clé de repos ; les
    versions antérieures déclarées sont gardées pour lire ce qui n'a pas
    encore été réécrit.
    """
    brut = env.get(VAR_VERSION)
    if brut is None or not brut.strip().isdigit():
        raise SecretsAbsents(f"{VAR_VERSION} manque ou n'est pas un entier")
    version = int(brut.strip())
    if not 1 <= version <= VERSION_MAX:
        raise SecretsAbsents(f"{VAR_VERSION} doit être entre 1 et {VERSION_MAX}")

    def famille(prefixe: str) -> dict[int, bytes]:
        motif = re.compile(re.escape(prefixe) + r"([0-9]{1,3})")
        trouves: dict[int, bytes] = {}
        for nom in env:
            correspondance = motif.fullmatch(nom)
            if correspondance and 1 <= int(correspondance.group(1)) <= VERSION_MAX:
                trouves[int(correspondance.group(1))] = _decoder_secret(env, nom)
        if version not in trouves:
            raise SecretsAbsents(f"{prefixe}{version} manque dans l'environnement")
        return trouves

    return SecretsServeur(
        version=version,
        poivres=famille(PREFIXE_POIVRE),
        cles_repos=famille(PREFIXE_CLE_REPOS),
        graine_sel=_decoder_secret(env, VAR_GRAINE_SEL),
    )


def journaliser_presence(secrets: SecretsServeur) -> None:
    """La PRÉSENCE de chaque secret, jamais sa valeur (§3.2)."""
    _journal.info(
        "secrets présents : version %d ; poivres %s ; clés de repos %s ; graine du sel",
        secrets.version,
        sorted(secrets.poivres),
        sorted(secrets.cles_repos),
    )


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

VAR_BASE = "COMPTES_BASE"
VAR_JOURNAL = "COMPTES_JOURNAL"
VAR_INSCRIPTIONS = "INSCRIPTIONS_OUVERTES"
VAR_BUDGET_CODES = "COMPTES_BUDGET_CODES_JOUR"
VAR_BUDGET_SECURITE = "COMPTES_BUDGET_SECURITE_JOUR"

# §3.3 : ``StateDirectory=diapason`` donne ``/var/lib/diapason``.
BASE_DEFAUT = Path("/var/lib/diapason/comptes.db")
JOURNAL_DEFAUT = Path("/var/lib/diapason/evenements.jsonl")

# D10 (décision par défaut du 24/09/2026). 256 Mio par compte : des années
# de conversations texte, et 1 000 comptes pleins tiennent encore sous la
# garde de 2 Go… si peu d'entre eux sont pleins, ce que « places limitées »
# (§5) dit en clair.
QUOTA_COMPTE_OCTETS = 256 * 1024 * 1024
# 2 Go pour la base, 20 Go libres sur « / » : 20 Go couvrent la marge de
# sauvegarde du §3.9 (taille × 1,2 + 15 Go) et laissent le reste des 91 Go
# libres relevés à Flashprime. Unités décimales, comme ``df -H`` et comme
# le panneau Hostinger les affichent.
GARDE_BASE_OCTETS = 2 * 10**9
GARDE_DISQUE_LIBRE_OCTETS = 20 * 10**9


@dataclass(frozen=True)
class Configuration:
    """Ce qui n'est pas secret. Les budgets de courriel n'ont PAS de valeur
    par défaut : ils se fixent d'après l'offre Resend (D12, étape 0), et un
    chiffre inventé ici serait une promesse faite à l'aveugle."""

    chemin_base: Path
    chemin_journal: Path
    budget_codes_jour: int
    budget_securite_jour: int
    inscriptions_ouvertes: bool = False
    quota_compte_octets: int = QUOTA_COMPTE_OCTETS
    garde_base_octets: int = GARDE_BASE_OCTETS
    garde_disque_libre_octets: int = GARDE_DISQUE_LIBRE_OCTETS
    chemin_disque: Path = Path("/")


def _entier_positif(env: Mapping[str, str], nom: str) -> int:
    brut = env.get(nom, "").strip()
    if not brut.isdigit() or int(brut) < 1:
        raise SecretsAbsents(f"{nom} manque ou n'est pas un entier positif")
    return int(brut)


def charger_configuration_chemins(env: Mapping[str, str]) -> tuple[Path, Path]:
    """``(comptes.db, evenements.jsonl)`` : ce dont ``diapason-comptes-admin``
    a besoin, sans les budgets de courriel qu'il n'envoie jamais."""
    return (
        Path(env.get(VAR_BASE, str(BASE_DEFAUT))),
        Path(env.get(VAR_JOURNAL, str(JOURNAL_DEFAUT))),
    )


def charger_configuration(env: Mapping[str, str]) -> Configuration:
    ouvertes = env.get(VAR_INSCRIPTIONS, "0").strip()
    if ouvertes not in {"0", "1"}:
        raise SecretsAbsents(f"{VAR_INSCRIPTIONS} vaut 0 ou 1")
    chemin_base, chemin_journal = charger_configuration_chemins(env)
    return Configuration(
        chemin_base=chemin_base,
        chemin_journal=chemin_journal,
        budget_codes_jour=_entier_positif(env, VAR_BUDGET_CODES),
        budget_securite_jour=_entier_positif(env, VAR_BUDGET_SECURITE),
        # Déployé FERMÉ (§3.5) : l'absence de la variable vaut 0.
        inscriptions_ouvertes=ouvertes == "1",
    )
