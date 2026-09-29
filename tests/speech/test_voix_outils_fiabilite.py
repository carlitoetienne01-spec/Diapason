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


def test_la_voix_finit_la_phrase_puis_la_reponse():
    """29/09/2026 : « une à trois phrases » coupait la réponse demandée.

    Appelant : LocalVoiceSession._system_prompt. Pas de route.
    Carlito : terminer les trois qui restent, dont la voix qui coupe.
    """
    session = LocalVoiceSession.__new__(LocalVoiceSession)
    session._instructions = "PERSONA"
    session._language = "français"
    session._enable_tools = True
    session._conversation_seule = False
    bas = session._system_prompt().lower()
    assert "one to three sentences" not in bas
    assert "finish every sentence" in bas
    assert "never stop in the middle of a sentence" in bas
    session._conversation_seule = True
    seule = session._system_prompt().lower()
    assert "une ou deux phrases" not in seule
    assert "ne t'arrête pas au milieu d'une phrase" in seule


def test_une_phrase_coupee_par_le_budget_reprend():
    from diapason.speech.realtime.local_voice import continuer_la_phrase

    assert continuer_la_phrase("length", "Il fait 18", 0) is True
    assert continuer_la_phrase("length", "Il fait 18 °C.", 0) is False
    assert continuer_la_phrase("stop", "Il fait 18", 0) is False, (
        "un arrêt choisi n'est pas une phrase coupée par le budget"
    )
    assert continuer_la_phrase("length", "Il fait 18", 8) is False


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

    def test_la_suppression_succes_est_offerte_mais_jamais_libre(self):
        """Demandé le 23 août 2026 : supprimer à la voix, dans Diapason
        seulement. Le garde-fou n'est plus l'absence de l'outil mais la
        cloche : chacun des trois déclare requires_confirmation, et une
        phrase mal comprise s'arrête donc à l'accord, pas à l'acte."""
        # Le conftest vide ToolRegistry et l'import mis en cache ne le
        # repeuple pas : on inscrit les classes soi-même, comme partout.
        from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS
        from diapason.tools.vie_continuity import VieDeleteContinuityTool
        from diapason.tools.vie_tasks import VieDeleteTaskTool
        from diapason.tools.vie_workspace import VieDeleteItemTool

        classes = {
            "vie_delete_task": VieDeleteTaskTool,
            "vie_delete_item": VieDeleteItemTool,
            "vie_delete_continuity": VieDeleteContinuityTool,
        }
        for nom, classe in classes.items():
            assert nom in DEFAULT_VOICE_TOOL_IDS
            assert classe().spec.requires_confirmation is True, (
                f"{nom} sans confirmation : une phrase mal comprise effacerait"
            )

    def test_le_disque_et_l_envoi_de_code_restent_hors_de_portee(self):
        """« Supprimer » ne vaut QUE dans Diapason — jamais sur le disque."""
        from diapason.speech.realtime.tools import DEFAULT_VOICE_TOOL_IDS

        interdits = ("shell_exec", "file_write", "apply_patch", "docker_shell_exec")
        for dangereux in interdits:
            assert dangereux not in DEFAULT_VOICE_TOOL_IDS
