"""La voix relie et décrit les branches (§82) — chantier réseau, 18 sept. 2026.

Jusque-là `succes_tasks` ne connaissait pas les arêtes : la souris était
l'unique chemin pour relier, délier ou savoir ce qu'une tâche attend. Les
tests ci-dessous rejouent AgriCulture (7 tâches, 5 arêtes) et vérifient ce
qui pourrait mentir : une boucle acceptée en silence, un titre ambigu deviné,
une phrase qui cite la demande au lieu de l'état du serveur.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from diapason.succes.store import SuccesError
from diapason.succes.sync import SuccesSyncStore
from diapason.tools.succes_tasks import SuccesTasksTool

# La même fixture que tests/succes/test_reseau.py et reseau.test.ts :
#   agriculteurs → discuter → contrat
#   riz → besoin → budget
#                → tracteur
AGRI = [
    ("tracteur", "Avoir besoin d’un tracteur"),
    ("agri", "Avoir les bons agriculteurs pour le projet"),
    ("budget", "Avoir un budget bien detaillé ?"),
    ("contrat", "Contrat | Paiement par jours de travail ou commission"),
    ("discuter", "Discuter du contrat avec les agriculteurs"),
    ("riz", "Qu’est ce que nou allons commencer avec en premier | Riz ou Haricots ?"),
    ("besoin", "Qu’est-ce qu’on aura besoin en premier ?"),
]
ARETES = [
    ("agri", "discuter"),
    ("discuter", "contrat"),
    ("besoin", "budget"),
    ("riz", "besoin"),
    ("besoin", "tracteur"),
]


def peupler(store: SuccesSyncStore) -> str:
    projet = store.create_project(
        {"id": "agri-p", "name": "AgriCulture", "structure": "network"}
    )
    for tid, titre in AGRI:
        store.create_task({"id": tid, "title": titre, "projectId": projet["id"]})
    for de, vers in ARETES:
        store.create_task_edge(projet["id"], de, vers)
    return projet["id"]


@pytest.fixture
def store() -> SuccesSyncStore:
    return SuccesSyncStore(pathlib.Path(tempfile.mkdtemp()) / "succes.db")


@pytest.fixture
def outil(store: SuccesSyncStore) -> SuccesTasksTool:
    peupler(store)
    return SuccesTasksTool(store)


class TestRelier:
    def test_link_refuse_une_boucle_avec_la_phrase_du_serveur(
        self, outil: SuccesTasksTool, store: SuccesSyncStore
    ) -> None:
        """Test fusible : « contrat → agriculteurs » fermerait la boucle
        agri → discuter → contrat → agri. Le refus vient de
        `create_task_edge`, mot pour mot, et rien n'est écrit."""
        avant = store.list_task_edges("agri-p")
        with pytest.raises(SuccesError) as refus:
            store.create_task_edge("agri-p", "contrat", "agri")
        resultat = outil.execute(
            action="link",
            project="AgriCulture",
            from_task="Contrat | Paiement par jours de travail ou commission",
            to_task="Avoir les bons agriculteurs pour le projet",
        )
        assert resultat.success is False
        assert resultat.content == str(refus.value), (
            "la phrase de la boucle doit remonter telle quelle, pas paraphrasée"
        )
        assert "boucle" in resultat.content
        assert resultat.metadata["persistence"] == "unchanged"
        assert store.list_task_edges("agri-p") == avant

    def test_link_cite_l_arete_renvoyee_par_le_serveur(
        self, outil: SuccesTasksTool, store: SuccesSyncStore
    ) -> None:
        """§100 : la phrase vient de l'arête rendue et de l'état relu."""
        resultat = outil.execute(
            action="link",
            project="AgriCulture",
            from_task="Avoir un budget",
            to_task="tracteur",
        )
        assert resultat.success is True, resultat.content
        arete = resultat.metadata["edge"]
        assert (arete["fromTaskId"], arete["toTaskId"]) == ("budget", "tracteur")
        assert arete["updatedAtMs"] > 0
        assert resultat.metadata["alreadyExisted"] is False
        assert resultat.content.startswith(
            "Lien créé : « Avoir un budget bien detaillé ? » débloque "
            "« Avoir besoin d’un tracteur »."
        )
        assert "est maintenant bloquée" in resultat.content
        assert ("budget", "tracteur") in {
            (e["fromTaskId"], e["toTaskId"]) for e in store.list_task_edges("agri-p")
        }

    def test_un_lien_qui_existait_deja_est_dit_tel_quel(
        self, outil: SuccesTasksTool
    ) -> None:
        """Le serveur rend l'arête existante sans op : « créé » mentirait."""
        resultat = outil.execute(
            action="link",
            project="AgriCulture",
            from_task="riz",
            to_task="Qu’est-ce qu’on aura besoin en premier ?",
        )
        assert resultat.success is True
        assert resultat.metadata["alreadyExisted"] is True
        assert resultat.content.startswith("Ce lien existait déjà")

    def test_deux_titres_ambigus_font_demander(self, outil: SuccesTasksTool) -> None:
        """§34 : « contrat » désigne « Discuter du contrat… » ET « Contrat |
        Paiement… ». Deviner relierait la mauvaise."""
        # « Contrat » et non « contrat » : ici les ids de la fixture sont
        # des mots, et un id exact l'emporte toujours sur un titre.
        resultat = outil.execute(
            action="link", project="AgriCulture", from_task="Contrat", to_task="riz"
        )
        assert resultat.success is False
        assert "Plusieurs tâches correspondent à « Contrat »" in resultat.content
        assert "Discuter du contrat avec les agriculteurs" in resultat.content
        assert "Contrat | Paiement" in resultat.content
        assert "Demandez" in resultat.content

    def test_un_titre_entier_l_emporte_sur_le_fragment(
        self, outil: SuccesTasksTool
    ) -> None:
        """Dire le titre en entier ne doit pas être puni par l'ambiguïté du
        fragment qu'il contient."""
        resultat = outil.execute(
            action="branches",
            project="AgriCulture",
            task="Discuter du contrat avec les agriculteurs",
        )
        assert resultat.success is True, resultat.content
        assert resultat.metadata["task"]["id"] == "discuter"

    def test_un_titre_inconnu_est_refuse(self, outil: SuccesTasksTool) -> None:
        resultat = outil.execute(
            action="link", project="AgriCulture", from_task="riz", to_task="licorne"
        )
        assert resultat.success is False
        assert "licorne" in resultat.content

    def test_un_projet_inconnu_est_refuse(self, outil: SuccesTasksTool) -> None:
        resultat = outil.execute(action="next_actions", project="Lunaire")
        assert resultat.success is False
        assert "Lunaire" in resultat.content

    def test_unlink_ne_dit_supprime_qu_apres_relecture(
        self, outil: SuccesTasksTool, store: SuccesSyncStore
    ) -> None:
        resultat = outil.execute(
            action="unlink", project="AgriCulture", from_task="riz", to_task="besoin"
        )
        assert resultat.success is True, resultat.content
        assert ("riz", "besoin") not in {
            (e["fromTaskId"], e["toTaskId"]) for e in store.list_task_edges("agri-p")
        }
        assert len(store.list_task_edges("agri-p")) == len(ARETES) - 1
        encore = outil.execute(
            action="unlink", project="AgriCulture", from_task="riz", to_task="besoin"
        )
        assert encore.success is False, "délier un lien absent n'est pas un succès"


class TestDecrire:
    def test_branches_dit_ce_que_besoin_attend_et_debloque(
        self, outil: SuccesTasksTool
    ) -> None:
        resultat = outil.execute(
            action="branches", project="AgriCulture", task="besoin en premier"
        )
        assert resultat.success is True, resultat.content
        assert resultat.content == (
            "« Qu’est-ce qu’on aura besoin en premier ? » est bloquée. Attend "
            "« Qu’est ce que nou allons commencer avec en premier | Riz ou "
            "Haricots ? ». Débloque « Avoir besoin d’un tracteur » et « Avoir un "
            "budget bien detaillé ? ». La terminer ouvre « Avoir besoin d’un "
            "tracteur » et « Avoir un budget bien detaillé ? ». 2 tâches "
            "ouvertes en aval."
        )
        assert resultat.metadata["status"] == "blocked"
        assert [t["id"] for t in resultat.metadata["missing"]] == ["riz"]

    def test_branches_relit_l_etat_apres_la_coche(
        self, outil: SuccesTasksTool, store: SuccesSyncStore
    ) -> None:
        store.set_task_done("agri", True)
        resultat = outil.execute(
            action="branches", project_id="agri-p", task="discuter"
        )
        assert resultat.success is True
        assert resultat.content.startswith(
            "« Discuter du contrat avec les agriculteurs » est faisable maintenant. "
            "Ses attentes sont toutes faites."
        )

    def test_next_actions_la_plus_utile_d_abord(self, outil: SuccesTasksTool) -> None:
        resultat = outil.execute(action="next_actions", project="agriculture")
        assert resultat.success is True, resultat.content
        assert [a["id"] for a in resultat.metadata["nextActions"]] == ["riz", "agri"]
        assert resultat.content.startswith(
            "Faisable maintenant dans « AgriCulture », la plus utile d'abord : "
            "« Qu’est ce que nou allons commencer avec en premier | Riz ou "
            "Haricots ? » (débloque « Qu’est-ce qu’on aura besoin en premier ? ») ; "
            "« Avoir les bons agriculteurs pour le projet » (débloque "
            "« Discuter du contrat avec les agriculteurs »)."
        )

    def test_next_actions_dit_quand_rien_n_est_faisable(
        self, outil: SuccesTasksTool, store: SuccesSyncStore
    ) -> None:
        for tid in (
            "riz",
            "agri",
            "besoin",
            "budget",
            "tracteur",
            "discuter",
            "contrat",
        ):
            store.set_task_done(tid, True)
        resultat = outil.execute(action="next_actions", project="AgriCulture")
        assert resultat.success is True
        assert resultat.metadata["nextActions"] == []
        assert "Rien n'est faisable maintenant" in resultat.content

    def test_le_schema_expose_les_quatre_actions(self, outil: SuccesTasksTool) -> None:
        actions = outil.spec.parameters["properties"]["action"]["enum"]
        assert {"link", "unlink", "branches", "next_actions"} <= set(actions)
