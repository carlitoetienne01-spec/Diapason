"""Un agent planifié doit se souvenir de son tour précédent.

L'appel qui écrivait cet état passait deux positionnels à une signature qui
n'en accepte qu'un. La ``TypeError`` était rattrapée par un ``except
Exception`` suivi d'un ``logger.debug`` : l'écriture échouait à *chaque* tour,
sans une ligne visible. L'agent redémarrait aveugle et refaisait le même
travail, ou pire, rapportait comme neuf ce qu'il avait déjà vu.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pytest

from diapason.agents.monitor_operative import MonitorOperativeAgent
from diapason.agents.operative import OperativeAgent
from diapason.tools.storage.sqlite import SQLiteMemory


@pytest.fixture
def backend():
    # Instancié en direct : le conftest de la suite vide les registres entre
    # les tests, et c'est le vrai backend qu'on veut ici — un double
    # accepterait joyeusement la signature fautive que ces tests gardent.
    return SQLiteMemory(db_path=str(Path(tempfile.mkdtemp()) / "m.db"))


def bare(cls, backend, operator_id: str):
    """L'agent sans son __init__ : on teste la persistance, pas le moteur."""
    agent = cls.__new__(cls)
    agent._memory_backend = backend
    agent._operator_id = operator_id
    return agent


class TestLEtatEstReellementEcrit:
    def test_operative_retrouve_son_etat(self, backend):
        agent = bare(OperativeAgent, backend, "veille")
        agent._auto_persist_state("Trois offres relevées, la moins chère à 420 €.")
        assert backend.retrieve("offres relevées")

    def test_monitor_operative_retrouve_son_etat(self, backend):
        agent = bare(MonitorOperativeAgent, backend, "surveillance")
        agent._auto_persist_state("Le disque est à 91 % depuis mardi.")
        assert backend.retrieve("disque")

    def test_le_bloc_notes_est_ecrit(self, backend):
        agent = bare(MonitorOperativeAgent, backend, "surveillance")
        agent._store_scratchpad("web_search", "Résultat intermédiaire à garder.")
        assert backend.retrieve("Résultat intermédiaire")

    def test_les_donnees_structurees_sont_ecrites(self, backend):
        agent = bare(MonitorOperativeAgent, backend, "surveillance")
        agent._store_structured("db_query", '{"clients": 42}')
        assert backend.retrieve("clients")

    def test_une_sortie_non_json_est_gardee_en_texte(self, backend):
        agent = bare(MonitorOperativeAgent, backend, "surveillance")
        agent._store_structured("shell", "pas du tout du JSON, mais à garder")
        assert backend.retrieve("pas du tout du JSON")


class TestUnEchecNeDoitPlusEtreMuet:
    def test_une_panne_de_stockage_laisse_une_trace(self, backend, caplog):
        """Le défaut n'était pas l'échec, c'était le silence. Si l'écriture
        casse à nouveau un jour, quelque chose doit le dire."""

        class BackendCasse:
            def store(self, *args, **kwargs):
                raise RuntimeError("disque plein")

        agent = bare(OperativeAgent, BackendCasse(), "veille")
        with caplog.at_level(logging.WARNING):
            agent._auto_persist_state("un état qui sera perdu")
        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_l_agent_ne_tombe_pas_pour_autant(self, backend):
        """Visible, oui ; fatal, non. Un agent de fond qui meurt d'une panne
        de disque est un deuxième défaut, pas une correction."""

        class BackendCasse:
            def store(self, *args, **kwargs):
                raise RuntimeError("disque plein")

        agent = bare(OperativeAgent, BackendCasse(), "veille")
        agent._auto_persist_state("un état qui sera perdu")  # ne lève pas
