"""Le contexte frais rejoint le tour courant, pas le préfixe de l'historique."""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from diapason.core.types import Role


class MessageAvecRole(Protocol):
    @property
    def role(self) -> str: ...


T = TypeVar("T", bound=MessageAvecRole)


def inserer_au_tour_courant(messages: Sequence[T], ajouts: Sequence[T]) -> list[T]:
    # 19/09/2026 : changer UNE seconde au début du contexte d'Anglais faisait
    # passer le préremplissage de 0,10 à 16,21 s. Déplacer les faits volatils
    # avant la dernière demande conserve le préfixe des échanges précédents.
    # Ne jamais séparer un appel d'outil de ses résultats : une requête peut
    # finir par des messages assistant/tool après cette demande utilisateur.
    index = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].role == Role.USER),
        len(messages),
    )
    return [*messages[:index], *ajouts, *messages[index:]]
