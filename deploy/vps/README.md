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

## Quatre règles

1. **Ne jamais éditer `sites-available/flashprime`.** Diapason a son fichier.
2. **`nginx -t` avant tout `reload`.** Une configuration refusée qui part en
   rechargement, et flashprime.online tombe.
3. **L'instantané Hostinger appartient à la machine entière — jamais sans le
   propriétaire de Flashprime.** Cette règle disait l'inverse jusqu'au
   24 septembre 2026 (« un instantané avant chaque étape ») et elle était
   dangereuse. D'après les pages de support Hostinger relevées par la revue
   d'exploitation — à confirmer dans le panneau —, un VPS ne garde **qu'un
   seul** instantané : en créer un écrase celui qui existe, peut-être celui de
   Flashprime. Et **restaurer réécrit tout le disque** : PostgreSQL, l'API, le
   web, l'admin, MinIO et Redis de Flashprime reviendraient en arrière avec
   Diapason. Un instantané n'est donc pas un retour arrière pour Diapason.
   Chaque étape de Diapason sur ce VPS a son propre retour arrière local,
   idempotent, essayé d'abord sur une VM jetable (voir
   `docs/development/compte-chiffre.md`, §3.9). Les sauvegardes automatiques
   de Hostinger sont hebdomadaires et couvrent, elles aussi, toute la machine.
4. **Ne pas redémarrer sans prévenir Flashprime.** Le 24 septembre 2026, la
   bannière de connexion affiche « System restart required » et trente mises
   à jour en attente. Redémarrer coupe aussi flashprime.online : c'est à
   planifier avec son propriétaire, à une heure creuse.

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
- `/etc/diapason/mail.env` — la clé d'API Resend (permission *Sending access*,
  restreinte au domaine `diapason.flashprime.online`) et `MAIL_FROM`, en
  `600 root:root` dans un dossier `700`. Déposée le 24 septembre 2026 par
  Carlito lui-même, sans passer par une session. **Ne jamais l'afficher**
  (`cat`), et ne pas la `source`r en bash : la valeur de `MAIL_FROM` contient
  `<` et `>`, que bash lit comme des redirections. Le format `CLÉ=valeur` est
  celui de systemd (`EnvironmentFile=`), de Docker (`--env-file`) et de
  python-dotenv. Pour vérifier la clé sans la lire, appeler
  `GET https://api.resend.com/domains` avec elle : une clé valide et limitée
  à l'envoi répond `restricted_api_key`. Une clé douteuse ne se répare pas :
  on la supprime dans Resend et on en crée une autre.

## Le courrier — la zone DNS est partagée, elle aussi

La zone `flashprime.online` est chez Hostinger (serveurs de noms
`helios.dns-parking.com` et `aster.dns-parking.com`), et **Flashprime y envoie
déjà son courrier par Resend, depuis l'apex**. Constaté le 24 septembre 2026,
avant la première saisie pour Diapason :

| Nom | Type et valeur | À qui |
|---|---|---|
| `@` | MX `10 inbound-smtp.us-east-1.amazonaws.com` | Flashprime — courrier entrant |
| `resend._domainkey` | TXT, clé DKIM | Flashprime |
| `send` | MX `10 feedback-smtp.us-east-1.amazonses.com` | Flashprime — rebonds |
| `send` | TXT `v=spf1 include:amazonses.com ~all` | Flashprime — SPF |
| `_dmarc` | TXT `v=DMARC1; p=none;` | Flashprime, et le sous-domaine par héritage |
| `diapason` | A `2.24.81.241` | Diapason — le site |
| `resend._domainkey.diapason` | TXT, clé DKIM | Diapason |
| `send.diapason` | CNAME `send.forge.rmta.net` | Diapason — Return-Path |
| `rsend.diapason` | CNAME `rsend.forge.rmta.net` | Diapason — Return-Path de secours |

Les noms de Diapason ne diffèrent de ceux de Flashprime que par `.diapason`,
et c'est là que tout peut casser :

- **Un TXT tapé `resend._domainkey`, sans le suffixe, n'est pas refusé.** Le
  DNS accepte plusieurs TXT sur un même nom : la clé s'ajouterait à côté de
  celle de Flashprime, dont la signature DKIM échouerait alors. Hostinger ne
  refuse qu'un CNAME en conflit — le seul cas où le filet existe.
- **En cas de conflit, la documentation de Resend conseille de supprimer
  l'existant.** Sur `send`, ce serait le SPF et les rebonds de Flashprime. On
  ne suit pas ce conseil ici : on corrige le nom tapé.
- Le guide Hostinger de Resend décrit l'ancien format (MX + TXT sur `send`),
  et son tableau DKIM indique le nom `send` par erreur. Seul l'onglet
  *Records* du domaine dans Resend fait foi.

Règles, en plus des quatre ci-dessus :

- **Ajouter, jamais modifier ni supprimer** une ligne de Flashprime.
- **Photographier la zone avant, comparer après**, sur les DEUX serveurs
  autoritaires et sans récursion (`dig +norec @aster.dns-parking.com …`).
  Le numéro de série SOA de Hostinger n'augmente pas forcément après une
  saisie (resté à `2026092401` le 24/09) : on juge sur les lignes elles-mêmes.
  La clé DKIM de Diapason commence par les mêmes quarante caractères que
  celle de Flashprime : on compare octet par octet, jamais à l'œil.
- **Pas de MX sur `diapason`** tant que Diapason ne traite pas le courrier
  entrant. Chaque courriel reçu compte dans le quota de Resend, et accepter du
  courrier que personne ne lit est une promesse en attente (§5). Sans MX, un
  courriel adressé à `…@diapason.flashprime.online` expire en quelques jours :
  rien n'écoute sur le port 25, et ufw ne l'ouvre pas. Les courriels envoyés
  porteront donc un `Reply-To` vers une boîte réellement lue.

Le domaine `diapason.flashprime.online` est **vérifié chez Resend depuis le
24 septembre 2026** — envoi seul, réception désactivée.

## Publier

```bash
./deploy/vps/deployer-site.sh
```

Construit la documentation, la synchronise, vérifie `nginx -t` et l'accès HTTP.
