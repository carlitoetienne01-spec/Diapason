#!/usr/bin/env bash
# Construit la documentation et la publie sur diapason.flashprime.online.
#
# 22/09/2026. Le VPS fait tourner flashprime.online EN PRODUCTION (six
# conteneurs, nginx, PostgreSQL) : ce script ne touche qu'à /var/www/diapason
# et ne recharge nginx que si sa configuration a changé ET que « nginx -t »
# l'accepte. Voir deploy/vps/README.md.
set -euo pipefail

HOTE="${DIAPASON_VPS_HOST:-diapason-vps}"
RACINE="/var/www/diapason"
DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Une faute de frappe ici effacerait le site de quelqu'un d'autre : le chemin
# est vérifié avant que « rsync --delete » ne parte.
case "$RACINE" in
  /var/www/diapason) ;;
  *) echo "✗ RACINE inattendue : $RACINE" >&2; exit 1 ;;
esac

echo "→ construction de la documentation"
cd "$DEPOT"
.venv/bin/python -m mkdocs build --clean --quiet

taille="$(du -sh site | cut -f1)"
fichiers="$(find site -type f | wc -l | tr -d ' ')"
echo "  $fichiers fichiers, $taille"

echo "→ publication vers $HOTE:$RACINE"
ssh "$HOTE" "mkdir -p $RACINE /var/www/diapason-acme && chown -R www-data:www-data $RACINE /var/www/diapason-acme"
rsync -az --delete --info=stats1 "$DEPOT/site/" "$HOTE:$RACINE/"
ssh "$HOTE" "chown -R www-data:www-data $RACINE"

echo "→ vérification"
ssh "$HOTE" "nginx -t" 2>&1 | sed 's/^/  /'
code="$(curl -s -o /dev/null -w '%{http_code}' https://diapason.flashprime.online/ || echo 000)"
echo "  https://diapason.flashprime.online/ → $code"
[ "$code" = "200" ] || echo "  (200 attendu ; si le certificat n'est pas encore émis, c'est normal)"
