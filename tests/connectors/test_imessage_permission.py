"""iMessage n'échoue plus en silence : l'échec porte son remède."""

from __future__ import annotations

import pytest

from diapason.connectors.imessage import IMessageConnector


def test_une_base_illisible_dit_le_remede(tmp_path):
    connecteur = IMessageConnector(db_path=tmp_path / "inexistant" / "chat.db")
    with pytest.raises(PermissionError) as info:
        list(connecteur.sync())
    assert "Accès complet au disque" in str(info.value)
    assert "resynchronise" in str(info.value)
