"""The remote-command tool stays out of the live voice path — and why.

**The reason this file used to give is no longer true, and that mattered.**
It said ``execute_voice_tool`` ran its allow-list directly rather than through
``ToolExecutor``, so any tool on that list ran with no confirmation whatever
risk it declared. That was correct when the file was written on 16 August
2026, and it stopped being correct on 22 August, when the voice path was
routed through ``ToolExecutor(interactive=True, confirm_callback=...)``. The
file itself said "when the voice path is fixed, delete it in the same commit
that fixes it, so the two facts stay in sync". The fix landed; the deletion
did not. A green test whose stated reason has evaporated is worse than no
test: it reports a guarantee nobody is providing any more.

So the restriction is kept, and re-justified for the reason that actually
holds today: **``mesh_send`` takes an open enumeration of actions and a spoken
device name.** A transcription is a lossy channel — "sur l'iPad" heard as
"sur le PC" sends a document to a screen the user is not near, and the code
itself calls that the worst failure this feature can produce. The approval
bell now covers the *risk*; it does not cover the *ambiguity*, and no
confirmation dialog can un-hear a wrong word.

``handoff_continue`` is absent from the voice list too, but by omission — no
test held it there. It is a narrower tool (one referent, taken from the
screen, no action to choose) so the argument above does not reach it; it is
listed here so its absence is a decision the next reader can find, rather
than an accident they must reconstruct.
"""

from __future__ import annotations

from diapason.server.voice_live_routes import outils_demandes_par_le_client
from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS


def test_mesh_send_is_not_reachable_from_the_voice_path():
    assert "mesh_send" not in DEFAULT_VOICE_TOOL_IDS, (
        "mesh_send choisit une action dans une énumération ouverte et un "
        "appareil d'après une phrase transcrite. La cloche d'approbation "
        "couvre le risque, pas l'ambiguïté : aucune confirmation ne dé-entend "
        "un mot mal transcrit."
    )


def test_the_read_only_mesh_tool_is_also_absent_while_send_is():
    """No point exposing the lookup alone: it exists to feed mesh_send."""
    if "mesh_send" not in DEFAULT_VOICE_TOOL_IDS:
        assert "mesh_devices" not in DEFAULT_VOICE_TOOL_IDS


class TestTheAllowListIsACeilingNotADefault:
    """A restriction a client can lift by naming the tool is decorative.

    ``list_voice_tool_ids`` checked a client-supplied list against the GLOBAL
    tool registry and nothing else, so a WebSocket ``start`` frame carrying
    ``tools: "mesh_send"`` got ``mesh_send`` — the very tool the test above
    claims to keep out. Not a privilege escalation: the socket sits behind the
    API key and the same tool is one HTTP call away on the chat path. A scope
    decision that did not apply, while a test said it did.
    """

    def test_a_client_cannot_ask_for_a_tool_the_voice_path_excludes(self):
        assert outils_demandes_par_le_client("mesh_send") is None, (
            "nommer l'outil suffisait à l'obtenir"
        )

    def test_a_client_keeps_the_tools_it_is_allowed_to_ask_for(self):
        permis = DEFAULT_VOICE_TOOL_IDS[0]
        assert outils_demandes_par_le_client(permis) == [permis]

    def test_a_mixed_request_keeps_only_what_is_permitted(self):
        permis = DEFAULT_VOICE_TOOL_IDS[0]
        assert outils_demandes_par_le_client(f"mesh_send,{permis}") == [permis]

    def test_asking_for_nothing_valid_falls_back_to_the_default_list(self):
        """None means "no restriction requested", the same as an empty frame.

        Refusing every tool to whoever asked badly would be a punishment, not
        a guard — and the default list is the safe one by construction.
        """
        assert outils_demandes_par_le_client("mesh_send,mesh_devices") is None
        assert outils_demandes_par_le_client("") is None
