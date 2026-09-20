"""Questions de cadrage du chat, sans action ni attente d'inférence (19/09/2026)."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from diapason.core.types import Message, Role

POSER_QUESTIONS = "diapason_ask_questions"
# 19/09/2026 : le plafond de trois questions rejetait un cadrage utile plus
# long. On borne les données (16 Ko), pas leur nombre. 8192 jetons laissent
# remplir cette enveloppe ; le modèle s'arrête dès son JSON terminé.
QUESTIONNAIRE_MAX_OCTETS = 16_000
CADRAGE_MAX_JETONS = 8192
RAPPEL = (
    "Si des précisions sont nécessaires, pose tes questions en appelant "
    "diapason_ask_questions maintenant. Ne les écris pas dans le texte. "
    "Si la demande est déjà précise ou si l'utilisateur a répondu à tes "
    "questions, réponds directement sans redemander les mêmes informations."
)
CONSIGNE = """Questions interactives : pour une demande de création ou de planification
encore vague, utilise diapason_ask_questions pour demander les précisions
qui changent réellement le résultat, avec 2 à 4 choix courts par question.
Choisis toi-même le nombre nécessaire selon la demande : aucune question si
elle est claire, peu pour un besoin simple, davantage pour un projet complexe.
Chaque question est affichée séparément. Ne vise aucun quota, ne répète pas
une question sous une autre forme et arrête-toi dès que les informations
nécessaires sont couvertes. Garde les questions et leurs choix concis.
Respecte le périmètre donné : si l'utilisateur indique qu'une seule précision
manque, demande seulement celle-ci, sans ajouter des préférences facultatives.
L'utilisateur peut toujours écrire une autre réponse. Respecte sa langue.
Si tu as besoin de précisions, appelle cet outil au lieu d'écrire tes questions
en texte ou en liste : ce sont ses paramètres qui créent les boutons du chat.
Ne questionne pas pour une réponse factuelle, une instruction déjà précise,
ni pour redemander une information présente dans la discussion. Si l'utilisateur
te laisse choisir ou demande d'agir directement, avance avec ses indications.
Après ses réponses, réalise la demande : ne relance pas le même questionnaire.
Appelle cet outil SEUL avant les actions qui dépendent de ces réponses.
Ce questionnaire ne remplace jamais l'approbation d'une action sensible.
Exemple : « Prépare-moi un programme pour apprendre l'anglais » manque de
précisions. Réponse attendue : appel de diapason_ask_questions avec des
questions sur le niveau, l'objectif et le temps disponible. Pas de liste de
questions rédigée. Si ces informations sont déjà fournies, livre le programme.
"""


class _Texte(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*")
    @classmethod
    def ne_pas_reciter_le_nom_interne(cls, valeur):
        if isinstance(valeur, str) and POSER_QUESTIONS in valeur.casefold():
            raise ValueError("Le questionnaire doit contenir des questions lisibles.")
        return valeur


class _Choix(_Texte):
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=180)


class _Question(_Texte):
    title: str = Field(min_length=1, max_length=240)
    options: list[_Choix] = Field(min_length=2, max_length=4)

    @field_validator("options")
    @classmethod
    def choix_distincts(cls, choix: list[_Choix]) -> list[_Choix]:
        if len({c.label.casefold() for c in choix}) != len(choix):
            raise ValueError("Les choix doivent être distincts.")
        return choix


class _Demande(_Texte):
    intro: str = Field(default="", max_length=300)
    questions: list[_Question] = Field(min_length=1)

    @field_validator("questions")
    @classmethod
    def questions_distinctes(cls, questions: list[_Question]) -> list[_Question]:
        if len({q.title.casefold() for q in questions}) != len(questions):
            raise ValueError("Les questions doivent être distinctes.")
        return questions


class _Decision(_Demande):
    subject: str = Field(min_length=1, max_length=180)
    knownDetails: list[str] = Field(max_length=12)
    questions: list[_Question]


def schema_questions() -> dict[str, Any]:
    # Schéma aplati : les petits modèles locaux interprètent mal les $ref.
    return {
        "type": "function",
        "function": {
            "name": POSER_QUESTIONS,
            "description": (
                "Demande les précisions utiles avant une demande vague. "
                "Affiche des choix cliquables et attend la réponse. "
                "Aucune action exécutée."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intro": {"type": "string"},
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "minItems": 2,
                                    "maxItems": 4,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "description": {"type": "string"},
                                        },
                                        "required": ["label"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["title", "options"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["questions"],
                "additionalProperties": False,
            },
        },
    }


def valider_questions(arguments: str) -> dict[str, Any]:
    if len(arguments.encode("utf-8")) > QUESTIONNAIRE_MAX_OCTETS:
        raise ValueError("Le questionnaire est trop long.")
    demande = _Demande.model_validate_json(arguments)
    return {
        "id": uuid.uuid4().hex,
        "intro": demande.intro,
        "questions": [
            {
                "id": f"q{i + 1}",
                "title": question.title,
                "options": [
                    {"id": f"o{j + 1}", **choix.model_dump()}
                    for j, choix in enumerate(question.options)
                ],
            }
            for i, question in enumerate(demande.questions)
        ],
    }


def texte_questions(demande: dict[str, Any]) -> str:
    """L'historique, la copie et un ancien client gardent un texte intelligible."""
    lignes = [demande["intro"]] if demande["intro"] else []
    for i, question in enumerate(demande["questions"], 1):
        lignes.append(f"{i}. {question['title']}")
        lignes.extend(f"- {choix['label']}" for choix in question["options"])
    return "\n\n".join(lignes)


async def cadrer_sans_outils(
    moteur: Any, modele: str, messages: list[Message]
) -> dict[str, Any] | None:
    """Un modèle sans fonctions peut produire les données d'une carte, sans agir."""
    schema = schema_questions()["function"]["parameters"]
    schema["properties"]["questions"]["minItems"] = 0
    schema["properties"] = {
        "subject": {"type": "string", "description": "Sujet de la dernière demande."},
        "knownDetails": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
            "description": "Précisions explicitement fournies pour CE SUJET seulement.",
        },
        **schema["properties"],
    }
    schema["required"] = ["subject", "knownDetails", "questions"]
    consigne = (
        "Décide si la DERNIÈRE demande de l'utilisateur nécessite des précisions "
        "avant de la réaliser. Tu prépares uniquement les données d'un formulaire, "
        "sans exécuter la demande ni aucune action. Pour une création ou un "
        "programme encore vague, choisis toi-même le nombre de questions utiles, "
        "chacune avec 2 à 4 choix courts. Aucun quota : peu pour un besoin simple, "
        "davantage pour un projet complexe. Chaque question est affichée séparément. "
        "Ne répète pas une question sous une autre forme et arrête-toi dès que "
        "les informations nécessaires sont couvertes. "
        "Respecte le périmètre donné : si l'utilisateur indique qu'une seule "
        "précision manque, demande seulement celle-ci, sans ajouter des "
        "préférences facultatives. "
        "Respecte la langue de l'utilisateur. N'invente pas ses "
        "réponses et ne redemande pas des informations déjà données POUR CE SUJET. "
        "Un niveau ou un objectif donné pour une autre activité ne vaut pas "
        "automatiquement pour la nouvelle. Par exemple, un programme "
        "d'apprentissage sans niveau ni temps disponible nécessite un cadrage : "
        '{"questions":[{"title":"Quel est ton niveau dans ce domaine ?",'
        '"options":[{"label":"Débutant"},{"label":"J’ai déjà des bases"}]}]}. '
        "Pour une question factuelle, une demande déjà précise, des réponses "
        "à un questionnaire ou une demande d'avancer sans questions, renvoie "
        "une liste questions vide. Ne mets jamais de noms d’outils ou de "
        "fonctions dans les textes du formulaire. L'introduction est facultative ; "
        "ne répète "
        "pas une question dans l'introduction. Réponds uniquement avec du JSON "
        "conforme au schéma suivant :\n" + json.dumps(schema, ensure_ascii=False)
    )
    derniere_demande = next(
        (m.content or "" for m in reversed(messages) if m.role == Role.USER), ""
    )
    travail = [
        *messages,
        Message(role=Role.SYSTEM, content=consigne),
        Message(
            role=Role.USER,
            content=(
                "Évalue uniquement le besoin de précisions pour cette demande "
                "du dialogue, puis fournis le JSON du formulaire :\n"
                + json.dumps(derniere_demande, ensure_ascii=False)
                + "\nIdentifie d'abord le sujet de CETTE demande dans subject, "
                "puis les seules précisions déjà connues POUR CE SUJET dans "
                "knownDetails. Les réponses sur une autre activité ne "
                "décrivent pas automatiquement celle-ci. Complète ensuite "
                "les questions utiles pour personnaliser le résultat."
            ),
        ),
    ]
    fragments: list[str] = []
    taille = 0
    arret = None
    async with aclosing(
        moteur.stream_full(
            travail,
            model=modele,
            temperature=0.0,
            max_tokens=CADRAGE_MAX_JETONS,
            format=schema,
        )
    ) as flux:
        async for morceau in flux:
            if morceau.tool_calls:
                raise ValueError("Un formulaire ne doit pas demander d'action.")
            if morceau.content:
                taille += len(morceau.content.encode("utf-8"))
                if taille > QUESTIONNAIRE_MAX_OCTETS:
                    raise ValueError("Le questionnaire est trop long.")
                fragments.append(morceau.content)
            if morceau.finish_reason:
                arret = morceau.finish_reason
    if arret != "stop":
        raise ValueError("Le questionnaire n'a pas été terminé.")
    decision = _Decision.model_validate_json("".join(fragments))
    if not decision.questions:
        return None
    return valider_questions(
        decision.model_dump_json(exclude={"subject", "knownDetails"})
    )


def consigne_sans_outils(messages: list[Message]) -> list[Message]:
    return ajouter_consigne(
        messages,
        "Pour ce tour, le modèle ne peut pas appeler d'outils. Réponds à la "
        "demande avec les informations déjà disponibles et les précisions reçues. "
        "N'annonce aucune lecture, recherche ou modification non effectuée. "
        "Si la demande dépend d'une telle action, explique clairement que tu "
        "ne peux pas la réaliser dans ce tour. Ne demande pas à l'utilisateur "
        "d'appeler un outil ou une fonction interne.",
    )


BALISE = "```diapason-questions"


def ajouter_consigne(
    messages: list[Message], consigne: str = CONSIGNE
) -> list[Message]:
    copie = list(messages)
    for i in range(len(copie) - 1, -1, -1):
        if copie[i].role == Role.SYSTEM:
            copie[i] = replace(
                copie[i], content=(copie[i].content or "") + "\n\n" + consigne
            )
            return copie
    return [Message(role=Role.SYSTEM, content=consigne), *copie]


def est_un_cadrage_textuel(texte: str) -> bool:
    """Reconnaît une demande de précisions, pas une question citée dans un cours."""
    # 19/09/2026 : le 14b demandait simplement « Quel langage de programmation
    # veux-tu apprendre ? ». Exiger « j'ai besoin » ET une liste numérotée
    # empêchait cette vraie question de recevoir ses boutons.
    courte = texte.strip()
    question_courte = (
        len(courte) <= 500
        and courte.endswith("?")
        and not re.search(r"[.!:\n]", courte)
        and re.match(
            r"^(?:quel(?:le)?s?\b|combien\b|(?:est.ce que )?"
            r"(?:veux|souhaites|préfères|peux|pourrais|as|es).tu\b)",
            courte,
            re.I,
        )
        and re.search(r"\b(?:tu|ton|ta|tes|votre|vos|vous)\b", courte, re.I)
    )
    return bool(question_courte) or bool(
        len(texte) < 6000
        and re.search(
            r"(?:j['’]ai besoin|quelques précisions|pourrais.tu me dire|"
            r"peux.tu (?:me dire|préciser)|I need|could you (?:tell|clarify))",
            texte[:500],
            re.I,
        )
        and re.search(r"^\s*1[.)]\s+[^\n]*\?", texte, re.M)
    )


def instruire_questions_texte(messages: list[Message]) -> list[Message]:
    """Les routes de fournisseurs qui ne transmettent que du texte gardent les choix."""
    consigne = CONSIGNE.replace(
        "utilise diapason_ask_questions", "pose un questionnaire"
    )
    consigne += (
        "\nPour un questionnaire seulement, réponds avec un unique bloc "
        "```diapason-questions suivi du JSON "
        '{"intro":"...","questions":[{"title":"...",'
        '"options":[{"label":"...","description":"..."},{"label":"..."}]}]}'
        " puis ferme le bloc par ```. Aucun autre texte autour. "
        "Pour une réponse ordinaire, écris normalement sans ce bloc."
    )
    # Certains fournisseurs ne gardent que le dernier SYSTEM : prolonger le
    # cadrage existant préserve aussi l'identité, au lieu de la remplacer.
    return ajouter_consigne(messages, consigne)


async def filtrer_questions_texte(
    source: AsyncIterator[str],
) -> AsyncIterator[tuple[str, Any]]:
    """Ne retient que le bloc balisé ; le texte ordinaire reste en flux."""
    tampon = ""
    direct = False
    async for token in source:
        if direct:
            yield "token", token
            continue
        tampon += token
        debut = tampon.lstrip()
        if len(tampon.encode("utf-8")) > QUESTIONNAIRE_MAX_OCTETS or not (
            BALISE.startswith(debut) or debut.startswith(BALISE)
        ):
            direct = True
            yield "token", tampon
            tampon = ""
    if not tampon:
        return
    contenu = tampon.strip()
    if contenu.startswith(BALISE) and contenu.endswith("```"):
        try:
            demande = valider_questions(contenu[len(BALISE) : -3].strip())
        except ValueError:
            pass
        else:
            yield "questions", demande
            yield "token", texte_questions(demande)
            return
    yield "token", tampon
