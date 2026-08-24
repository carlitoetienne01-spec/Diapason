"""Le filet anti-promesse — partagé entre la voix et le chat.

Né à la voix (23 août 2026) : après un dialogue de clarification, le tour
répondait « d'accord, je cherche du R&B sur YouTube pour toi » — dit, rien
fait. Étendu au chat et AFFINÉ (Atlas, 24 août 2026) : le filet original
attrapait aussi les OFFRES (« veux-tu que je cherche ? », « je peux le
faire si tu veux ») — or une offre attend une réponse, elle ne promet
rien. L'analyse se fait PHRASE PAR PHRASE : une question ne somme jamais,
une offre conditionnelle non plus.

Deux régimes :
- oral (défaut) : le filet historique, plus l'exclusion des offres ;
- ``ecrit=True`` (chat) : s'y ajoutent les verbes de discours écrits
  (« je note que… »), le « c'est fait » d'instruction (« quand c'est
  fait, dis-le-moi »), et l'abandon de « un instant » (prose courante) et
  de « est ouverte/fermée » (le cliché du bureau rend « Safari est
  ouvert » parfaitement légitime).
"""

from __future__ import annotations

import re

_ANNONCE = (
    r"\bje\s+(?:"
    r"vais\s+(?:chercher|ouvrir|lancer|relancer|mettre|jouer|cr[ée]er|"
    r"installer|regarder|faire|refaire|noter|ajouter|r[ée]essayer)|"
    r"cherche|lance|relance|refais|r[ée]essaie|recommence|joue|mets|note|"
    r"ajoute|m['’]en\s+occupe"
    r")\b"
    r"|\bj['’]ouvre\b"
)

_ACCOMPLI_COMMUN = (
    r"\bc['’]est\s+fait\b"
    r"|\bs['’]affichent?\b|\bdevraient\s+s['’]afficher\b"
)

# À l'oral, « est ouverte/fermée » sans acte est un mensonge ; au chat, le
# cliché du bureau (« Safari est ouvert au premier plan ») le rend légitime.
_ACCOMPLI_ORAL = (
    r"|\best\s+(?:relanc[ée]|lanc[ée]|faite|refaite|ouverte?|ferm[ée]|"
    r"cr[ée][ée]|install[ée]|not[ée]|ajout[ée])e?s?\b"
)
_ACCOMPLI_ECRIT = (
    r"|\best\s+(?:relanc[ée]|lanc[ée]|faite|refaite|"
    r"cr[ée][ée]|install[ée]|not[ée]|ajout[ée])e?s?\b"
)

PROMESSE_SANS_ACTE_RE = re.compile(
    _ANNONCE + r"|\bun\s+(?:instant|moment)\b|" + _ACCOMPLI_COMMUN + _ACCOMPLI_ORAL,
    re.IGNORECASE,
)
_PROMESSE_ECRITE_RE = re.compile(
    _ANNONCE + "|" + _ACCOMPLI_COMMUN.lstrip("|") + _ACCOMPLI_ECRIT,
    re.IGNORECASE,
)

# Une offre attend une réponse — elle ne promet rien.
_OFFRE_RE = re.compile(
    r"\bque\s+je\b|\bje\s+peux\b|\bveux-tu\b|\bvoulez-vous\b"
    r"|\bsi\s+tu\s+(?:veux|pr[ée]f[èe]res|souhaites)\b"
    r"|\bsi\s+vous\s+(?:voulez|pr[ée]f[ée]rez|souhaitez)\b",
    re.IGNORECASE,
)
_DISCOURS_ECRIT_RE = re.compile(
    r"\bje\s+note\s+que\b|\bje\s+mets\s+(?:l['’]accent|en\s+garde)\b",
    re.IGNORECASE,
)
_FAIT_CONDITIONNEL_RE = re.compile(
    r"\b(?:quand|une\s+fois\s+que|d[èe]s\s+que|lorsque)\b[^.!?\n]*"
    r"\bc['’]est\s+fait",
    re.IGNORECASE,
)
_PHRASES_RE = re.compile(r"[^.!?…\n]+[.!?…]?")
_C_EST_FAIT_RE = re.compile(r"\bc['’]est\s+fait\b", re.IGNORECASE)


def est_une_promesse_sans_acte(texte: str, *, ecrit: bool = False) -> bool:
    """Ce texte annonce-t-il une action sans l'avoir faite ?

    Phrase par phrase : une question ne somme jamais, une offre non plus.
    """
    regex = _PROMESSE_ECRITE_RE if ecrit else PROMESSE_SANS_ACTE_RE
    for brut in _PHRASES_RE.findall(texte or ""):
        phrase = brut.strip()
        if not phrase or phrase.endswith("?"):
            continue
        if _OFFRE_RE.search(phrase):
            continue
        if ecrit:
            if _DISCOURS_ECRIT_RE.search(phrase):
                continue
            if _FAIT_CONDITIONNEL_RE.search(phrase):
                # « quand c'est fait, préviens-moi » : le c'est fait est une
                # instruction à l'usager, pas une proclamation.
                phrase = _C_EST_FAIT_RE.sub("", phrase)
        if regex.search(phrase):
            return True
    return False


__all__ = ["PROMESSE_SANS_ACTE_RE", "est_une_promesse_sans_acte"]
