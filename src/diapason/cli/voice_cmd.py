"""``diapason voice`` — l'empreinte vocale du propriétaire."""

from __future__ import annotations

import click
from rich.console import Console


@click.group("voice")
def voice() -> None:
    """Le verrou vocal : ne répondre qu'à la voix enrôlée."""


@voice.command("status")
def voice_status() -> None:
    """Où en est l'empreinte : échantillons, verrou, modèle."""
    from diapason.speech.speaker_id import ECHANTILLONS_REQUIS, get_verifier

    console = Console()
    v = get_verifier()
    console.print(
        f"Échantillons enrôlés : {v.echantillons}/{ECHANTILLONS_REQUIS} requis"
    )
    if v.arme:
        console.print("[green]Verrou armé[/green] — seule la voix enrôlée est écoutée.")
    else:
        console.print(
            "[yellow]Profil à préparer[/yellow] — ouvre Réglages → Voix "
            "et enregistre ton profil avec le parcours guidé."
        )


@voice.command("reset")
@click.confirmation_option(prompt="Effacer l'empreinte vocale et tout réapprendre ?")
def voice_reset() -> None:
    """Oublie l'empreinte ; un nouvel enregistrement guidé sera nécessaire."""
    from diapason.speech.speaker_id import get_verifier

    get_verifier().reset()
    Console().print(
        "[green]Empreinte effacée.[/green] "
        "Prépare un nouveau profil dans Réglages → Voix."
    )


__all__ = ["voice"]
