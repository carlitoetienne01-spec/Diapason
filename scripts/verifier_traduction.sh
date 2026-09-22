#!/usr/bin/env bash
# Compare une page traduite à son original : titres, blocs de code, longueur.
#
# 22/09/2026. Une traduction de 11 571 mots est revenue amputée de quatre-vingts
# blocs de code et de vingt titres, sans que rien ne le signale : un agent qui
# relit sa propre sortie ne compte pas. Ce contrôle-ci compte.
#
# Les titres se comptent HORS des blocs de code : « # Installer Ollama », en
# commentaire bash dans un bloc, n'est pas un titre — la première version en
# comptait trois de trop sur une page parfaitement traduite.
set -u
fr="$1"; o="${fr%.fr.md}.md"
[ -f "$o" ] || { echo "✗ original introuvable : $o"; exit 1; }

titres() { awk '/^```/ {dans = !dans; next} !dans && /^#+ / {n++} END {print n+0}' "$1"; }

th=$(titres "$o"); tf=$(titres "$fr")
ch=$(grep -c '^```' "$o"); cf=$(grep -c '^```' "$fr")
mo=$(wc -w < "$o" | tr -d ' '); mf=$(wc -w < "$fr" | tr -d ' ')
pct=$(( (mf - mo) * 100 / mo ))
faute=0
[ "$th" != "$tf" ] && { echo "✗ $(basename "$fr") — titres : $th dans l'original, $tf dans la traduction"; faute=1; }
[ "$ch" != "$cf" ] && { echo "✗ $(basename "$fr") — blocs de code : $ch dans l'original, $cf dans la traduction"; faute=1; }
[ "$pct" -lt 0 ] && { echo "✗ $(basename "$fr") — longueur : $pct % ; le français allonge, il ne raccourcit pas"; faute=1; }
[ "$faute" = 0 ] && echo "✓ $(basename "$fr") — $tf titres, $cf blocs, $pct %"
exit "$faute"
