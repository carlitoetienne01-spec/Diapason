"""La perception du bureau : lecture, cache, description française."""

from __future__ import annotations

import diapason.desktop.etat_bureau as eb
from diapason.desktop.etat_bureau import (
    EtatBureau,
    decrire,
    etat_du_bureau,
    interpreter,
)

SORTIE = "App Store\nSafari|Notes|WhatsApp|App Store\n"


def _sans_cache(monkeypatch):
    monkeypatch.setattr(eb, "_cache", None)


class TestInterpreter:
    def test_le_premier_plan_et_les_apps_se_lisent(self):
        etat = interpreter(SORTIE)
        assert etat.premier_plan == "App Store"
        assert etat.en_marche == ("Safari", "Notes", "WhatsApp", "App Store")

    def test_une_sortie_vide_rend_none(self):
        assert interpreter("") is None
        assert interpreter("\n") is None


class TestCache:
    def test_le_cliche_frais_ne_relit_pas(self, monkeypatch):
        _sans_cache(monkeypatch)
        lectures = []

        def runner(_s):
            lectures.append(1)
            return SORTIE

        pendule = {"t": 100.0}
        horloge = lambda: pendule["t"]  # noqa: E731
        monkeypatch.setattr("time.monotonic", horloge)
        etat_du_bureau(runner=runner, horloge=horloge)
        pendule["t"] += 2.0
        etat_du_bureau(runner=runner, horloge=horloge)
        assert len(lectures) == 1
        pendule["t"] += 10.0
        etat_du_bureau(runner=runner, horloge=horloge)
        assert len(lectures) == 2

    def test_une_lecture_en_panne_garde_le_vieux_cliche(self, monkeypatch):
        _sans_cache(monkeypatch)

        def casse(_s):
            raise RuntimeError("osascript grognon")

        pendule = {"t": 100.0}
        horloge = lambda: pendule["t"]  # noqa: E731
        monkeypatch.setattr("time.monotonic", horloge)
        etat_du_bureau(runner=lambda _s: SORTIE, horloge=horloge)
        pendule["t"] += 60.0
        etat = etat_du_bureau(runner=casse, horloge=horloge)
        assert etat is not None and etat.premier_plan == "App Store"


class TestDecrire:
    def test_une_phrase_francaise_prete_pour_le_contexte(self):
        etat = EtatBureau("App Store", ("Safari", "Notes", "App Store"), 0.0)
        assert decrire(etat) == (
            "État du bureau : au premier plan, App Store. "
            "Aussi en marche : Safari, Notes."
        )

    def test_la_liste_longue_se_coupe_et_se_compte(self):
        etat = EtatBureau("Safari", tuple(f"App{i}" for i in range(20)), 0.0)
        texte = decrire(etat, limite=3)
        assert "App0, App1, App2 (+17)" in texte


class TestTitreEtOnglet:
    """« Safari » ne dit rien ; « Safari — Gmail, brouillon à Julie » dit
    tout, sans capture d'écran (Atlas, 24 août 2026)."""

    def test_le_titre_de_fenetre_se_lit_en_troisieme_ligne(self):
        etat = interpreter("Mail\nMail|Finder\nBoîte de réception — 3 messages")
        assert etat.titre_fenetre == "Boîte de réception — 3 messages"
        assert etat.onglet == ""

    def test_une_sortie_sans_titre_reste_lisible(self):
        """L'ancien format à deux lignes ne casse pas : titre vide."""
        etat = interpreter("Mail\nMail|Finder")
        assert etat.titre_fenetre == ""
        assert etat.premier_plan == "Mail"

    def test_l_onglet_n_est_demande_qu_a_un_navigateur_connu(self, monkeypatch):
        """Le contrat testé ici est la DÉCISION d'aller chercher l'onglet ;
        la lecture elle-même est testée juste en dessous, avec son runner.
        (La garde autouse du dossier neutralise onglet_actif : on l'espionne
        plutôt que de la contourner.)"""
        import diapason.desktop.etat_bureau as eb

        demandes = []
        monkeypatch.setattr(
            eb, "onglet_actif", lambda app, *_a, **_k: demandes.append(app) or "Gmail"
        )
        etat = eb.interpreter("Google Chrome\nGoogle Chrome|Finder\nGmail")
        assert demandes == ["Google Chrome"]
        assert etat.onglet == "Gmail"

        demandes.clear()
        eb.interpreter("Mail\nMail|Finder\nBoîte")
        assert demandes == []  # Mail n'est pas un navigateur : rien n'est demandé

    def test_un_navigateur_inconnu_ne_compile_aucun_script(self):
        """Un `tell application` littéral pour une app non installée ouvre une
        boîte « Où se trouve… ? » qu'aucun try ne rattrape — d'où la liste
        blanche."""
        import importlib

        vrai = importlib.reload(
            importlib.import_module("diapason.desktop.etat_bureau")
        ).onglet_actif
        appels = []
        assert vrai("Opera GX", lambda s: appels.append(s) or "x") == ""
        assert appels == []

    def test_un_onglet_illisible_se_tait(self):
        import importlib

        def casse(_s):
            raise RuntimeError("automatisation refusée")

        vrai = importlib.reload(
            importlib.import_module("diapason.desktop.etat_bureau")
        ).onglet_actif
        assert vrai("Safari", casse) == ""

    def test_la_phrase_reste_identique_sans_precision(self):
        """Comparée à l'égalité ailleurs : elle ne doit pas bouger d'un octet."""
        etat = EtatBureau("Mail", ("Mail", "Finder"), 0.0)
        assert decrire(etat) == (
            "État du bureau : au premier plan, Mail. Aussi en marche : Finder."
        )

    def test_l_onglet_prime_sur_le_titre_dans_la_phrase(self):
        etat = EtatBureau(
            "Safari", ("Safari",), 0.0, titre_fenetre="Safari", onglet="EF SET — test"
        )
        assert "Safari — EF SET — test" in decrire(etat)
