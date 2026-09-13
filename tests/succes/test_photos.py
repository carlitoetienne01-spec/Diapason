"""Les piles de photos d'un projet — magasin et routes.

Le serveur ne décode pas d'image : il lit la signature, borne la taille et
range le fichier. Ces tests vérifient chaque refus autant que chaque
acceptation, parce qu'une galerie qui accepte n'importe quoi finit par servir
n'importe quoi.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diapason.succes.photos import (
    MAX_THUMB_BYTES,
    SuccesPhotosStore,
    decoder_base64,
    mime_depuis_signature,
)
from diapason.succes.routes import router, set_store_for_tests
from diapason.succes.store import SuccesError, SuccesNotFound
from diapason.succes.sync import SuccesSyncStore

# Un JPEG minimal : la signature suffit, le serveur ne va pas plus loin.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
HTML = b"<html><body>pas une image</body></html>"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture
def magasin(tmp_path: Path) -> SuccesPhotosStore:
    return SuccesSyncStore(tmp_path / "succes.db")


@pytest.fixture
def projet(magasin: SuccesPhotosStore) -> dict:
    return magasin.create_project({"name": "La Cité"})


class TestLaSignature:
    def test_reconnait_les_quatre_formats_et_rien_d_autre(self) -> None:
        """§ photos — le type vient des octets, jamais du client."""
        assert mime_depuis_signature(JPEG) == "image/jpeg"
        assert mime_depuis_signature(PNG) == "image/png"
        assert mime_depuis_signature(WEBP) == "image/webp"
        assert mime_depuis_signature(GIF) == "image/gif"
        assert mime_depuis_signature(HTML) == "", "du HTML n'est pas une image"
        assert mime_depuis_signature(b"") == ""

    def test_le_base64_est_strict_et_borne_avant_de_decoder(self) -> None:
        assert decoder_base64(b64(JPEG), champ="x", maximum=1000) == JPEG
        assert (
            decoder_base64(
                "data:image/jpeg;base64," + b64(JPEG), champ="x", maximum=1000
            )
            == JPEG
        )
        with pytest.raises(SuccesError, match="base64"):
            decoder_base64("ceci n'est pas du base64 !!", champ="x", maximum=1000)
        with pytest.raises(SuccesError, match="dépasse"):
            decoder_base64(b64(b"\x00" * 2000), champ="x", maximum=1000)
        with pytest.raises(SuccesError, match="vide"):
            decoder_base64("", champ="x", maximum=1000)


class TestLesPiles:
    def test_une_pile_se_cree_se_renomme_et_refuse_le_doublon(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "  Python   3 ")
        assert pile["name"] == "Python 3", "les espaces se normalisent"
        assert pile["count"] == 0 and pile["apercus"] == []
        with pytest.raises(SuccesError, match="existe déjà"):
            magasin.create_photo_pile(projet["id"], "python 3")
        renommee = magasin.update_photo_pile(pile["id"], {"name": "Git"})
        assert renommee["name"] == "Git"
        with pytest.raises(SuccesError, match="besoin d'un nom"):
            magasin.create_photo_pile(projet["id"], "   ")

    def test_une_pile_exige_un_projet_vivant(self, magasin: SuccesPhotosStore) -> None:
        with pytest.raises(SuccesNotFound):
            magasin.create_photo_pile("inconnu", "Python")

    def test_les_piles_s_ordonnent_par_creation(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        for nom in ("Python", "Git", "Ottawa"):
            magasin.create_photo_pile(projet["id"], nom)
        noms = [p["name"] for p in magasin.list_photo_piles(projet["id"])["piles"]]
        assert noms == ["Python", "Git", "Ottawa"]


class TestLesPhotos:
    def test_une_photo_se_range_sur_le_disque_et_en_base(
        self, magasin: SuccesPhotosStore, projet: dict, tmp_path: Path
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        photo = magasin.add_photo(
            pile["id"],
            {
                "fileName": "decorateurs.png",
                "dataBase64": b64(PNG),
                "thumbBase64": b64(JPEG),
                "width": 1200,
                "height": 800,
                "tint": "#3B6D11",
                "caption": "Les décorateurs",
            },
        )
        assert photo["mime"] == "image/png", "le type vient de la signature"
        assert photo["bytes"] == len(PNG)
        assert photo["tint"] == "#3b6d11"
        assert photo["thumb"].startswith("data:image/jpeg;base64,")
        dossier = tmp_path / "succes-photos" / projet["id"]
        assert (dossier / f"{photo['id']}.png").read_bytes() == PNG
        assert (dossier / f"{photo['id']}.apercu.jpg").read_bytes() == JPEG
        contenu = magasin.photo_content(photo["id"])
        assert base64.b64decode(contenu["dataBase64"]) == PNG
        assert contenu["mime"] == "image/png"

    def test_le_type_annonce_ne_compte_pas_seule_la_signature(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        with pytest.raises(SuccesError, match="pas une image"):
            magasin.add_photo(
                pile["id"],
                {
                    "fileName": "x.jpg",
                    "dataBase64": b64(HTML),
                    "thumbBase64": b64(JPEG),
                },
            )
        with pytest.raises(SuccesError, match="aperçu doit être un JPEG"):
            magasin.add_photo(
                pile["id"],
                {"fileName": "x.png", "dataBase64": b64(PNG), "thumbBase64": b64(PNG)},
            )
        with pytest.raises(SuccesError, match="aperçu dépasse"):
            magasin.add_photo(
                pile["id"],
                {
                    "dataBase64": b64(PNG),
                    "thumbBase64": b64(JPEG + b"\x00" * MAX_THUMB_BYTES),
                },
            )
        assert magasin.list_photos(pile["id"])["photos"] == [], "rien n'est écrit"

    def test_un_refus_ne_laisse_aucun_fichier_orphelin(
        self, magasin: SuccesPhotosStore, projet: dict, tmp_path: Path
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        with pytest.raises(SuccesError):
            magasin.add_photo(
                pile["id"],
                {"dataBase64": b64(PNG), "thumbBase64": b64(JPEG), "taskId": "fantôme"},
            )
        dossier = tmp_path / "succes-photos" / projet["id"]
        assert not dossier.exists() or not any(dossier.iterdir())

    def test_la_teinte_hors_format_est_ignoree(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        photo = magasin.add_photo(
            pile["id"],
            {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG), "tint": "red;x"},
        )
        assert photo["tint"] == "", "du texte libre n'entre jamais dans un style"

    def test_la_pile_montre_la_couverture_puis_les_plus_recentes(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        ids = []
        for i in range(5):
            photo = magasin.add_photo(
                pile["id"],
                {
                    "fileName": f"{i}.jpg",
                    "dataBase64": b64(JPEG),
                    "thumbBase64": b64(JPEG),
                },
            )
            # Forcer un ordre strict : la même milliseconde ne trie rien.
            with magasin._connect() as conn:
                conn.execute(
                    "UPDATE succes_photos SET created_at_ms=? WHERE id=?",
                    (1_000 + i, photo["id"]),
                )
                conn.commit()
            ids.append(photo["id"])
        liste = magasin.list_photo_piles(projet["id"])["piles"][0]
        assert liste["count"] == 5
        assert [a["id"] for a in liste["apercus"]] == [ids[4], ids[3], ids[2]]

        magasin.update_photo_pile(pile["id"], {"coverPhotoId": ids[0]})
        liste = magasin.list_photo_piles(projet["id"])["piles"][0]
        assert [a["id"] for a in liste["apercus"]] == [ids[0], ids[4], ids[3]]
        assert liste["coverPhotoId"] == ids[0]

        # La couverture supprimée : la pile retombe sur la plus récente.
        magasin.delete_photo(ids[0])
        liste = magasin.list_photo_piles(projet["id"])["piles"][0]
        assert liste["coverPhotoId"] == ""
        assert [a["id"] for a in liste["apercus"]] == [ids[4], ids[3], ids[2]]

    def test_la_couverture_vient_de_la_pile_elle_meme(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        a = magasin.create_photo_pile(projet["id"], "A")
        b = magasin.create_photo_pile(projet["id"], "B")
        photo = magasin.add_photo(
            a["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
        )
        with pytest.raises(SuccesError, match="pile elle-même"):
            magasin.update_photo_pile(b["id"], {"coverPhotoId": photo["id"]})

    def test_une_photo_pointe_vers_une_tache_du_meme_projet(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        autre = magasin.create_project({"name": "Ailleurs"})
        tache = magasin.create_task({"title": "Étape 1", "projectId": projet["id"]})
        etrangere = magasin.create_task({"title": "Étape X", "projectId": autre["id"]})
        pile = magasin.create_photo_pile(projet["id"], "Python")
        photo = magasin.add_photo(
            pile["id"],
            {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG), "taskId": tache["id"]},
        )
        assert photo["taskId"] == tache["id"]
        assert magasin.list_photo_piles(projet["id"])["parTache"] == {tache["id"]: 1}
        with pytest.raises(SuccesError, match="n'appartient pas"):
            magasin.update_photo(photo["id"], {"taskId": etrangere["id"]})
        detachee = magasin.update_photo(photo["id"], {"taskId": ""})
        assert detachee["taskId"] == ""
        assert magasin.list_photo_piles(projet["id"])["parTache"] == {}

    def test_une_photo_change_de_pile_mais_jamais_de_projet(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        autre = magasin.create_project({"name": "Ailleurs"})
        a = magasin.create_photo_pile(projet["id"], "A")
        b = magasin.create_photo_pile(projet["id"], "B")
        ailleurs = magasin.create_photo_pile(autre["id"], "Z")
        photo = magasin.add_photo(
            a["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
        )
        magasin.update_photo_pile(a["id"], {"coverPhotoId": photo["id"]})
        deplacee = magasin.update_photo(photo["id"], {"pileId": b["id"]})
        assert deplacee["pileId"] == b["id"]
        assert magasin.list_photos(a["id"])["pile"]["coverPhotoId"] == "", (
            "l'ancienne pile ne garde pas une couverture partie"
        )
        with pytest.raises(SuccesError, match="ne change pas de projet"):
            magasin.update_photo(photo["id"], {"pileId": ailleurs["id"]})

    def test_supprimer_la_pile_emporte_photos_et_fichiers(
        self, magasin: SuccesPhotosStore, projet: dict, tmp_path: Path
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        for _ in range(3):
            magasin.add_photo(
                pile["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
            )
        dossier = tmp_path / "succes-photos" / projet["id"]
        assert len(list(dossier.iterdir())) == 6
        assert magasin.delete_photo_pile(pile["id"]) == 3
        assert list(dossier.iterdir()) == [], "les fichiers partent avec la pile"
        assert magasin.list_photo_piles(projet["id"])["piles"] == []
        with pytest.raises(SuccesNotFound):
            magasin.list_photos(pile["id"])

    def test_supprimer_le_projet_cache_les_piles_mais_garde_les_fichiers(
        self, magasin: SuccesPhotosStore, projet: dict, tmp_path: Path
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        photo = magasin.add_photo(
            pile["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
        )
        magasin.delete_project(projet["id"])
        with pytest.raises(SuccesNotFound):
            magasin.list_photos(pile["id"])
        with pytest.raises(SuccesNotFound):
            magasin.photo_content(photo["id"])
        dossier = tmp_path / "succes-photos" / projet["id"]
        assert len(list(dossier.iterdir())) == 2, (
            "une soft-delete ne détruit pas d'images"
        )


class TestLesRoutes:
    @pytest.fixture
    def client(self, magasin: SuccesPhotosStore):
        set_store_for_tests(magasin)
        app = FastAPI()
        app.include_router(router)
        try:
            yield TestClient(app)
        finally:
            set_store_for_tests(None)

    def test_le_cycle_complet_par_http(self, client: TestClient, projet: dict) -> None:
        pid = projet["id"]
        creee = client.post(
            f"/v1/succes/projects/{pid}/photo-piles", json={"name": "Python"}
        )
        assert creee.status_code == 201
        pile = creee.json()["pile"]

        ajout = client.post(
            f"/v1/succes/photo-piles/{pile['id']}/photos",
            json={
                "fileName": "capture.png",
                "dataBase64": b64(PNG),
                "thumbBase64": b64(JPEG),
                "width": 10,
                "height": 10,
                "tint": "#123456",
                "caption": "Première",
            },
        )
        assert ajout.status_code == 201, ajout.text
        photo = ajout.json()["photo"]
        assert photo["caption"] == "Première"

        liste = client.get(f"/v1/succes/projects/{pid}/photo-piles")
        assert liste.status_code == 200
        assert liste.json()["piles"][0]["count"] == 1
        assert liste.json()["piles"][0]["tint"] == "#123456"

        contenu = client.get(f"/v1/succes/photos/{photo['id']}/contenu")
        assert contenu.status_code == 200
        assert base64.b64decode(contenu.json()["dataBase64"]) == PNG

        renommee = client.patch(
            f"/v1/succes/photo-piles/{pile['id']}", json={"name": "Python 3"}
        )
        assert renommee.status_code == 200
        assert renommee.json()["pile"]["name"] == "Python 3"

        legende = client.patch(
            f"/v1/succes/photos/{photo['id']}", json={"caption": "Renommée"}
        )
        assert legende.json()["photo"]["caption"] == "Renommée"

        refus = client.request(
            "DELETE", f"/v1/succes/photos/{photo['id']}", json={"confirmed": False}
        )
        assert refus.status_code == 409
        assert refus.json()["detail"]["code"] == "confirmation_required"

        supprimee = client.request(
            "DELETE", f"/v1/succes/photo-piles/{pile['id']}", json={"confirmed": True}
        )
        assert supprimee.status_code == 200
        assert supprimee.json()["photos"] == 1

    def test_les_refus_du_domaine_rendent_409_ou_404(
        self, client: TestClient, projet: dict
    ) -> None:
        pid = projet["id"]
        pile = client.post(
            f"/v1/succes/projects/{pid}/photo-piles", json={"name": "A"}
        ).json()["pile"]
        doublon = client.post(
            f"/v1/succes/projects/{pid}/photo-piles", json={"name": "a"}
        )
        assert doublon.status_code == 409
        faux = client.post(
            f"/v1/succes/photo-piles/{pile['id']}/photos",
            json={"dataBase64": b64(HTML), "thumbBase64": b64(JPEG)},
        )
        assert faux.status_code == 409
        assert "pas une image" in faux.json()["detail"]
        absente = client.get("/v1/succes/photo-piles/inconnue/photos")
        assert absente.status_code == 404
        # Un projet supprimé n'accepte plus de pile.
        client.request("DELETE", f"/v1/succes/projects/{pid}", json={"confirmed": True})
        morte = client.post(
            f"/v1/succes/projects/{pid}/photo-piles", json={"name": "B"}
        )
        assert morte.status_code == 404


class TestLeRangement:
    def _trois(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> tuple[dict, list[str]]:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        ids = []
        for i in range(3):
            photo = magasin.add_photo(
                pile["id"],
                {
                    "fileName": f"{i}.jpg",
                    "dataBase64": b64(JPEG),
                    "thumbBase64": b64(JPEG),
                },
            )
            with magasin._connect() as conn:
                conn.execute(
                    "UPDATE succes_photos SET created_at_ms=? WHERE id=?",
                    (1_000 + i, photo["id"]),
                )
                conn.commit()
            ids.append(photo["id"])
        return pile, ids

    def test_sans_rangement_la_plus_recente_est_devant(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile, ids = self._trois(magasin, projet)
        # Chaque ajout prend `min - 1` : la dernière ajoutée est devant.
        assert [p["id"] for p in magasin.list_photos(pile["id"])["photos"]] == ids[::-1]

    def test_l_ordre_donne_s_applique_et_le_reste_suit(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile, ids = self._trois(magasin, projet)
        ranges = magasin.reorder_photos(pile["id"], [ids[0], ids[2]])
        assert [p["id"] for p in ranges] == [ids[0], ids[2], ids[1]], (
            "les absents gardent leur ordre relatif, après"
        )
        assert [p["position"] for p in ranges] == [0, 1, 2]
        # La pile fermée suit le même ordre.
        apercus = magasin.list_photo_piles(projet["id"])["piles"][0]["apercus"]
        assert [a["id"] for a in apercus] == [ids[0], ids[2], ids[1]]

    def test_une_photo_ajoutee_apres_un_rangement_passe_devant(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile, ids = self._trois(magasin, projet)
        magasin.reorder_photos(pile["id"], [ids[0], ids[1], ids[2]])
        nouvelle = magasin.add_photo(
            pile["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
        )
        assert nouvelle["position"] == -1
        liste = [p["id"] for p in magasin.list_photos(pile["id"])["photos"]]
        assert liste == [nouvelle["id"], ids[0], ids[1], ids[2]]

    def test_une_photo_d_une_autre_pile_est_refusee(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile, ids = self._trois(magasin, projet)
        autre = magasin.create_photo_pile(projet["id"], "Git")
        etrangere = magasin.add_photo(
            autre["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
        )
        with pytest.raises(SuccesError, match="pas dans la pile"):
            magasin.reorder_photos(pile["id"], [etrangere["id"]])
        with pytest.raises(SuccesNotFound):
            magasin.reorder_photos("inconnue", ids)

    def test_par_http(self, magasin: SuccesPhotosStore, projet: dict) -> None:
        pile, ids = self._trois(magasin, projet)
        set_store_for_tests(magasin)
        app = FastAPI()
        app.include_router(router)
        try:
            client = TestClient(app)
            reponse = client.put(
                f"/v1/succes/photo-piles/{pile['id']}/ordre",
                json={"photoIds": [ids[1], ids[0], ids[2]]},
            )
            assert reponse.status_code == 200, reponse.text
            assert [p["id"] for p in reponse.json()["photos"]] == [
                ids[1],
                ids[0],
                ids[2],
            ]
            vide = client.put(
                f"/v1/succes/photo-piles/{pile['id']}/ordre", json={"photoIds": []}
            )
            assert vide.status_code == 422
        finally:
            set_store_for_tests(None)

    def test_une_base_d_avant_recoit_la_colonne(self, tmp_path: Path) -> None:
        """Une base créée sans `position` doit s'ouvrir et se ranger."""
        chemin = tmp_path / "ancienne.db"
        magasin = SuccesSyncStore(chemin)
        with magasin._connect() as conn:
            conn.executescript(
                "ALTER TABLE succes_photos RENAME TO ancienne;"
                "CREATE TABLE succes_photos AS SELECT id, pile_id, project_id, "
                "file_name, mime, bytes, width, height, tint, caption, task_id, "
                "file_path, thumb_path, created_at_ms, updated_at_ms, deleted_at_ms "
                "FROM ancienne;"
                "DROP TABLE ancienne;"
            )
            conn.commit()
        rouverte = SuccesSyncStore(chemin)
        with rouverte._connect() as conn:
            colonnes = {
                r["name"] for r in conn.execute("PRAGMA table_info(succes_photos)")
            }
        assert "position" in colonnes


class TestLaRetoucheEtLesAnnotations:
    def _photo(self, magasin: SuccesPhotosStore, projet: dict) -> dict:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        return magasin.add_photo(
            pile["id"], {"dataBase64": b64(JPEG), "thumbBase64": b64(JPEG)}
        )

    def test_la_rotation_et_le_cadre_se_gardent_sans_toucher_l_original(
        self, magasin: SuccesPhotosStore, projet: dict, tmp_path: Path
    ) -> None:
        photo = self._photo(magasin, projet)
        retouchee = magasin.update_photo(
            photo["id"],
            {"rotation": 90, "crop": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.5}},
        )
        assert retouchee["rotation"] == 90
        assert retouchee["crop"] == {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.5}
        dossier = tmp_path / "succes-photos" / projet["id"]
        assert (dossier / f"{photo['id']}.jpg").read_bytes() == JPEG, (
            "non destructif : l'original n'a pas bougé"
        )
        effacee = magasin.update_photo(photo["id"], {"crop": None, "rotation": 0})
        assert effacee["crop"] is None and effacee["rotation"] == 0

    def test_un_cadre_hors_image_ou_minuscule_est_refuse(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        photo = self._photo(magasin, projet)
        with pytest.raises(SuccesError, match="rester dans l'image"):
            magasin.update_photo(
                photo["id"], {"crop": {"x": 0.8, "y": 0, "w": 0.5, "h": 0.5}}
            )
        with pytest.raises(SuccesError, match="au moins 2"):
            magasin.update_photo(
                photo["id"], {"crop": {"x": 0, "y": 0, "w": 0.01, "h": 0.5}}
            )
        with pytest.raises(SuccesError, match="entre 0 et 1"):
            magasin.update_photo(
                photo["id"], {"crop": {"x": "a", "y": 0, "w": 0.5, "h": 0.5}}
            )
        with pytest.raises(SuccesError, match="0, 90, 180 ou 270"):
            magasin.update_photo(photo["id"], {"rotation": 45})

    def test_l_apercu_suit_la_retouche(
        self, magasin: SuccesPhotosStore, projet: dict, tmp_path: Path
    ) -> None:
        photo = self._photo(magasin, projet)
        nouveau = JPEG + b"\x00\x11"
        magasin.update_photo(photo["id"], {"thumbBase64": b64(nouveau)})
        dossier = tmp_path / "succes-photos" / projet["id"]
        assert (dossier / f"{photo['id']}.apercu.jpg").read_bytes() == nouveau
        with pytest.raises(SuccesError, match="JPEG"):
            magasin.update_photo(photo["id"], {"thumbBase64": b64(PNG)})

    def test_les_annotations_sont_normalisees_et_bornees(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        photo = self._photo(magasin, projet)
        calque = [
            {"type": "arrow", "color": "#FF0000", "points": [[0.1, 0.1], [0.5, 0.5]]},
            {
                "type": "text",
                "color": "zzz",
                "points": [[0.2, 0.2]],
                "text": "ici",
                "width": 99,
            },
        ]
        annotee = magasin.update_photo(photo["id"], {"annotations": calque})
        assert len(annotee["annotations"]) == 2
        assert annotee["annotations"][0]["color"] == "#ff0000"
        assert annotee["annotations"][1]["color"] == "#ff3b30", (
            "couleur invalide → défaut"
        )
        assert annotee["annotations"][1]["width"] == 24, "l'épaisseur est bornée"
        assert annotee["annotations"][1]["text"] == "ici"
        assert all("id" in a for a in annotee["annotations"])
        with pytest.raises(SuccesError, match="inconnu"):
            magasin.update_photo(
                photo["id"], {"annotations": [{"type": "laser", "points": [[0, 0]]}]}
            )
        with pytest.raises(SuccesError, match="points"):
            magasin.update_photo(
                photo["id"], {"annotations": [{"type": "rect", "points": []}]}
            )
        vide = magasin.update_photo(photo["id"], {"annotations": []})
        assert vide["annotations"] == []

    def test_l_ocr_et_la_recherche(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        pile = magasin.create_photo_pile(projet["id"], "Python")
        a = magasin.add_photo(
            pile["id"],
            {
                "fileName": "erreur.png",
                "dataBase64": b64(PNG),
                "thumbBase64": b64(JPEG),
            },
        )
        b = magasin.add_photo(
            pile["id"],
            {
                "fileName": "b.png",
                "dataBase64": b64(PNG),
                "thumbBase64": b64(JPEG),
                "caption": "Les décorateurs",
            },
        )
        magasin.set_photo_ocr(a["id"], "  TypeError: unsupported   operand type(s)  ")
        assert magasin.search_photos(projet["id"], "typeerror")[0]["id"] == a["id"]
        assert magasin.search_photos(projet["id"], "Décorateurs")[0]["id"] == b["id"]
        # Dans l'ordre de la pile : b, ajoutée après, est devant.
        assert [p["id"] for p in magasin.search_photos(projet["id"], "png")] == [
            b["id"],
            a["id"],
        ], "chaque mot compte, dans le nom aussi"
        assert magasin.search_photos(projet["id"], "operand typeerror") == [
            magasin.search_photos(projet["id"], "typeerror")[0]
        ], "l'ordre des mots n'importe pas"
        assert magasin.search_photos(projet["id"], "rien-du-tout") == []
        assert magasin.search_photos(projet["id"], "   ") == []
        assert (
            magasin.search_photos(projet["id"], "typeerror")[0]["pileName"] == "Python"
        )

    def test_l_export_n_ecrit_que_du_pdf_chez_l_utilisateur(
        self, magasin: SuccesPhotosStore, tmp_path: Path, monkeypatch
    ) -> None:
        maison = tmp_path / "maison"
        maison.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: maison))
        pdf = b"%PDF-1.4\n%fin"
        cible = maison / "Documents"
        cible.mkdir()
        resultat = magasin.write_export(str(cible / "pile.pdf"), b64(pdf))
        assert (cible / "pile.pdf").read_bytes() == pdf
        assert resultat["bytes"] == len(pdf)
        with pytest.raises(SuccesError, match="dossier personnel"):
            magasin.write_export(str(tmp_path / "ailleurs.pdf"), b64(pdf))
        with pytest.raises(SuccesError, match="\\.pdf"):
            magasin.write_export(str(cible / "pile.txt"), b64(pdf))
        with pytest.raises(SuccesError, match="pas un PDF"):
            magasin.write_export(str(cible / "faux.pdf"), b64(JPEG))
        with pytest.raises(SuccesError, match="n'existe pas"):
            magasin.write_export(str(maison / "nulle-part" / "x.pdf"), b64(pdf))

    def test_par_http_le_cadre_s_efface_par_drapeau(
        self, magasin: SuccesPhotosStore, projet: dict
    ) -> None:
        photo = self._photo(magasin, projet)
        set_store_for_tests(magasin)
        app = FastAPI()
        app.include_router(router)
        try:
            client = TestClient(app)
            pose = client.patch(
                f"/v1/succes/photos/{photo['id']}",
                json={"crop": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}, "rotation": 180},
            )
            assert pose.status_code == 200, pose.text
            assert pose.json()["photo"]["rotation"] == 180
            efface = client.patch(
                f"/v1/succes/photos/{photo['id']}", json={"effacerCadre": True}
            )
            assert efface.json()["photo"]["crop"] is None
            assert efface.json()["photo"]["rotation"] == 180, "la rotation reste"
            recherche = client.get(
                f"/v1/succes/projects/{projet['id']}/photos/recherche",
                params={"q": "photo"},
            )
            assert recherche.status_code == 200
            assert recherche.json()["count"] == 1
            faux = client.post(
                "/v1/succes/photos/exporter",
                json={"path": "/etc/x.pdf", "dataBase64": b64(b"%PDF-1.4")},
            )
            assert faux.status_code == 409
        finally:
            set_store_for_tests(None)
