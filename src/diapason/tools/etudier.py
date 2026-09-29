"""Le même cours et le même examen depuis la voix, le chat et le formulaire."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.etudes.conversation import contexte_actuel, nombre_questions_explicite
from diapason.etudes.magasin import vue_publique
from diapason.etudes.modeles import ActionEtude, DemandeEtude
from diapason.tools._stubs import BaseTool, ToolSpec


def _rendre(etude: dict, *, texte: str = "") -> ToolResult:
    question = next(
        (q for q in etude["questions"] if q["id"] == etude["currentQuestionId"]),
        etude["questions"][0],
    )
    retour = {
        "sessionId": etude["id"],
        "version": etude["version"],
        "title": etude["title"],
        "state": etude["state"],
        "mode": etude["mode"],
        "sources": etude["sources"],
        "currentQuestion": question,
        "response": etude["responses"].get(question["id"]),
        "grade": etude["grades"].get(question["id"]),
        "hint": etude["hints"].get(question["id"]),
        "answered": len(etude["responses"]),
        "questionCount": len(etude["questions"]),
    }
    if etude["state"] == "finished":
        retour["score"] = sum(g["score"] for g in etude["grades"].values())
        retour["maxScore"] = sum(q["maxScore"] for q in etude["questions"])
        retour["review"] = [
            {
                "objective": q["objective"],
                "grade": etude["grades"].get(q["id"]),
                "assisted": q["id"] in etude["assisted"],
            }
            for q in etude["questions"]
        ]
    if etude["state"] == "ready":
        retour["objectives"] = etude["objectives"]
    if texte:
        retour["text"] = texte
    return ToolResult(
        tool_name="study",
        success=True,
        content=json.dumps(retour, ensure_ascii=False),
        metadata={"study": etude, "persistence": "local"},
    )


@ToolRegistry.register("study")
class EtudierTool(BaseTool):
    tool_id = "study"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="study",
            description=(
                "Teach with the saved study shared by chat, voice and Study panel. "
                "Read first to resume the exact current question. Prepare creates "
                "a saved course/test using attached documents or existing sources. "
                "Start begins the test. Ask ONE current question and wait. Answer "
                "records the student's exact latest words; never supply an answer. "
                "For choices set choiceIndex (1-based) from the student's choice. "
                "Check corrects practice only. Next advances; lesson/source reads "
                "material by part; hint helps practice. Finish grades the exam "
                "only when requested. Use sessionId and version from the latest "
                "result for mutations. Read again on conflict. Claim success "
                "only after successful execution."
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "read",
                            "prepare",
                            "resume",
                            "start",
                            "answer",
                            "next",
                            "previous",
                            "hint",
                            "check",
                            "finish",
                            "lesson",
                            "source",
                        ],
                    },
                    "sessionId": {"type": "string"},
                    "version": {"type": "integer", "minimum": 1},
                    "topic": {"type": "string", "maxLength": 1200},
                    "level": {"type": "string", "maxLength": 120},
                    "mode": {"type": "string", "enum": ["practice", "exam"]},
                    "questionCount": {"type": "integer", "minimum": 2, "maximum": 12},
                    "choiceIndex": {"type": "integer", "minimum": 1, "maximum": 5},
                    "part": {"type": "integer", "minimum": 1},
                    "sourceIndex": {"type": "integer", "minimum": 1, "maximum": 2},
                    "useDocuments": {
                        "type": "boolean",
                        "description": (
                            "True by default; false only for a new topic "
                            "explicitly requested without those documents."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="study",
            # 180 s de génération + 20 s de restitution, puis 10 s de marge
            # pour que l'outil rende son échec avant la garde de l'exécuteur.
            timeout_seconds=210,
            metadata={"risk": "routine_write", "reversible": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        contexte = contexte_actuel()
        if contexte is None or not contexte.conversation:
            return ToolResult(
                tool_name="study",
                success=False,
                content="Ouvre une discussion pour retrouver son parcours Étudier.",
            )
        try:
            try:
                meme_boucle = asyncio.get_running_loop() is contexte.boucle
            except RuntimeError:
                meme_boucle = False
            if meme_boucle:
                raise ValueError(
                    "L'outil Étudier doit s'exécuter hors de la boucle du serveur."
                )
            futur = asyncio.run_coroutine_threadsafe(
                self._agir(contexte, params), contexte.boucle
            )
            try:
                # La génération a déjà son plafond de 180 s ; les 20 s restants
                # couvrent l'écriture et la restitution, sans attente infinie.
                resultat = futur.result(timeout=200)
                if resultat.success:
                    contexte.actions.add(params.get("action", ""))
                    s = resultat.metadata.get("study") or {}
                    if s:
                        contexte.etat_lu = s["state"]
                        contexte.resultats.append(
                            (params.get("action", ""), json.loads(resultat.content))
                        )
                    contexte.correction_lue = contexte.correction_lue or bool(
                        (s.get("grades") or {}).get(s.get("currentQuestionId"))
                        or s.get("state") == "finished"
                    )
                return resultat
            except TimeoutError:
                futur.cancel()
                raise ValueError(
                    "La préparation a dépassé son délai ; "
                    "aucune réussite n'est annoncée."
                ) from None
        except Exception as exc:
            return ToolResult(
                tool_name="study",
                success=False,
                content=str(exc),
                metadata={"persistence": "check_before_retry"},
            )

    async def _agir(self, contexte, p):
        service = contexte.service
        depot = service.depot
        action = p.get("action", "")
        liste = await asyncio.to_thread(depot.lister, contexte.conversation)
        if action == "list":
            resumes = [
                {k: s[k] for k in ("id", "title", "state", "mode", "version")}
                for s in liste
            ]
            return ToolResult(
                tool_name="study",
                success=True,
                content=json.dumps(resumes, ensure_ascii=False),
                metadata={"sessions": resumes},
            )
        # Le modèle vocal fournissait « nouveau » comme identifiant à prepare.
        # Une création choisit son id côté serveur et reprend uniquement les
        # sources du fil courant ; aucun id proposé ne doit la détourner.
        identifiant = (
            (liste[0]["id"] if liste else None)
            if action == "prepare"
            else p.get("sessionId") or (liste[0]["id"] if liste else None)
        )
        s = await asyncio.to_thread(depot.lire, identifiant) if identifiant else None
        if s and s["conversationId"] != contexte.conversation:
            raise ValueError("Cette étude n'appartient pas à la discussion active.")
        if action == "prepare":
            materiel = await asyncio.to_thread(
                depot.lire_sources, contexte.conversation
            )
            sources = (
                (materiel or contexte.sources or (s["sources"] if s else []))
                if p.get("useDocuments", True)
                else []
            )
            nombre = nombre_questions_explicite(contexte.demande)
            demande = DemandeEtude.model_validate(
                {
                    "conversationId": contexte.conversation,
                    "model": contexte.modele,
                    "topic": p.get("topic", ""),
                    "level": p.get("level", "Débutant"),
                    "mode": p.get("mode", "practice"),
                    # L'essai réel omettait ce paramètre et transformait les
                    # deux questions demandées en cinq. La quantité explicite
                    # vient des mots de l'étudiant, avant le défaut du modèle.
                    "questionCount": nombre
                    if nombre is not None
                    else p.get("questionCount", 5),
                    "sources": sources,
                }
            )
            return _rendre(
                await service.creer(demande),
                texte="Le cours est enregistré et prêt à consulter.",
            )
        if s is None:
            if action == "read":
                sources = (
                    await asyncio.to_thread(depot.lire_sources, contexte.conversation)
                    or contexte.sources
                )
                return ToolResult(
                    tool_name="study",
                    success=True,
                    content=json.dumps(
                        {
                            "state": "none",
                            "documentsAvailable": [d["name"] for d in sources],
                            "text": "Aucun parcours préparé dans cette discussion.",
                        },
                        ensure_ascii=False,
                    ),
                )
            raise ValueError(
                "Aucune étude dans cette discussion. "
                "Il faut préparer un parcours à partir d'un sujet."
            )
        public = vue_publique(s)
        if action == "read":
            return _rendre(public)
        if action in {"lesson", "source"}:
            if s["state"] == "active" and s["mode"] == "exam":
                raise ValueError(
                    "Le cours et ses sources sont masqués pendant l'examen."
                )
            contenu = public["lesson"]
            if action == "source":
                index = p.get("sourceIndex", 1) - 1
                if index < 0 or index >= len(s["sources"]):
                    raise ValueError("Document inconnu.")
                contenu = s["sources"][index]["text"]
            partie = p.get("part", 1)
            # 3 000 caractères : une explication orale reste un échange,
            # et les autres parties restent accessibles, jamais tronquées en secret.
            total = max(1, (len(contenu) + 2999) // 3000)
            if not isinstance(partie, int) or partie < 1 or partie > total:
                raise ValueError("Partie inconnue.")
            return _rendre(
                public,
                texte=f"Partie {partie}/{total}\n"
                + contenu[(partie - 1) * 3000 : partie * 3000],
            )
        if not p.get("sessionId") or not isinstance(p.get("version"), int):
            raise ValueError("Relis d'abord l'étude pour obtenir sa version actuelle.")
        qid = public["currentQuestionId"]
        question = next(q for q in public["questions"] if q["id"] == qid)
        donnees = {"action": action, "version": p["version"], "questionId": qid}
        if action in {"next", "previous"}:
            index = next(i for i, q in enumerate(public["questions"]) if q["id"] == qid)
            index += 1 if action == "next" else -1
            if index < 0 or index >= len(public["questions"]):
                raise ValueError("Il n'y a pas d'autre question dans cette direction.")
            donnees.update(
                action="navigate", questionId=public["questions"][index]["id"]
            )
        if action == "answer":
            texte = contexte.demande.strip()
            if not texte:
                raise ValueError("Aucune réponse de l'étudiant à enregistrer.")
            if question["kind"] == "choice":
                choix = p.get("choiceIndex")
                if (
                    not isinstance(choix, int)
                    or choix < 1
                    or choix > len(question["choices"])
                ):
                    raise ValueError(
                        "Le choix doit correspondre aux options de cette question."
                    )
                donnees["text"] = question["choices"][choix - 1]
            else:
                donnees["text"] = texte
            donnees["spokenText"] = texte
        resultat = await service.agir(s["id"], ActionEtude.model_validate(donnees))
        return _rendre(resultat)
