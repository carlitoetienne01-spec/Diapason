"""Un tirage de la Grande Vie, et la lecture d'une page d'archives.

Le jeu : cinq numéros parmi 49, plus un Grand Numéro parmi 7. La Grande Vie de
Loto-Québec et le Daily Grand pancanadien sont LE MÊME TIRAGE sous deux noms —
vérifié le 31 août 2026 sur les chiffres eux-mêmes : 06-23-28-34-37 + 4 des
deux côtés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from math import comb

NUMEROS_PAR_TIRAGE = 5
NUMERO_MAX = 49
GRAND_NUMERO_MAX = 7

#: Le nombre de grilles distinctes. C(49,5) x 7 = 13 348 188.
#: Recoupé avec la cote publiée du gros lot : 1 sur 13 348 188.
COMBINAISONS = comb(NUMERO_MAX, NUMEROS_PAR_TIRAGE) * GRAND_NUMERO_MAX


class TirageInvalide(ValueError):
    """Une ligne d'archive qu'on refuse de lire plutôt que de la deviner."""


@dataclass(frozen=True, slots=True)
class Tirage:
    """Un tirage : sa date, ses cinq numéros triés, son Grand Numéro."""

    jour: date
    numeros: tuple[int, ...]
    grand_numero: int

    def __post_init__(self) -> None:
        if len(self.numeros) != NUMEROS_PAR_TIRAGE:
            raise TirageInvalide(
                f"un tirage porte {NUMEROS_PAR_TIRAGE} numéros, pas {len(self.numeros)}"
            )
        if len(set(self.numeros)) != NUMEROS_PAR_TIRAGE:
            raise TirageInvalide(
                "un numéro ne peut pas sortir deux fois dans un tirage"
            )
        for n in self.numeros:
            if not 1 <= n <= NUMERO_MAX:
                raise TirageInvalide(f"le numéro {n} est hors de 1..{NUMERO_MAX}")
        if not 1 <= self.grand_numero <= GRAND_NUMERO_MAX:
            raise TirageInvalide(
                f"le Grand Numéro {self.grand_numero} est hors de 1..{GRAND_NUMERO_MAX}"
            )
        if list(self.numeros) != sorted(self.numeros):
            raise TirageInvalide("les numéros doivent être triés")


# La ligne d'archive, telle qu'elle est servie :
#
#   <td class="date-cell" ...>31/08<br>26(MON)</td>
#   <td class="number-cell" ...>06,&nbsp;23,&nbsp;28,&nbsp;34,&nbsp;37</td>
#   <td class="bonus-cell" ...>04</td>
#
# Les classes sont le point d'ancrage, pas la position des colonnes : une
# colonne ajoutée devant ne casserait rien, alors qu'un découpage par rang
# aurait décalé toute la lecture en silence.
_LIGNE = re.compile(
    r'<td[^>]*class="date-cell"[^>]*>(?P<jour>\d{1,2})/(?P<mois>\d{1,2})'
    r"\s*<br\s*/?>\s*(?P<annee>\d{2})"
    r'.*?<td[^>]*class="number-cell"[^>]*>(?P<numeros>.*?)</td>'
    r'.*?<td[^>]*class="bonus-cell"[^>]*>\s*(?P<grand>\d{1,2})\s*</td>',
    re.S | re.I,
)


def _annee_pleine(deux_chiffres: int) -> int:
    """« 26 » vaut 2026.

    Le jeu a commencé en octobre 2016 : aucun tirage ne peut être antérieur, et
    la borne de 2100 est loin devant. Deviner un siècle est une source d'erreur
    silencieuse ; ici la règle est écrite.
    """
    return 2000 + deux_chiffres


def analyser_page(html: str) -> list[Tirage]:
    """Les tirages d'une page d'archives, dans l'ordre où elle les donne.

    Fonction PURE : pas de réseau, pas de disque. C'est elle qui porte tout le
    risque de lecture, donc c'est elle qu'on teste — sur du HTML capturé, pas
    sur une page vivante qui changerait sous les tests.

    Une ligne illisible est SAUTÉE, pas devinée. Une page d'archives contient
    des en-têtes, des publicités et des tableaux de mise en page ; exiger que
    tout se lise ferait échouer la moisson entière sur un encart.
    """
    tirages: list[Tirage] = []
    for m in _LIGNE.finditer(html):
        bruts = re.findall(r"\d{1,2}", re.sub(r"&nbsp;?", " ", m.group("numeros")))
        if len(bruts) != NUMEROS_PAR_TIRAGE:
            continue
        try:
            tirage = Tirage(
                jour=date(
                    _annee_pleine(int(m.group("annee"))),
                    int(m.group("mois")),
                    int(m.group("jour")),
                ),
                numeros=tuple(sorted(int(b) for b in bruts)),
                grand_numero=int(m.group("grand")),
            )
        except (TirageInvalide, ValueError):
            continue
        tirages.append(tirage)
    return tirages
