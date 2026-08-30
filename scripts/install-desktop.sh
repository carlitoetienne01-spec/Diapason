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
# `tauri build` sort en CODE 1 alors que les bundles sont bel et bien
# produits : il signale ainsi l'absence de TAURI_SIGNING_PRIVATE_KEY, qui
# ne concerne que le mécanisme de mise à jour automatique, pas
# l'application. Avec `set -e`, ce code arrêtait tout — constaté au premier
# usage réel : compilation réussie, aucune étape suivante exécutée.
#
# On ne juge donc pas la compilation sur son code de sortie mais sur SON
# RÉSULTAT : le bundle existe-t-il, et vient-il d'être écrit ? C'est la
# question qui compte, et la seule qui ne mente pas.
avant=0
[ -d "$BUNDLE" ] && avant=$(stat -f %m "$BUNDLE" 2>/dev/null || echo 0)

set +e
npm run tauri:build
code_build=$?
set -e

if [ ! -d "$BUNDLE" ]; then
  echo "✗ compilation échouée : aucun bundle produit (code $code_build)" >&2
  exit 1
fi
apres=$(stat -f %m "$BUNDLE" 2>/dev/null || echo 0)
if [ "$apres" -le "$avant" ]; then
  echo "✗ compilation échouée : le bundle n'a pas été réécrit (code $code_build)." >&2
  echo "  Installer l'ancien serait pire que de s'arrêter ici." >&2
  exit 1
fi
[ "$code_build" -ne 0 ] && echo "  (tauri a signalé le code $code_build — bundle produit, on continue)"

# L'interface web du SERVEUR vit dans src/diapason/server/static — une COPIE
# de frontend/dist que rien ne rafraîchissait : le 22 août, le serveur servait
# une interface du 17 pendant que l'app de bureau, elle, embarquait la
# fraîche. Deux interfaces, deux âges, zéro message. La copie fait maintenant
# partie de la construction.
if [ -d "$RACINE/frontend/dist" ] && [ -f "$RACINE/frontend/dist/index.html" ]; then
  echo "→ synchronisation de l'interface web du serveur"
  rsync -a --delete "$RACINE/frontend/dist/" "$RACINE/src/diapason/server/static/"
else
  echo "✗ frontend/dist absent après la construction — interface du serveur NON rafraîchie" >&2
fi

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

# Tauri signe *ad hoc* (`signingIdentity: "-"`). Le droit Accessibilité
# s'ancre alors sur le cdhash du binaire : chaque rebuild le change,
# Réglages Système continue d'afficher Diapason coché, et
# CGPreflightPostEventAccess reste faux — constaté le 29 août 2026, case
# cochée, même erreur. Une identité Apple Development ancre le droit sur
# le certificat. Absent du trousseau, on le dit : installer l'ad hoc
# sans prévenir recréerait le piège.
identite="${DIAPASON_SIGNING_IDENTITY:-}"
if [ -z "$identite" ]; then
  identite="$(security find-identity -v -p codesigning 2>/dev/null \
    | awk -F'"' '/Apple Development|Developer ID Application/ { print $2; exit }')"
fi
if [ -n "$identite" ]; then
  echo "→ signature stable ($identite)"
  codesign --force --deep --options runtime \
    --entitlements "$RACINE/frontend/src-tauri/Entitlements.plist" \
    --sign "$identite" \
    "$CIBLE"
  exigence="$(codesign -d -r- "$CIBLE" 2>&1 || true)"
  if ! echo "$exigence" | grep -Eq 'certificate leaf|anchor apple|anchor trusted'; then
    echo "✗ la signature est encore ancrée sur le cdhash — Accessibilité ne survivra pas" >&2
    echo "$exigence" >&2
    # Le nouveau paquet est DÉJÀ en place à ce point : cette sortie laissait
    # l'utilisateur devant une application installée, un droit condamné, et
    # aucune façon affichée de revenir — la ligne de restauration n'existait
    # que dans la branche « n'a pas démarré », vingt lignes plus bas. Un
    # script qui abandonne doit dire comment défaire ce qu'il a déjà fait.
    echo "  Restaurer :  rm -rf '$CIBLE' && cp -R '$SAUVEGARDE' '$CIBLE'" >&2
    exit 1
  fi
else
  echo "⚠ aucune identité de signature dans le trousseau : le droit Accessibilité mourra au prochain rebuild" >&2
fi

echo "→ relance"
open -a "$CIBLE"
sleep 5

if pgrep -f "Diapason.app/Contents/MacOS" >/dev/null; then
  # L'artefact de compilation disparaît sitôt la copie installée : Spotlight
# indexe target/release/bundle, et l'utilisateur voyait DEUX « Diapason » —
# l'installée et le sous-produit du build — sans pouvoir les distinguer.
# Constaté le 23 août 2026, quatre entrées Diapason dans Spotlight. Le
# bundle renaît à chaque compilation ; sa place n'est pas dans l'index.
rm -rf "$BUNDLE"
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
