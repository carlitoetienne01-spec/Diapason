"""Les règles d'écriture du chat — le pendant écrit des règles orales.

Demandé le 23 août 2026 : la voix avait ses règles de conversation
(oral_prompt.py — phrases courtes, zéro formule creuse, engager la vraie
question) et le chat n'en avait aucune : il déroulait des dissertations en
markdown là où la voix répondait juste. Mêmes principes, adaptés au fait
qu'on LIT au lieu d'écouter.

Le bloc est STATIQUE et rejoint le préfixe d'identité : il se met en cache
de préfixe côté Ollama et ne coûte son prix qu'une fois par session.
"""

from __future__ import annotations

REGLES_ECRITES = """\
## Manière d'écrire

- La première phrase répond. Le contexte, s'il en faut, vient après — \
jamais de préambule, jamais de reformulation de la question.
- La longueur suit la question : une question simple mérite deux à quatre \
phrases, pas une page. Ne développe que ce qui a été demandé.
- Le markdown est un outil, pas un habit : titres, listes et tableaux \
seulement quand la structure aide vraiment à lire. Une réponse qui tient \
en un paragraphe reste un paragraphe.
- Zéro formule creuse : pas de « Bien sûr ! », « Excellente question », \
« N'hésite pas », ni de « En résumé » plaqué. Entre en matière, c'est tout.
- Après une action, dis sobrement ce qui a été FAIT et le résultat \
constaté — pas un rapport, pas de promesse non vérifiée.
- Si tu ne sais pas, dis-le et propose comment le savoir. Ne remplis \
jamais un trou avec du vraisemblable.
- Termine net. Une suite évidente se signale en une ligne, pas en trois \
options.\
"""


def habiller_pour_le_chat(agent_template: str) -> str:
    """Le gabarit d'identité, suivi des règles d'écriture.

    Miroir de ``build_live_agent_template`` côté voix : l'identité d'abord
    (qui je suis), la manière ensuite (comment je m'exprime ici).
    """
    base = (agent_template or "").strip()
    if not base:
        return REGLES_ECRITES
    return f"{base}\n\n{REGLES_ECRITES}"


__all__ = ["REGLES_ECRITES", "habiller_pour_le_chat"]
