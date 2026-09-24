"""Base volée, refus de démarrer, aucun écho, rotation des secrets.

Conception : ``docs/development/compte-chiffre.md`` §3.1, §3.2, A2 et
étape 4 du §6 (« Base et secrets »).
"""

from __future__ import annotations

import base64
import os

import pytest

from diapason_comptes.app import creer_app_depuis_environnement
from diapason_comptes.secrets_serveur import SecretsAbsents
from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    amk_mdp,
    amk_recup,
    secrets_de_test,
    trousseau,
)


def _b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode()


def _env_complet(tmp_path) -> dict[str, str]:
    return {
        "COMPTES_SECRETS_VERSION": "1",
        "COMPTES_POIVRE_1": _b64(os.urandom(32)),
        "COMPTES_CLE_REPOS_1": _b64(os.urandom(32)),
        "COMPTES_GRAINE_SEL": _b64(os.urandom(32)),
        "COMPTES_BASE": str(tmp_path / "comptes.db"),
        "COMPTES_JOURNAL": str(tmp_path / "evenements.jsonl"),
        "COMPTES_BUDGET_CODES_JOUR": "80",
        "COMPTES_BUDGET_SECURITE_JOUR": "20",
    }


class TestBaseVolee:
    def test_une_base_volee_seule_ne_donne_ni_adresse_ni_enveloppe(self, service):
        """A2 — sans ``comptes.env``, ``comptes.db`` ne dit ni l'adresse, ni
        les enveloppes, ni ``authKey`` : tout est poivré ou sur-chiffré."""
        inscrit = service.inscrire("vole@exemple.org")
        service.connecter(inscrit)
        octets = service.octets_sur_disque()
        assert b"vole@exemple.org" not in octets, "l'adresse est sur-chiffrée"
        assert "vole@exemple.org".encode("utf-16-le") not in octets, "sous aucune forme"
        for nom, secret in (
            ("authKey", inscrit.auth_key),
            ("recoveryAuthKey", inscrit.recovery_auth_key),
            ("wrappedMasterKey", inscrit.wrapped),
            ("sealedMasterKey", inscrit.sealed),
            ("keyring", inscrit.keyring),
        ):
            assert secret not in octets, f"{nom} n'est pas dans la base"
            # Même un fragment : l'en-tête DPE1 est public, le reste non.
            assert secret[-24:] not in octets, f"aucun fragment de {nom}"


class TestDemarrage:
    def test_le_service_refuse_de_demarrer_sans_comptes_env(self):
        """§3.2 — un service lancé sans secrets poivrerait sous une clé vide :
        chaque vérificateur écrit alors serait perdu au premier vrai
        démarrage."""
        with pytest.raises(SecretsAbsents, match="COMPTES_SECRETS_VERSION"):
            creer_app_depuis_environnement({})

    def test_un_secret_de_31_octets_est_refuse_sans_etre_cite(self, tmp_path):
        """§3.2 — 32 o exactement ; le message nomme la variable, jamais sa
        valeur, qui finirait dans journald."""
        env = _env_complet(tmp_path)
        court = _b64(os.urandom(31))
        env["COMPTES_POIVRE_1"] = court
        with pytest.raises(SecretsAbsents) as refus:
            creer_app_depuis_environnement(env)
        assert "COMPTES_POIVRE_1" in str(refus.value), "la variable est nommée"
        assert court not in str(refus.value), "la valeur n'est jamais citée"

    def test_sans_boite_de_reponse_le_service_ne_demarre_pas(self, tmp_path):
        """D17 n'est pas tranchée : aucune adresse de réponse inventée. Sans
        elle, le service refuse de démarrer plutôt que d'envoyer des courriels
        sans boîte lue derrière."""
        env = _env_complet(tmp_path)
        env.update(
            RESEND_API_KEY="re_test",
            COURRIEL_EXPEDITEUR="Diapason <test@exemple.invalid>",
            COMPTES_ORIGINE_PUBLIQUE="https://exemple.invalid",
        )
        with pytest.raises(SecretsAbsents, match="COURRIEL_REPONSE"):
            creer_app_depuis_environnement(env)

    def test_la_presence_des_secrets_atteint_journald(self, tmp_path, capsys):
        """§3.2 — « il ne journalise que la PRÉSENCE de chaque secret ».
        Rien ne configurait ``logging`` : le niveau effectif restait WARNING
        et la ligne INFO n'atteignait jamais journald, seule trace attendue
        au démarrage."""
        env = _env_complet(tmp_path)
        env.update(
            RESEND_API_KEY="re_test",
            COURRIEL_EXPEDITEUR="Diapason <test@exemple.invalid>",
            COURRIEL_REPONSE="reponse@exemple.invalid",
            COMPTES_ORIGINE_PUBLIQUE="https://exemple.invalid",
        )
        app = creer_app_depuis_environnement(env)
        try:
            sortie = capsys.readouterr().err
        finally:
            app.state.contexte.fermer()
        assert "secrets présents" in sortie, "la présence est écrite sur stderr"
        assert env["COMPTES_POIVRE_1"] not in sortie, "jamais une valeur"

    def test_les_budgets_de_courriel_n_ont_pas_de_valeur_par_defaut(self, tmp_path):
        """D12 — le plafond se fixe d'après l'offre Resend (étape 0) ; un
        chiffre inventé serait une promesse faite à l'aveugle."""
        env = _env_complet(tmp_path)
        del env["COMPTES_BUDGET_CODES_JOUR"]
        with pytest.raises(SecretsAbsents, match="COMPTES_BUDGET_CODES_JOUR"):
            creer_app_depuis_environnement(env)


class TestAucunEcho:
    SECRET = "VALEUR-QUI-NE-DOIT-JAMAIS-REVENIR"

    def test_un_422_nomme_le_champ_et_jamais_la_valeur(self, service):
        """§3.1 — le 422 par défaut de FastAPI recopie l'entrée refusée : un
        ``authKey`` mal encodé serait revenu en écho, puis dans tout journal
        qui garde les réponses."""
        r = service.post("/login", {"email": "a@exemple.org", "authKey": self.SECRET})
        assert r.status_code == 422, "authKey invalide"
        assert r.json() == {"error": {"code": "invalidRequest", "field": "authKey"}}
        assert self.SECRET not in r.text, "aucun écho de la valeur"

    def test_un_corps_illisible_ne_revient_pas_non_plus(self, service):
        """§3.1 — JSON cassé, flottant, clé en double : même réponse sobre."""
        for corps in (
            '{"authKey": "' + self.SECRET + '"',
            '{"email": "a@b.c", "authKey": 1.5, "x": "' + self.SECRET + '"}',
            '{"authKey": "' + self.SECRET + '", "authKey": "b"}',
        ):
            r = service.client.post(
                "/api/v1/login",
                content=corps,
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == 422, f"refusé : {corps[:20]}"
            assert r.json() == {"error": {"code": "invalidRequest", "field": "body"}}
            assert self.SECRET not in r.text, "aucun écho"

    def test_une_exception_ne_sort_pas_de_l_application(self, service, caplog):
        """§3.1 — le 500 ne journalise que le TYPE : le message d'une
        exception SQLite ou d'AESGCM peut citer une valeur. Jusqu'au
        24/09/2026, Starlette relançait l'exception après le gestionnaire,
        et uvicorn l'écrivait avec son message et sa trace dans journald,
        gardé 7 jours. ``raise_server_exceptions=True`` : si elle sort de
        l'application ASGI, ce test la voit lever."""

        def lever(*_a, **_k):
            raise ValueError(self.SECRET)

        inscrit = service.inscrire("exception@exemple.org")
        service.ctx.journal.ligne_de_securite = lever
        with caplog.at_level("DEBUG"):
            r = service.post(
                "/vault/commit", service.corps_commit(inscrit), headers=inscrit.bearer
            )
        assert r.status_code == 500, "un 500 sobre"
        assert r.json() == {"error": {"code": "internal"}}, "sans écho"
        assert r.headers["cache-control"] == "no-store", "no-store sur le 500"
        assert self.SECRET not in caplog.text, "le message n'est jamais journalisé"
        assert "ValueError" in caplog.text, "le type, lui, l'est"

    def test_chaque_reponse_porte_no_store_et_nosniff(self, service):
        """§3.1 — y compris les erreurs : un 401 ou un 404 cachés par un
        intermédiaire ne doivent pas l'être davantage qu'un 200."""
        reponses = [
            service.get("/health"),
            service.get("/account"),
            service.get("/inexistant"),
            service.post("/login", {"email": "x"}),
        ]
        for r in reponses:
            assert r.headers["cache-control"] == "no-store", (
                f"no-store sur {r.status_code}"
            )
            assert r.headers["x-content-type-options"] == "nosniff", "nosniff"


class TestRotationDesSecrets:
    def test_la_connexion_reecrit_le_compte_sous_les_secrets_courants(
        self, fabrique, tmp_path
    ):
        """§3.2 — « la rotation a lieu à la connexion suivante » : après une
        rotation du poivre, l'ancien compte se connecte encore, puis passe
        sous la version courante ; le sel, lui, ne bouge pas (§2.2)."""
        v1 = secrets_de_test(1)
        avant = fabrique(secrets=v1, dossier=tmp_path / "rot")
        inscrit = avant.inscrire("rotation@exemple.org")
        sel = avant.post("/login/params", {"email": inscrit.email}).json()
        avant.ctx.fermer()

        v2 = secrets_de_test(2, anciens=v1)
        apres = fabrique(secrets=v2, dossier=tmp_path / "rot", horloge=avant.horloge)
        assert apres.connecter(inscrit).status_code == 200, (
            "l'ancien index est retrouvé"
        )
        with apres.ctx.base.lecture() as conn:
            version, index, verif, courriel = conn.execute(
                "SELECT secrets_version, courriel_index, verif_auth, courriel_chiffre "
                "FROM comptes"
            ).fetchone()
        assert (index[0], verif[0], courriel[0]) == (2, 2, 2), "tout est réécrit en v2"
        assert _versions(apres) == {
            "courriel_index": 2,
            "courriel_chiffre": 2,
            "sel_kdf": 2,
            "verif_auth": 2,
            "amk_mdp": 2,
            "verif_recup": 1,
            "amk_recup": 2,
            "trousseau": 2,
        }, "enveloppes et trousseau re-scellés ; verif_recup attend recoveryAuthKey"
        assert version == 1, (
            "secrets_version dit la plus vieille version encore nécessaire : "
            "verif_recup est en v1, retirer v1 perdrait la clé de récupération"
        )
        assert apres.connecter(inscrit).status_code == 200, "et se reconnecte en v2"
        assert apres.post("/login/params", {"email": inscrit.email}).json() == sel, (
            "le sel ne dépend pas du poivre"
        )
        r = apres.post(
            "/recovery/unwrap",
            {
                "email": inscrit.email,
                "recoveryAuthKey": b64url(inscrit.recovery_auth_key),
            },
        )
        assert r.status_code == 200, "le vérificateur de récupération v1 vaut encore"
        assert _versions(apres)["verif_recup"] == 2, "unwrap réécrit verif_recup"
        assert _secrets_version(apres) == 2, "plus rien n'exige v1"

    def test_le_sel_d_une_adresse_inconnue_ne_bouge_pas_a_la_rotation(
        self, fabrique, tmp_path
    ):
        """§2.2 — le sel ne dépend que de ``GRAINE_SEL``, jamais tournée. Le
        test précédent ne regardait qu'un compte EXISTANT, dont le sel est
        gardé : une formule qui mêlait le poivre, lui tourné, changeait le
        sel des adresses inconnues seules, et sonder ``login/params`` avant
        et après une rotation séparait les inscrits des autres."""
        v1 = secrets_de_test(1)
        avant = fabrique(secrets=v1, dossier=tmp_path / "sel")
        inconnue = {"email": "jamais.inscrite@exemple.org"}
        sel_avant = avant.post("/login/params", inconnue).json()
        avant.ctx.fermer()
        apres = fabrique(
            secrets=secrets_de_test(2, anciens=v1), dossier=tmp_path / "sel"
        )
        assert apres.post("/login/params", inconnue).json() == sel_avant, (
            "même sel pour une adresse inconnue avant et après la rotation"
        )


def _versions(service) -> dict[str, int | None]:
    colonnes = (
        "courriel_index",
        "courriel_chiffre",
        "sel_kdf",
        "verif_auth",
        "amk_mdp",
        "verif_recup",
        "amk_recup",
        "trousseau",
    )
    with service.ctx.base.lecture() as conn:
        ligne = conn.execute(f"SELECT {', '.join(colonnes)} FROM comptes").fetchone()
    return {c: (None if v is None else v[0]) for c, v in zip(colonnes, ligne)}


def _secrets_version(service) -> int:
    with service.ctx.base.lecture() as conn:
        return conn.execute("SELECT secrets_version FROM comptes").fetchone()[0]


def _seulement(secrets_):
    """Les secrets après que l'exploitant a retiré toute version antérieure."""
    from diapason_comptes.secrets_serveur import SecretsServeur

    v = secrets_.version
    return SecretsServeur(
        version=v,
        poivres={v: secrets_.poivres[v]},
        cles_repos={v: secrets_.cles_repos[v]},
        graine_sel=secrets_.graine_sel,
    )


class TestRotationParLeCoffre:
    """§3.2 — ``secrets_version`` est ce que l'exploitant lit pour savoir
    s'il peut retirer une version. Jusqu'au 24/09/2026, ``vault/commit`` et
    ``reset/complete`` le posaient à la version courante sans réécrire
    l'index ni l'adresse : la connexion suivante ne corrigeait plus rien,
    l'exploitant retirait v1, et le compte était perdu pour de bon."""

    def _passer_en_v2(self, fabrique, tmp_path):
        v1 = secrets_de_test(1)
        avant = fabrique(secrets=v1, dossier=tmp_path / "coffre")
        inscrit = avant.inscrire("coffre-v2@exemple.org")
        avant.ctx.fermer()
        v2 = secrets_de_test(2, anciens=v1)
        apres = fabrique(secrets=v2, dossier=tmp_path / "coffre", horloge=avant.horloge)
        return inscrit, apres, v2

    def _retirer_v1(self, fabrique, tmp_path, service, v2, inscrit):
        service.ctx.fermer()
        seul = fabrique(
            secrets=_seulement(v2), dossier=tmp_path / "coffre", horloge=service.horloge
        )
        r = seul.connecter(inscrit)
        assert r.status_code == 200, f"connexion sans v1 : {r.text}"
        bearer = {"Authorization": f"Bearer {r.json()['sessionToken']}"}
        compte = seul.get("/account", headers=bearer)
        assert compte.status_code == 200, "GET /account sans v1"
        assert compte.json()["email"] == inscrit.email, "l'adresse se lit en v2"

    def test_vault_commit_remplace_tout_et_v1_peut_partir(self, fabrique, tmp_path):
        inscrit, service, v2 = self._passer_en_v2(fabrique, tmp_path)
        r = service.post(
            "/vault/commit",
            service.corps_commit(
                inscrit,
                recuperation={
                    "mode": "replace",
                    "authKey": b64url(os.urandom(32)),
                    "sealedMasterKey": b64url(amk_recup(inscrit.account_id, 2)),
                },
            ),
            headers=inscrit.bearer,
        )
        assert r.status_code == 200, r.text
        assert set(_versions(service).values()) == {2}, "toutes les colonnes en v2"
        assert _secrets_version(service) == 2, "secrets_version dit vrai"
        self._retirer_v1(fabrique, tmp_path, service, v2, inscrit)

    def test_vault_commit_qui_garde_la_cle_dit_que_v1_sert_encore(
        self, fabrique, tmp_path
    ):
        inscrit, service, _v2 = self._passer_en_v2(fabrique, tmp_path)
        r = service.post(
            "/vault/commit", service.corps_commit(inscrit), headers=inscrit.bearer
        )
        assert r.status_code == 200, r.text
        versions = _versions(service)
        assert (versions["courriel_index"], versions["courriel_chiffre"]) == (2, 2), (
            "l'index et l'adresse passent en v2"
        )
        assert versions["verif_recup"] == 1, "mode keep : verif_recup reste v1"
        assert _secrets_version(service) == 1, "et secrets_version le dit"

    def test_reset_complete_remplace_tout_et_v1_peut_partir(self, fabrique, tmp_path):
        from diapason_comptes import jetons

        inscrit, service, v2 = self._passer_en_v2(fabrique, tmp_path)
        with service.ctx.base.transaction() as conn:
            conn.execute(
                "UPDATE comptes SET reinit_demandee_ms = ?, reinit_effective_ms = ?",
                (service.horloge() - 1, service.horloge() - 1),
            )
            jetons.enregistrer_code(
                conn,
                service.secrets,
                conn.execute("SELECT courriel_index FROM comptes").fetchone()[0],
                "reinitialisation",
                "818181",
                service.horloge(),
            )
        nouvelle = os.urandom(32)
        r = service.post(
            "/reset/complete",
            {
                "email": inscrit.email,
                "code": "818181",
                "kdfVersion": 1,
                "authKey": b64url(nouvelle),
                "wrappedMasterKey": b64url(amk_mdp(inscrit.account_id)),
                "recovery": None,
                "keyring": b64url(trousseau(inscrit.account_id)),
            },
        )
        assert r.status_code == 200, r.text
        assert set(_versions(service).values()) == {2, None}, "tout en v2"
        assert _secrets_version(service) == 2, "secrets_version dit vrai"
        inscrit.auth_key = nouvelle
        self._retirer_v1(fabrique, tmp_path, service, v2, inscrit)


class TestSelScelle:
    def test_aucun_sel_de_compte_ne_se_lit_dans_la_base(self, service):
        """A2, §2.9 — le sel est public par ``login/params`` à qui connaît
        l'adresse. Stocké en clair, il faisait de la base volée seule un
        annuaire : le voleur comparait ``sel_kdf`` au ``kdfSalt`` servi pour
        chaque adresse candidate. Il est scellé depuis le 24/09/2026."""
        inscrits = [service.inscrire(f"sel{i}@exemple.org") for i in range(2)]
        octets = service.octets_sur_disque()
        for inscrit in inscrits:
            sel = base64.urlsafe_b64decode(inscrit.kdf_salt + "=")
            assert sel not in octets, "le sel n'est pas dans la base ni le WAL"
            servi = service.post("/login/params", {"email": inscrit.email}).json()
            assert servi["kdfSalt"] == inscrit.kdf_salt, "login/params rend le sel"
