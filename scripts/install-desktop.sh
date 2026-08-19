#!/usr/bin/env bash
# Compile, sauvegarde, installe et relance l'application de bureau.
#
# Ce script existe parce que le geste fait à la main laissait des traces :
# sept copies de Diapason.app dans /Applications, toutes avec le MÊME
# identifiant et la MÊME version (com.diapason.desktop, 1.0.0), donc
# indiscernables dans Spotlight. Le risque n'était pas les 123 Mo — c'était
# d'en lancer une ancienne sans le savoir.
#
# Trois règles, et elles sont le cœur du correctif :
#   1. la sauvegarde sort de /Applications, donc Spotlight ne l'indexe plus ;
#   2. il n'y en a qu'UNE, écrasée à chaque fois — un filet, pas un musée ;
#   3. l'ancienne n'est retirée qu'APRÈS que la nouvelle soit en place.
set -euo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
CIBLE="/Applications/Diapason.app"
ABRI="$HOME/.diapason/backups"
SAUVEGARDE="$ABRI/Diapason.app.precedente"
BUNDLE="$RACINE/frontend/src-tauri/target/release/bundle/macos/Diapason.app"

echo "→ compilation (Rust + Vite, quelques minutes)"
cd "$RACINE/frontend"
npm run tauri:build

[ -d "$BUNDLE" ] || { echo "✗ bundle absent : $BUNDLE" >&2; exit 1; }

echo "→ fermeture de l'application"
osascript -e 'tell application "Diapason" to quit' 2>/dev/null || true
sleep 3
pkill -f "Diapason.app/Contents/MacOS/diapason-desktop" 2>/dev/null || true
sleep 1

if [ -d "$CIBLE" ]; then
  echo "→ sauvegarde de la version en place → $SAUVEGARDE"
  mkdir -p "$ABRI"
  # Remplacer l'unique sauvegarde : en garder plusieurs, c'est refaire le
  # désordre qu'on vient de nettoyer.
  rm -rf "$SAUVEGARDE.tmp"
  mv "$CIBLE" "$SAUVEGARDE.tmp"
  rm -rf "$SAUVEGARDE"
  mv "$SAUVEGARDE.tmp" "$SAUVEGARDE"
fi

echo "→ installation"
cp -R "$BUNDLE" "$CIBLE"

echo "→ relance"
open -a "$CIBLE"
sleep 5

if pgrep -f "Diapason.app/Contents/MacOS" >/dev/null; then
  echo "✓ installée et relancée"
else
  # Ne pas prétendre que ça marche. La sauvegarde est là, on dit comment.
  echo "✗ l'application n'a pas démarré." >&2
  echo "  Restaurer :  rm -rf '$CIBLE' && cp -R '$SAUVEGARDE' '$CIBLE'" >&2
  exit 1
fi

echo
echo "  version installée : $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$CIBLE/Contents/Info.plist" 2>/dev/null)"
echo "  sauvegarde        : $SAUVEGARDE"
echo "  copies parasites  : $(ls -d /Applications/Diapason.app.* 2>/dev/null | wc -l | tr -d ' ') (doit rester 0)"
