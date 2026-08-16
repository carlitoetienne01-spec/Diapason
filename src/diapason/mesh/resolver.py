"""Turning « sur mon PC » into a device id — or refusing to guess.

Spec §22. The assistant hears a phrase, not an identifier. This module is
the only place allowed to bridge the two, and its governing rule is that a
wrong guess is worse than a question: opening a screen on the wrong machine
is confusing, and sending a notification to the wrong one is a small
betrayal of trust. So when two devices match equally well, this returns an
AMBIGUOUS answer with the candidates rather than picking the first.

The one place it does decide on its own: a single obvious match, or a tie
broken by reachability — because "the phone that is on" is what a person
means by "my phone" when only one is awake.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence

from diapason.mesh.presence import is_reachable, presence_of

__all__ = ["resolve_device", "describe_devices"]

# Words a person uses for a kind of machine, mapped to what the registry
# stores. Deliberately not exhaustive-by-cleverness: each entry is one the
# user actually says out loud in French or English.
_TYPE_WORDS: dict[str, tuple[str, ...]] = {
    "PHONE": (
        "telephone",
        "tel",
        "phone",
        "portable",
        "mobile",
        "cellulaire",
        "iphone",
        "android",
        "smartphone",
    ),
    "TABLET": ("tablette", "tablet", "ipad"),
    "LAPTOP": ("laptop", "portable", "macbook", "notebook"),
    "DESKTOP": ("bureau", "desktop", "fixe", "tour", "pc", "ordinateur", "imac"),
    "BROWSER": ("navigateur", "browser", "onglet", "web"),
}

_PLATFORM_WORDS: dict[str, tuple[str, ...]] = {
    "MACOS": ("mac", "macos", "macbook", "imac"),
    "WINDOWS": ("windows", "pc", "win"),
    "LINUX": ("linux", "ubuntu", "debian", "fedora"),
    "IOS": ("iphone", "ios", "ipad", "ipados"),
    "IPADOS": ("ipad", "ipados"),
    "ANDROID": ("android",),
    "WEB": ("navigateur", "browser", "web"),
}

# Phrases meaning "not here, the other one" — only usable when exactly one
# other device exists, otherwise they are as ambiguous as saying nothing.
_OTHER_WORDS = (
    "autre appareil",
    "autre machine",
    "l autre",
    "other device",
    "autre",
)

# Phrases meaning "this machine", which the mesh must never route remotely.
_HERE_WORDS = (
    "ici",
    "cet appareil",
    "cette machine",
    "sur place",
    "here",
    "this device",
    "local",
    "en local",
)


def _fold(text: str) -> str:
    """Lowercase, strip accents and punctuation — « télé » and « tele » match."""
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(c for c in raw if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def _name_score(phrase: str, device: Mapping[str, Any]) -> int:
    """How strongly the words in *phrase* point at this device's name.

    Exact name match beats a shared word, which beats nothing. Names are
    user-chosen, so they are the strongest signal available.
    """
    name = _fold(device.get("name"))
    if not name:
        return 0
    if name and name == phrase:
        return 100
    if name and name in phrase:
        return 80
    name_words = {w for w in name.split() if len(w) > 2}
    phrase_words = {w for w in phrase.split() if len(w) > 2}
    shared = name_words & phrase_words
    return 40 + len(shared) if shared else 0


def _kind_score(phrase: str, device: Mapping[str, Any]) -> int:
    """Points for « mon téléphone » matching a PHONE, « mon Mac » a MACOS."""
    words = set(phrase.split())
    score = 0
    for word in _TYPE_WORDS.get(str(device.get("deviceType") or "").upper(), ()):
        if word in words:
            score = max(score, 30)
    platform = str(device.get("platform") or "").upper()
    for word in _PLATFORM_WORDS.get(platform, ()):
        if word in words:
            score = max(score, 30)
    return score


def resolve_device(
    phrase: str,
    devices: Sequence[Mapping[str, Any]],
    *,
    local_device_id: str = "",
) -> dict[str, Any]:
    """Read *phrase* against the fleet and say who is meant — or that it is unclear.

    Returns one of four outcomes, each with a French sentence the assistant
    can say verbatim:

    ``LOCAL``      the user means this machine; do not route anything.
    ``RESOLVED``   one device, with ``device``.
    ``AMBIGUOUS``  several plausible, with ``candidates`` — ask, do not pick.
    ``UNKNOWN``    nothing matched, with ``candidates`` listing what exists.
    """
    folded = _fold(phrase)
    fleet = [
        d
        for d in devices
        if d.get("trustLevel") == "TRUSTED" and d.get("deviceId") != local_device_id
    ]

    if folded and any(w in folded for w in _HERE_WORDS):
        return {
            "status": "LOCAL",
            "device": None,
            "candidates": [],
            "message": "C'est cet appareil-ci : rien à envoyer ailleurs.",
        }

    if not fleet:
        return {
            "status": "UNKNOWN",
            "device": None,
            "candidates": [],
            "message": (
                "Aucun autre appareil n'est appairé. Ajoutez-en un depuis "
                "l'écran Appareils pour pouvoir lui envoyer quelque chose."
            ),
        }

    # « l'autre appareil » is only meaningful when there is exactly one.
    if folded and any(w in folded for w in _OTHER_WORDS) and len(fleet) == 1:
        return _resolved(fleet[0])

    scored: list[tuple[int, Mapping[str, Any]]] = []
    for device in fleet:
        score = max(_name_score(folded, device), _kind_score(folded, device))
        if score:
            scored.append((score, device))

    if not scored:
        # No phrase at all, and only one device: that is not a guess.
        if not folded.strip() and len(fleet) == 1:
            return _resolved(fleet[0])
        return {
            "status": "UNKNOWN",
            "device": None,
            "candidates": describe_devices(fleet),
            "message": (
                "Je ne vois pas de quel appareil il s'agit. " + _list_sentence(fleet)
            ),
        }

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best = scored[0][0]
    top = [device for score, device in scored if score == best]

    if len(top) > 1:
        # Being awake breaks a tie: « mon téléphone » means the one that is on.
        awake = [d for d in top if is_reachable(d)]
        if len(awake) == 1:
            return _resolved(awake[0])
        return {
            "status": "AMBIGUOUS",
            "device": None,
            "candidates": describe_devices(top),
            "message": ("Plusieurs appareils correspondent. " + _list_sentence(top)),
        }

    return _resolved(top[0])


def _resolved(device: Mapping[str, Any]) -> dict[str, Any]:
    presence = presence_of(device)
    name = device.get("name") or "cet appareil"
    return {
        "status": "RESOLVED",
        "device": dict(device),
        "candidates": [],
        "message": f"{name} ({_state_label(presence['state'])}).",
    }


def _state_label(state: str) -> str:
    return {
        "ONLINE": "en ligne",
        "IDLE": "inactif mais joignable",
        "BACKGROUND": "en arrière-plan",
        "OFFLINE": "hors ligne",
    }.get(state, "état inconnu")


def _list_sentence(devices: Sequence[Mapping[str, Any]]) -> str:
    """The question to ask back, with each device's state — because the user's
    answer usually depends on which one is actually on."""
    parts = [
        f"« {d.get('name')} » ({_state_label(presence_of(d)['state'])})"
        for d in devices
    ]
    return "Lequel : " + ", ".join(parts) + " ?"


def describe_devices(devices: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The fleet as the assistant should see it: names, kinds, and whether
    they are awake. No keys, no addresses — nothing the model needs."""
    return [
        {
            "deviceId": d.get("deviceId"),
            "name": d.get("name"),
            "deviceType": d.get("deviceType"),
            "platform": d.get("platform"),
            "presence": presence_of(d)["state"],
            "reachable": is_reachable(d),
            "capabilities": list(d.get("capabilities") or []),
        }
        for d in devices
    ]
