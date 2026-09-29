"""Guide phonétique : le kreyòl écrit devient lisible par la voix française.

29/09/2026 : Orion synthétise avec language="French". « tèt » y perd le
t, « gen » se lit « jen » (le g français devant e), « lapòs » avale le s.
Le guide ne réécrit qu'une phrase déjà jugée kreyòl. Le français et
l'anglais ressortent tels quels : un mélange involontaire ici serait
une prononciation fausse, pas un accent.

Il n'y a pas de modèle acoustique kreyòl dans la voix installée. Ce
texte est la prononciation ; le timbre reste celui de Diapason.
"""

from __future__ import annotations

import re

from diapason.speech.langues.detection import detecter

# grapheme officiel → graphie que le français oral fait entendre.
# « jèn » → « jène » : le e muet force le n consonantique, sinon la
# nasale française mange le n. « gen » → « gain » : /gɛ̃/, pas /ʒɑ̃/.
# « laposse » : le s doublé et le e muet empêchent le s final muet.
GUIDE_PHONETIQUE: tuple[tuple[str, str], ...] = (
    ("tèt", "tète"),
    ("jèn", "jène"),
    ("kè", "kè"),
    ("sè", "sè"),
    ("peyi", "péyi"),
    ("mèsi", "mèssi"),
    ("avni", "avni"),
    ("lapòs", "laposse"),
)

_SUPPLEMENT: tuple[tuple[str, str], ...] = (
    ("mwen", "mouin"),
    ("wi", "oui"),
    ("gen", "gain"),
    ("pwoblèm", "pwoblème"),
    ("ye", "yé"),
    ("k", "ke"),
    ("fèt", "fète"),
    ("mesi", "mèssi"),
    ("bonjou", "bondjou"),
    ("bonswa", "bondswa"),
    ("byen", "bien"),
    ("kreyòl", "kréyol"),
    ("kreyol", "kréyol"),
    ("avèk", "avèque"),
    ("ak", "aque"),
    ("konnen", "konnin"),
    ("pral", "prale"),
    ("ale", "alé"),
)

_TABLE = dict(GUIDE_PHONETIQUE)
_TABLE.update(_SUPPLEMENT)

_LOCUTIONS: tuple[tuple[str, str], ...] = (
    ("sa k ap fèt", "sa ke ape fète"),
    ("ann avanse", "ann avancé"),
    ("men wi", "main oui"),
    ("mwen la", "mouin la"),
    ("kounye a", "kounyé a"),
)

_CLITIQUES: tuple[tuple[str, str], ...] = (
    (r"\bm\s+ap\b", "mape"),
    (r"\bl\s+ap\b", "lape"),
    (r"\bn\s+ap\b", "nape"),
    (r"\bw\s+ap\b", "ouape"),
    (r"\by\s+ap\b", "yape"),
    (r"\bt\s+ap\b", "tape"),
)

_HESITATION = re.compile(r"\b(euh+|euhm|hum+|hmm+|um+|uh+)\b", re.IGNORECASE)
_MOT = re.compile(r"[A-Za-zÀ-ÿœæ]+")
_QUESTION = re.compile(
    r"^(kijan|kisa|poukisa|èske|eske|ki moun|ki kote|kiles)\b",
    re.IGNORECASE,
)

# Orthographe officielle, seulement dans une phrase déjà kreyòl.
# « créole » dans une phrase française n'est pas réécrit.
_ORTHOGRAPHE = {
    "kreyol": "kreyòl",
    "creole": "kreyòl",
    "créole": "kreyòl",
    "mesi": "mèsi",
    "lapos": "lapòs",
    "pwoblem": "pwoblèm",
    "avek": "avèk",
}

# 29/09/2026 : 1,0 aussi pour le kreyòl. Accélérer le PCM sans vocodeur
# de phase monte la hauteur et réintroduit les coupures. Le rythme plus
# vif est le texte sans « euh » ni points de suspension.
_VITESSE = {"fr": 1.0, "ht": 1.0, "en": 1.0}


def vitesse(code: str) -> float:
    return _VITESSE.get(code, 1.0)


def _kreyol_certain(texte: str) -> bool:
    vu = detecter(texte)
    return vu.code == "ht" and vu.certaine


def _casse(mot: str, rendu: str) -> str:
    if mot[:1].isupper() and rendu[:1].islower():
        return rendu[:1].upper() + rendu[1:]
    return rendu


def _regle(mot: str) -> str:
    """Filet pour un mot absent du guide : g dur, ò, consonne finale."""
    bas = mot.lower().replace("ò", "o").replace("Ò", "o")
    bas = re.sub(r"g(?=[eèéêi])", "gu", bas)
    if (
        len(bas) >= 2
        and bas[-1] in "bdfgkpst"
        and not bas.endswith(("an", "en", "on", "oun", "e"))
    ):
        bas += "e"
    return bas


def _mot(mot: str) -> str:
    bas = mot.lower()
    rendu = _TABLE[bas] if bas in _TABLE else _regle(bas)
    return _casse(mot, rendu)


def _nettoyer(texte: str) -> str:
    """Retire les hésitations que le vocodeur lirait comme des coupures."""
    suspension = (texte or "").rstrip().endswith(("…", "..."))
    sans = _HESITATION.sub(" ", texte or "")
    sans = sans.replace("…", " ")
    sans = re.sub(r"\.{3,}", " ", sans)
    sans = re.sub(r"^[\s,;:.]+", "", sans)
    # L'espace avant « ? » est l'intonation française : le retirer colle
    # le point d'interrogation au mot et la voix ne monte plus pareil.
    sans = re.sub(r"\s+([,.;:])", r"\1", sans)
    sans = re.sub(r"[ \t]{2,}", " ", sans).strip(" ,;")
    if suspension and sans and not sans.endswith((".", "!", "?")):
        sans += "."
    return sans


def _questions(original: str, rendu: str) -> str:
    if (original or "").rstrip().endswith("?"):
        corps = rendu.rstrip()
        if not corps.endswith("?"):
            corps = corps.rstrip(" .") + " ?"
        return corps
    if _QUESTION.search((original or "").strip()):
        corps = rendu.rstrip()
        if corps.endswith("."):
            corps = corps[:-1].rstrip()
        if not corps.endswith("?"):
            corps += " ?"
        return corps
    return rendu


def forme_orale(texte: str) -> str:
    """Graphie à synthétiser. Identité hors kreyòl certain."""
    if not texte or not _kreyol_certain(texte):
        return texte
    rendu = _nettoyer(texte)
    for source, cible in _LOCUTIONS:
        rendu = re.sub(re.escape(source), cible, rendu, flags=re.IGNORECASE)
    for motif, cible in _CLITIQUES:
        rendu = re.sub(motif, cible, rendu, flags=re.IGNORECASE)
    rendu = _MOT.sub(lambda match: _mot(match.group(0)), rendu)
    rendu = re.sub(r"[ \t]{2,}", " ", rendu).strip()
    rendu = _questions(texte, rendu)
    if texte[:1].isupper() and rendu[:1].islower():
        rendu = rendu[:1].upper() + rendu[1:]
    return rendu


def forme_ecrite(texte: str) -> str:
    """Orthographe officielle à l'écran. La phrase française ne bouge pas."""
    if not texte or not _kreyol_certain(texte):
        return texte

    def remplacer(match: re.Match[str]) -> str:
        mot = match.group(0)
        rendu = _ORTHOGRAPHE.get(mot.lower())
        if rendu is None:
            return mot
        return _casse(mot, rendu)

    return _MOT.sub(remplacer, texte)
