"""Unit tests for clap detector (no microphone)."""

from __future__ import annotations

import pytest

from diapason.speech.clap_listener import ClapConfig, ClapDetector, rms_mono


def _cfg(**kwargs) -> ClapConfig:
    base = dict(
        spike_ratio=5.0,
        cooldown_s=0.2,
        min_double_gap_s=0.05,
        max_double_gap_s=0.35,
        retrigger_ratio=0.55,
        descente_alpha=0.90,
        min_rms=0.01,
    )
    base.update(kwargs)
    return ClapConfig(**base)


def _feed_quiet(det: ClapDetector, t0: float, n: int = 30) -> float:
    t = t0
    for i in range(n):
        t = t0 + i * 0.04
        det.process(0.002, t)
    return t


def _clap_pulse(det: ClapDetector, t: float, peak: float = 0.2) -> bool:
    hit = det.process(peak, t)
    det.process(0.001, t + 0.02)
    return hit


def test_rms_silence():
    import numpy as np

    assert rms_mono(np.zeros(64, dtype="float32")) == 0.0


def test_double_clap_within_window():
    det = ClapDetector(cfg=_cfg(), noise_floor=0.002)
    t = _feed_quiet(det, 0.0)
    assert _clap_pulse(det, t + 0.1) is False
    assert _clap_pulse(det, t + 0.1 + 0.15) is True


def test_gap_too_large_starts_new_pair():
    det = ClapDetector(cfg=_cfg(), noise_floor=0.002)
    t = _feed_quiet(det, 0.0)
    assert _clap_pulse(det, t + 0.1) is False
    assert _clap_pulse(det, t + 0.1 + 0.50) is False
    assert _clap_pulse(det, t + 0.1 + 0.50 + 0.12) is True


def test_local_trigger_emit(tmp_path):
    from diapason.channels.local_trigger import LocalTriggerChannel

    path = tmp_path / "t.jsonl"
    ch = LocalTriggerChannel(path=path)
    received = []

    def handler(msg):
        received.append(msg.content)
        return None

    ch.on_message(handler)
    ch.connect()
    ch.emit("hello", event="welcome_home")
    import time

    time.sleep(0.8)
    ch.disconnect()
    assert any("hello" in c for c in received)


class TestLeDemarrageSeConstate:
    """Ajouté le 25 août 2026 : start() rendait la main sur une espérance.

    Le fil d'écoute meurt à sa première ligne quand sounddevice manque, et
    rien ne le disait — l'appelant croyait écouter. Deux signaux rendent le
    démarrage constatable.
    """

    def test_sans_sounddevice_l_ecoute_avoue_sa_panne(self, monkeypatch):
        import builtins

        from diapason.speech.clap_listener import ClapListener

        vrai_import = builtins.__import__

        def _sans_sounddevice(nom, *a, **k):
            if nom == "sounddevice":
                raise ImportError("pas de sounddevice")
            return vrai_import(nom, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _sans_sounddevice)
        ecouteur = ClapListener(lambda: None, once=False)
        ecouteur.start()
        assert ecouteur.ecoute is False
        assert "sounddevice" in (ecouteur.panne or "")
        ecouteur.stop()

    def test_le_detecteur_compte_les_claps_simples(self):
        """Distinguer « le micro n'entend rien » de « mes claps sont trop
        espacés » demande de compter les pics, pas seulement les doubles."""
        from diapason.speech.clap_listener import ClapConfig, ClapDetector

        d = ClapDetector(cfg=ClapConfig())
        # Une seconde de calme d'abord : le détecteur apprend la pièce avant
        # d'y entendre quoi que ce soit, et un test qui clape à la première
        # milliseconde teste un détecteur qui ne sait pas encore où il est.
        for i in range(ClapConfig().blocs_d_amorcage):
            d.process(0.001, 5.0 + i * 0.04)
        # Deux pics très espacés : aucun double, mais deux claps entendus.
        # Le silence entre les deux réarme le détecteur — sans lui, le
        # second pic est considéré comme la queue du premier.
        # Les instants partent de dix : à zéro, le temps de repos initial
        # (now - last_logged_double = 0) écarterait le premier pic. En
        # production l'horloge monotone est grande, jamais nulle.
        assert d.process(0.5, 10.0) is False
        d.process(0.0005, 11.0)
        assert d.process(0.5, 15.0) is False
        assert d.claps_entendus == 2
        assert "gap_too_large" in (d.last_miss_reason or "")


class TestLaPieceNEstPasUnClap:
    """Le fond sonore d'une pièce réelle ne doit jamais passer pour un clap.

    Les niveaux rejoués ici ont été MESURÉS dans la pièce de Carlito le
    25 août 2026 (MacBook Air, micro interne, personne ne parle) après
    qu'il eut constaté que « n'importe quel bruit active la caméra ».
    Un seuil réglé sur un studio imaginaire ne prouve rien ; celui-ci se
    confronte à du son enregistré.
    """

    def _trace(self) -> dict:
        import json
        import pathlib

        chemin = (
            pathlib.Path(__file__).resolve().parents[1]
            / "fixtures"
            / "piece_au_repos.json"
        )
        return json.loads(chemin.read_text())

    def _rejouer(self, det: ClapDetector, trace: dict) -> tuple[int, float]:
        pas = trace["block_ms"] / 1000.0
        doubles = 0
        instant = 10.0
        for i, niveau in enumerate(trace["niveaux"]):
            instant = 10.0 + i * pas
            if det.process(niveau, instant):
                doubles += 1
        return doubles, instant

    def test_le_silence_mesure_ne_declenche_rien(self):
        trace = self._trace()
        det = ClapDetector(cfg=ClapConfig())
        doubles, _ = self._rejouer(det, trace)
        assert doubles == 0, "le fond sonore de la pièce a été pris pour des claps"
        assert det.claps_entendus == 0

    def test_le_fond_sonore_apprend_la_piece(self):
        trace = self._trace()
        det = ClapDetector(cfg=ClapConfig())
        self._rejouer(det, trace)
        niveaux = sorted(trace["niveaux"])
        median = niveaux[len(niveaux) // 2]
        assert median * 0.4 <= det.noise_floor <= median * 2.5, (
            f"fond appris {det.noise_floor:.5f} contre une pièce à {median:.5f}"
        )

    def test_un_vrai_clap_perce_le_fond_sonore(self):
        trace = self._trace()
        det = ClapDetector(cfg=ClapConfig())
        _, t = self._rejouer(det, trace)
        assert det.process(0.35, t + 0.50) is False, "premier clap ignoré"
        det.process(0.006, t + 0.54)
        assert det.process(0.35, t + 0.70) is True, "le double clap n'a pas été vu"


class TestLaMesureNeSeLaissePasDeplacer:
    """Les statistiques d'une mesure ne doivent pas céder devant ce qu'elles
    servent à juger.

    Défaut confirmé le 25 août 2026 : la garde comparait le maximum au
    quantile 0,95 de la MÊME fenêtre. Dès qu'un transitoire durait quatre
    blocs, il définissait lui-même la référence à laquelle on le comparait,
    et la garde se taisait précisément quand elle devait parler. Les tests
    d'alors ne construisaient que des transitoires d'UN bloc — le seul
    régime où elle fonctionnait. La DURÉE est donc le paramètre à balayer.
    """

    def _piece(self, blocs: list[float]):
        from diapason.speech.clap_listener import Piece, niveau_ordinaire

        niveau, dispersion = niveau_ordinaire(blocs)
        return Piece(
            niveau=niveau,
            dispersion=dispersion,
            maximum=max(blocs),
            blocs_bruyants=sum(1 for b in blocs if b > niveau * 6.0),
        )

    def _trace(self) -> list[float]:
        import json
        import pathlib as pl

        chemin = (
            pl.Path(__file__).resolve().parents[1] / "fixtures" / "piece_au_repos.json"
        )
        return json.loads(chemin.read_text())["niveaux"][:62]

    def test_une_piece_au_repos_n_est_pas_troublee(self):
        piece = self._piece(self._trace())
        assert not piece.troublee
        assert piece.blocs_bruyants == 0

    def test_la_garde_tient_quelle_que_soit_la_duree_du_transitoire(self):
        """Le balayage que les anciens tests ne faisaient pas."""
        trace = self._trace()
        queue = [0.30, 0.22, 0.14, 0.09, 0.05, 0.04, 0.03, 0.025, 0.022, 0.02, 0.018, 0.016]
        for duree in range(2, 13):
            piece = self._piece(trace[: 62 - duree] + queue[:duree])
            assert piece.troublee, f"transitoire de {duree} blocs non détecté"

    def test_la_mediane_ne_bouge_pas_quand_le_maximum_explose(self):
        """Un clap pendant la phase calme ne doit pas redéfinir la pièce."""
        trace = self._trace()
        pure = self._piece(trace)
        pollue = self._piece(trace[:56] + [0.30, 0.22, 0.14, 0.09, 0.05, 0.04])
        assert abs(pollue.niveau - pure.niveau) < pure.niveau * 0.1, (
            "la médiane a suivi le transitoire"
        )
        assert pollue.maximum > pure.maximum * 20, "le maximum, lui, l'a suivi"

    def test_le_bruit_de_fond_n_entre_pas_dans_les_claps(self):
        """Une touche de clavier retenue comme « clap » devenait le plus
        faible, et c'est lui qui fixait le seuil."""
        from diapason.speech.clap_listener import _bouffees, seuil_de_bouffee

        piece = self._piece(self._trace())
        pendant = [0.031, 0.021] + [0.004] * 5 + [0.40, 0.30, 0.10]
        assert _bouffees(pendant, seuil_de_bouffee(piece)) == [0.40]

    def test_une_mesure_ne_rend_jamais_le_detecteur_plus_bavard_que_l_usine(self):
        """Le plancher d'usine avait été relevé parce que le silence
        déclenchait. Une calibration ne doit pas pouvoir le défaire."""
        from diapason.speech.clap_listener import ClapConfig, Ecoute, reglage_calibre

        piece = self._piece(self._trace())
        # Des « claps » faibles mais réguliers : sans plancher, le seuil
        # tomberait sous celui d'usine.
        ecoute = Ecoute(piece=piece, claps=[0.12, 0.13, 0.14], ecartes=[])
        assert reglage_calibre(ecoute).min_rms >= ClapConfig().min_rms

    def test_un_seul_son_fort_ne_suffit_pas_a_calibrer(self):
        from diapason.speech.clap_listener import Ecoute, reglage_calibre

        piece = self._piece(self._trace())
        with pytest.raises(ValueError, match="un seul son fort"):
            reglage_calibre(Ecoute(piece=piece, claps=[0.45], ecartes=[]))

    def test_le_plus_faible_ne_tire_plus_tout_le_reglage(self):
        """La médiane des claps, pas leur minimum : le minimum cède devant
        un seul intrus, et c'est justement lui qui fixerait le seuil."""
        from diapason.speech.clap_listener import Ecoute, reglage_calibre

        piece = self._piece(self._trace())
        propre = reglage_calibre(Ecoute(piece=piece, claps=[0.44, 0.45, 0.46], ecartes=[]))
        avec_intrus = reglage_calibre(
            Ecoute(piece=piece, claps=[0.20, 0.45, 0.46], ecartes=[])
        )
        assert propre.min_rms == avec_intrus.min_rms

    def test_des_claps_trop_faibles_sont_refuses_plutot_que_rendus_inaudibles(self):
        """Planchonner le seuil au-dessus des claps donnerait un mode qui ne
        s'arme jamais. Le dire vaut mieux que l'enregistrer."""
        from diapason.speech.clap_listener import Ecoute, reglage_calibre

        piece = self._piece(self._trace())
        with pytest.raises(ValueError, match="trop faibles"):
            reglage_calibre(Ecoute(piece=piece, claps=[0.06, 0.065, 0.07], ecartes=[]))

    def test_un_choc_pendant_la_phase_calme_se_dit_avec_ses_chiffres(self):
        from diapason.speech.clap_listener import Ecoute, Piece, reglage_calibre

        troublee = Piece(niveau=0.006, dispersion=0.3, maximum=0.62, blocs_bruyants=5)
        with pytest.raises(ValueError, match="Attends que je te dise de claper"):
            reglage_calibre(Ecoute(piece=troublee, claps=[0.5, 0.5], ecartes=[]))
