"""Les collections que le moteur de synchronisation sait transporter (§4.8).

Conception : ``docs/development/compte-chiffre.md`` §4.7 et §4.8.

:data:`COLLECTIONS_SYNCHRONISEES` est une liste BLANCHE, calquée sur
``SYNC_ENTITIES`` (``vie/sync.py``). Un objet dont le clair nomme une
collection absente d'ici n'est ni ingéré ni perdu : il attend dans la table
``inconnus`` de ``etat.key``, et l'écran dit « mettez Diapason à jour ». Une
liste NOIRE aurait laissé la première collection ajoutée par une version
plus récente de l'app s'écrire, avec un schéma inconnu, dans une base que
cette version ne sait pas lire.

La v1 ne transporte que les conversations. Le test-fusible
``test_jamais_synchronise.py`` (§4.8) dira ce qui ne doit jamais entrer ici.
"""

from __future__ import annotations

__all__ = ["COLLECTIONS_SYNCHRONISEES"]

COLLECTIONS_SYNCHRONISEES = frozenset({"conversations"})
