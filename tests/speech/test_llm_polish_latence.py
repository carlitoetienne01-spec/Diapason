"""Le délai du polissage doit être RÉEL, et les longues phrases exemptées.

Mesuré le 23 août 2026 : délai demandé 1 s, durée réelle 8,2 s — la sortie du
« with ThreadPoolExecutor » attendait la fin de la génération même après
l'expiration. Sur un Ollama à créneau unique occupé, la dictée restait
suspendue derrière la file : pour l'utilisateur, « les phrases longues ne
s'écrivent pas ».

Et cinquante-huit mots prennent 4,0 s à régénérer modèle CHAUD — tout le
budget avant le moindre aléa : tenter, c'est garantir l'expiration.
"""

from __future__ import annotations

import time

from diapason.speech.llm_polish import llm_polish_text


class _MoteurLent:
    engine_id = "ollama"
    is_cloud = False

    def __init__(self, sommeil: float) -> None:
        self._sommeil = sommeil
        self.appels = 0

    def generate(self, *args, **kwargs):
        self.appels += 1
        time.sleep(self._sommeil)
        return {"content": "peu importe"}


def test_le_delai_est_respecte_meme_si_le_moteur_traine():
    moteur = _MoteurLent(sommeil=5.0)
    debut = time.time()
    rendu = llm_polish_text(
        "une phrase courte à polir sans se presser",
        timeout_ms=400,
        engine=moteur,
        model="x",
    )
    duree = time.time() - debut
    assert rendu is None, "à l'expiration, le brut doit être gardé"
    assert duree < 2.0, (
        f"le délai était factice : {duree:.1f}s réels pour 0,4s demandés — "
        "la dictée attendait la fin de la génération"
    )


def test_une_longue_phrase_ne_consulte_jamais_le_modele():
    """Elle ne peut pas tenir le budget : la tenter brûle quatre secondes
    pour coller le brut qu'on aurait pu coller tout de suite."""
    moteur = _MoteurLent(sommeil=0.0)
    debut = time.time()
    rendu = llm_polish_text(
        " ".join(["mot"] * 58), timeout_ms=4000, engine=moteur, model="x"
    )
    assert rendu is None
    assert moteur.appels == 0, "le moteur ne doit même pas être consulté"
    assert time.time() - debut < 0.5


def test_une_phrase_courte_est_toujours_polie():
    class MoteurVif:
        engine_id = "ollama"
        is_cloud = False

        def generate(self, *args, **kwargs):
            return {"content": "Bonjour, comment vas-tu aujourd'hui ?"}

    rendu = llm_polish_text(
        "bonjour comment vas tu aujourd hui",
        timeout_ms=4000,
        engine=MoteurVif(),
        model="x",
    )
    assert rendu == "Bonjour, comment vas-tu aujourd'hui ?"
