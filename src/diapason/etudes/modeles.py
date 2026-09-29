"""Contrats pédagogiques ; le corrigé ne fait pas partie de la vue publique."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contrat(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, str_strip_whitespace=True
    )


class Source(Contrat):
    nom: str = Field(alias="name", min_length=1, max_length=180)
    texte: str = Field(alias="text", min_length=1, max_length=48_000)
    tronque: bool = Field(alias="truncated", default=False)


class MaterielEtude(Contrat):
    conversation: str = Field(alias="conversationId", min_length=1, max_length=160)
    sources: list[Source] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def documents_entiers(self):
        if any(s.tronque for s in self.sources):
            raise ValueError("Un document tronqué ne peut pas servir de cours complet.")
        if sum(len(s.texte) for s in self.sources) > 48_000:
            raise ValueError("Les sources dépassent 48 000 caractères.")
        return self


class EmplacementEtude(Contrat):
    apres_message: str | None = Field(alias="afterMessageId", max_length=160)
    ouverture: int = Field(alias="openedAt", ge=0, strict=True)


class DemandeEtude(Contrat):
    conversation: str = Field(alias="conversationId", min_length=1, max_length=160)
    modele: str = Field(alias="model", min_length=1, max_length=160)
    sujet: str = Field(alias="topic", min_length=3, max_length=1200)
    niveau: str = Field(alias="level", min_length=1, max_length=120)
    mode: Literal["practice", "exam"] = "practice"
    nombre: int = Field(alias="questionCount", default=5, ge=2, le=12)
    sources: list[Source] = Field(default_factory=list, max_length=2)
    emplacement: EmplacementEtude | None = Field(alias="placement", default=None)

    @model_validator(mode="after")
    def documents_entiers(self):
        if any(s.tronque for s in self.sources):
            raise ValueError(
                "Un document tronqué ne permet pas de couvrir le cours. "
                "Joins le chapitre à étudier."
            )
        # 29/09/2026 : 48k caractères (~12k jetons) laissent la place au
        # cours et au corrigé dans les 32k du modèle local, deux sources incluses.
        if sum(len(s.texte) for s in self.sources) > 48_000:
            raise ValueError(
                "Les sources dépassent 48 000 caractères. Choisis les "
                "chapitres à étudier."
            )
        return self


class Question(Contrat):
    identifiant: str = Field(alias="id", pattern=r"^q[1-9][0-9]?$", max_length=3)
    type: Literal["choice", "open"] = Field(alias="kind")
    enonce: str = Field(alias="prompt", min_length=5, max_length=1400)
    objectif: str = Field(alias="objective", min_length=1, max_length=300)
    choix: list[str] = Field(alias="choices", max_length=5)
    reponse: str = Field(alias="answer", min_length=1, max_length=2500)
    explication: str = Field(alias="explanation", min_length=1, max_length=2500)
    indice: str = Field(alias="hint", min_length=1, max_length=500)
    criteres: list[str] = Field(alias="criteria", min_length=1, max_length=5)
    source: int | None = Field(alias="sourceIndex", ge=0, le=1)
    citation: str = Field(alias="quote", max_length=1200)

    @model_validator(mode="after")
    def coherence(self):
        if any(not s or len(s) > 500 for s in [*self.choix, *self.criteres]):
            raise ValueError("Choix ou critère vide ou trop long.")
        if self.type == "choice":
            if len(self.choix) < 2 or len({c.casefold() for c in self.choix}) != len(
                self.choix
            ):
                raise ValueError("Un QCM exige des choix distincts.")
            if self.reponse not in self.choix or len(self.criteres) != 1:
                raise ValueError(
                    "Le corrigé du QCM doit être un choix exact, sur un point."
                )
        elif self.choix:
            raise ValueError("Une question ouverte n'a pas de choix.")
        return self


class Programme(Contrat):
    titre: str = Field(alias="title", min_length=1, max_length=200)
    objectifs: list[str] = Field(alias="objectives", min_length=1, max_length=12)
    cours: str = Field(alias="lesson", min_length=30, max_length=18_000)
    essentiels: list[str] = Field(alias="essentials", min_length=1, max_length=12)
    questions: list[Question] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def coherence(self):
        if len({q.identifiant for q in self.questions}) != len(self.questions):
            raise ValueError("Les questions doivent avoir des identifiants distincts.")
        if any(q.objectif not in self.objectifs for q in self.questions):
            raise ValueError("Chaque question doit évaluer un objectif du cours.")
        if any(not v or len(v) > 600 for v in [*self.objectifs, *self.essentiels]):
            raise ValueError("Un objectif ou essentiel est vide ou trop long.")
        return self


def valider_sources(programme: Programme, demande: DemandeEtude) -> None:
    if len(programme.questions) != demande.nombre:
        raise ValueError("Le nombre de questions ne correspond pas à la demande.")
    for q in programme.questions:
        if not demande.sources:
            if q.source is not None or q.citation:
                raise ValueError(
                    "Une référence ne peut pas être inventée sans document."
                )
            continue
        if q.source is None or q.source >= len(demande.sources):
            raise ValueError("La question doit citer une source fournie.")

        def normaliser(v):
            return " ".join(v.split())

        if not q.citation or normaliser(q.citation) not in normaliser(
            demande.sources[q.source].texte
        ):
            raise ValueError("L'extrait cité n'existe pas dans le document.")


class Correction(Contrat):
    acquis: list[bool] = Field(alias="criteriaMet", max_length=5, strict=True)
    retour: str = Field(alias="feedback", min_length=1, max_length=2500)


class ActionEtude(Contrat):
    version: int = Field(ge=1)
    action: Literal["start", "answer", "hint", "check", "finish", "navigate", "resume"]
    question: str | None = Field(alias="questionId", default=None, max_length=3)
    texte: str = Field(alias="text", default="", max_length=8000)
    entendu: str = Field(alias="spokenText", default="", max_length=8000)
