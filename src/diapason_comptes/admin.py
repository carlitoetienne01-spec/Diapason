"""``diapason-comptes-admin`` : restaurer une copie, changer de génération.

Conception : ``docs/development/compte-chiffre.md`` §3.10 et étape 5 du §6.

    python -m diapason_comptes.admin restaurer /var/backups/diapason/comptes-AAAAMMJJ.db
    python -m diapason_comptes.admin nouvelle-generation

À lancer sur le VPS sous l'utilisateur ``diapason`` (``sudo -u diapason``) :
la base est en 0600, et un fichier recréé par root ne serait plus lisible
par le service. L'outil pose lui-même l'umask 077 : celui de l'unité
systemd (``UMask=0077``) ne s'applique pas à un shell. Les secrets viennent de
``--env-file`` (par défaut ``/etc/diapason/comptes.env``), dont seules les
variables ``COMPTES_*`` sont retenues ; une variable posée dans
l'environnement de la commande l'emporte (``COMPTES_BASE=… restaurer …``).

``restaurer`` (§3.10) : 1) copie ; 2) rejeu de ``evenements.jsonl`` — comptes
supprimés de nouveau, coffres remis à leur dernière version,
``reset/complete`` rejoués ; 3) ``sessions`` et ``jetons_temporaires``
vidés ; 4) ``generation`` nouvelle. Le service doit être ARRÊTÉ : il garde
la base ouverte, et ``os.replace`` sous lui le laisserait écrire dans un
fichier que plus personne ne lit. L'outil refuse tant que systemd le dit
actif. La base remplacée est gardée à côté, en 0600 : une restauration
lancée sur la mauvaise copie doit pouvoir se défaire.

``nouvelle-generation`` : change ``generation`` sans rien restaurer. Chaque
appareil remet alors son curseur à zéro, tire tout et repousse ce qui
manque au serveur (§4.5) — après une réparation à la main de la base, par
exemple. ``globalSeq`` avance d'un cran et ne recule jamais : le cacher
effacerait le signal d'un retour arrière de toute la machine (§3.10).
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from diapason_comptes import journal
from diapason_comptes.base import Base, ecriture, generation
from diapason_comptes.secrets_serveur import (
    SecretsAbsents,
    charger_configuration_chemins,
    charger_secrets,
)

UNITE = "diapason-comptes"
ENV_DEFAUT = Path("/etc/diapason/comptes.env")

# Codes de sortie : 0 fait, 1 échec de l'opération, 2 refus avant d'agir
# (service actif, secret manquant, copie introuvable). Un script qui
# enchaîne sait ainsi si quelque chose a été touché.
SORTIE_ECHEC = 1
SORTIE_REFUS = 2


def lire_fichier_env(chemin: Path) -> dict[str, str]:
    """Les lignes ``CLE=valeur`` d'un ``EnvironmentFile`` de systemd.

    Seules les clés ``COMPTES_*`` sont gardées : ``comptes.env`` n'en porte
    pas d'autres, et un fichier désigné par erreur (``mail.env``) ne doit
    rien faire entrer dans l'environnement de l'outil.
    """
    valeurs: dict[str, str] = {}
    for ligne in Path(chemin).read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip()
        if cle.startswith("COMPTES_"):
            valeurs[cle] = valeur.strip().strip("'\"")
    return valeurs


def service_actif(unite: str = UNITE) -> bool:
    """Vrai si systemd dit l'unité active. Sans ``systemctl`` (une machine
    de test), faux : c'est alors à l'exploitant de l'avoir arrêtée."""
    if shutil.which("systemctl") is None:
        return False
    resultat = subprocess.run(
        ["systemctl", "is-active", "--quiet", unite], check=False, timeout=10
    )
    return resultat.returncode == 0


def _garder_a_cote(base: Path, maintenant_ms: int) -> Path | None:
    """Une copie cohérente de la base remplacée, par ``Connection.backup`` :
    un ``cp`` du fichier seul oublierait ce qui dort encore dans le WAL."""
    if not base.exists():
        return None
    cote = base.with_name(f"{base.name}.avant-restauration-{maintenant_ms}")
    source = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    cible = sqlite3.connect(str(cote))
    try:
        source.backup(cible)
    finally:
        source.close()
        cible.close()
    os.chmod(cote, 0o600)
    return cote


def restaurer(
    copie: Path,
    env: Mapping[str, str],
    *,
    actif: Callable[[], bool] = service_actif,
    ecrire: Callable[[str], None] = print,
) -> int:
    copie = Path(copie)
    if actif():
        ecrire(f"refus : {UNITE} est actif ; « systemctl stop {UNITE} » d'abord")
        return SORTIE_REFUS
    if not copie.is_file():
        ecrire(f"refus : copie introuvable : {copie}")
        return SORTIE_REFUS
    try:
        secrets_ = charger_secrets(env)
        base, fichier_journal = charger_configuration_chemins(env)
    except SecretsAbsents as exc:
        ecrire(f"refus : {exc}")
        return SORTIE_REFUS
    if copie.resolve() == base.resolve():
        ecrire("refus : la copie EST la base en service")
        return SORTIE_REFUS
    try:
        cote = _garder_a_cote(base, time.time_ns() // 1_000_000)
        rapport = journal.restaurer(copie, base, fichier_journal, secrets_)
    except Exception as exc:
        # Le type seulement : le message d'une erreur SQLite ou AES-GCM peut
        # citer une valeur, et ce terminal finit souvent dans un historique.
        ecrire(f"échec de la restauration : {type(exc).__name__}")
        return SORTIE_ECHEC
    ecrire(
        f"restauré : {rapport.appliques} événements rejoués, {rapport.ignores} "
        f"ignorés ; generation {rapport.generation} ; globalSeq {rapport.global_seq}"
    )
    if rapport.global_seq_remplacee is None:
        ecrire(
            "attention : base remplacée absente ou illisible — globalSeq peut "
            "avoir reculé sous ce que les appareils ont vu ; ceux-là passeront "
            "en « serveur revenu en arrière » (§3.10)"
        )
    if cote is not None:
        ecrire(
            f"ancienne base gardée dans {cote} — à effacer (shred) une fois la "
            "restauration vérifiée : elle garde ce que le journal a effacé depuis"
        )
    return 0


def nouvelle_generation(
    env: Mapping[str, str], *, ecrire: Callable[[str], None] = print
) -> int:
    """Possible service en marche : une transaction SQLite ordinaire, que le
    service voit à sa requête suivante (``/health`` relit ``meta``)."""
    base_chemin, _ = charger_configuration_chemins(env)
    if not base_chemin.is_file():
        ecrire(f"refus : base introuvable : {base_chemin}")
        return SORTIE_REFUS
    base = Base(base_chemin)
    try:
        with base.transaction() as conn:
            ancienne = generation(conn)
            nouvelle = secrets.token_hex(16)
            conn.execute(
                "UPDATE meta SET valeur = ? WHERE cle = 'generation'", (nouvelle,)
            )
            seq = ecriture(conn)
    finally:
        base.fermer()
    ecrire(f"generation {ancienne} → {nouvelle} ; globalSeq {seq}")
    return 0


def principal(
    arguments: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    actif: Callable[[], bool] = service_actif,
    ecrire: Callable[[str], None] = print,
) -> int:
    analyseur = argparse.ArgumentParser(
        prog="diapason-comptes-admin",
        description="Restauration et génération du service de comptes (§3.10).",
    )
    analyseur.add_argument(
        "--env-file",
        type=Path,
        default=ENV_DEFAUT,
        help=f"fichier des secrets (défaut : {ENV_DEFAUT})",
    )
    commandes = analyseur.add_subparsers(dest="commande", required=True)
    restauration = commandes.add_parser(
        "restaurer", help="copie + rejeu du journal + sessions vidées + generation"
    )
    restauration.add_argument("copie", type=Path)
    commandes.add_parser("nouvelle-generation", help="change generation seulement")
    options = analyseur.parse_args(arguments)

    env: dict[str, str] = {}
    if options.env_file.is_file():
        try:
            env.update(lire_fichier_env(options.env_file))
        except OSError as exc:
            ecrire(f"refus : {options.env_file} illisible ({type(exc).__name__})")
            return SORTIE_REFUS
    env.update(os.environ if environ is None else environ)
    # L'umask du service (``UMask=0077``), pas celui du shell : sous 022, la
    # base restaurée, sa copie « à côté » et les ``-wal``/``-shm`` que
    # ``nouvelle-generation`` peut créer sortaient lisibles de tous
    # (24/09/2026). Rendu en sortant : ``principal`` s'appelle aussi en test.
    umask_trouve = os.umask(0o077)
    try:
        if options.commande == "restaurer":
            return restaurer(options.copie, env, actif=actif, ecrire=ecrire)
        return nouvelle_generation(env, ecrire=ecrire)
    finally:
        os.umask(umask_trouve)


if __name__ == "__main__":
    sys.exit(principal())
