"""Faut-il envoyer les schémas d'outils avec ce tour ?

Envoyer la trousse coûte du préremplissage à chaque message : dix-sept outils
pèsent près de trois mille jetons, que le modèle relit avant de répondre. Sur un
« merci » c'est du temps pur perdu, et à la voix il s'entend.

Mais la retenir coûte plus cher encore : le prompt annonce des capacités, et un
tour privé d'outils répond de son imagination du même ton assuré. C'est ce qui
est arrivé au chemin vocal quand le filtre était une liste d'AUTORISATION —
« quelles sont mes tâches aujourd'hui » n'y figurait pas, et la réponse était
inventée sans que rien ne le signale.

D'où le sens de la règle : par défaut on envoie, et seule une parole
reconnaissablement dépourvue de demande en est dispensée. Une liste
d'autorisation devrait énumérer toutes les formulations de toutes les capacités
pour être juste ; une liste de refus n'a qu'à reconnaître « ouais, merci ».

Extrait de ``speech/realtime/local_voice.py`` le 22 août 2026, quand le chat en
flux a reçu ses outils à son tour et a hérité du même arbitrage.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

# ``'`` et ``’`` toutes les deux : laquelle arrive dépend du moteur de
# transcription, pas de la personne qui parle. Ne reconnaître que la forme
# ASCII laissait « d'accord » passer pour un tour porteur d'outils.
_APOS = r"['’]"

# Tours qui ne peuvent visiblement rien demander : acquiescements, salutations,
# remerciements. Chaque entrée doit être impossible à lire comme un ordre —
# « arrête » et « stop » restent dehors, ils coupent le partage d'écran.
NO_TOOL_TURN_RE = re.compile(
    r"^\W*(?:"
    r"oui|ouais|non|nan|ok|okay|d" + _APOS + r"accord|dac|entendu|"
    r"merci(?:\s+beaucoup)?|de\s+rien|"
    r"salut|bonjour|bonsoir|coucou|hello|hi|hey|"
    r"au\s+revoir|bye|à\s+plus|à\s+bientôt|bonne\s+nuit|"
    r"parfait|super|génial|cool|nickel|très\s+bien|"
    r"exactement|voilà|c" + _APOS + r"est\s+ça|je\s+vois|"
    r"ah|oh|hmm|euh|mm+"
    r")\W*$",
    re.IGNORECASE,
)


def turn_needs_tools(messages: Sequence[Mapping[str, Any]]) -> bool:
    """Vrai s'il faut joindre la trousse au dernier tour utilisateur."""
    for message in reversed(messages):
        if message.get("role") == "user":
            contenu = str(message.get("content") or "").strip()
            if not contenu:
                return False
            return not NO_TOOL_TURN_RE.match(contenu)
    return False


def text_needs_tools(texte: str) -> bool:
    """Même arbitrage, sur un texte nu."""
    propre = str(texte or "").strip()
    if not propre:
        return False
    return not NO_TOOL_TURN_RE.match(propre)


__all__ = ["NO_TOOL_TURN_RE", "text_needs_tools", "turn_needs_tools"]
