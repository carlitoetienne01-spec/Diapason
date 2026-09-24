"""``diapason-comptes-admin`` : restaurer et changer de génération.

Conception : ``docs/development/compte-chiffre.md`` §3.10 et étape 5 du §6.
Aucune lecture de ``/etc/diapason`` : chaque test écrit son propre
``comptes.env`` dans son dossier temporaire.
"""

from __future__ import annotations

import base64
import os
import pathlib
import sqlite3
import stat
import subprocess
import sys

from diapason_comptes import admin
from tests.diapason_comptes._synchro import nouvel_id, pousser_un, tirer

RACINE = pathlib.Path(__file__).resolve().parents[2]


def _copier(chemin_base, destination) -> None:
    source = sqlite3.connect(str(chemin_base))
    cible = sqlite3.connect(str(destination))
    try:
        source.backup(cible)
    finally:
        source.close()
        cible.close()


def _fichier_env(service, dossier: pathlib.Path) -> pathlib.Path:
    """Le ``comptes.env`` du service de test, plus une ligne étrangère."""
    s = service.secrets

    def b64(octets: bytes) -> str:
        return base64.b64encode(octets).decode("ascii")

    lignes = [
        "# généré par le test",
        f"COMPTES_SECRETS_VERSION={s.version}",
        *(f"COMPTES_POIVRE_{v}={b64(p)}" for v, p in s.poivres.items()),
        *(f"COMPTES_CLE_REPOS_{v}={b64(c)}" for v, c in s.cles_repos.items()),
        f"COMPTES_GRAINE_SEL={b64(s.graine_sel)}",
        f"COMPTES_BASE={service.configuration.chemin_base}",
        f"COMPTES_JOURNAL={service.configuration.chemin_journal}",
        "RESEND_API_KEY=ne-doit-pas-etre-lu",
    ]
    chemin = dossier / "comptes.env"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def _generation(chemin_base) -> str:
    conn = sqlite3.connect(str(chemin_base))
    try:
        return conn.execute(
            "SELECT valeur FROM meta WHERE cle = 'generation'"
        ).fetchone()[0]
    finally:
        conn.close()


class TestRestaurer:
    def test_la_commande_restaure_la_copie_et_rejoue_le_journal(
        self, fabrique, tmp_path
    ):
        """§3.10 — ``diapason-comptes-admin restaurer <copie>`` : l'ancien mot
        de passe est refusé, le jeton d'avant est mort, les objets de la copie
        sont là sous une ``generation`` nouvelle, et la base remplacée est
        gardée à côté en 0600 — une restauration lancée sur la mauvaise copie
        doit pouvoir se défaire."""
        service = fabrique()
        alice = service.inscrire("alice@exemple.org")
        oid = nouvel_id()
        pousser_un(service, alice, oid, 0)
        generation_avant = service.get("/health").json()["generation"]
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        ancien_jeton = alice.bearer
        nouvelle = os.urandom(32)
        r = service.post(
            "/vault/commit",
            service.corps_commit(alice, nouvelle_auth=nouvelle),
            headers=alice.bearer,
        )
        assert r.status_code == 200, r.text
        seq_avant = service.get("/health").json()["globalSeq"]
        env = _fichier_env(service, tmp_path)
        service.ctx.fermer()

        sorties: list[str] = []
        code = admin.principal(
            ["--env-file", str(env), "restaurer", str(copie)],
            environ={},
            actif=lambda: False,
            ecrire=sorties.append,
        )
        assert code == 0, sorties
        cotes = list(tmp_path.glob("comptes.db.avant-restauration-*"))
        assert len(cotes) == 1, "l'ancienne base est gardée à côté"
        assert stat.S_IMODE(cotes[0].stat().st_mode) == 0o600, "en 0600"
        assert any(str(cotes[0]) in ligne for ligne in sorties), "son chemin est dit"

        restaure = fabrique(secrets=service.secrets, horloge=service.horloge)
        assert restaure.get("/account", headers=ancien_jeton).status_code == 401, (
            "les sessions sont vidées"
        )
        assert restaure.connecter(alice).status_code == 401, "l'ancien mot de passe"
        alice.auth_key = nouvelle
        r = restaure.connecter(alice)
        assert r.status_code == 200, "le coffre rejoué est le courant"
        assert r.json()["keyEpoch"] == 2, "l'époque de la rotation rejouée"
        alice.jeton = r.json()["sessionToken"]
        page = tirer(restaure, alice).json()
        assert [i["objectId"] for i in page["items"]] == [oid], "l'objet de la copie"
        assert page["meta"]["generation"] != generation_avant, "generation nouvelle"
        assert restaure.get("/health").json()["globalSeq"] > seq_avant, (
            "globalSeq ne recule pas"
        )

    def test_global_seq_ne_recule_pas_quand_la_derniere_ecriture_est_une_poussee(
        self, fabrique, tmp_path
    ):
        """§3.10 — ni les poussées ni les pièces n'écrivent au journal : le
        « maximum du journal » ne couvrait pas l'activité ordinaire. Après
        vingt poussées postérieures à la copie, ``globalSeq`` retombait de 22
        à 3 (24/09/2026), et chaque appareil concluait à un retour arrière
        de TOUTE la machine — rotation obligatoire, message « mot de passe
        d'avant ». Le plancher est le ``globalSeq`` de la base remplacée."""
        service = fabrique()
        alice = service.inscrire("pousse@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        for _ in range(20):
            pousser_un(service, alice, nouvel_id(), 0)
        seq_avant = service.get("/health").json()["globalSeq"]
        env = _fichier_env(service, tmp_path)
        service.ctx.fermer()

        sorties: list[str] = []
        code = admin.principal(
            ["--env-file", str(env), "restaurer", str(copie)],
            environ={},
            actif=lambda: False,
            ecrire=sorties.append,
        )
        assert code == 0, sorties
        restaure = fabrique(secrets=service.secrets, horloge=service.horloge)
        seq_apres = restaure.get("/health").json()["globalSeq"]
        assert seq_apres > seq_avant, f"globalSeq {seq_avant} → {seq_apres}"

    def test_sans_base_remplacee_la_sortie_dit_que_global_seq_peut_reculer(
        self, fabrique, tmp_path
    ):
        """§3.10 — VPS perdu, base absente : rien ne dit plus jusqu'où
        ``globalSeq`` était monté. L'outil restaure quand même, et le DIT,
        plutôt que de laisser croire que le compteur n'a pas reculé."""
        service = fabrique()
        service.inscrire("perdu@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        env = _fichier_env(service, tmp_path)
        service.ctx.fermer()
        for suffixe in ("", "-wal", "-shm"):
            pathlib.Path(str(service.configuration.chemin_base) + suffixe).unlink(
                missing_ok=True
            )
        sorties: list[str] = []
        code = admin.principal(
            ["--env-file", str(env), "restaurer", str(copie)],
            environ={},
            actif=lambda: False,
            ecrire=sorties.append,
        )
        assert code == 0, sorties
        assert any("globalSeq peut avoir reculé" in s for s in sorties), sorties

    def test_la_base_restauree_est_en_0600_meme_sous_umask_022(
        self, fabrique, tmp_path
    ):
        """§3.1 — ``UMask=0077`` est celui de l'unité systemd, pas celui d'un
        shell ``sudo -u diapason``. Sous umask 022, la base restaurée sortait
        en 0644 (24/09/2026) : courriels chiffrés, vérificateurs, enveloppes
        et blobs lisibles par tout utilisateur d'un VPS partagé."""
        service = fabrique()
        service.inscrire("mode@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        env = _fichier_env(service, tmp_path)
        service.ctx.fermer()
        ancien = os.umask(0o022)
        try:
            code = admin.principal(
                ["--env-file", str(env), "restaurer", str(copie)],
                environ={},
                actif=lambda: False,
                ecrire=lambda _ligne: None,
            )
            umask_apres = os.umask(0o022)
        finally:
            os.umask(ancien)
        assert code == 0
        assert umask_apres == 0o022, "l'outil rend l'umask qu'il a trouvé"
        base = service.configuration.chemin_base
        for chemin in (base, *base.parent.glob(base.name + "-*")):
            mode = stat.S_IMODE(chemin.stat().st_mode)
            assert mode == 0o600, f"{chemin.name} en {oct(mode)}"

    def test_la_commande_refuse_une_copie_qui_est_la_base(self, fabrique, tmp_path):
        """§3.10 — restaurer la base sur elle-même la lirait pendant qu'on
        la remplace : refus avant d'agir, code 2."""
        service = fabrique()
        env = _fichier_env(service, tmp_path)
        avant = _generation(service.configuration.chemin_base)
        sorties: list[str] = []
        code = admin.principal(
            [
                "--env-file",
                str(env),
                "restaurer",
                str(service.configuration.chemin_base),
            ],
            environ={},
            actif=lambda: False,
            ecrire=sorties.append,
        )
        assert code == admin.SORTIE_REFUS, sorties
        assert _generation(service.configuration.chemin_base) == avant, "rien touché"

    def test_la_commande_refuse_tant_que_le_service_tourne(self, fabrique, tmp_path):
        """§3.10 — le service garde la base ouverte : ``os.replace`` sous lui
        le laisserait écrire dans un fichier que plus personne ne lit, et
        chaque écriture suivante serait perdue sans un mot."""
        service = fabrique()
        service.inscrire("actif@exemple.org")
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        env = _fichier_env(service, tmp_path)
        avant = _generation(service.configuration.chemin_base)
        sorties: list[str] = []
        code = admin.principal(
            ["--env-file", str(env), "restaurer", str(copie)],
            environ={},
            actif=lambda: True,
            ecrire=sorties.append,
        )
        assert code == admin.SORTIE_REFUS, sorties
        assert "systemctl stop" in sorties[0], "la marche à suivre est dite"
        assert _generation(service.configuration.chemin_base) == avant, "rien touché"

    def test_la_commande_refuse_sans_secrets_ni_copie(self, fabrique, tmp_path):
        """§3.2 — sans ``comptes.env``, le journal ne se déchiffre pas : mieux
        vaut refuser avant de toucher à la base que la remplacer à moitié."""
        service = fabrique()
        copie = tmp_path / "copie.db"
        _copier(service.configuration.chemin_base, copie)
        sorties: list[str] = []
        code = admin.principal(
            ["--env-file", str(tmp_path / "absent.env"), "restaurer", str(copie)],
            environ={"COMPTES_BASE": str(service.configuration.chemin_base)},
            actif=lambda: False,
            ecrire=sorties.append,
        )
        assert code == admin.SORTIE_REFUS, sorties
        assert "COMPTES_SECRETS_VERSION" in sorties[0], "la variable fautive nommée"
        assert not list(tmp_path.glob("*.avant-restauration-*")), "rien touché"
        env = _fichier_env(service, tmp_path)
        code = admin.principal(
            ["--env-file", str(env), "restaurer", str(tmp_path / "rien.db")],
            environ={},
            actif=lambda: False,
            ecrire=sorties.append,
        )
        assert code == admin.SORTIE_REFUS, "copie introuvable"

    def test_seules_les_variables_comptes_sont_lues_du_fichier(self, tmp_path):
        """§3.2 — un fichier désigné par erreur (``mail.env``) ne fait rien
        entrer d'autre que ``COMPTES_*`` dans l'environnement de l'outil."""
        chemin = tmp_path / "x.env"
        chemin.write_text(
            "# commentaire\nCOMPTES_BASE='/tmp/b.db'\nRESEND_API_KEY=secret\n"
            "ligne sans egal\n",
            encoding="utf-8",
        )
        assert admin.lire_fichier_env(chemin) == {"COMPTES_BASE": "/tmp/b.db"}


class TestNouvelleGeneration:
    def test_change_generation_sans_toucher_aux_donnees(self, service, tmp_path):
        """§4.5 — une ``generation`` nouvelle fait remettre à zéro le SEUL
        curseur de chaque appareil ; sessions et objets restent, et
        ``globalSeq`` avance plutôt que de reculer (§3.10). Possible service
        en marche : ``/health`` relit ``meta`` à chaque appel."""
        inscrit = service.inscrire("generation@exemple.org")
        oid = nouvel_id()
        pousser_un(service, inscrit, oid, 0)
        avant = service.get("/health").json()
        sorties: list[str] = []
        code = admin.principal(
            ["--env-file", str(tmp_path / "absent.env"), "nouvelle-generation"],
            environ={"COMPTES_BASE": str(service.configuration.chemin_base)},
            ecrire=sorties.append,
        )
        assert code == 0, sorties
        apres = service.get("/health").json()
        assert apres["generation"] != avant["generation"], "generation nouvelle"
        assert apres["globalSeq"] == avant["globalSeq"] + 1, "globalSeq + 1"
        page = tirer(service, inscrit)
        assert page.status_code == 200, "la session tient"
        assert [i["objectId"] for i in page.json()["items"]] == [oid], "l'objet reste"
        assert page.json()["meta"]["generation"] == apres["generation"]

    def test_le_module_se_lance_en_ligne_de_commande(self, service, tmp_path):
        """§6, étape 5 — ``python -m diapason_comptes.admin`` est la commande
        que le déploiement installera sous le nom ``diapason-comptes-admin``."""
        avant = _generation(service.configuration.chemin_base)
        env = {
            **os.environ,
            "PYTHONPATH": str(RACINE / "src"),
            "COMPTES_BASE": str(service.configuration.chemin_base),
        }
        sortie = subprocess.run(
            [
                sys.executable,
                "-m",
                "diapason_comptes.admin",
                "--env-file",
                str(tmp_path / "absent.env"),
                "nouvelle-generation",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=RACINE,
            timeout=60,
        )
        assert sortie.returncode == 0, sortie.stderr
        assert _generation(service.configuration.chemin_base) != avant, "changée"
