"""La durée estimée en jours d'une tâche du réseau (chantier réseau, 18 sept. 2026).

Proposition 12 : sans durée, le réseau ne peut ni projeter une fin ni
distinguer la marge de « budget » de l'absence de marge de « paiement » ; mais
un « chemin critique » sans durée serait faire semblant (§5). La colonne
`estimate_days` porte un ENTIER de jours (règle 1 du CLAUDE.md : aucun
flottant dans une enveloppe signée), 0 signifiant « pas d'estimation ».
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.succes.routes import router, set_store_for_tests
from diapason.succes.store import SuccesError, SuccesStore
from diapason.succes.sync import SuccesSyncStore


class TestLaDureeDansLeMagasin:
    def test_une_tache_neuve_n_a_pas_d_estimation(self, tmp_path) -> None:
        store = SuccesStore(tmp_path / "succes.db")
        tache = store.create_task({"title": "Avoir un budget bien detaillé ?"})
        assert tache["estimateDays"] == 0, "0 = pas d'estimation, jamais un jour"

    def test_la_duree_se_pose_a_la_creation_et_par_retouche(self, tmp_path) -> None:
        store = SuccesStore(tmp_path / "succes.db")
        tache = store.create_task({"title": "Discuter du contrat", "estimateDays": 3})
        assert tache["estimateDays"] == 3
        apres = store.update_task(tache["id"], {"estimateDays": 5})
        assert apres["estimateDays"] == 5
        assert apres["title"] == "Discuter du contrat", (
            "retoucher la durée ne touche à rien d'autre"
        )
        retiree = store.update_task(tache["id"], {"estimateDays": 0})
        assert retiree["estimateDays"] == 0

    def test_la_duree_survit_a_la_fermeture(self, tmp_path) -> None:
        chemin = tmp_path / "succes.db"
        tache = SuccesStore(chemin).create_task(
            {"title": "Riz ou haricots", "estimateDays": 2}
        )
        relue = SuccesStore(chemin).get_task(tache["id"])
        assert relue["estimateDays"] == 2

    @pytest.mark.parametrize("valeur", [1.5, "deux", -1, 3651, True])
    def test_un_flottant_un_mot_un_negatif_ou_dix_ans_sont_refuses(
        self, tmp_path, valeur
    ) -> None:
        # Un demi-jour écrit `1.5` par Python et `1.5` par Dart, mais `1e-07`
        # contre `1e-7` dès qu'il est petit : aucun flottant ne passe.
        store = SuccesStore(tmp_path / "succes.db")
        with pytest.raises(SuccesError, match="durée estimée"):
            store.create_task({"title": "Tracteur", "estimateDays": valeur})

    def test_une_base_d_avant_le_champ_recoit_la_colonne_a_l_ouverture(
        self, tmp_path
    ) -> None:
        # Six bases dans ~/.diapason, aucune migration : chaque schéma se
        # complète à l'ouverture. Une base créée avant le 18 sept. 2026 n'a
        # pas la colonne ; la première ouverture l'ajoute, à 0.
        chemin = tmp_path / "ancienne.db"
        SuccesStore(chemin).create_task({"title": "D'avant"})
        with sqlite3.connect(chemin) as conn:
            conn.execute("CREATE TABLE sauvegarde AS SELECT * FROM succes_tasks")
            colonnes = [
                r[1]
                for r in conn.execute("PRAGMA table_info(succes_tasks)").fetchall()
                if r[1] != "estimate_days"
            ]
            conn.execute("DROP TABLE succes_tasks")
            conn.execute(
                "CREATE TABLE succes_tasks AS SELECT "
                + ", ".join(colonnes)
                + " FROM sauvegarde"
            )
            conn.execute("DROP TABLE sauvegarde")
            conn.commit()
        relue = SuccesStore(chemin).list_tasks()
        assert [t["estimateDays"] for t in relue] == [0]


class TestLaDureeSurLeFil:
    def _client(self, tmp_path) -> TestClient:
        set_store_for_tests(SuccesStore(tmp_path / "api.db"))
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_le_champ_voyage_en_entier_et_revient(self, tmp_path) -> None:
        client = self._client(tmp_path)
        try:
            cree = client.post(
                "/v1/succes/tasks", json={"title": "Contrat", "estimateDays": 4}
            )
            assert cree.status_code == 201
            assert cree.json()["task"]["estimateDays"] == 4
            tid = cree.json()["task"]["id"]
            patch = client.patch(f"/v1/succes/tasks/{tid}", json={"estimateDays": 6})
            assert patch.status_code == 200
            assert patch.json()["task"]["estimateDays"] == 6
            sans = client.patch(f"/v1/succes/tasks/{tid}", json={"title": "Contrat 2"})
            assert sans.json()["task"]["estimateDays"] == 6, (
                "une retouche qui ne parle pas de durée ne l'efface pas"
            )
        finally:
            set_store_for_tests(None)

    def test_un_flottant_est_refuse_a_la_porte(self, tmp_path) -> None:
        client = self._client(tmp_path)
        try:
            refuse = client.post(
                "/v1/succes/tasks", json={"title": "Contrat", "estimateDays": 1.5}
            )
            assert refuse.status_code == 422, "1.5 ne doit pas être arrondi en silence"
            refuse = client.patch("/v1/succes/tasks/x", json={"estimateDays": "2"})
            assert refuse.status_code == 422, "« 2 » en texte n'est pas un entier"
        finally:
            set_store_for_tests(None)


class TestLaDureeEnReplication:
    """Le journal d'ops rejoué par un pair doit tolérer le champ — et son absence."""

    def _paire(self, tmp_path):
        source = SuccesSyncStore(tmp_path / "source.db")
        cible = SuccesSyncStore(tmp_path / "cible.db")
        invitation = cible.create_pairing("Mac secondaire")
        pair = cible.redeem_pairing(invitation["pairingToken"])
        return source, cible, pair

    def test_la_duree_traverse_l_echange(self, tmp_path) -> None:
        source, cible, pair = self._paire(tmp_path)
        source.create_task(
            {"id": "contrat", "title": "Contrat", "estimateDays": 4, "updatedAtMs": 1}
        )
        ops = source.list_operations()["operations"]
        cible.exchange(pair["peerId"], after=0, operations=ops)
        assert cible.get_task("contrat")["estimateDays"] == 4

    def test_un_pair_qui_ignore_le_champ_ne_remet_pas_la_duree_a_zero(
        self, tmp_path
    ) -> None:
        # Le client Dart n'écrit que ce qu'il connaît : sa relève renvoie la
        # tâche sans `estimateDays`. Remise à 0 à chaque échange, la durée
        # posée sur le Mac ne tiendrait pas une journée.
        source, cible, pair = self._paire(tmp_path)
        cible.create_task(
            {"id": "contrat", "title": "Contrat", "estimateDays": 4, "updatedAtMs": 1}
        )
        source.create_task(
            {"id": "contrat", "title": "Contrat (tel)", "updatedAtMs": 5}
        )
        ops = source.list_operations()["operations"]
        for op in ops:
            op["payload"].pop("estimateDays", None)
        cible.exchange(pair["peerId"], after=0, operations=ops)
        relue = cible.get_task("contrat")
        assert relue["title"] == "Contrat (tel)", "le reste de la tâche est bien pris"
        assert relue["estimateDays"] == 4, "la durée locale est gardée, pas remise à 0"

    def test_une_duree_illisible_ne_brise_pas_le_lot(self, tmp_path) -> None:
        source, cible, pair = self._paire(tmp_path)
        source.create_task({"id": "contrat", "title": "Contrat", "updatedAtMs": 1})
        ops = source.list_operations()["operations"]
        for op in ops:
            op["payload"]["estimateDays"] = "beaucoup"
        cible.exchange(pair["peerId"], after=0, operations=ops)
        assert cible.get_task("contrat")["estimateDays"] == 0, (
            "une estimation perdue est un désagrément, un lot rejeté brise "
            "la réplication"
        )
