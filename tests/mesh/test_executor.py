"""What this device may claim to have done — and what it may not.

26 August 2026, measured on real hardware. A Windows PC ran the Python server
with no window open. Notifications sent from the Mac over a sealed channel
came back SUCCESS / « Notification affichée. », were recorded as such on both
machines, and were displayed nowhere: `_notify` pushed an entry onto an
in-memory list and returned a sentence in the past tense. Nothing on this
side had a screen.

Spec §100 — never a false SUCCESS — and §5 — never pretend a capability
exists. The property under test is that a handler states a verdict it can
actually support, and refuses out loud when it cannot.
"""

from __future__ import annotations

import pytest

from diapason.mesh import executor as ex
from diapason.mesh.commands import build_command


@pytest.fixture(autouse=True)
def clean_shell_state():
    """Module globals: reset both, both ways, or tests leak into each other."""
    ex._pending.clear()
    ex._last_collection_ms = None
    yield
    ex._pending.clear()
    ex._last_collection_ms = None


def a_command(tool: str, **arguments):
    return build_command(
        owner_id="owner_test",
        origin_device_id="dev_mac",
        target_device_id="dev_pc",
        tool=tool,
        arguments=arguments,
    )


class TestUnEcranSeConstate:
    """Un pair qui relève la boîte est la SEULE preuve qu'une fenêtre existe."""

    def test_sans_aucune_releve_personne_ne_regarde(self):
        assert ex.shell_is_collecting() is False, (
            "un processus qui vient de démarrer n'a pas de fenêtre attachée"
        )

    def test_une_releve_qui_vide_compte(self):
        ex.pending_navigations(drain=True)
        assert ex.shell_is_collecting() is True

    def test_une_lecture_de_diagnostic_ne_compte_pas(self):
        """Regarder n'est pas relever.

        `drain=False` est la lecture qu'un `curl` de mise au point fait. Si
        elle comptait, une session de débogage ferait croire à la machine que
        quelqu'un surveille l'écran, et la remettrait à mentir.
        """
        ex.pending_navigations(drain=False)
        assert ex.shell_is_collecting() is False

    def test_une_fenetre_qui_se_tait_cesse_de_compter(self):
        """La fenêtre relève toutes les 2 s, bridée à 1/min si elle est
        cachée. Au-delà de la fenêtre de tolérance, elle est partie."""
        ex.pending_navigations(drain=True)
        depart = ex._last_collection_ms
        assert ex.shell_is_collecting(now=depart + ex._COLLECTION_WINDOW_MS - 1)
        assert not ex.shell_is_collecting(now=depart + ex._COLLECTION_WINDOW_MS)

    def test_la_tolerance_couvre_un_cycle_bride_entier(self):
        """Le nombre porte sa raison : un onglet caché est ramené par le
        navigateur à environ une minuterie par minute. Moins de 60 s
        refuserait une fenêtre simplement en arrière-plan."""
        assert ex._COLLECTION_WINDOW_MS > 60_000


class TestRienNEstAnnonceSansEcran:
    def test_une_notification_sans_fenetre_est_refusee(self):
        """LE défaut du 26 août 2026, dans sa forme la plus courte."""
        resultat = ex._notify(a_command("notifications.show", title="a", body="b"))
        assert resultat["ok"] is False, (
            "sans fenêtre, rien n'a été affiché — le dire est le minimum"
        )
        assert resultat["errorCode"] == "NO_SHELL"
        assert "affich" in resultat["userSafeMessage"]

    def test_rien_n_est_empile_quand_personne_ne_releve(self):
        """Empiler serait pire que refuser : l'entrée surgirait des heures
        plus tard, hors contexte, ou serait jetée par `_MAX_PENDING` sans un
        mot."""
        ex._notify(a_command("notifications.show", title="a", body="b"))
        assert ex._pending == [], "une notification refusée ne se met pas en file"

    def test_avec_une_fenetre_la_notification_est_remise(self):
        ex.pending_navigations(drain=True)
        resultat = ex._notify(a_command("notifications.show", title="a", body="b"))
        assert resultat["ok"] is True
        assert len(ex._pending) == 1

    def test_la_phrase_ne_dit_plus_affichee(self):
        """Remettre est ce qui vient de se passer ; afficher est ce que la
        fenêtre fera ensuite. L'écart fait deux secondes et reste un écart."""
        ex.pending_navigations(drain=True)
        resultat = ex._notify(a_command("notifications.show", title="a", body="b"))
        assert "affichée" not in resultat["userSafeMessage"]

    @pytest.mark.parametrize(
        "outil,arguments",
        [
            ("app.navigate", {"route": "success://today"}),
            ("app.show_resource", {"resourceType": "task", "resourceId": "t1"}),
            ("app.open", {}),
            ("notifications.show", {"title": "a", "body": "b"}),
        ],
    )
    def test_aucun_ecran_ne_s_annonce_ouvert_sans_fenetre(self, outil, arguments):
        """Les quatre outils d'écran partageaient le même mensonge."""
        resultat = ex._HANDLERS[outil](a_command(outil, **arguments))
        assert resultat["ok"] is False, f"{outil} annonce un écran sans fenêtre"


class TestChaqueExecuteurRendUnVerdict:
    """« ok » est exigé, jamais supposé — sinon le silence repasse pour un
    succès, qui est la forme exacte du défaut corrigé ce jour."""

    @pytest.mark.parametrize("outil", sorted(ex._HANDLERS))
    def test_avec_une_fenetre(self, outil):
        ex.pending_navigations(drain=True)
        resultat = ex._HANDLERS[outil](a_command(outil))
        assert "ok" in resultat, f"{outil} ne dit pas si l'action a abouti"

    @pytest.mark.parametrize("outil", sorted(ex._HANDLERS))
    def test_sans_fenetre(self, outil):
        resultat = ex._HANDLERS[outil](a_command(outil))
        assert "ok" in resultat, f"{outil} ne dit pas si l'action a abouti"

    def test_un_executeur_muet_est_un_echec_pas_un_succes(self, monkeypatch):
        """La branche de garde de `local_executor`. Les deux issues n'ont pas
        le même coût : deviner « réussi » ici est par où tout a commencé."""
        monkeypatch.setitem(ex._HANDLERS, "app.open", lambda cmd: {"route": "x"})
        resultat = ex.local_executor(a_command("app.open"))
        assert resultat["ok"] is False
        assert resultat["errorCode"] == "EXECUTOR_SILENT"


class TestUnMessageNeContreditPasSonVerdict:
    """26 août 2026, mesuré sur le PC Windows de Carlito.

    `open_anything` y rend `success=False` avec le contenu « Started
    ApplicationQuiNExistePasDuTout » pour une application qui n'existe pas.
    Relayé tel quel, cela donnait un échec dont la phrase annonçait un
    succès — et c'est cette phrase, pas le drapeau, que l'utilisateur lit.
    """

    def _outil(self, monkeypatch, *, success, content):
        class FauxResultat:
            pass

        faux = FauxResultat()
        faux.success = success
        faux.content = content

        class FauxOutil:
            def execute(self, **_):
                return faux

        from diapason.core.registry import ToolRegistry

        monkeypatch.setattr(ToolRegistry, "get", staticmethod(lambda _n: FauxOutil))

    def test_un_echec_ne_peut_pas_dire_started(self, monkeypatch):
        self._outil(monkeypatch, success=False, content="Started Machin")
        resultat = ex._desktop_open(a_command("desktop.open", target="Machin"))
        assert resultat["ok"] is False
        assert resultat["userSafeMessage"].startswith("Échec"), (
            "un échec dont le message annonce un succès est pire qu'un "
            "message vide : l'utilisateur lit la phrase, pas le drapeau"
        )
        assert "Started Machin" in resultat["userSafeMessage"], (
            "la raison de l'outil reste utile — elle est encadrée, pas jetée"
        )

    def test_un_succes_garde_la_phrase_de_l_outil(self, monkeypatch):
        self._outil(monkeypatch, success=True, content="Safari est ouvert.")
        resultat = ex._desktop_open(a_command("desktop.open", target="Safari"))
        assert resultat == {"ok": True, "userSafeMessage": "Safari est ouvert."}


class TestUneFilePleineNeMentPasNonPlus:
    """Le dernier faux SUCCESS de la chaîne, celui du débordement.

    `push_navigation` jetait la PLUS ANCIENNE entrée — `del
    _pending[:-_MAX_PENDING]` — sans un mot. Or cette entrée-là avait déjà
    valu un SUCCESS à l'appareil qui l'avait envoyée : la jeter transformait
    après coup une promesse tenue en mensonge, et rien nulle part ne le
    consignait.

    Le cas est atteignable dès qu'un pair revient d'une heure hors ligne :
    `flush_pending` livre jusqu'à VINGT commandes par appareil en un seul
    battement (`dispatch.limit_per_device`) quand cette file en tient SEIZE.
    """

    def test_la_file_tient_seize(self):
        ex.pending_navigations(drain=True)
        for i in range(ex._MAX_PENDING):
            assert ex.push_navigation({"route": f"r{i}"}) is True
        assert len(ex._pending) == ex._MAX_PENDING

    def test_la_dix_septieme_est_refusee_pas_avalee(self):
        ex.pending_navigations(drain=True)
        for i in range(ex._MAX_PENDING):
            ex.push_navigation({"route": f"r{i}"})
        assert ex.push_navigation({"route": "trop"}) is False
        routes = [e["route"] for e in ex._pending]
        assert routes[0] == "r0", (
            "la plus ancienne avait déjà valu un SUCCESS : la jeter ment "
            "rétroactivement"
        )
        assert "trop" not in routes

    def test_l_outil_le_dit_a_l_emetteur(self):
        """Refuser sans le dire ne vaudrait pas mieux que jeter en silence."""
        ex.pending_navigations(drain=True)
        for i in range(ex._MAX_PENDING):
            ex.push_navigation({"route": f"r{i}"})
        resultat = ex._notify(a_command("notifications.show", title="a", body="b"))
        assert resultat["ok"] is False
        assert resultat["errorCode"] == "SHELL_QUEUE_FULL"

    def test_la_file_est_plus_petite_que_ce_qu_un_battement_livre(self):
        """Le nombre porte sa raison — et ici, deux constantes se parlent."""
        import inspect

        from diapason.mesh import dispatch

        par_battement = (
            inspect.signature(dispatch.flush_pending)
            .parameters["limit_per_device"]
            .default
        )
        assert ex._MAX_PENDING < par_battement, (
            "si la file devenait plus grande que ce qu'un battement livre, "
            "ce test deviendrait tautologique — il garde le cas RÉEL"
        )
