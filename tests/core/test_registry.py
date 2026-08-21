"""Tests for the decorator-based registry system."""

from __future__ import annotations

import pytest

from diapason.core.registry import (
    EngineRegistry,
    ModelRegistry,
    RouterPolicyRegistry,
)


class TestRegistryBase:
    def test_register_and_get(self) -> None:
        @ModelRegistry.register("test-model")
        class _Dummy:
            pass

        assert ModelRegistry.get("test-model") is _Dummy

    def test_register_value(self) -> None:
        ModelRegistry.register_value("val", 42)
        assert ModelRegistry.get("val") == 42

    def test_duplicate_raises(self) -> None:
        ModelRegistry.register_value("dup", 1)
        with pytest.raises(ValueError, match="already has an entry"):
            ModelRegistry.register_value("dup", 2)

    def test_get_missing_raises(self) -> None:
        with pytest.raises(KeyError, match="does not have an entry"):
            ModelRegistry.get("nonexistent")

    def test_create_instantiates(self) -> None:
        @ModelRegistry.register("factory")
        class _Cls:
            def __init__(self, x: int) -> None:
                self.x = x

        obj = ModelRegistry.create("factory", 7)
        assert obj.x == 7

    def test_create_non_callable_raises(self) -> None:
        ModelRegistry.register_value("plain", "hello")
        with pytest.raises(TypeError, match="not callable"):
            ModelRegistry.create("plain")

    def test_items(self) -> None:
        ModelRegistry.register_value("a", 1)
        ModelRegistry.register_value("b", 2)
        assert dict(ModelRegistry.items()) == {"a": 1, "b": 2}

    def test_keys(self) -> None:
        ModelRegistry.register_value("x", 10)
        ModelRegistry.register_value("y", 20)
        assert set(ModelRegistry.keys()) == {"x", "y"}

    def test_contains(self) -> None:
        ModelRegistry.register_value("present", True)
        assert ModelRegistry.contains("present")
        assert not ModelRegistry.contains("absent")

    def test_clear(self) -> None:
        ModelRegistry.register_value("temp", 0)
        ModelRegistry.clear()
        assert ModelRegistry.keys() == ()

    def test_isolation_between_registries(self) -> None:
        """Entries in ModelRegistry must not leak into EngineRegistry."""
        ModelRegistry.register_value("shared-key", "model")
        with pytest.raises(KeyError):
            EngineRegistry.get("shared-key")


class TestRouterPolicyRegistry:
    def test_register_and_get(self) -> None:
        RouterPolicyRegistry.register_value("test-policy", "dummy")
        assert RouterPolicyRegistry.get("test-policy") == "dummy"

    def test_keys(self) -> None:
        RouterPolicyRegistry.register_value("a", 1)
        RouterPolicyRegistry.register_value("b", 2)
        assert set(RouterPolicyRegistry.keys()) == {"a", "b"}

    def test_contains(self) -> None:
        RouterPolicyRegistry.register_value("present", True)
        assert RouterPolicyRegistry.contains("present")
        assert not RouterPolicyRegistry.contains("absent")

    def test_duplicate_raises(self) -> None:
        RouterPolicyRegistry.register_value("dup", 1)
        with pytest.raises(ValueError, match="already has an entry"):
            RouterPolicyRegistry.register_value("dup", 2)


def test_miner_registry_register_and_get():
    from diapason.core.registry import MinerRegistry

    class _Stub:
        provider_id = "stub-pearl"

    MinerRegistry.register_value("stub-pearl", _Stub)
    assert MinerRegistry.contains("stub-pearl") is True
    assert MinerRegistry.get("stub-pearl") is _Stub


def test_miner_registry_cleared_between_tests():
    from diapason.core.registry import MinerRegistry

    # If autouse clear works, no entry from prior tests remains
    assert MinerRegistry.contains("stub-pearl") is False


class TestDeclarerSansCharger:
    """Un moteur optionnel ne doit pas coûter ses dépendances à tout le monde.

    MESURÉ le 20 août 2026 : importer ``diapason.cli`` chargeait ``numpy`` et
    ``torch``, parce que le paquet de stockage importait chaque moteur
    « pour déclencher son enregistrement ». Deux d'entre eux échouaient ensuite
    sur une dépendance absente — l'échec était avalé, le coût restait. Or un
    ``numpy`` cassé fait alors tomber ``diapason serve`` au démarrage, pour un
    moteur que personne n'a demandé.
    """

    def test_declarer_n_importe_pas(self) -> None:
        import sys

        from diapason.core.registry import RegistryBase

        class Bac(RegistryBase):
            pass

        Bac.clear()
        Bac.register_lazy("json", "json")
        avant = "json" in sys.modules
        assert "json" in Bac.keys()
        # La déclaration seule ne doit rien avoir chargé de neuf.
        assert ("json" in sys.modules) == avant

    def test_interroger_resout(self) -> None:
        from diapason.core.registry import RegistryBase

        class Bac(RegistryBase):
            pass

        Bac.clear()
        Bac.register_lazy("mien", "tests.core._faux_moteur")
        # Le module n'existe pas : la clé disparaît au lieu de lever.
        assert Bac.contains("mien") is False

    def test_un_enregistrement_reel_remplace_une_declaration(self) -> None:
        """Importer le module directement ne doit pas se heurter à sa déclaration."""
        from diapason.core.registry import RegistryBase

        class Bac(RegistryBase):
            pass

        Bac.clear()
        Bac.register_lazy("truc", "un.module.quelconque")

        @Bac.register("truc")
        class Vrai:
            pass

        assert Bac.get("truc") is Vrai

    def test_deux_enregistrements_reels_se_heurtent_toujours(self) -> None:
        """Le garde d'origine reste : seule la DÉCLARATION est effaçable."""
        import pytest

        from diapason.core.registry import RegistryBase

        class Bac(RegistryBase):
            pass

        Bac.clear()

        @Bac.register("truc")
        class Premier:
            pass

        with pytest.raises(ValueError):

            @Bac.register("truc")
            class Second:
                pass

    def test_importer_la_cli_ne_tire_pas_numpy(self) -> None:
        """La garantie que tout ceci protège, vérifiée dans un processus neuf."""
        import subprocess
        import sys

        resultat = subprocess.run(
            [
                sys.executable,
                "-c",
                "import diapason.tools.storage, sys; "
                "assert not [m for m in sys.modules if m.startswith('numpy')]",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert resultat.returncode == 0, resultat.stderr
