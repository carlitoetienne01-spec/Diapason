"""Tests for heartbeat queue + routines."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openjarvis.heartbeat.markdown import (
    append_task,
    clear_done,
    mark_done,
    parse_heartbeat,
    pending_now,
    read_heartbeat,
)
from openjarvis.heartbeat.quiet import in_quiet_hours
from openjarvis.heartbeat.runner import run_heartbeat_tick
from openjarvis.heartbeat.routines import (
    Routine,
    ensure_routines_file,
    get_routine,
    load_routines,
    set_routine_enabled,
)
from openjarvis.heartbeat.kinds import run_routine
from openjarvis.heartbeat.sync import HEARTBEAT_TASK_ID, sync_heartbeat_and_routines


SAMPLE = """# HEARTBEAT

## Now
- [ ] Check calendar before 11
- [x] Already done
- [ ] Ping unread mail

## Watching
- [ ] Watch drafts folder
"""


def test_parse_heartbeat():
    now, watching = parse_heartbeat(SAMPLE)
    assert len(now) == 3
    assert now[0].text == "Check calendar before 11"
    assert now[0].done is False
    assert now[1].done is True
    assert len(watching) == 1


def test_pending_mark_append(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "HEARTBEAT.md").write_text(SAMPLE, encoding="utf-8")
    pending = pending_now(ws)
    assert len(pending) == 2
    mark_done(pending[0], ws)
    pending2 = pending_now(ws)
    assert len(pending2) == 1
    assert pending2[0].text == "Ping unread mail"
    append_task("New task", ws)
    assert any(t.text == "New task" for t in pending_now(ws))


def test_clear_done(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "HEARTBEAT.md").write_text(SAMPLE, encoding="utf-8")
    n = clear_done(ws)
    assert n == 1
    now, _ = read_heartbeat(ws)
    assert all(not t.done for t in now)


def test_quiet_hours_overnight():
    noon = datetime(2026, 8, 9, 12, 0)
    night = datetime(2026, 8, 9, 23, 0)
    morning = datetime(2026, 8, 9, 6, 0)
    assert in_quiet_hours(enabled=True, start="22:00", end="07:00", now=noon) is False
    assert in_quiet_hours(enabled=True, start="22:00", end="07:00", now=night) is True
    assert in_quiet_hours(enabled=True, start="22:00", end="07:00", now=morning) is True
    assert in_quiet_hours(enabled=False, start="22:00", end="07:00", now=night) is False


def test_tick_empty_and_drain(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "HEARTBEAT.md").write_text(
        "# HEARTBEAT\n\n## Now\n\n## Watching\n", encoding="utf-8"
    )
    out = run_heartbeat_tick(system=None, force=True, workspace=str(ws))
    assert out["skipped"] is True
    assert out["reason"] == "empty"

    append_task("Say hello locally", ws)
    out2 = run_heartbeat_tick(system=None, force=True, workspace=str(ws))
    assert out2["ok"] is True
    assert out2["skipped"] is False
    assert "Say hello" in out2["task"]
    assert pending_now(ws) == []


def test_routines_seed_and_enable(tmp_path: Path):
    ws = tmp_path / "ws"
    ensure_routines_file(ws)
    items = load_routines(ws)
    assert any(r.id == "morning-digest" for r in items)
    set_routine_enabled("idle-check", True, ws)
    assert get_routine("idle-check", ws).enabled is True


def test_run_reminder_routine(tmp_path: Path):
    r = Routine(
        id="nudge",
        kind="reminder",
        enabled=True,
        payload={"message": "Drink water"},
    )
    out = run_routine(r, system=None, force=True, workspace=str(tmp_path))
    assert out["ok"] is True
    assert "Drink water" in out["content"]


def test_run_prompt_silent(tmp_path: Path):
    r = Routine(
        id="cal",
        kind="prompt",
        enabled=True,
        payload={"prompt": "If none reply exactly: SILENT."},
    )
    out = run_routine(r, system=None, force=True, workspace=str(tmp_path))
    assert out["skipped"] is True
    assert out["reason"] == "silent"


def test_sync_creates_tasks(tmp_path: Path):
    from openjarvis.core.config import HeartbeatConfig, RoutinesConfig, JarvisConfig
    from openjarvis.scheduler.scheduler import TaskScheduler
    from openjarvis.scheduler.store import SchedulerStore

    ws = tmp_path / "ws"
    db = tmp_path / "sched.db"
    store = SchedulerStore(db)
    sched = TaskScheduler(store)
    cfg = JarvisConfig(
        heartbeat=HeartbeatConfig(enabled=True, interval_seconds=1800, workspace_dir=str(ws)),
        routines=RoutinesConfig(enabled=True),
    )
    summary = sync_heartbeat_and_routines(sched, cfg, workspace=str(ws))
    assert summary["heartbeat"] == HEARTBEAT_TASK_ID
    ids = {t.id for t in sched.list_tasks()}
    assert HEARTBEAT_TASK_ID in ids
    assert "routine:morning-digest" in ids
    store.close()
