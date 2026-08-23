

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
