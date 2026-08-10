"""The .app bundle — the keys without which macOS cannot grant permissions."""

from __future__ import annotations

import os
import plistlib

from openjarvis.desktop import app_bundle


def test_info_plist_declares_microphone_usage():
    """Without this key macOS cannot grant Microphone AT ALL.

    A bare interpreter under launchd has no Info.plist, so the request can
    never be made and the app is handed silence forever — the exact
    "[no audio captured]" loop that motivated the bundle.
    """
    info = app_bundle.build_info_plist()
    assert info["NSMicrophoneUsageDescription"]
    assert "dictation key" in info["NSMicrophoneUsageDescription"]


def test_info_plist_is_an_agent_not_a_windowed_app():
    info = app_bundle.build_info_plist()
    assert info["LSUIElement"] is True  # no Dock icon, no window


def test_info_plist_has_a_stable_identity():
    info = app_bundle.build_info_plist()
    assert info["CFBundleIdentifier"] == "com.openjarvis.dictation"
    assert info["CFBundleExecutable"] == app_bundle.EXECUTABLE_NAME
    assert info["CFBundleName"] == "OpenJarvis Dictation"


def test_launcher_execs_so_launchd_tracks_the_python_process():
    """`exec` matters: launchd watches the process it spawned."""
    script = app_bundle.build_launcher_script("/venv/bin/python", "/proj")
    assert script.startswith("#!/bin/sh")
    assert 'exec "/venv/bin/python" -m openjarvis.cli dictate' in script


def test_launcher_never_cds_into_a_tcc_protected_project_dir():
    """A `cd` into ~/Downloads fails for the app and breaks every later call.

    The symptom is `getcwd: Operation not permitted` on stderr. The working
    directory is irrelevant to dictation, so it runs from $HOME.
    """
    script = app_bundle.build_launcher_script(
        "/venv/bin/python", "/Users/x/Downloads/p"
    )
    assert "/Users/x/Downloads/p" not in script
    assert 'cd "$HOME"' in script


def test_build_creates_a_runnable_bundle(tmp_path):
    dest = tmp_path / "Test.app"
    bundle = app_bundle.build(dest, python="/venv/bin/python", workdir="/proj")

    exe = app_bundle.executable_path(bundle)
    assert exe.is_file()
    assert os.access(exe, os.X_OK), "launcher must be executable"

    with open(bundle / "Contents" / "Info.plist", "rb") as fh:
        info = plistlib.load(fh)
    assert info["CFBundleIdentifier"] == "com.openjarvis.dictation"
    assert app_bundle.is_installed(bundle) is True


def test_rebuild_replaces_cleanly(tmp_path):
    dest = tmp_path / "Test.app"
    app_bundle.build(dest, python="/a/python", workdir="/one")
    app_bundle.build(dest, python="/b/python", workdir="/two")
    script = app_bundle.executable_path(dest).read_text()
    assert "/b/python" in script
    assert "/a/python" not in script


def test_is_installed_false_when_absent(tmp_path):
    assert app_bundle.is_installed(tmp_path / "Nope.app") is False
