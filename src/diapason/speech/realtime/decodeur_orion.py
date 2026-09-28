"""Décodage incrémental avec la référence et les raccords du rendu complet.

Adapté de MLX Audio 0.5.6, Prince Canuma et contributeurs, licence MIT
reproduite dans synthese_orion.py. Aucun changement des poids ou des codes.
"""

from __future__ import annotations

import hashlib
import weakref

_AMORCE = None
# Seize codes = 1,28 s : plus petit, le noyau numérique ne conserve plus
# le PCM court témoin (banc natif du 27/09/2026, essai de douze codes).
CODES_MINIMUM = 16


def raccorder_sur_echantillonnage(couche, entree):
    import mlx.core as mx

    contexte = 0
    if couche._overflow is not None:
        entree = mx.concatenate([couche._overflow, entree], axis=1)
        contexte = couche.trim_right
    sortie = couche.conv(entree)
    if couche.trim_right > 0:
        # 27/09/2026 : streaming_step additionnait deux convolutions AVEC
        # biais au raccord. Jusqu'à 8498 niveaux PCM16 d'écart avec le rendu
        # complet. Même sans le double biais, l'addition de sorties arrondies
        # diffère. Les noyaux natifs font deux fois le pas : relire UNE entrée
        # à gauche permet une seule convolution, sans addition au raccord.
        couche._overflow = entree[:, -1:, :]
        sortie = sortie[:, contexte : -couche.trim_right, :]
    return sortie


class DecodeurOrion:
    """Un état par phrase, avec seulement l'amorce de référence réutilisable."""

    def __init__(self, decodeur, reference):
        import mlx.core as mx
        import numpy as np

        global _AMORCE
        self.decodeur = decodeur
        self.position = 0
        self.termine = False
        self.historique = reference[:, :, :0]
        self.en_attente = reference[:, :, :0]
        decodeur.reset_streaming_state()
        self.couches = [getattr(c, "couche", c) for c in decodeur.decoder]
        valeurs = np.asarray(reference)
        signature = (
            valeurs.shape,
            valeurs.dtype.str,
            hashlib.sha256(valeurs.tobytes()).digest(),
        )
        if _AMORCE is not None and _AMORCE[0]() is decodeur and _AMORCE[1] == signature:
            _, _, buffers, caches = _AMORCE
            modules = dict(decodeur.named_modules())
            for nom, attribut, valeur in buffers:
                setattr(modules[nom], attribut, mx.array(valeur))
            decodeur._transformer_cache = decodeur.pre_transformer.make_cache()
            for cache, etat in zip(decodeur._transformer_cache, caches, strict=True):
                cache.state = tuple(mx.array(v) for v in etat)
            self.position = reference.shape[2]
            self.historique = reference[:, :, -25:]
        else:
            self.decoder(reference, retenir_queue=False)  # ne jamais émettre ce son
            buffers = []
            for nom, module in decodeur.named_modules():
                for attribut in ("_buffer", "_overflow"):
                    valeur = getattr(module, attribut, None)
                    if valeur is not None:
                        buffers.append((nom, attribut, mx.array(valeur)))
            caches = [
                tuple(mx.array(v) for v in c.state) for c in decodeur._transformer_cache
            ]
            mx.eval(*[v for _, _, v in buffers], *[v for etat in caches for v in etat])
            # Une seule référence en mémoire, sans conserver les sorties des
            # conversations. Les copies évitent que le KV du tour suivant
            # réécrive l'amorce et fasse dériver le timbre de phrase en phrase.
            _AMORCE = (weakref.ref(decodeur), signature, buffers, caches)

    def _pas(self, codes):
        import mlx.core as mx

        d = self.decodeur
        if d._transformer_cache is None:
            d._transformer_cache = d.pre_transformer.make_cache()
        courant = mx.transpose(d.quantizer.decode(codes), (0, 2, 1))
        courant = d.pre_conv.step(courant)
        courant = d.pre_transformer(courant, cache=d._transformer_cache)
        for couches in d.upsample:
            courant = couches[0](courant)
            courant = couches[1].step(courant)
        courant = self.couches[0].step(courant)
        mx.eval(courant)
        for bloc in self.couches[1:-2]:
            courant = bloc.block[0](courant)
            courant = raccorder_sur_echantillonnage(bloc.block[1], courant)
            for unite in bloc.block[2:]:
                courant = unite.step(courant)
            mx.eval(courant)
        courant = self.couches[-2](courant)
        courant = self.couches[-1].step(courant)
        son = mx.clip(mx.transpose(courant, (0, 2, 1)), -1.0, 1.0)
        mx.eval(son)
        return son

    def decoder(self, codes, *, termine=False, retenir_queue=True):
        import mlx.core as mx

        if self.termine:
            raise ValueError("La phrase du décodeur est déjà terminée")
        codes = mx.concatenate([self.en_attente, codes], axis=2)
        self.en_attente = codes[:, :, :0]
        morceaux = []
        lus = 0
        while lus < codes.shape[2]:
            taille = min(codes.shape[2] - lus, 300 - self.position % 300)
            partie = codes[:, :, lus : lus + taille]
            fin_bloc = (self.position + taille) % 300 == 0
            if (
                taille < CODES_MINIMUM
                and not fin_bloc
                and not termine
                and retenir_queue
            ):
                # Un lot traversant 300 laissait six codes seuls après le
                # raccord. Les joindre au prochain lot conserve le même
                # noyau numérique. La réserve de lecture couvre cette queue.
                self.en_attente = partie
                break
            if self.position and self.position % 300 == 0:
                # Même frontière que chunked_decode : 300 codes, avec les
                # 25 précédents relus après remise à zéro du décodeur.
                # Ne le faire qu'après la décision de retenir la queue,
                # sinon son arrivée fait recalculer deux fois cette amorce.
                self.decodeur.reset_streaming_state()
                self._pas(self.historique)
            if (termine or fin_bloc) and taille < CODES_MINIMUM:
                # Une très petite queue (8–9 codes) choisit un autre noyau
                # numérique et amplifie les arrondis. Compléter le calcul
                # causal, puis ne garder QUE les échantillons réels. Aucun
                # son ajouté ; cet état ne peut plus servir à une suite.
                complete = mx.concatenate(
                    [
                        partie,
                        mx.zeros(
                            (1, partie.shape[1], CODES_MINIMUM - taille), partie.dtype
                        ),
                    ],
                    axis=2,
                )
                son = self._pas(complete)[:, :, : taille * self.decodeur.total_upsample]
            else:
                son = self._pas(partie)
            morceaux.append(son)
            self.historique = mx.concatenate([self.historique, partie], axis=2)[
                :, :, -25:
            ]
            self.position += taille
            lus += taille
        self.termine = termine
        if not morceaux:
            return mx.zeros((1, 1, 0))
        return mx.concatenate(morceaux, axis=-1)

    def fermer(self):
        self.decodeur.reset_streaming_state()
