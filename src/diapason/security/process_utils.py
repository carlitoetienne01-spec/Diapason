"""Subprocess helpers with hard timeout and process-tree cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate *process* and its descendants as reliably as the OS allows."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.kill()


def run_with_timeout(
    args: str | Sequence[str],
    *,
    timeout: float,
    shell: bool = False,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and kill its process group if the deadline expires.

    ``subprocess.run(timeout=...)`` kills only the immediate child.  Starting a
    new session on POSIX lets Diapason terminate the whole process group, so a
    timed-out shell command cannot leave grandchildren running in background.
    """
    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "shell": shell,
        "stderr": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "text": True,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(args, **popen_kwargs)  # noqa: S603
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            process.args,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc

    return subprocess.CompletedProcess(
        process.args,
        process.returncode,
        stdout,
        stderr,
    )


__all__ = ["run_with_timeout"]
