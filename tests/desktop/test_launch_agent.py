"""The LaunchAgent plist builder — the parts that must be exactly right."""

from __future__ import annotations

import plistlib

from openjarvis.desktop import launch_agent


def _plist(**kw):
    defaults = dict(
        python="/venv/bin/python",
        workdir="/proj",
        out_log="/logs/out.log",
        err_log="/logs/err.log",
    )
    defaults.update(kw)
    return plistlib.loads(launch_agent.build_plist(**defaults).encode())


def test_plist_is_valid_and_runs_dictate_via_module():
    d = _plist()
    assert d["Label"] == "com.openjarvis.dictate"
    # -m openjarvis.cli, not a console script that might not be on PATH.
    assert d["ProgramArguments"] == [
        "/venv/bin/python",
        "-m",
        "openjarvis.cli",
        "dictate",
    ]


def test_plist_runs_at_login_and_restarts_on_crash_only():
    d = _plist()
    assert d["RunAtLoad"] is True
    # KeepAlive restarts on CRASH only — a clean exit (waiting for a
    # permission grant) must NOT loop and re-prompt.
    assert d["KeepAlive"] == {"SuccessfulExit": False}
    assert d["ThrottleInterval"] >= 1


def test_plist_captures_logs():
    d = _plist(out_log="/x/out.log", err_log="/x/err.log")
    assert d["StandardOutPath"] == "/x/out.log"
    assert d["StandardErrorPath"] == "/x/err.log"


def test_plist_escapes_special_chars_in_paths():
    # A workdir with & or < must not corrupt the XML.
    d = _plist(workdir="/Users/a & b/<proj>")
    assert d["WorkingDirectory"] == "/Users/a & b/<proj>"


def test_label_and_paths_are_stable():
    assert launch_agent.LABEL == "com.openjarvis.dictate"
    assert launch_agent.plist_path().name == "com.openjarvis.dictate.plist"
    assert "LaunchAgents" in str(launch_agent.plist_path())
