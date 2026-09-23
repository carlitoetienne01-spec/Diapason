"""Ce qu'une carte d'outil dit d'une recherche — chat et voix, un seul calcul.

22/09/2026. `web_search` savait depuis le 20/09 quel moteur avait répondu et
combien de résultats il avait rendus ; rien ne le faisait traverser. La carte
affichait « web_search · 0,8 s », le terminal une ligne `OK` verte : une
recherche VIDE se lisait comme une recherche fructueuse, et la réponse bâtie
dessus ne s'annonçait pas (§5).
"""

from diapason.core.types import ToolResult
from diapason.server.details_outils import details_du_fil


class TestCeQuiTraverse:
    def test_le_moteur_et_le_compte(self):
        resultat = ToolResult(
            tool_name="web_search",
            content="[1] …",
            success=True,
            metadata={"engine": "brave/news", "numResults": 8, "sources": []},
        )
        assert details_du_fil(resultat) == {"engine": "brave/news", "numResults": 8}

    def test_zero_traverse_aussi(self):
        """C'est le cas pour lequel ceci existe : un `if not nombre` l'aurait
        jeté, et le vide se serait lu comme un succès."""
        vide = ToolResult(
            tool_name="web_search",
            content="No results found.",
            success=True,
            metadata={"engine": "duckduckgo/text", "numResults": 0},
        )
        assert details_du_fil(vide)["numResults"] == 0

    def test_la_boucle_vocale_porte_des_dicts(self):
        """Le chat manipule un ToolResult, la voix des dicts. Deux calculs des
        mêmes deux pièges finiraient par diverger, et c'est celui qu'on
        oublierait qui mentirait."""
        assert details_du_fil(
            {
                "ok": True,
                "content": "…",
                "metadata": {"engine": "yahoo/text", "numResults": 3},
            }
        ) == {"engine": "yahoo/text", "numResults": 3}


class TestCeQuiNeTraversePas:
    def test_un_outil_ordinaire_n_ajoute_rien(self):
        assert (
            details_du_fil(ToolResult(tool_name="read_file", content="x", success=True))
            == {}
        )

    def test_un_outil_qui_leve_n_a_pas_de_resultat(self):
        """L'appelant nomme `resultat` avant son `try` : sans cela, la carte
        d'un outil cassé serait un NameError au lieu d'un échec."""
        assert details_du_fil(None) == {}

    def test_une_metadonnee_qui_n_en_est_pas_une(self):
        assert details_du_fil({"ok": True, "metadata": "pas un dict"}) == {}

    def test_un_booleen_n_est_pas_un_compte(self):
        """`isinstance(True, int)` est vrai en Python : « 1 rés. » pour un
        drapeau serait un chiffre inventé."""
        assert "numResults" not in details_du_fil(
            ToolResult(
                tool_name="web_search",
                content="x",
                success=True,
                metadata={"numResults": True},
            )
        )

    def test_un_moteur_vide_ne_fabrique_pas_de_cle(self):
        assert details_du_fil({"metadata": {"engine": "", "numResults": 0}}) == {
            "numResults": 0
        }
