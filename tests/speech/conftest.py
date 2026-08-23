"""Gardes du dossier parole.

L'historique vocal (traces.db) suit le modèle du profil vocal : AUCUN test
ne doit écrire dans le vrai ~/.diapason/traces.db. La fixture autouse coupe
la résolution du magasin ; un test qui veut observer le journal en injecte
un explicitement (session._magasin_traces_obj = TraceStore(tmp_path/...),
session._magasin_traces_resolu = True).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isoler_les_traces_vocales(monkeypatch):
    from diapason.speech.realtime import local_voice

    def _aucun_magasin(self):
        # Respecte un magasin injecté par le test (résolu d'avance) ; bloque
        # seulement la résolution par la config — celle du vrai ~/.diapason.
        if not self._magasin_traces_resolu:
            self._magasin_traces_resolu = True
            self._magasin_traces_obj = None
        return self._magasin_traces_obj

    monkeypatch.setattr(
        local_voice.LocalVoiceSession, "_magasin_traces", _aucun_magasin
    )
    yield
