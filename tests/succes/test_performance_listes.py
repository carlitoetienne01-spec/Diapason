"""§5/§100 : alléger les listes sans perdre arbres, classement ou document."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI

from diapason.succes import routes
from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.notes_resume import resumer_note


@pytest.fixture
def db(tmp_path):
    return SuccesContinuityStore(tmp_path / "succes.db")


class TestListesGroupees:
    def test_deux_lectures_gardent_les_memes_taches_et_sous_taches(
        self, db, monkeypatch
    ):
        for i in range(24):
            task = db.create_task(
                {
                    "title": f"Tâche {i}",
                    "date": "2026-09-19",
                    "priority": "high" if i % 2 else "low",
                    "notes": "Consigne",
                    "journal": "Carnet",
                }
            )
            db.add_subtask(task["id"], "Sous-tâche")
        original = db._connect
        requetes = []

        @contextmanager
        def mesurer():
            with original() as conn:
                conn.set_trace_callback(requetes.append)
                yield conn

        monkeypatch.setattr(db, "_connect", mesurer)
        liste = db.list_tasks()
        lectures = [q for q in requetes if q.lstrip().upper().startswith("SELECT")]
        assert len(lectures) == 2, (
            "le nombre de lectures ne dépend plus du nombre de tâches"
        )
        assert liste == [db.get_task(t["id"]) for t in liste], (
            "contenus et arbres complets conservés"
        )
        assert db.list_tasks(search="absente") == []
        assert db.list_tasks(scheduled_date="2026-09-20") == []
        db.set_task_done(liste[0]["id"], True)
        assert len(db.list_tasks(include_done=False)) == 23
        db.delete_task(liste[1]["id"])
        assert len(db.list_tasks()) == 23


class TestResumesNotes:
    def test_relecture_sans_calcul_mais_frappe_et_format_jamais_perimes(
        self, monkeypatch
    ):
        """§5 : la date ne suffit pas à détecter une modification du document."""
        from collections import OrderedDict
        from unittest.mock import Mock

        from diapason.succes import notes_resume

        monkeypatch.setattr(notes_resume, "_cache_pages", OrderedDict())
        calcul = Mock(wraps=notes_resume._calculer_pages)
        monkeypatch.setattr(notes_resume, "_calculer_pages", calcul)
        note = {"id": "a", "updatedAtMs": 1, "content": "x" * 2000, "pageFormat": "a4"}
        assert resumer_note(note)["pageCountEstimate"] == 1
        assert resumer_note(note | {"title": "Renommée"})["title"] == "Renommée"
        assert calcul.call_count == 1, "renommer ne reparcourt pas le contenu"
        assert resumer_note(note | {"pageFormat": "a5"})["pageCountEstimate"] == 2
        assert resumer_note(note | {"content": "x" * 3000})["pageCountEstimate"] == 2
        assert calcul.call_count == 3, "le contenu et le format invalident le calcul"

    def test_le_resume_preserve_les_metadonnees_sans_html(self, db):
        note = db.create_note(
            {
                "title": "Verbes",
                "content": "<p>"
                + "mot " * 1000
                + '</p><hr class="succes-page-break"><p>Suite</p>',
                "category": "Études",
            }
        )
        resume = resumer_note(note)
        assert "content" not in resume, "un cartable n'embarque jamais tout le document"
        assert resume["pageCountEstimate"] == 3
        assert {k: v for k, v in resume.items() if k != "pageCountEstimate"} == {
            k: v for k, v in note.items() if k != "content"
        }
        assert db.get_note(note["id"])["content"] == note["content"], (
            "la lecture ne réécrit rien"
        )

    def test_emojis_entites_et_sauts_ne_dependent_pas_du_navigateur(self):
        assert (
            resumer_note({"content": "<p>" + "😀" * 1401 + "</p>", "pageFormat": "a4"})[
                "pageCountEstimate"
            ]
            == 2
        )
        assert (
            resumer_note(
                {"content": '<p>&amp; &lt; &#xE9;</p><hr class="succes-page-break">'}
            )["pageCountEstimate"]
            == 2
        )
        assert resumer_note({"content": ""})["pageCountEstimate"] == 1

    def test_routes_resume_detail_et_compatibilite(self, db, monkeypatch):
        monkeypatch.setattr(routes, "_store", db)
        note = db.create_note({"title": "A", "content": "Texte caché recherché"})
        app = FastAPI()
        app.include_router(routes.router)

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                legacy = await client.get("/v1/succes/notes")
                resume = await client.get(
                    "/v1/succes/notes/resumes", params={"search": "recherché"}
                )
                detail = await client.get("/v1/succes/notes/" + note["id"])
                absent = await client.get("/v1/succes/notes/inconnue")
                assert legacy.json()["notes"][0]["content"] == note["content"]
                assert resume.json()["notes"][0]["id"] == note["id"], (
                    "la recherche couvre encore le contenu"
                )
                assert "content" not in resume.json()["notes"][0]
                assert detail.json()["note"] == note
                assert absent.status_code == 404

        asyncio.run(scenario())


class TestReactiviteServeur:
    def test_une_lecture_lente_ne_bloque_pas_la_boucle_du_chat(self, db, monkeypatch):
        monkeypatch.setattr(routes, "_store", db)
        entree = threading.Event()

        def lente(**kwargs):
            entree.set()
            time.sleep(0.3)
            return []

        monkeypatch.setattr(db, "list_tasks", lente)
        app = FastAPI()
        app.include_router(routes.router)

        @app.get("/ping")
        async def ping():
            return {"ok": True}

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                lecture = asyncio.create_task(client.get("/v1/succes/tasks"))
                await asyncio.to_thread(entree.wait, 2)
                avant = time.perf_counter()
                reponse = await client.get("/ping")
                assert reponse.status_code == 200
                assert not lecture.done(), (
                    "le ping passe pendant le blocage SQLite, pas après"
                )
                assert time.perf_counter() - avant < 0.2
                await lecture

        asyncio.run(scenario())
