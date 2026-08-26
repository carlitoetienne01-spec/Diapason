"""Tests for install-method detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from diapason.cli._install_detect import InstallInfo, detect_install


def _patch_pkg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``diapason.__file__`` at ``tmp_path / diapason / __init__.py``."""
    pkg_dir = tmp_path / "diapason"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    init = pkg_dir / "__init__.py"
    init.write_text("__version__ = '0.0.0+test'\n")

    import diapason

    monkeypatch.setattr(diapason, "__file__", str(init))
    return init


def test_editable_git_install_detected(tmp_path, monkeypatch):
    # Layout: <tmp>/repo/.git, <tmp>/repo/pyproject.toml,
    #         <tmp>/repo/src/diapason/__init__.py
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='diapason'\n")
    src = repo / "src"
    _patch_pkg_file(src, monkeypatch)

    info = detect_install()
    assert info.kind == "editable-git"
    assert "git pull" in info.upgrade_command
    # PAS « uv sync » nu, et ce test l'exigeait. La commande nue ÉLAGUE tout
    # extra qu'elle ne nomme pas : suivre le conseil de Diapason après un
    # `git pull` aurait emporté fastapi, uvicorn, faster-whisper et
    # l'extension native, sans un mot. Le piège avait déjà mordu deux fois
    # sur la machine de développement les 24 et 25 août 2026 ; il était
    # inscrit ici dans la commande conseillée à tout le monde.
    assert "make setup" in info.upgrade_command, (
        f"commande élagueuse : {info.upgrade_command!r}"
    )
    assert "uv sync" not in info.upgrade_command
    assert info.repo_root == repo


def test_uv_tool_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "share" / "uv" / "tools" / "diapason" / "lib" / "python3.12"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "uv-tool"
    assert info.upgrade_command == "uv tool upgrade diapason"


def test_pypi_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "pypi"
    assert info.upgrade_command == "pip install --upgrade diapason"


def test_unknown_install_falls_back_to_pypi(tmp_path, monkeypatch):
    fake = tmp_path / "somewhere" / "weird"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command == "pip install --upgrade diapason"


def test_missing_diapason_file_falls_back_to_pypi(monkeypatch):
    """diapason unimportable / no __file__ — still get a sane default."""
    with patch("diapason.cli._install_detect.Path") as mock_path:
        mock_path.side_effect = Exception("boom")
        info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command == "pip install --upgrade diapason"


def test_returns_install_info_dataclass():
    info = detect_install()
    assert isinstance(info, InstallInfo)
    assert info.kind in {"pypi", "uv-tool", "editable-git", "unknown"}
    assert info.upgrade_command
