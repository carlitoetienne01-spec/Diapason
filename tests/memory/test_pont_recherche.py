"""Les faits extraits doivent atterrir là où la relecture les cherche.

Constaté le 22 août 2026. ``build_memory_service`` rangeait les faits dans
``memory_facts.jsonl`` ; ``inject_context`` interrogeait le magasin vectoriel
de ``memory.db``. Deux magasins qui ne se croisaient jamais. Diapason
distillait correctement « le projet Olala doit être publié sur l'App Store
avant fin septembre », l'écrivait, et ne le retrouvait plus jamais : la
mémoire automatique écrivait dans le vide.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from diapason.memory.store import LocalFactStore, SearchableFactStore


class _MagasinFactice:
    def __init__(self, casse: bool = False) -> None:
        self.recus: list[tuple[str, str]] = []
        self._casse = casse

    def store(self, content: str, *, source: str = "", metadata=None) -> str:
        if self._casse:
            raise RuntimeError("magasin indisponible")
        self.recus.append((content, source))
        return "doc-1"


def _pont(tmp_path, casse: bool = False):
    journal = LocalFactStore(tmp_path / "facts.jsonl")
    magasin = _MagasinFactice(casse=casse)
    return SearchableFactStore(journal, magasin), journal, magasin


def test_un_fait_part_dans_les_deux_magasins(tmp_path):
    pont, journal, magasin = _pont(tmp_path)
    assert pont.add("Carlito boit du thé le matin.", source="chat") is True
    assert journal.count() == 1
    assert magasin.recus == [("Carlito boit du thé le matin.", "chat")], (
        "le fait n'atteignait jamais le magasin que la relecture interroge"
    )


def test_un_doublon_n_est_pas_reindexe(tmp_path):
    """Réindexer coûte un embedding pour rien et pollue les résultats."""
    pont, _, magasin = _pont(tmp_path)
    pont.add("Un fait.", source="chat")
    assert pont.add("Un fait.", source="chat") is False
    assert len(magasin.recus) == 1


def test_une_panne_du_magasin_ne_perd_pas_le_fait(tmp_path):
    """Le journal a déjà écrit : l'indexation est un bonus, pas une condition."""
    pont, journal, _ = _pont(tmp_path, casse=True)
    assert pont.add("Un fait qui compte.") is True
    assert journal.count() == 1
    assert [f.text for f in pont.list()] == ["Un fait qui compte."]


def test_la_source_par_defaut_est_nommee(tmp_path):
    """Sans source, le résultat s'afficherait sans attribution."""
    pont, _, magasin = _pont(tmp_path)
    pont.add("Sans source explicite.")
    assert magasin.recus[0][1] == "memory"


def test_le_pont_delegue_lecture_comptage_et_purge(tmp_path):
    pont, journal, _ = _pont(tmp_path)
    pont.add("A")
    pont.add("B")
    assert pont.count() == 2
    assert [f.text for f in pont.list()] == ["A", "B"]
    assert pont.clear() == 2
    assert journal.count() == 0


class TestConstruction:
    """``build_memory_service`` doit poser le pont quand un magasin existe."""

    def _config(self, tmp_path, enabled=True):
        return SimpleNamespace(
            memory=SimpleNamespace(
                enabled=enabled,
                backend="local",
                extraction_model="modele-de-test",
                max_facts=100,
                facts_path=str(tmp_path / "facts.jsonl"),
            )
        )

    def test_avec_un_magasin_le_pont_est_pose(self, tmp_path):
        from diapason.memory.service import build_memory_service

        svc = build_memory_service(
            self._config(tmp_path),
            engine=object(),
            memory_backend=_MagasinFactice(),
        )
        assert svc is not None
        assert isinstance(svc._store, SearchableFactStore)

    def test_sans_magasin_le_journal_seul_subsiste(self, tmp_path):
        """Une installation sans backend garde une mémoire, même non cherchable."""
        from diapason.memory.service import build_memory_service

        svc = build_memory_service(self._config(tmp_path), engine=object())
        assert svc is not None
        assert isinstance(svc._store, LocalFactStore)

    def test_memoire_desactivee_ne_construit_rien(self, tmp_path):
        from diapason.memory.service import build_memory_service

        assert (
            build_memory_service(
                self._config(tmp_path, enabled=False),
                engine=object(),
                memory_backend=_MagasinFactice(),
            )
            is None
        )


@pytest.mark.parametrize("texte", ["", "   "])
def test_un_fait_vide_n_encombre_rien(tmp_path, texte):
    pont, _, magasin = _pont(tmp_path)
    pont.add(texte)
    assert magasin.recus == []
