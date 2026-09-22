# Le VPS — ce qu'une session doit savoir avant d'y toucher

**Ce serveur n'est pas à nous seuls.** Il fait tourner `flashprime.online` en
production. Constaté le 22 septembre 2026, avant la première installation.

| | |
|---|---|
| Hôte | `srv1852797.hstgr.cloud` — `2.24.81.241` (Hostinger, Boston) |
| Système | Ubuntu 24.04 LTS, 2 vCPU, 8 Go, 100 Go |
| Accès | `ssh diapason-vps` (clé `~/.ssh/diapason_vps`, entrée dans `~/.ssh/config`) |

## Ce qui tournait déjà, et qui ne doit pas s'arrêter

Six conteneurs Docker en `restart=unless-stopped`, debout depuis huit semaines :
`flashprime-prod-web` (127.0.0.1:3000), `-admin` (3001), `-api` (4000),
`-minio` (9000), `-postgres` (PostgreSQL 16) et `-redis`. Devant eux, **nginx**
sur 80/443 avec `/etc/nginx/sites-available/flashprime` (six blocs `server`,
174 lignes) et un certificat Let's Encrypt couvrant `flashprime.online`,
`www.`, `admin.` et `api.`. `certbot.timer` est actif et passe deux fois par
jour. Un agent Monarx surveille la machine.

## Trois règles

1. **Ne jamais éditer `sites-available/flashprime`.** Diapason a son fichier.
2. **`nginx -t` avant tout `reload`.** Une configuration refusée qui part en
   rechargement, et flashprime.online tombe.
3. **Un instantané avant chaque étape qui installe ou modifie** (panneau
   Hostinger → « Snapshot et sauvegardes »). Les sauvegardes automatiques sont
   hebdomadaires : entre deux, il n'y a que l'instantané.

## Pourquoi les fichiers nginx commencent par `zz-`

nginx charge `sites-enabled/*` dans l'ordre alphabétique, et le **premier**
bloc `server` d'une adresse d'écoute devient son serveur par défaut — celui
qui reçoit le trafic dont l'en-tête `Host` ne correspond à rien, dont les
visites sur l'IP brute. Aucun `default_server` n'est déclaré ici : c'est donc
l'ordre des fichiers qui tranche. Un fichier nommé `diapason` passerait avant
`flashprime` et détournerait ce trafic. Le préfixe lui rend son rang.

## Ce que Diapason occupe

- `/var/www/diapason` — le site statique (documentation MkDocs construite).
- `/var/www/diapason-acme` — la racine du défi ACME, **hors** du site : le
  `rsync --delete` du déploiement effacerait sinon le jeton en plein
  renouvellement.
- `/etc/nginx/sites-available/zz-diapason` — la configuration, liée depuis
  `sites-enabled/`.

## Publier

```bash
./deploy/vps/deployer-site.sh
```

Construit la documentation, la synchronise, vérifie `nginx -t` et l'accès HTTP.
