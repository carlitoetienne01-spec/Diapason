"""CLI: jarvis dictionary — teach the recogniser your own vocabulary.

Two mechanisms, one list: the words bias recognition BEFORE transcription
(faster-whisper hotwords), and the misheard variants are replaced AFTER it.
Adding "Carlito" is what stops it coming back as "Karli 2-1"; adding the
variant "Karli 2-1" fixes the ones that already slipped through.
"""

from __future__ import annotations

import click


@click.group("dictionary")
def dictionary() -> None:
    """Manage the personal dictation dictionary."""


@dictionary.command("list")
def list_words() -> None:
    """Show every word, most-used first."""
    from diapason.speech.dictation_dictionary import load_dictionary

    entries = sorted(load_dictionary(), key=lambda e: -e.usage_count)
    if not entries:
        click.echo(
            "Dictionary is empty. Add a word with:\n"
            "  jarvis dictionary add Carlito --variant 'Karli 2-1'"
        )
        return
    for e in entries:
        repl = e.replacements or []
        suffix = f"  ← {', '.join(repl)}" if repl else ""
        click.echo(f"{e.usage_count:5d}  {e.word}{suffix}")


@dictionary.command("add")
@click.argument("word")
@click.option(
    "--variant",
    "variants",
    multiple=True,
    help="A way the recogniser gets it wrong (repeatable).",
)
def add_word(word: str, variants: tuple[str, ...]) -> None:
    """Add WORD, optionally with the mistakes to correct into it."""
    from diapason.speech.dictation_dictionary import (
        DictionaryEntry,
        upsert_entry,
    )

    entry = DictionaryEntry(
        word=word,
        original_word=variants[0] if variants else "",
        replacements=list(variants),
    )
    upsert_entry(entry)
    extra = f" (corrects: {', '.join(variants)})" if variants else ""
    click.echo(f"Added {word!r}{extra}")
    click.echo("It will bias the next transcription — no restart needed.")


@dictionary.command("hints")
def show_hints() -> None:
    """Show exactly what is fed to the recogniser as hotwords."""
    from diapason.speech.dictation_dictionary import transcription_hints

    words = transcription_hints()
    if not words:
        click.echo("No hints — the dictionary is empty.")
        return
    click.echo(f"{len(words)} hint(s) sent to the recogniser:")
    click.echo("  " + " ".join(words))
