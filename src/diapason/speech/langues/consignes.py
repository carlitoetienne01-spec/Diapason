"""Ce que le modèle doit respecter dans chaque langue.

Les consignes sont en anglais, comme le reste du prompt vocal : elles
disent la langue à parler, elles ne sont pas la phrase à lire.
"""

from __future__ import annotations

CONSIGNE_KREYOL = (
    "The user is speaking Haitian Creole (kreyòl ayisyen). "
    "Reply only in kreyòl, in the official orthography. "
    "When they fit, use the native idioms « men wi », « sa k ap fèt », "
    "« ann avanse » and « mwen la ». "
    "Do not translate French or English word for word. "
    "Sound like a native conversation: warm, short, with no French "
    "or English mixed in."
)

CONSIGNE_FRANCAIS = (
    "The user is speaking French. Reply only in French, clear and neutral. "
    "Do not mix in Kreyòl words."
)

CONSIGNE_ANGLAIS = (
    "The user is speaking English. Reply only in English, clear and natural. "
    "Do not mix in Kreyòl or French."
)

# Amorce de Whisper, pas une consigne. Le modèle continue ce texte : ces
# mots rendent « mwen » et « mèsi » écrivables alors que la langue acoustique
# reste le français, le plus proche voisin du kreyòl dans ce modèle.
INVITE_OREILLE = "Mwen, mèsi, wi, kijan, sa k ap fèt, bonjou, men wi, ann avanse."

CONSIGNE_PERMANENTE = (
    "Switch language with the user, each turn: French, Haitian Creole "
    "(kreyòl ayisyen), or English. A mixed sentence follows its dominant "
    "language. A short unclear turn stays in the previous language. "
    "Kreyòl uses official orthography and native phrasing. "
    "French and English stay in their own words, with no accidental Kreyòl."
)


def consigne_kreyol() -> str:
    return CONSIGNE_KREYOL


def consigne_francais() -> str:
    return CONSIGNE_FRANCAIS


def consigne_anglais() -> str:
    return CONSIGNE_ANGLAIS


def consigne_pour(code: str) -> str:
    if code == "ht":
        return CONSIGNE_KREYOL
    if code == "en":
        return CONSIGNE_ANGLAIS
    return CONSIGNE_FRANCAIS
