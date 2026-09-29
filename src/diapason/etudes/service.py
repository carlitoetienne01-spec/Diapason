"""Un seul parcours transactionnel pour le formulaire, le chat et la voix."""

from __future__ import annotations

import asyncio
import time

from diapason.etudes.generation import corriger, preparer
from diapason.etudes.magasin import ConflitEtude, MagasinEtudes, vue_publique
from diapason.etudes.modeles import ActionEtude, DemandeEtude, Question


class ServiceEtudes:
    def __init__(self, depot: MagasinEtudes, moteur):
        self.depot = depot
        self.moteur = moteur
        self.verrou = asyncio.Lock()

    async def creer(self, demande: DemandeEtude) -> dict:
        if self.verrou.locked():
            raise ConflitEtude("Une préparation ou correction est déjà en cours.")
        async with self.verrou:
            creation = time.time_ns() // 1_000_000
            programme = await preparer(self.moteur, demande)
            s = await asyncio.to_thread(self.depot.creer, demande, programme, creation)
        return vue_publique(s)

    async def agir(self, session_id: str, action: ActionEtude) -> dict:
        if action.action in {"start", "answer", "hint", "navigate", "resume"}:
            s = await asyncio.to_thread(
                self.depot.modifier,
                session_id,
                action.version,
                action.action,
                action.model_dump(by_alias=True),
            )
            return vue_publique(s)
        porte = self.verrou
        if porte.locked():
            raise ConflitEtude("Une préparation ou correction est déjà en cours.")
        async with porte:
            s = await asyncio.to_thread(self.depot.lire, session_id)
            if s["version"] != action.version:
                raise ConflitEtude(
                    "Cette épreuve a changé. Recharge-la avant de corriger."
                )
            if s["state"] == "finished" and action.action == "finish":
                return vue_publique(s)
            if s["state"] != "active":
                raise ValueError("Commence l'épreuve avant la correction.")
            questions = [Question.model_validate(q) for q in s["program"]["questions"]]
            if action.action == "check":
                if s["mode"] != "practice":
                    raise ValueError(
                        "La correction immédiate est réservée à l'entraînement."
                    )
                q = next(
                    (q for q in questions if q.identifiant == action.question), None
                )
                if q is None:
                    raise ValueError("Question inconnue.")
                if q.identifiant in s["grades"]:
                    return vue_publique(s)
                if not s["responses"].get(q.identifiant, {}).get("text", ""):
                    raise ValueError("Enregistre une réponse avant de la corriger.")
                note = await corriger(self.moteur, s, q)
                resultat = await asyncio.to_thread(
                    self.depot.noter, session_id, action.version, q.identifiant, note
                )
            else:
                notes = dict(s["grades"])
                for q in questions:
                    if q.identifiant not in notes:
                        notes[q.identifiant] = await corriger(self.moteur, s, q)
                resultat = await asyncio.to_thread(
                    self.depot.terminer, session_id, action.version, notes
                )
            return vue_publique(resultat)
