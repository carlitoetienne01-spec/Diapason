"""Restreindre un fichier à son propriétaire — là où cela veut dire quelque chose.

26 août 2026. Trois endroits du dépôt écrivaient un secret sur le disque et
tentaient d'en restreindre l'accès avec ``os.fchmod(fd, 0o600)`` : la clé
d'identité du maillage, la clé d'API locale, et la politique de capacités.
Trois écritures, trois gardes différents, et deux d'entre eux faux :

* ``identity.py`` et ``auth_middleware.py`` testaient ``hasattr(os, "fchmod")``.
  Or Python 3.13 EXPOSE ce nom sur Windows, où l'appel lève invariablement
  ``PermissionError: [WinError 5]``. Tester le nom, c'est confondre « la
  fonction est là » avec « l'opération marche ».
* ``capabilities.py`` n'avait aucun garde du tout.

Constaté sur le PC de Carlito au premier jumelage : ``device_identity()``
levait, et comme presque tout le maillage l'appelle, RIEN ne fonctionnait sur
Windows. La clé d'API du serveur serait tombée sur la même pierre.

**Ce que Windows fait à la place, et ce que nous n'y faisons donc pas.** Les
bits POSIX n'y gouvernent pas l'accès : les ACL le font. Les fichiers
concernés vivent sous ``%LOCALAPPDATA%``, dont l'ACL par défaut n'accorde
l'accès qu'à l'utilisateur, à SYSTEM et aux administrateurs. La protection est
donc RÉELLE mais HÉRITÉE — pas posée par nous. Le dire ainsi vaut mieux que
de laisser croire qu'on l'a exigée : le jour où quelqu'un déplacera ces
fichiers hors du profil utilisateur, cette page sera la seule à l'avoir prévenu.
"""

from __future__ import annotations

import os

__all__ = ["POSIX", "restreindre_au_proprietaire"]

# Le seul test qui vaille : la plateforme, jamais l'existence du nom.
POSIX = os.name != "nt"


def restreindre_au_proprietaire(descriptor: int) -> None:
    """Poser 0600 sur un descripteur — sans effet là où cela n'a pas de sens.

    Silencieux sur Windows PAR CONCEPTION, et c'est la seule exception que ce
    module s'autorise : il n'y a rien à faire, pas quelque chose qui a échoué.
    Sur POSIX, en revanche, un échec REMONTE : ne pas réussir à restreindre un
    fichier de clé y est une vraie perte de confidentialité, et l'avaler
    laisserait un secret lisible par tous sans que personne ne le sache.
    """
    if POSIX:
        os.fchmod(descriptor, 0o600)
