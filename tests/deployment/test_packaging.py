"""Guards for the diapason-rust packaging split (#584 / #615).

``diapason_rust`` is the native PyO3 extension. It is NOT published to PyPI,
so it must not appear in the published ``desktop`` extra — listing it there
breaks ``pip install diapason[desktop]`` at install time. It lives in the uv
``desktop-native`` dependency group instead (excluded from wheel metadata),
which the desktop app installs from source via
``uv sync --group desktop-native``.
"""

from __future__ import annotations

from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = ROOT / "pyproject.toml"
DESKTOP_LIB_RS = ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
WINDOWS_INSTALL_PS1 = ROOT / "deploy" / "windows" / "install.ps1"
QUICKSTART_SH = ROOT / "scripts" / "quickstart.sh"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_diapason_rust_not_in_published_desktop_extra() -> None:
    desktop = _pyproject()["project"]["optional-dependencies"]["desktop"]
    assert not any("diapason-rust" in dep for dep in desktop), (
        "diapason-rust must not be in the published `desktop` extra — it is "
        "not on PyPI, so it breaks `pip install diapason[desktop]`."
    )


def test_diapason_rust_lives_in_uv_dependency_group() -> None:
    group = _pyproject()["dependency-groups"]["desktop-native"]
    assert any("diapason-rust" in dep for dep in group)


def test_diapason_rust_has_local_uv_path_source() -> None:
    src = _pyproject()["tool"]["uv"]["sources"]["diapason-rust"]
    assert src["path"] == "rust/crates/diapason-python"


def test_desktop_app_syncs_the_native_group() -> None:
    # Otherwise the group's diapason_rust is never installed for the app.
    assert '"desktop-native"' in DESKTOP_LIB_RS.read_text(), (
        "the desktop app must `uv sync --group desktop-native` so the native "
        "extension is built at launch."
    )


def test_windows_installer_syncs_the_native_group() -> None:
    """Le groupe natif est synchronisé — QUAND Rust est là pour le bâtir.

    Ce test exigeait la commande en dur, inconditionnelle. Or ce groupe tire
    `diapason-rust`, que uv.lock déclare comme une source de RÉPERTOIRE sans
    aucune roue : uv doit le compiler, avec rustc 1.88, les outils MSVC, CMake
    et NASM — que l'installateur ne vérifiait ni n'installait. Sur un PC neuf
    la commande échouait, et le script s'arrêtait là.

    La dépendance était pourtant connue : ci.yml installe
    dtolnay/rust-toolchain en étape séparée avant chaque appel à maturin.
    Seule cette ligne l'ignorait. Constaté le 26 août 2026, avant que Carlito
    n'y passe une soirée.

    Le test garde donc l'intention — bâtir l'extension quand c'est possible —
    au lieu d'une chaîne de caractères.
    """
    script = WINDOWS_INSTALL_PS1.read_text()
    assert "--group', 'desktop-native'" in script or (
        "--group desktop-native" in script
    ), "l'installateur ne bâtit plus jamais l'extension native"
    assert "Get-Command cargo" in script, (
        "l'installateur exige Rust sans vérifier qu'il est là"
    )
    assert "Rustlang.Rustup" in script, (
        "l'installateur doit dire comment obtenir Rust, pas seulement le "
        "constater absent"
    )


def test_quickstart_installs_web_search_dependencies() -> None:
    quickstart = QUICKSTART_SH.read_text()
    assert "--extra tools-search" in quickstart


def test_quickstart_refuses_a_port_already_served() -> None:
    """Quickstart ne doit pas empiler un serveur sur un autre.

    Cette assertion vivait dans le test des dépendances de recherche web, et
    portait sur la formulation exacte du message. On vérifie désormais le
    MÉCANISME : la question est posée au noyau — un ``curl /health`` ne voit
    pas un détenteur muet — et un port occupé fait échouer le script.
    """
    quickstart = QUICKSTART_SH.read_text()
    assert "port_listeners" in quickstart, "le port doit être vérifié"
    assert "lsof" in quickstart, "la question doit être posée au noyau"
    assert "already served by" in quickstart, "un port occupé doit faire échouer"
