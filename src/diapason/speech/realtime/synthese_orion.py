"""Préfixes causaux d'Orion, avec le contexte du décodeur complet.

Boucle ICL adaptée de MLX Audio 0.5.6 (Prince Canuma et contributeurs,
licence MIT). Le runtime privé fixe cette version ; ni poids ni tirages
du modèle ne changent. MLX n'est importé que dans l'ouvrier natif.

Copyright (c) 2024 Prince Canuma
Copyright (c) 2025, Prince Canuma and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import math
import time
from collections import deque

# 16 codes à 12,5 Hz donnent 1,28 s de réserve à la première émission.
# Les anciens paquets de 480 ms manquaient de réserve. Le décodage
# incrémental conserve la référence et les frontières du décodeur complet.
CODES_PAR_PREFIXE = 16
# Garder 15 % de marge avant d'autoriser une lecture anticipée. Sinon la
# phrase reste entière en tampon : on ne remet pas les trous de 480 ms.
RATIO_CALCUL_MAX = 0.85


def prefixe_assez_rapide(secondes_calcul: float, secondes_audio: float) -> bool:
    return 0 <= secondes_calcul <= secondes_audio * RATIO_CALCUL_MAX


def cout_prochain_prefixe(
    durees_codes, decodage: float, nombre_codes: int = CODES_PAR_PREFIXE
) -> float:
    # Le premier pas relit le contexte du timbre. Le refacturer à chaque
    # paquet condamnait le flux alors que les suivants tenaient la lecture.
    # Douze codes = les 960 dernières ms de son. Le décodeur reçoit un
    # préfixe plus long au passage suivant : coût majoré de 20 %, contrôlé
    # à nouveau au passage suivant et amorti par la taille adaptée du lot.
    recentes = list(durees_codes)[-12:]
    if not recentes:
        return float("inf")
    return sum(recentes) / len(recentes) * nombre_codes + decodage * 1.2


def taille_prochain_prefixe(durees_codes, decodage: float) -> int:
    # 27/09/2026 : sur 27,6 s de parole, redécoder tous les 24 codes
    # coûtait 30 s et vidait la réserve. Espacer les décodages amortit leur
    # coût fixe. Des pas de 12 codes (960 ms de son) évitent de changer la
    # taille à chaque fluctuation ; 96 codes bornent le lot à 7,68 s.
    recentes = list(durees_codes)[-12:]
    par_code = sum(recentes) / len(recentes) if recentes else 0.08
    marge = 0.08 * RATIO_CALCUL_MAX - par_code
    if marge <= 0:
        return 96
    necessaires = math.ceil(decodage * 1.2 / marge / 12) * 12
    return min(96, max(CODES_PAR_PREFIXE, necessaires))


def generer(modele, texte: str, reference: str, texte_reference: str, mesures=None):
    """Produire du PCM fidèle, anticipé seulement si le calcul tient la lecture."""
    import mlx.core as mx
    import numpy as np
    from decodeur_orion import DecodeurOrion
    from mlx_audio.utils import load_audio

    debut = time.monotonic()
    if mesures is None:
        mesures = {}
    mesures["mode"] = "complete"
    mx.random.seed(84)
    ref_audio = load_audio(reference, sample_rate=modele.sample_rate)
    entrees, texte_suivant, remplissage, codes_reference = (
        modele._prepare_icl_generation_inputs(
            text=texte,
            ref_audio=ref_audio,
            ref_text=texte_reference,
            language="French",
        )
    )
    if modele.sample_rate != 24000:
        raise ValueError("Fréquence inattendue")
    cache = modele.talker.make_cache()
    predicteur = modele.talker.code_predictor
    cache_codes = predicteur.make_cache()
    config = modele.config.talker_config
    fin_phrase = config.codec_eos_token_id
    interdits = [
        n for n in range(config.vocab_size - 1024, config.vocab_size) if n != fin_phrase
    ]
    codes = []
    jetons = []
    index_texte = 0
    emis = 0
    durees_codes = deque(maxlen=12)
    prochain_decodage = CODES_PAR_PREFIXE
    codes_decodes = 0
    pcm_complet = bytearray()
    decodeur = DecodeurOrion(
        modele.speech_tokenizer.decoder.chunked_decode.__self__, codes_reference
    )
    mesures["prepareMs"] = round((time.monotonic() - debut) * 1000)

    def decoder(*, termine=False):
        nonlocal codes_decodes
        if len(codes) > codes_decodes or termine:
            nouveaux = (
                mx.stack(codes[codes_decodes:], axis=2)
                if len(codes) > codes_decodes
                else mx.zeros((1, codes_reference.shape[1], 0), codes_reference.dtype)
            )
            audio = decodeur.decoder(nouveaux, termine=termine)[0, 0]
            valeurs = np.asarray(audio).reshape(-1)
            if not np.isfinite(valeurs).all():
                raise ValueError("Audio non fini")
            pcm_complet.extend(
                (np.clip(valeurs, -1, 1) * 32767).astype("<i2").tobytes()
            )
            codes_decodes = len(codes)
        return bytes(pcm_complet)

    try:
        # Même plafond que la synthèse complète. L'atteindre est un échec,
        # jamais une phrase déclarée terminée alors qu'elle est tronquée.
        for _ in range(900):
            debut_code = time.monotonic()
            logits, cache_hidden = modele.talker(entrees, cache=cache)
            suivant = modele._sample_token(
                logits,
                temperature=0.6,
                top_k=50,
                top_p=1.0,
                repetition_penalty=1.5,
                generated_tokens=jetons or None,
                suppress_tokens=interdits,
            )
            termine = suivant[0, 0] == fin_phrase
            groupe = [suivant]
            cache_hidden = cache_hidden[:, -1:, :]
            for c in cache_codes:
                # La lecture ne voit que les entrées réécrites jusqu'à
                # offset. Réallouer les mêmes buffers à chaque code était
                # inutile ; l'état de la phrase n'est jamais partagé.
                c.offset = 0
            for index in range(config.num_code_groups - 1):
                if index == 0:
                    embedding = modele.talker.get_input_embeddings()(suivant)
                    entree_code = mx.concatenate([cache_hidden, embedding], axis=1)
                else:
                    entree_code = predicteur.codec_embedding[index - 1](groupe[-1])
                logits_code, cache_codes, _ = predicteur(
                    entree_code, cache=cache_codes, generation_step=index
                )
                groupe.append(
                    modele._sample_token(
                        logits_code, temperature=0.6, top_k=50, top_p=1.0
                    )
                )
            tous_codes = mx.concatenate(groupe, axis=1)
            if index_texte < texte_suivant.shape[1]:
                portion = texte_suivant[:, index_texte : index_texte + 1, :]
                index_texte += 1
            else:
                portion = remplissage
            embedding = modele.talker.get_input_embeddings()(suivant)
            for index, code in enumerate(groupe[1:]):
                embedding = embedding + predicteur.codec_embedding[index](code)
            entrees = portion + embedding
            mx.eval(entrees, termine)
            if not codes:
                mesures["firstCodeMs"] = round((time.monotonic() - debut_code) * 1000)
            durees_codes.append(time.monotonic() - debut_code)
            if termine.item():
                break
            jetons.append(int(suivant[0, 0]))
            codes.append(tous_codes)
            if len(codes) >= prochain_decodage:
                # Sous concurrence, les codes seuls dépassaient parfois
                # la durée du son. Décoder alors un préfixe inutilisable
                # ajoutait du travail avant le repli. Réévaluer 12 codes
                # plus loin ; la fin de phrase garde son décodage complet.
                if not emis and not prefixe_assez_rapide(
                    cout_prochain_prefixe(durees_codes, 0), CODES_PAR_PREFIXE * 0.08
                ):
                    prochain_decodage = len(codes) + 12
                    continue
                debut_decodage = time.monotonic()
                pcm = decoder()
                decodage = time.monotonic() - debut_decodage
                taille = taille_prochain_prefixe(durees_codes, decodage)
                prochain_decodage = len(codes) + taille
                cout = cout_prochain_prefixe(durees_codes, decodage, taille)
                if not emis:
                    mesures["prefixMs"] = round((time.monotonic() - debut) * 1000)
                    mesures["nextMs"] = round(cout * 1000)
                    mesures["decodeMs"] = round(decodage * 1000)
                if not emis and not prefixe_assez_rapide(cout, taille * 0.08):
                    # 27/09/2026 : un ralentissement concurrent condamnait
                    # toute la phrase, même après le retour à un calcul
                    # rapide. Recontrôler le rythme, sans rien jouer tant
                    # que la réserve et la marge ne couvrent pas la suite.
                    prochain_decodage = len(codes) + CODES_PAR_PREFIXE
                elif not emis and not prefixe_assez_rapide(cout, len(pcm) / 48000):
                    # 27/09/2026 : un premier lot un peu lent condamnait
                    # toute la phrase. Accumuler un lot supplémentaire
                    # peut suffire à couvrir le prochain lot, plus grand.
                    prochain_decodage = len(codes) + CODES_PAR_PREFIXE
                else:
                    mesures["mode"] = "prefix"
                    nouveau = pcm[emis:]
                    emis = len(pcm)
                    if nouveau:
                        yield nouveau
        else:
            raise ValueError("Synthèse incomplète")
        if not codes:
            raise ValueError("Synthèse vide")
        pcm = decoder(termine=True)
        if len(pcm) < emis:
            raise ValueError("Synthèse incohérente")
        if len(pcm) > emis:
            yield pcm[emis:]
    finally:
        decodeur.fermer()
        mx.clear_cache()
