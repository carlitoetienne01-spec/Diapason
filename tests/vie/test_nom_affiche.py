"""Le domaine « vie » s'affiche sous le nom Diapason (étape 11, phase 1b).

Plan : docs/development/diapason-mobile.md, étape 11. « Succès » était le nom
d'une application séparée ; il survivait dans des messages rendus à
l'utilisateur (erreurs 503, refus du mode local, aide de ``diapason serve``),
aux outils du modèle (« Action Succès inconnue ») et au récepteur du maillage
(« Succès est au premier plan. »). Chacun disait le nom d'un produit qui
n'existe plus à l'écran.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import diapason

_SOURCE = Path(diapason.__file__).parent
# La majuscule seule : « un succès », au sens de réussite, reste permis.
_ANCIEN_NOM = re.compile(r"\bSuccès\b")


def _chaines_hors_docstrings(chemin: Path) -> list[tuple[int, str]]:
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for noeud in ast.walk(arbre):
        if isinstance(
            noeud, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            corps = noeud.body
            if (
                corps
                and isinstance(corps[0], ast.Expr)
                and isinstance(corps[0].value, ast.Constant)
            ):
                docstrings.add(id(corps[0].value))
    return [
        (noeud.lineno, noeud.value)
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Constant)
        and isinstance(noeud.value, str)
        and id(noeud) not in docstrings
    ]


class TestLeNomAffiche:
    def test_aucune_chaine_du_code_ne_nomme_encore_succes(self):
        """Les docstrings et les commentaires racontent l'histoire, à bon droit ;
        une chaîne, elle, peut finir à l'écran ou dans la bouche du modèle."""
        fautives = [
            f"{chemin.relative_to(_SOURCE)}:{ligne}"
            for chemin in sorted(_SOURCE.rglob("*.py"))
            for ligne, valeur in _chaines_hors_docstrings(chemin)
            if _ANCIEN_NOM.search(valeur)
        ]
        assert fautives == [], f"ces chaînes disent encore « Succès » : {fautives}"

    def test_le_banc_voit_bien_les_chaines(self, tmp_path):
        """Sans ce témoin, un parcours qui ne lirait rien passerait le test
        précédent sans rien vérifier."""
        temoin = tmp_path / "temoin.py"
        temoin.write_text(
            '"""Succès dans la docstring."""\nMESSAGE = "Succès est ouvert."\n',
            encoding="utf-8",
        )
        trouvees = [
            valeur
            for _, valeur in _chaines_hors_docstrings(temoin)
            if _ANCIEN_NOM.search(valeur)
        ]
        assert trouvees == ["Succès est ouvert."], (
            "la chaîne doit être vue, la docstring ignorée"
        )


def _aides_de_la_ligne_de_commande(groupe, chemin="diapason"):
    """Chaque texte que ``--help`` rend : aide, résumé, aide des options."""
    import click

    textes = [(chemin, groupe.help or ""), (chemin, groupe.short_help or "")]
    textes += [
        (f"{chemin} {p.name}", p.help or "")
        for p in groupe.params
        if isinstance(p, click.Option)
    ]
    for nom, commande in getattr(groupe, "commands", {}).items():
        textes += _aides_de_la_ligne_de_commande(commande, f"{chemin} {nom}")
    return textes


class TestLAideDeLaLigneDeCommande:
    def test_aucune_aide_de_commande_ne_nomme_encore_succes(self):
        """Click publie la docstring d'une commande comme son ``--help`` : le
        test précédent, qui écarte toute docstring, ne pouvait pas voir
        « les données de Succès » de ``diapason heartbeat briefing --help``
        (constaté le 25/09/2026)."""
        from diapason.cli import cli

        aides = _aides_de_la_ligne_de_commande(cli)
        fautives = sorted(
            {chemin for chemin, texte in aides if _ANCIEN_NOM.search(texte)}
        )
        assert len(aides) > 200, f"le parcours doit voir toute la CLI, pas {len(aides)}"
        assert fautives == [], f"ces aides disent encore « Succès » : {fautives}"
