"""Tests for `diapason digest` CLI command."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from diapason.agents.digest_store import DigestArtifact, DigestStore


def test_digest_command_exists():
    """The digest command is registered on the CLI."""
    from diapason.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--help"])
    assert result.exit_code == 0
    assert "digest" in result.output.lower()


def test_digest_displays_cached(tmp_path):
    from diapason.cli import cli

    db_path = str(tmp_path / "digest.db")
    store = DigestStore(db_path=db_path)
    store.save(
        DigestArtifact(
            text="# Messages\nYou have 3 emails.\n# Calendar\n2 meetings today.",
            audio_path=Path("/nonexistent/audio.mp3"),
            sections={},
            sources_used=["gmail"],
            # L'heure LOCALE, pas UTC. ``get_today`` compare la date du
            # tampon à aujourd'hui dans le fuseau de la machine — c'est le
            # sens du champ, et sa docstring le dit. Un tampon UTC désigne
            # déjà demain à l'ouest de Greenwich dès le début de soirée : ce
            # test échouait quatre heures par jour, tous les jours, sur la
            # machine de quiconque n'est pas à UTC.
            generated_at=datetime.now().astimezone(),
            model_used="test",
            voice_used="diapason",
        )
    )
    store.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--text-only", "--db-path", db_path])
    assert result.exit_code == 0
    assert "3 emails" in result.output


def test_digest_no_cache(tmp_path):
    from diapason.cli import cli

    db_path = str(tmp_path / "empty.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--db-path", db_path])
    assert result.exit_code == 0
    assert "No digest for today" in result.output
