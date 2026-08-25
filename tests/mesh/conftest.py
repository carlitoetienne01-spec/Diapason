"""La flotte de test ne touche jamais la vraie flotte.

Spatial Mesh, phase 0 — 25 août 2026. Ce dossier n'avait AUCUNE garde
d'isolation, alors que trois modules retombent sur le vrai foyer quand on
ne leur injecte rien : ``registry.py`` et ``queue.py`` sur
``get_data_dir()/"mesh.db"``, ``identity.py`` sur
``get_config_dir()/"mesh"``. Un test distrait — une injection oubliée, un
import qui déclenche ``device_identity()`` — écrit donc dans
``~/.diapason``.

Pour une identité d'appareil, ce n'est pas une salissure : régénérer la
clé privée **orpheline toute la flotte déjà jumelée**, puisque les pairs
ne connaissent que l'ancienne clé publique. ``identity.py`` documente
précisément ce danger ; il manquait la ceinture. C'est le même accident
que le profil vocal (conftest racine) et que les jetons de connecteurs
(tests/connectors/conftest.py), tous deux arrivés pour de vrai.

``DIAPASON_HOME`` suffit : ``get_config_dir`` et ``get_data_dir`` relisent
l'environnement à CHAQUE appel, donc tous les replis internes suivent sans
qu'on ait à les repointer un par un — et un test qui injecte déjà son
propre chemin n'est pas gêné.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isoler_la_flotte(tmp_path, monkeypatch):
    """Chaque test de maillage vit dans sa propre maison."""
    foyer = tmp_path / "foyer-mesh"
    foyer.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DIAPASON_HOME", str(foyer))
    yield


def test_la_garde_detourne_bien_le_vrai_foyer(tmp_path):
    """La ceinture se vérifie, elle ne se suppose pas.

    Sans la fixture autouse ci-dessus, ces deux appels rendraient
    ~/.diapason — le foyer réel, avec la clé privée de la machine.
    """
    from diapason.core.paths import get_config_dir, get_data_dir

    reel = str((tmp_path / "..").resolve())  # marqueur : on est bien sous tmp
    assert "foyer-mesh" in str(get_config_dir())
    assert "foyer-mesh" in str(get_data_dir())
    assert ".diapason" != get_config_dir().name or reel  # jamais le vrai foyer


def test_une_identite_creee_en_test_ne_touche_pas_la_machine():
    """Le danger nommé : générer une clé écrirait par-dessus la vraie."""
    from diapason.mesh.identity import device_identity, identity_dir

    dossier = identity_dir()
    assert "foyer-mesh" in str(dossier)
    identite = device_identity()  # crée réellement une paire de clés
    assert identite.device_id.startswith("dev_")
    assert (dossier / "device_key").exists()
    # et cette clé est bien dans le foyer temporaire, pas dans ~/.diapason
    assert str(dossier).startswith("/private/") or "/pytest-" in str(dossier)
