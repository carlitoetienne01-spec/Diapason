#!/usr/bin/env bash
set -euo pipefail

# Bump the desktop app version across all 3 config files.
# Usage: ./scripts/bump-desktop-version.sh <semver>
# Example: ./scripts/bump-desktop-version.sh 1.0.1

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 1.0.1"
  exit 1
fi

VERSION="$1"

# Validate semver (major.minor.patch, optional pre-release)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo "Error: '$VERSION' is not a valid semver (expected X.Y.Z or X.Y.Z-pre)"
  exit 1
fi

FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"

# 1. package.json
node -e "
  const fs = require('fs');
  const path = '${FRONTEND_DIR}/package.json';
  const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
  pkg.version = '${VERSION}';
  fs.writeFileSync(path, JSON.stringify(pkg, null, 2) + '\n');
"
echo "Updated frontend/package.json -> ${VERSION}"

# 2. tauri.conf.json
node -e "
  const fs = require('fs');
  const path = '${FRONTEND_DIR}/src-tauri/tauri.conf.json';
  const conf = JSON.parse(fs.readFileSync(path, 'utf8'));
  conf.version = '${VERSION}';
  fs.writeFileSync(path, JSON.stringify(conf, null, 2) + '\n');
"
echo "Updated frontend/src-tauri/tauri.conf.json -> ${VERSION}"

# 3. Cargo.toml
sed -i.bak "s/^version = \".*\"/version = \"${VERSION}\"/" "${FRONTEND_DIR}/src-tauri/Cargo.toml"
rm -f "${FRONTEND_DIR}/src-tauri/Cargo.toml.bak"
echo "Updated frontend/src-tauri/Cargo.toml -> ${VERSION}"

# 4. Ce que le contrôle d'identité compare aussi — sans quoi un bump suivi
#    d'un tag mettait la CI en rouge (« version mismatch », 13 septembre
#    2026) : le paquet Python, le verrou npm (généré, mais versionné), la
#    constante du contrôle lui-même, et le verrou Cargo de l'app.
RACINE="$(cd "${FRONTEND_DIR}/.." && pwd)"
# (python3 plutôt que sed : la première occurrence seulement, et le sed de
#  macOS ne connaît pas l'adresse « 0,/re/ » de GNU.)
python3 - "${RACINE}/pyproject.toml" "${VERSION}" <<'PY'
import re, sys
chemin, version = sys.argv[1:]
texte = open(chemin).read()
texte, n = re.subn(r'^version = "[^"]*"', f'version = "{version}"', texte, count=1, flags=re.M)
assert n == 1, "pas de ligne version dans pyproject.toml"
open(chemin, "w").write(texte)
PY
echo "Updated pyproject.toml -> ${VERSION}"

node -e "
  const fs = require('fs');
  const path = '${FRONTEND_DIR}/package-lock.json';
  const lock = JSON.parse(fs.readFileSync(path, 'utf8'));
  lock.version = '${VERSION}';
  if (lock.packages && lock.packages['']) lock.packages[''].version = '${VERSION}';
  fs.writeFileSync(path, JSON.stringify(lock, null, 2) + '\n');
"
echo "Updated frontend/package-lock.json -> ${VERSION}"

sed -i.bak -E "s/^EXPECTED_VERSION = \".*\"/EXPECTED_VERSION = \"${VERSION}\"/" "${RACINE}/scripts/check_project_identity.py"
rm -f "${RACINE}/scripts/check_project_identity.py.bak"
echo "Updated scripts/check_project_identity.py -> ${VERSION}"

# Le verrou uv porte la version du paquet Python : sans ce pas, l'app
# (qui installe avec `uv sync --locked`) refusait de s'installer sur un Mac
# vierge — « The lockfile needs to be updated » — constaté à l'essai de la
# 1.0.1, le 13 septembre 2026. `uv lock` ne touche pas au venv.
(cd "${RACINE}" && uv lock -q)
echo "Updated uv.lock -> ${VERSION}"

# Le verrou Cargo porte la version de la caisse : sans ce pas, le premier
# `cargo build` de la CI le réécrit, et un `--locked` refuserait.
(cd "${FRONTEND_DIR}/src-tauri" && cargo update -q --offline -p diapason-desktop 2>/dev/null || cargo update -q -p diapason-desktop)
echo "Updated frontend/src-tauri/Cargo.lock -> ${VERSION}"

"${RACINE}/.venv/bin/python" "${RACINE}/scripts/check_project_identity.py"

echo ""
echo "Version bumped to ${VERSION} everywhere the identity check looks."
echo ""
echo "Next steps:"
echo "  git add -A pyproject.toml uv.lock scripts/check_project_identity.py frontend/package.json frontend/package-lock.json frontend/src-tauri/tauri.conf.json frontend/src-tauri/Cargo.toml frontend/src-tauri/Cargo.lock"
echo "  git commit -m \"Version ${VERSION} de l'app de bureau\""
echo "  git push origin main"
echo "  git tag desktop-v${VERSION} && git push origin desktop-v${VERSION}"
