"""Détection français / kreyòl / anglais, et mémoire du tour précédent.

29/09/2026 : « Answer in {langue} » figeait la voix. Une phrase kreyòl
était répondue en français, et une phrase mixte n'avait pas de langue
dominante. Le score compte des mots qui ne sont pas partagés ; une
égalité ou un « ok » ne devine pas, il garde la langue déjà en cours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CODES = ("fr", "ht", "en")

# Poids 3 : le mot suffit presque à lui seul. Poids 2 : il compte, mais
# deux mots de langues différentes s'annulent au lieu de trancher.
_HT3 = frozenset(
    """
    mwen kijan kisa poukisa kreyòl kreyol bonjou bonswa ayisyen ayiti
    lapòs tèt jèn kè sè peyi avni fèt fè konnen kapab bezwen avèk
    lakay byen pwoblèm kounye souple anpil jodi jodia oubyen èske eske
    kote moun kay zanmi pitit bagay anmwe chita kanpe gade tande demen
    kontan
    """.split()
)
_HT2 = frozenset(
    """
    mèsi mesi wi ap nan pou ak yo nou gen ale vini yon tou avanse pral
    paske pale
    """.split()
)
_FR = frozenset(
    """
    je tu nous vous il elle ils elles est suis es sont ai as avons avez
    ont pas ne que qui quoi dont où dans avec pour sur sous sans mais
    donc merci oui bonjour comment pourquoi quand aussi très tres bien
    fait faire vais va aller c'est aujourd'hui aujourdhui aujourd demain
    hier une des les du au aux ce cet cette ces mon ma mes ton ta tes sa
    ses un le et chez plus tout tous ça ca veux veut peux peut parle dis
    dit juste voulais dire petit bonne bonsoir salut
    """.split()
)
_EN = frozenset(
    """
    the is are was were you your what how please thanks thank hello yes
    this that these those with from have has do does did can could would
    should my we they them their our not it of and to for be been will
    just about there here today tomorrow tell works see look
    """.split()
)
_BIGRAMMES_HT = (
    "men wi",
    "sa k",
    "k ap",
    "ap fèt",
    "ap fet",
    "ann avanse",
    "mwen la",
    "kounye a",
    "ki kote",
    "m ap",
    "l ap",
    "n ap",
    "w ap",
    "y ap",
    "t ap",
)
_JETON = re.compile(r"[a-zàâäèéêëïîòôùûüçœæ']+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Detection:
    """La langue retenue, et si le texte l'a vraiment montrée."""

    code: str
    certaine: bool
    fr: int
    ht: int
    en: int


class MemoireLinguistique:
    """La langue du dernier tour certain. Remplacée, jamais mutée."""

    def __init__(self, code: str = "fr") -> None:
        self._code = code if code in _CODES else "fr"

    def courante(self) -> str:
        return self._code

    def noter(self, code: str) -> MemoireLinguistique:
        if code not in _CODES or code == self._code:
            return self
        return MemoireLinguistique(code)


def _jetons(texte: str) -> list[str]:
    bas = (texte or "").lower().replace("’", "'")
    trouves: list[str] = []
    for brut in _JETON.findall(bas):
        mot = brut.strip("'")
        if len(mot) >= 2:
            trouves.append(mot)
        if "'" in brut:
            trouves.extend(
                part.strip("'") for part in brut.split("'") if len(part.strip("'")) >= 2
            )
    return trouves


def _poids(jeton: str) -> tuple[str, int] | None:
    if jeton in _HT3:
        return ("ht", 3)
    if jeton in _HT2:
        return ("ht", 2)
    if jeton in _FR:
        return ("fr", 2)
    if jeton in _EN:
        return ("en", 2)
    # ò n'appartient pas à l'orthographe française courante.
    if "ò" in jeton:
        return ("ht", 2)
    return None


def detecter(texte: str, memoire: MemoireLinguistique | None = None) -> Detection:
    """Langue dominante. L'ambigu revient à la mémoire, sinon au français."""
    fr = ht = en = 0
    for jeton in _jetons(texte):
        poids = _poids(jeton)
        if poids is None:
            continue
        if poids[0] == "fr":
            fr += poids[1]
        elif poids[0] == "ht":
            ht += poids[1]
        else:
            en += poids[1]
    compact = re.sub(r"\s+", " ", (texte or "").lower().replace("’", "'"))
    borne = f" {compact} "
    for gram in _BIGRAMMES_HT:
        if f" {gram} " in borne:
            ht += 3
    scores = {"fr": fr, "ht": ht, "en": en}
    meilleur = max(scores.values())
    leaders = [code for code, valeur in scores.items() if valeur == meilleur]
    if meilleur <= 0 or len(leaders) != 1:
        code = memoire.courante() if memoire is not None else "fr"
        return Detection(code, False, fr, ht, en)
    return Detection(leaders[0], True, fr, ht, en)
