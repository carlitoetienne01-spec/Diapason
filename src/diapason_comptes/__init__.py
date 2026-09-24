"""Le service de comptes du VPS : identité, coffre, courriel, synchronisation.

Conception : ``docs/development/compte-chiffre.md`` §3. Ce paquet est le
SERVEUR ; ``diapason.compte`` est le client. Il n'importe jamais
``diapason`` : il tourne seul sur le VPS (Python 3.12.3, ``/opt/diapason``),
sans l'application de bureau, et un import croisé l'y ferait tomber au
démarrage. De ``cryptography`` il n'importe que
``hazmat.primitives.ciphers.aead`` (D19) ; un test en sous-processus le
vérifie (``tests/diapason_comptes/test_forme.py``).

Il reste absent de la roue de l'app de bureau : ``pyproject.toml`` ne
construit que ``src/diapason``.

Le VPS est un classeur aveugle : il ne voit ni mot de passe, ni clé, ni
contenu (§2.9). Ce qu'il garde, il le garde poivré ou sur-chiffré.
"""

# La version que ``/health`` annonce. Elle suit le CONTRAT du service
# (``tests/contract/compte_api_surface.json``), pas l'app de bureau.
VERSION = "1.0.0"
