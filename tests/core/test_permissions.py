"""0600 là où cela veut dire quelque chose, et nulle part ailleurs.

Trois endroits du dépôt écrivaient un secret sur le disque et tentaient d'en
restreindre l'accès. Trois gardes différents, dont deux faux :

* deux testaient ``hasattr(os, "fchmod")`` — or Python 3.13 EXPOSE ce nom sur
  Windows, où l'appel lève ``PermissionError: [WinError 5]``. Tester le nom,
  c'est confondre « la fonction est là » avec « l'opération marche ».
* le troisième n'avait aucun garde.

Constaté sur le PC de Carlito le 26 août 2026, au premier jumelage :
``device_identity()`` levait, et comme presque tout le maillage l'appelle,
RIEN ne fonctionnait sur Windows. La clé d'API du serveur serait tombée sur la
même pierre au démarrage suivant.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from diapason.core import permissions


def test_le_garde_regarde_la_plateforme_pas_le_nom():
    """`hasattr` répond « oui » sur Windows depuis Python 3.13. La question
    n'était donc pas la bonne."""
    assert permissions.POSIX == (os.name != "nt")


def test_sur_posix_les_droits_sont_reellement_poses(tmp_path: Path):
    if not permissions.POSIX:
        pytest.skip("les bits POSIX ne gouvernent pas l'accès ici")
    chemin = tmp_path / "secret"
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT, 0o666)
    try:
        permissions.restreindre_au_proprietaire(fd)
    finally:
        os.close(fd)
    assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600


def test_sur_windows_il_ne_fait_rien_et_ne_leve_pas(tmp_path, monkeypatch):
    """Simule Windows : l'appel doit être un non-événement, pas un échec.

    Sans cela — c'est exactement ce qui s'est produit — la moindre lecture de
    clé fait tomber tout le maillage.
    """
    monkeypatch.setattr(permissions, "POSIX", False)

    appele = []
    monkeypatch.setattr(os, "fchmod", lambda *a: appele.append(a), raising=False)

    chemin = tmp_path / "secret"
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT, 0o666)
    try:
        permissions.restreindre_au_proprietaire(fd)  # ne doit pas lever
    finally:
        os.close(fd)
    assert appele == [], "fchmod a été appelé là où il échoue toujours"


def test_les_trois_ecritures_de_secret_passent_par_ce_garde():
    """Un seul endroit, pas trois copies — c'est ce qui a permis à deux des
    trois d'être fausses sans que personne ne le voie."""
    racine = Path(__file__).resolve().parents[2] / "src" / "diapason"
    fautifs = []
    for chemin in racine.rglob("*.py"):
        if chemin.name == "permissions.py":
            continue
        texte = chemin.read_text(encoding="utf-8")
        for numero, ligne in enumerate(texte.splitlines(), 1):
            if "os.fchmod(" in ligne and not ligne.lstrip().startswith("#"):
                fautifs.append(f"{chemin.relative_to(racine)}:{numero}")
    assert not fautifs, (
        f"`os.fchmod` appelé directement, hors du garde partagé : {fautifs}"
    )
