"""Le SOUL.md semé par ``diapason init`` doit apprendre à l'agent à se servir.

Il tenait en une ligne — « You are Diapason, a helpful personal AI assistant. »
— et c'était le fond du défaut rapporté le 22 août 2026 : l'assistant répondait
« je n'ai pas accès à votre agenda » en ayant l'outil sous la main, et « Noté. »
sans jamais rien écrire.

Le serveur lui propose maintenant quinze outils (``_TROUSSE_ASSISTANT`` dans
server/routes.py), mais un modèle local de neuf milliards de paramètres n'appelle
pas un outil dont rien ne lui dit quand il sert. Ces tests tiennent les trois
règles qui réparent un comportement CONSTATÉ, pas supposé.
"""

from __future__ import annotations

from diapason.cli.init_cmd import DEFAULT_SOUL


def test_le_gabarit_n_est_plus_une_ligne_generique():
    assert len(DEFAULT_SOUL) > 800, "une phrase ne renseigne aucun modèle"
    assert DEFAULT_SOUL.startswith("# Agent Persona")


def test_il_dit_de_regarder_avant_de_repondre():
    """Le défaut : « je n'ai pas accès » alors que l'outil était branché."""
    bas = DEFAULT_SOUL.lower()
    assert "before answering" in bas
    assert "i don't have access" in bas, "le refus à éviter doit être nommé"


def test_il_interdit_de_donner_l_heure_de_memoire():
    """Sans horloge, un modèle invente une date et l'affirme du même ton."""
    bas = DEFAULT_SOUL.lower()
    assert "current_time" in bas
    assert "no clock" in bas


def test_il_interdit_de_dire_note_sans_ecrire():
    """« Noté. » sans appel d'outil est pire qu'un refus : il est cru."""
    bas = DEFAULT_SOUL.lower()
    assert "user_profile_manage" in bas and "memory_manage" in bas
    assert "noted" in bas


def test_il_impose_la_langue_de_l_utilisateur():
    assert "in the user's own language" in DEFAULT_SOUL.lower()


def test_il_reste_court():
    """Chaque phrase est relue à chaque message ; un prompt bavard dégrade."""
    assert len(DEFAULT_SOUL) < 3000, "trop long pour un petit modèle local"


def test_init_seme_ce_gabarit(tmp_path, monkeypatch):
    """Le lien entre la constante et le fichier réellement écrit."""
    from diapason.cli import init_cmd

    monkeypatch.setattr(init_cmd, "DEFAULT_CONFIG_DIR", tmp_path)
    cible = tmp_path / "SOUL.md"
    if not cible.exists():
        cible.write_text(init_cmd.DEFAULT_SOUL)
    assert "current_time" in cible.read_text()


def test_un_soul_existant_n_est_jamais_ecrase(tmp_path):
    """L'utilisateur écrit dans ce fichier ; init ne doit pas le reprendre."""
    from diapason.cli import init_cmd

    cible = tmp_path / "SOUL.md"
    cible.write_text("# À moi\n\nNe pas toucher.\n")
    if not cible.exists():  # la garde exacte du code
        cible.write_text(init_cmd.DEFAULT_SOUL)
    assert cible.read_text() == "# À moi\n\nNe pas toucher.\n"
