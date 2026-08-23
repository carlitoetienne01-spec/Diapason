"""Les commentaires HTML des fichiers de persona ne doivent pas atteindre le modèle.

``USER.md`` est livré avec une note éditoriale — « ce fichier est à vous,
ajoutez-y ce que Diapason doit savoir » — adressée à la PERSONNE, glissée dans
un commentaire HTML parce que les afficheurs Markdown le masquent. Le modèle,
lui, n'a pas d'afficheur : il lit la note comme du contexte. Sur l'installation
de Carlito, ces trois lignes pesaient 19 % du prompt système entier.
"""

from __future__ import annotations

from diapason.core.config import MemoryFilesConfig, SystemPromptConfig
from diapason.prompt.builder import SystemPromptBuilder, _strip_html_comments


def _constructeur(tmp_path, contenu_user: str) -> SystemPromptBuilder:
    (tmp_path / "USER.md").write_text(contenu_user, encoding="utf-8")
    return SystemPromptBuilder(
        agent_template="Tu es Diapason.",
        memory_files_config=MemoryFilesConfig(
            soul_path="",
            memory_path="",
            user_path=str(tmp_path / "USER.md"),
        ),
        system_prompt_config=SystemPromptConfig(),
    )


class TestStripHtmlComments:
    def test_un_commentaire_disparait(self):
        assert _strip_html_comments("Avant <!-- caché --> après") == "Avant  après"

    def test_un_commentaire_sur_plusieurs_lignes_disparait(self):
        texte = "Utile\n<!-- ligne un\n     ligne deux -->\nEncore utile"
        sorti = _strip_html_comments(texte)
        assert "ligne un" not in sorti and "ligne deux" not in sorti
        assert "Utile" in sorti and "Encore utile" in sorti

    def test_plusieurs_commentaires_disparaissent(self):
        assert "x" not in _strip_html_comments("<!--x--> a <!--x--> b <!--x-->")

    def test_un_texte_sans_commentaire_garde_sa_forme(self):
        assert _strip_html_comments("- Prénom : Carlito") == "- Prénom : Carlito"

    def test_un_fichier_entierement_commente_devient_vide(self):
        assert _strip_html_comments("<!-- rien que ça -->") == ""


def test_la_note_editoriale_de_user_md_n_atteint_pas_le_modele(tmp_path):
    """Le cas réel, tel qu'il est livré."""
    b = _constructeur(
        tmp_path,
        "# Utilisateur\n\n- Prénom : Carlito.\n\n"
        "<!-- Ce fichier est à vous : ajoutez ici tout ce que Diapason doit\n"
        "     savoir. Il est lu à chaque session. -->\n",
    )
    prompt = b.build()
    assert "Carlito" in prompt
    assert "<!--" not in prompt
    assert "Ce fichier est à vous" not in prompt, (
        "une consigne adressée à l'auteur devenait une consigne à l'assistant"
    )


def test_le_profil_reste_lisible_apres_nettoyage(tmp_path):
    b = _constructeur(tmp_path, "<!-- note -->\n- Langue : français.\n<!-- fin -->")
    prompt = b.build()
    assert "- Langue : français." in prompt
    assert "## User Profile" in prompt
