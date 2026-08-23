"""Optional one-shot LLM polish for dictation (Diapason-style, opt-in)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DICTATION_SYSTEM = """\
You clean speech-to-text. Output ONLY the cleaned text.
Always write in the SAME language as the input. Never translate: a
translation is not a correction, even when it preserves the meaning.
Preserve meaning and the user's words. Do not add facts, names, or signatures.
Allowed: remove fillers; fix obvious STT/grammar/punctuation/capitalization;
apply self-corrections ("4pm sorry 5pm" → "5pm");
"readme dot md" → "readme.md" ("readme point md" → "readme.md");
spoken emoji phrases → emoji.
Never invent closings. Never explain."""

_EMAIL_EXTRA = """\
If this is clearly an email, add line breaks after the greeting and before any
closing. Keep spoken closings exactly ("Best" stays "Best"). Never add a
signature the user did not say."""


def _strip_model_noise(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(
        r"^(?:here(?:'s| is)(?: the)?(?: cleaned| polished)?(?: text)?[:\s]*)",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    if t.startswith("```") and t.endswith("```"):
        t = re.sub(r"^```\w*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _unwrap_engine(resultat: Any) -> Any:
    """Le moteur, qu'on ait reçu un couple ``(nom, moteur)`` ou le moteur nu.

    ``get_engine`` rend un couple. Garder le tuple donnait un objet sans
    ``engine_id`` ni ``is_cloud``, que le garde local-only classait
    « distant » — sa règle « un moteur inconnu n'est pas local » est juste,
    elle refusait donc TOUJOURS. Le polissage par modèle était mort par une
    erreur de dépaquetage, et le refus parfaitement expliqué dans un journal
    que personne ne lisait.
    """
    if isinstance(resultat, tuple):
        return resultat[1] if len(resultat) > 1 else None
    return resultat


# Deux jeux de marqueurs. On ne cherche pas à nommer une langue dans l'absolu
# — seulement à voir si la correction a CHANGÉ de langue. Les mots communs aux
# deux langues (« note », « message », « important », « double », « page »)
# sont volontairement absents : ils n'arbitrent rien. L'intersection est
# retirée par construction plus bas, pour qu'aucun mot ne plaide des deux côtés.
_MARQUEURS_FR = frozenset(
    """
je tu il elle nous vous ils elles te se lui leur y en
le la les un une des du au aux ce cet cette ces
et est sont etait etaient etre suis es sommes etes
ai avons avez ont avait avaient
ca cela ceci celui celle
mon ma mes ton ta tes sa ses notre votre leurs
qui que quoi dont ou quand comment pourquoi
pour avec dans sur sous sans mais donc car ni
plus moins tres bien tout tous toute toutes rien
fais fait faire dis dit dire vais va aller
ouvre ouvrir ferme fermer envoie envoyer envoyez
demain hier aujourd hui matin soir
merci bonjour salut oui non peux peut veux veut
dois doit faut attends attendre regarde regarder
""".split()
)

_MARQUEURS_EN = frozenset(
    """
the of and to is are was were be been being am
this that these those there here
with for from into onto about
you your yours my mine it its they them their our ours
he she his her we us
will would can could should must shall may might
have has had do does did doesn didn won isn aren
open close send sent write wrote read tell told ask asked
tomorrow yesterday today morning evening night
please thanks thank sorry hello yes no not
wait waiting stop start make made take took give gave
what when where which who why how
""".split()
)

# Un mot qui appartient aux deux ne départage rien : on le retire des deux.
_AMBIGUS = _MARQUEURS_FR & _MARQUEURS_EN
_MARQUEURS_FR = _MARQUEURS_FR - _AMBIGUS
_MARQUEURS_EN = _MARQUEURS_EN - _AMBIGUS

_ELISION = re.compile(r"\b(?:[cdjlmnst]|qu)'", re.I)
_ACCENTS = re.compile(r"[\u00e0-\u00ff\u0153\u00e6]", re.I)
_MOTS = re.compile(r"[a-z\u00e0-\u00ff\u0153\u00e6']+", re.I)


def _profil_langue(texte: str) -> tuple[int, int]:
    """Poids d'indices francais et anglais dans un texte. Jamais une certitude."""
    plats: list[str] = []
    for mot in _MOTS.findall(texte or ""):
        plats.extend(p for p in mot.lower().split("'") if p)
    fr = sum(1 for p in plats if p in _MARQUEURS_FR)
    en = sum(1 for p in plats if p in _MARQUEURS_EN)
    # Elision et accents ne se rencontrent pas en anglais : ce sont des indices
    # francais que les listes de mots ne captent pas sur un texte tres court.
    fr += len(_ELISION.findall(texte or ""))
    if _ACCENTS.search(texte or ""):
        fr += 1
    return fr, en


def _langue_conservee(brut: str, corrige: str) -> bool:
    """La correction reste-t-elle dans la langue dictee ?

    Une traduction a la meme longueur que l'original : le garde de fidelite,
    qui compte des caracteres, ne peut pas la voir passer. Celui-ci refuse le
    BASCULEMENT, pas une langue en particulier — dicter en anglais reste permis.

    En cas de doute on accepte : refuser a tort ne coute qu'un texte non poli,
    alors que laisser passer une traduction coute la phrase de l'utilisateur.
    """
    fb, eb = _profil_langue(brut)
    fc, ec = _profil_langue(corrige)
    if fb > eb and ec > fc:
        return False
    if eb > fb and fc > ec:
        return False
    return True


def llm_polish_text(
    text: str,
    *,
    email_mode: bool = False,
    timeout_ms: int = 2000,
    model: str = "",
    engine: Any = None,
) -> Optional[str]:
    """Polish dictation via the configured engine. Returns None on skip/failure."""
    raw = (text or "").strip()
    if not raw:
        return None
    if len(raw.split()) < 3:
        return None
    # Une LONGUE phrase ne se polit pas au modèle : il la RÉGÉNÈRE mot à mot,
    # et la mesure est sans appel — cinquante-huit mots prennent 4,0 s modèle
    # CHAUD, c'est-à-dire tout le budget avant même un aléa. Tenter, c'est
    # garantir l'expiration : quatre secondes brûlées pour coller le brut
    # qu'on aurait pu coller tout de suite. Le dictionnaire personnel et le
    # polissage mécanique s'appliquent toujours, eux.
    if len(raw.split()) > 40:
        logger.debug("llm polish skipped: %d words, cannot fit the budget",
                     len(raw.split()))
        return None

    system = _DICTATION_SYSTEM
    if email_mode:
        system = system + "\n" + _EMAIL_EXTRA

    try:
        from diapason.core.config import load_config
        from diapason.core.types import Message, Role

        cfg = load_config()
        resolved_model = (model or cfg.intelligence.default_model or "").strip()
        if not resolved_model:
            logger.debug("llm polish skipped: no default model")
            return None

        eng = engine
        if eng is None:
            from diapason.engine._discovery import get_engine

            key = (cfg.engine.default or "").strip() or None
            eng = get_engine(cfg, key)
            # get_engine rend (nom, moteur). Prendre le tuple entier donnait
            # un objet sans engine_id ni is_cloud, que le garde local-only
            # classait « distant » — sa règle « un moteur inconnu n'est pas
            # local » est juste, elle refusait donc TOUJOURS. Le polissage
            # par modèle était ainsi mort par une erreur de dépaquetage, et
            # le refus, lui, était parfaitement expliqué dans le journal.
            eng = _unwrap_engine(eng)
        if eng is None:
            return None

        # Local-only mode covers the WHOLE dictation path, not just the
        # transcription. This function received whatever engine the config
        # named and sent the dictated sentence to it without ever asking
        # whether it ran on this machine — so a user dictating with a local
        # Whisper still had every phrase polished in the cloud.
        #
        # There is no cloud-free way to polish with a remote engine, so in
        # local-only mode the answer is "no polish" — never "polish
        # elsewhere". Returning None makes the caller keep the raw text,
        # which is exactly the degradation the user asked for.
        from diapason.core.local_mode import engine_is_local, local_only

        if local_only(cfg) and not engine_is_local(eng):
            logger.info(
                "llm polish skipped: engine %r is remote and local-only mode is on — "
                "raw text kept, nothing was sent",
                getattr(eng, "engine_id", "?"),
            )
            return None

        messages = [
            Message(role=Role.SYSTEM, content=system),
            Message(
                role=Role.USER,
                content=f"===SPEECH===\n{raw}\n===END===",
            ),
        ]
        timeout_s = max(0.3, float(timeout_ms) / 1000.0)

        def _call() -> str:
            result = eng.generate(
                messages,
                model=resolved_model,
                temperature=0.1,
                max_tokens=min(512, max(64, len(raw.split()) * 4)),
            )
            content = ""
            if isinstance(result, dict):
                content = str(result.get("content") or "")
            return _strip_model_noise(content)

        # PAS de « with » : sa sortie attend la fin du travail même après
        # l'expiration. Mesuré — délai demandé 1 s, durée réelle 8,2 s sur un
        # moteur lent : le délai était factice, et une dictée derrière un
        # créneau Ollama occupé restait suspendue jusqu'au bout de la file.
        # À l'expiration on ABANDONNE le fil (il mourra seul en fin de
        # génération, sans rien retenir) et le brut se colle à l'heure dite.
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(_call)
        try:
            out = fut.result(timeout=timeout_s)
        except FuturesTimeout:
            logger.info("llm polish timed out after %sms", timeout_ms)
            return None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if not out or len(out) > max(40, len(raw) * 3):
            return None
        if not _langue_conservee(raw, out):
            logger.info("llm polish switched language, raw text kept")
            return None
        return out
    except Exception:
        logger.debug("llm polish failed", exc_info=True)
        return None


__all__ = ["llm_polish_text"]
