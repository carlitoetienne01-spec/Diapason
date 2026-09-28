"""Formules explicites de départ, distinctes d'une interruption de parole."""

from __future__ import annotations

import re
import unicodedata

# 27/09/2026 : chercher « au revoir » dans une phrase fermerait le micro
# pendant « comment dit-on au revoir ? ». Toute la phrase doit être une
# formule de départ ; aucune similarité approximative ni décision du LLM.
_FORMULE = re.compile(
    r"(?:"
    r"(?:tu peux|vous pouvez) (?:disposer|te retirer|vous retirer)"
    r"|j ?en ai fini (?:avec toi|avec vous|pour (?:aujourd hui|le moment))"
    r"|je n ?ai plus besoin de (?:toi|vous)(?: pour le moment)?"
    r"|(?:on s ?arrete|arretons nous) la(?: pour (?:aujourd hui|le moment))?"
    r"|(?:ce sera|c ?est) tout(?: pour (?:aujourd hui|le moment))?"
    r"|(?:termine|ferme|arrete|coupe) (?:la|notre|cette) "
    r"(?:conversation|discussion|session)(?: vocale)?(?: et coupe le micro)?"
    r"|coupe le micro et termine (?:la|notre) (?:conversation|session)"
    r"|fin de (?:la|notre) (?:conversation|session)"
    r"|finissons (?:la|notre) (?:conversation|session)"
    r"|on en reste la|je te laisse|nous avons termine"
    r"|au revoir|a bientot|a la prochaine|a plus tard|bonne nuit"
    r")"
)
_BORD = re.compile(r"^(?:ok|okay|bon|eh bien|euh|merci|diapason)\b\s*")
_FIN = re.compile(r"\s*\b(?:diapason|merci|s il te plait|s il vous plait)$")


def demande_fin_conversation(texte: str) -> bool:
    """Une formule complète, hors citation, question, condition ou négation."""
    if any(signe in texte for signe in ('"', "«", "»", "“", "”", "?")):
        return False
    if texte.strip().startswith(("'", "‘")):
        return False
    normalise = "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    )
    normalise = re.sub(r"[^a-z0-9]+", " ", normalise).strip()
    while nouveau := _BORD.sub("", normalise, count=1):
        if nouveau == normalise:
            break
        normalise = nouveau
    while nouveau := _FIN.sub("", normalise, count=1):
        if nouveau == normalise:
            break
        normalise = nouveau
    return _FORMULE.fullmatch(normalise) is not None
