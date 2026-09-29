"""Format local de génération ; le contrat sauvegardé demeure Programme."""

from pydantic import Field, StrictInt, StrictStr, model_validator

from diapason.etudes.modeles import Contrat, Programme


class QuestionPreparation(Contrat):
    enonce: str = Field(alias="prompt", min_length=5, max_length=1400)
    objectif: str = Field(alias="objective", min_length=1, max_length=300)
    explication: str = Field(alias="explanation", min_length=1, max_length=2500)
    indice: str = Field(alias="hint", min_length=1, max_length=500)
    citation: str = Field(alias="quote", max_length=1200)


class QcmPreparation(QuestionPreparation):
    choix: list[str] = Field(alias="choices", min_length=2, max_length=5)
    reponse: StrictInt = Field(alias="answer", ge=0, le=4)


class OuvertePreparation(QuestionPreparation):
    reponse: StrictStr = Field(alias="answer", min_length=1, max_length=2500)
    criteres: list[str] = Field(alias="criteria", min_length=1, max_length=5)


class CoursPreparation(Contrat):
    titre: str = Field(alias="title", min_length=1, max_length=200)
    objectifs: list[str] = Field(alias="objectives", min_length=1, max_length=12)
    cours: str = Field(alias="lesson", min_length=30, max_length=18_000)
    essentiels: list[str] = Field(alias="essentials", min_length=1, max_length=12)

    @model_validator(mode="after")
    def libelles_valides(self):
        if any(not v or len(v) > 300 for v in self.objectifs):
            raise ValueError("Un objectif est vide ou dépasse 300 caractères.")
        if any(not v or len(v) > 600 for v in self.essentiels):
            raise ValueError("Un essentiel est vide ou dépasse 600 caractères.")
        return self


class QuestionsPreparation(Contrat):
    qcm: list[QcmPreparation] = Field(
        alias="choiceQuestions", min_length=1, max_length=11
    )
    ouvertes: list[OuvertePreparation] = Field(
        alias="openQuestions", min_length=1, max_length=11
    )


class ProgrammePreparation(CoursPreparation, QuestionsPreparation):
    def developper(self, references: dict[str, tuple[int, str]]) -> Programme:
        # 29/09/2026 : cinq questions dépassaient 180 s, puis une lettre
        # de QCM obligeait à régénérer tout le cours. Le modèle donne un
        # indice explicite ; aucune lettre ou paraphrase n'est devinée.
        questions = []
        for n, q in enumerate([*self.qcm, *self.ouvertes], 1):
            if q.citation and q.citation not in references:
                raise ValueError(f"Question {n} : référence de document inconnue.")
            source, citation = references.get(q.citation, (None, ""))
            choix = isinstance(q, QcmPreparation)
            reponse = q.reponse
            if choix:
                if type(reponse) is not int or not 0 <= reponse < len(q.choix):
                    raise ValueError(
                        f"Question {n} : answer doit être l'indice entier d'un "
                        "choix, à partir de zéro."
                    )
                reponse = q.choix[reponse]
            elif not isinstance(reponse, str):
                raise ValueError(f"Question {n} : une réponse ouverte est un texte.")
            questions.append(
                {
                    "id": f"q{n}",
                    "kind": "choice" if choix else "open",
                    "prompt": q.enonce,
                    "objective": q.objectif,
                    "choices": q.choix if choix else [],
                    "answer": reponse,
                    "explanation": q.explication,
                    "hint": q.indice,
                    "criteria": ["Choisir la bonne réponse."] if choix else q.criteres,
                    "sourceIndex": source,
                    "quote": citation,
                }
            )
        return Programme.model_validate(
            {
                "title": self.titre,
                "objectives": self.objectifs,
                "lesson": self.cours,
                "essentials": self.essentiels,
                "questions": questions,
            }
        )
