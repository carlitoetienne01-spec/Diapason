"""§78/100 : fermer le micro ne doit ni relancer Orion ni rejouer un ancien son."""

import asyncio
import json
import sys

import pytest
import pytest_asyncio

from diapason.speech.realtime import reserve_orion as reserve
from diapason.speech.realtime import voix_expressive as voix
from diapason.speech.realtime.local_voice import LocalVoiceSession


@pytest_asyncio.fixture
async def ouvriers(monkeypatch, tmp_path):
    monkeypatch.setenv("DIAPASON_HOME", str(tmp_path / "configuration"))
    journal = tmp_path / "requetes.jsonl"
    processus = []
    creer = asyncio.create_subprocess_exec
    code = """
import base64,json,os,sys,time
journal=sys.argv[1]
print(json.dumps({"type":"ready"}),flush=True)
for ligne in sys.stdin:
    r=json.loads(ligne)
    with open(journal,"a") as f: f.write(ligne)
    if r.get("type")=="ping":
        if os.path.exists(journal+".ping-bloque"): time.sleep(30)
        if os.path.exists(journal+".ping-erreur"):
            print(json.dumps({"type":"error"}),flush=True)
            continue
        print(json.dumps({"type":"ready"}),flush=True)
        continue
    texte=r["text"]
    if texte=="erreur":
        print(json.dumps({"type":"error"}),flush=True)
        continue
    print(json.dumps({"type":"audio","sampleRate":24000,
                      "data":base64.b64encode(texte.encode("utf-16-le")).decode()}),flush=True)
    if texte=="bloquer": time.sleep(30)
    print(json.dumps({"type":"done"}),flush=True)
"""

    async def lancer(*_, **options):
        p = await creer(sys.executable, "-u", "-c", code, str(journal), **options)
        processus.append(p)
        return p

    monkeypatch.setattr(voix, "moteur_installe", lambda: True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lancer)
    try:
        yield processus, journal
    finally:
        await reserve.fermer_reserve_orion()
        for p in processus:
            await reserve.arreter_processus(p)


def nouvelle_voix():
    return voix.VoixExpressive("qwen3-b", conserver_au_repos=True)


@pytest.mark.asyncio
async def test_rouvrir_reprend_le_moteur_sans_prechauffage_ni_ancien_audio(ouvriers):
    """§100 : la chauffe coûtait encore trois secondes après une simple fermeture."""
    processus, journal = ouvriers
    premiere = nouvelle_voix()
    await premiere.preparer()
    _ = [p async for p in premiere.morceaux("ancienne phrase")]
    await premiere.fermer()
    seconde = nouvelle_voix()
    try:
        await seconde.preparer()
        assert len(processus) == 1, "le modèle déjà prêt ne doit pas être rechargé"
        pcm = b"".join([p async for p in seconde.morceaux("nouvelle phrase")])
        assert pcm.decode("utf-16-le") == "nouvelle phrase", (
            "aucun son de la séance précédente ne doit passer dans la nouvelle"
        )
        requetes = [json.loads(ligne) for ligne in journal.read_text().splitlines()]
        assert len(requetes) == 4, "une chauffe, deux phrases et une sonde seulement"
        assert requetes[2] == {"type": "ping"}, "la reprise vérifie vraiment le moteur"
        await premiere.fermer()
        assert processus[0].returncode is None, (
            "l'ancien propriétaire ne tue pas le nouveau"
        )
    finally:
        await seconde.annuler()


@pytest.mark.asyncio
async def test_deux_seances_ne_partagent_pas_les_tubes_et_un_seul_moteur_reste(
    ouvriers,
):
    """§100 : deux consommateurs du même tube pourraient échanger leurs paroles."""
    processus, _ = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    await a.fermer()
    b, c = nouvelle_voix(), nouvelle_voix()
    await asyncio.gather(b.preparer(), c.preparer())
    assert b._processus is not c._processus, "chaque séance possède ses propres tubes"
    assert len(processus) == 2, "la première reprend le moteur, la seconde en crée un"
    await b.fermer()
    await c.fermer()
    assert sum(p.returncode is None for p in processus) == 1, (
        "les fermetures ne doivent pas accumuler plusieurs modèles en mémoire"
    )


@pytest.mark.asyncio
async def test_une_phrase_interrompue_ne_retourne_pas_dans_la_reserve(ouvriers):
    """§100 : la fin d'une ancienne phrase ne doit jamais servir de nouvelle réponse."""
    processus, _ = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    flux = a.morceaux("bloquer")
    await anext(flux)
    await a.fermer()
    await flux.aclose()
    assert processus[0].returncode is not None, "le calcul incomplet est vraiment tué"
    assert reserve.reserve_orion().prendre("qwen3-b") is None, "aucun ouvrier contaminé"


@pytest.mark.asyncio
async def test_une_erreur_ne_laisse_pas_un_moteur_reutilisable(ouvriers):
    """§100 : un processus vivant après une erreur n'est pas une voix prête."""
    processus, _ = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    with pytest.raises(RuntimeError):
        _ = [p async for p in a.morceaux("erreur")]
    await a.fermer()
    assert processus[0].returncode is not None, "le flux fautif est détruit"
    assert reserve.reserve_orion().prendre("qwen3-b") is None, "pas de faux prêt"


@pytest.mark.asyncio
async def test_la_reserve_expire_et_libere_la_memoire(ouvriers, monkeypatch):
    """§78 : le repos est temporaire, sans entretien permanent du moteur."""
    monkeypatch.setattr(reserve, "REPOS_MAX_S", 0.03)
    processus, _ = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    await a.fermer()
    await asyncio.wait_for(processus[0].wait(), 2)
    assert reserve.reserve_orion().prendre("qwen3-b") is None, (
        "le délai détruit la réserve"
    )


@pytest.mark.asyncio
async def test_reprendre_annule_l_expiration_et_arreter_le_serveur_libere(
    ouvriers, monkeypatch
):
    """§100 : l'ancien minuteur ne doit pas tuer une nouvelle séance en cours."""
    monkeypatch.setattr(reserve, "REPOS_MAX_S", 0.03)
    processus, _ = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    await a.fermer()
    b = nouvelle_voix()
    await b.preparer()
    await asyncio.sleep(0.07)
    assert processus[0].returncode is None, "une séance reprise n'expire plus au repos"
    await b.fermer()
    await reserve.fermer_reserve_orion()
    assert processus[0].returncode is not None, (
        "la fermeture serveur libère aussi la réserve"
    )


@pytest.mark.asyncio
async def test_un_moteur_mort_est_remplace_avant_de_promettre_ready(ouvriers):
    processus, _ = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    await a.fermer()
    await reserve.arreter_processus(processus[0])
    b = nouvelle_voix()
    await b.preparer()
    assert len(processus) == 2, "une nouvelle vraie chauffe remplace le moteur mort"
    await b.annuler()


@pytest.mark.asyncio
@pytest.mark.parametrize("defaut", ["erreur", "bloque"])
async def test_un_moteur_vivant_mais_defaillant_ne_devient_pas_un_faux_pret(
    ouvriers, defaut
):
    """§100 : la sonde doit refuser un flux en erreur ou un ouvrier bloqué."""
    processus, journal = ouvriers
    a = nouvelle_voix()
    await a.preparer()
    await a.fermer()
    journal.with_name(journal.name + ".ping-" + defaut).touch()
    b = nouvelle_voix()
    await asyncio.wait_for(b.preparer(), 4)
    assert len(processus) == 2, "la reprise défaillante impose une vraie chauffe"
    assert processus[0].returncode is not None, "l'ancien ouvrier est tué et récolté"
    await b.annuler()


@pytest.mark.asyncio
async def test_annuler_la_preparation_ne_garde_pas_un_moteur_incomplet(
    ouvriers, monkeypatch
):
    """§78 : fermer pendant Connexion n'entretient pas une préparation abandonnée."""
    commence = asyncio.Event()
    a = nouvelle_voix()

    async def chauffer():
        commence.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(a, "_prechauffer", chauffer)
    tache = asyncio.create_task(a.preparer())
    await asyncio.wait_for(commence.wait(), 2)
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    await a.fermer()
    assert ouvriers[0][0].returncode is not None, "pas de moteur orphelin"
    assert reserve.reserve_orion().prendre("qwen3-b") is None, "chauffe non terminée"


@pytest.mark.asyncio
async def test_les_vraies_seances_reprennent_orion_sans_partager_le_contexte(
    ouvriers, monkeypatch
):
    """§5 : la réserve doit être exercée par le vrai démarrage des séances."""
    monkeypatch.setattr(
        "diapason.speech.realtime.local_voice.ollama_reachable", lambda: True
    )
    processus, _ = ouvriers
    for texte in ("Je débute en anglais.", "Je souhaite jardiner."):
        s = LocalVoiceSession(
            stt=lambda _: "",
            llm=lambda _: None,
            enable_tools=False,
            historique=[{"role": "user", "content": texte}],
        )
        try:
            await s.connect()
            assert (await s._queue.get()).kind == "ready", "attendre le moteur prêt"
            assert s._history == [{"role": "user", "content": texte}], (
                "aucun historique emprunté"
            )
        finally:
            await s.close()
    assert len(processus) == 1, "fermer puis rouvrir la vraie session réutilise Orion"


@pytest.mark.asyncio
async def test_arreter_le_vrai_serveur_libere_son_ouvrier_au_repos(
    ouvriers, monkeypatch
):
    """§78 : le cycle de vie serveur doit réellement libérer la réserve Orion."""
    from unittest.mock import MagicMock

    from diapason.core.config import DiapasonConfig
    from diapason.server import app as module_app

    async def attendre(*_):
        await asyncio.Event().wait()

    for nom in ("_prewarm_local_model", "_mesh_heartbeat", "_synchroniser_le_compte"):
        monkeypatch.setattr(module_app, nom, attendre)
    monkeypatch.setattr("diapason.mesh.discovery.run_discovery", attendre)
    monkeypatch.setattr("diapason.server.prechauffage.entretenir_le_prefixe", attendre)
    moteur = MagicMock()
    moteur.engine_id = "mock"
    config = DiapasonConfig()
    config.analytics.enabled = False
    config.traces.enabled = False
    application = module_app.create_app(moteur, "modele-factice", config=config)
    async with application.router.lifespan_context(application):
        v = nouvelle_voix()
        await v.preparer()
        await v.fermer()
        assert ouvriers[0][0].returncode is None, "la réserve existe avant fermeture"
    assert ouvriers[0][0].returncode is not None, "pas d'ouvrier après l'arrêt serveur"
