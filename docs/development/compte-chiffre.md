# Comptes chiffrés de bout en bout et synchronisation entre appareils

*Destination : `docs/development/compte-chiffre.md`, à ajouter à `exclude_docs` (`mkdocs.yml:175-192`). Conception en lecture seule, établie le 24/09/2026 sur `main` à `a8fce01` avec un arbre propre. Elle intègre trois revues : cryptographie, protocole et exploitation. Aucune ligne de code n'a été écrite. Rien n'a été fait sur le VPS.*

---

## Préambule

### Ce que sont « les points 3, 4 et 5 »

La mémoire du projet donne l'ordre convenu dans `~/.claude/projects/-Users-carlito-e-Projets-Diapason/memory/hebergement-diapason.md:29-40` :

- **point 2** : trancher le chiffrement de bout en bout. Carlito l'a tranché : le VPS ne doit jamais pouvoir lire le contenu ;
- **point 3** : les comptes côté serveur (inscription, vérification par courriel, connexion, sessions), la politique de confidentialité et les conditions ;
- **point 4** : l'écran d'activation dans l'app ;
- **point 5** : la synchronisation, en dernier.

La décision D0 de la version précédente (« quels points 3, 4 et 5 ? ») disparaît donc. La roadmap (`docs/development/roadmap.md:88-130`) numérote d'autres chantiers, sans rapport avec celui-ci. Le plan du §6 indique à quel point appartient chaque étape.

### Ce que la revue a changé

La version précédente avait **trois défauts bloquants** :

1. **Aucune clé ne tournait jamais.** Changer le mot de passe, retirer la clé de récupération ou révoquer un appareil réenveloppait la même clé maîtresse. Tout ancien secret donnait donc accès aux données présentes **et futures**.
2. **Une réinitialisation ou un changement de compte ne remettait pas à zéro l'état de synchronisation.** L'appareil pouvait afficher « Synchronisé » face à un serveur vide.
3. **L'exploitation du VPS mettait en danger la production de Flashprime.** Les sauvegardes n'avaient pas de borne en octets, et on comptait sur un instantané Hostinger qui écrase tout le disque.

Quinze défauts sérieux et une quinzaine de mineurs s'y ajoutaient. L'annexe A dit ce que devient chacun.

### Vérifié dans cette passe (lecture seule)

- `conversations_store.py:343-353` : `delete` ne lit que `deleted_at` et date la tombale `max(_now_ms(), existing or 0)`.
- `conversations_store.py:256` : la purge des tombales tourne à l'ouverture.
- `conversations_store.py:411-419` : elle efface toute tombale de plus de 30 jours, sans condition.
- `conversations_store.py:322-324` : une tombale gagne si `deleted_at >= updated_at`. Sinon la version reçue est stockée telle quelle.
- `tmutil isexcluded ~/Library/Keychains ~/.diapason` renvoie `[Included]` pour les deux.
- `.venv/.../starlette/background.py:23` : une tâche de fond synchrone passe par `run_in_threadpool`, c'est-à-dire le même pool que les routes `def`.
- `auth_middleware.py:290-326` : le limiteur exempte déjà `/v1/succes` (sauf `sync`), `/v1/chat/completions`, `/v1/conversations`, `/v1/voice/live/health` et les GET du maillage.
- `frontend/src-tauri/src/lib.rs:5770-5774` : `ExitRequested` lance `stop_all` sans `prevent_exit`.
- `frontend/src-tauri/src/lib.rs:680-688` : `stop_all` tue le serveur.
- `deploy/vps/README.md` (règle 3) : un instantané avant chaque étape. Cette règle est à corriger (§3.9).
- `PRIVACY.md:60-64` promet que `local_only` bloque « toute » sortie réseau.
- `security/file_policy.py:8-27` et `file_policy.rs:19-23` ne filtrent que **le nom du fichier**, avec des motifs comme `*.key`.
- cryptography 50.0.0 fournit :
  - `hpke.Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)`, dont `encrypt(plaintext, public_key, info)` rend 80 o pour un clair de 32 o ;
  - X25519 ;
  - `AESGCMSIV` (présent, contrairement à ce que disait la version précédente, mais inutile ici).
- Mesures sur ce Mac, reprises des revues : Argon2id à 262 144 Kio, t=3, p=4 prend 0,48 à 0,50 s ; à 131 072 Kio, 0,25 s. `XChaCha20Poly1305` est absent.

---

## 0. En douze lignes

1. **Le serveur Python local fait toute la cryptographie et parle seul au VPS.** Le bundle ne voit aucune clé, la CSP ne change pas, et aucune caisse Rust n'est ajoutée.
2. **Mot de passe.** `Argon2id` sur le mot de passe, avec un sel lié au courriel, puis HKDF, qui sépare deux clés : `authKey`, dont le VPS ne garde qu'un HMAC poivré, et `KEK`, qui ne quitte jamais l'appareil.
3. **Clé maîtresse du compte (AMK).** Elle est aléatoire. Elle est enveloppée sous la `KEK` et **scellée par HPKE** vers une clé publique tirée de la clé de récupération. On peut donc la réenvelopper **sans connaître la clé de récupération**.
4. **Rotation.** Chaque changement de secret et chaque révocation d'appareil **fait tourner les clés** : AMK neuve, clé de données de l'époque suivante, et révocation d'office des autres sessions. Ce qui est écrit après n'est plus lisible avec un ancien accès. Ce qui a été écrit avant le reste, et on le dit.
5. **Enregistrements.** Chacun est scellé en AES-256-GCM sous une sous-clé HKDF à usage unique. L'AAD lie compte, objet, révision, époque et en-tête.
6. **Le VPS est un classeur aveugle.** Une version par objet, plus la précédente pendant 30 jours. Un `rev` en comparer-et-échanger. Un `seq` par compte. Il ne fusionne rien.
7. **La fusion tourne sur chaque appareil**, avec `fusionner_conversations`, sans changer la règle.
8. **L'appareil garde des planchers que rien sur le serveur ne remet à zéro** : révision maximale vue, date de suppression, versions du coffre et du trousseau, époque de clé.
9. **L'état de synchronisation dépend de (compte, incarnation).** Une réinitialisation ou un autre compte le vide et repousse tout.
10. **Le VPS de Flashprime est protégé** : budget de sauvegarde en octets, contrôle de l'espace libre, retour arrière local à chaque étape, et jamais de restauration de la machine pour Diapason.
11. **Tout est dit, rien n'est découvert (§5)** : ce que voit le serveur, ce qu'une restauration ramène, ce qu'un appareil « connecté » peut vraiment sauver, qui détient la machine.
12. **« Synchronisé » ne s'affiche que sur un `seq` rendu par le VPS**, avec une file sortante vide et un état qui correspond à l'incarnation courante (§100).

---

## 1. Menaces couvertes et non couvertes

### 1.1 Adversaires

| # | Adversaire | Ce qu'on garantit | Ce qu'on NE garantit PAS |
|---|---|---|---|
| **A1** | **VPS hostile.** Root, le titulaire `flashprime` (sudo, docker), Hostinger, quiconque contrôle la zone DNS (donc un certificat, donc un TLS intercepté). Il lit la base, la mémoire, `comptes.env` et les journaux. Il reçoit `authKey` à chaque connexion. | Il ne lit aucun contenu. Il ne fabrique et ne permute aucun enregistrement. Il ne fait pas accepter à un appareil une révision inférieure à son plancher, une conversation supprimée que l'appareil sait supprimée, un coffre ou un trousseau plus ancien que le plancher, ni un KDF affaibli. Les données écrites après une rotation échappent à qui n'avait que l'ancien accès. | Il peut attaquer le mot de passe hors ligne, au coût d'Argon2id : seule l'entropie protège. Il peut couper le service ou effacer. Il voit les métadonnées (§2.9), dont la **suppression, visible à la chute de taille**. Il peut **se connecter au compte** (il voit `authKey`), lire le chiffré et écraser. Il peut cacher une tombale à un appareil qui ne l'a jamais vue. Il peut simuler un « retour arrière » pour faire saisir un ancien mot de passe, qu'il connaît de toute façon déjà par son `authKey`. |
| **A2** | **Fichier `comptes.db` ou copie de `/var/backups/diapason` volé seul**, sans `comptes.env` | Aucun essai hors ligne : les vérificateurs sont poivrés, les enveloppes et les courriels sur-chiffrés au repos. | Le nombre de comptes, les tailles, les jours. |
| **A2′** | **Copie de toute la machine** (sauvegarde hebdomadaire Hostinger, instantané, disque) | Aucun contenu. | **`comptes.env` est sur le même disque** : les essais hors ligne redeviennent possibles au coût d'Argon2id, et les adresses sont lisibles. On l'écrit tel quel. |
| **A3** | **Boîte courriel compromise** | Aucun code ne donne le contenu. Une réinitialisation est retardée de 72 h, ou de 7 jours si une session a été vue dans les 30 derniers jours. Elle est **annoncée dans l'app sur chaque appareil connecté**, pas seulement par courriel, et annulable. | Si aucun appareil ne se connecte pendant le délai, la réinitialisation passe. C'est un déni de service, pas une lecture. |
| **A4** | **Appareil perdu** | Depuis un autre appareil, avec le mot de passe : révocation, **rotation**, révocation de toutes les autres sessions. Le perdu ne reçoit plus rien et ne lit rien de ce qui est écrit ensuite. | Ce qui est déjà en clair sur l'appareil. L'historique chiffré sous les anciennes clés, si l'attaquant a l'AMK mémorisée **et** obtient le chiffré par A1. |
| **A5** | **Mot de passe faible** | En ligne : délais progressifs. Hors ligne : 256 Mio par essai. | Un mot de passe d'environ 30 bits tombe en quelques semaines sur GPU. D'où le minimum de 12 caractères et la phrase générée proposée (D5). |
| **A6** | **Rejeu ou retour arrière** | Planchers locaux (§4.4). La fusion est une union. | Un gel total ne se voit qu'à l'ancienneté de `lastConfirmedAt`, qui est affichée. |
| **A7** | **Processus de la même session** (`shell_exec` de l'assistant, maliciel) | Rien de plus qu'aujourd'hui : il lit déjà `conversations.db`. | Tout. C'est dit, pas promis. |
| **A8** | **Abus du service** | Quotas, garde disque globale, budget de sauvegarde, budgets de courriel, limites nginx. `MemoryMax` et `CPUQuota` protègent Flashprime. | — |
| **A9** | **Jeton de session volé** | Il ne donne ni l'enveloppe AMK, ni le coffre, ni une révocation, ni la suppression du compte. Un écrasement se répare tout seul (§4.6), et la version précédente reste 30 jours. Une pièce marquée orpheline est réclamée de nouveau. | Il permet de lire le chiffré, de voir les métadonnées et d'écraser temporairement. |
| **A10** | **Erreur d'exploitation** : restauration de `comptes.db`, restauration de toute la machine, perte du VPS | Une restauration logique rejoue le journal d'événements : suppressions, révocations, coffres. Un retour arrière de toute la machine est détecté (`globalSeq`) et mène à un parcours dit à l'utilisateur. Une perte du VPS mène à l'état `serverLost`. Les données locales sont toujours intactes. | Après un retour arrière de la machine, l'ancien mot de passe de la date restaurée est de nouveau accepté par le serveur jusqu'à la rotation forcée qui suit. |
| **A11** | **Tiers hébergeur** : le propriétaire de Flashprime, qui détient la machine, le DNS et le panneau Hostinger | Mêmes garanties que A1. | Il peut arrêter le service sans préavis (D3). |

### 1.2 Hors du modèle, et dit

- Il n'y a **pas de PAKE**. `authKey` est un secret porteur, et un VPS hostile qui le voit peut se connecter.
- Il n'y a **pas de rotation « par appareil »**. Déconnecter un appareil perdu fait tourner les clés pour tout le compte, et les autres appareils redemandent le mot de passe (D21).
- **L'historique n'est pas rechiffré** après une rotation.
- Le **téléphone** (Dart Succès) est hors de la v1.

---

## 2. Chiffrement

### 2.1 Où tourne la cryptographie

Elle tourne dans le serveur Python local (`diapason serve`, 127.0.0.1:8000), et seulement là. Quatre raisons :

- **Le bundle ne peut pas joindre le VPS.** Sa `connect-src` est limitée à localhost (`tauri.conf.json:29`, `middleware.py:52-58`), et WebCrypto n'a pas Argon2id.
- **Le verrou Rust n'a ni argon2 ni aes-gcm.**
- **`cryptography` 50.0.0 fournit tout** : Argon2id, AES-GCM, HKDF, X25519, HPKE (`pyproject.toml:237`, roue `win_amd64` dans `uv.lock:1441-1462`).
- **Le serveur local est la seule couche commune** à la fenêtre (`tauri://localhost`) et au mini-panneau (`127.0.0.1:8000`).

Deux règles de transport :

- **Le mot de passe voyage du bundle au serveur local dans un corps JSON**, jamais dans l'URL, puisqu'uvicorn journalise chemin et requête (`serve.py:259-263`).
- **Le bundle ne reçoit jamais de clé**, sauf la clé de récupération, montrée une fois pour qu'on la note.

**Aucune clé du maillage n'est réutilisée**, et `owner_id` n'est jamais envoyé au VPS :

- `device_key` : `sign_envelope` n'a pas de préfixe de domaine (`identity.py:348-355`) ;
- `seal_key` : elle est renouvelée et effacée au bout de 7 jours (`scellement.py:138-154, 199-230`).

### 2.2 Hiérarchie des clés

```
P = NFKC(mot de passe) en UTF-8          E = NFKC(courriel).strip().lower()
kdfSalt = HMAC(GRAINE_SEL, "sel\0" ‖ HMAC(POIVRE,"courriel\0"‖E))   — servi par le VPS, DÉTERMINISTE,
                                                                       identique pour une adresse connue ou non
sel     = SHA-256("diapason/compte/v1/sel-argon2\0" ‖ E ‖ "\0" ‖ kdfSalt)
K_mdp   = Argon2id(P, sel, paramètres de kdfVersion)
  ├─ HKDF(info="diapason/compte/v1/auth") ─► authKey ──TLS──► VPS : HMAC(POIVRE, "auth\0"‖accountId‖authKey)
  └─ HKDF(info="diapason/compte/v1/kek")  ─► KEK_mdp            (ne quitte jamais l'appareil)

R = clé de récupération, 16 o aléatoires (montrée une fois, jamais stockée)
  ├─ HKDF(info="diapason/compte/v1/recuperation-auth")   ─► recoveryAuthKey ─► VPS : HMAC(POIVRE, …)
  └─ HKDF(info="diapason/compte/v1/recuperation-x25519") ─► graine ─► sk_rec (X25519) ; pk_rec public

AMK_n = 32 o aléatoires, NEUVE à chaque rotation n
  ├─ enveloppée sous KEK_mdp                   (type 03, AES-GCM)
  ├─ scellée vers pk_rec par HPKE              (type 06 ; aucun besoin de R pour sceller)
  ├─ HKDF(info="…/trousseau")      ─► K_trousseau_n ─chiffre─► KEYRING (version r)
  └─ HKDF(info="…/noms-appareils") ─► K_noms_n

KEYRING = {"v":1, "currentEpoch":e, "epochs":{"1":b64(DEK_1), …, "e":b64(DEK_e)},
           "idKey":b64(K_id), "recoveryPublicKey":b64(pk_rec) | null}
  DEK_e ─HKDF(salt = sel aléatoire de 32 o PAR ENVELOPPE, info=…/enveloppe|type)─► sous-clé à usage unique
  DEK_e ─HKDF(info="…/piece-id")─► K_piece_e     (identifiants de pièces PAR ÉPOQUE)
  K_id  ─HMAC-SHA256─► objectId                   (stable pendant toute l'incarnation du compte)
```

**Pourquoi chaque étage :**

- **`kdfSalt` déterministe.** La version précédente tirait un sel neuf à chaque changement de mot de passe. En sondant `login/params` dans le temps, on voyait alors qu'une adresse s'inscrivait ou changeait de mot de passe (constat mineur des revues cryptographie et protocole). Désormais le sel d'une adresse ne change jamais, qu'elle ait un compte ou non. Comme `E` est dans le sel, un serveur qui servirait le même `kdfSalt` à tout le monde n'obtiendrait pas pour autant un dictionnaire commun.
  - `GRAINE_SEL` est un secret à part, **jamais tourné**. Une rotation du poivre ne doit pas faire changer les sels des adresses inconnues pendant que ceux des comptes restent fixes.
  - Réutiliser le même sel pour un nouveau mot de passe ne coûte rien : le mot de passe change.
- **Pourquoi la clé de récupération scelle par HPKE.** Faire tourner l'AMK exige de la réenvelopper aussi pour la récupération, alors que `R` n'est jamais stockée. Une paire X25519 tirée de `R` le permet : l'appareil scelle vers `pk_rec` sans connaître `R`.
  - `pk_rec` est lue **dans le trousseau déchiffré**, jamais dans une réponse du serveur. Un VPS hostile ne peut donc pas y substituer sa propre clé.
- **Pourquoi l'AMK change à chaque rotation.** C'est le défaut bloquant de la revue cryptographie : une ancienne enveloppe et un ancien secret redonnaient la clé courante pour toujours.
  - Le trousseau garde les anciennes DEK, pour lire l'historique.
  - Les nouvelles écritures utilisent `DEK_{e+1}`.
  - Aucune migration n'est nécessaire : l'époque existe dans le format dès la v1 (CLAUDE.md §5, aucune migration SQLite).
- **Pourquoi `K_piece_e` dépend de l'époque.** Sinon, après une rotation, `/pieces/missing` répondrait « présente » et l'image resterait sous la DEK compromise. Les pièces sont donc renvoyées sous la nouvelle époque à la prochaine poussée de l'objet qui les référence.
- **Pourquoi `K_id` est stable pendant l'incarnation.** Deux appareils doivent nommer pareil la même conversation. Elle ne change qu'à une réinitialisation, qui crée une nouvelle incarnation.

**Préfixes.** Tous les `info` commencent par `diapason/compte/v1/`. Ils ne recoupent ni `diapason-mesh-transfer-v1` (`coffre.py:37`) ni `diapason-mesh-command-v1` (`scellement.py:78`).

### 2.3 Primitives et paramètres

| Usage | Primitive | Paramètres |
|---|---|---|
| Étirement du mot de passe | `Argon2id` | kdfVersion **1** = `memory_cost=262144` (256 Mio), `iterations=3`, `lanes=4`, `length=32`. On descend à 131 072 si pc-bureau dépasse 2,5 s (D2). La valeur est **figée avant le premier compte**. |
| Séparation des clés | `HKDF(SHA256, 32)` | `salt=None` pour les clés de rôle ; 32 o aléatoires pour les sous-clés d'enveloppe |
| Chiffrement symétrique | `AESGCM` 256 | nonce `os.urandom(12)`, tag de 128 bits, **une sous-clé par message** |
| Scellement de récupération | `hpke.Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)` | `info` = en-tête ‖ `"|"` ‖ AAD canonique. L'API n'a pas de paramètre `aad` : tout le contexte passe par `info`. |
| Identifiants | `HMAC-SHA256` | tronqué à 16 o, base64url sans remplissage |
| Empreintes d'égalité | `SHA-256(clair canonique)` | **locales seulement**, jamais envoyées |
| Côté VPS | `hmac`, `hashlib`, `secrets` ; `AESGCM` pour le repos | **Aucun Argon2id** côté serveur. `cryptography` est épinglé par empreinte dans le verrou du VPS (D19). |

**Contre le déclassement.** Le client code en dur `VERSIONS_KDF = {1: (262144, 3, 4)}` et `KDF_VERSION_MIN = 1`. Une version inconnue ou inférieure est refusée avec le code `kdfDowngrade`, selon le principe de `doit_sceller` (`scellement.py:392-438`).

**Écartés** :

- `coffre.sceller`, dont le nonce est l'index (`coffre.py:133-136`) ;
- XChaCha20, absent ;
- `aes_key_wrap`, qui n'a pas d'AAD ;
- AES-GCM-SIV, présent mais inutile avec des sous-clés à usage unique.

**Mémoire.** Le serveur local ne fait qu'**une dérivation Argon2id à la fois** (`threading.Semaphore(1)`).

### 2.4 Normalisations (figées par les vecteurs)

- **Courriel** : `NFKC`, `strip`, `lower`. De 3 à 254 caractères, un seul `@`, aucun espace.
- **Mot de passe** : `NFKC` sans `strip`, puis UTF-8. De 12 à 1 024 caractères. Il ne doit pas contenir la partie locale de l'adresse.
  - Pourquoi : un « é » saisi en NFD sous macOS et en NFC sous Windows donnerait deux clés différentes.

### 2.5 Format d'enveloppe « DPE1 »

| Octets | Champ |
|---|---|
| 0 | format `0x01` |
| 1 | type : `01` objet · `02` pièce · `03` AMK sous KEK · `04` nom d'appareil · `05` trousseau · `06` AMK scellée vers la récupération |
| 2-5 | `keyEpoch`, uint32 gros-boutiste (0 pour les types 03, 05 et 06) |
| types 01-05 : 6-37 · 38-49 · 50… | sel HKDF (32 o) · nonce (12 o) · chiffré ‖ tag (16 o) : **66 o de surcoût** |
| type 06 : 6… | sortie HPKE = `enc` (32 o) ‖ chiffré ‖ tag : 86 o pour une AMK |

**Sous-clé (types 01 à 05).** `HKDF(SHA256, 32, salt=sel, info=b"diapason/compte/v1/enveloppe|"+type)` appliquée à la clé de base :

| Type | Clé de base |
|---|---|
| 01, 02 | DEK de l'époque |
| 03 | KEK_mdp |
| 04 | K_noms |
| 05 | K_trousseau |

**AAD** = en-tête (octets 0 à 49, ou 0 à 5 pour le type 06) ‖ `b"|"` ‖ JSON produit par `aad_canonique()`. Ce JSON est trié, compact, en UTF-8, et ne contient **que des chaînes et des entiers**. Un `float`, un `bytes` ou tout autre type lève `TypeError`. On n'emprunte pas `identity.canonical_bytes`, dont le `default=str` (`identity.py:344`) signerait `"b'…'"` en silence.

| Type | JSON de l'AAD |
|---|---|
| objet | `{"a":accountId,"e":keyEpoch,"i":incarnation,"o":objectId,"r":rev,"t":"object","v":1}` |
| pièce | `{"a":…,"e":…,"i":…,"o":pieceId,"t":"attachment","v":1}` |
| AMK sous mot de passe | `{"a":…,"k":kdfVersion,"t":"amk","u":"password","w":vaultVersion}` |
| AMK scellée (récupération) | `{"a":…,"t":"amk","u":"recovery","w":vaultVersion}` |
| trousseau | `{"a":…,"r":keyringVersion,"t":"keyring","v":1,"w":vaultVersion}` |
| nom d'appareil | `{"a":…,"s":sessionId,"t":"deviceName","v":1}` |

**Pourquoi `w` et `i` ont été ajoutés.**

- `w` (`vaultVersion`) dans les enveloppes AMK et le trousseau. Sans lui, un appareil ne pouvait pas distinguer une enveloppe périmée, ramenée par une restauration, de l'enveloppe courante (revue cryptographie).
- `i` (`incarnation`) dans les objets. Un blob d'avant une réinitialisation ne peut plus passer pour un blob d'après.

**Rembourrage.** Le cadre du clair est `uint32 BE(L) ‖ clair ‖ zéros`, complété jusqu'à `max(plancher, padme(4 + L))`. Le plancher vaut 1 024 o pour un objet et 4 096 o pour une pièce. Les zéros sont **vérifiés** au déchiffrement. On n'utilise jamais `rstrip(b"\x00")` (`scellement.py:444-456`), qui mangerait les octets d'une image.

```python
def padme(L: int) -> int:           # Nikitin et al., PURBs 2019 — surcoût ≤ 12 %
    E = L.bit_length() - 1
    S = E.bit_length()
    masque = (1 << (E - S)) - 1
    return (L + masque) & ~masque
```

Le VPS vérifie que `taille − 66` est une valeur de Padmé, supérieure ou égale au plancher.

**Ce que le rembourrage ne cache pas.** La taille d'une conversation ne fait que croître, puisque la fusion est une union (`conversations_store.py:176-189`) qui garde le contenu le plus long (`:131-149`). Seule une tombale la fait retomber. Mesure de la revue : 3 138 → 116 802 → 1 090 o. **Le serveur peut donc reconnaître une suppression.** On l'écrit dans `/confidentialite` (§5). Rembourrer la tombale jusqu'à la taille précédente est une option (D20), non retenue par défaut, parce qu'une suppression qui ne libère pas l'espace surprendrait davantage.

**Clair d'un objet.** Toutes ses clés sont en anglais camelCase (CLAUDE.md §3), fixées **avant** le premier vecteur. `sans_substituts` est appliqué avant (`conversations_store.py:91-101`).

```json
{"v":1,"collection":"conversations","id":"<id local>","schema":1,"data":{…conversation projetée…}}
{"v":1,"collection":"conversations","id":"<id local>","schema":1,"deleted":{"deletedAt":1790000000000}}
```

- **Collection dans le clair.** Le nom de collection est **à l'intérieur** : le VPS ignore quelle application produit quoi.
- **Recalcul de `objectId`.** À l'ouverture, le client recalcule `objectId` à partir de `collection` et `id`. En cas d'écart, l'objet est mis en quarantaine comme « permuté ».
- **Flottants.** Des flottants peuvent figurer dans `data`. C'est sans conséquence : ces octets ne sont jamais ré-encodés d'un langage à l'autre, et ce n'est pas une enveloppe signée du maillage (CLAUDE.md §4).

### 2.6 Identifiants opaques

- **Objets** : `objectId = b64url(HMAC(K_id, "object\0" ‖ collection ‖ "\0" ‖ idLocal)[:16])`.
- **Pièces** : `pieceId = b64url(HMAC(K_piece_e, "attachment\0" ‖ SHA-256(octets))[:16])`. L'identifiant est calculé par époque. Le VPS voit qu'une même image a été envoyée deux fois dans la même époque, mais ne peut pas tester la présence d'une image connue.

### 2.7 Clé de récupération

- **Format** : `R` fait 16 o. S'y ajoutent 4 o de contrôle, `SHA-256("diapason/compte/v1/recuperation-controle" ‖ R)[:4]`. Le tout est écrit en base32 Crockford : 32 caractères en 8 groupes de 4.
- **Saisie tolérante** : tirets et espaces ignorés, `O` lu comme `0`, `I` et `L` lus comme `1`. Une faute de frappe est détectée **localement**, avant tout appel réseau.
- **Pas d'Argon2id** : 128 bits ne se devinent pas.
- **Preuve de sauvegarde** : ressaisir deux groupes tirés au hasard. C'est une fonction pure, testée par vitest.
- **Durée de vie** : `R` n'est jamais stockée. Elle vit en mémoire du serveur local entre « préparer » et « terminer », 30 min au plus.
- **Après usage** : une clé utilisée pour récupérer le compte est **remplacée par défaut**, car elle a été tapée. Garder l'ancienne reste possible, avec un avertissement (D22).

### 2.8 Rotation (nouvelle, v1)

**Quand.** Une rotation a lieu à chaque :

- changement de mot de passe ;
- oubli du mot de passe avec un appareil déverrouillé ;
- récupération par `R` ;
- remplacement ou retrait de la clé de récupération ;
- déconnexion d'un **autre** appareil (appareil perdu).

**Opération, sur l'appareil qui a l'AMK courante et le nouveau (ou l'actuel) mot de passe :**

1. Tirer `AMK′` et `DEK_{e+1}`.
2. Écrire le trousseau `r+1` = l'ancien, plus `epochs[e+1]`, avec `currentEpoch = e+1`, `idKey` inchangée et `recoveryPublicKey` gardée, remplacée ou `null`.
3. Envelopper `AMK′` sous `KEK_mdp` (type 03, `w = vaultVersion + 1`).
4. Si la récupération est conservée, sceller `AMK′` vers `pk_rec` (type 06).
5. Appeler **`POST /vault/commit`** (§3.4). Le serveur fait un comparer-et-échanger sur `vaultVersion` **et** `keyringVersion`, en une transaction, et **révoque toutes les autres sessions, sans option**.
6. Toute nouvelle écriture (objet ou pièce) est scellée sous `DEK_{e+1}`. Le VPS refuse une poussée dont `keyEpoch` diffère de l'époque courante (409 `keyEpochChanged`).

**Ce que chaque texte dit** (§5 du cahier) :

> Clés renouvelées. Ce qui sera écrit à partir de maintenant ne pourra pas être lu avec l'ancien mot de passe ni par un appareil déconnecté. Ce qui a été écrit avant reste lisible par qui avait déjà l'ancien accès. Vos autres appareils vous redemanderont le mot de passe.

**Déconnexion volontaire.** Se déconnecter de **cet** appareil (P7) ne fait pas tourner les clés : l'appareil est entre vos mains.

### 2.9 Ce que le VPS ne voit jamais, et ce qu'il voit quand même

**Jamais** :

- le mot de passe, `K_mdp`, les KEK, l'AMK, les DEK, `K_id`, `K_piece` et `R` ;
- les titres, les messages, les images, le modèle, les épingles, les dates internes ;
- les identifiants locaux, les noms de collection et les noms d'appareil.

**Quand même**, texte à reprendre tel quel dans `/confidentialite` :

- **Compte** :
  - l'adresse courriel, chiffrée au repos, mais déchiffrée par le service pour écrire ;
  - le jour de création ;
  - la version des conditions ;
  - `kdfVersion` et le sel ;
  - les vérificateurs et enveloppes, opaques.
- **Données** :
  - le nombre d'objets et de pièces, et leurs tailles arrondies ;
  - le nombre de révisions par objet ;
  - quels objets changent ensemble ;
  - l'identité de deux envois d'une même image dans une même époque ;
  - **qu'une conversation a vraisemblablement été supprimée**, à la chute de sa taille et aux pièces libérées ensuite ;
  - le moment des rotations.
- **Activité** :
  - l'ordre (`seq`) et le moment des requêtes ;
  - l'adresse IP, en mémoire du limiteur ;
  - les journaux nginx (§3.9, D11) ;
  - journald, 7 jours ;
  - un compteur global d'écritures (`globalSeq`), qui révèle l'activité agrégée du service.
- **Sessions** : leur nombre, et leur jour de création et de dernière activité.
- **Authentification** : `authKey` à chaque connexion. Un serveur hostile peut donc se connecter au compte, sans pouvoir le déchiffrer.

### 2.10 Où vit chaque clé sur l'appareil

**Dossier.** Tout vit dans `get_config_dir()/compte/`, en 0700. Sous Windows, c'est `%USERPROFILE%\.diapason\compte\` (`paths.py:83-105`).

- Sous macOS, le dossier est **exclu de Time Machine** par `tmutil addexclusion` (exclusion collante, sans sudo), au premier usage.
- L'état local s'appelle `compte/etat.key`, en SQLite avec `journal_mode=DELETE`. Le suffixe `.key` le fait refuser par `file_read`, qui ne filtre que le nom (`file_policy.py:17`, `file_policy.rs:20`). Le fichier `-journal` transitoire n'est pas couvert. `shell_exec` contourne cette politique de toute façon (A7).

| Élément | macOS | Windows | Linux | VPS |
|---|---|---|---|---|
| P, K_mdp, KEK, R, sk_rec | `bytearray` écrasé après usage. On ne promet rien de plus : Python copie les `bytes`. | idem | idem | jamais |
| authKey, recoveryAuthKey | mémoire, le temps d'une requête | idem | idem | HMAC poivré |
| AMK, trousseau déverrouillés | **un seul** objet `Serrure` dans `app.state` | idem | idem | jamais |
| AMK mémorisée (« Garder cet appareil déverrouillé », **décochée par défaut**) | trousseau de session, service `Diapason Compte`, écrit et lu par `/usr/bin/security -i`, secret passé par l'entrée standard. Si le test `ps` de l'étape 3 échoue : fichier 0600 dans `compte/` (exclu de Time Machine), et on le dit. | DPAPI par `ctypes` (`CryptProtectData`, entropie `b"diapason/compte/v1"+accountId`, `CRYPTPROTECT_UI_FORBIDDEN`). **Refusée si le compte Windows n'a pas de mot de passe** (§2.11). | pas de mémorisation | jamais |
| Jeton de session | **même protecteur que l'AMK s'il existe** (trousseau, DPAPI), même quand l'AMK n'est pas mémorisée. Sinon `compte/session.key`, 0600, exclu de Time Machine. | DPAPI | fichier 0600 | SHA-256 |
| Enveloppe AMK et trousseau (déverrouillage hors ligne) | `compte/etat.key` | idem | idem | sur-chiffrés au repos |
| Planchers (§4.4) | `compte/etat.key` | idem | idem | — |

**Ce qu'on ne fait jamais** :

- mettre un secret dans une variable d'environnement (`lib.rs:1940-1943`, `shell_exec.py:121-125`) ;
- en écrire un dans `config.toml`, qui est en 0644 ;
- en mettre un dans `localStorage` ou `sessionStorage` ;
- en faire passer un par une commande Tauri ;
- en écrire un dans un journal.

### 2.11 Ce que la mémorisation protège vraiment

La version précédente se trompait : le trousseau est **inclus** dans Time Machine (`tmutil isexcluded ~/Library/Keychains` → `[Included]`), et un élément générique n'y est protégé que par le mot de passe de session macOS. La mémorisation **contourne Argon2id**. Texte des Réglages :

> La clé est gardée sur cet ordinateur, protégée par le mot de passe de votre session macOS (ou Windows). Quiconque obtient une sauvegarde de cet ordinateur **et** ce mot de passe peut lire vos données synchronisées. Un programme ouvert dans votre session, l'assistant compris, peut aussi la lire. En contrepartie, cet appareil peut vous servir de secours si vous oubliez votre mot de passe Diapason.

**Windows sans mot de passe.** DPAPI ne vaut que le mot de passe Windows. L'étape 3 détecte un compte sans mot de passe : `LogonUserW(nom, ".", "", LOGON32_LOGON_INTERACTIVE, …)` réussit, ou échoue avec `ERROR_ACCOUNT_RESTRICTION` (1327). La mémorisation est alors refusée. Le cas d'un compte Microsoft ou d'un code PIN est **à vérifier sur pc-bureau**. S'il reste indéterminé, on refuse aussi.

**Ce qu'on ne promet pas** : le trousseau « data protection » (ThisDeviceOnly). Il exige un droit d'accès que le Python du venv n'a pas.

**Redémarrage.** Chez les autres utilisateurs, le serveur meurt avec l'app (`lib.rs:680-688`, `:5770-5774`). Au démarrage suivant, il relit lui-même l'AMK si elle est mémorisée. Sinon, l'état est `locked`.

### 2.11 bis Ce que l'étape 1 a appris (24/09/2026)

La contre-épreuve de l'étape 1 a trouvé et fait corriger un défaut sérieux, et
laissé trois limites qui relèvent d'étapes suivantes :

- **Corrigé.** `ouvrir_coffre_par_recuperation` acceptait un coffre forgé par
  l'appareil perdu et un VPS complice : une AMK à eux, et un trousseau dont
  `recoveryPublicKey` était LEUR clé. La rotation suivante, qui garde la
  récupération par défaut, leur aurait scellé l'AMK neuve. Un trousseau qui ne
  nomme pas la clé tirée de `R` est désormais refusé (`serverKeyInvalid`).
- **Reste, étape 8.** HPKE en mode Base n'authentifie pas l'expéditeur : un
  appareil perdu peut encore forger un coffre qui porte la VRAIE `pk_rec`,
  avec des DEK choisies par lui. Après une récupération par `R`, l'appareil
  **fait tourner les clés avant toute écriture**, et tient l'historique ouvert
  par ce chemin pour non authentifié.
- **Reste, étape 10.** Le trousseau garde les anciennes DEK pour lire
  l'historique : un porteur d'une ancienne DEK peut donc encore faire accepter
  un objet forgé d'une époque passée. Le moteur de synchronisation met en
  quarantaine tout blob d'époque inférieure à `keyEpochMax` dont la révision
  dépasse la révision maximale connue.
- **Décision à prendre (Carlito).** Le nom d'appareil (type 04) n'a pas de
  plancher de rembourrage : Padmé seul laisse deviner au VPS l'ordre de
  grandeur du nom. Un plancher de 64 ou 256 o change le format et les vecteurs.

### 2.12 Vecteurs de contrat

`scripts/gen_vecteurs_compte.py` produit `tests/contract/vecteurs_compte.json`, régénéré **dans le même commit** que tout changement de format. Il contient :

- Argon2id avec les vrais paramètres ;
- un mot de passe en NFC, en NFD et en pleine chasse ;
- les HKDF ;
- une enveloppe de chaque type 01 à 05, avec sel et nonce injectés ;
- une enveloppe HPKE de type 06, par déchiffrement seul, puisque HPKE tire son aléa en interne ;
- Padmé sur 12 longueurs ;
- une clé de récupération et son contrôle ;
- `objectId` et `pieceId` ;
- un trousseau à deux époques.

---

## 3. Comptes

### 3.1 Forme du service VPS

**Code.** Le service vit dans `src/diapason_comptes/`.

- Il est couvert par `ruff check src/` et reste absent de la roue (`pyproject.toml:271-272`).
- Ses tests sont dans `tests/diapason_comptes/`.
- Il n'importe **jamais** `diapason`, et de `cryptography` il n'importe que `hazmat.primitives.ciphers.aead` (D19). Un test en sous-processus le vérifie.
- Il est compatible avec Python 3.12.3.

**Exécution.** C'est une unité systemd `diapason-comptes`, **sans Docker**. Le démon Docker est partagé avec Flashprime, qui fait un `prune -af` à 00:31, et un port publié par Docker contourne ufw.

- Utilisateur système `diapason`.
- `uvicorn diapason_comptes.app:app --host 127.0.0.1 --port 8710 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log`.
- `MemoryMax=300M`, `CPUQuota=50%`, `TasksMax=64`, `UMask=0077`, `StateDirectory=diapason`, `PrivateDevices=yes`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, plus le durcissement de `deploy/systemd/diapason.service:21-37`.
- Code et venv dans `/opt/diapason/{app,venv}`, propriété de root.

**Routes.** Toutes sont en `def` synchrones. SQLite est protégé par un verrou, comme `conversations_store.py:237-246`.

- La validation est écrite à la main. Le gestionnaire `RequestValidationError` est remplacé par `{"error":{"code":"invalidRequest","field":"…"}}`, pour qu'aucune valeur (dont `authKey`) ne soit renvoyée en écho.
- `Cache-Control: no-store` et `X-Content-Type-Options: nosniff` sont posés sur chaque réponse.

**Courriels.** Ils ne passent **jamais** par `BackgroundTasks`, qui occupe le pool de 40 fils partagé avec toutes les routes `def` (`starlette/background.py:23`, `anyio` `CapacityLimiter(40)`). Il y a **un fil expéditeur dédié** (démon) et une `queue.Queue(maxsize=200)` en mémoire. La route se contente de `put_nowait`. Si la file est pleine, l'envoi est abandonné et compté. Un test prouve qu'un expéditeur bloqué ne retarde pas `/health`.

**Entretien au passage, sans cron** :

- codes et jetons expirés : purgés à chaque création ;
- sessions expirées : purgées dans `login` ;
- compteurs de plus de 24 h : purgés à chaque échec ;
- versions précédentes et pièces orphelines de plus de 30 jours : purgées à chaque poussée du compte.

**Aucune réinitialisation ne s'exécute d'elle-même** (§3.6).

### 3.2 Secrets du serveur

Ils sont dans `/etc/diapason/comptes.env`, généré **sur le VPS** avec `umask 077`, et ne transitent jamais par le Mac.

```
COMPTES_SECRETS_VERSION=1
COMPTES_POIVRE_1=<b64 32 o>      # HMAC : vérificateurs, index de courriel, codes, limites (domaines séparés)
COMPTES_CLE_REPOS_1=<b64 32 o>   # AES-256-GCM au repos : courriel, enveloppes, trousseau, journal ; AAD = accountId|colonne
COMPTES_GRAINE_SEL=<b64 32 o>    # kdfSalt déterministe ; JAMAIS tournée
```

- **Deux `EnvironmentFile`** sans « - » : `mail.env` et `comptes.env`. Le service refuse de démarrer si un fichier manque ou si un secret n'a pas 32 o (modèle `deploy/systemd/diapason.service:13-19`). Il ne journalise que la **présence** de chaque secret.
- **Rotation** : chaque compte porte `secrets_version`, et la rotation a lieu à la connexion suivante.
- **Perte de `comptes.env`** : plus aucune connexion ni récupération n'est possible. Les appareils qui ont mémorisé l'AMK continuent. D'où une copie hors du VPS (D18).
- **Honnêteté (A2′)** : `comptes.env` est sur le même disque que la base, donc dans les sauvegardes Hostinger. Le poivre ne protège que contre la fuite isolée d'un fichier de base.

### 3.3 Schéma (`/var/lib/diapason/comptes.db`, complet dès la naissance)

```sql
PRAGMA journal_mode = WAL;  PRAGMA foreign_keys = ON;  PRAGMA secure_delete = ON;

CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
  -- 'schema'='1' ; 'generation' = 16 o hex, changée par l'outil de restauration ;
  -- 'globalSeq' = compteur global d'écritures, monotone

CREATE TABLE comptes (
  id                 TEXT PRIMARY KEY,          -- UUID v4 tiré à signup/verify
  courriel_index     BLOB NOT NULL UNIQUE,      -- HMAC(POIVRE,"courriel\0"+E)
  courriel_chiffre   BLOB NOT NULL,
  cree_jour          INTEGER NOT NULL,
  conditions_version INTEGER NOT NULL,
  secrets_version    INTEGER NOT NULL,
  kdf_version        INTEGER NOT NULL,
  sel_kdf            BLOB NOT NULL,             -- = kdfSalt déterministe, gardé pour survivre à une rotation de poivre
  verif_auth         BLOB NOT NULL,
  amk_mdp            BLOB NOT NULL,             -- DPE1 type 03, sur-chiffrée
  verif_recup        BLOB,                      -- NULL : aucune clé de récupération
  amk_recup          BLOB,                      -- DPE1 type 06, sur-chiffrée
  version_coffre     INTEGER NOT NULL,
  trousseau          BLOB NOT NULL,             -- DPE1 type 05, sur-chiffré
  version_trousseau  INTEGER NOT NULL,
  epoque_cle         INTEGER NOT NULL DEFAULT 1,  -- keyEpoch : +1 à chaque rotation
  incarnation        INTEGER NOT NULL DEFAULT 1,  -- +1 à reset/complete
  seq                INTEGER NOT NULL DEFAULT 0,
  octets             INTEGER NOT NULL DEFAULT 0,
  quota_octets       INTEGER NOT NULL,
  reinit_demandee_ms INTEGER,                   -- reset/confirm
  reinit_effective_ms INTEGER                   -- ouvre le DROIT d'appeler reset/complete
);
CREATE TABLE codes (courriel_index BLOB NOT NULL,
  but TEXT NOT NULL CHECK (but IN ('inscription','coffre','reinitialisation')),
  code_mac BLOB NOT NULL, expire_ms INTEGER NOT NULL, essais INTEGER NOT NULL DEFAULT 0, consomme_ms INTEGER,
  PRIMARY KEY (courriel_index, but));
CREATE TABLE jetons_temporaires (hash BLOB PRIMARY KEY,
  but TEXT NOT NULL CHECK (but IN ('inscription','recuperation')),
  courriel_index BLOB NOT NULL, compte_id TEXT, expire_ms INTEGER NOT NULL, consomme_ms INTEGER);
CREATE TABLE sessions (id TEXT PRIMARY KEY,
  compte_id TEXT NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
  jeton_hash BLOB NOT NULL UNIQUE, nom_chiffre BLOB,
  cree_jour INTEGER NOT NULL, vu_jour INTEGER NOT NULL, expire_ms INTEGER NOT NULL);
CREATE TABLE objets (compte_id TEXT NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
  objet_id TEXT NOT NULL, rev INTEGER NOT NULL, seq INTEGER NOT NULL, blob BLOB NOT NULL,
  blob_precedent BLOB, rev_precedente INTEGER, precedent_jour INTEGER,   -- 30 jours, autoréparation
  PRIMARY KEY (compte_id, objet_id));
CREATE INDEX objets_seq ON objets (compte_id, seq);
CREATE TABLE pieces (compte_id TEXT NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
  piece_id TEXT NOT NULL, blob BLOB NOT NULL,
  reclame_seq INTEGER NOT NULL,                 -- seq du compte à la dernière réclamation
  orpheline_jour INTEGER,
  PRIMARY KEY (compte_id, piece_id));
CREATE TABLE limites (cle BLOB PRIMARY KEY, echecs INTEGER NOT NULL, debut_ms INTEGER NOT NULL,
  bloque_jusqua_ms INTEGER NOT NULL);
CREATE TABLE envois (cle BLOB PRIMARY KEY, minute INTEGER, heure INTEGER, jour INTEGER, fenetre_ms INTEGER NOT NULL);
```

- **Aucune IP n'est stockée.** Le limiteur par IP vit en mémoire, sous `HMAC(POIVRE, préfixe /24 ou /48)`.
- **Aucune heure par objet.**
- **Consommation atomique.** Un code ou un jeton est consommé par un seul `UPDATE … WHERE consomme_ms IS NULL AND expire_ms >= ?` (modèle `mesh/registry.py:228-260`).

**Journal d'événements.** `/var/lib/diapason/evenements.jsonl` est un fichier hors de la base, en ajout seul, écrit avec fsync. Il reçoit :

- chaque suppression de compte (index HMAC, jamais l'adresse) ;
- chaque révocation (hash de session) ;
- chaque `vault/commit` et `reset/complete`, avec la ligne de sécurité **complète après le changement**, sur-chiffrée par `CLE_REPOS` : vérificateurs, enveloppes, trousseau, versions, époque, incarnation.

Chaque entrée pèse environ 2 Kio. Le journal est tronqué à « dernière sauvegarde valide moins 1 jour ». Il sert à la restauration logique (§3.10).

### 3.4 Routes du VPS

Préfixe : `https://diapason.flashprime.online/api/v1`. Conventions :

- JSON en camelCase ;
- octets en base64url sans remplissage ;
- heures en millisecondes entières ;
- **aucun flottant accepté** ;
- erreurs `{"error":{"code":"…"}}` ;
- session par `Authorization: Bearer dps1_…`.

| Route | Corps → réponse | Notes |
|---|---|---|
| `GET /health` | → `{status, version, timeMs, generation, globalSeq}` | Sans authentification. Dans une `location =` propre (§3.9). `generation` et `globalSeq` permettent de détecter une perte ou un retour arrière (§3.10). |
| `POST /signup/start` | `{email, termsVersion}` → 202 `{}` \| 503 `mailUnavailable` \| 503 `signupClosed` | Adresse libre : code. Adresse prise : « un compte existe déjà », **au plus une fois par jour**. `mailUnavailable` est global, donc sans risque d'énumération. |
| `POST /signup/verify` | `{email, code}` → `{signupToken, accountId, kdfSalt}` \| 400 `invalidCode` | Même 400 pour une adresse inconnue, déjà prise ou mal saisie. |
| `POST /signup/complete` | `{signupToken, kdfVersion, authKey, wrappedMasterKey, recovery:{authKey, sealedMasterKey}\|null, keyring}` → 201 `{accountId, sessionId, sessionToken, vaultVersion:1, keyringVersion:1, keyEpoch:1, incarnation:1}` | Vérifie la forme des enveloppes, refuse une `kdfVersion` sous le plancher, sur-chiffre. **Le compte n'existe qu'à partir d'ici.** |
| `POST /login/params` | `{email}` → `{kdfVersion, kdfSalt}` | Le sel est déterministe et identique pour une adresse inconnue. Limité par adresse, comme `/login`. |
| `POST /login` | `{email, authKey}` → `{accountId, sessionId, sessionToken, kdfVersion, vaultVersion, wrappedMasterKey, keyring, keyringVersion, keyEpoch, incarnation, recoveryConfigured, pendingResetAt}` \| 401 `invalidCredentials` \| 429 `tooManyAttempts {retryAfterS}` | Adresse inconnue : comparaison à un vérificateur factice. Courriel « nouvelle connexion » (D8). |
| `POST /logout` | Bearer → 204 | |
| `GET /account` | Bearer → `{accountId, email, createdDay, usedBytes, quotaBytes, vaultVersion, keyringVersion, keyEpoch, incarnation, recoveryConfigured, pendingResetAt}` | Ne rend **jamais** d'enveloppe. |
| `PUT /sessions/current` · `GET /sessions` | `{encryptedName}` → 204 · → `{sessions:[…]}` | La révocation d'une autre session ne passe **que** par `vault/commit`. |
| `POST /vault/code` | Bearer `{}` → 202 | Code pour « oublié, appareil déverrouillé ». |
| `POST /vault/commit` | Bearer, ou `recoveryToken`. `{proof:{kind:"password",authKey}\|{kind:"emailCode",code}\|{kind:"recovery",recoveryToken}, baseVaultVersion, newVaultVersion, baseKeyringVersion, newKeyringVersion, newKeyEpoch, password:{kdfVersion, authKey, wrappedMasterKey}, recovery:{mode:"keep",sealedMasterKey}\|{mode:"replace",authKey,sealedMasterKey}\|{mode:"remove"}, keyring, revokedSessionId?}` → `{vaultVersion, keyringVersion, keyEpoch, sessionId, sessionToken}` \| 409 `vaultConflict` \| 403 `invalidProof` | **Toute rotation passe par ici.** Comparer-et-échanger sur les deux versions, `new > courant`, `newKeyEpoch = courant + 1`, en une transaction, avec une entrée au journal. **Toutes les autres sessions sont révoquées.** La preuve `emailCode` exige aussi un Bearer. Courriels : « mot de passe changé », « clé de récupération remplacée/retirée », « appareil déconnecté ». |
| `POST /recovery/unwrap` | `{email, recoveryAuthKey}` → `{accountId, recoveryToken, sealedMasterKey, vaultVersion, keyring, keyringVersion, keyEpoch, incarnation}` \| 401 | Jeton de 10 min à usage unique. Compteur d'échecs à part. |
| `POST /reset/request` · `/reset/confirm` · `/reset/cancel` | `{email}` → 202 · `{email, code}` → 202 `{effectiveAt}` · Bearer → 200 | Délai de 72 h, ou 7 jours si une session a été vue dans les 30 derniers jours (D8). Les échecs de `confirm` comptent **avec ceux de `/login`**. |
| `POST /reset/complete` | `{email, code, kdfVersion, authKey, wrappedMasterKey, recovery, keyring}` → session | Seulement après `effectiveAt`, avec un nouveau code. **En une transaction** : effacement des objets, des pièces et des sessions ; nouveau coffre et nouveau trousseau ; `incarnation + 1` ; `keyEpoch = 1` ; entrée au journal. |
| `POST /account/delete` | Bearer `{authKey}` → 204 | Effacement immédiat (`secure_delete`), entrée au journal, courriel. |
| `GET /sync/changes?since=N&limit=L` | Bearer → `{meta, items:[{objectId, rev, seq, blob}], until, hasMore}` | Voir `meta` plus bas. |
| `POST /sync/push` | Bearer `{incarnation, keyEpoch, items:[{objectId, baseRev, blob}]}` → `{meta, results:[stored{rev,seq} \| conflict{current:{rev,seq,blob}} \| rejected{code}]}` | 409 `incarnationChanged` ou `keyEpochChanged`. Au plus 50 éléments et 8 Mio. Un objet absent a pour `rev` 0 : un `baseRev` qui ne correspond pas renvoie **toujours** un conflit **avec** `current` (`null` si absent). |
| `GET /sync/previous/{objectId}` | Bearer → `{rev, blob}` \| 404 | La version remplacée, gardée 30 jours. |
| `POST /pieces/missing` | `{asOfSeq, pieceIds}` → `{missing}` | **Réclame** chaque pièce listée qui existe (`reclame_seq = seq`, `orpheline_jour = NULL`). Une pièce orpheline est comptée comme manquante, ce qui force un PUT qui la ranime. |
| `PUT /pieces/{id}` · `GET /pieces/{id}` | `application/octet-stream` → 201/200 · → octets | Immuable. |
| `DELETE /pieces/{id}` | `{asOfSeq}` → 204 \| 409 `reclaimed` | Marque orpheline seulement si `reclame_seq <= asOfSeq`. Purge à +30 jours. |

**Le bloc `meta`** est porté par chaque réponse de `/sync/*` : `{generation, incarnation, keyEpoch, vaultVersion, keyringVersion, serverSeq, pendingResetAt}`. Il rend visibles, sans appel supplémentaire, une rotation faite ailleurs, une réinitialisation en attente et un retour arrière.

**Erreurs de session** : 401 `sessionRevoked`, `sessionExpired` ou `accountDeleted`.

**Aucune route ne touche au maillage.** Ni `COMMAND_VERSION` (`commands.py:47`), ni `PULL_VERSION` (`pull.py:47`), ni `_POLL_FIELDS` ou `_ACK_FIELDS` (`pull.py:58-74`). La surface est figée dans `tests/contract/compte_api_surface.json`, produit par `scripts/gen_compte_surface.py`.

### 3.5 Énumération, force brute, courriels

**Énumération.** Même statut, même corps et même classe de temps pour une adresse connue ou inconnue, sur `signup/*`, `login/params`, `login`, `recovery/unwrap` et `reset/*`. Un test compare octet par octet. **Limite dite dans `/confidentialite`** : cette résistance vaut à un instant donné. Le seul changement observable dans le temps serait `kdfVersion`, le jour où une version 2 existera.

**Délais de connexion :**

- **Par (adresse, préfixe IP /24 ou /48)** : 5 échecs gratuits, puis `2^(n−5)` min, plafonnés à 60 min. Une réussite remet à zéro. Il n'y a pas de verrouillage permanent.
- **Plafond lâche par adresse, toutes IP confondues** : 100 échecs par jour. Au-delà, blocage de la connexion **pour la journée**, et courriel « connexions bloquées », une seule fois par jour. Risque résiduel, dit : un attaquant qui dispose de nombreux préfixes peut bloquer les nouvelles connexions d'une adresse pendant une journée. Les appareils déjà connectés ne sont pas touchés.
- **Par IP, en mémoire** : 30 échecs par heure.

**nginx.** Deux zones :

- `diapason_compte`, 10 r/min, rafale 5 ;
- `diapason_sync`, 120 r/min, rafale 40, qui couvre aussi `/health`.

**Codes.** Six chiffres, 15 min de validité, 5 essais.

**Budgets de courriel :**

- **Par adresse**, sur **tous** les envois : 1 par minute, 3 par heure, 10 par jour. « Compte existant » et « connexions bloquées » : au plus 1 par jour chacun.
- **Globaux**, deux budgets séparés :
  - **codes et avis non authentifiés**, plafond quotidien fixé d'après l'offre Resend (D12) ;
  - **avis de sécurité**, déclenchés seulement par une action authentifiée ou prouvée par code (mot de passe changé, réinitialisation prévue, suppression). Ce budget est réservé et ne peut pas être épuisé par un inconnu.
- **Épuisement** : quand le budget des codes est épuisé, ou que Resend échoue 5 fois de suite en 10 min (circuit ouvert), `signup/start`, `vault/code` et `reset/request` répondent **503 `mailUnavailable`**, et l'interface le dit. L'épuisement est journalisé.

**Quotas et gardes :**

- **Par compte** : 256 Mio (D10), objet ≤ 4 Mio, pièce ≤ 10 Mio, 50 000 objets, 5 000 pièces.
- **Garde globale** : toute écriture est refusée (507 `serverFull`) si `comptes.db` dépasse **2 Go** (D10), ou s'il reste **moins de 20 Go libres** sur `/`. 20 Go couvrent la marge du §3.9 et laissent le reste à Flashprime (91 Go libres relevés).
- **Inscriptions** : `INSCRIPTIONS_OUVERTES=0|1`, avec 503 `signupClosed` quand elles sont fermées. Le service est déployé fermé.

**Envoi (Resend).**

- `urllib.request` vers `https://api.resend.com/emails`, avec un délai de 10 s, depuis le fil dédié. Un seul nouvel essai 30 s plus tard.
- Échec journalisé sous les 8 premiers caractères hex de l'index, jamais l'adresse.
- Courriels bilingues (FR puis EN), sans image ni pixel, **sans lien porteur de jeton** (les liens `diapason://` sont morts, `lib.rs:5495-5499`).
- `Reply-To` vers une boîte lue (D17). Suivi Resend désactivé.
- **Compte Resend distinct de celui de Flashprime** (D12), pour que plaintes et quotas de Diapason n'atteignent jamais le courrier de production de Flashprime.
- Chaque courriel se termine par : « Diapason ne vous demandera jamais votre mot de passe ni votre clé de récupération. »

**Textes de l'interface** (§100) :

- **Après l'envoi d'un code** :
  > Si un compte peut être créé avec cette adresse, nous essayons d'y envoyer un code. Rien après deux minutes ? Vérifiez l'adresse et les indésirables, puis [Renvoyer].

  Le bouton [Renvoyer] s'active après 60 s.
- **Sur `mailUnavailable`** :
  > L'envoi de courriels est momentanément indisponible. Rien n'a été créé ; réessayez plus tard.

**Modèles de courriel** :

- code d'inscription ;
- compte existant ;
- nouvelle connexion ;
- code du coffre ;
- mot de passe changé ;
- clé de récupération utilisée, remplacée ou retirée ;
- appareil déconnecté et clés renouvelées ;
- connexions bloquées ;
- code de réinitialisation ;
- réinitialisation prévue, annulée ou effectuée ;
- compte supprimé.

### 3.6 Réinitialisation (oubli sans rien)

1. **`reset/request` puis `reset/confirm`** fixent `effectiveAt` à maintenant + 72 h, ou à maintenant + 7 jours si une session a été vue dans les 30 derniers jours.
2. **Le compte signale l'attente partout où il peut** :
   - **Côté serveur** : `pendingResetAt` figure dans `meta` de chaque réponse de `/sync/*`, dans `/login` et dans `/account`.
   - **Sur chaque appareil connecté** : état local `resetPending`, bandeau permanent, notification système au premier constat et [Annuler].
   - **Par courriel** : « réinitialisation prévue ». C'est un filet secondaire, puisque la boîte peut être celle de l'attaquant (A3).
3. **`reset/cancel`** est accepté depuis n'importe quelle session.
4. **Après `effectiveAt`** : un nouveau code, puis `reset/complete`, qui fait **tout en une transaction** : effacement, nouveau coffre, nouveau trousseau, `incarnation + 1`, `keyEpoch = 1`, révocation des sessions. Le timer n'efface **rien**. La version précédente faisait effacer ailleurs, ce qui laissait un état incohérent.

### 3.7 Sessions

- **Jeton** : `"dps1_" + base64url(token_bytes(32))`. Seul son SHA-256 est gardé (motif `succes/sync.py:40-41`).
- **Durée** : 90 jours d'inactivité, glissants.
- **Révocation** : consultée à chaque requête.

**Ce qu'une session seule permet** (texte corrigé) :

- lire le chiffré et les métadonnées du compte ;
- pousser des objets, ce qui écrase temporairement la version du serveur. Les appareils se réparent seuls (§4.6), et la version précédente reste 30 jours ;
- marquer des pièces orphelines. Elles sont réclamées de nouveau à la prochaine synchronisation complète d'un appareil ;
- annuler une réinitialisation.

**Ce qu'elle ne permet pas** :

- obtenir une enveloppe AMK ;
- modifier le coffre ou le trousseau ;
- révoquer une session ;
- supprimer le compte.

Ces actions exigent `authKey`, ou une session **plus** un code.

**Côté local**, un 401 du VPS devient **409 `sessionExpired`**, jamais un 401, parce qu'`apiFetch` rejoue les 401 (`api.ts:191-201`). Sur `sessionRevoked`, l'appareil efface l'AMK mémorisée, le jeton et `enveloppe_locale`, puis passe en `sessionExpired`. **Un changement de mot de passe fait ailleurs atteint donc cet appareil au premier contact.**

### 3.8 Routes locales `/v1/account/*` (serveur de chaque appareil)

**Montage** : `src/diapason/server/compte_routes.py`, sur l'app de boucle locale, à côté des conversations (`app.py:414-421`), derrière la clé locale. Jamais dans `mesh/routes.py` ni `files_routes.py`. `_PORTES_LAN` ne change pas.

**Règles** :

- tout en `def` synchrone ;
- validation écrite à la main ;
- **jamais de 401** : un compte verrouillé renvoie 423 `accountLocked`, les autres cas 409 `sessionExpired`, `localOnly`, `alreadyConnected` ou `notConnected` ;
- **un seau de limitation propre** dans `auth_middleware.py`. La phrase « seule route exemptée » de la version précédente était fausse (`:290-326`).
  - `GET /v1/account/status` est exempté, puisque les vues le sondent.
  - `POST /v1/account/unlock` est strict : 5 essais, puis 30 s d'attente, en plus du seau.
  - Le reste passe par un seau large, distinct du seau commun de 60 par minute, que le poller vocal vide (`:292-297`).

| Route locale | Corps → réponse |
|---|---|
| `GET /v1/account/status` | → `{state, email?, remembered, protector:"keychain"\|"dpapi"\|"file"\|"memory", rememberAllowed, recoveryConfigured, backupMeans:{recoveryKey:bool, rememberedDevices:int\|null}, onboarding, localConversations, sync:{state, serverSeq, lastConfirmedAt, pendingCount, quarantinedCount, repairedCount, errorCode}, clockSkewMs, pendingResetAt}`. `state` vaut l'un de : `none`, `signupInProgress`, `locked`, `unlocked`, `sessionExpired`, `resetPending`, `accountReset`, `accountDeleted`, `serverRolledBack` ou `serverLost`. |
| `POST /v1/account/signup/start` · `/verify` · `/prepare` · `/complete` | `{email, termsAccepted}` · `{code}` · `{password, remember}` → `{recoveryKey, confirmGroups}` · `{recoveryExcerpt}` \| `{skipRecovery:true}` |
| `POST /v1/account/login` · `/unlock` · `/lock` | `{email, password, remember}` · `{password}` · `{}` |
| `POST /v1/account/password` | `{currentPassword, newPassword}` → rotation |
| `POST /v1/account/password/forgotten-here/code` · `/forgotten-here` | `{}` · `{code, newPassword}` → rotation. Exige cet appareil **déverrouillé en ce moment**. |
| `POST /v1/account/recover` | `{email, recoveryKey, newPassword, remember, keepRecoveryKey:false}` → `{newRecoveryKey?}` → rotation |
| `POST /v1/account/recovery-key` · `/confirm` · `/remove` | `{password}` → `{recoveryKey, confirmGroups}` · `{recoveryExcerpt}` · `{password}` → rotation |
| `POST /v1/account/reset/request` · `/confirm` · `/cancel` · `/complete` | comme au VPS, plus `newPassword` et `remember` |
| `GET /v1/account/devices` · `POST /v1/account/devices/{id}/disconnect` | · `{password}` → rotation et révocation de toutes les autres sessions |
| `POST /v1/account/logout` · `/delete` | `{eraseLocalData:false}` · `{password, eraseLocalData:false}` |
| `POST /v1/account/sync/consent` · `/sync-now` · `/onboarding/done` | `{}` |

**Modules** : `compte/{cles, enveloppe, recuperation, trousseau, transport, client, etat, gardien, serrure, service, synchro}.py`, plus `compte/collections/`.

### 3.9 nginx, sauvegardes, déploiement, retour arrière

**nginx**, uniquement dans `zz-diapason.conf` :

- **En tête** : les zones `diapason_compte` et `diapason_sync`, puis :
  ```
  log_format diapason_api '[$time_local] "$request_method $uri" $status $body_bytes_sent $request_time';
  ```
  Ce format n'a ni IP ni chaîne de requête (D11).
- **Les `location`** :
  - `location = /api/v1/health` : zone `diapason_sync`, pour qu'un sondage régulier n'épuise pas la zone de compte derrière un NAT ;
  - `^~ /api/v1/pieces/` : `client_max_body_size 11m` ;
  - `^~ /api/v1/sync/` : `12m` ;
  - `^~ /api/` : `64k`.
- **Chaque `location` porte** :
  - `proxy_pass http://127.0.0.1:8710;` sans URI ;
  - `gzip off` ;
  - `limit_req_status 429` et `limit_req_log_level info` ;
  - `error_log /var/log/nginx/diapason.api.error.log crit;`, pour ne pas garder l'IP des refus ;
  - `access_log /var/log/nginx/diapason.api.log diapason_api`.
- **Aucun `add_header`** dans ces `location` (piège de `zz-diapason.conf:68-71`).
- **Bloc du port 80** : il reçoit son propre `access_log … diapason_api`, au lieu d'hériter du format `combined` de `nginx.conf:40`.
- **Côté client, repli sur un 429 sans corps JSON** (celui de nginx) : attente de 60 s. Le décalage d'horloge se mesure sur l'en-tête `Date` des réponses de `/sync`.

**Sauvegardes** : `diapason-sauvegarde.{service,timer}`, à 04:15 UTC, hors des fenêtres de Flashprime (00:31, 02:30-02:45, 03:00, 03:06).

- **Unité** : `CPUQuota=25%`, `IOSchedulingClass=idle`, `Nice=19`, `MemoryMax=200M`.
- **`deploy/vps/comptes/sauvegarder.py`** :
  1. **Exige un espace libre d'au moins `taille(db) × 1,2 + 15 Go`**. Sinon il sort en code 1, sans rien écrire.
  2. Copie par `sqlite3.Connection.backup` vers `/var/backups/diapason/comptes-AAAAMMJJ.db`, en 0700.
  3. Lance `PRAGMA integrity_check` sur la copie. Si le résultat n'est pas `ok`, il sort en code 1.
  4. **Rétention par budget** : 10 Go au total, 14 copies au plus, et toujours au moins la dernière copie valide. Les plus anciennes sont supprimées d'abord.
  5. Tronque `evenements.jsonl` (§3.3).
  6. N'exécute **aucune** réinitialisation.
- **Test** : un faux `shutil.disk_usage` qui annonce 5 Go libres fait refuser la copie.
- **Copie hors du VPS** (D18) : un `rsync` quotidien tiré par le Mac de Carlito (agent launchd) récupère la dernière copie et le journal. `comptes.env` est gardé à part, **pas sur ce même Mac** : gestionnaire de mots de passe ou papier.

**Déploiement** : `deploy/vps/deployer-comptes.sh`.

1. Garde `case "$RACINE"` et refus d'un arbre sale (motifs de `deployer-site.sh:14-34`).
2. `rsync` du code, puis `pip install --require-hashes -r deploy/vps/comptes/requirements.txt`. Ce fichier est compilé par `uv pip compile --python-version 3.12 --python-platform x86_64-manylinux_2_28 --generate-hashes`.
3. `systemctl restart diapason-comptes`.
4. `curl -fsS …/api/v1/health` **et** `curl -fsS https://flashprime.online/`.

**Prérequis nommé** : `apt install python3.12-venv`, absent du VPS (`import ensurepip` échoue). Il n'installe rien d'autre, puisque le candidat est identique à la version installée. À faire avec l'accord de Carlito.

**Modification nginx** : copie, `nginx -t; rc=$?`, restauration si `rc≠0`, sinon `reload`. Jamais `nginx -t | …`.

**Retour arrière : jamais par l'instantané Hostinger.** Hostinger ne garde qu'un instantané par VPS, et en créer un écrase le précédent. Une restauration réécrit **tout** le disque, donc la production de Flashprime (PostgreSQL, api, web, admin, minio, redis). Ces faits viennent des pages de support citées par la revue exploitation et restent à confirmer dans le panneau. En conséquence :

- **Chaque étape du VPS a son script de retour arrière local**, `deploy/vps/comptes/defaire.sh <étape>`, idempotent :
  - `systemctl disable --now diapason-comptes diapason-sauvegarde.timer` ;
  - retrait des blocs `/api` et des zones, `nginx -t; rc=$?`, puis `reload` ;
  - `userdel diapason` ;
  - `rm -rf /opt/diapason /var/lib/diapason /var/backups/diapason` ;
  - `apt remove python3.12-venv`.
- **Tests** : ces scripts sont d'abord essayés sur une VM Ubuntu 24.04 jetable. Une VM arm64 sur ce Mac valide les scripts ; les roues sont validées sur le VPS même.
- **Aucun instantané n'est pris sans le propriétaire de Flashprime.** On lui demande s'il en garde un, et on obtient son accord écrit (D23).
- **`deploy/vps/README.md`, règle 3**, est réécrite dans le même commit que les scripts : « l'instantané appartient à la machine entière ; il ne se prend et ne se restaure jamais sans le propriétaire de Flashprime ; Diapason se défait par `defaire.sh` ».

**Ne jamais redémarrer la machine**, même si `reboot-required` est en attente.

### 3.10 Restauration, perte et retour arrière du serveur

| Événement | Côté VPS | Côté appareil |
|---|---|---|
| **Restauration logique** (copie de `/var/backups`) | `diapason-comptes-admin restaurer <copie>` : 1) copie ; 2) **rejoue `evenements.jsonl`** postérieur à la copie : comptes supprimés de nouveau, coffres et trousseaux remis à leur dernière version, `reset/complete` rejoués ; 3) **vide `sessions` et `jetons_temporaires`** ; 4) change `generation`. | Il voit une `generation` nouvelle, remet **seulement le curseur** à 0, garde ses planchers, tire tout et repousse ce qui manque (§4.5). Les sessions ayant été vidées, il se reconnecte avec le mot de passe **courant**, puisque le journal a rejoué le coffre. |
| **Retour arrière de toute la machine** (instantané, sauvegarde Hostinger) | Le journal recule avec le reste. `generation` ne change pas, mais `globalSeq` recule. | Si `globalSeq` est inférieur au maximum vu, ou si `serverSeq` est inférieur au curseur, l'état passe à `serverRolledBack` (texte plus bas). L'appareil refuse tout coffre, trousseau ou révision sous ses planchers. Après connexion, une **rotation est obligatoire**, avec `newVaultVersion = max(plancher, serveur) + 1`, puis tout est repoussé. |
| **Perte du VPS ou base neuve** | — | Si la `generation` de `/health` est inconnue et que la session ou la connexion échoue, l'état passe à `serverLost` (texte plus bas). L'appareil repasse par l'inscription, puis repousse tout, planchers de suppression compris. |

**Texte de `serverRolledBack`** :

> Le serveur de comptes est revenu à un état antérieur. Vos données sont intactes sur cet appareil. Connectez-vous avec le mot de passe que vous utilisiez avant le {date du dernier changement, gardée localement}, ou avec votre clé de récupération. Diapason renouvellera ensuite les clés et renverra vos données.

**Texte de `serverLost`** :

> Le serveur de comptes a perdu vos données de compte. Vos conversations sont intactes sur cet appareil. [Recréer le compte avec la même adresse]

**Ce que cela dit dans `/conditions`** : la perte du serveur efface les comptes, pas les données des appareils.

### 3.11 Parcours et ce que chaque écran dit

**P1 — Premier lancement.**

- **Où et quand** : `EcranCompte` se place entre `SetupScreen` et les routes (`App.tsx:350-356`), dans la fenêtre Tauri seulement, une seule fois. Le drapeau `onboarding` est gardé dans `compte/etat.key`, jamais dans le `localStorage`. L'écran arrive après le téléchargement du modèle (D13).
  > Diapason fonctionne sans compte. Un compte ne sert qu'à retrouver vos conversations sur un autre ordinateur. Elles sont chiffrées sur cet appareil avant de partir ; le serveur les garde sans pouvoir les lire.
  > [Créer un compte] [J'ai déjà un compte] [Plus tard — tout reste sur cet appareil]
- **Étapes** :
  1. Adresse et conditions.
  2. Code.
  3. Mot de passe, saisi deux fois. La case « Garder cet appareil déverrouillé » est **décochée**. Son sous-texte reprend le §2.11. Elle est grisée si `rememberAllowed` est faux.
  4. Clé de récupération : Copier, Imprimer, ressaisir deux groupes. [Continuer sans clé] ouvre une confirmation en ton `danger` (D4).
  5. Ce qui se synchronise.
  6. « Envoyé et confirmé par le serveur : 9/9 (n° 57) ».
- **Encadré permanent de l'étape 3** (texte corrigé : un appareil ne sauve rien s'il n'est pas déverrouillé) :
  > Votre mot de passe chiffre vos données. Personne, nous compris, ne peut le retrouver ni le réinitialiser en gardant vos données. Si vous l'oubliez, deux choses permettent d'en choisir un nouveau : votre clé de récupération, ou un autre de vos appareils **resté déverrouillé** (case « Garder cet appareil déverrouillé » cochée, ou Diapason encore ouvert et déverrouillé). Sans l'une ni l'autre, la copie du serveur est perdue ; ce qui est sur vos appareils ne l'est pas.
- **Moyens de secours** : dans Réglages › Compte, un bloc permanent compte les moyens réels, par la fonction pure `moyensDeSecours(status)` testée par vitest : « clé de récupération confirmée », plus les appareils mémorisés. **S'il y en a zéro, un avertissement reste affiché.**

**P2 — Code interrompu.** Rien n'existe sur le VPS avant `signup/complete`. On recommence à l'étape du code.

**P3 — Second appareil.** Connexion, puis déverrouillage. Si des conversations locales existent, l'état passe à `needsConsent` :

> Cet appareil a déjà 3 conversations. Elles seront chiffrées et ajoutées à votre compte, et apparaîtront sur vos autres appareils. [Ajouter] [Annuler la connexion]

**P4 — Mot de passe oublié.** Trois chemins :

1. **« J'ai ma clé de récupération »** : rotation ; toutes les autres sessions sont révoquées ; une nouvelle clé est proposée par défaut.
2. **« Un autre appareil est resté déverrouillé »** : l'écran donne la marche à suivre sur cet appareil. Il faut ce déverrouillage **et** un code courriel.
3. **« Ni l'un ni l'autre »**, en ton danger :
   > La copie chiffrée du serveur ne peut plus être relue par personne, nous compris. Vous pouvez réinitialiser le compte : après {72 heures | 7 jours}, pendant lesquels chacun de vos appareils connectés affichera un avertissement et pourra annuler, elle sera effacée et remplacée par les données de CET appareil. Vos autres appareils devront se reconnecter ; ce qu'ils ont en local sera renvoyé sous la nouvelle clé.

**P5 — Changement de mot de passe.**

> Mot de passe changé et clés renouvelées. Ce qui sera écrit désormais ne peut plus être lu avec l'ancien mot de passe. Ce qui a été écrit avant reste lisible par qui l'aurait déjà obtenu. Vos autres appareils vous demanderont le nouveau mot de passe ; un appareil resté hors ligne s'ouvre encore localement avec l'ancien, sans rien recevoir, jusqu'à son prochain contact avec le serveur.

**P6 — Appareil perdu.** Réglages › Compte › Appareils › [Déconnecter], avec le mot de passe :

> Cet appareil ne recevra plus rien, et ce que vous écrirez désormais lui restera illisible. Ce qu'il contient déjà reste lisible par quiconque ouvre sa session : la déconnexion n'efface rien à distance. Vos autres appareils vous redemanderont le mot de passe. Si votre mot de passe a pu être vu, changez-le aussi.

**P7 — Déconnexion de cet appareil.**

> Vos conversations restent sur cet appareil, en clair comme avant le compte. N modifications n'ont pas encore été envoyées : elles resteront ici seulement.

**P8 — Suppression du compte.** Il faut le mot de passe.

- **Effacé** : adresse, enveloppes, données chiffrées, sessions.
- **Reste** :
  - les données en clair de vos appareils ;
  - les sauvegardes de Diapason, 14 jours au plus ;
  - les sauvegardes et l'instantané de l'hébergeur, jusqu'à {N} jours, à {lieu}. Ces valeurs sont relevées dans le panneau à l'étape 0 ; tant qu'elles ne le sont pas, la page ne s'ouvre pas ;
  - les journaux nginx, environ 15 jours ;
  - journald, 7 jours.
- **Cas d'une restauration** : si le serveur devait être restauré, le journal d'événements efface de nouveau le compte supprimé. Ce n'est pas vrai pour une restauration de toute la machine par l'hébergeur (§3.10).

**P9 — États courants.** Quelques exemples de textes :

- « Hors ligne depuis 14:02 — 3 modifications en attente » ;
- « Verrouillé — la synchronisation reprendra après le mot de passe » ;
- « Réinitialisation du compte prévue le {date} — [Annuler] » ;
- « L'horloge de cet appareil a 4 min d'écart : en cas de modifications simultanées, l'appareil en avance l'emportera ».

**P10 — Fermeture de l'app.**

- Sur `ExitRequested`, Tauri appelle `api.prevent_exit()`, puis `POST /v1/account/sync-now` avec un délai de 3 s, puis `stop_all`, puis `app.exit(0)`. Un drapeau évite la boucle.
- Si `pendingCount > 0` au lancement suivant, l'app affiche : « N modifications n'avaient pas pu partir à la fermeture ; elles partent maintenant. »

**Place dans l'interface.**

- **Réglages** : Section « Compte et chiffrement » après Connexion (`SettingsPage.tsx:678`), en blocs `w-full max-w-*`, sans `SettingRow` à largeur fixe (règles du mini-panneau).
- **« Effacer »** (`SettingsPage.tsx:484-501`) : avec un compte, le texte dit « sur cet appareil **et sur vos autres appareils synchronisés** ».
- **Bandeau** `Layout.tsx:99-122` : `locked`, `sessionExpired`, `resetPending`, `accountReset`, `serverRolledBack` et `serverLost`.
- **Mini-panneau** : état et déverrouillage seulement (D14).
- **Jamais de mot de passe par la voix ni par la dictée**, puisque `dictation_history.jsonl` journalise le texte. Le §82 du cahier reste respecté par le clavier et le clic.

### 3.12 `local_only`

`local_only = True` par défaut (`config.py:1823-1827`), et `assert_may_leave` refuse tout (`local_mode.py:139-165`). La recommandation (D1) est une **troisième frontière étroite**, `compte/transport.py:assert_may_reach_account_server(url)`, sur le modèle de `mesh/transport.assert_may_reach_device`. Quatre conditions :

1. **L'origine est une constante du code**, `SERVEUR_COMPTES`, versionnée. Une surcharge par `DIAPASON_SERVEUR_COMPTES` n'est pas exemptée. Changer d'origine demande une nouvelle version de l'app, et le runbook de publication le dit (D3).
2. **Le compte s'active par un geste explicite**, depuis un écran qui nomme la destination.
3. **La synchronisation ne transporte que des `EnveloppeChiffree`.** Le transport refuse tout autre type.
4. **Sans compte, rien ne part.**

**Mise à jour des textes**, dans le même commit que l'ouverture :

- la docstring de `local_mode.py:44-64` ;
- **`PRIVACY.md:60-64`** et `/confidentialite` : « `local_only` bloque toute sortie, sauf l'envoi de données déjà chiffrées vers le serveur de comptes, après que vous avez activé un compte. Cet envoi se fait en tâche de fond. »

Un test anti-divergence protège ce texte.

### 3.13 `owner_id` et maillage

Le compte et la flotte restent indépendants (D9) :

- `owner_id` n'est jamais envoyé au VPS ;
- aucune enveloppe du maillage ne change ;
- `device_key` et `seal_key` ne servent jamais au compte.

---

## 4. Synchronisation

### 4.1 Topologie

```
vue fenêtre (tauri://localhost) ──┐  convSync.ts — INCHANGÉ
vue mini-panneau (127.0.0.1:8000) ┘
            ⇅  JSON, clé locale, en clair
serveur local : ConversationsStore (clair) + compte/synchro.py (tâche du lifespan) + compte/etat.key
            ⇅  HTTPS, httpx, blobs DPE1
VPS : objets (compte, objectId, rev, seq, blob [+ précédent]), pièces, meta
```

Le moteur est un **second client** du `ConversationsStore` (`app.state.conversations_store`, `app.py:419-421`). `fusionner_conversations` (`conversations_store.py:190`) est une jointure : pousser toujours la jointure de ce qu'on a et de ce qu'on a vu fait converger les appareils.

### 4.2 État local (`compte/etat.key`)

```sql
CREATE TABLE etat (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
  -- accountId, email, incarnation, generation, globalSeqMax, curseurDistant, onboarding, etatCompte,
  -- lastConfirmedAt, serverSeq, clockSkewMs, sessionId, consentement, pendingResetAt, dernierCommitMs
CREATE TABLE planchers_compte (id INTEGER PRIMARY KEY CHECK (id = 1),
  vault_version_max INTEGER NOT NULL, keyring_version_max INTEGER NOT NULL, key_epoch_max INTEGER NOT NULL);
CREATE TABLE enveloppe_locale (id INTEGER PRIMARY KEY CHECK (id = 1),
  kdf_version INTEGER NOT NULL, sel_kdf BLOB NOT NULL, amk_mdp BLOB NOT NULL,
  trousseau BLOB NOT NULL, version_coffre INTEGER NOT NULL, version_trousseau INTEGER NOT NULL);
-- Tout ce qui suit porte (account_id, incarnation) et est vidé quand l'un change.
CREATE TABLE connus (account_id TEXT, incarnation INTEGER, collection TEXT, id_local TEXT,
  object_id TEXT NOT NULL, rev_max INTEGER NOT NULL, seq INTEGER NOT NULL, empreinte BLOB,
  illisible INTEGER NOT NULL DEFAULT 0, degrade INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, incarnation, collection, id_local));
CREATE TABLE curseurs_export (account_id TEXT, incarnation INTEGER, collection TEXT, seq_local INTEGER NOT NULL,
  PRIMARY KEY (account_id, incarnation, collection));
CREATE TABLE sortants (account_id TEXT, incarnation INTEGER, collection TEXT, id_local TEXT,
  supprime_le_ms INTEGER, empreinte_poussee BLOB, tentatives INTEGER NOT NULL DEFAULT 0,
  prochain_essai_ms INTEGER NOT NULL DEFAULT 0, derniere_erreur TEXT,
  PRIMARY KEY (account_id, incarnation, collection, id_local));
CREATE TABLE quarantaine (account_id TEXT, incarnation INTEGER, object_id TEXT, motif TEXT NOT NULL,
  empreinte BLOB, depuis_ms INTEGER NOT NULL, PRIMARY KEY (account_id, incarnation, object_id));
CREATE TABLE inconnus (account_id TEXT, incarnation INTEGER, object_id TEXT, rev INTEGER, seq INTEGER, blob BLOB,
  PRIMARY KEY (account_id, incarnation, object_id));
CREATE TABLE pieces_connues (account_id TEXT, incarnation INTEGER, key_epoch INTEGER, piece_id TEXT,
  PRIMARY KEY (account_id, incarnation, key_epoch, piece_id));
CREATE TABLE a_reprendre (account_id TEXT, incarnation INTEGER, object_id TEXT, motif TEXT, prochain_essai_ms INTEGER,
  PRIMARY KEY (account_id, incarnation, object_id));
-- Survit aux incarnations et aux générations ; vidée à la déconnexion ou sous un autre compte.
CREATE TABLE planchers_suppression (account_id TEXT, collection TEXT, id_local TEXT, deleted_at INTEGER NOT NULL,
  PRIMARY KEY (account_id, collection, id_local));
```

### 4.3 Le cycle

**Lancement.** Une tâche asyncio dans le lifespan de `create_app`, à côté de `_mesh_heartbeat` (`app.py:253-273`), avec `except CancelledError: raise`. Le travail passe par `await asyncio.to_thread(cycle)`, **sous un `threading.Lock` d'exclusivité** : « Synchroniser maintenant » et la tâche ne se chevauchent jamais. Ce n'est pas le `TaskScheduler`, qui passe derrière le créneau unique d'Ollama.

**Réveil.** Un hook `sur_ecriture` du magasin pose un `asyncio.Event` par `loop.call_soon_threadsafe`.

| Paramètre | Valeur | Raison |
|---|---|---|
| `_CALME_S` | 5 s | La vue pousse toutes les 1,2 s pendant un flux (`convSync.ts:67`). Une réponse de 60 s ferait 50 envois, contre deux plus le final avec ce calme. |
| `_POUSSEE_MAX_S` | 30 s | Une réponse longue n'attend pas indéfiniment. |
| `_TIRAGE_S` | 30 s si une vue a sondé dans la dernière minute, 300 s sinon | Suffit entre appareils, et reste léger pour 2 vCPU partagés. |
| Repli | 30 s → 15 min, ±20 % | `retryAfterS`, ou 60 s sur un 429 nginx sans corps. |
| Réclamation des pièces | au plus une fois par jour, après un tirage complet | Rattrape une pièce marquée orpheline à tort (§4.7). |

```
cycle():
  0. PORTÉE — (accountId, incarnation) courants ≠ ceux des tables → PURGER toutes les tables de portée
     (sauf planchers_suppression si même accountId), curseurDistant=0, état needsConsent si des données locales existent.
  1. EXPORTER — toujours, même verrouillé, hors ligne ou sous local_only (n'écrit que etat.key)
     (changés, seqLocal) = C.changements_depuis(curseur) → sortants (+ supprime_le_ms ; planchers_suppression)
  2. état ≠ unlocked → "paused" ; consentement manquant → "needsConsent" ; fin
     assert_may_reach_account_server()    ← AVANT de lire le jeton
  3. TIRER (≤ 200 éléments / ≤ 8 Mio par page) ; si la portée vient d'être purgée : since=0 AVANT toute poussée
     meta : incarnation ≠ → "accountReset", arrêt ; keyEpoch/vaultVersion/keyringVersion > connus → recharger le trousseau
            (session révoquée → sessionExpired) ; < planchers → "serverRolledBack", arrêt
            pendingResetAt → "resetPending" (+ notification au premier constat)
            generation ≠ ou serverSeq < curseurDistant → curseurDistant = 0 SEULEMENT (planchers conservés)
     pour chaque item :
       rev < connus.rev_max → NE PAS ingérer ; mettre (C,id) en sortants avec baseRev = item.rev (réaffirmation)
       rev = connus.rev_max et empreinte connue → ignorer
       ouvrir(blob, AAD) ; échec → connus.rev_max = item.rev, illisible=1 ;
             version locale présente → sortants (autoréparation, repairedCount+1)
             sinon → GET /sync/previous ; ouvrable → ingérer + sortants ; sinon quarantaine "illisible" (visible)
       objectId recalculé ≠ → quarantaine "permute"
       version/collection/schéma inconnus → inconnus
       vivant avec updatedAt ≤ planchers_suppression.deleted_at → NE PAS ingérer ; sortants (repousser la tombale)
       pièce en 404 → appliquer SANS la pièce, degrade=1 (jamais de report)
       autre échec transitoire (5xx pièce) → a_reprendre ; le curseur AVANCE quand même
       sinon C.ingerer(clair) ; connus = (item.rev, item.seq, H(clair)) ;
             H(C.clair_local(id)) ≠ H(clair) → sortants
     curseurDistant = until
  4. POUSSER (lots ≤ 50 / ≤ 8 Mio)
     (C,id) échus : si supprime_le_ms ≥ updatedAt du clair local, ou clair local absent → tombale ; sinon clair_local
       H(clair) = connus.empreinte et non illisible → retirer
       pièces d'abord : /pieces/missing{asOfSeq} puis PUT des manquantes (clé K_piece de l'époque courante)
       objet dégradé → relire la version serveur et fusionner AVANT de pousser
       item = {objectId, baseRev: connus.rev_max ou 0, blob: sceller(clair, rev = baseRev+1, keyEpoch courant)}
       empreinte_poussee = H(clair)
     stored → connus ; DELETE FROM sortants WHERE … AND empreinte_poussee = H poussée (une ré-exportation plus récente survit)
     conflict → ingérer current (ou rev 0 si null) ; connus.rev_max = current.rev ; rejouer (≤ 3 fois par cycle)
     rejected → quarantaine visible ; quotaExceeded / serverFull → état
     keyEpochChanged → recharger le trousseau (session révoquée → sessionExpired)
  5. "upToDate" SEULEMENT si : portée à jour, sortants vide, a_reprendre vide, serverSeq rendu par le VPS,
     aucun plancher dépassé. lastConfirmedAt = maintenant.
```

### 4.4 Planchers (anti-rejeu)

**Ce qu'on retient.** Pour chaque objet connu, `connus.rev_max`. Pour chaque suppression, `planchers_suppression.deleted_at`, toute la vie du compte, soit environ 60 o par conversation supprimée. Pour le compte, `vault_version_max`, `keyring_version_max` et `key_epoch_max`.

**Ce qu'aucune valeur serveur ne remet à zéro.** Ni une `generation` nouvelle, ni un `serverSeq` qui recule. La version précédente vidait `connus` sur une `generation` nouvelle, alors que la `generation` n'est authentifiée par rien. Un VPS hostile pouvait donc la changer puis servir la version d'avant une suppression, avec sa vraie `rev` et une AAD valide : la conversation ressuscitait partout. Les revues cryptographie et protocole l'ont relevé indépendamment.

**Ce qui les vide.** Une incarnation nouvelle, confirmée par `/login` ou `reset/complete` avec des clés neuves, vide les tables de portée. Les planchers de suppression restent. Une déconnexion ou un autre compte vide tout.

**Refus.** Un coffre ou un trousseau sous le plancher est refusé avec le code `serverKeyStale`, sauf dans le parcours `serverRolledBack`. Celui-ci exige le mot de passe de l'époque et se termine par une rotation au-dessus du plancher.

### 4.5 Conflits, restauration, réinitialisation

**Comparer-et-échanger sur `rev`.** `rev` figure dans l'AAD, et un conflit rend `current`. On converge en au plus deux allers-retours une fois les écritures arrêtées.

**Pourquoi le serveur ne tient pas de journal.** Il ne garde qu'une ligne par objet, plus la précédente pendant 30 jours. `succes_operations`, 306 Mo sur 311, montre ce qu'un journal en ajout seul coûterait.

**`generation` nouvelle.** Le curseur revient à 0 et l'appareil tire tout. Ce qui diffère ou manque au serveur repasse dans `sortants`. Les planchers ne bougent pas.

**Réinitialisation, ou connexion à un autre compte** (défaut bloquant de la revue protocole). L'étape 0 du cycle purge la portée. Toutes les conversations locales, vivantes ou supprimées d'après `planchers_suppression`, repassent dans `sortants`. Le premier tirage se fait avec `since=0` avant toute poussée, pour que `baseRev` vienne du serveur. `upToDate` n'apparaît qu'une fois tout confirmé.

### 4.6 Suppressions

- **Du local vers le VPS.** La tombale part comme un objet chiffré `{"deleted":{"deletedAt":…}}` et reçoit un plancher de suppression.
- **Du VPS vers le local.** Nouvelle méthode `ConversationsStore.appliquer_tombale(id, deleted_at)`, qui applique la règle d'`upsert` à la lettre (`conversations_store.py:322-324`).
- **Datation.** `delete` date la tombale `max(maintenant, existante, updated_at_stocké + 1)`. Une suppression l'emporte donc toujours sur ce qu'elle a vu, même si cette version venait d'une horloge en avance.
- **Purge locale bornée par la confirmation, pas par l'export** (revue protocole). Le magasin reçoit `peut_purger: Callable[[str, int], bool] | None`. Avec un compte, une tombale de plus de 30 jours n'est purgée que si trois conditions tiennent :
  1. aucune ligne `sortants` n'existe pour elle ;
  2. `connus.empreinte` vaut H(tombale), autrement dit le serveur l'a confirmée ;
  3. `planchers_suppression` la contient.
  Sans compte, `None` : le comportement est celui d'aujourd'hui. Même purgée localement, la suppression reste défendue par son plancher.
- **Rétention sur le VPS** : toute la vie du compte.
- **Propriété assumée** : une modification faite **sans avoir vu** la suppression ressuscite la conversation entière. C'est la règle d'union existante.

**Autoréparation contre un jeton volé (A9).** Un blob illisible avec une version locale est réécrasé aussitôt. Sans version locale, la version précédente est tentée. Le compteur `repairedCount` est affiché : « 3 éléments illisibles sur le serveur ont été réparés depuis cet appareil. Si ce n'est pas vous, déconnectez les autres appareils. »

### 4.7 Collection `conversations` et pièces

- **`changements_depuis(seq)`** = `store.list(since=seq)` (`:262-299`). Les conversations vierges sont sautées (`discussions.ts:57`).
- **`clair_local(id)`** projette la conversation :
  - **`messages[].audio` est retiré**, puisque son URL pointe vers la machine elle-même (`InputArea.tsx:989`). L'empreinte se calcule sur la projection, ce qui évite toute boucle.
  - **Chaque image `data:` devient une pièce.** On la décode, puis on vérifie que le ré-encodage redonne exactement la chaîne. Si oui, on chiffre `{"header":"data:image/png;base64,"}` avec les octets ; sinon `{"form":"raw"}` avec la chaîne. Dans le clair, l'image devient `"diapason-piece:<pieceId>"`.
- **`ingerer(clair)`** réinjecte les pièces à l'identique, puis appelle `upsert` ou `appliquer_tombale`.
- **Pièce en 404.** L'objet est appliqué sans elle et marqué `degrade`. Avant toute poussée, le moteur relit la version du serveur et fusionne, si bien qu'un appareil dégradé n'efface jamais une image.
- **Orphelines, sans course** (revue protocole). Un appareil ne marque orpheline une pièce qu'après avoir tiré jusqu'à `serverSeq = S`, et envoie `DELETE {asOfSeq: S}`. Le serveur refuse si `reclame_seq > S`, c'est-à-dire si quelqu'un l'a réclamée par `/pieces/missing` depuis. Chaque appareil réclame, au plus une fois par jour, toutes les pièces qu'il référence.
- **Époques.** Après une rotation, la prochaine poussée d'un objet recalcule ses `pieceId` sous `K_piece_{e+1}` et renvoie les images. L'ancienne pièce devient orpheline.
- **Effet mesuré** : environ 1,57 Mo passe à environ 115 Ko par poussée d'une conversation illustrée.
- **Granularité** : un objet par conversation.

### 4.8 Ajouter une collection

L'interface `compte/collections/base.py` demande : `nom`, `schema`, `changements_depuis`, `clair_local`, `ingerer`, `pieces`, `detacher`, `rattacher`.

**Liste blanche** : `COLLECTIONS_SYNCHRONISEES`, calquée sur `SYNC_ENTITIES` (`succes/sync.py:80-104`). Un client ancien met une collection inconnue dans `inconnus`, affiche « mettez Diapason à jour », et la rejoue après la mise à jour.

**Ordre après la v1** :

1. **Mémoire** : il faut d'abord un id par fait et une suppression datée (`memory/store.py:139-172`).
2. **Succès** : on part de `succes_sync_clocks`. Dernier écrit gagne par `_clock_wins` (`sync.py:145-149`). Les suppressions se lisent dans `deleted=1`. Dépend de D16.
3. **Photos Succès**, en pièces.
4. **`USER.md`, `SOUL.md`, `MEMORY.md`, `dictation_dictionary.json`** (D15), avec les conflits gardés dans `compte/conflits/`.
5. **`[privacy]` et `[memory]`** de `config.toml`, au plus.

**Test-fusible `test_jamais_synchronise.py`** :

| Catégorie | Éléments |
|---|---|
| Secrets | `auth/`, `mesh/*`, `mesh.db`, `updater/`, `connectors/*.json`, `whatsapp_baileys_bridge/`, `compte/*` |
| Sécurité | `approvals.db`, `audit.db`, `telemetry.db`, `traces.db`, `anon_id`, `analytics-store.json`, `sync_state.db` |
| Biométrie | `voice_profile.npz`, `claps.json`, `gestes.json`, `reglette*.json` |
| Recalculable | `knowledge.db`, `memory.db`, `digest.db`, `loterie.db`, `cache/`, `logs/`, `models/`, `backups/`, `succes_operations` |

### 4.9 Horloges

`dateEcriture = max(Date.now(), précédente + 1)` (`store.ts:102-104`), appliquée à une copie déjà fusionnée : c'est une horloge de Lamport par conversation. **Aucune HLC n'est ajoutée.**

Reste le cas de deux modifications vraiment concurrentes des métadonnées : l'appareil dont l'horloge est en avance gagne. On le dit :

- `clockSkewMs` est mesuré sur l'en-tête `Date`, corrigé de la moitié de l'aller-retour ;
- un bandeau apparaît au-delà de 120 s ;
- la docstring `conversations_store.py:217-221` est réécrite dans le même commit.

### 4.10 Hors ligne et fermeture

- L'export tourne toujours.
- Sous Windows et chez les autres utilisateurs de macOS, la synchronisation ne tourne que **pendant que l'app est ouverte**. À la fermeture, une dernière poussée a 3 s (P10).
- Sur le Mac de Carlito, le serveur launchd synchronise même l'app fermée.

### 4.11 États affichés (§100)

**Liste des états** :

- `disabled` ;
- `paused` ;
- `needsConsent` ;
- `syncing` ;
- `upToDate` ;
- `pending` ;
- `offline` ;
- `quarantined` ;
- `repaired` ;
- `quotaExceeded` ;
- `serverFull` ;
- `sessionExpired` ;
- `resetPending` ;
- `accountReset` ;
- `accountDeleted` ;
- `serverRolledBack` ;
- `serverLost`.

**Recalcul** : ils sont recalculés à chaque lecture (modèle `etat_de_chiffrement`, `scellement.py:545-581`).

**Libellé « Synchronisé »** : **une seule fonction pure**, `libelleSynchro(sync, maintenant)` dans `frontend/src/lib/compte.ts`, a le droit d'écrire « Synchronisé à 14 h 02 ».

**Journalisation** : un avertissement à la panne, un au rétablissement (modèle `convSync.ts:404-416`).

### 4.12 Face à un VPS hostile (tests)

| Le serveur… | Défense | Test |
|---|---|---|
| échange deux blobs, ou prend un blob d'un autre compte | AAD `{a,o,i}` et `objectId` recalculé | quarantaine, rien n'est écrit |
| présente la révision 3 comme la 5 | AAD `r` | InvalidTag |
| rejoue une vieille version avec sa vraie `rev` | `rev < rev_max` : pas d'ingestion, réaffirmation | rien ne change, le serveur est réécrasé |
| **change `generation` et rejoue une version d'avant une suppression de plus de 40 jours** | plancher de suppression, `connus` conservé | la conversation reste supprimée |
| rejoue un coffre ou un trousseau ancien | AAD `w` et `r`, planchers | `serverKeyStale` |
| retouche l'en-tête | en-tête dans l'AAD | InvalidTag |
| impose un Argon2 faible | versions figées | `kdfDowngrade` |
| rend une enveloppe AMK forgée ou une `pk_rec` à lui | AAD ; `pk_rec` lue dans le trousseau authentifié | `serverKeyInvalid` |
| écrase un objet avec un blob aléatoire (jeton volé) | autoréparation, version précédente | l'objet est restauré, `repairedCount` = 1 |
| cache une tombale à un appareil qui ne l'a jamais vue | **aucune** | risque assumé |
| retient ou efface | **aucune** | ancienneté de `lastConfirmedAt` |
| lit | tout est chiffré | **canari** : un titre et un message uniques introuvables dans les octets de `comptes.db`, de ses sauvegardes et de `evenements.jsonl` |

---

## 5. Pages légales

**Sources et publication.**

- **Sources canoniques** : `deploy/vps/accueil/confidentialite.html` et `conditions.html`, servies par le `try_files $uri.html` existant (`zz-diapason.conf:62-64`).
- **Polices** : VT323 et Press Start 2P sont auto-hébergées (OFL). On retire aussi Google Fonts de `index.html:8-10`.
- **Liens** depuis :
  - le pied de `index.html` ;
  - l'écran d'inscription, dans le navigateur du système (le comportement de `target=_blank` est à vérifier dans WKWebView et WebView2) ;
  - chaque courriel.
- **Autres fichiers** :
  - `PRIVACY.md` devient une copie générée, protégée par un test anti-divergence (modèle `gen_agents_md.py` et `test_agents_md.py`) ;
  - `docs/confidentialite.md` renvoie vers la page canonique ;
  - `docs/telemetry.md:10` est corrigé (déjà faux face à `config.py:1107`).
- **Un seul commit, un seul déploiement, juste avant `INSCRIPTIONS_OUVERTES=1`.** Il contient les pages légales, l'accueil corrigé (`index.html:7`, `:30-33`, « pas de serveur ») et `PRIVACY.md` (`:5-8`, `:60-64`). La raison : `deployer-site.sh:61` publie l'arbre `accueil/` à chaque déploiement de la documentation, si bien qu'une page légale commitée plus tôt partirait en ligne à côté d'un accueil qui dit le contraire. Un test refuse « pas de serveur » dans `index.html` dès que `confidentialite.html` existe.

**`/confidentialite` dit :**

1. Le compte est facultatif. Sans compte, rien ne part.
2. Le §2.9 tel quel, y compris : la suppression visible à la taille, ce qu'un serveur compromis pourrait tenter, et `globalSeq`.
3. On ne peut ni lire ni restituer les données. Ce qui arrive après un oubli sans clé ni appareil déverrouillé.
4. **Ce qu'une copie de la machine permet** (A2′) : « Une copie du seul fichier de base ne permet pas de deviner les mots de passe. Une copie de toute la machine, par exemple une sauvegarde de l'hébergeur, le permet, au prix d'un calcul coûteux par essai. »
5. **Ce qu'une restauration peut ramener** (§3.10).
6. **Sous-traitants et lieux** :
   - Hostinger : serveur à Boston ; lieu des sauvegardes **à relever dans le panneau** ;
   - Resend, aux États-Unis : il voit l'adresse et les codes ;
   - l'agent Monarx ;
   - **le propriétaire de Flashprime**, qui a un accès administrateur à la machine et contrôle le DNS (D3).
7. Les transferts hors du Canada.
8. **Durées** :
   - compte : jusqu'à sa suppression ;
   - sauvegardes Diapason : 14 jours au plus ;
   - sauvegardes et instantané de l'hébergeur : {relevé} ;
   - nginx : environ 15 jours (logrotate daily, rotate 14), **sans adresse IP** (D11) ;
   - journald : 7 jours (`MaxRetentionSec=7day`).
9. `local_only` : ce qu'il bloque, et l'exception du compte.
10. Les droits, et un contact **lu** (D17), pas une issue GitHub publique (`PRIVACY.md:66-69`).
11. Aucune analytique, aucune publicité, aucune revente.
12. Le cadre : Loi 25, LPRPDE, RGPD, **à faire valider par un juriste**.

**`/conditions` dit :**

- service gratuit, fourni tel quel, **places limitées** (garde de 2 Go, D10) ;
- **la synchronisation n'est pas une sauvegarde** ;
- la personne est seule dépositaire de son mot de passe et de sa clé ;
- **le service est hébergé chez un tiers, qui peut l'interrompre sans préavis ; vos données restent sur vos appareils.** Ce texte remplace « préavis de 30 jours », qui ne peut pas être tenu tant que la machine et le domaine ne sont pas à Carlito (D3) ;
- la perte du serveur efface les comptes, pas les données des appareils ;
- quotas et usage acceptable ;
- résiliation ;
- âge minimum et droit applicable ;
- `termsVersion` entier, acceptation datée.

**Tests** : aucune référence à `fonts.googleapis`. Les durées sont importées des constantes du service, et les valeurs Hostinger d'un fichier `deploy/vps/comptes/hebergeur.json` rempli à l'étape 0. Si ce fichier contient `null`, le test échoue, et la page ne peut pas sortir.

---

## 6. Plan d'implémentation ordonné

**Règles pour toutes les étapes :**

- un commit par thème, dont le sujet nomme le défaut (CLAUDE.md §3) ;
- le bloc complet de CLAUDE.md §2 avant de pousser ;
- rien n'est poussé ni déployé sans que Carlito le demande ;
- sur le VPS, aucune écriture sans son accord explicite, et **aucun instantané sans le propriétaire de Flashprime**.

**Correspondance avec les points** :

| Point | Étapes |
|---|---|
| Point 2 (chiffrement) | 1 à 3 |
| **Point 3** (comptes et pages légales) | 4 à 7 |
| **Point 4** (écran d'activation) | 8 et 9 |
| **Point 5** (synchronisation) | 10 et 11 |
| Publication | 12 et 13 |

### Étape 0 — Décisions et relevés (aucun code)

- Carlito tranche les décisions bloquantes (§7).
- **Sur pc-bureau** (Python 3.12 et 3.13) :
  - Argon2id à 256 et 128 Mio ;
  - AESGCM et HPKE de la roue `win_amd64` ;
  - `Path.home()` sous le serveur lancé par Tauri ;
  - `icacls` sur `.diapason` ;
  - **détection d'un compte Windows sans mot de passe**, compte local et compte Microsoft.
- **Dans le panneau Hostinger, avec le propriétaire du compte** :
  - fréquence, conservation et lieu des sauvegardes ;
  - existence d'un instantané, et à qui il sert ;
  - tout est consigné dans `deploy/vps/comptes/hebergeur.json`.
- **Resend** :
  - un compte distinct de celui de Flashprime ;
  - le plafond de l'offre ;
  - le suivi désactivé ;
  - `sudo cut -d= -f1 /etc/diapason/mail.env`, relevé par Carlito : les noms seulement.
- **Fin de l'étape** : `VERSIONS_KDF[1]` est figé.

### Étape 1 — Primitives pures

**Fichiers** :

- `src/diapason/compte/{__init__,cles,enveloppe,recuperation,trousseau}.py` ;
- `scripts/gen_vecteurs_compte.py` ;
- `tests/contract/vecteurs_compte.json`.

**Tests** `tests/compte/test_{cles,enveloppe,recuperation,trousseau,vecteurs}.py` :

- NFC, NFD et pleine chasse donnent les mêmes clés ;
- `authKey` diffère de `KEK` ;
- `kdfVersion` 0 est refusé ;
- objet, compte ou incarnation permutés, en-tête modifié, blob tronqué, zéros non nuls : tous refusés ;
- zéros finaux d'un binaire préservés ;
- `padme` idempotent, surcoût ≤ 12 % ;
- `aad_canonique` lève `TypeError` sur un `float` ou un `bytes` ;
- faute de frappe détectée dans la clé de récupération ;
- **rotation** :
  - l'ancienne enveloppe et l'ancien mot de passe **ne rendent plus** l'AMK courante ;
  - l'ancienne AMK ouvre `DEK_1`, mais pas `DEK_2` ;
- **HPKE** : on scelle vers `pk_rec` sans `R`, et on ouvre avec `R` ;
- **enveloppe AMK de `vaultVersion` inférieure** refusée par le plancher ;
- **`pieceId` différent d'une époque à l'autre** ;
- **clés du clair et du trousseau en anglais**, vérifiées sur le vecteur ;
- vecteurs régénérés à l'identique.

### Étape 2 — Magasin des conversations prêt pour plusieurs horloges

**Changements** dans `conversations_store.py` :

- datation de `delete` ;
- `appliquer_tombale` ;
- `peut_purger` ;
- hook `sur_ecriture` ;
- docstring `:217-221`.

**Tests** :

- une tombale gagne contre une copie datée dans le futur ;
- une tombale distante ancienne perd contre une modification postérieure ;
- **une tombale de 40 jours exportée mais non confirmée survit** ;
- comportement inchangé sans compte ;
- `tests/contract/fusion_conversations.json` inchangé.

### Étape 3 — Protecteurs locaux

**Fichiers** : `compte/gardien.py`, avec `ProtecteurTrousseauMac`, `ProtecteurDpapi`, `ProtecteurFichier`, `ProtecteurMemoire`, `choisir_protecteur()`, `memorisation_permise()`, et l'exclusion Time Machine de `compte/`.

**Tests** :

- **macOS**, avec un service de test unique et un nettoyage garanti, hors de la CI par défaut :
  - preuve que le secret n'apparaît pas dans `ps` ;
  - `tmutil isexcluded` sur `compte/` rend `[Excluded]` ;
- **DPAPI** (`skipif(os.name != "nt")`) : aller-retour, et refus sur un compte sans mot de passe simulé ;
- **jeton de session** rangé dans le protecteur.

Si la preuve `ps` échoue, D7 bascule sur `ProtecteurFichier`.

### Étape 3 bis — Politique de fichiers

Nommer l'état `etat.key` suffit. Aucun changement de `file_policy`. Un test vérifie que `is_sensitive_file(".../compte/etat.key")` rend vrai.

### Étape 4 — Service VPS : identité, coffre, courriel (point 3)

**Fichiers** :

- `src/diapason_comptes/{__init__,app,base,secrets_serveur,validation,jetons,limites,courriel,journal,routes_identite,routes_coffre}.py` ;
- `deploy/vps/comptes/requirements.{in,txt}`, avec `cryptography` épinglé par empreinte (D19).

**Tests** `tests/diapason_comptes/`, avec un faux expéditeur :

- **Énumération** :
  - octet par octet sur les routes du §3.5 ;
  - **`login/params` stable dans le temps** : même sel avant et après inscription, et après un changement de mot de passe.
- **Limites et codes** :
  - délais par (adresse, préfixe) et plafond par adresse ;
  - échecs de `reset/confirm` comptés avec `/login` ;
  - codes à usage unique : de deux consommations concurrentes, une seule gagne.
- **Sessions** : hachage et révocation.
- **`vault/commit`** :
  - comparer-et-échanger sur les deux versions ;
  - **révocation d'office** des autres sessions ;
  - `emailCode` exige aussi un Bearer ;
  - `newKeyEpoch = courant + 1`.
- **Ce qu'une session seule ne peut pas faire** : obtenir une enveloppe, révoquer, supprimer le compte.
- **Réinitialisation** :
  - retardée, 72 h ou 7 jours ;
  - annulable ;
  - **`reset/complete` atomique** ;
  - le timer n'efface rien.
- **Journal et restauration** :
  - **`restaurer` rejoue le journal** : un jeton révoqué rend 401, l'ancien mot de passe est refusé, un compte supprimé ne revient pas ;
  - suppression en cascade et `secure_delete` : l'adresse n'apparaît plus dans les octets.
- **Base et secrets** :
  - base volée seule : ni adresse ni enveloppe exploitable ;
  - refus de démarrer sans `comptes.env` ;
  - aucun écho dans un 422.
- **Courriel** :
  - **un expéditeur bloqué 60 s ne retarde pas `/health`** ;
  - `mailUnavailable` quand le budget est épuisé ;
  - le budget des avis de sécurité n'est pas consommable sans authentification.
- **Forme du code** :
  - routes `def` seulement ;
  - indépendance vis-à-vis de `diapason`, et seul `cryptography.hazmat.primitives.ciphers.aead` est autorisé (vérifié en sous-processus) ;
  - `compte_api_surface.json`.

### Étape 5 — Service VPS : synchronisation et pièces (côté serveur du point 5)

**Fichiers** : `routes_synchro.py`, `routes_pieces.py`, `diapason-comptes-admin` (`restaurer`, `nouvelle-generation`).

**Tests** :

- comparer-et-échanger sur `rev` : un seul gagnant sur deux poussées ;
- conflit sur un objet absent : `current: null`, jamais d'erreur ;
- `seq` monotone ;
- pagination ;
- taille hors Padmé refusée ;
- `keyEpochChanged` et `incarnationChanged` ;
- version précédente gardée 30 jours ;
- `meta` présent sur chaque réponse ;
- **`DELETE /pieces` refusé si la pièce a été réclamée après `asOfSeq`** ;
- `/pieces/missing` ranime une orpheline ;
- quotas, 507, et garde « 20 Go libres » simulée ;
- `globalSeq` monotone ;
- aucun accès à un autre compte.

### Étape 6 — Pages légales, rédigées et testées, non déployées (point 3)

**Fichiers** :

- `confidentialite.html` et `conditions.html` ;
- polices ;
- `hebergeur.json` ;
- `scripts/gen_privacy_md.py` et `tests/test_privacy_md.py` ;
- `docs/confidentialite.md` ;
- `docs/telemetry.md:10` ;
- `exclude_docs`.

**Tests** du §5.

**Garde-fou** : rien n'est déployé ici. `deployer-site.sh` doit refuser de publier `confidentialite.html` tant que `INSCRIPTIONS_OUVERTES` n'est pas prévu, par un drapeau `accueil/.publier-legal` créé à l'étape 13.

### Étape 7 — Mise en service sur le VPS, inscriptions fermées (point 3)

Avec Carlito.

**Fichiers** :

- `deploy/vps/systemd/diapason-comptes.service` ;
- `diapason-sauvegarde.{service,timer}` ;
- `sauvegarder.py` ;
- `deployer-comptes.sh` ;
- **`defaire.sh`** ;
- `zz-diapason.conf` ;
- `deploy/vps/README.md`, dont la règle 3 est réécrite.

**Préalable** : `defaire.sh` et le déploiement ont été joués puis défaits sur une VM Ubuntu 24.04 jetable.

**Tests** :

- `tests/deploy/test_zz_diapason_api.py` :
  - pas d'`add_header` dans `/api` ;
  - `proxy_pass` sans URI ;
  - `client_max_body_size` explicite ;
  - zones `diapason_` ;
  - `gzip off` ;
  - `location = /api/v1/health` ;
  - `limit_req_log_level` ;
  - `log_format` sans `$remote_addr` ;
- `tests/deploy/test_sauvegarder.py` : refus quand l'espace libre est insuffisant, rétention par budget, sortie en code 1 si `integrity_check` échoue.

**Sur le VPS** :

1. `apt install python3.12-venv`.
2. Déploiement.
3. `nginx -t; rc=$?`, puis `reload`.

**Fin de l'étape** :

- `/api/v1/health` et `https://flashprime.online/` rendent 200 ;
- `signup/start` rend 503 `signupClosed` ;
- `ss -ltn` montre 8710 seulement sur 127.0.0.1 ;
- une sauvegarde manuelle réussit ;
- `df -h /` est relevé avant et après.

### Étape 8 — Compte local, sans synchronisation (point 4)

**Fichiers** :

- `compte/{etat,serrure,transport,client,service}.py` et `server/compte_routes.py` ;
- montage dans `app.py` ;
- **seau `/v1/account/*` dans `auth_middleware.py`** ;
- docstring de `local_mode.py` ;
- fixture autouse de portée session `_isoler_le_compte` dans `tests/conftest.py` (modèle `:336-375`), puisque ce Mac sert de runner CI.

**Tests** de bout en bout contre `diapason_comptes` en mémoire, par `httpx.Client(transport=httpx.MockTransport(...))` :

- parcours P1 à P8 ;
- **chaque rotation** : les autres sessions tombent en `sessionExpired`, et `enveloppe_locale` est effacée sur `sessionRevoked` ;
- `test_aucune_requete_ne_contient_kek_ni_amk` ;
- mot de passe absent des journaux (`caplog`, `traces.db`, `telemetry.db` de test) ;
- 423 et jamais 401 ;
- `kdfDowngrade` et `serverKeyStale` ;
- `local_only` : l'hôte constant passe, une surcharge et un clair sont refusés ;
- `unlock` : 5 essais, puis 30 s d'attente.

### Étape 9 — Interface d'activation (point 4)

**Fichiers** :

- `frontend/src/lib/compte.ts` et `compte.test.ts` : `etapeActivation`, règles du mot de passe, format et extrait de la clé, **`moyensDeSecours`**, `libelleSynchro`, messages par `code` ;
- `features/compte/{api.ts,EcranCompte.tsx,SectionCompte.tsx,BandeauCompte.tsx}` ;
- `App.tsx`, `SettingsPage.tsx`, `Layout.tsx` ;
- `messages.ts` en et fr (`i18n.test.ts:45-48`).

Aucun test de composant.

**Vérification à la main** dans la fenêtre Tauri et dans le mini-panneau.

### Étape 10 — Moteur de synchronisation, texte (point 5)

**Fichiers** :

- `compte/synchro.py` et `compte/collections/{base,conversations}.py` ;
- tâche du lifespan, avec le verrou d'exclusivité ;
- `peut_purger` branché ;
- **Tauri** : `prevent_exit` et `sync-now` avant `stop_all` (`lib.rs:5770`).

**Tests** `test_deux_appareils.py`, avec deux magasins, deux serrures et un VPS en mémoire :

- messages concurrents fusionnés ;
- conflit rejoué ;
- suppression propagée ;
- suppression contre modification concurrente ;
- appareil de retour après 60 jours ;
- horloge décalée de 10 min ;
- `seq` stable au second cycle ;
- `needsConsent` ;
- `audio` retiré sans boucle ;
- **`test_reinitialisation_repousse_tout`** : après `reset/complete`, le VPS contient N objets avant que `upToDate` apparaisse ;
- **connexion à un autre compte** : portée purgée ;
- **rotation en cours de synchronisation** : `keyEpochChanged`, puis rechargement ;
- **blob illisible avec copie locale** : réparé en un cycle, sans boucle ;
- **deux cycles simultanés** : une ré-exportation n'est jamais perdue ;
- **`resetPending` affiché** depuis `meta` ;
- **restauration logique** par `generation` : planchers conservés, aucune perte ;
- **retour arrière de toute la machine** simulé : `serverRolledBack`, rotation, puis tout repoussé.

**Tests** `test_synchro_hostile.py`, qui reprennent le §4.12, dont le changement de `generation` suivi du rejeu d'une version d'avant une suppression de 40 jours. Le canari doit rester absent.

### Étape 11 — Pièces (point 5)

**Fichiers** : `compte/pieces.py` et l'adaptateur.

**Tests** :

- réintégration à l'octet près ;
- un objet n'est jamais poussé avant sa pièce ;
- un objet dégradé n'efface pas l'image du serveur ;
- déduplication dans une époque, nouvel envoi après une rotation ;
- **course orpheline et réclamation** : la pièce survit ;
- réclamation quotidienne ;
- `pieceId` invérifiable sans `K_piece`.

### Étape 12 — Windows sur pc-bureau

**Fichier** : liste à cocher `docs/development/compte-windows.md`, dans `exclude_docs`.

**À vérifier** :

- DPAPI : aller-retour, et échec depuis un autre profil ;
- **refus de la mémorisation sur un compte sans mot de passe** ;
- durée d'Argon2id ;
- emplacement réel des données ;
- mot de passe accentué tapé au clavier Windows ;
- P1 à P10, fermeture de l'app comprise.

La matrice `test-windows` exécute `tests/compte/` et `tests/diapason_comptes/`.

### Étape 13 — Publication et ouverture

1. `bump-desktop-version.sh`, puis le tag `desktop-v*` (dmg et NSIS).
2. Déploiement des étapes 5 et 11 sur le VPS.
3. **Le commit unique du §5**, avec les pages légales, l'accueil et `PRIVACY.md`, et `accueil/.publier-legal`. Puis `deployer-site.sh`.
4. `INSCRIPTIONS_OUVERTES=1`.
5. CAPABILITY_MATRIX et roadmap mis à jour.
6. Une ligne de pièges dans CLAUDE.md : « jamais de 401 local ; aucun secret de compte en environnement ; l'instantané Hostinger n'est pas un retour arrière ». Puis régénération d'`AGENTS.md` dans le même commit.

### Ensuite, chacune seule

- ajout d'appareil par HPKE avec un code affiché ;
- mémoire, puis Succès, puis photos, puis documents ;
- long-poll ;
- changement d'adresse courriel ;
- rembourrage des tombales (D20).

### Hors périmètre, à traiter à part

- les trois routes `async` bloquantes existantes : `oauth_callback`, `connect_connector`, `voice_live_health` ;
- `cli/vault_cmd.py`, qui détruit le coffre en silence ;
- `device_identity()`, qui publie une clé publique fausse si `device.json` disparaît ;
- `LIFEOS_SYNC_TOKEN` codé en dur dans le client Dart (`app_config.dart:91-94`) ;
- `permissions.py:17-24`, qui cite `%LOCALAPPDATA%` à tort.

---

## 6 bis. Écarts de l'implémentation, étapes 4 à 6 (24/09/2026)

Les étapes 4 à 6 ont été écrites puis réfutées par des contre-épreuves
(sécurité, vérité des tests, exploitation, honnêteté). Ce qui suit est ce que le
code fait et que les §2, §3 et §5 ne disaient pas, ou disaient autrement. **Le
code et ses tests font foi sur ces points** ; le reste du document est inchangé.

**Identité et secrets du serveur (§2.2, §3.2, §3.3)**

- `kdfSalt = HMAC(GRAINE_SEL, "sel\0" ‖ E)`, sans passer par le poivre : le poivre
  tourne (§3.2), et la formule d'origine aurait changé le sel des adresses
  inconnues pendant que celui des comptes restait fixe. Le client ne voit qu'un
  sel opaque.
- `sel_kdf` est scellé sous `CLE_REPOS` (AAD `accountId|sel_kdf`), et
  `login/params` ne le lit plus : une base volée, croisée avec la route publique,
  livrait sinon la liste des adresses inscrites.
- Chaque valeur poivrée ou sur-chiffrée porte en tête un octet de version de
  secret. `secrets_version` vaut la plus vieille version encore nécessaire :
  `verif_recup` ne se réécrit qu'à `recovery/unwrap`, donc un vieux poivre ne se
  retire pas tant qu'un compte garde une clé de récupération inutilisée depuis
  la rotation.
- Le `signupToken` transporte l'adresse scellée sous `CLE_REPOS` : le schéma n'a
  aucune colonne pour la garder entre `verify` et `complete`.

**Journal et restauration (§3.3, §3.6, §3.10)**

- Types d'entrée ajoutés : `accountCreated`, `resetScheduled`, `resetCancelled`,
  `entryAborted`. Chaque entrée porte un `id` unique. Le rejeu se décide sur
  `(incarnation, vaultVersion)`, pas sur l'heure, et il est idempotent. Sans
  `resetScheduled`/`resetCancelled`, une restauration ressuscitait une
  réinitialisation annulée (constat de la contre-épreuve).
- Après une suppression de compte, le journal ne garde que la trace de
  suppression sous l'index HMAC — ni adresse chiffrée ni enveloppes.
- Après une restauration logique, `serverSeq` revient à celui de la copie mais
  `globalSeq` ne recule pas : **le client compare `generation` avant
  `serverSeq` et son curseur**, sinon une restauration se lit comme
  `serverRolledBack`.

**Sessions et coffre (§3.4, §3.7)**

- `vault/commit` révoque TOUTES les sessions, la courante comprise, et la
  réponse en porte une neuve.
- Un jeton de récupération (10 min) ne survit plus au retrait ou au
  remplacement de la clé, ni à `reset/complete` : il permettait de reprendre le
  compte pendant dix minutes (constat de la contre-épreuve).
- `401 accountDeleted` n'est jamais émis : un jeton inconnu vaut
  `sessionRevoked`, qui déclenche le même effacement côté appareil. Les sessions
  expirées ne sont purgées qu'après 30 jours de grâce, pour qu'un appareil revenu
  le lendemain lise `sessionExpired` et non `sessionRevoked`.
- 50 sessions au plus par compte.

**Courriels et limites (§3.5, D12)**

- « Compte existant » compte comme un code (plafonds 1/min et 3/h). Les avis de
  sécurité ont un plafond de 10 par jour et par adresse, sur un compteur séparé ;
  « nouvelle connexion » ne peut prendre que la moitié du budget réservé.
  **Risque résiduel** : plusieurs comptes qui bouclent sur `vault/commit`
  peuvent encore épuiser l'autre moitié.
- « Connexions bloquées » ne part plus vers une adresse sans compte en affirmant
  « votre compte Diapason ».
- La garde 507 s'applique à `signup/complete` et `PUT /sessions/current`, pas à
  `vault/commit`, `reset/complete` ni `account/delete` : refuser la révocation
  d'un appareil perdu faute de place serait pire.
- Variables d'environnement sans valeur par défaut inventée :
  `COMPTES_BUDGET_CODES_JOUR`, `COMPTES_BUDGET_SECURITE_JOUR` (D12),
  `COURRIEL_REPONSE` (D17), `COMPTES_ORIGINE_PUBLIQUE` (D3). Le service refuse de
  démarrer sans elles. `INSCRIPTIONS_OUVERTES` vaut 0 par défaut.

**Synchronisation et pièces (§3.4, §4)**

- Codes : `deferred` (à renvoyer), `serverBusy` (503, `retryAfterS`),
  `serverBehind` (409, remettre le curseur à zéro), `invalidEnvelope`,
  `objectTooLarge`, `507 quotaExceeded`. Résultats par objet de la forme
  `{status: …}`. `meta` accompagne toute réponse authentifiée de `/sync/*`,
  refus compris ; seuls le 401 et le 503 s'en passent. Le client reprend à
  `until`, pas au seq du dernier élément, et tire jusqu'à `until` avant tout
  `DELETE /pieces`.
- Le quota ne refuse que ce qui fait grossir la version courante : une tombale
  passe au-delà du quota (constat : elle était refusée, et une suppression
  devenait impossible au quota). Le dépassement est borné à deux fois la plus
  grande version courante de chaque objet.
- `PUT` d'une pièce existante rend 200 ; celui d'une orpheline purgée dans la
  même transaction rend 201 (il rendait 200 « déjà là » sur une pièce effacée).
- La base restaurée par `diapason-comptes-admin` est créée en 0600 (elle
  naissait en 0644 : `UMask=0077` ne vaut que pour l'unité systemd).

**Pages légales (§5, §3.9, §3.12)**

- D11 vaut pour TOUT `zz-diapason.conf`, le bloc 443 du site statique compris :
  il enregistre aujourd'hui l'IP des visiteurs, et la page ne peut pas dire le
  contraire tant que l'étape 7 ne l'a pas changé.
- La phrase du §3.12 « `local_only` bloque toute sortie, sauf l'envoi de données
  déjà chiffrées » est fausse : les mises à jour, le premier téléchargement du
  modèle, la recherche YouTube, l'adresse, `authKey` et les codes du compte
  sortent aussi. Les pages ne la portent pas.
- Les pages refusent de se générer tant que manquent : l'hébergeur et son lieu
  (D3), les sauvegardes, la copie hors du VPS (D18), l'adresse de contact (D17),
  la conservation et le suivi chez Resend (D12). Elles refusent de se publier
  tant que le site charge une police ou un script distant (Google Fonts,
  jsDelivr, Mermaid).

**Décidé par la session principale**

- **Constat 19 — l'incarnation entre dans l'AAD des types 03, 05 et 06.** Après
  `reset/complete`, le coffre repart à `vaultVersion = 1`, et l'état de
  l'appareil, lié à `(compte, incarnation)`, vide ses planchers : une enveloppe
  de l'incarnation précédente, rejouée par le VPS à ce moment-là, n'était
  distinguée de la nouvelle par rien. Les objets portaient déjà `i` ; le coffre
  aussi, désormais. Changer le format est gratuit tant qu'aucun compte n'existe,
  et ne le sera plus ensuite. **À faire avant l'étape 8**, avec les vecteurs
  régénérés dans le même commit — pas encore fait au moment où ces lignes sont
  écrites.

**Reste ouvert**

- `compte_api_surface.json` ne fige que méthodes et chemins, pas les champs des
  réponses : un champ en snake_case glisserait sans que le contrat le voie.
- `deploy/vps/comptes/requirements.txt` n'est audité par rien (`uv audit` ne lit
  que `uv.lock`).
- Aucun outil n'exporte ni ne supprime un compte sur demande de son titulaire :
  les droits d'accès et d'effacement se traitent à la main tant qu'il n'existe
  pas.

## 7. Décisions qui appartiennent à Carlito

Le champ `decisionsPourCarlito` porte la liste complète, avec une recommandation pour chacune. Voici celles qui bloquent :

| Bloque | Décisions |
|---|---|
| **L'étape 1** | D2 (paramètres Argon2), D5 (règles du mot de passe), D20 (rembourrage des tombales, car il touche le format), D21 (rotation à la déconnexion d'un appareil) |
| **L'étape 4** | D19 (`cryptography` sur le VPS), D8 (délais) |
| **L'étape 7** | D3 (hébergement), D10 (quotas), D11 (journaux), D12 (Resend), D17 (boîte de réponse), D18 (copies hors du VPS), D23 (instantané) |
| **L'étape 9** | D4, D6, D7, D13, D14 |

---

## Annexe A — Sort de chaque constat

| Constat | Sévérité | Traitement |
|---|---|---|
| Aucune rotation | bloquant | §2.2, §2.8, `vault/commit`, `K_piece_e`, textes P5 et P6 |
| Réinitialisation ou autre compte sans remise à zéro | bloquant | §4.2 (portée), §4.5, étape 0 du cycle, test dédié |
| Sauvegardes qui remplissent le disque | bloquant | §3.9 : budget, espace libre, garde abaissée, priorité idle |
| L'instantané Hostinger comme retour arrière | bloquant | §3.9 : `defaire.sh`, VM jetable, D23, README réécrit |
| La mémorisation contourne Argon2, et le trousseau est dans Time Machine | sérieux | §2.10 et §2.11 : texte honnête, case décochée, refus sur un Windows sans mot de passe, exclusion de `compte/` |
| `generation` non authentifiée | sérieux (×2) | §4.4 : planchers jamais vidés |
| Une restauration réactive coffre et sessions | sérieux (×2) | AAD `w`, planchers, journal d'événements, sessions vidées, §3.10 |
| La suppression se lit dans la taille | sérieux | promesse retirée, §2.9 et §5 ; D20 |
| Une session seule détruit | sérieux (×2) | §3.7 ; autoréparation ; version précédente pendant 30 jours ; jeton dans le protecteur ; révocation seulement par `vault/commit` |
| Purge bornée par l'export | sérieux | §4.6 : bornée par la confirmation, plus un plancher de suppression |
| 72 h non annulables en pratique | sérieux | §3.6 : `meta.pendingResetAt`, `resetPending`, notification, 7 jours si une session est active |
| Course sur les pièces orphelines | sérieux | `reclame_seq`, `asOfSeq`, réclamation quotidienne |
| Blob illisible ou pièce en 404 bloquants | sérieux | §4.3 : `rev_max` noté, autoréparation, 404 dégradé, le curseur avance toujours |
| `BackgroundTasks` et pool partagé | sérieux | §3.1 : fil dédié et file bornée |
| Changement de mot de passe sans effet ailleurs | sérieux | révocation d'office, effacement sur `sessionRevoked`, `meta` |
| Serveur perdu : « mot de passe incorrect » | sérieux | `/health.generation`, `serverLost`, copie hors du VPS |
| A2 faux (`comptes.env` sur le même disque) | sérieux | A2 et A2′ réécrits, §3.2 |
| Sauvegardes Hostinger tues | sérieux | P8, §5, `hebergeur.json` bloquant |
| « Appareil connecté » inutile s'il n'est pas mémorisé | sérieux | encadré réécrit, `moyensDeSecours` |
| Courriels : texte et compte Resend partagé | sérieux | textes, `mailUnavailable`, compte distinct (D12), 1 « compte existant » par jour |
| Préavis de 30 jours et origine en dur | sérieux | `/conditions` réécrit, D3, origine versionnée |
| Mineurs | mineur | tous intégrés : sel déterministe et limité, plancher de trousseau, D19 bloquante, clés anglaises, `reset/complete` atomique, `/health` hors zone de compte et 429 sans corps, verrou de cycle et suppression conditionnelle, seau `/v1/account`, D0 retirée, `PRIVACY.md:60-64`, journal d'erreurs nginx et port 80, commit légal unique, `python3.12-venv`, poussée à la fermeture, budgets de courriel, délais par préfixe |
