"""Generate canonical-encoding vectors for the Succès Flutter mesh client.

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

out = [
    {"payload": case, "expected": canonical_bytes(case).decode("utf-8")}
    for case in CASES
]
path = pathlib.Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "~/Desktop/Porfolio/Succes/test/mesh/canonical_vectors.json"
).expanduser()
path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(out)} vecteurs ecrits depuis l'implementation Python reelle")
for entry in out[:4]:
    print("  ", entry["expected"])
