"""Generate canonical-encoding vectors for the Diapason mobile mesh client.

Run me whenever ``canonical_bytes`` changes shape, and commit the result in
the Flutter repo:

    .venv/bin/python scripts/gen_canonical_vectors.py [chemin/de/sortie.json]

The vectors come from the REAL implementation.

The Dart side has to produce these bytes exactly. Anything else and every
signature fails, with nothing in any error message to explain why.
"""

import json
import pathlib
import sys

from diapason.mesh.identity import canonical_bytes
from diapason.mesh.sessions import SESSION_REQUEST_FIELDS, build_session_request

CASES = [
    {"b": 2, "a": 1},
    {
        "version": 1,
        "ownerId": "owner_abc",
        "deviceId": "dev_x",
        "sentAtMs": 1755300000000,
    },
    {"capabilities": ["app.open", "app.navigate", "notifications.show"]},
    {"nom": "MacBook de Carlito"},
    {"accent": "Bilan du soir — n'oublie pas « Succes »"},
    {"emoji": "\U0001f4f1 releve"},
    {"vide": "", "nul": None, "vrai": True, "faux": False},
    {"imbrique": {"z": [1, {"y": "x"}], "a": {}}},
    {"guillemets": 'il a dit "oui"', "backslash": "a\\b", "saut": "a\nb\tc"},
    {"controle": "\x01\x1f"},
    {"unicode_haut": "\U0001d11e cle de sol"},
    {"arguments": {"route": "success://notes/n-1"}, "tool": "app.navigate"},
    {"negatif": -42, "zero": 0, "grand": 9007199254740993},
    {"cle_accentuee": 1, "cle_zzz": 2, "cle_aaa": 3},
]


def _enveloppe_de_session() -> dict:
    """L'enveloppe ``webview-session`` telle que Python la construit.

    26/09/2026, phase 2 étape 2 : le Dart signe cette enveloppe pour ouvrir
    la session de sa WebView. Construite par ``build_session_request`` — la
    fonction réelle —, à l'heure et au nonce près, figés pour que le vecteur
    ne change pas à chaque génération. Réduite à ``SESSION_REQUEST_FIELDS`` :
    ce sont ces octets-là, et eux seuls, que ``verify_session_request`` fait
    signer.
    """
    brute = build_session_request(
        owner_id="owner_abc",
        device_id="dev_0123456789abcdef01234567",
        audience="mac-fictif0123456789",
        now=1790409600000,
    )
    brute["nonce"] = "nonce-fige-de-trente-deux-signes"
    return {cle: brute[cle] for cle in SESSION_REQUEST_FIELDS}


# Les cas NOMMÉS : le Dart retrouve le sien par son nom et vérifie, en plus
# des octets, que SON constructeur produit exactement ces clés.
NOMMES = {"enveloppe-de-session": _enveloppe_de_session()}

out = [
    {"payload": case, "expected": canonical_bytes(case).decode("utf-8")}
    for case in CASES
] + [
    {"nom": nom, "payload": case, "expected": canonical_bytes(case).decode("utf-8")}
    for nom, case in NOMMES.items()
]
path = pathlib.Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "~/Projets/diapason_mobile/test/mesh/canonical_vectors.json"
).expanduser()
path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(out)} vecteurs ecrits depuis l'implementation Python reelle")
for entry in out[:4]:
    print("  ", entry["expected"])
