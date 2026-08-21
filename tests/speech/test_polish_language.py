"""Le polissage corrige la dictée ; il ne la traduit pas.

Constaté sur la machine : « ouvre readme point md » revenait « Open README.md ».
Le garde de fidélité existant compte des caractères, et une traduction fait la
même longueur que l'original — il ne pouvait pas la voir passer.
"""

from typing import Any, Optional

import pytest

from diapason.speech.llm_polish import (
    _DICTATION_SYSTEM,
    _MARQUEURS_EN,
    _MARQUEURS_FR,
    _langue_conservee,
    _profil_langue,
    llm_polish_text,
)


class FauxMoteur:
    """Un moteur local qui rend exactement ce qu'on lui a dit de rendre."""

    engine_id = "ollama"

    def __init__(self, sortie: str) -> None:
        self.sortie = sortie
        self.appels: list[Any] = []

    def generate(self, messages: Any, **kwargs: Any) -> dict:
        self.appels.append(messages)
        return {"content": self.sortie}


def _polir(brut: str, sortie: str) -> Optional[str]:
    # Modèle explicite : sans lui, le test dépendait du modèle par défaut de la
    # configuration ambiante. Il passait donc pour une raison incidente, et
    # échouait dès qu'une autre suite laissait une configuration sans modèle —
    # « llm polish skipped: no default model », constaté en enchaînant
    # tests/desktop puis tests/speech.
    return llm_polish_text(
        brut, engine=FauxMoteur(sortie), timeout_ms=4000, model="modele-de-test"
    )


# --- le basculement de langue est refusé ---------------------------------


@pytest.mark.parametrize(
    "brut, traduit",
    [
        ("ouvre readme point md", "Open README.md"),
        ("ouvre le fichier", "Open the file"),
        ("envoie lui le rapport demain", "Send him the report tomorrow"),
        ("je regarde ca ce soir", "I will look at this tonight"),
    ],
)
def test_traduction_francais_vers_anglais_refusee(brut: str, traduit: str) -> None:
    assert _langue_conservee(brut, traduit) is False


@pytest.mark.parametrize(
    "brut, traduit",
    [
        ("open the file please", "Ouvre le fichier"),
        ("send it to him tomorrow", "Envoie-le-lui demain"),
    ],
)
def test_traduction_anglais_vers_francais_refusee(brut: str, traduit: str) -> None:
    """Le garde refuse un basculement, pas une langue : l'anglais aussi est protégé."""
    assert _langue_conservee(brut, traduit) is False


# --- les vraies corrections passent --------------------------------------


@pytest.mark.parametrize(
    "brut, corrige",
    [
        ("c est bon merci", "C'est bon, merci."),
        ("envoie lui ca", "Envoie-lui ça."),
        ("je pense qu il faut revoir ca", "Je pense qu'il faut revoir ça."),
        ("demain 4h non 5h", "Demain, 5h."),
        ("ouvre readme point md", "Ouvre readme.md"),
    ],
)
def test_correction_francaise_conservee(brut: str, corrige: str) -> None:
    assert _langue_conservee(brut, corrige) is True


def test_dictee_anglaise_polie_en_anglais_conservee() -> None:
    assert _langue_conservee("open the file please", "Open the file, please.") is True


def test_texte_sans_marqueur_accepte_par_defaut() -> None:
    """Dans le doute on accepte : refuser à tort ne coûte qu'un texte non poli."""
    assert _langue_conservee("readme md", "readme.md") is True


def test_accents_seuls_suffisent_comme_indice_francais() -> None:
    """Sur un texte très court, les listes de mots ne captent rien : l'accent, si."""
    fr, en = _profil_langue("ça")
    assert fr > en


def test_elision_compte_comme_indice_francais() -> None:
    fr, en = _profil_langue("qu'il l'a dit")
    assert fr > en


# --- invariants ----------------------------------------------------------


def test_aucun_mot_ne_plaide_des_deux_cotes() -> None:
    """Un mot présent dans les deux listes ne départagerait rien."""
    assert _MARQUEURS_FR & _MARQUEURS_EN == frozenset()


@pytest.mark.parametrize("brut, corrige", [("", ""), ("", "x"), ("x", "")])
def test_le_garde_ne_leve_jamais(brut: str, corrige: str) -> None:
    """Un diagnostic qui plante empêcherait toute dictée : il doit encaisser."""
    assert isinstance(_langue_conservee(brut, corrige), bool)


# --- branché à la source, donc valable pour tous les appelants -----------


def test_polissage_rejette_une_traduction_et_garde_le_brut() -> None:
    assert _polir("ouvre le fichier et regarde", "Open the file and look") is None


def test_polissage_rend_une_correction_de_meme_langue() -> None:
    assert _polir("c est bon merci beaucoup", "C'est bon, merci beaucoup.") == (
        "C'est bon, merci beaucoup."
    )


def test_le_prompt_interdit_explicitement_la_traduction() -> None:
    """Le prompt seul ne suffit pas — mesuré — mais son silence était une cause."""
    bas = _DICTATION_SYSTEM.lower()
    assert "same language" in bas
    assert "never translate" in bas
