"""Ouvrir une application du BUREAU depuis un appareil appairé.

Les quatre autres outils du maillage pilotent Succès : « app.open » pousse
``success://today``. « Ouvre l'écran Notes sur mon MacBook » n'avait donc
aucun vocabulaire pour exister — la demande partait vers L'Entité, qui parle
au serveur PHP et réclame un jeton sans rapport.

Le propriétaire a choisi la portée OUVERTE, après avoir vu les trois
possibles (validation, liste blanche, ouvert). Ce que ces tests gardent, ce
n'est donc pas une restriction de cible : c'est que le verdict soit vrai, et
que ce qui protège encore ne dépende pas de l'appelant.
"""

from __future__ import annotations

import secrets

import pytest

from diapason.mesh import executor as mesh_executor
from diapason.mesh.capabilities import ALL_CAPABILITIES
from diapason.mesh.commands import RemoteCommand, now_ms
from diapason.mesh.tools import REMOTE_TOOLS


def commande(**arguments) -> RemoteCommand:
    return RemoteCommand(
        version=1,
        command_id=f"cmd_{secrets.token_hex(8)}",
        owner_id="owner_1",
        origin_device_id="dev_phone",
        target_device_id="mac-1",
        tool="desktop.open",
        arguments=arguments,
        created_at_ms=now_ms(),
        expires_at_ms=now_ms() + 300_000,
        nonce=secrets.token_hex(12),
        idempotency_key=f"idem_{secrets.token_hex(8)}",
        requires_confirmation=False,
    )


class FauxOutil:
    """Remplace open_anything : les tests ne doivent ouvrir aucune app."""

    def __init__(self, success=True, content="Opened app Notes"):
        self._success = success
        self._content = content
        self.appels: list[dict] = []

    def execute(self, **kw):
        self.appels.append(kw)
        from diapason.core.types import ToolResult

        return ToolResult(
            tool_name="open_anything", success=self._success, content=self._content
        )


@pytest.fixture
def faux(monkeypatch):
    outil = FauxOutil()

    class FauxRegistre:
        @staticmethod
        def get(_name):
            return lambda: outil

    monkeypatch.setattr(
        "diapason.core.registry.ToolRegistry", FauxRegistre, raising=False
    )
    return outil


class TestLOrdreEstTransmisTelQuel:
    def test_la_cible_arrive_intacte(self, faux):
        r = mesh_executor._desktop_open(commande(target="Notes", kind="app"))
        assert r["ok"] is True
        assert faux.appels == [{"target": "Notes", "kind": "app"}]

    def test_le_genre_par_defaut_est_auto(self, faux):
        mesh_executor._desktop_open(commande(target="youtube.com"))
        assert faux.appels[0]["kind"] == "auto"

    def test_le_message_de_l_outil_est_relaye(self, faux):
        r = mesh_executor._desktop_open(commande(target="Notes"))
        assert r["userSafeMessage"] == "Opened app Notes"


class TestUnEchecResteUnEchec:
    """Annoncer « ouvert » sur un échec serait exactement le défaut que
    l'audit a passé la semaine à retirer de ce dépôt."""

    def test_un_refus_de_l_outil_n_est_pas_maquille(self, monkeypatch):
        outil = FauxOutil(success=False, content="Application introuvable.")

        class FauxRegistre:
            @staticmethod
            def get(_name):
                return lambda: outil

        monkeypatch.setattr(
            "diapason.core.registry.ToolRegistry", FauxRegistre, raising=False
        )
        r = mesh_executor._desktop_open(commande(target="AppQuiNExistePas"))
        assert r["ok"] is False
        assert "introuvable" in r["userSafeMessage"]

    def test_une_cible_vide_est_refusee(self):
        r = mesh_executor._desktop_open(commande(target="   "))
        assert r["ok"] is False
        assert "cible" in r["userSafeMessage"].lower()

    def test_un_outil_absent_refuse_au_lieu_de_lever(self, monkeypatch):
        """Sur une machine sans desktop_tools, l'ordre doit être refusé
        proprement — pas remonter en erreur 500 côté route."""

        class RegistreVide:
            @staticmethod
            def get(_name):
                raise KeyError(_name)

        monkeypatch.setattr(
            "diapason.core.registry.ToolRegistry", RegistreVide, raising=False
        )
        r = mesh_executor._desktop_open(commande(target="Notes"))
        assert r["ok"] is False
        assert "disponible" in r["userSafeMessage"]


class TestLaDeclarationEstCoherente:
    def test_l_outil_est_au_catalogue(self):
        assert "desktop.open" in REMOTE_TOOLS
        assert REMOTE_TOOLS["desktop.open"].capability == "desktop.open"

    def test_la_capacite_est_connue(self):
        assert "desktop.open" in ALL_CAPABILITIES

    def test_il_exige_un_appareil_en_ligne(self):
        """Ouvrir quelque chose des heures plus tard, sur une machine dont on
        ne sait plus ce qu'elle affiche, serait une surprise, pas un
        service."""
        assert REMOTE_TOOLS["desktop.open"].offline_policy == "REQUIRE_ONLINE"

    def test_il_a_son_propre_gestionnaire(self):
        """Le dispatcher résout par nom exact : pas de nom dynamique venu de
        l'émetteur, sinon un catalogue étroit devient universel."""
        assert mesh_executor._HANDLERS["desktop.open"] is mesh_executor._desktop_open

    def test_seuls_les_ordinateurs_peuvent_l_offrir(self):
        """Le plafond par plateforme fait le tri : un téléphone ne doit pas
        pouvoir DÉCLARER cette capacité, seulement s'en servir à distance.
        C'est la différence entre commander un bureau et en être un."""
        from diapason.mesh.capabilities import PLATFORM_CAPABILITIES as P

        assert "desktop.open" in P["MACOS"]
        assert "desktop.open" in P["WINDOWS"]
        assert "desktop.open" not in P["ANDROID"]
        assert "desktop.open" not in P["IOS"]
