"""Un type de routine inconnu doit se déclarer en échec, pas en succès.

``kinds.py`` posait ``content = f"Unknown routine kind: {kind}"`` puis tombait
dans le chemin de SUCCÈS : ``record_run(success=True)``. Neuf des douze
routines de Carlito étaient dans ce cas. Elles « réussissaient » chaque jour
sans rien faire, et aucune surface ne le lui apprenait.

Un échec silencieux qui se déclare réussi est pire qu'un échec bruyant : il
retire jusqu'à la possibilité de s'en apercevoir.
"""

from __future__ import annotations

import pytest

from diapason.heartbeat.kinds import KINDS_EXECUTABLES


def test_la_liste_des_types_executables_est_exposee():
    """Le message d'erreur doit pouvoir nommer ce qui marche."""
    assert "morning-digest" in KINDS_EXECUTABLES
    assert "reminder" in KINDS_EXECUTABLES


def test_morning_brief_est_devenu_executable():
    """C'est l'un des neuf que le fichier de Carlito contient."""
    assert "morning-brief" in KINDS_EXECUTABLES


@pytest.mark.parametrize(
    "absent",
    ["dictation-style", "extract-skills", "email-learning", "nightly-reflection"],
)
def test_les_types_encore_absents_le_sont_franchement(absent):
    """Ils ne sont pas exécutables — et le code ne doit pas prétendre l'inverse."""
    assert absent not in KINDS_EXECUTABLES


def test_un_type_inconnu_rend_un_echec(tmp_path, monkeypatch):
    from diapason.heartbeat import kinds

    enregistres: list[dict] = []
    monkeypatch.setattr(
        kinds, "record_run", lambda rid, **kw: enregistres.append({"id": rid, **kw})
    )
    monkeypatch.setattr(kinds, "_precheck_idle", lambda r, force=False: (True, ""))
    monkeypatch.setattr(kinds, "_quiet_from_config", lambda c: False)

    from diapason.heartbeat.routines import Routine

    routine = Routine(
        id="essai",
        name="Essai",
        cron="0 7 * * *",
        kind="un-type-qui-n-existe-pas",
        enabled=True,
        payload={},
    )
    resultat = kinds.run_routine(routine, workspace=str(tmp_path))

    assert resultat["ok"] is False, "un type inconnu était compté comme un succès"
    assert resultat["reason"] == "unknown_kind"
    assert "un-type-qui-n-existe-pas" in resultat["content"]
    assert enregistres and enregistres[0]["success"] is False, (
        "le journal des exécutions doit porter l'échec"
    )
    # Le message doit dire ce qui EST possible, sinon il ne sert qu'à constater.
    assert "morning-digest" in resultat["content"]
