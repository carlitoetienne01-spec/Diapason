"""Les branches d'un réseau, côté serveur — miroir de `reseau.test.ts`.

Chantier réseau du 18 septembre 2026. Le serveur refusait la boucle mais ne
calculait rien de dérivé : la voix ne pouvait ni dire ce qu'une tâche attend
ni ce qu'elle débloque. Chaque test rejoue la fixture AgriCulture telle
qu'elle est dans ~/.diapason/succes.db (7 tâches ouvertes, 5 arêtes) et
attend la MÊME réponse que le module TypeScript.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from diapason.succes.reseau import (
    ce_que_debloque,
    chaine,
    cle_titre,
    construire_reseau,
    faisables,
    impact,
    statut_de,
    voisines_ordonnees,
)
from diapason.succes.store import SuccesNotFound
from diapason.succes.sync import SuccesSyncStore

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


def _taches(faites: set[str] = frozenset()) -> list[dict]:
    return [{"id": i, "title": t, "done": i in faites} for i, t in AGRI]


def _aretes() -> list[dict]:
    return [{"fromTaskId": d, "toTaskId": v} for d, v in ARETES]


def agriculture(faites: set[str] = frozenset()):
    return construire_reseau(_taches(faites), _aretes())


@pytest.fixture
def store() -> SuccesSyncStore:
    return SuccesSyncStore(pathlib.Path(tempfile.mkdtemp()) / "succes.db")


def peupler(store: SuccesSyncStore) -> str:
    """AgriCulture dans une vraie base, ids identiques à la fixture."""
    projet = store.create_project(
        {"id": "agri-p", "name": "AgriCulture", "structure": "network"}
    )
    for tid, titre in AGRI:
        store.create_task({"id": tid, "title": titre, "projectId": projet["id"]})
    for de, vers in ARETES:
        store.create_task_edge(projet["id"], de, vers)
    return projet["id"]


class TestLeModulePur:
    def test_une_arete_dont_un_bout_n_existe_plus_est_ecartee(self) -> None:
        reseau = construire_reseau(
            _taches(), _aretes() + [{"fromTaskId": "agri", "toTaskId": "fantome"}]
        )
        assert reseau.aval["agri"] == ["discuter"], "un fantôme n'est pas une attente"

    def test_deux_faisables_cinq_bloquees_aucune_faite(self) -> None:
        reseau = agriculture()
        statuts = {i: statut_de(reseau, i) for i, _ in AGRI}
        assert statuts["agri"] == "feasible"
        assert statuts["riz"] == "feasible"
        assert statuts["discuter"] == "blocked"
        assert list(statuts.values()).count("blocked") == 5

    def test_une_tache_faite_ne_bloque_plus_ce_qu_elle_debloquait(self) -> None:
        reseau = agriculture({"agri"})
        assert statut_de(reseau, "agri") == "done"
        assert statut_de(reseau, "discuter") == "feasible"
        assert statut_de(reseau, "contrat") == "blocked"

    def test_une_tache_inconnue_est_traitee_comme_faite(self) -> None:
        assert statut_de(agriculture(), "nulle-part") == "done", (
            "sinon une arête vers une tâche disparue bloquerait à jamais"
        )

    def test_besoin_attend_riz_et_debloque_budget_et_tracteur(self) -> None:
        reseau = agriculture()
        assert voisines_ordonnees(reseau, "besoin", "amont") == ["riz"]
        assert voisines_ordonnees(reseau, "besoin", "aval") == ["tracteur", "budget"]

    def test_contrat_remonte_toute_sa_chaine(self) -> None:
        assert chaine(agriculture(), "contrat", "amont") == [
            ("discuter", 1),
            ("agri", 2),
        ]
        assert chaine(agriculture(), "contrat", "aval") == []

    def test_la_chaine_indente_par_profondeur_et_ne_repasse_jamais(self) -> None:
        assert chaine(agriculture(), "riz", "aval") == [
            ("besoin", 1),
            ("tracteur", 2),
            ("budget", 2),
        ]
        boucle = construire_reseau(
            [{"id": "t1", "title": "un"}, {"id": "t2", "title": "deux"}],
            [
                {"fromTaskId": "t1", "toTaskId": "t2"},
                {"fromTaskId": "t2", "toTaskId": "t1"},
            ],
        )
        assert chaine(boucle, "t1", "aval") == [("t2", 1)], (
            "une boucle relayée par un pair ne doit pas tourner sans fin"
        )

    def test_une_attente_faite_passe_apres_les_ouvertes(self) -> None:
        reseau = construire_reseau(
            [
                {"id": "a", "title": "zèbre", "done": True},
                {"id": "b", "title": "âne"},
                {"id": "c", "title": "cible"},
            ],
            [
                {"fromTaskId": "a", "toTaskId": "c"},
                {"fromTaskId": "b", "toTaskId": "c"},
            ],
        )
        assert voisines_ordonnees(reseau, "c", "amont") == ["b", "a"]

    def test_cocher_agriculteurs_ouvre_discuter(self) -> None:
        assert ce_que_debloque(agriculture({"agri"}), "agri") == ["discuter"]

    def test_rien_n_est_annonce_quand_une_autre_attente_reste_ouverte(self) -> None:
        reseau = construire_reseau(
            [
                {"id": "a", "title": "a", "done": True},
                {"id": "b", "title": "b"},
                {"id": "c", "title": "c"},
            ],
            [
                {"fromTaskId": "a", "toTaskId": "c"},
                {"fromTaskId": "b", "toTaskId": "c"},
            ],
        )
        assert ce_que_debloque(reseau, "a") == []

    def test_riz_pese_trois_taches_agriculteurs_deux_tracteur_rien(self) -> None:
        reseau = agriculture()
        assert impact(reseau, "riz") == 3
        assert impact(reseau, "agri") == 2
        assert impact(reseau, "tracteur") == 0

    def test_l_impact_ne_compte_pas_les_taches_faites_en_aval(self) -> None:
        reseau = construire_reseau(
            [
                {"id": "a", "title": "a"},
                {"id": "b", "title": "b", "done": True},
                {"id": "c", "title": "c"},
            ],
            [
                {"fromTaskId": "a", "toTaskId": "b"},
                {"fromTaskId": "b", "toTaskId": "c"},
            ],
        )
        assert impact(reseau, "a") == 1

    def test_les_faisables_se_lisent_par_ce_qu_elles_liberent(self) -> None:
        assert faisables(agriculture()) == ["riz", "agri"], (
            "« riz » (3) avant « agriculteurs » (2), jamais l'alphabet"
        )

    def test_a_impact_egal_les_faisables_se_lisent_par_titre_francais(self) -> None:
        reseau = construire_reseau(
            [
                {"id": "z", "title": "zèbre"},
                {"id": "a", "title": "âne"},
                {"id": "c", "title": "cible"},
            ],
            [
                {"fromTaskId": "z", "toTaskId": "c"},
                {"fromTaskId": "a", "toTaskId": "c"},
            ],
        )
        assert faisables(reseau) == ["a", "z"], (
            "« âne » avant « zèbre » : par points de code, « â » passe après « z »"
        )
        assert cle_titre("Éléphant") == "elephant"


class TestLesBranchesDansLeMagasin:
    """`branches_de` et `prochaines_actions` lisent la base, jamais la demande."""

    def test_les_taches_d_un_projet_ne_melangent_pas_les_autres(
        self, store: SuccesSyncStore
    ) -> None:
        pid = peupler(store)
        store.create_task({"title": "Avoir un budget", "projectId": ""})
        assert len(store.list_project_tasks(pid)) == 7, (
            "un titre voisin d'une autre liste entrait dans la résolution"
        )

    def test_besoin_attend_riz_debloque_deux_et_pese_deux(
        self, store: SuccesSyncStore
    ) -> None:
        pid = peupler(store)
        b = store.branches_de(pid, "besoin")
        assert b["status"] == "blocked"
        assert [t["id"] for t in b["upstream"]] == ["riz"]
        assert [t["id"] for t in b["missing"]] == ["riz"]
        assert [t["id"] for t in b["downstream"]] == ["tracteur", "budget"]
        assert [(t["id"], t["depth"]) for t in b["upstreamAll"]] == [("riz", 1)]
        assert b["impact"] == 2
        assert [t["id"] for t in b["unlocks"]] == ["tracteur", "budget"], (
            "terminer « besoin » ouvre ses deux successeures : rien ne les retient"
        )

    def test_contrat_remonte_deux_crans_et_ne_debloque_rien(
        self, store: SuccesSyncStore
    ) -> None:
        pid = peupler(store)
        b = store.branches_de(pid, "contrat")
        assert [(t["id"], t["depth"]) for t in b["upstreamAll"]] == [
            ("discuter", 1),
            ("agri", 2),
        ]
        assert b["downstream"] == []
        assert b["impact"] == 0

    def test_les_branches_se_relisent_apres_la_coche(
        self, store: SuccesSyncStore
    ) -> None:
        """§100 : la réponse vient de l'état rechargé, pas de ce qu'on a demandé."""
        pid = peupler(store)
        store.set_task_done("agri", True)
        b = store.branches_de(pid, "discuter")
        assert b["status"] == "feasible"
        assert b["missing"] == []
        assert [t["id"] for t in b["unlocks"]] == ["contrat"]

    def test_une_tache_d_un_autre_projet_est_refusee(
        self, store: SuccesSyncStore
    ) -> None:
        pid = peupler(store)
        autre = store.create_task({"id": "ailleurs", "title": "Ailleurs"})
        with pytest.raises(SuccesNotFound):
            store.branches_de(pid, autre["id"])

    def test_prochaines_actions_riz_puis_agriculteurs(
        self, store: SuccesSyncStore
    ) -> None:
        pid = peupler(store)
        actions = store.prochaines_actions(pid)
        assert [a["id"] for a in actions] == ["riz", "agri"]
        assert actions[0]["impact"] == 3
        assert [t["id"] for t in actions[0]["unlocks"]] == ["besoin"]

    def test_tout_fait_ne_propose_rien(self, store: SuccesSyncStore) -> None:
        pid = peupler(store)
        for tid, _ in AGRI:
            store.set_task_done(tid, True)
        assert store.prochaines_actions(pid) == []
