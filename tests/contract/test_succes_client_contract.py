"""Le contrat entre Diapason et son client mobile Succès.

Les deux vivent dans des dépôts séparés — Succès doit rester présentable
seul — et communiquent par deux surfaces : l'encodage canonique du maillage
(des octets signés, où un écart d'UN caractère invalide toutes les
signatures) et les 49 routes ``/v1/succes``.

Une frontière entre deux dépôts ne se surveille pas toute seule. Sans ces
tests, un changement anodin ici casse l'application mobile en silence, et
le défaut n'apparaît qu'au téléphone, loin du commit qui l'a causé. Ces
tests échouent DU CÔTÉ où le changement est fait.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from diapason.mesh.identity import canonical_bytes

# Le dépôt Flutter, à côté. Absent sur une machine de CI ou chez quelqu'un
# qui n'a que Diapason : les tests concernés se sautent alors proprement,
# plutôt que d'échouer pour une raison qui n'est pas un défaut.
SUCCES = pathlib.Path.home() / "Desktop/Porfolio/Succes"
VECTEURS = SUCCES / "test/mesh/canonical_vectors.json"

besoin_du_flutter = pytest.mark.skipif(
    not VECTEURS.exists(),
    reason="dépôt Succès absent — contrat vérifié là où les deux coexistent",
)


class TestLEncodageCanoniqueNeDerivePas:
    """Les octets que Dart doit reproduire à l'identique.

    Le générateur (scripts/gen_canonical_vectors.py) écrit ces vecteurs
    depuis l'implémentation réelle. Rien ne signalait qu'ils étaient
    devenus faux : toucher ``canonical_bytes`` sans régénérer laissait un
    fichier périmé côté Flutter, et chaque signature échouait ensuite sans
    qu'aucun message n'explique pourquoi.
    """

    @besoin_du_flutter
    def test_les_vecteurs_livres_correspondent_a_l_implementation(self):
        livres = json.loads(VECTEURS.read_text(encoding="utf-8"))
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
            "puis commite le fichier dans le dépôt Succès.\n"
            f"Premier écart : {derives[0]['payload']}"
        )

    @besoin_du_flutter
    def test_le_jeu_couvre_les_pieges_connus(self):
        """Un vecteur ne protège que ce qu'il exerce. Ces quatre-là sont les
        écarts d'encodage qui cassent une signature sans rien dire."""
        payloads = [
            v["payload"] for v in json.loads(VECTEURS.read_text(encoding="utf-8"))
        ]
        texte = json.dumps(payloads, ensure_ascii=False)

        assert any(len(p) > 1 for p in payloads), "aucun cas de tri des clés"
        assert "«" in texte or "—" in texte, "aucun cas non-ASCII"
        assert any(
            isinstance(v, list) for p in payloads for v in p.values()
        ), "aucun cas de liste"
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
    """Les 73 routes que l'application mobile appelle.

    Un cliquet, pas une interdiction : renommer ou supprimer une route
    reste permis — il faut seulement régénérer l'instantané dans le MÊME
    commit, ce qui rend le changement visible en revue et rappelle qu'un
    client mobile déjà installé va cesser de fonctionner.

    Sans ça, la rupture ne se manifeste qu'au téléphone, loin du commit.
    """

    def _actuelles(self) -> list[str]:
        from diapason.succes.routes import router

        return sorted(
            f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}"
            for r in router.routes
            if getattr(r, "methods", None)
        )

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
