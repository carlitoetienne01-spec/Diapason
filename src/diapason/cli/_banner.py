"""Startup banner — Diapason wordmark + tagline."""

from __future__ import annotations

# "DIAPASON" rendered as a compact terminal wordmark. Stored as plain text
# (no inline Rich markup) so the backslashes in the glyphs don't collide with
# Rich's [tag] markup or Python raw-string escaping — colour is applied at
# print time via a style argument.
#
# 29 August 2026: the previous drawing still spelled the PRE-RENAME product
# name — see the diff of this commit, which cannot be quoted here because
# `scripts/check_project_identity.py` refuses that string anywhere outside
# its own allowlist, and weakening the ratchet for a comment would be a poor
# trade. Every Windows startup therefore contradicted the application's own
# name before its first screen appeared.
_WORDMARK = (
    " ____  ___    _    ____   _    ____   ___  _   _ ",
    "|  _ \\|_ _|  / \\  |  _ \\ / \\  / ___| / _ \\| \\ | |",
    "| | | || |  / _ \\ | |_) / _ \\ \\___ \\| | | |  \\| |",
    "| |_| || | / ___ \\|  __/ ___ \\ ___) | |_| | |\\  |",
    "|____/|___/_/   \\_\\_| /_/   \\_\\____/ \\___/|_| \\_|",
)

_TAGLINE = "Personal AI, On Personal Devices"


def print_banner(quiet: bool = False) -> None:
    """Print the Diapason startup banner. No-op when quiet."""
    if quiet:
        return
    try:
        from rich.console import Console

        console = Console()
        for line in _WORDMARK:
            console.print(line, style="bold bright_blue", highlight=False, markup=False)
        console.print(f"      {_TAGLINE}", style="cyan", highlight=False, markup=False)
        console.print()
    except ImportError:
        for line in _WORDMARK:
            print(line)
        print(f"      {_TAGLINE}")
        print()
