#!/usr/bin/env python3
"""Génère l'instantané de contrat de la fusion des conversations.

La règle de fusion (union des messages par identité, la version la plus
complète par message, métadonnées de l'écriture la plus récente, ordre total
sur égalité) vit DEUX fois : ``conversations_store.fusionner_conversations``
côté serveur et ``fusionnerConversations`` dans ``convSync.ts`` côté client.
Si elles divergent d'un cheveu, les vues « convergent » vers des résultats
différents et chacune se croit synchronisée (§100).

Ce script fait calculer les cas par le Python et écrit
``tests/contract/fusion_conversations.json`` ; ``tests/contract/
test_fusion_conversations.py`` vérifie que le Python le reproduit encore,
``frontend/src/lib/convSync.fixture.test.ts`` que le TypeScript le
reproduit aussi. Régénérer dans le MÊME commit que tout changement de la
règle :

    .venv/bin/python scripts/gen_fusion_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from diapason.server.conversations_store import fusionner_conversations  # noqa: E402

DESTINATION = Path(__file__).resolve().parent.parent / "tests" / "contract"
DESTINATION = DESTINATION / "fusion_conversations.json"


def _msg(ident, role, content, ts, **extra):
    m = {"id": ident, "role": role, "content": content, "timestamp": ts}
    m.update(extra)
    return m


def _conv(conv_id, updated, title, messages, **extra):
    c = {
        "id": conv_id,
        "title": title,
        "createdAt": 1000,
        "updatedAt": updated,
        "model": "default",
        "messages": messages,
    }
    c.update(extra)
    return c


BASE = [_msg("q1", "user", "Bonjour", 100), _msg("r1", "assistant", "Salut", 101)]

CAS = {
    "deux vues, deux paires : union dans l'ordre du temps": (
        _conv(
            "x",
            2001,
            "Titre de A",
            BASE
            + [_msg("q2", "user", "A ?", 2000), _msg("r2", "assistant", "Ra", 2001)],
        ),
        _conv(
            "x",
            3001,
            "Titre de B",
            BASE
            + [_msg("q3", "user", "B ?", 3000), _msg("r3", "assistant", "Rb", 3001)],
        ),
    ),
    "copie partielle récente contre réponse complète ancienne": (
        _conv(
            "x",
            5000,
            "x",
            [
                _msg("q", "user", "?", 1),
                _msg(
                    "r",
                    "assistant",
                    "Bonjour !",
                    2,
                    usage={
                        "prompt_tokens": 1,
                        "completion_tokens": 3,
                        "total_tokens": 4,
                    },
                ),
            ],
        ),
        _conv(
            "x",
            6000,
            "x",
            [_msg("q", "user", "?", 1), _msg("r", "assistant", "Bonj", 2)],
            pinned=True,
        ),
    ),
    "même milliseconde, titres différents : ordre total": (
        _conv("x", 1000, "Alpha", [_msg("1", "user", "x", 1)]),
        _conv("x", 1000, "Beta", [_msg("1", "user", "x", 1)]),
    ),
    "même milliseconde, même contenu, longueur égale : lexicographique": (
        _conv("x", 1000, "T", [_msg("1", "assistant", "abc", 1)]),
        _conv("x", 1000, "T", [_msg("1", "assistant", "abd", 1)]),
    ),
    "messages d'avant l'identifiant : repli role@timestamp": (
        _conv("x", 10, "x", [{"role": "user", "content": "salut", "timestamp": 5}]),
        _conv(
            "x",
            20,
            "y",
            [
                {"role": "user", "content": "salut", "timestamp": 5},
                {"role": "assistant", "content": "re", "timestamp": 6},
            ],
        ),
    ),
    "paire à la même milliseconde : la question précède la réponse": (
        _conv("x", 10, "x", [_msg("b", "assistant", "réponse", 7)]),
        _conv("x", 10, "x", [_msg("a", "user", "question", 7)]),
    ),
    "unicode et accents dans les deux copies": (
        _conv("x", 10, "Été 😀", [_msg("1", "user", "héhé", 1)]),
        _conv(
            "x",
            10,
            "Été 😀",
            [_msg("1", "user", "héhé", 1), _msg("2", "user", "ça", 2)],
        ),
    ),
    "copies identiques : sans effet": (
        _conv("x", 10, "x", [_msg("1", "user", "a", 1)], pinned=False),
        _conv("x", 10, "x", [_msg("1", "user", "a", 1)], pinned=False),
    ),
    "createdAt le plus bas, updatedAt le plus haut": (
        dict(_conv("x", 10, "vieux", []), createdAt=5),
        dict(_conv("x", 30, "neuf", []), createdAt=9),
    ),
}


def main() -> None:
    cas = []
    for nom, (a, b) in CAS.items():
        ab = fusionner_conversations(a, b)
        ba = fusionner_conversations(b, a)
        assert ab == ba, f"la fusion doit être commutative : {nom}"
        assert fusionner_conversations(ab, a) == ab, f"et idempotente : {nom}"
        cas.append({"nom": nom, "a": a, "b": b, "fusion": ab})
    DESTINATION.write_text(
        json.dumps({"cas": cas}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(cas)} cas écrits dans {DESTINATION}")


if __name__ == "__main__":
    main()
