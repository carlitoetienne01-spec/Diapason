class TestEnchainementParle:
    """« Maintenant, fais-moi la recherche du jeu solitaire » tombait dans le
    vide (23 août 2026) : les connecteurs d'enchaînement cassaient TOUS les
    motifs ancrés en tête, et « faire la recherche de » n'était pas un verbe
    de recherche connu."""

    def test_les_connecteurs_de_tete_ne_cassent_plus_rien(self):
        from diapason.desktop.voice_commands import parse_voice_command

        assert parse_voice_command("Ensuite, ouvre Safari").kind == "focus_app"
        assert parse_voice_command("et maintenant cherche des jeux").kind == "search"
        assert parse_voice_command("Bon, alors, trouve-moi un café").kind == "search"

    def test_faire_la_recherche_est_une_recherche(self):
        from diapason.desktop.voice_commands import parse_voice_command

        action = parse_voice_command(
            "Maintenant, fais-moi la recherche du jeu solitaire."
        )
        assert action.kind == "search"
        assert action.target == "jeu solitaire"
        action = parse_voice_command("fais une recherche sur les chaises")
        assert action.kind == "search"

    def test_faire_autre_chose_ne_devient_pas_une_recherche(self):
        from diapason.desktop.voice_commands import parse_voice_command

        assert parse_voice_command("fais la vaisselle").kind == "none"
        assert parse_voice_command("fais-moi un café").kind == "none"


class TestLeTelephoneNeCommandePasLeMac:
    """execute_voice_action ouvre, cherche et compose sur le Mac sans passer
    par ToolExecutor : sa dernière barrière est la sienne (26/09/2026)."""

    def test_sous_la_marque_du_telephone_rien_ne_s_ouvre(self, monkeypatch):
        from diapason.core.origine_telephone import marquer_le_telephone
        from diapason.desktop.voice_commands import VoiceAction, execute_voice_action
        from diapason.tools import desktop_tools

        ouvertures: list = []
        monkeypatch.setattr(
            desktop_tools, "open_application", lambda nom, **_k: ouvertures.append(nom)
        )
        with marquer_le_telephone():
            rendu = execute_voice_action(VoiceAction(kind="focus_app", target="Safari"))
        assert ouvertures == [], "Safari s'est ouvert sur le Mac depuis le téléphone"
        assert rendu["success"] is False
        assert "téléphone" in rendu["detail"], "le refus doit dire pourquoi"
