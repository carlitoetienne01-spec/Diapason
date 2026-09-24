"""Compte chiffré de bout en bout — les primitives.

Conception : ``docs/development/compte-chiffre.md``. Ce paquet ne contient
pour l'instant que l'étape 1 du plan (§6) : des fonctions pures, sans disque
ni réseau, que les étapes suivantes (protecteurs locaux, service VPS, moteur
de synchronisation) appelleront.

- ``cles`` : normalisations, Argon2id, séparation des clés par HKDF,
  identifiants opaques (§2.2 à §2.4, §2.6) ;
- ``enveloppe`` : le format DPE1, son AAD et son rembourrage (§2.5) ;
- ``recuperation`` : la clé de récupération et sa paire X25519 (§2.7) ;
- ``trousseau`` : le trousseau des époques et la rotation (§2.2, §2.8).

Ce fichier n'importe rien à dessein : importer ``diapason.compte`` ne doit
pas charger ``cryptography`` pour qui n'a pas de compte.
"""
