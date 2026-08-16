"""What « sur mon PC » must mean, and when it must mean nothing.

The tests that matter here are the refusals. A resolver that always answers
is a resolver that will one day open a private note on the wrong screen, so
half of this file exists to prove it keeps quiet when it should.
"""

from __future__ import annotations

import time

import pytest

from diapason.mesh.resolver import describe_devices, resolve_device


def device(
    device_id: str,
    name: str,
    *,
    kind: str = "DESKTOP",
    platform: str = "WINDOWS",
    trust: str = "TRUSTED",
    seen_s_ago: float = 1.0,
    capabilities: tuple[str, ...] = ("app.navigate",),
) -> dict:
    return {
        "deviceId": device_id,
        "name": name,
        "deviceType": kind,
        "platform": platform,
        "trustLevel": trust,
        "lastSeenAtMs": int((time.time() - seen_s_ago) * 1000),
        "capabilities": list(capabilities),
    }


MAC = device("d1", "MacBook de Carlito", kind="LAPTOP", platform="MACOS")
PC = device("d2", "PC du bureau", kind="DESKTOP", platform="WINDOWS")
PHONE = device("d3", "iPhone de Carlito", kind="PHONE", platform="IOS")
TABLET = device("d4", "iPad", kind="TABLET", platform="IPADOS")


class TestNaming:
    def test_the_exact_name_wins(self):
        out = resolve_device("sur PC du bureau", [MAC, PC, PHONE])
        assert out["status"] == "RESOLVED"
        assert out["device"]["deviceId"] == "d2"

    def test_accents_and_case_do_not_matter(self):
        out = resolve_device("SUR MON TÉLÉPHONE", [MAC, PC, PHONE])
        assert out["status"] == "RESOLVED"
        assert out["device"]["deviceId"] == "d3"

    def test_a_kind_word_finds_the_right_kind(self):
        assert (
            resolve_device("ma tablette", [MAC, PC, TABLET])["device"]["deviceId"]
            == "d4"
        )

    def test_a_platform_word_finds_the_right_platform(self):
        assert (
            resolve_device("sur mon mac", [MAC, PC, PHONE])["device"]["deviceId"]
            == "d1"
        )

    def test_a_partial_name_is_enough_when_it_is_unique(self):
        out = resolve_device("ouvre ça sur le macbook", [MAC, PC])
        assert out["device"]["deviceId"] == "d1"


class TestRefusals:
    """The half of the resolver that protects the user from a confident guess."""

    def test_two_equally_good_matches_ask_instead_of_choosing(self):
        second_phone = device("d5", "iPhone du travail", kind="PHONE", platform="IOS")
        out = resolve_device("sur mon iphone", [PHONE, second_phone])
        assert out["status"] == "AMBIGUOUS"
        assert {c["deviceId"] for c in out["candidates"]} == {"d3", "d5"}
        assert "Lequel" in out["message"]

    def test_an_unmatched_phrase_lists_what_exists(self):
        out = resolve_device("sur la console de salon", [MAC, PC])
        assert out["status"] == "UNKNOWN"
        assert out["device"] is None
        assert len(out["candidates"]) == 2

    def test_this_device_is_never_routed_remotely(self):
        out = resolve_device("ouvre ça ici", [MAC, PC])
        assert out["status"] == "LOCAL"
        assert out["device"] is None

    def test_an_empty_phrase_with_several_devices_is_not_a_guess(self):
        out = resolve_device("", [MAC, PC, PHONE])
        assert out["status"] == "UNKNOWN"

    def test_revoked_devices_are_not_candidates(self):
        stolen = device("d9", "PC du bureau", trust="REVOKED")
        out = resolve_device("sur le PC du bureau", [stolen])
        assert out["status"] == "UNKNOWN"
        assert out["candidates"] == []

    def test_this_machine_is_never_its_own_target(self):
        out = resolve_device("sur mon mac", [MAC, PC], local_device_id="d1")
        # The only Mac in the fleet is this one, so nothing remote matches.
        assert out["status"] == "UNKNOWN"

    def test_an_empty_fleet_says_so_plainly(self):
        out = resolve_device("sur mon PC", [])
        assert out["status"] == "UNKNOWN"
        assert "appairé" in out["message"]


class TestSensibleDefaults:
    def test_one_device_and_no_phrase_needs_no_question(self):
        out = resolve_device("", [PC])
        assert out["status"] == "RESOLVED"
        assert out["device"]["deviceId"] == "d2"

    def test_the_other_device_works_when_there_is_exactly_one(self):
        assert resolve_device("sur l'autre appareil", [PC])["status"] == "RESOLVED"

    def test_the_other_device_is_ambiguous_when_there_are_two(self):
        assert resolve_device("sur l'autre appareil", [PC, MAC])["status"] == "UNKNOWN"

    def test_being_awake_breaks_a_tie(self):
        awake = device("d6", "iPhone perso", kind="PHONE", platform="IOS", seen_s_ago=2)
        asleep = device(
            "d7", "iPhone pro", kind="PHONE", platform="IOS", seen_s_ago=99_999
        )
        out = resolve_device("mon iphone", [awake, asleep])
        assert out["status"] == "RESOLVED"
        assert out["device"]["deviceId"] == "d6"

    def test_two_sleeping_devices_still_ask(self):
        a = device(
            "d6", "iPhone perso", kind="PHONE", platform="IOS", seen_s_ago=99_999
        )
        b = device("d7", "iPhone pro", kind="PHONE", platform="IOS", seen_s_ago=99_999)
        assert resolve_device("mon iphone", [a, b])["status"] == "AMBIGUOUS"


class TestWhatTheAssistantSees:
    def test_the_description_carries_no_key_and_no_address(self):
        full = {**PC, "publicKey": "SECRET", "address": "http://192.168.1.20:8000"}
        described = describe_devices([full])[0]
        assert set(described) == {
            "deviceId",
            "name",
            "deviceType",
            "platform",
            "presence",
            "reachable",
            "capabilities",
        }
        assert "SECRET" not in repr(described)

    def test_presence_is_included_because_it_changes_the_answer(self):
        described = describe_devices([PC])[0]
        assert described["presence"] == "ONLINE"
        assert described["reachable"] is True


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("sur mon pc", "d2"),
        ("sur mon ordinateur de bureau", "d2"),
        ("sur mon portable", "d1"),
        ("sur ma tablette", "d4"),
        ("sur mon ipad", "d4"),
    ],
)
def test_the_phrases_a_person_actually_says(phrase, expected):
    out = resolve_device(phrase, [MAC, PC, TABLET])
    assert out["status"] == "RESOLVED", out["message"]
    assert out["device"]["deviceId"] == expected
