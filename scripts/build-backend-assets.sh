#!/usr/bin/env bash
# Les trois fichiers que l'app de bureau télécharge au premier lancement
# (voir frontend/src-tauri/src/amorcage.rs), à publier avec chaque release
# `desktop-v<version>` :
#
#   diapason-src-<version>.tar.gz   le code (git archive, un dossier de tête)
#   diapason_rust-…-<cible>.whl     l'extension native précompilée
#   backend.json                    le manifeste qui nomme les deux
#
# La version est celle de l'app (tauri.conf.json) : l'app cherche son backend
# sous sa propre version, jamais sous une autre.
#
# Usage : ./scripts/build-backend-assets.sh [dossier-de-sortie]
#         (défaut : dist/backend, vidé d'abord)
#
# Pourquoi un script et pas seulement le workflow : il faut pouvoir produire
# ces fichiers ici, sur ce Mac, et tester l'amorçage contre un serveur local
# (`DIAPASON_BACKEND_URL=http://127.0.0.1:8765`) avant qu'une release existe.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SORTIE="${1:-$RACINE/dist/backend}"
cd "$RACINE"

VERSION="$(python3 -c "import json;print(json.load(open('frontend/src-tauri/tauri.conf.json'))['version'])")"
PYTHON="${PYTHON:-$RACINE/.venv/bin/python}"
MATURIN="${MATURIN:-$RACINE/.venv/bin/maturin}"
[[ -x "$PYTHON" ]] || { echo "python introuvable : $PYTHON" >&2; exit 1; }
[[ -x "$MATURIN" ]] || { echo "maturin introuvable : $MATURIN (uv pip install maturin)" >&2; exit 1; }
PY_MINEUR="$("$PYTHON" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
CIBLE="$(rustc -vV | sed -n 's/^host: //p')"

rm -rf "$SORTIE"
mkdir -p "$SORTIE"

echo "→ code source (git archive HEAD, version $VERSION)"
ARCHIVE="diapason-src-$VERSION.tar.gz"
git archive --format=tar.gz --prefix="diapason-src-$VERSION/" -o "$SORTIE/$ARCHIVE" HEAD

echo "→ extension native (maturin, Python $PY_MINEUR, cible $CIBLE)"
"$MATURIN" build --release \
  --manifest-path rust/crates/diapason-python/Cargo.toml \
  --interpreter "$PYTHON" \
  --out "$SORTIE" >/dev/null
ROUE="$(cd "$SORTIE" && ls diapason_rust-*.whl | head -1)"
[[ -n "$ROUE" ]] || { echo "aucune wheel produite" >&2; exit 1; }

echo "→ backend.json"
python3 - "$SORTIE/backend.json" "$VERSION" "$PY_MINEUR" "$ARCHIVE" "$CIBLE" "$ROUE" <<'EOF'
import json, sys
chemin, version, python, archive, cible, roue = sys.argv[1:]
json.dump(
    {"version": version, "python": python, "source": archive, "wheels": {cible: roue}},
    open(chemin, "w"),
    indent=2,
    ensure_ascii=False,
)
print(open(chemin).read())
EOF

echo
echo "✓ $SORTIE"
ls -la "$SORTIE"
