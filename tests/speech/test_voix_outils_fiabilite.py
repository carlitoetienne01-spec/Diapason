"""Le tour vocal qui porte des outils doit être refroidi.

La voix disait « J'ai bien noté ta préférence » sans rien écrire — le mensonge
exact corrigé pour le chat le même jour, mais par une cause différente.

Le prompt vocal se termine par « Keep answers short and spoken ». Cette règle,
nécessaire à la parole, pousse activement CONTRE l'action : le modèle préfère
répondre vite que regarder. Mesuré sur qwen3.5:9b avec le prompt vocal complet,
six essais par palier, sur « retiens que… » et « mes tâches ? » :

    défaut d'Ollama (0,8)   3/6
    0,3                     4/6
    0,1                   6/6 et 5/6
"""

from __future__ import annotations

from diapason.speech.realtime.local_voice import (
    VOICE_TOOL_TURN_TEMPERATURE,
    LocalVoiceSession,
)


def test_la_temperature_des_tours_outilles_est_basse():
    assert VOICE_TOOL_TURN_TEMPERATURE <= 0.15, (
        "au-dessus, le modèle préfère répondre vite que regarder"
    )


def test_la_regle_orale_dit_que_la_brievete_ne_dispense_pas_d_agir():
    """Sans cette phrase, « court » se lit comme « n'appelle rien »."""
    session = LocalVoiceSession.__new__(LocalVoiceSession)
    session._instructions = "PERSONA"
    session._language = "français"
    session._enable_tools = True
    prompt = session._system_prompt()
    bas = prompt.lower()
    assert "brevity governs what you say" in bas
    assert "never whether you act" in bas
    assert "call the tool first" in bas


def test_la_regle_orale_garde_ses_interdits_de_mise_en_forme():
    """Ces mots sont LUS À VOIX HAUTE : le formatage y devient du charabia."""
    session = LocalVoiceSession.__new__(LocalVoiceSession)
    session._instructions = "PERSONA"
    session._language = "français"
    session._enable_tools = True
    bas = session._system_prompt().lower()
    for interdit in ("emojis", "markdown", "bullet points"):
        assert interdit in bas


def test_le_persona_du_serveur_survit_aux_regles_orales():
    """La régression documentée dans le fichier : les instructions écrasaient tout."""
    session = LocalVoiceSession.__new__(LocalVoiceSession)
    session._instructions = "SOUL-ET-MEMOIRE"
    session._language = "français"
    session._enable_tools = True
    assert "SOUL-ET-MEMOIRE" in session._system_prompt()


class TestTrousseVocale:
    """Ce que la voix pouvait faire, et ce qui lui manquait."""

    def test_elle_sait_lire_l_heure(self):
        from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS

        assert "current_time" in DEFAULT_VOICE_TOOL_IDS, (
            "le modèle réclamait current_time et recevait « not allowed »"
        )

    def test_elle_sait_retenir(self):
        from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS

        assert "memory_manage" in DEFAULT_VOICE_TOOL_IDS
        assert "user_profile_manage" in DEFAULT_VOICE_TOOL_IDS

    def test_elle_ne_sait_toujours_pas_supprimer(self):
        """Une phrase mal comprise ne doit pas pouvoir effacer une tâche."""
        from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS

        for dangereux in (
            "succes_delete_task",
            "succes_delete_item",
            "shell_exec",
            "file_write",
        ):
            assert dangereux not in DEFAULT_VOICE_TOOL_IDS
