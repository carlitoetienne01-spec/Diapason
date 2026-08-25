"""Double-clap detector and optional microphone listener (welcome trigger)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClapConfig:
    sample_rate: int = 44100
    block_ms: int = 40
    channels: int = 1
    # Un clap est un son FORT et bref. Les valeurs d'origine (rapport 2,5 et
    # plancher 0,003) avaient été posées pour un studio imaginaire : mesurée
    # le 25 août 2026, la pièce de Carlito au repos vit entre 0,005 et 0,015,
    # soit AU-DESSUS de ce plancher. Le silence lui-même franchissait le
    # seuil — cinq « claps » en huit secondes sans que personne ne bouge.
    spike_ratio: float = 8.0
    min_rms: float = 0.05
    cooldown_s: float = 0.35
    min_double_gap_s: float = 0.04
    max_double_gap_s: float = 0.80
    retrigger_ratio: float = 0.80
    # Le fond sonore retombe vite et ne monte que lentement : un clap dure
    # un bloc et ne doit pas soulever le plancher qu'il vient de franchir.
    descente_alpha: float = 0.90
    montee_alpha: float = 0.98
    plafond_de_montee: float = 1.6
    # Une seconde d'écoute pour apprendre la pièce avant d'y prétendre
    # entendre quoi que ce soit.
    blocs_d_amorcage: int = 25


@dataclass
class ClapDetector:
    """Stateful detector: feed RMS samples, receive double-clap events."""

    cfg: ClapConfig
    noise_floor: float = 1e-4
    last_logged_double: float = 0.0
    first_clap_time: float | None = None
    spike_armed: bool = True
    last_miss_reason: str | None = None
    # Ce que le micro ENTEND, même quand aucun double ne se forme.
    # Sans ce compte, quelqu'un qui clape peut le faire une heure sans
    # savoir si le micro l'entend, si le seuil est trop haut, ou si c'est
    # l'écart entre les deux claps qui ne convient pas (25 août 2026).
    claps_entendus: int = 0
    dernier_clap_a: float = 0.0
    # L'apprentissage de la pièce : tant qu'il n'est pas fini, on se tait.
    blocs_ecoutes: int = 0
    amorce: list[float] = field(default_factory=list)

    def process(self, level: float, now: float) -> bool:
        self.last_miss_reason = None
        cfg = self.cfg

        # 1. Apprendre la pièce. Le fond sonore ne se devine pas : il partait
        #    de 0,0001 et ne se mettait à jour QUE si le niveau descendait
        #    sous 0,0002 — ce qu'aucune pièce réelle ne fait. Il restait donc
        #    figé à vie, et le seuil qu'il gouverne avec lui.
        if self.blocs_ecoutes < cfg.blocs_d_amorcage:
            self.blocs_ecoutes += 1
            self.amorce.append(level)
            calme = sorted(self.amorce)
            self.noise_floor = max(calme[len(calme) // 2], 1e-7)
            self.last_miss_reason = "amorcage"
            return False

        # 2. Le suivre ensuite, sans le laisser soulever par ce qu'il filtre :
        #    la cible est plafonnée, donc un clap ne peut pas relever le
        #    plancher qu'il vient de franchir.
        cible = min(level, self.noise_floor * cfg.plafond_de_montee)
        alpha = cfg.descente_alpha if cible < self.noise_floor else cfg.montee_alpha
        self.noise_floor = max(alpha * self.noise_floor + (1.0 - alpha) * cible, 1e-7)

        threshold = max(self.noise_floor * cfg.spike_ratio, cfg.min_rms)
        retrigger_level = threshold * cfg.retrigger_ratio

        if level < retrigger_level:
            self.spike_armed = True

        if not (
            self.spike_armed
            and level >= threshold
            and (now - self.last_logged_double) >= cfg.cooldown_s
        ):
            return False

        self.spike_armed = False
        self.claps_entendus += 1
        self.dernier_clap_a = now
        if self.first_clap_time is None:
            self.first_clap_time = now
            return False

        gap = now - self.first_clap_time
        if gap < cfg.min_double_gap_s:
            self.last_miss_reason = f"gap_too_small={gap:.3f}s"
            return False
        if gap <= cfg.max_double_gap_s:
            self.first_clap_time = None
            self.last_logged_double = now
            return True

        self.last_miss_reason = f"gap_too_large={gap:.3f}s_new_first"
        self.first_clap_time = now
        return False

    @property
    def threshold(self) -> float:
        return max(self.noise_floor * self.cfg.spike_ratio, self.cfg.min_rms)


def rms_mono(block) -> float:
    import numpy as np

    arr = np.asarray(block)
    if arr.ndim > 1:
        arr = np.mean(arr.astype(np.float64), axis=1)
    else:
        arr = arr.astype(np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr**2)))


def _input_devices():
    import sounddevice as sd

    return [
        (i, dev)
        for i, dev in enumerate(sd.query_devices())
        if dev["max_input_channels"] >= 1
    ]


def resolve_input_device_index(spec: str) -> int:
    import sounddevice as sd

    spec = spec.strip()
    if spec.isdigit():
        idx = int(spec)
        sd.query_devices(idx)
        return idx
    needle = spec.lower()
    for idx, dev in _input_devices():
        if needle in str(dev["name"]).lower():
            return idx
    raise ValueError(f"No input device matches {spec!r}")


def probe_input_max_rms(
    device: int,
    blocksize: int,
    *,
    sample_rate: int,
    channels: int,
    probe_s: float,
) -> float | None:
    import sounddevice as sd

    try:
        with sd.InputStream(
            device=device,
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            peak = 0.0
            deadline = time.monotonic() + probe_s
            while time.monotonic() < deadline:
                data, _ = stream.read(blocksize)
                peak = max(peak, rms_mono(data))
            return peak
    except Exception:
        return None


def choose_input_device(
    cfg: ClapConfig,
    blocksize: int,
    *,
    override: str | None = None,
    silent_rms: float = 0.0005,
    probe_s: float = 0.5,
) -> int | None:
    """Pick a working mic: override → default if loud → loudest input → default."""
    import sounddevice as sd

    logger.info("Audio devices:\n%s", sd.query_devices())

    if override and override.strip():
        idx = resolve_input_device_index(override)
        peak = probe_input_max_rms(
            idx,
            blocksize,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            probe_s=probe_s,
        )
        logger.info(
            "Using configured mic [%d] (probe rms=%s)",
            idx,
            f"{peak:.5f}" if peak is not None else "unopenable",
        )
        return idx

    default = sd.default.device[0]
    if default is not None and default >= 0:
        peak = probe_input_max_rms(
            default,
            blocksize,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            probe_s=probe_s,
        )
        if peak is not None and peak >= silent_rms:
            logger.info("Using default mic [%d] (probe rms=%.5f)", default, peak)
            return int(default)
        logger.warning(
            "Default mic [%d] silent/unusable (rms=%s); scanning…",
            default,
            f"{peak:.5f}" if peak is not None else "n/a",
        )

    best_idx: int | None = None
    best_peak = -1.0
    for idx, _dev in _input_devices():
        if default is not None and idx == default:
            continue
        peak = probe_input_max_rms(
            idx,
            blocksize,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            probe_s=probe_s,
        )
        if peak is not None and peak > best_peak:
            best_peak = peak
            best_idx = idx

    if best_idx is not None and best_peak >= silent_rms:
        logger.info("Auto-selected mic [%d] (probe rms=%.5f)", best_idx, best_peak)
        return best_idx

    if default is not None and default >= 0:
        logger.warning("Falling back to default mic [%d]", default)
        return int(default)
    inputs = _input_devices()
    if inputs:
        logger.warning("Falling back to first input [%d]", inputs[0][0])
        return inputs[0][0]
    return None


def chemin_reglage_claps() -> "Path":
    from diapason.core.paths import get_config_dir

    return Path(get_config_dir()) / "claps.json"


def charger_reglage_claps() -> ClapConfig:
    """Le réglage de CETTE pièce — celui d'usine si rien n'est calibré."""
    import json

    try:
        brut = json.loads(chemin_reglage_claps().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ClapConfig()
    connus = set(ClapConfig.__dataclass_fields__)
    return ClapConfig(**{k: v for k, v in brut.items() if k in connus})


def enregistrer_reglage_claps(cfg: ClapConfig) -> None:
    import json
    from dataclasses import asdict

    chemin = chemin_reglage_claps()
    chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    chemin.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")


def oublier_le_reglage_claps() -> None:
    chemin_reglage_claps().unlink(missing_ok=True)


def niveau_ordinaire(blocs: list[float]) -> tuple[float, float]:
    """Le niveau habituel d'un fond sonore, et sa dispersion.

    La médiane, pas un quantile haut ni un maximum : un transitoire ne doit
    pas pouvoir déplacer la statistique qui sert à le juger. Un maximum brut
    cède devant un seul bloc ; le quantile 0,95 cède devant quatre. La
    médiane demande d'en corrompre la moitié.

    Le calcul se fait sur les logarithmes, parce qu'un niveau sonore se
    compare en RAPPORTS et non en écarts : entre 0,005 et 0,015 il y a le
    même chemin qu'entre 0,05 et 0,15.
    """
    from math import exp, log

    if not blocs:
        return 0.0, 0.0
    logs = sorted(log(max(b, 1e-7)) for b in blocs)
    median = logs[len(logs) // 2]
    ecarts = sorted(abs(x - median) for x in logs)
    # 1,4826 : le facteur qui rend la MAD comparable à un écart-type sur une
    # loi normale, et donc lisible par qui connaît les écarts-types.
    dispersion = 1.4826 * ecarts[len(ecarts) // 2]
    return exp(median), dispersion


@dataclass
class Piece:
    """Ce qu'une pièce fait quand personne ne lui demande rien."""

    niveau: float
    """Son niveau habituel — médiane, insensible aux évènements isolés."""
    dispersion: float
    """Sa respiration, en log : de combien elle s'écarte d'ordinaire."""
    maximum: float
    """Le plus fort entendu, transitoire compris."""
    blocs_bruyants: int
    """Combien de blocs ont dépassé six fois son niveau habituel."""

    @property
    def haute(self) -> float:
        """Sa portée haute ordinaire — le plafond de ce qu'elle fait seule.

        Trois dispersions, pas cinq : calibré sur la pièce réelle de Carlito,
        dont le maximum observé vaut deux dispersions au-dessus de la
        médiane. Cinq donnaient 0,040 pour une pièce qui n'a jamais dépassé
        0,0124 — une marge inventée devient un seuil que les claps doivent
        franchir pour rien.
        """
        from math import exp, log

        if self.niveau <= 0.0:
            return 0.0
        return exp(log(self.niveau) + 3.0 * self.dispersion)

    @property
    def troublee(self) -> bool:
        """Quelque chose est arrivé pendant que la pièce devait se taire.

        Un COMPTAGE, pas un rapport. Un rapport entre le maximum et une
        statistique de la même fenêtre monte des deux côtés à la fois : dès
        que le transitoire dure quatre blocs, il définit lui-même la
        référence à laquelle on le compare, et la garde se tait précisément
        quand elle devrait parler. Un clap, attaque et réverbération, dure
        toujours plus que ça (démontré le 25 août 2026).
        """
        return self.blocs_bruyants >= 2


@dataclass
class Ecoute:
    """Une mesure complète : la pièce, puis ce qui s'y est ajouté."""

    piece: Piece
    claps: list[float]
    ecartes: list[float]
    """Les bouffées écartées : trop faibles pour être les mêmes claps."""


def _bouffees(niveaux: list[float], seuil: float) -> list[float]:
    """Un sommet par bouffée. Un clap occupe plusieurs blocs — attaque puis
    réverbération — et serait sinon compté plusieurs fois."""
    pics: list[float] = []
    en_cours = 0.0
    for niveau in niveaux:
        if niveau >= seuil:
            en_cours = max(en_cours, niveau)
        elif en_cours:
            pics.append(en_cours)
            en_cours = 0.0
    if en_cours:
        pics.append(en_cours)
    return pics


def ecouter_la_piece(
    *,
    cfg: ClapConfig | None = None,
    device: int | None = None,
    duree_s: float = 2.5,
    oubli_initial_s: float = 0.6,
) -> Piece:
    """Écouter une pièce se taire. Rien n'est enregistré : seuls des niveaux
    sonores sortent d'ici, jamais de son (§10).

    Les premières fractions de seconde sont JETÉES : la mesure est déclenchée
    par un clic sur la machine qui tient le micro, et ce clic est un
    transitoire net.
    """
    import sounddevice as sd

    cfg = cfg or ClapConfig()
    bloc = int(cfg.sample_rate * cfg.block_ms / 1000)
    with sd.InputStream(
        device=device,
        samplerate=cfg.sample_rate,
        channels=cfg.channels,
        dtype="float32",
        blocksize=bloc,
    ) as flux:
        fin = time.monotonic() + oubli_initial_s
        while time.monotonic() < fin:
            flux.read(bloc)
        releves: list[float] = []
        fin = time.monotonic() + duree_s
        while time.monotonic() < fin:
            donnees, _ = flux.read(bloc)
            releves.append(rms_mono(donnees))

    niveau, dispersion = niveau_ordinaire(releves)
    return Piece(
        niveau=niveau,
        dispersion=dispersion,
        maximum=max(releves) if releves else 0.0,
        blocs_bruyants=sum(1 for r in releves if r > niveau * 6.0),
    )


def seuil_de_bouffee(piece: Piece) -> float:
    """À partir de quel niveau un son mérite d'être regardé.

    Dix fois le fond, au minimum : un clap vaut vingt à soixante fois le
    niveau habituel d'une pièce. Deux fois et demie laissait entrer une
    touche de clavier, qui devenait ensuite « le clap le plus faible » et
    tirait tout le réglage vers le bas.
    """
    return max(piece.niveau * 10.0, piece.haute * 2.0, 0.02)


def ecouter_les_claps(
    piece: Piece,
    *,
    cfg: ClapConfig | None = None,
    device: int | None = None,
    duree_s: float = 6.0,
    oubli_initial_s: float = 0.25,
) -> Ecoute:
    """Écouter quelqu'un claper, dans une pièce déjà mesurée."""
    import sounddevice as sd

    cfg = cfg or ClapConfig()
    bloc = int(cfg.sample_rate * cfg.block_ms / 1000)
    with sd.InputStream(
        device=device,
        samplerate=cfg.sample_rate,
        channels=cfg.channels,
        dtype="float32",
        blocksize=bloc,
    ) as flux:
        fin = time.monotonic() + oubli_initial_s
        while time.monotonic() < fin:
            flux.read(bloc)
        releves: list[float] = []
        fin = time.monotonic() + duree_s
        while time.monotonic() < fin:
            donnees, _ = flux.read(bloc)
            releves.append(rms_mono(donnees))

    pics = _bouffees(releves, seuil_de_bouffee(piece))
    if not pics:
        return Ecoute(piece=piece, claps=[], ecartes=[])
    # Une bouffée nettement plus faible que les autres n'est pas le même
    # geste : c'est une chaise, une touche, un choc. L'écarter vaut mieux
    # que de caler tout le réglage dessus.
    milieu = sorted(pics)[len(pics) // 2]
    gardes = [p for p in pics if p >= 0.4 * milieu]
    return Ecoute(
        piece=piece,
        claps=gardes,
        ecartes=[p for p in pics if p < 0.4 * milieu],
    )


def reglage_calibre(
    ecoute: Ecoute,
    *,
    base: ClapConfig | None = None,
) -> ClapConfig:
    """Un seuil posé entre DEUX mesures : la pièce, et les claps de son
    occupant.

    Le seuil vise la moyenne géométrique — le milieu au sens de l'oreille,
    qui entend des rapports et non des différences.
    """
    from dataclasses import replace
    from math import sqrt

    base = base or ClapConfig()
    piece = ecoute.piece
    plancher_usine = ClapConfig().min_rms

    # Chaque refus nomme la MANŒUVRE à corriger, pas seulement le symptôme :
    # trois causes différentes donnaient le même message, et l'utilisateur
    # ne pouvait pas savoir laquelle le concernait.
    if piece.troublee:
        raise ValueError(
            f"Un bruit fort ({piece.maximum:.3f}) est arrivé pendant que "
            f"j'écoutais la pièce, qui vit d'ordinaire à {piece.niveau:.3f}. "
            "Attends que je te dise de claper, puis recommence."
        )
    if not ecoute.claps:
        raise ValueError(
            f"Aucun clap n'a été entendu — la pièce est restée à "
            f"{piece.niveau:.3f} du début à la fin. Clape plus fort, plus "
            "près du Mac, et pendant les six secondes qui suivent le signal."
        )
    if len(ecoute.claps) < 2:
        # Un seul pic ne dit pas si c'était un clap ou un choc. Deux se
        # ressemblent ; un tout seul ne se compare à rien.
        raise ValueError(
            f"Je n'ai entendu qu'un seul son fort ({ecoute.claps[0]:.3f}). "
            "Clape trois fois, bien séparément, pendant les six secondes."
        )

    # La MÉDIANE des claps retenus, jamais le plus faible : le minimum cède
    # devant un seul intrus, et c'est justement lui qui fixerait le seuil.
    ordonnes = sorted(ecoute.claps)
    reference = ordonnes[len(ordonnes) // 2]
    if reference < piece.haute * 3.0:
        raise ValueError(
            f"Tes claps ({reference:.3f}) ne se détachent pas assez du "
            f"bruit de la pièce ({piece.haute:.3f}). Clape plus fort, "
            "plus près du micro, ou dans un endroit plus calme."
        )

    seuil = sqrt(piece.haute * reference)
    # Une mesure ne doit JAMAIS rendre le détecteur plus bavard que l'usine
    # sans le dire : c'est ainsi qu'un plancher réglé pour un studio
    # imaginaire avait laissé le silence déclencher.
    # Le plancher s'appuie sur la portée HAUTE, pas sur le maximum brut :
    # un maximum cède devant un seul bloc, et un clic isolé pendant la phase
    # calme suffirait sinon à rendre le seuil inatteignable.
    seuil = max(seuil, piece.haute * 3.0, plancher_usine)
    if reference < seuil * 1.5:
        # Le plancher a rattrapé le seuil au point de dépasser les claps :
        # le poser quand même donnerait un mode qui ne s'arme jamais.
        raise ValueError(
            f"Tes claps ({reference:.3f}) sont trop faibles pour être "
            f"distingués sans risque du bruit ambiant (il faudrait au moins "
            f"{seuil * 1.5:.3f}). Rapproche-toi du Mac et recommence."
        )
    return replace(base, min_rms=round(seuil, 4))


class ClapListener:
    """Background mic loop that invokes a callback on double clap."""

    def __init__(
        self,
        on_double_clap: Callable[[], None],
        *,
        cfg: ClapConfig | None = None,
        once: bool = True,
        device: int | None = None,
        debug: bool = False,
    ) -> None:
        self._on_double = on_double_clap
        self._cfg = cfg or charger_reglage_claps()
        self._once = once
        self._device = device
        self._debug = debug
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fired = False
        # Le fil d'écoute meurt en silence quand sounddevice manque ou que
        # le micro refuse de s'ouvrir : start() rend la main sans rien dire,
        # et l'appelant croit écouter (constaté le 25 août 2026 — le mode
        # annonçait « écoute active » alors que le fil était mort à la
        # première ligne). Ces deux signaux rendent le démarrage
        # CONSTATABLE au lieu d'être supposé.
        self._pret = threading.Event()
        self._panne: Optional[str] = None
        self._detecteur: Optional[ClapDetector] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._pret.clear()
        self._panne = None
        self._thread = threading.Thread(
            target=self._run, name="clap-listener", daemon=True
        )
        self._thread.start()
        # Attendre le verdict plutôt que de rendre la main sur une
        # espérance : deux secondes suffisent à ouvrir un micro, et
        # au-delà c'est que quelque chose ne va pas.
        self._pret.wait(2.0)

    @property
    def ecoute(self) -> bool:
        """Le micro est-il RÉELLEMENT ouvert ? Constaté, jamais supposé."""
        return (
            self._pret.is_set()
            and self._panne is None
            and self._thread is not None
            and self._thread.is_alive()
        )

    @property
    def claps_entendus(self) -> int:
        """Combien de pics le micro a relevés — doubles ou non."""
        return self._detecteur.claps_entendus if self._detecteur else 0

    @property
    def seuil(self) -> float:
        """Le seuil que ce fil applique VRAIMENT, à cet instant.

        Le lire dans le fichier de réglage reviendrait à proclamer : un fil
        démarré avant une calibration garde l'ancien seuil jusqu'à ce qu'on
        le relance, et l'interface afficherait un chiffre auquel personne
        n'obéit. Zéro quand rien n'écoute — il n'y a alors pas de seuil.
        """
        if self._detecteur is not None:
            return self._detecteur.threshold
        return 0.0

    @property
    def fond_sonore(self) -> float:
        """Le fond sonore que ce fil a APPRIS de la pièce où il tourne.

        Comparé au seuil, il dit d'un coup d'œil si la marge est confortable
        ou si la pièce est montée jusqu'à frôler le déclenchement.
        """
        return self._detecteur.noise_floor if self._detecteur else 0.0

    @property
    def dernier_echec(self) -> Optional[str]:
        """Pourquoi le dernier pic n'a pas formé un double, s'il y a lieu."""
        return self._detecteur.last_miss_reason if self._detecteur else None

    @property
    def panne(self) -> Optional[str]:
        """Pourquoi l'écoute n'a pas démarré, s'il y a une raison."""
        return self._panne

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self._panne = "sounddevice manque : uv sync --extra speech-wake"
            logger.error(self._panne)
            self._pret.set()
            return

        blocksize = max(
            1,
            int(self._cfg.sample_rate * self._cfg.block_ms / 1000),
        )
        detector = ClapDetector(cfg=self._cfg)
        self._detecteur = detector
        logger.info(
            "Clap listener started "
            "(spike_ratio=%.1f, gap=%.2f–%.2fs, once=%s, debug=%s)",
            self._cfg.spike_ratio,
            self._cfg.min_double_gap_s,
            self._cfg.max_double_gap_s,
            self._once,
            self._debug,
        )
        last_peak_log = 0.0
        peak_window = 0.0
        first_seen = False
        try:
            with sd.InputStream(
                device=self._device,
                samplerate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                dtype="float32",
                blocksize=blocksize,
            ) as stream:
                # Le micro est ouvert POUR DE VRAI : c'est seulement ici
                # qu'on peut le dire.
                self._pret.set()
                while not self._stop.is_set():
                    data, _overflowed = stream.read(blocksize)
                    level = rms_mono(data)
                    now = time.monotonic()
                    peak_window = max(peak_window, level)

                    if self._debug and (now - last_peak_log) >= 1.0:
                        logger.info(
                            "mic peak=%.5f floor=%.5f thr=%.5f",
                            peak_window,
                            detector.noise_floor,
                            detector.threshold,
                        )
                        peak_window = 0.0
                        last_peak_log = now

                    before = detector.first_clap_time
                    hit = detector.process(level, now)
                    if (
                        before is None
                        and detector.first_clap_time is not None
                        and not hit
                        and not first_seen
                    ):
                        first_seen = True
                        logger.info(
                            "First clap (rms=%.5f thr=%.5f) — clap again within %.2fs",
                            level,
                            detector.threshold,
                            self._cfg.max_double_gap_s,
                        )
                    if (
                        detector.last_miss_reason
                        and detector.last_miss_reason.startswith("gap_too_large")
                    ):
                        logger.info(
                            "Second clap too late (%s)", detector.last_miss_reason
                        )
                        first_seen = True

                    if not hit:
                        continue
                    if self._once and self._fired:
                        logger.info("Double clap ignored (already fired this session)")
                        continue
                    self._fired = True
                    logger.info("Double clap detected — firing callback")
                    try:
                        self._on_double()
                    except Exception:
                        logger.exception("Clap callback failed")
                    if self._once:
                        break
        except Exception:
            logger.exception("Clap listener audio error")
