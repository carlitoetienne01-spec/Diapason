"""La télécommande du téléphone, jugée par le vrai contrôle n°10.

26/09/2026, phase 2 étape 7 (docs/development/diapason-mobile.md). Le
téléphone signait ``desktop.open`` avec ``requiresConfirmation: false``
(``mesh_api.dart:155``) ; depuis le 25 août (921acb9), le contrôle n°10 de
``verify_command`` refuse un outil à fort impact non confirmé : la
télécommande était refusée à chaque appui, et rien de ce dépôt ne le voyait.

Les enveloppes ne sont PAS écrites ici : elles sortent du vrai
``MeshApi.enveloppeDeCommande`` du dépôt mobile, signées par une clé fixe
(``test/mesh/telecommande_confirmee_test.dart``). Une enveloppe écrite par
Python aurait porté l'idée que Python se fait du Dart. Même chemin, même
règle que les vecteurs canoniques : hors CI, un dépôt mobile absent est un
ÉCHEC, pas un saut.
"""

from __future__ import annotations

import base64
import json
import os

import pytest
from _depot_mobile import depot_mobile

from diapason.mesh.commands import CommandRejected, verify_command

MOBILE = depot_mobile()
FIXTURE = MOBILE / "test/mesh/telecommande_signee.json"


def _en_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _fixture() -> dict:
    try:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))
    except OSError:
        if _en_ci():
            pytest.skip(f"{FIXTURE} absent du runner de CI")
        pytest.fail(
            f"{FIXTURE} introuvable ou illisible. Le dépôt mobile doit vivre "
            f"dans {MOBILE} ; hors CI, son absence n'est pas un saut : c'est "
            "la télécommande qui n'est plus éprouvée sur ce que le Dart signe."
        )


class _Registre:
    """Le seul appareil connu : le téléphone de la fixture, par sa clé.

    Les octets bruts, comme ``DeviceRegistry.public_key_of`` les rend.
    """

    def __init__(self, appareil: str, cle_b64: str) -> None:
        self._appareil, self._cle = appareil, base64.b64decode(cle_b64)

    def public_key_of(self, device_id: str) -> bytes | None:
        return self._cle if device_id == self._appareil else None


class _Nonces:
    def spend(self, nonce: str, device_id: str) -> bool:
        return True


@pytest.fixture()
def juger(monkeypatch):
    """``verify_command`` tel que le Mac l'applique, à l'heure de l'ordre.

    La capacité ``desktop.open`` est posée explicitement : le plafond de la
    plateforme dépend de la machine qui lance les tests, et le contrôle
    n°9 (capacités) passe avant le n°10.
    """
    monkeypatch.setattr(
        "diapason.mesh.capabilities.local_capabilities",
        lambda: frozenset({"desktop.open"}),
    )
    fixture = _fixture()

    def _juger(cas: str):
        brute = fixture["cas"][cas]
        return verify_command(
            brute,
            registry=_Registre(fixture["originDeviceId"], fixture["publicKey"]),
            local_device_id=brute["targetDeviceId"],
            local_owner_id=brute["ownerId"],
            nonces=_Nonces(),
            now=brute["createdAtMs"] + 1_000,
        )

    return _juger


class TestLaTelecommandeDuTelephone:
    def test_confirmee_sur_le_telephone_elle_passe_le_controle_10(self, juger):
        commande = juger("confirmee")
        assert commande.tool == "desktop.open", "l'ordre doit être desktop.open"
        assert commande.requires_confirmation is True, (
            "la confirmation signée par le téléphone doit être lue comme telle"
        )

    def test_non_confirmee_elle_est_refusee(self, juger):
        with pytest.raises(CommandRejected) as refus:
            juger("nonConfirmee")
        assert refus.value.code == "DENIED", (
            "sans confirmation, desktop.open doit rendre DENIED"
        )
        assert "exige une confirmation explicite" in refus.value.message, (
            f"le refus doit venir du contrôle n°10, pas d'un autre : "
            f"{refus.value.message}"
        )

    def test_les_deux_cas_ne_different_que_par_la_confirmation(self):
        """Sinon le refus pourrait venir d'autre chose que la valeur signée."""
        cas = _fixture()["cas"]
        a, b = dict(cas["confirmee"]), dict(cas["nonConfirmee"])
        for enveloppe in (a, b):
            for cle in ("signature", "commandId", "nonce", "idempotencyKey"):
                enveloppe.pop(cle)
        assert a.pop("requiresConfirmation") is True
        assert b.pop("requiresConfirmation") is False
        assert a == b, "hors identifiants, les deux ordres doivent être égaux"
