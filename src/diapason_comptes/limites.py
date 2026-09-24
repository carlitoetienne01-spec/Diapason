"""Délais de connexion, limiteur par IP en mémoire, budgets de courriel.

Conception : ``docs/development/compte-chiffre.md`` §3.3 et §3.5.

AUCUNE IP n'est stockée ni journalisée (D11). Le limiteur par IP vit en
mémoire, sous ``HMAC(POIVRE, préfixe /24 ou /48)`` ; les délais par
(adresse, préfixe) vivent dans ``limites`` sous un HMAC du même genre. Une
copie de la base ne dit donc ni d'où l'on s'est connecté, ni à quelle
adresse appartient un compteur.
"""

from __future__ import annotations

import ipaddress
import sqlite3
import threading
from collections import deque

from diapason_comptes.base import JOUR_MS
from diapason_comptes.secrets_serveur import SecretsServeur

MINUTE_MS = 60_000
HEURE_MS = 3_600_000

# §3.5 : 5 échecs gratuits, puis 2^(n−5) min, plafonnés à 60 min. Cinq
# fautes de frappe ne coûtent rien ; un robot qui essaie mille mots de passe
# par préfixe n'en essaie plus qu'une vingtaine par jour.
ECHECS_GRATUITS = 5
DELAI_PLAFOND_MS = 60 * MINUTE_MS
# §3.5 : plafond lâche par adresse, toutes IP confondues. 100 par jour : bien
# au-delà de ce qu'une personne tape, bien en deçà de ce qu'un botnet
# essaierait. Risque résiduel, dit : quelqu'un qui dispose de nombreux
# préfixes peut bloquer les NOUVELLES connexions d'une adresse une journée ;
# les appareils déjà connectés ne sont pas touchés.
ECHECS_JOUR_ADRESSE = 100
# §3.5 : par IP, en mémoire, 30 échecs par heure.
ECHECS_HEURE_IP = 30

# Familles de compteurs : ``reset/confirm`` et ``reset/complete`` comptent
# AVEC ``/login`` (§3.4), sinon deviner un code de réinitialisation serait un
# second guichet sans délai. ``recovery/unwrap`` a son compteur à part.
FAMILLE_CONNEXION = b"connexion"
FAMILLE_RECUPERATION = b"recuperation"


def prefixe_ip(hote: str | None) -> str:
    """``a.b.c.0/24`` ou ``xxxx:xxxx:xxxx::/48`` — jamais l'adresse entière.

    Un hôte qui n'est pas une IP (le client de test, un socket Unix) vaut
    lui-même : il reste un compteur, simplement moins partagé.
    """
    if not hote:
        return "inconnu"
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError:
        return hote
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    longueur = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{longueur}", strict=False))


def _secondes(ms: int) -> int:
    return max(1, -(-ms // 1000))


class LimiteurConnexions:
    """Délais par (adresse, préfixe) et plafond par adresse, dans ``limites``."""

    def __init__(self, secrets_: SecretsServeur) -> None:
        self._secrets = secrets_

    def _cle_prefixe(self, famille: bytes, courriel: str, prefixe: str) -> bytes:
        return self._secrets.mac(
            b"limite", famille + b"\0" + courriel.encode() + b"\0" + prefixe.encode()
        )

    def _cle_adresse(self, famille: bytes, courriel: str) -> bytes:
        return self._secrets.mac(b"limite-jour", famille + b"\0" + courriel.encode())

    def attente_s(
        self,
        conn: sqlite3.Connection,
        courriel: str,
        prefixe: str,
        maintenant: int,
        famille: bytes = FAMILLE_CONNEXION,
    ) -> int:
        """Secondes à attendre, ou 0. Ne compte rien."""
        cles = (
            self._cle_prefixe(famille, courriel, prefixe),
            self._cle_adresse(famille, courriel),
        )
        ligne = conn.execute(
            "SELECT MAX(bloque_jusqua_ms) FROM limites WHERE cle IN (?, ?)", cles
        ).fetchone()
        jusqua = ligne[0] if ligne and ligne[0] is not None else 0
        return _secondes(jusqua - maintenant) if jusqua > maintenant else 0

    def echec(
        self,
        conn: sqlite3.Connection,
        courriel: str,
        prefixe: str,
        maintenant: int,
        famille: bytes = FAMILLE_CONNEXION,
    ) -> bool:
        """Compte un échec. Vrai si CET échec vient de bloquer l'adresse pour
        la journée : l'appelant envoie alors « connexions bloquées »."""
        # « Compteurs de plus de 24 h : purgés à chaque échec » (§3.1).
        conn.execute(
            "DELETE FROM limites WHERE debut_ms < ? AND bloque_jusqua_ms < ?",
            (maintenant - JOUR_MS, maintenant),
        )
        cle = self._cle_prefixe(famille, courriel, prefixe)
        ligne = conn.execute(
            "SELECT echecs, debut_ms FROM limites WHERE cle = ?", (cle,)
        ).fetchone()
        echecs = (ligne[0] if ligne else 0) + 1
        debut = ligne[1] if ligne else maintenant
        bloque = 0
        if echecs > ECHECS_GRATUITS:
            # 2^(n−5) min, au pied du §3.5 : 2 min au 6e échec. Jusqu'au
            # 24/09/2026, un ``- 1`` de trop donnait 2^(n−6), et chaque délai
            # valait la moitié de ce que la conception promet.
            delai = min(
                MINUTE_MS * 2 ** min(echecs - ECHECS_GRATUITS, 16), DELAI_PLAFOND_MS
            )
            bloque = maintenant + delai
        conn.execute(
            "INSERT OR REPLACE INTO limites (cle, echecs, debut_ms, bloque_jusqua_ms) "
            "VALUES (?, ?, ?, ?)",
            (cle, echecs, debut, bloque),
        )

        cle_jour = self._cle_adresse(famille, courriel)
        ligne = conn.execute(
            "SELECT echecs, debut_ms, bloque_jusqua_ms FROM limites WHERE cle = ?",
            (cle_jour,),
        ).fetchone()
        if ligne is None or ligne[1] < maintenant - JOUR_MS:
            echecs_jour, debut_jour, bloque_jour = 1, maintenant, 0
        else:
            echecs_jour, debut_jour, bloque_jour = ligne[0] + 1, ligne[1], ligne[2]
        vient_de_bloquer = False
        if echecs_jour >= ECHECS_JOUR_ADRESSE and bloque_jour <= maintenant:
            bloque_jour = debut_jour + JOUR_MS
            vient_de_bloquer = True
        conn.execute(
            "INSERT OR REPLACE INTO limites (cle, echecs, debut_ms, bloque_jusqua_ms) "
            "VALUES (?, ?, ?, ?)",
            (cle_jour, echecs_jour, debut_jour, bloque_jour),
        )
        return vient_de_bloquer

    def reussite(
        self,
        conn: sqlite3.Connection,
        courriel: str,
        prefixe: str,
        famille: bytes = FAMILLE_CONNEXION,
    ) -> None:
        """« Une réussite remet à zéro » le compteur (adresse, préfixe) — pas
        le plafond du jour, que l'attaquant a rempli, pas la personne."""
        conn.execute(
            "DELETE FROM limites WHERE cle = ?",
            (self._cle_prefixe(famille, courriel, prefixe),),
        )


class LimiteurIp:
    """30 échecs par heure et par préfixe, EN MÉMOIRE seulement (§3.3)."""

    def __init__(self, secrets_: SecretsServeur) -> None:
        self._secrets = secrets_
        self._verrou = threading.Lock()
        self._echecs: dict[bytes, deque[int]] = {}

    def _cle(self, prefixe: str) -> bytes:
        return self._secrets.mac(b"ip", prefixe.encode())

    def _nettoyer(self, file: deque[int], maintenant: int) -> None:
        while file and file[0] <= maintenant - HEURE_MS:
            file.popleft()

    def attente_s(self, prefixe: str, maintenant: int) -> int:
        with self._verrou:
            file = self._echecs.get(self._cle(prefixe))
            if not file:
                return 0
            self._nettoyer(file, maintenant)
            if len(file) < ECHECS_HEURE_IP:
                return 0
            return _secondes(file[0] + HEURE_MS - maintenant)

    def echec(self, prefixe: str, maintenant: int) -> None:
        with self._verrou:
            # Purge des préfixes muets depuis une heure : sans elle, un
            # balayage d'adresses IPv6 ferait grossir le dictionnaire jusqu'au
            # ``MemoryMax=300M`` du service.
            if len(self._echecs) > 10_000:
                for cle in [
                    c
                    for c, f in self._echecs.items()
                    if not f or f[-1] <= maintenant - HEURE_MS
                ]:
                    del self._echecs[cle]
            file = self._echecs.setdefault(self._cle(prefixe), deque())
            self._nettoyer(file, maintenant)
            file.append(maintenant)


# ----------------------------------------------------------------------
# Portillon des gros corps (§3.1, §4.3)
# ----------------------------------------------------------------------

# Une poussée porte jusqu'à 8 Mio de blobs, soit environ 11 Mio de base64
# (12 Mio chez nginx, §3.9) ; une pièce, 10 Mio ; une page de
# ``sync/changes``, 8 Mio avant encodage. Chacune coûte de 25 à 35 Mio de
# mémoire le temps d'être lue, décodée et réencodée. Les 40 fils de
# Starlette pouvaient en tenir quarante à la fois, soit plus d'un gigaoctet
# sous ``MemoryMax=300M`` : systemd tuait le service au milieu d'une
# transaction (24/09/2026). Quatre passages, 140 Mio au pire, laissent la
# place au reste ; le cinquième reçoit 503 ``serverBusy`` et réessaie.
PASSAGES_LOURDS = 4
ATTENTE_PASSAGE_S = 5


class Portillon:
    """Au plus :data:`PASSAGES_LOURDS` requêtes lourdes à la fois.

    Jamais d'attente : un fil du pool qui patienterait ici serait un fil de
    moins pour ``/health`` et les connexions. ``entrer`` rend faux quand
    tout est pris, et la route répond 503 aussitôt.
    """

    def __init__(self, passages: int = PASSAGES_LOURDS) -> None:
        self._semaphore = threading.BoundedSemaphore(passages)

    def entrer(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def sortir(self) -> None:
        self._semaphore.release()


# ----------------------------------------------------------------------
# Budgets de courriel (§3.5, D12)
# ----------------------------------------------------------------------

# Par adresse, sur TOUS les envois : 1 par minute, 3 par heure, 10 par
# jour. Une boîte ne reçoit jamais de rafale, même si quelqu'un tape son
# adresse en boucle dans ``signup/start``.
ENVOIS_MINUTE = 1
ENVOIS_HEURE = 3
ENVOIS_JOUR = 10

BUDGET_CODES = "codes"
BUDGET_SECURITE = "securite"
_CLE_GLOBALE = {BUDGET_CODES: b"global:codes", BUDGET_SECURITE: b"global:securite"}
# « Nouvelle connexion » part à CHAQUE ``/login`` réussi (D8) : c'est l'avis
# de sécurité qu'un titulaire déclenche en boucle au meilleur prix. Il ne
# peut prendre que la moitié du budget réservé du jour ; l'autre moitié
# reste aux avis qui demandent une rotation ou un code (mot de passe
# changé, clé remplacée, réinitialisation prévue, suppression). Jusqu'au
# 24/09/2026, vingt connexions d'un compte à soi vidaient le budget, et le
# « mot de passe changé » d'un autre compte ne partait plus, sans un mot.
_CLE_CONNEXIONS = b"global:nouvelle-connexion"
PART_CONNEXIONS = 2


def _fenetres(
    conn: sqlite3.Connection, cle: bytes, maintenant: int
) -> tuple[int, int, int]:
    """(minute, heure, jour) déjà envoyés dans les fenêtres fixes courantes."""
    ligne = conn.execute(
        "SELECT minute, heure, jour, fenetre_ms FROM envois WHERE cle = ?", (cle,)
    ).fetchone()
    if ligne is None:
        return 0, 0, 0
    minute, heure, jour_, dernier = (v or 0 for v in ligne)
    return (
        minute if dernier // MINUTE_MS == maintenant // MINUTE_MS else 0,
        heure if dernier // HEURE_MS == maintenant // HEURE_MS else 0,
        jour_ if dernier // JOUR_MS == maintenant // JOUR_MS else 0,
    )


def _compter(
    conn: sqlite3.Connection,
    cle: bytes,
    fenetres: tuple[int, int, int],
    maintenant: int,
) -> None:
    minute, heure, jour_ = fenetres
    conn.execute(
        "INSERT OR REPLACE INTO envois (cle, minute, heure, jour, fenetre_ms) "
        "VALUES (?, ?, ?, ?, ?)",
        (cle, minute + 1, heure + 1, jour_ + 1, maintenant),
    )


class BudgetsCourriel:
    """Deux budgets globaux séparés, plus les plafonds par adresse.

    Le budget des AVIS DE SÉCURITÉ est réservé : seules des actions
    authentifiées (ou prouvées par un code) y puisent. Un inconnu qui tape
    des adresses en boucle épuise au pire le budget des codes — et
    ``mailUnavailable`` le dit — mais « mot de passe changé » part encore.
    """

    def __init__(
        self, secrets_: SecretsServeur, *, codes_jour: int, securite_jour: int
    ) -> None:
        self._secrets = secrets_
        self._plafonds = {BUDGET_CODES: codes_jour, BUDGET_SECURITE: securite_jour}

    def _cle_adresse(self, courriel: str, genre: str | None = None) -> bytes:
        domaine = b"envoi" if genre is None else b"envoi-" + genre.encode()
        return self._secrets.mac(domaine, courriel.encode())

    def epuise(self, conn: sqlite3.Connection, budget: str, maintenant: int) -> bool:
        _, _, jour_ = _fenetres(conn, _CLE_GLOBALE[budget], maintenant)
        return jour_ >= self._plafonds[budget]

    def autoriser(
        self,
        conn: sqlite3.Connection,
        budget: str,
        courriel: str,
        maintenant: int,
        *,
        une_fois_par_jour: str | None = None,
        nouvelle_connexion: bool = False,
    ) -> bool:
        """Vrai si l'envoi est permis — et le COMPTE alors dans chaque budget.

        ``une_fois_par_jour`` : « compte existant » et « connexions
        bloquées » n'arrivent qu'une fois par jour chacun (§3.5).

        Un avis de sécurité compte dans les plafonds de l'adresse mais n'est
        soumis qu'au sien, par jour : « réinitialisation prévue » suit de
        trente secondes le code de réinitialisation, et le plafond d'une
        minute l'aurait avalé — précisément l'avis que la personne doit
        recevoir (A3). Son plafond du jour est à part de celui des codes,
        qu'un inconnu remplit en tapant l'adresse dans ``signup/start`` : le
        partager aurait laissé cet inconnu faire taire « mot de passe
        changé ».
        """
        # « Purgés à chaque création » : une ligne par adresse vue, sinon.
        conn.execute("DELETE FROM envois WHERE fenetre_ms < ?", (maintenant - JOUR_MS,))
        cle_globale = _CLE_GLOBALE[budget]
        globales = _fenetres(conn, cle_globale, maintenant)
        if globales[2] >= self._plafonds[budget]:
            return False
        cle_adresse = self._cle_adresse(courriel)
        adresse = _fenetres(conn, cle_adresse, maintenant)
        a_compter = [(cle_globale, globales), (cle_adresse, adresse)]
        if budget == BUDGET_SECURITE:
            cle_securite = self._cle_adresse(courriel, BUDGET_SECURITE)
            securite = _fenetres(conn, cle_securite, maintenant)
            if securite[2] >= ENVOIS_JOUR:
                return False
            a_compter.append((cle_securite, securite))
            if nouvelle_connexion:
                connexions = _fenetres(conn, _CLE_CONNEXIONS, maintenant)
                part = max(1, self._plafonds[BUDGET_SECURITE] // PART_CONNEXIONS)
                if connexions[2] >= part:
                    return False
                a_compter.append((_CLE_CONNEXIONS, connexions))
        if budget == BUDGET_CODES:
            # « Connexions bloquées » est déjà borné à un par jour : seul le
            # plafond du JOUR s'y applique. Sous le plafond d'une minute, il
            # tombait quand un code était parti dans la même minute — et,
            # n'étant émis qu'au franchissement du seuil, il était perdu pour
            # la journée. « Compte existant », lui, est compté comme un code
            # par ``signup/start`` : les mêmes plafonds que pour une adresse
            # libre, sans quoi le budget dirait laquelle est prise.
            rafale = une_fois_par_jour is None and (
                adresse[0] >= ENVOIS_MINUTE or adresse[1] >= ENVOIS_HEURE
            )
            if rafale or adresse[2] >= ENVOIS_JOUR:
                return False
        if une_fois_par_jour is not None and not self.premier_du_jour(
            conn, une_fois_par_jour, courriel, maintenant
        ):
            return False
        for cle, fenetres in a_compter:
            _compter(conn, cle, fenetres, maintenant)
        return True

    def premier_du_jour(
        self, conn: sqlite3.Connection, genre: str, courriel: str, maintenant: int
    ) -> bool:
        """Vrai la PREMIÈRE fois du jour pour (genre, adresse) — et marque."""
        cle = self._cle_adresse(courriel, genre)
        unique = _fenetres(conn, cle, maintenant)
        if unique[2] >= 1:
            return False
        _compter(conn, cle, unique, maintenant)
        return True

    def envois_du_jour(
        self, conn: sqlite3.Connection, budget: str, maintenant: int
    ) -> int:
        return _fenetres(conn, _CLE_GLOBALE[budget], maintenant)[2]
