"""La cloche s'annonce : une demande d'approbation se voit hors de l'app.

Deux confirmations avaient déjà expiré sans que Carlito le sache (Atlas,
24 août 2026) : la cloche ne vit que dans la fenêtre de l'application. Le
fail-closed est bon, mais il ne doit pas être muet.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from diapason.server import approval_bridge


def _annoncer_et_attendre(prompt, **kw):
    """L'annonce part en tâche de fond ; le test attend qu'elle se pose."""
    with patch("diapason.heartbeat.livraison.notifier_macos") as notifier:
        approval_bridge._annoncer_la_demande(prompt, **kw)
        for _ in range(200):
            if notifier.call_args is not None:
                break
            time.sleep(0.01)
    return notifier.call_args


def test_le_nom_de_l_outil_prime_sur_les_arguments():
    """« Diapason veut utiliser shell_exec » se lit d'un coup d'œil ; le
    JSON des arguments ne tient pas dans une bannière."""
    assert (
        approval_bridge.resumer_la_demande(
            "Allow execution of tool 'shell_exec' with args {\"cmd\": \"ls\"}?"
        )
        == "Diapason veut utiliser shell_exec"
    )
    assert approval_bridge.resumer_la_demande("") == "Diapason demande une autorisation"


def test_l_annonce_dit_la_demande_et_ou_repondre():
    titre, corps = _annoncer_et_attendre(
        "Allow execution of tool 'open_anything' with args {}?"
    )[0]
    assert "accord" in titre.lower()
    assert "open_anything" in corps
    assert "Diapason" in corps


def test_l_annonce_ne_bloque_pas_l_attente():
    """notifier_macos peut attendre osascript dix secondes — un quart du
    budget vocal. L'annonce part en fond et rend la main tout de suite."""
    lent = threading.Event()

    def _lent(*_a, **_k):
        lent.wait(5.0)
        return (True, "")

    with patch("diapason.heartbeat.livraison.notifier_macos", _lent):
        debut = time.monotonic()
        approval_bridge._annoncer_la_demande("peu importe")
        ecoule = time.monotonic() - debut
    lent.set()
    assert ecoule < 0.5


def test_la_relance_dit_le_temps_restant():
    corps = _annoncer_et_attendre("supprimer une tâche", restant_s=45)[0][1]
    assert "45 s" in corps


def test_un_prompt_fleuve_est_tronque():
    assert len(_annoncer_et_attendre("x" * 500)[0][1]) < 200


def test_une_notification_en_panne_ne_casse_rien():
    with patch(
        "diapason.heartbeat.livraison.notifier_macos",
        side_effect=RuntimeError("osascript absent"),
    ):
        approval_bridge._annoncer_la_demande("peu importe")  # ne lève pas
        time.sleep(0.05)


def test_la_demande_est_annoncee_des_la_mise_en_file():
    """Le contrat qui compte : annoncer AVANT d'attendre, pas après."""
    from diapason.tools.approval_store import STATUS_DENIED

    class _Action:
        id = "a1"
        status = STATUS_DENIED

    class _Store:
        def queue_action(self, **_kw):
            return _Action()

        def get_action(self, _id):
            return _Action()

        def update_status(self, *_a):
            pass

        def close(self):
            pass

    with patch("diapason.tools.approval_store.ApprovalStore", _Store):
        with patch.object(approval_bridge, "_annoncer_la_demande") as annonce:
            assert approval_bridge._await_decision("ouvrir Safari", 1.0) is False
    annonce.assert_called_once()
