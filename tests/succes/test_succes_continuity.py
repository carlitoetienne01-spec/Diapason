from __future__ import annotations

from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.speech.realtime.tools import list_voice_tool_ids
from diapason.succes import store as magasin_taches
from diapason.succes.continuity import SuccesContinuityStore
from diapason.succes.routes import router, set_store_for_tests
from diapason.tools.succes_continuity import (
    SuccesContinuityTool,
    SuccesDeleteContinuityTool,
)


def store(tmp_path) -> SuccesContinuityStore:
    return SuccesContinuityStore(tmp_path / "succes.db")


#: Le jour où ce test se place. Tout ce qu'il coche est coché CE jour-là.
_LE_JOUR = date(2026, 8, 15)


class _HorlogeFigee(date):
    """Une horloge arrêtée au 15 août 2026."""

    @classmethod
    def today(cls) -> date:
        return _LE_JOUR


def _figer_le_temps(monkeypatch) -> None:
    """Arrêter les deux horloges du magasin, pas une seule.

    Ce test cochait une tâche puis demandait le bilan d'AOÛT. Il ne disait donc
    la vérité que pendant le mois d'août : vert d'octobre 2026 au 31 août 2026,
    rouge à minuit le 1er septembre, sans qu'une ligne de code ait changé.

    Il faut figer DEUX choses, et la seconde se laisse oublier :

      `date.today()`  — ce que `set_task_done` écrit dans `completedDate`.
      `now_ms()`      — ce qu'il écrit dans `updatedAtMs`, et c'est CELUI-LÀ
                        que le bilan annuel consulte pour compter une tâche
                        achevée (`continuity.year_review`). Figer le calendrier
                        sans figer l'horodatage laissait le test rouge, avec
                        une `completedDate` pourtant juste au 15 août.
    """
    midi = datetime(_LE_JOUR.year, _LE_JOUR.month, _LE_JOUR.day, 12, 0)
    monkeypatch.setattr(magasin_taches, "date", _HorlogeFigee)
    monkeypatch.setattr(magasin_taches, "now_ms", lambda: int(midi.timestamp() * 1000))


def test_weekly_materialization_is_deterministic_and_respects_tombstone(tmp_path):
    db = store(tmp_path)
    template = db.create_template(
        {
            "id": "sport",
            "title": "Faire du sport",
            "frequency": "weekly",
            "weeklyDays": [1, 3],
            "startDate": "2026-08-01",
            "endDate": "2026-08-31",
        }
    )

    first = db.materialize_templates("2026-08-03", "2026-08-09")
    second = db.materialize_templates("2026-08-03", "2026-08-09")

    assert first["count"] == 2
    assert second["count"] == 0
    assert {task["id"] for task in first["created"]} == {
        "tpl_sport_2026-08-03",
        "tpl_sport_2026-08-05",
    }
    db.delete_task("tpl_sport_2026-08-03")
    assert db.materialize_templates("2026-08-03", "2026-08-03")["count"] == 0
    assert template["id"] == "sport"


def test_monthly_last_weekday_and_update_propagation(tmp_path):
    db = store(tmp_path)
    item = db.create_template(
        {
            "id": "monthly",
            "title": "Ancien titre",
            "frequency": "monthly",
            "monthWeekSlots": ["last"],
            "monthWeekDow": 1,
            "startDate": "2026-08-01",
            "endDate": "2026-09-30",
        }
    )

    result = db.materialize_templates("2026-08-01", "2026-08-31")
    assert [task["date"] for task in result["created"]] == ["2026-08-31"]
    changed = db.update_template(item["id"], {"title": "Nouveau titre"})
    assert changed["title"] == "Nouveau titre"
    assert db.get_task("tpl_monthly_2026-08-31")["title"] == "Nouveau titre"


def test_habit_template_reconciles_and_cascades(tmp_path):
    db = store(tmp_path)
    item = db.create_template(
        {
            "id": "hydrate",
            "title": "Boire de l'eau",
            "templateKind": "habit",
            "frequency": "daily",
            "startDate": "2026-08-01",
            "endDate": "2026-12-31",
        }
    )

    habit = db.get_habit(item["linkedHabitId"], on_date="2026-08-15")
    assert habit["name"] == "Boire de l'eau"
    assert habit["due"] is True
    db.update_template("hydrate", {"title": "Boire 2 litres"})
    assert db.get_habit(item["linkedHabitId"])["name"] == "Boire 2 litres"

    result = db.delete_template("hydrate")
    assert result["tasksDeleted"] == 0
    assert db.list_habits(on_date="2026-08-15") == []


def test_quotes_are_stable_per_day_and_exported(tmp_path):
    db = store(tmp_path)
    first = db.create_quote({"id": "a", "text": "Avance", "author": "DIA"})
    db.create_quote({"id": "b", "text": "Respire"})

    assert db.quote_for_date("2026-08-15") == db.quote_for_date("2026-08-15")
    exported = db.export_state()
    assert exported["format"] == "diapason-succes-v3"
    assert {quote["id"] for quote in exported["state"]["quotes"]} == {"a", "b"}
    db.delete_quote(first["id"])
    assert [quote["id"] for quote in db.list_quotes()] == ["b"]


def test_dashboard_and_year_review_use_business_dates(tmp_path, monkeypatch):
    _figer_le_temps(monkeypatch)
    db = store(tmp_path)
    project = db.create_project(
        {"id": "project", "name": "Projet", "createdAt": "2026-08-01"}
    )
    task = db.create_task(
        {
            "id": "task",
            "title": "Livrer",
            "date": "2026-08-15",
            "createdAt": "2026-08-10",
            "projectId": project["id"],
        }
    )
    db.set_task_done(task["id"], True)
    habit = db.create_habit({"id": "habit", "name": "Lire", "startDate": "2026-08-01"})
    db.set_habit_done(habit["id"], "2026-08-15", True)

    dashboard = db.dashboard(on_date="2026-08-15")
    assert dashboard["tasks"]["todayTotal"] == 1
    assert dashboard["tasks"]["weekCompleted"] == 1
    assert dashboard["habits"]["completed"] == 1
    assert dashboard["projects"][0]["taskCompleted"] == 1

    review = db.year_review(2026, month=8)
    assert review["summary"]["tasksCreated"] == 1
    assert review["summary"]["tasksCompleted"] == 1
    assert review["summary"]["habitsCompleted"] == 1
    assert review["summary"]["projectsCreated"] == 1
    assert review["summary"]["projectsCompleted"] == 1


def test_legacy_templates_and_quotes_materialize(tmp_path):
    db = store(tmp_path)
    summary = db.import_legacy_snapshot(
        {
            "todos": [],
            "projects": [],
            "todoTemplates": [
                {
                    "id": "legacy-template",
                    "title": "Legacy",
                    "frequency": "daily",
                    "startDate": "2026-08-01",
                    "endDate": "2026-08-02",
                }
            ],
            "quotes": [{"id": "legacy-quote", "text": "Continue"}],
        }
    )

    assert summary["templatesImported"] == 1
    assert summary["quotesImported"] == 1
    assert db.get_template("legacy-template")["title"] == "Legacy"
    assert db.list_quotes()[0]["id"] == "legacy-quote"


def test_api_lifecycle_and_planner_materialization(tmp_path):
    db = store(tmp_path)
    app = FastAPI()
    app.include_router(router)
    set_store_for_tests(db)
    client = TestClient(app)
    try:
        created = client.post(
            "/v1/succes/templates",
            json={
                "title": "Tous les jours",
                "frequency": "daily",
                "startDate": "2026-08-01",
                "endDate": "2026-08-31",
            },
        )
        assert created.status_code == 201
        template_id = created.json()["template"]["id"]
        assert (
            client.get("/v1/succes/planner?date=2026-08-15").json()["summary"]["total"]
            == 1
        )
        assert client.get("/v1/succes/year-review?year=2026").status_code == 200
        assert client.get("/v1/succes/export").json()["format"] == "diapason-succes-v3"
        assert (
            client.request(
                "DELETE",
                f"/v1/succes/templates/{template_id}",
                json={"confirmed": False},
            ).status_code
            == 409
        )
        removed = client.request(
            "DELETE", f"/v1/succes/templates/{template_id}", json={"confirmed": True}
        )
        assert removed.status_code == 200
        assert removed.json()["tasksDeleted"] == 1
    finally:
        set_store_for_tests(None)


def test_dia_routine_and_sensitive_tools_are_separated(tmp_path):
    db = store(tmp_path)
    routine = SuccesContinuityTool(db)
    created = routine.execute(
        action="create_template",
        title="Rituel",
        frequency="daily",
        start_date="2026-08-15",
        end_date="2026-08-20",
    )
    assert created.success is True
    assert routine.spec.requires_confirmation is False
    assert "succes_continuity" in list_voice_tool_ids()

    sensitive = SuccesDeleteContinuityTool(db)
    assert sensitive.spec.requires_confirmation is True
    assert "succes_delete_continuity" not in list_voice_tool_ids()


def test_current_date_is_accepted_in_year_review(tmp_path):
    db = store(tmp_path)
    assert db.year_review(date.today().year)["year"] == date.today().year
