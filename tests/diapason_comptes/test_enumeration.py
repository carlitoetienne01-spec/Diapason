"""Énumération : une adresse connue et une inconnue répondent pareil.

Conception : ``docs/development/compte-chiffre.md`` §3.5 et étape 4 du §6
(« Énumération »). Même statut, même corps, mêmes en-têtes, OCTET PAR OCTET,
sur ``signup/*``, ``login/params``, ``login``, ``recovery/unwrap`` et
``reset/*``. Un écart d'un seul octet suffit à tester une liste d'adresses.
"""

from __future__ import annotations

import os

import pytest

from diapason_comptes.validation import b64url
from tests.diapason_comptes._outils import (
    HEURE_MS,
    JOUR_MS,
    amk_mdp,
    trousseau,
)

INCONNUE = "personne@exemple.org"


def _identiques(a, b) -> None:
    assert a.status_code == b.status_code, (
        f"statuts différents : {a.status_code} ≠ {b.status_code}"
    )
    assert a.content == b.content, f"corps différents : {a.content!r} ≠ {b.content!r}"
    assert sorted(a.headers.items()) == sorted(b.headers.items()), "en-têtes différents"


def _corps_complete(email: str) -> dict:
    compte = "00000000-0000-4000-8000-000000000001"
    return {
        "email": email,
        "code": "000000",
        "kdfVersion": 1,
        "authKey": b64url(os.urandom(32)),
        "wrappedMasterKey": b64url(amk_mdp(compte)),
        "recovery": None,
        "keyring": b64url(trousseau(compte)),
    }


# Chaque cas : (route, fabrique du corps pour une adresse). Les corps portent
# une preuve FAUSSE : c'est la réponse d'échec qu'un sondeur observe.
CAS = {
    "signup/start": lambda e: {"email": e, "termsVersion": 1},
    "signup/verify": lambda e: {"email": e, "code": "000000"},
    "login": lambda e: {"email": e, "authKey": b64url(os.urandom(32))},
    "recovery/unwrap": lambda e: {
        "email": e,
        "recoveryAuthKey": b64url(os.urandom(32)),
    },
    "reset/request": lambda e: {"email": e},
    "reset/confirm": lambda e: {"email": e, "code": "000000"},
    "reset/complete": _corps_complete,
}


class TestEnumeration:
    @pytest.mark.parametrize("route", sorted(CAS))
    def test_octet_par_octet_pour_une_adresse_connue_ou_inconnue(self, service, route):
        """§3.5 — le même statut, le même corps et les mêmes en-têtes.

        Échec évité : un « un compte existe déjà » en clair, un 404 pour une
        adresse inconnue, ou un corps d'un octet plus long, et quiconque
        vérifiait qui a un compte Diapason à partir d'une liste d'adresses.
        """
        inscrit = service.inscrire("connue@exemple.org")
        # Hors des fenêtres d'envoi de l'inscription (1 par minute, 3 par h).
        service.horloge.avancer(2 * HEURE_MS)
        connue = service.post("/" + route, CAS[route](inscrit.email))
        inconnue = service.post("/" + route, CAS[route](INCONNUE))
        _identiques(connue, inconnue)
        assert connue.status_code < 500, f"{route} ne doit pas échouer en 5xx"

    def test_login_params_rend_la_meme_forme_pour_une_adresse_inconnue(self, service):
        """§3.4 — ``kdfVersion`` et un ``kdfSalt`` de même longueur :
        l'inconnue reçoit un sel déterministe, pas une erreur."""
        inscrit = service.inscrire("params@exemple.org")
        connue = service.post("/login/params", {"email": inscrit.email})
        inconnue = service.post("/login/params", {"email": INCONNUE})
        assert connue.status_code == inconnue.status_code == 200, "toujours 200"
        a, b = connue.json(), inconnue.json()
        assert a.keys() == b.keys(), "mêmes clés"
        assert a["kdfVersion"] == b["kdfVersion"] == 1, "même version"
        assert len(a["kdfSalt"]) == len(b["kdfSalt"]), "même longueur de sel"
        assert len(connue.content) == len(inconnue.content), "même longueur de corps"

    def test_login_params_est_stable_dans_le_temps(self, service):
        """§2.2 et étape 4 — même sel AVANT l'inscription, APRÈS, et après un
        changement de mot de passe. Un sel tiré à chaque changement laissait
        voir, en sondant ``login/params`` dans le temps, qu'une adresse
        s'inscrivait ou changeait de mot de passe."""
        email = "stable@exemple.org"
        avant = service.post("/login/params", {"email": email}).json()
        inscrit = service.inscrire(email)
        apres = service.post("/login/params", {"email": email}).json()
        assert inscrit.kdf_salt == avant["kdfSalt"], "verify rend le même sel"
        assert avant == apres, "même sel avant et après l'inscription"

        nouvelle = os.urandom(32)
        r = service.post(
            "/vault/commit",
            service.corps_commit(inscrit, nouvelle_auth=nouvelle),
            headers=inscrit.bearer,
        )
        assert r.status_code == 200, r.text
        rotation = service.post("/login/params", {"email": email}).json()
        assert rotation == avant, "même sel après un changement de mot de passe"

    def test_la_casse_et_les_espaces_ne_font_pas_une_autre_adresse(self, service):
        """§2.4 — ``NFKC``, ``strip``, ``lower`` : « Connue@… » et « connue@… »
        sont le même compte, donc le même sel."""
        service.inscrire("casse@exemple.org")
        a = service.post("/login/params", {"email": "  CASSE@Exemple.org "}).json()
        b = service.post("/login/params", {"email": "casse@exemple.org"}).json()
        assert a == b, "l'adresse est normalisée avant l'index"


def _changements(service) -> int:
    with service.ctx.base.lecture() as conn:
        return conn.total_changes


def _mesurer(service, route: str, email: str) -> int:
    avant = _changements(service)
    service.post("/" + route, CAS.get(route, lambda e: {"email": e})(email))
    return _changements(service) - avant


def _purger_d_abord(service) -> None:
    """Un appel sur une TROISIÈME adresse fait les purges du moment (codes
    expirés, fenêtres d'envoi, compteurs) : sans lui, le premier des deux
    appels mesurés paie seul une purge que le second ne voit plus."""
    service.post("/signup/start", {"email": "tiers@exemple.org", "termsVersion": 1})
    service.post(
        "/login", {"email": "tiers@exemple.org", "authKey": b64url(os.urandom(32))}
    )


# Ce qui précède chaque route mesurée, pour que le code visé existe.
PREALABLE = {
    "signup/verify": "signup/start",
    "reset/confirm": "reset/request",
    "reset/complete": "reset/request",
}


class TestMemeTravailPourConnueEtInconnue:
    """§3.5 — « même classe de temps ». Un ``COMMIT`` qui écrit se paie d'un
    ``fsync`` du WAL ; un ``COMMIT`` vide, non. Jusqu'au 24/09/2026,
    ``reset/request`` écrivait 5 lignes pour une adresse connue et 1 pour
    une inconnue, puis 0 contre 1 au second appel ; ``signup/start``, 0
    contre 3 ; ``signup/verify``, 0 contre 1."""

    @pytest.mark.parametrize("ecart_ms", [0, 2 * HEURE_MS])
    @pytest.mark.parametrize(
        "route", sorted(set(CAS) | {"login/params"} - {"reset/complete"})
    )
    def test_le_meme_nombre_d_ecritures_sur_deux_appels(self, service, route, ecart_ms):
        """Deux appels de suite, dans la même minute puis à deux heures
        d'écart (le second ``signup/start`` du jour, hors fenêtre)."""
        inscrit = service.inscrire("connue@exemple.org")
        # L'inscription date de la veille : ni la connue ni l'inconnue n'a de
        # marque du jour. Ces marques dépendent de ce que l'adresse a reçu
        # aujourd'hui, pas de l'existence du compte ; et de toute façon le
        # COMMIT écrit des deux côtés, ce qui ferme le canal du ``fsync``.
        service.horloge.avancer(JOUR_MS)
        connue: list[int] = []
        inconnue: list[int] = []
        for tour in range(2):
            if tour == 0 or ecart_ms:
                service.horloge.avancer(ecart_ms or 2 * HEURE_MS)
                _purger_d_abord(service)
            if tour == 0 and route in PREALABLE:
                for email in (inscrit.email, INCONNUE):
                    service.post("/" + PREALABLE[route], CAS[PREALABLE[route]](email))
            connue.append(_mesurer(service, route, inscrit.email))
            inconnue.append(_mesurer(service, route, INCONNUE))
        assert connue == inconnue, (
            f"{route} : écritures {connue} (connue) ≠ {inconnue} (inconnue)"
        )

    def test_reset_complete_ecrit_autant_pour_connue_et_inconnue(self, service):
        """Même mesure pour ``reset/complete``, dont le corps porte un coffre."""
        inscrit = service.inscrire("connue@exemple.org")
        service.horloge.avancer(2 * HEURE_MS)
        _purger_d_abord(service)
        for email in (inscrit.email, INCONNUE):
            service.post("/reset/request", {"email": email})
        mesures = {}
        for email in (inscrit.email, INCONNUE):
            avant = _changements(service)
            service.post("/reset/complete", _corps_complete(email))
            mesures[email] = _changements(service) - avant
        assert mesures[inscrit.email] == mesures[INCONNUE], f"écritures {mesures}"

    @pytest.mark.parametrize("route", ["login", "recovery/unwrap"])
    def test_le_meme_nombre_de_hmac_de_verification(self, service, monkeypatch, route):
        """§3.5 — l'adresse inconnue est comparée à un vérificateur factice.
        Sans lui, l'échec répondait sans HMAC, donc plus vite."""
        from diapason_comptes.secrets_serveur import SecretsServeur

        inscrit = service.inscrire("connue@exemple.org")
        appels: list[bytes] = []
        vraie = SecretsServeur.verifier_mac

        def compter(self, stocke, domaine, donnees):
            appels.append(domaine)
            return vraie(self, stocke, domaine, donnees)

        monkeypatch.setattr(SecretsServeur, "verifier_mac", compter)
        service.post("/" + route, CAS[route](inscrit.email))
        connue = list(appels)
        appels.clear()
        service.post("/" + route, CAS[route](INCONNUE))
        assert connue and connue == appels, (
            f"HMAC de vérification : {connue} (connue) ≠ {appels} (inconnue)"
        )


class TestBudgetGlobalSansEnumeration:
    """§3.5 — « ``mailUnavailable`` est global, donc sans risque
    d'énumération ». Faux jusqu'au 24/09/2026 : ``reset/request`` puisait
    dans le budget des codes pour une adresse connue, jamais pour une
    inconnue, et le second ``signup/start`` du jour faisait l'inverse. Sur
    un service peu fréquenté, le compteur global se devine : un bit par
    jour et par cible."""

    def _consommation(self, fabrique, tmp_path, connue: bool) -> list[int]:
        from diapason_comptes.limites import BUDGET_CODES

        service = fabrique(dossier=tmp_path / ("connue" if connue else "inconnue"))
        cible = "cible@exemple.org"
        if connue:
            service.inscrire(cible)
        else:
            service.inscrire("autre@exemple.org")
        service.horloge.avancer(2 * HEURE_MS)
        releves = []
        for chemin, corps in (
            ("/reset/request", {"email": cible}),
            ("/reset/request", {"email": cible}),
            ("/signup/start", {"email": cible, "termsVersion": 1}),
            ("/signup/start", {"email": cible, "termsVersion": 1}),
        ):
            service.horloge.avancer(2 * HEURE_MS)
            assert service.post(chemin, corps).status_code == 202, chemin
            with service.ctx.base.lecture() as conn:
                releves.append(
                    service.ctx.courrier.budgets.envois_du_jour(
                        conn, BUDGET_CODES, service.horloge()
                    )
                )
        return releves

    def test_le_budget_des_codes_bouge_pareil_pour_connue_et_inconnue(
        self, fabrique, tmp_path
    ):
        connue = self._consommation(fabrique, tmp_path, connue=True)
        inconnue = self._consommation(fabrique, tmp_path, connue=False)
        assert connue == inconnue, (
            f"budget global : {connue} (connue) ≠ {inconnue} (inconnue)"
        )
