"""Smoke test that the tmp_diapason_home fixture works."""

from __future__ import annotations

from pathlib import Path

from diapason.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_diapason_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_diapason_home
    assert tmp_diapason_home.exists()
    assert (tmp_diapason_home / ".state").exists()
    assert (tmp_diapason_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_diapason_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_diapason_home / "config.toml"
