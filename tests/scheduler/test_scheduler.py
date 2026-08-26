"""Tests for TaskScheduler — scheduling logic, lifecycle, and execution."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from diapason.scheduler.scheduler import ScheduledTask, TaskScheduler
from diapason.scheduler.store import SchedulerStore


@pytest.fixture()
def store(tmp_path):
    s = SchedulerStore(tmp_path / "scheduler_test.db")
    yield s
    s.close()


@pytest.fixture()
def scheduler(store):
    sched = TaskScheduler(store, poll_interval=1)
    yield sched
    sched.stop()


# -- ScheduledTask dataclass -------------------------------------------------


class TestScheduledTask:
    def test_round_trip(self):
        task = ScheduledTask(
            id="abc123",
            prompt="hello",
            schedule_type="interval",
            schedule_value="60",
            agent="orchestrator",
            tools="calculator,think",
            metadata={"key": "value"},
        )
        d = task.to_dict()
        restored = ScheduledTask.from_dict(d)
        assert restored.id == "abc123"
        assert restored.prompt == "hello"
        assert restored.schedule_type == "interval"
        assert restored.agent == "orchestrator"
        assert restored.tools == "calculator,think"
        assert restored.metadata == {"key": "value"}

    def test_defaults(self):
        task = ScheduledTask(
            id="x",
            prompt="p",
            schedule_type="once",
            schedule_value="2026-01-01T00:00:00",
        )
        assert task.context_mode == "isolated"
        assert task.status == "active"
        assert task.agent == "simple"
        assert task.tools == ""
        assert task.metadata == {}


# -- TaskScheduler create/list -----------------------------------------------


class TestCreateAndList:
    def test_create_task(self, scheduler):
        task = scheduler.create_task(
            prompt="hello world",
            schedule_type="interval",
            schedule_value="3600",
        )
        assert task.id
        assert task.prompt == "hello world"
        assert task.schedule_type == "interval"
        assert task.next_run is not None
        assert task.status == "active"

    def test_create_task_with_agent_and_tools(self, scheduler):
        task = scheduler.create_task(
            prompt="hello",
            schedule_type="once",
            schedule_value="2099-01-01T00:00:00+00:00",
            agent="orchestrator",
            tools="calculator,think",
        )
        assert task.agent == "orchestrator"
        assert task.tools == "calculator,think"

    def test_list_tasks_empty(self, scheduler):
        assert scheduler.list_tasks() == []

    def test_list_tasks(self, scheduler):
        scheduler.create_task("a", "interval", "60")
        scheduler.create_task("b", "interval", "120")
        assert len(scheduler.list_tasks()) == 2

    def test_list_tasks_filter_status(self, scheduler):
        t1 = scheduler.create_task("a", "interval", "60")
        scheduler.create_task("b", "interval", "120")
        scheduler.pause_task(t1.id)
        active = scheduler.list_tasks(status="active")
        paused = scheduler.list_tasks(status="paused")
        assert len(active) == 1
        assert len(paused) == 1


# -- Pause / resume / cancel -------------------------------------------------


class TestPauseResumeCancel:
    def test_pause_task(self, scheduler):
        task = scheduler.create_task("test", "interval", "60")
        scheduler.pause_task(task.id)
        tasks = scheduler.list_tasks(status="paused")
        assert len(tasks) == 1
        assert tasks[0].status == "paused"

    def test_resume_task(self, scheduler):
        task = scheduler.create_task("test", "interval", "60")
        scheduler.pause_task(task.id)
        scheduler.resume_task(task.id)
        tasks = scheduler.list_tasks(status="active")
        assert len(tasks) == 1

    def test_cancel_task(self, scheduler):
        task = scheduler.create_task("test", "interval", "60")
        scheduler.cancel_task(task.id)
        tasks = scheduler.list_tasks(status="cancelled")
        assert len(tasks) == 1
        assert tasks[0].next_run is None

    def test_pause_nonexistent(self, scheduler):
        with pytest.raises(KeyError):
            scheduler.pause_task("nonexistent")

    def test_resume_nonexistent(self, scheduler):
        with pytest.raises(KeyError):
            scheduler.resume_task("nonexistent")

    def test_cancel_nonexistent(self, scheduler):
        with pytest.raises(KeyError):
            scheduler.cancel_task("nonexistent")


# -- _compute_next_run -------------------------------------------------------


class TestComputeNextRun:
    def test_interval(self, scheduler):
        task = ScheduledTask(
            id="t", prompt="p", schedule_type="interval", schedule_value="300"
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run is not None
        # Should be roughly 300 seconds from now
        parsed = datetime.fromisoformat(next_run)
        diff = (parsed - datetime.now(timezone.utc)).total_seconds()
        assert 295 <= diff <= 310

    def test_once_not_yet_run(self, scheduler):
        target = "2099-06-15T12:00:00+00:00"
        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="once",
            schedule_value=target,
            last_run=None,
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run == target

    def test_once_already_run(self, scheduler):
        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="once",
            schedule_value="2099-06-15T12:00:00+00:00",
            last_run="2099-06-15T12:01:00+00:00",
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run is None

    def test_cron_fallback(self, scheduler):
        task = ScheduledTask(
            id="t",
            prompt="p",
            schedule_type="cron",
            schedule_value="30 2 * * *",
        )
        next_run = scheduler._compute_next_run(task)
        assert next_run is not None

    def test_unknown_type(self, scheduler):
        task = ScheduledTask(
            id="t", prompt="p", schedule_type="unknown", schedule_value="x"
        )
        assert scheduler._compute_next_run(task) is None


# -- _execute_task -----------------------------------------------------------


class TestExecuteTask:
    def test_execute_with_system(self, store):
        mock_system = MagicMock()
        mock_system.ask.return_value = "result text"
        sched = TaskScheduler(store, system=mock_system, poll_interval=1)

        task = sched.create_task("what is 2+2?", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        mock_system.ask.assert_called_once()
        call_args = mock_system.ask.call_args
        assert call_args[0][0] == "what is 2+2?"

        # Check that a run log was recorded
        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert logs[0]["result"] == "result text"

    def test_execute_without_system(self, store):
        sched = TaskScheduler(store, poll_interval=1)
        task = sched.create_task("dry run", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert "dry-run" in logs[0]["result"]

    def test_execute_with_error(self, store):
        mock_system = MagicMock()
        mock_system.ask.side_effect = RuntimeError("engine down")
        sched = TaskScheduler(store, system=mock_system, poll_interval=1)

        task = sched.create_task("fail", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 0
        assert "engine down" in logs[0]["error"]

    def test_execute_publishes_events(self, store):
        mock_bus = MagicMock()
        sched = TaskScheduler(store, bus=mock_bus, poll_interval=1)
        task = sched.create_task("test", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        assert mock_bus.publish.call_count == 2
        start_call = mock_bus.publish.call_args_list[0]
        end_call = mock_bus.publish.call_args_list[1]
        assert start_call[0][0] == "scheduler_task_start"
        assert end_call[0][0] == "scheduler_task_end"

    def test_execute_once_task_completed_after_run(self, store):
        sched = TaskScheduler(store, poll_interval=1)
        task = sched.create_task("one-shot", "once", "2026-01-01T00:00:00+00:00")
        sched._execute_task(task)

        updated = store.get_task(task.id)
        assert updated["status"] == "completed"
        assert updated["next_run"] is None

    def test_execute_with_tools(self, store):
        mock_system = MagicMock()
        mock_system.ask.return_value = "4"
        sched = TaskScheduler(store, system=mock_system, poll_interval=1)

        task = sched.create_task(
            "what is 2+2?",
            "once",
            "2026-01-01T00:00:00+00:00",
            tools="calculator,think",
        )
        sched._execute_task(task)

        call_kwargs = mock_system.ask.call_args[1]
        assert call_kwargs["tools"] == ["calculator", "think"]


# -- Start / stop lifecycle ---------------------------------------------------


class TestLifecycle:
    def test_start_stop(self, scheduler):
        scheduler.start()
        assert scheduler._thread is not None
        assert scheduler._thread.is_alive()
        scheduler.stop()
        assert not scheduler._thread

    def test_double_start(self, scheduler):
        scheduler.start()
        t1 = scheduler._thread
        scheduler.start()  # Should not create a second thread
        assert scheduler._thread is t1
        scheduler.stop()

    def test_poll_loop_finds_due_tasks(self, store):
        sched = TaskScheduler(store, poll_interval=1)
        # Create a task that is already due
        task = sched.create_task("immediate", "once", "2020-01-01T00:00:00+00:00")
        # Manually set next_run to the past
        d = store.get_task(task.id)
        d["next_run"] = "2020-01-01T00:00:00+00:00"
        store.update_task(d)

        sched.start()
        # Give the poll loop time to execute
        time.sleep(2.5)
        sched.stop()

        logs = store.get_run_logs(task.id)
        assert len(logs) >= 1


class TestADeniedTickIsNotASuccess:
    """A tick that was allowed to do nothing must not log a green "yes".

    A denied capability does not raise. `ToolExecutor` turns it into a tool
    result reading "Capability 'x' denied", the agent reads that like any
    other output and carries on to a fluent answer, and `success = True` was
    set on the sole ground that `ask` returned. So an operator forbidden from
    using any of its tools reported success every five minutes, forever — a
    false SUCCESS (§100) in the one place nobody watches.
    """

    def _bus(self):
        from diapason.core.events import EventBus

        return EventBus()

    def _deny(self, bus, *, agent="operative", tool="web_search", cap="network:fetch"):
        from diapason.core.events import EventType

        bus.publish(
            EventType.CAPABILITY_DENIED,
            {"agent_id": agent, "capability": cap, "tool": tool},
        )

    def test_a_tick_whose_tool_was_denied_is_logged_as_a_failure(self, store):
        bus = self._bus()
        system = MagicMock()
        system.ask.side_effect = lambda *a, **k: (
            self._deny(bus) or "I could not search, but here is a summary."
        )
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        task = sched.create_task(
            "tick", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )

        sched._execute_task(task)

        logs = store.get_run_logs(task.id)
        assert logs[0]["success"] == 0, (
            "un tic dont l'outil a été refusé n'a pas fait ce qu'on lui demandait"
        )

    def test_the_refusal_says_which_tool_and_which_capability(self, store):
        bus = self._bus()
        system = MagicMock()
        system.ask.side_effect = lambda *a, **k: self._deny(bus) or "fine"
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        task = sched.create_task(
            "tick", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )

        sched._execute_task(task)

        erreur = store.get_run_logs(task.id)[0]["error"]
        assert "web_search" in erreur
        assert "network:fetch" in erreur

    def test_the_answer_is_kept_even_when_the_tick_is_marked_failed(self, store):
        """The result is not the culprit; losing it would help nobody."""
        bus = self._bus()
        system = MagicMock()
        system.ask.side_effect = lambda *a, **k: self._deny(bus) or "partial answer"
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        task = sched.create_task(
            "tick", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )

        sched._execute_task(task)

        assert store.get_run_logs(task.id)[0]["result"] == "partial answer"

    def test_a_refusal_from_another_agent_is_not_this_tick_s(self, store):
        """The bus is shared. A chat turn refused mid-tick is not our fault."""
        bus = self._bus()
        system = MagicMock()
        system.ask.side_effect = lambda *a, **k: (
            self._deny(bus, agent="simple") or "all good"
        )
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        task = sched.create_task(
            "tick", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )

        sched._execute_task(task)

        assert store.get_run_logs(task.id)[0]["success"] == 1

    def test_a_crash_keeps_its_own_reason(self, store):
        """A denial must not overwrite the headline of a real failure."""
        bus = self._bus()
        system = MagicMock()

        def _boom(*a, **k):
            self._deny(bus)
            raise RuntimeError("engine down")

        system.ask.side_effect = _boom
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        task = sched.create_task(
            "tick", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )

        sched._execute_task(task)

        erreur = store.get_run_logs(task.id)[0]["error"]
        assert "engine down" in erreur

    def test_the_listener_does_not_outlive_the_tick(self, store):
        """Otherwise every later tick inherits every earlier refusal."""
        bus = self._bus()
        system = MagicMock()
        system.ask.side_effect = lambda *a, **k: self._deny(bus) or "ok"
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        premier = sched.create_task(
            "un", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )
        sched._execute_task(premier)

        system.ask.side_effect = lambda *a, **k: "rien de refusé cette fois"
        second = sched.create_task(
            "deux", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )
        sched._execute_task(second)

        assert store.get_run_logs(second.id)[0]["success"] == 1

    def test_a_clean_tick_is_still_a_success(self, store):
        bus = self._bus()
        system = MagicMock()
        system.ask.return_value = "done"
        sched = TaskScheduler(store, system=system, poll_interval=1, bus=bus)
        task = sched.create_task(
            "tick", "once", "2026-01-01T00:00:00+00:00", agent="operative"
        )

        sched._execute_task(task)

        assert store.get_run_logs(task.id)[0]["success"] == 1
