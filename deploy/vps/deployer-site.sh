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

# Le site se construit depuis l'ARBRE DE TRAVAIL : tout ce qui traîne dans
# docs/ part en ligne, commité ou non. Le 22/09/2026, le document de
# conception d'une autre session — non commité, absent de GitHub — s'est
# retrouvé publié. Une session ne publie plus sans savoir ce qu'elle publie.
cd "$DEPOT"
sales="$(git status --porcelain -- docs/ | head -20)"
if [ -n "$sales" ]; then
  echo "⚠ docs/ porte des modifications non commitées — elles PARTIRONT en ligne :"
  echo "$sales" | sed 's/^/    /'
  if [ "${DIAPASON_PUBLIER_QUAND_MEME:-}" != "1" ]; then
    echo "  Relance avec DIAPASON_PUBLIER_QUAND_MEME=1 si c'est voulu." >&2
    exit 1
  fi
fi

echo "→ construction de la documentation"
.venv/bin/python -m mkdocs build --clean --quiet

taille="$(du -sh site | cut -f1)"
fichiers="$(find site -type f | wc -l | tr -d ' ')"
echo "  $fichiers fichiers, $taille"

echo "→ publication vers $HOTE:$RACINE"
ssh "$HOTE" "mkdir -p $RACINE /var/www/diapason-acme && chown -R www-data:www-data $RACINE /var/www/diapason-acme"
# Pas de « --info=… » : le rsync livré avec macOS (openrsync) ne le connaît
# pas et sort sur son mode d'emploi — transfert vide, sans erreur lisible
# si la sortie est filtrée (22/09/2026).
# Les guides sous docs/, la vitrine à la racine. L'exclusion est vitale :
# sans elle, le --delete de la vitrine emporterait les 945 fichiers des guides.
rsync -az --delete --stats "$DEPOT/site/" "$HOTE:$RACINE/docs/" | grep -E "files transferred|Total transferred" || true
rsync -az --delete --exclude "/docs" --stats "$DEPOT/deploy/vps/accueil/" "$HOTE:$RACINE/" | grep -E "files transferred|Total transferred" || true
ssh "$HOTE" "chown -R www-data:www-data $RACINE"

echo "→ vérification"
ssh "$HOTE" "nginx -t" 2>&1 | sed 's/^/  /'
code="$(curl -s -o /dev/null -w '%{http_code}' https://diapason.flashprime.online/ || echo 000)"
echo "  https://diapason.flashprime.online/ → $code"
[ "$code" = "200" ] || echo "  (200 attendu ; si le certificat n'est pas encore émis, c'est normal)"
