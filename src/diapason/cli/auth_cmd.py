"""CLI commands for API key management."""

from __future__ import annotations

import os

import click

from diapason.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
)
from diapason.server.auth_middleware import generate_api_key


@click.group("auth")
def auth() -> None:
    """Manage API authentication keys."""


@auth.command("create-key")
def create_key() -> None:
    """Generate or rotate the owner-only local API key."""
    key = generate_api_key()
    auth_dir = DEFAULT_CONFIG_DIR / "auth"
    auth_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path = auth_dir / "local_api_key"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(key_path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key + "\n")
    key_path.chmod(0o600)

    click.echo(f"API key generated: {key}")
    click.echo(f"Stored in: {key_path}")
    click.echo("File permissions set to 0600 (user-only read/write).")


@auth.command("generate-key")
def generate_key() -> None:
    """Print a new key for use in DIAPASON_API_KEY or service secrets."""
    click.echo(generate_api_key())


@auth.command("revoke-key")
def revoke_key() -> None:
    """Revoke the current API key."""
    key_path = DEFAULT_CONFIG_DIR / "auth" / "local_api_key"
    if key_path.exists() and not key_path.is_symlink():
        key_path.unlink()
    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        click.echo("Local API key revoked.")
        return

    content = config_path.read_text()
    if "api_key" not in content:
        click.echo("Local API key revoked.")
        return

    import re

    content = re.sub(r'api_key\s*=\s*"[^"]*"', 'api_key = ""', content)
    config_path.write_text(content)
    click.echo("API key revoked.")
