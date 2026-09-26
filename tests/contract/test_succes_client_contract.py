"""Le contrat entre Diapason et son client mobile (diapason_mobile, ex-Succès).

Les deux vivent dans des dépôts séparés — Succès doit rester présentable
seul — et communiquent par deux surfaces : l'encodage canonique du maillage
(des octets signés, où un écart d'UN caractère invalide toutes les
signatures) et les routes ``/v1/succes``, dont l'instantané fait foi
(tests/contract/succes_api_surface.json).

Une frontière entre deux dépôts ne se surveille pas toute seule. Sans ces
tests, un changement anodin ici casse l'application mobile en silence, et
le défaut n'apparaît qu'au téléphone, loin du commit qui l'a causé. Ces
tests échouent DU CÔTÉ où le changement est fait.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from diapason.mesh.identity import canonical_bytes

# Le dépôt Flutter, à côté. Déménagé de ~/Desktop/Porfolio/Succes le
# 25/09/2026 : l'ancien chemin a fait SAUTER ces tests en silence dès le
# déménagement — le cliquet se taisait exactement quand plus rien ne le
# vérifiait. Hors CI, son absence est donc un ÉCHEC (voir _vecteurs).
MOBILE = pathlib.Path.home() / "Projets/diapason_mobile"
VECTEURS = MOBILE / "test/mesh/canonical_vectors.json"


def _lisible(chemin: pathlib.Path) -> bool:
    """Le fichier est-il RÉELLEMENT lisible, pas seulement présent ?

    ``exists()`` ne suffit pas sur macOS : le Bureau est protégé, et un
    processus sans autorisation voit le fichier tout en se voyant refuser son
    ouverture. Le test échouait alors sur un PermissionError et signalait une
    rupture de contrat là où il n'y avait qu'une permission manquante — le
    genre de faux défaut qui fait chercher au mauvais endroit.
    """
    try:
        with chemin.open("rb") as f:
            f.read(1)
    except OSError:
        return False
    return True


def _en_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _vecteurs() -> pathlib.Path:
    """Le fichier de vecteurs du dépôt mobile — ou un échec qui le dit.

    Seule la CI a le droit de s'en passer : le runner Windows pc-bureau n'a
    que Diapason. Partout ailleurs, un dépôt mobile absent ou illisible
    veut dire que le chemin ci-dessus est faux, et un saut maquillerait
    cette panne en « contrat respecté ».
    """
    if _lisible(VECTEURS):
        return VECTEURS
    if _en_ci():
        pytest.skip(
            f"{VECTEURS} absent du runner de CI — contrat vérifié là où les "
            "deux dépôts coexistent"
        )
    pytest.fail(
        f"{VECTEURS} introuvable ou illisible. Le dépôt mobile doit vivre dans "
        f"{MOBILE} (clone-le, ou corrige MOBILE ici et dans "
        "scripts/gen_canonical_vectors.py s'il a déménagé). Hors CI, son "
        "absence n'est pas un saut : c'est le contrat qui n'est plus vérifié."
    )


class TestLEncodageCanoniqueNeDerivePas:
    """Les octets que Dart doit reproduire à l'identique.

    Le générateur (scripts/gen_canonical_vectors.py) écrit ces vecteurs
    depuis l'implémentation réelle. Rien ne signalait qu'ils étaient
    devenus faux : toucher ``canonical_bytes`` sans régénérer laissait un
    fichier périmé côté Flutter, et chaque signature échouait ensuite sans
    qu'aucun message n'explique pourquoi.
    """

    def test_les_vecteurs_livres_correspondent_a_l_implementation(self):
        livres = json.loads(_vecteurs().read_text(encoding="utf-8"))
        assert livres, "le fichier de vecteurs est vide"

        derives = [
            v
            for v in livres
            if canonical_bytes(v["payload"]).decode("utf-8") != v["expected"]
        ]
        assert not derives, (
            f"{len(derives)} vecteur(s) périmé(s) — canonical_bytes a changé "
            "sans régénération. Lance :\n"
            "  .venv/bin/python scripts/gen_canonical_vectors.py\n"
            "puis commite le fichier dans le dépôt diapason_mobile.\n"
            f"Premier écart : {derives[0]['payload']}"
        )

    def test_le_jeu_couvre_les_pieges_connus(self):
        """Un vecteur ne protège que ce qu'il exerce. Ces quatre-là sont les
        écarts d'encodage qui cassent une signature sans rien dire."""
        payloads = [
            v["payload"] for v in json.loads(_vecteurs().read_text(encoding="utf-8"))
        ]
        texte = json.dumps(payloads, ensure_ascii=False)

        assert any(len(p) > 1 for p in payloads), "aucun cas de tri des clés"
        assert "«" in texte or "—" in texte, "aucun cas non-ASCII"
        assert any(isinstance(v, list) for p in payloads for v in p.values()), (
            "aucun cas de liste"
        )
        assert any(
            isinstance(v, int) and v > 2**31 for p in payloads for v in p.values()
        ), "aucun cas d'entier 64 bits (les millisecondes débordent en 32)"

    def test_l_encodage_reste_sans_espaces_et_trie(self):
        """La propriété que le Dart réimplémente. Indépendante du Flutter :
        elle doit tenir même seule dans ce dépôt."""
        rendu = canonical_bytes({"b": 2, "a": 1}).decode("utf-8")
        assert rendu == '{"a":1,"b":2}', rendu

    def test_le_non_ascii_n_est_pas_echappe(self):
        """``ensure_ascii=True`` produirait \\u00e9 — des octets différents,
        donc une signature différente, pour un texte identique à l'œil."""
        rendu = canonical_bytes({"v": "été"}).decode("utf-8")
        assert rendu == '{"v":"été"}', rendu


SURFACE = pathlib.Path(__file__).with_name("succes_api_surface.json")


class TestLaSurfaceApiNeBougePasParAccident:
    """Les routes que l'application mobile appelle.

    Le compte vit dans l'instantané, pas dans cette phrase : deux nombres
    écrits en dur (49 ici, 73 là) contredisaient déjà le fichier, qui en
    porte 79. Un commentaire qui vieillit est pire qu'aucun.

    Un cliquet, pas une interdiction : renommer ou supprimer une route
    reste permis — il faut seulement régénérer l'instantané dans le MÊME
    commit, ce qui rend le changement visible en revue et rappelle qu'un
    client mobile déjà installé va cesser de fonctionner.

    Sans ça, la rupture ne se manifeste qu'au téléphone, loin du commit.
    """

    def _actuelles(self) -> list[str]:
        # 25/09/2026 : ce fichier fige désormais l'ALIAS /v1/succes, calculé
        # sur une application montée (le routeur nu n'a plus de préfixe).
        from diapason.vie.routes import PREFIXE_HERITE, surface_api

        return surface_api(PREFIXE_HERITE)

    def test_aucune_route_disparue_ni_renommee(self):
        figees = set(json.loads(SURFACE.read_text(encoding="utf-8")))
        perdues = figees - set(self._actuelles())
        assert not perdues, (
            f"{len(perdues)} route(s) que Succès appelle ont disparu :\n  "
            + "\n  ".join(sorted(perdues))
            + "\n\nSi c'est voulu, régénère l'instantané dans CE commit et "
            "prévois la version mobile qui cessera de fonctionner."
        )

    def test_les_routes_neuves_sont_declarees(self):
        """Ajouter est inoffensif pour le client — mais l'instantané doit
        rester le miroir exact de la surface, sinon il cesse d'être une
        référence de confiance."""
        figees = set(json.loads(SURFACE.read_text(encoding="utf-8")))
        neuves = set(self._actuelles()) - figees
        assert not neuves, (
            f"{len(neuves)} route(s) neuve(s) hors instantané :\n  "
            + "\n  ".join(sorted(neuves))
            + "\n\nRégénère :\n"
            "  .venv/bin/python scripts/gen_succes_surface.py"
        )
