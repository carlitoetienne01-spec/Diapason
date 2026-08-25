"""« Pas encore » n'est pas « refusé ».

Un appareil en mode pull va CHERCHER ses commandes : le verdict n'existe pas
quand ``dispatch`` rend la main, seulement quelques centaines de
millisecondes plus tard. ``mesh_send`` rendait donc ``success=False`` avec un
message de réussite — « C'est prêt pour Mon téléphone » — et la commande
passait à SUCCESS deux secondes après. Mesuré sur le vrai téléphone : 1,9 s.

Un agent qui lit ce drapeau conclut à une panne, réessaie, ou annonce un
échec qui n'a pas eu lieu. C'est le motif inverse de celui que l'audit a
traqué : non plus un échec déguisé en succès, mais une attente déguisée en
échec.
"""

from __future__ import annotations

from typing import Any

import pytest

from diapason.tools import mesh_tools


class FausseFile:
    """File dont le statut change au n-ième regard, comme un vrai appareil."""

    def __init__(self, statuts: list[str], message: str = "Fait."):
        self._statuts = list(statuts)
        self._message = message
        self.lectures = 0

    def get(self, command_id: str) -> dict[str, Any]:
        self.lectures += 1
        statut = self._statuts[min(self.lectures - 1, len(self._statuts) - 1)]
        return {"status": statut, "user_message": self._message}


def outil(queue) -> Any:
    """`queue` est une propriété en lecture seule sur l'outil réel : on
    sous-classe pour la fournir, plutôt que de forcer l'attribut."""

    class OutilDeBanc(mesh_tools.MeshSendTool):
        @property
        def queue(self):  # type: ignore[override]
            return queue

    return OutilDeBanc.__new__(OutilDeBanc)


BASE = {
    "status": "QUEUED",
    "commandId": "cmd_test",
    "userSafeMessage": "C'est prêt pour Mon téléphone.",
}


@pytest.fixture(autouse=True)
def _fenetre_courte(monkeypatch):
    """Les tests ne doivent pas dormir quatre secondes pour prouver ceci."""
    monkeypatch.setattr(mesh_tools, "_ACK_WAIT_S", 0.4)
    monkeypatch.setattr(mesh_tools, "_ACK_POLL_S", 0.05)


class TestLAttenteRendLeVraiVerdict:
    def test_un_appareil_qui_repond_donne_un_succes(self):
        """Le cas mesuré en vrai : le téléphone récupère et exécute."""
        r = outil(
            FausseFile(["QUEUED", "SUCCESS"], "Notification affichée.")
        )._await_ack(dict(BASE))
        assert r["status"] == "SUCCESS"
        assert r["userSafeMessage"] == "Notification affichée."
        assert not r.get("pending")

    def test_un_echec_distant_reste_un_echec(self):
        """L'attente ne doit pas transformer un refus en réussite."""
        r = outil(FausseFile(["FAILED"], "L'appareil a refusé."))._await_ack(dict(BASE))
        assert r["status"] == "FAILED"
        assert r["status"] not in mesh_tools._DONE

    def test_un_appareil_endormi_reste_en_attente(self):
        """Un téléphone qui dort n'a rien refusé. Le message d'origine dit
        déjà « à son réveil » ; le drapeau ``pending`` permet de distinguer
        cette attente d'un refus, ce que ``success=False`` seul ne faisait
        pas."""
        r = outil(FausseFile(["QUEUED"]))._await_ack(dict(BASE))
        assert r["status"] == "QUEUED"
        assert r["pending"] is True
        assert r["userSafeMessage"] == BASE["userSafeMessage"]

    def test_sans_identifiant_de_commande_on_n_attend_pas(self):
        sans = {k: v for k, v in BASE.items() if k != "commandId"}
        file = FausseFile(["SUCCESS"])
        assert outil(file)._await_ack(sans) == sans
        assert file.lectures == 0, "aucune lecture sans identifiant"

    def test_une_file_illisible_ne_fait_pas_tomber_l_envoi(self):
        class FileCassee:
            def get(self, _):
                raise RuntimeError("base verrouillée")

        r = outil(FileCassee())._await_ack(dict(BASE))
        assert r["status"] == "QUEUED", "on rend l'issue d'origine, sans lever"
