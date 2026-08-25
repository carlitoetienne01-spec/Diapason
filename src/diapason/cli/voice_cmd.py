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
            "[yellow]En apprentissage[/yellow] — les prochains tours adressés "
            "(« Diapason, … ») nourrissent le profil, puis le verrou s'arme."
        )


@voice.command("reset")
@click.confirmation_option(prompt="Effacer l'empreinte vocale et tout réapprendre ?")
def voice_reset() -> None:
    """Oublie l'empreinte : les prochains tours adressés réapprennent."""
    from diapason.speech.speaker_id import get_verifier

    get_verifier().reset()
    Console().print("[green]Empreinte effacée.[/green] La voix se réapprend seule.")


__all__ = ["voice"]
