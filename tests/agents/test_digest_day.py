"""À quel jour appartient un bulletin.

Le bulletin est un artefact *quotidien* : il appartient à une date de
calendrier, et cette date est celle de la personne qui l'écoute. Le relire
sur un autre fuseau que celui où il a été écrit fait diverger les deux dates
autour de minuit — et l'API répondait « No digest for today » à propos d'un
bulletin qui était dans la table.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import diapason.agents.digest_store as digest_store_module
from diapason.agents.digest_store import DigestArtifact, DigestStore

TORONTO = "America/Toronto"  # UTC-4 l'été : minuit UTC y est 20 h
TOKYO = "Asia/Tokyo"  # UTC+9 : minuit local y est 15 h UTC la veille


@pytest.fixture
def a_lheure(monkeypatch):
    """Gèle l'horloge du module à une heure locale donnée."""

    def geler(tz_name: str, heure: int, jour: int = 18):
        fige = dt.datetime(2026, 8, jour, heure, 0, tzinfo=ZoneInfo(tz_name))

        class Horloge(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return fige.astimezone(tz) if tz else fige.replace(tzinfo=None)

        monkeypatch.setattr(digest_store_module, "datetime", Horloge)

    return geler


def store_avec_bulletin_du(tz_name: str, jour: int = 18) -> DigestStore:
    store = DigestStore(db_path=str(Path(tempfile.mkdtemp()) / "d.db"))
    store.save(
        DigestArtifact(
            text="Bonjour. Trois courriels, deux réunions.",
            audio_path=Path(""),
            sections={},
            sources_used=[],
            generated_at=dt.datetime(2026, 8, jour, 6, 30, tzinfo=ZoneInfo(tz_name)),
            model_used="qwen3.5:4b",
            voice_used="",
        )
    )
    return store


class TestLeBulletinResteTrouvableToutLeJour:
    """C'est l'APPEL SANS ARGUMENT qui portait le défaut.

    ``get_today`` acceptait déjà un fuseau, et le lui passer a toujours
    marché — mais les deux routes appelaient ``get_today()`` tout court, et
    le défaut valait ``"UTC"``. Un test qui passe le fuseau explicitement
    aurait été vert des deux côtés de la correction : il faut interroger le
    chemin que le serveur emprunte réellement.
    """

    @pytest.mark.parametrize("heure", [7, 13, 19, 20, 21, 23])
    def test_a_toronto_y_compris_le_soir(self, a_lheure, heure):
        """À 20 h à Toronto, UTC est déjà demain — quatre heures par jour où
        le bulletin du matin disparaissait derrière un 404."""
        a_lheure(TORONTO, heure)
        assert store_avec_bulletin_du(TORONTO).get_today() is not None

    @pytest.mark.parametrize("heure", [6, 7, 8, 10, 18])
    def test_a_tokyo_y_compris_au_petit_matin(self, a_lheure, heure):
        """À l'est de Greenwich l'erreur s'inverse : c'est le matin que la
        date UTC est encore celle de la veille."""
        a_lheure(TOKYO, heure)
        assert store_avec_bulletin_du(TOKYO).get_today() is not None

    @pytest.mark.parametrize("heure", [20, 21, 23])
    def test_la_route_le_sert_encore_le_soir(self, a_lheure, monkeypatch, heure):
        """Bout en bout : c'est ici que « No digest for today » était rendu."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import diapason.server.digest_routes as routes

        a_lheure(TORONTO, heure)
        store = store_avec_bulletin_du(TORONTO)
        monkeypatch.setattr(routes, "DigestStore", lambda **_: store)

        app = FastAPI()
        app.include_router(routes.create_digest_router(db_path="ignored"))
        reponse = TestClient(app).get("/api/digest")

        assert reponse.status_code == 200, reponse.json()
        assert "Trois courriels" in reponse.json()["text"]


class TestLaCorrectionNEstPasUneIndulgence:
    """Rendre le bulletin trouvable ne doit pas le rendre éternel."""

    @pytest.mark.parametrize("tz", [TORONTO, TOKYO])
    def test_le_bulletin_dhier_reste_refuse(self, a_lheure, tz):
        a_lheure(tz, 9, jour=18)
        store = store_avec_bulletin_du(tz, jour=17)  # celui de la veille
        assert store.get_today(tz) is None

    def test_une_table_vide_rend_none(self, a_lheure):
        a_lheure(TORONTO, 9)
        vide = DigestStore(db_path=str(Path(tempfile.mkdtemp()) / "d.db"))
        assert vide.get_today(TORONTO) is None


class TestLesReplis:
    def test_un_fuseau_inconnu_retombe_sur_la_machine(self, a_lheure):
        """Un nom mal orthographié dans la configuration ne doit pas priver
        quelqu'un de son briefing — ni faire tomber la route."""
        a_lheure(TORONTO, 9)
        store = store_avec_bulletin_du(TORONTO)
        assert store.get_today("Mars/Olympus") is not None

    def test_sans_fuseau_la_machine_fait_foi(self, a_lheure):
        """Le repli est l'heure locale, pas UTC : les lignes écrites avant
        cette correction sont naïves-locales, et c'est ce qu'elles veulent
        dire."""
        a_lheure(TORONTO, 9)
        assert store_avec_bulletin_du(TORONTO).get_today("") is not None

    def test_une_ligne_ancienne_sans_fuseau_est_encore_lue(self, a_lheure):
        """Les bulletins déjà en base portent un horodatage naïf."""
        a_lheure(TORONTO, 9)
        store = DigestStore(db_path=str(Path(tempfile.mkdtemp()) / "d.db"))
        store.save(
            DigestArtifact(
                text="Bonjour.",
                audio_path=Path(""),
                sections={},
                sources_used=[],
                generated_at=dt.datetime(2026, 8, 18, 6, 30),  # naïf, comme avant
                model_used="q",
                voice_used="",
            )
        )
        assert store.get_today(TORONTO) is not None


class TestLeDefautNAffirmePlusUneVille:
    def test_la_configuration_ne_suppose_aucun_fuseau(self):
        """Le défaut était « America/Los_Angeles ». Sur une machine à
        Toronto, le briefing datait sa journée à Los Angeles et annonçait
        l'heure du Pacifique — une heure fausse de trois heures, sous une
        étiquette exacte, donc invérifiable pour qui l'écoute."""
        from diapason.core.config import DigestConfig

        assert DigestConfig().timezone == ""

    def test_vide_signifie_cette_machine(self):
        from diapason.agents.morning_digest import _now_in

        assert _now_in("").utcoffset() == dt.datetime.now().astimezone().utcoffset()
