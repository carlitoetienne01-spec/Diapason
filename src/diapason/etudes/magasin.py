"""Épreuves locales, transactions courtes et version optimiste par séance."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from diapason.etudes.modeles import DemandeEtude, MaterielEtude, Programme
from diapason.security.file_utils import secure_create


class ConflitEtude(ValueError):
    """Une autre vue a déjà enregistré une modification."""


def vue_publique(s: dict) -> dict:
    fini = s["state"] == "finished"
    programme = s["program"]
    questions = []
    for q in programme["questions"]:
        public = {k: q[k] for k in ("id", "kind", "prompt", "objective", "choices")}
        public["maxScore"] = len(q["criteria"])
        if fini or (s["mode"] == "practice" and q["id"] in s["grades"]):
            public.update(
                {
                    k: q[k]
                    for k in (
                        "answer",
                        "explanation",
                        "sourceIndex",
                        "quote",
                        "criteria",
                    )
                }
            )
        questions.append(public)
    return {
        **{
            k: s[k]
            for k in (
                "id",
                "conversationId",
                "mode",
                "model",
                "level",
                "state",
                "version",
                "updatedAt",
                "responses",
                "assisted",
            )
        },
        "title": programme["title"],
        "createdAt": s.get("createdAt", s["updatedAt"]),
        "placement": s.get("placement"),
        "currentQuestionId": s.get(
            "currentQuestionId", programme["questions"][0]["id"]
        ),
        "objectives": programme["objectives"],
        "lesson": programme["lesson"]
        if s["state"] != "active" or s["mode"] == "practice"
        else "",
        "essentials": programme["essentials"]
        if s["state"] != "active" or s["mode"] == "practice"
        else [],
        "questions": questions,
        "sources": [
            {"name": d["name"], "characters": len(d["text"])} for d in s["sources"]
        ],
        "hints": {
            q["id"]: q["hint"]
            for q in programme["questions"]
            if q["id"] in s["assisted"]
        },
        "grades": s["grades"] if fini or s["mode"] == "practice" else {},
    }


class MagasinEtudes:
    def __init__(self, chemin: Path):
        if not isinstance(chemin, Path):
            raise TypeError("Le magasin exige un véritable chemin.")
        self.chemin = chemin
        secure_create(chemin)
        with closing(self._connexion()) as c, c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS etudes (id TEXT PRIMARY KEY, "
                "conversation TEXT NOT NULL, version INTEGER NOT NULL, "
                "updated INTEGER NOT NULL, contenu TEXT NOT NULL)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS etudes_conversation ON "
                "etudes(conversation, updated)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS discussions_supprimees "
                "(conversation TEXT PRIMARY KEY)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS materiels_etudes "
                "(conversation TEXT PRIMARY KEY, contenu TEXT NOT NULL)"
            )

    def _connexion(self):
        return sqlite3.connect(self.chemin, timeout=10)

    def garder_sources(self, conversation: str, sources: list[dict]) -> None:
        materiel = MaterielEtude.model_validate(
            {"conversationId": conversation, "sources": sources}
        )
        with closing(self._connexion()) as c, c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute(
                "SELECT 1 FROM discussions_supprimees WHERE conversation=?",
                (conversation,),
            ).fetchone():
                raise ValueError("Cette discussion a été supprimée.")
            c.execute(
                "INSERT OR REPLACE INTO materiels_etudes VALUES (?, ?)",
                (
                    conversation,
                    json.dumps(
                        [d.model_dump(by_alias=True) for d in materiel.sources],
                        ensure_ascii=False,
                    ),
                ),
            )

    def lire_sources(self, conversation: str) -> list[dict]:
        with closing(self._connexion()) as c:
            r = c.execute(
                "SELECT contenu FROM materiels_etudes WHERE conversation=?",
                (conversation,),
            ).fetchone()
        return json.loads(r[0]) if r else []

    def creer(
        self, demande: DemandeEtude, programme: Programme, creation: int | None = None
    ) -> dict:
        s = {
            "id": uuid.uuid4().hex,
            "conversationId": demande.conversation,
            "mode": demande.mode,
            "model": demande.modele,
            "level": demande.niveau,
            "state": "ready",
            "version": 1,
            "updatedAt": time.time_ns() // 1_000_000,
            "createdAt": creation
            if creation is not None
            else time.time_ns() // 1_000_000,
            "placement": demande.emplacement.model_dump(by_alias=True)
            if demande.emplacement is not None
            else None,
            "program": programme.model_dump(by_alias=True),
            "sources": [d.model_dump(by_alias=True) for d in demande.sources],
            "responses": {},
            "grades": {},
            "assisted": [],
            "currentQuestionId": programme.questions[0].identifiant,
        }
        with closing(self._connexion()) as c, c:
            # Une préparation peut finir après la suppression du fil.
            # Le même verrou d'écriture empêche de recréer ses documents.
            c.execute("BEGIN IMMEDIATE")
            if c.execute(
                "SELECT 1 FROM discussions_supprimees WHERE conversation=?",
                (demande.conversation,),
            ).fetchone():
                raise ValueError("Cette discussion a été supprimée.")
            c.execute(
                "INSERT INTO etudes VALUES (?, ?, ?, ?, ?)",
                (
                    s["id"],
                    s["conversationId"],
                    1,
                    s["updatedAt"],
                    json.dumps(s, ensure_ascii=False),
                ),
            )
        return s

    def lire(self, identifiant: str) -> dict:
        with closing(self._connexion()) as c:
            ligne = c.execute(
                "SELECT contenu FROM etudes WHERE id=?", (identifiant,)
            ).fetchone()
        if ligne is None:
            raise KeyError(identifiant)
        return json.loads(ligne[0])

    def lister(self, conversation: str) -> list[dict]:
        with closing(self._connexion()) as c:
            lignes = c.execute(
                "SELECT contenu FROM etudes WHERE conversation=? ORDER BY "
                "updated DESC, rowid DESC",
                (conversation,),
            ).fetchall()
        return [vue_publique(json.loads(ligne[0])) for ligne in lignes]

    def supprimer(self, identifiant: str) -> None:
        with closing(self._connexion()) as c, c:
            c.execute("DELETE FROM etudes WHERE id=?", (identifiant,))

    def supprimer_conversation(self, conversation: str) -> None:
        with closing(self._connexion()) as c, c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM etudes WHERE conversation=?", (conversation,))
            c.execute(
                "DELETE FROM materiels_etudes WHERE conversation=?", (conversation,)
            )
            c.execute(
                "INSERT OR IGNORE INTO discussions_supprimees VALUES (?)",
                (conversation,),
            )

    def _ecrire(self, s: dict, version: int) -> dict:
        # 29/09/2026 : une réponse déplaçait le cours au bas du fil. Pour
        # les anciennes études sans date de création, figer le seul repère
        # disponible AVANT de dater cette nouvelle écriture.
        s.setdefault("createdAt", s["updatedAt"])
        s["version"] = version + 1
        s["updatedAt"] = time.time_ns() // 1_000_000
        with closing(self._connexion()) as c, c:
            resultat = c.execute(
                "UPDATE etudes SET version=?, updated=?, contenu=? WHERE "
                "id=? AND version=?",
                (
                    s["version"],
                    s["updatedAt"],
                    json.dumps(s, ensure_ascii=False),
                    s["id"],
                    version,
                ),
            )
            if resultat.rowcount != 1:
                raise ConflitEtude(
                    "Cette épreuve a changé dans une autre fenêtre. "
                    "Recharge-la pour continuer."
                )
        return s

    def _version(self, identifiant: str, version: int) -> dict:
        s = self.lire(identifiant)
        if s["version"] != version:
            raise ConflitEtude(
                "Cette épreuve a changé. Recharge-la pour conserver les "
                "dernières réponses."
            )
        return s

    def modifier(
        self, identifiant: str, version: int, action: str, donnees: dict
    ) -> dict:
        s = self._version(identifiant, version)
        if action == "resume":
            return self._ecrire(s, version)
        if action == "navigate":
            if s["state"] == "ready":
                raise ValueError("Commence l'épreuve avant de changer de question.")
            qid = donnees.get("questionId")
            if not any(q["id"] == qid for q in s["program"]["questions"]):
                raise ValueError("Question inconnue.")
            s["currentQuestionId"] = qid
            return self._ecrire(s, version)
        if action == "start":
            if s["state"] != "ready":
                raise ValueError("L'épreuve est déjà commencée.")
            s["state"] = "active"
        else:
            if s["state"] != "active":
                raise ValueError("Commence l'épreuve avant de répondre.")
            qid = donnees.get("questionId")
            q = next((q for q in s["program"]["questions"] if q["id"] == qid), None)
            if q is None:
                raise ValueError("Question inconnue.")
            if qid in s["grades"]:
                raise ValueError("Cette réponse a déjà été corrigée.")
            if action == "hint":
                if s["mode"] != "practice":
                    raise ValueError("Les indices ne sont pas disponibles en examen.")
                if qid not in s["assisted"]:
                    s["assisted"].append(qid)
            elif action == "answer":
                texte = donnees.get("text", "").strip()
                if len(texte) > 8000 or (
                    q["kind"] == "choice" and texte and texte not in q["choices"]
                ):
                    raise ValueError("Réponse invalide.")
                s["responses"][qid] = {"text": texte}
                if donnees.get("spokenText"):
                    s["responses"][qid]["spokenText"] = donnees["spokenText"][:8000]
                s["currentQuestionId"] = qid
            else:
                raise ValueError("Action inconnue.")
        return self._ecrire(s, version)

    def noter(self, identifiant: str, version: int, qid: str, correction: dict) -> dict:
        s = self._version(identifiant, version)
        if s["state"] != "active" or s["mode"] != "practice":
            raise ValueError("La correction immédiate est réservée à l'entraînement.")
        s["grades"][qid] = correction
        return self._ecrire(s, version)

    def terminer(self, identifiant: str, version: int, corrections: dict) -> dict:
        s = self._version(identifiant, version)
        if s["state"] != "active":
            raise ValueError("L'épreuve n'est pas en cours.")
        if set(corrections) != {q["id"] for q in s["program"]["questions"]}:
            raise ValueError("La correction doit couvrir toutes les questions.")
        s["grades"] = corrections
        s["state"] = "finished"
        return self._ecrire(s, version)
