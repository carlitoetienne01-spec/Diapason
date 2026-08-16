"""The remote-command tool must stay out of the live voice path — for now.

Not a style rule. ``execute_voice_tool`` runs its allow-list directly rather
than through ``ToolExecutor``, which is where the approval system lives. Any
tool on that list therefore runs with no confirmation, whatever risk it
declares. ``mesh_send`` is an outward action — it changes what appears on a
screen the user may not be near — so it must not be reachable that way until
the voice path goes through the executor like everything else.

This test is the tripwire. When the voice path is fixed, delete it in the
same commit that fixes it, so the two facts stay in sync.
"""

from __future__ import annotations

from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS


def test_mesh_send_is_not_reachable_from_the_voice_path():
    assert "mesh_send" not in DEFAULT_VOICE_TOOL_IDS, (
        "mesh_send est une action sortante et le chemin vocal contourne "
        "ToolExecutor, donc les approbations. Faites d'abord passer la voix "
        "par l'exécuteur ; ce test disparaîtra dans le même commit."
    )


def test_the_read_only_mesh_tool_is_also_absent_while_send_is():
    """No point exposing the lookup alone: it exists to feed mesh_send."""
    if "mesh_send" not in DEFAULT_VOICE_TOOL_IDS:
        assert "mesh_devices" not in DEFAULT_VOICE_TOOL_IDS
