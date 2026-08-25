"""Le briefing du matin : composé de données, jamais inventé.

La routine ``morning-digest`` demandait au modèle de RÉDIGER le briefing. Sur
une machine où Ollama n'a qu'un créneau, un briefing qui infère fait attendre —
et invente quand il se trompe. Or « trois tâches en retard depuis le 19 août,
dont une urgente » est une phrase que les données écrivent toutes seules.

Ces tests tiennent la composition, sans base ni agenda.
"""

from __future__ import annotations

from datetime import date

import pytest

from diapason.heartbeat.briefing import (
    MAX_LIGNES_PAR_SECTION,
    composer,
    date_en_francais,
)

JOUR = date(2026, 8, 22)  # un samedi


def _t(titre, *, date_prevue="", priorite="medium", done=False):
    return {"title": titre, "date": date_prevue, "priority": priorite, "done": done}


class TestDateFrancaise:
    def test_le_jour_et_le_mois_sont_en_francais(self):
        assert date_en_francais(JOUR) == "samedi 22 août"

    def test_aucun_mois_anglais(self):
        for mois in range(1, 13):
            rendu = date_en_francais(date(2026, mois, 1))
            assert not any(
                m in rendu for m in ("January", "August", "December", "Monday")
            )


class TestRien:
    def test_une_journee_vide_le_dit_en_une_ligne(self):
        """Meubler apprend à l'utilisateur à ne plus lire."""
        b = composer(jour=JOUR, prenom="Carlito")
        assert b.rien_a_signaler is True
        assert "Rien de prévu" in b.corps
        assert len(b.corps) < 120

    def test_une_tache_deja_cochee_ne_compte_pas(self):
        b = composer(jour=JOUR, taches_du_jour=[_t("Faite", done=True)])
        assert b.rien_a_signaler is True


class TestRetard:
    def test_le_retard_vient_en_premier(self):
        """C'est la seule chose qu'un briefing fait voir qu'on ne verrait pas."""
        b = composer(
            jour=JOUR,
            taches_du_jour=[_t("Prévue aujourd'hui")],
            taches_en_retard=[_t("Oubliée", date_prevue="2026-08-19")],
        )
        assert b.corps.index("en retard") < b.corps.index("aujourd'hui :")

    def test_l_anciennete_est_dite(self):
        b = composer(
            jour=JOUR, taches_en_retard=[_t("Vieille", date_prevue="2026-08-19")]
        )
        assert "depuis 3 jours" in b.corps

    @pytest.mark.parametrize(
        "prevue,attendu",
        [
            ("2026-08-21", "depuis hier"),
            ("2026-08-19", "depuis 3 jours"),
            ("2026-08-10", "depuis 1 semaine"),
            ("2026-08-01", "depuis 3 semaines"),
            ("2026-05-01", "depuis plus d'un mois"),
        ],
    )
    def test_l_anciennete_reste_lisible(self, prevue, attendu):
        b = composer(jour=JOUR, taches_en_retard=[_t("X", date_prevue=prevue)])
        assert attendu in b.corps

    def test_une_date_illisible_ne_casse_rien(self):
        b = composer(jour=JOUR, taches_en_retard=[_t("X", date_prevue="pas-une-date")])
        assert "X" in b.corps

    def test_l_urgent_est_signale_et_passe_devant(self):
        b = composer(
            jour=JOUR,
            taches_en_retard=[
                _t("Ordinaire", date_prevue="2026-08-01"),
                _t("Pressée", date_prevue="2026-08-21", priorite="urgent"),
            ],
        )
        assert "dont 1 urgente" in b.corps
        assert b.corps.index("Pressée") < b.corps.index("Ordinaire")

    def test_le_titre_annonce_le_retard(self):
        """C'est la ligne que porte une notification : elle doit trancher."""
        b = composer(
            jour=JOUR,
            taches_en_retard=[_t("A", date_prevue="2026-08-19")],
        )
        assert b.titre == "1 tâche en retard"


class TestLongueur:
    def test_une_longue_liste_est_ecourtee_en_le_disant(self):
        """Une notification illisible d'un coup d'œil n'est pas lue."""
        b = composer(
            jour=JOUR,
            taches_en_retard=[
                _t(f"Tâche {i}", date_prevue="2026-08-19") for i in range(12)
            ],
        )
        assert "et 7 autres" in b.corps
        assert b.corps.count("— Tâche") == MAX_LIGNES_PAR_SECTION
        assert "12 tâches en retard" in b.corps, "le compte total reste exact"

    def test_une_seule_de_trop_se_dit_au_singulier(self):
        b = composer(
            jour=JOUR,
            taches_en_retard=[
                _t(f"T{i}", date_prevue="2026-08-19")
                for i in range(MAX_LIGNES_PAR_SECTION + 1)
            ],
        )
        assert "et 1 autre" in b.corps and "autres" not in b.corps


class TestSections:
    def test_les_rendez_vous_paraissent_avec_leur_heure(self):
        b = composer(jour=JOUR, evenements=[{"title": "Dentiste", "start": "14:30"}])
        assert "14:30 Dentiste" in b.corps

    def test_les_habitudes_tiennent_sur_une_ligne(self):
        b = composer(jour=JOUR, habitudes_dues=[{"name": "Prier"}, {"name": "Marcher"}])
        assert "Habitudes du jour : Prier, Marcher." in b.corps

    def test_une_habitude_sans_nom_est_ignoree(self):
        b = composer(jour=JOUR, habitudes_dues=[{"name": ""}])
        assert b.rien_a_signaler is True

    def test_le_prenom_est_repris_quand_il_est_connu(self):
        assert "Bonjour Carlito." in composer(jour=JOUR, prenom="Carlito").corps

    def test_sans_prenom_la_salutation_reste_correcte(self):
        assert composer(jour=JOUR).corps.startswith("Bonjour. Nous sommes")
