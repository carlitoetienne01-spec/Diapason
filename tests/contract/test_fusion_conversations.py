"""L'instantané de la fusion des conversations est encore celui du code.

La même règle vit côté serveur (Python) et côté client (TypeScript) ; cet
instantané est ce qui les tient ensemble. S'il périme d'un côté sans être
régénéré, ``frontend/src/lib/convSync.fixture.test.ts`` ou ce test le dit.
"""

from __future__ import annotations

import json
from pathlib import Path

from diapason.server.conversations_store import fusionner_conversations

INSTANTANE = Path(__file__).parent / "fusion_conversations.json"


class TestLInstantaneDeLaFusion:
    def test_le_python_reproduit_chaque_cas(self):
        """§100 — deux vues qui « convergent » vers deux résultats différents
        se croient toutes deux synchronisées. Régénérer avec
        scripts/gen_fusion_fixture.py dans le même commit que la règle."""
        cas = json.loads(INSTANTANE.read_text(encoding="utf-8"))["cas"]
        assert cas, "l'instantané ne doit pas être vide"
        for c in cas:
            assert fusionner_conversations(c["a"], c["b"]) == c["fusion"], (
                f"la règle Python a changé sans régénérer l'instantané : {c['nom']}"
            )
            assert fusionner_conversations(c["b"], c["a"]) == c["fusion"], (
                f"la fusion doit être commutative : {c['nom']}"
            )
