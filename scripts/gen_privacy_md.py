#!/usr/bin/env python
"""Remplit les pages légales et engendre PRIVACY.md à partir de /confidentialite.

24/09/2026, étape 6 de `docs/development/compte-chiffre.md` (§5). Trois
défauts que ce script existe pour empêcher :

1. **Une page légale qui promet un fait que personne n'a relevé.** Le lieu
   des sauvegardes de l'hébergeur, leur durée, l'adresse de contact : rien
   de tout cela ne se déduit du code, et la version précédente de la
   conception comptait sur un instantané Hostinger qu'elle n'avait jamais
   vu. Ces faits vivent dans `deploy/vps/comptes/hebergeur.json`, et tant
   qu'un seul y vaut `null`, ce script refuse d'écrire quoi que ce soit.
   Dans les pages commitées, chaque trou porte « [à fournir : …] » — jamais
   une valeur plausible.

2. **Deux copies d'une politique qui divergent.** `PRIVACY.md` (lu sur
   GitHub) et `/confidentialite` (lu sur le site) diraient deux choses le
   jour où l'on n'en corrige qu'une. La page est la source ; `PRIVACY.md`
   en découle, et `tests/test_privacy_md.py` refuse qu'ils s'écartent —
   même modèle que `gen_agents_md.py`.

3. **Une page légale publiée à côté d'un accueil qui dit le contraire.**
   `deployer-site.sh` publie tout `accueil/` à chaque mise en ligne de la
   documentation. Une page qui décrit un serveur de comptes, en ligne à
   côté d'un accueil qui jure « il n'y a pas de serveur », ment d'un côté
   ou de l'autre. `PRIVACY.md` n'est donc réécrit, et les pages ne partent,
   que lorsque le drapeau `deploy/vps/accueil/.publier-legal` existe — il
   est créé dans le commit unique de l'étape 13.

Usage :
    .venv/bin/python scripts/gen_privacy_md.py             # remplit les pages
    .venv/bin/python scripts/gen_privacy_md.py --verifier  # ce qui bloque

Sans --verifier, PRIVACY.md n'est écrit que si le drapeau existe.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Ce que chaque champ de hebergeur.json veut dire, et comment la page le lit.
# La description sert deux fois : dans le message de refus, et dans le
# marqueur « [à fournir : …] » que la page porte tant que le champ est vide.
# Un champ absent d'ici est une faute de frappe, et il est refusé.
CHAMPS: dict[str, str] = {
    "hebergeur.nom": "nom de l'hébergeur (D3)",
    "hebergeur.lieuServeur": "ville et pays du serveur, lus après « à » (D3)",
    "hebergeur.tiersAdministrateur": (
        "phrase complète : qui d'autre administre la machine "
        "et contrôle le domaine (D3)"
    ),
    "sauvegardes.frequence": "fréquence des sauvegardes de l'hébergeur",
    "sauvegardes.conservation": (
        "durée de conservation des sauvegardes de l'hébergeur, lue après « conservées »"
    ),
    "sauvegardes.lieu": "lieu des sauvegardes de l'hébergeur, lu après « à »",
    "instantane.description": (
        "phrase complète : l'instantané de l'hébergeur existe-t-il, "
        "combien de temps, pour qui"
    ),
    # 24/09/2026 : la copie quotidienne de la base et du journal vers une
    # autre machine (D18, §3.9) n'avait ni créneau ni phrase. La page
    # promettait « 14 jours au plus » pendant qu'une copie de lieu, de
    # détenteur et de durée inconnus existerait ailleurs.
    "copieHorsVps.description": (
        "phrase complète : où va la copie quotidienne de la base et du journal "
        "hors du serveur, qui la détient, combien de temps elle y reste, "
        "sauvegardes de cette machine comprises (D18)"
    ),
    # 24/09/2026 : « le suivi des ouvertures est désactivé » était écrit sans
    # que rien ne le vérifie — c'est un réglage du domaine dans le tableau de
    # bord Resend, pas un champ de l'appel — et la durée pendant laquelle
    # Resend garde l'adresse et les codes n'était dite nulle part.
    "resend.conservation": (
        "combien de temps Resend garde l'adresse et le contenu des courriels, "
        "codes compris, lu après « les garde »"
    ),
    "resend.suiviVerifie": (
        "phrase complète : le suivi des ouvertures et des clics est-il désactivé "
        "sur le domaine d'envoi, qui l'a vérifié dans le tableau de bord Resend, "
        "et quand (D12)"
    ),
    "contact.adresse": "adresse courriel de contact, lue par quelqu'un (D17)",
    "contact.responsable": (
        "nom ou titre de la personne responsable des renseignements personnels (Loi 25)"
    ),
    "conditions.ageMinimum": "âge minimum pour créer un compte",
    "conditions.droitApplicable": "droit applicable, lu après « régies par »",
    "publication.origineSite": "origine publique du site, sans barre finale (D3)",
    "publication.enVigueurLe": "date d'entrée en vigueur, lue après « le »",
    "publication.validationJuridique": "relecture par un juriste : qui, et quand",
    "releve.le": "date du relevé dans le panneau de l'hébergeur",
    "releve.par": "qui a fait le relevé",
}

# Les valeurs que le service de comptes applique, telles que la page les
# promet. Elles sont écrites ici en toutes lettres (« 72 heures », « 256 Mio »),
# et `tests/test_privacy_md.py` confronte chacune de celles qui existent déjà
# dans `src/diapason_comptes/` à sa constante : une recopie que rien ne
# compare avait laissé la page promettre des durées que le service
# n'appliquait pas (24/09/2026). Les quotas d'objets et de pièces attendent
# l'étape 5, les sauvegardes et les journaux l'étape 7.
VALEURS_DU_SERVICE: dict[str, str] = {
    "service.quotaCompte": "256 Mio",  # D10
    "service.objetMax": "4 Mio",  # §3.5
    "service.pieceMax": "10 Mio",  # §3.5
    "service.objetsMax": "50 000",  # §3.5
    "service.piecesMax": "5 000",  # §3.5
    "service.gardeBase": "2 Go",  # D10
    "service.delaiReinit": "72 heures",  # D8
    "service.delaiReinitActif": "7 jours",  # D8
    "service.fenetreActivite": "30 derniers jours",  # D8
    "service.sessionInactivite": "90 jours",  # §3.7, DUREE_SESSION_MS
    "service.graceSession": "30 jours",  # GRACE_PURGE_SESSION_MS
    "service.versionPrecedente": "30 jours",  # §3.3
    "service.piecesOrphelines": "30 jours",  # §3.4
    "service.codeValidite": "15 minutes",  # §3.5
    "service.sauvegardes": "14 jours",  # §3.9 : 14 copies quotidiennes au plus
    "service.journauxNginx": "environ 15 jours",  # §5 : logrotate daily, rotate 14
    "service.journald": "7 jours",  # §5 : MaxRetentionSec=7day
    "service.versionConditions": "1",  # termsVersion, entier (§5)
}

# Des mots qui trahissent un champ « rempli » pour faire taire le refus.
# 24/09/2026 : « à relever » — le mot même du §5 — et « N/A », « null »,
# « None », « ? » passaient, et auraient été publiés comme lieu des
# sauvegardes. Cherchés comme mots entiers : « none » ne doit pas refuser
# un nom qui le contiendrait.
_BOUCHE_TROUS = re.compile(
    r"(?<!\w)(?:à fournir|à relever|à confirmer|à compléter|à préciser|todo|tbd"
    r"|xxx|inconnue?|n/a|n\.a\.|null|none|nan|nil|undefined|lorem)(?!\w)",
    re.I,
)
# Une valeur de moins de trois lettres (« ? », « - », « 42 ») n'est pas un
# fait relevé ; l'âge minimum, entier, est traité à part.
_LETTRES_MIN = 3

# Les phrases de l'accueil que le compte rend fausses (§5 : index.html:7 et
# :30-33). Elles ne peuvent pas rester en ligne à côté de /confidentialite.
# 24/09/2026 : « Rien n'en sort. », le titre même de l'accueil, n'y était pas.
# Cherchées dans le texte normalisé : un retour à la ligne ou un &nbsp; entre
# « pas de » et « serveur » ne doit pas les déjouer.
FAUSSES_PROMESSES_ACCUEIL = ("pas de serveur", "envoyé à un serveur", "rien n'en sort")

# §5 « Liens » : le pied de l'accueil mène aux deux pages.
LIENS_ACCUEIL = ('href="/confidentialite"', 'href="/conditions"')

_POLICES_DISTANTES = ("fonts.googleapis", "fonts.gstatic")

# Les variables nginx qui écrivent une adresse IP ou une chaîne de requête.
# D11 : aucune IP dans les journaux. 24/09/2026 : la page promettait des
# journaux nginx « sans adresse IP » pendant que zz-diapason.conf écrivait
# le format `combined` — IP complète, chaîne de requête, Referer — pour
# chaque lecteur de la politique elle-même.
_VARIABLES_BAVARDES = re.compile(
    r"\$\{?(?:remote_addr|binary_remote_addr|realip_remote_addr|http_x_forwarded_for"
    r"|proxy_add_x_forwarded_for|http_x_real_ip|http_forwarded|args|arg_\w+"
    r"|query_string|request_uri|request|http_referer)(?![\w])\}?"
)
# Un journal d'erreurs au niveau par défaut écrit « client: <IP> » sur
# chaque 404 ; « crit » ne garde que les erreurs graves (§3.9).
_NIVEAUX_ERREUR_SOBRES = frozenset({"crit", "alert", "emerg"})

_CRENEAU = re.compile(
    r'(<span data-valeur="(?P<cle>[^"]+)">)(?P<contenu>.*?)(</span>)', re.S
)
MARQUEUR = "[à fournir"

PAGES = ("confidentialite.html", "conditions.html")

ENTETE_PRIVACY = (
    "<!-- Copie engendrée de deploy/vps/accueil/confidentialite.html par "
    "scripts/gen_privacy_md.py.\n"
    "     Ne pas corriger ici : corriger la page, puis relancer le script. -->"
)


def chemins(racine: Path = RACINE) -> dict[str, Path]:
    accueil = racine / "deploy" / "vps" / "accueil"
    return {
        "accueil": accueil,
        "drapeau": accueil / ".publier-legal",
        "index": accueil / "index.html",
        "hebergeur": racine / "deploy" / "vps" / "comptes" / "hebergeur.json",
        "privacy": racine / "PRIVACY.md",
        "mkdocs": racine / "mkdocs.yml",
        "mkdocs_api": racine / "mkdocs.api.yml",
        "nginx": racine / "deploy" / "vps" / "nginx" / "zz-diapason.conf",
        **{page: accueil / page for page in PAGES},
    }


def marqueur(cle: str) -> str:
    return f"[à fournir : {CHAMPS[cle]}]"


def _aplatir(donnees: dict, prefixe: str = "") -> dict[str, object]:
    plat: dict[str, object] = {}
    for cle, valeur in donnees.items():
        if cle.startswith("_"):
            continue
        chemin = f"{prefixe}{cle}"
        if isinstance(valeur, dict):
            plat.update(_aplatir(valeur, f"{chemin}."))
        else:
            plat[chemin] = valeur
    return plat


def _defaut_de_valeur(cle: str, valeur: object) -> str | None:
    """Pourquoi cette valeur ne peut pas être publiée, ou None si elle le peut."""
    if valeur is None:
        return "non relevé"
    if (
        cle == "conditions.ageMinimum"
        and isinstance(valeur, int)
        and not isinstance(valeur, bool)
    ):
        return None if 0 < valeur < 120 else "âge hors de toute plage raisonnable"
    if not isinstance(valeur, str) or not valeur.strip():
        return "doit être un texte non vide"
    if _BOUCHE_TROUS.search(valeur):
        return f"bouche-trou, pas une valeur : {valeur!r}"
    if sum(c.isalpha() for c in valeur) < _LETTRES_MIN:
        return f"moins de {_LETTRES_MIN} lettres, pas un fait relevé : {valeur!r}"
    if cle == "contact.adresse" and not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", valeur
    ):
        return f"n'est pas une adresse courriel : {valeur!r}"
    if cle == "publication.origineSite" and not re.fullmatch(
        r"https://[^/\s]+", valeur
    ):
        return f"attend « https://hôte », sans chemin ni barre finale : {valeur!r}"
    return None


def lire_hebergeur(racine: Path = RACINE) -> tuple[dict[str, str], list[str]]:
    """Les valeurs publiables de hebergeur.json, et la liste de ce qui manque.

    Un champ inconnu, un champ attendu absent, un `null` ou un bouche-trou
    comptent tous comme manquants : aucun ne doit laisser sortir la page.
    """
    donnees = json.loads(chemins(racine)["hebergeur"].read_text(encoding="utf-8"))
    plat = _aplatir(donnees)
    valeurs: dict[str, str] = {}
    manquants: list[str] = []
    for cle in sorted(set(plat) - set(CHAMPS)):
        manquants.append(f"{cle} : champ inconnu (faute de frappe ?)")
    for cle, description in CHAMPS.items():
        if cle not in plat:
            manquants.append(f"{cle} : absent du fichier — {description}")
            continue
        defaut = _defaut_de_valeur(cle, plat[cle])
        if defaut:
            manquants.append(f"{cle} : {defaut} — {description}")
            continue
        valeur = plat[cle]
        valeurs[cle] = (
            f"{valeur} ans" if isinstance(valeur, int) else str(valeur).strip()
        )
    return valeurs, manquants


def valeurs_de_rendu(racine: Path = RACINE) -> tuple[dict[str, str], list[str]]:
    """Ce que chaque créneau des pages doit afficher, marqueurs compris."""
    connues, manquants = lire_hebergeur(racine)
    valeurs = {cle: connues.get(cle, marqueur(cle)) for cle in CHAMPS}
    valeurs.update(VALEURS_DU_SERVICE)
    return valeurs, manquants


def creneaux(page: str) -> list[str]:
    return [m.group("cle") for m in _CRENEAU.finditer(page)]


def rendre_page(page: str, valeurs: dict[str, str]) -> str:
    """La page avec chaque créneau `<span data-valeur="…">` rempli.

    Un créneau dont la clé n'existe ni dans CHAMPS ni dans
    VALEURS_DU_SERVICE lève : il ne serait jamais rempli.
    """

    def remplir(m: re.Match[str]) -> str:
        cle = m.group("cle")
        if cle not in valeurs:
            raise KeyError(f"créneau inconnu dans la page : {cle}")
        return f"{m.group(1)}{html.escape(valeurs[cle], quote=False)}{m.group(4)}"

    return _CRENEAU.sub(remplir, page)


class _VersMarkdown(HTMLParser):
    """Le sous-ensemble de HTML que les pages légales emploient, en Markdown.

    Titres, paragraphes, listes (imbriquées), gras, italique, code, liens.
    Tout le reste — style, en-tête, pied — est hors de l'`<article>` et
    n'est jamais lu.
    """

    _BLOCS = {"h1": "# ", "h2": "## ", "h3": "### ", "p": ""}

    def __init__(self, origine: str) -> None:
        super().__init__(convert_charrefs=True)
        self.origine = origine
        self.dans_article = 0
        self.ignorer = 0
        self.lignes: list[str] = []
        self.tampon: list[str] = []
        self.prefixe: str | None = None
        self.listes: list[str] = []
        self.liens: list[str | None] = []

    def _vider(self) -> None:
        texte = re.sub(r"\s+", " ", "".join(self.tampon)).strip()
        self.tampon = []
        if texte and self.prefixe is not None:
            self.lignes.append(self.prefixe + texte)
        self.prefixe = None

    def _blanc(self) -> None:
        if self.lignes and self.lignes[-1] != "":
            self.lignes.append("")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self.dans_article += 1
            return
        if not self.dans_article:
            return
        if tag in ("style", "script"):
            self.ignorer += 1
        elif tag in self._BLOCS:
            self._vider()
            self._blanc()
            self.prefixe = self._BLOCS[tag]
        elif tag in ("ul", "ol"):
            self._vider()
            if not self.listes:
                self._blanc()
            self.listes.append(tag)
        elif tag == "li":
            self._vider()
            self.prefixe = "  " * (len(self.listes) - 1) + "- "
        elif tag in ("strong", "b"):
            self.tampon.append("**")
        elif tag == "em":
            self.tampon.append("*")
        elif tag == "code":
            self.tampon.append("`")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("/"):
                href = self.origine + href
            self.liens.append(href if href and not href.startswith("#") else None)
            if self.liens[-1]:
                self.tampon.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            self._vider()
            self.dans_article -= 1
            return
        if not self.dans_article:
            return
        if tag in ("style", "script"):
            self.ignorer -= 1
        elif tag in self._BLOCS or tag == "li":
            self._vider()
            if tag != "li":
                self._blanc()
        elif tag in ("ul", "ol"):
            self._vider()
            self.listes.pop()
            if not self.listes:
                self._blanc()
        elif tag in ("strong", "b"):
            self.tampon.append("**")
        elif tag == "em":
            self.tampon.append("*")
        elif tag == "code":
            self.tampon.append("`")
        elif tag == "a" and self.liens:
            href = self.liens.pop()
            if href:
                self.tampon.append(f"]({href})")

    def handle_data(self, data: str) -> None:
        if self.dans_article and not self.ignorer:
            if self.prefixe is None and data.strip():
                # Du texte hors de tout bloc serait perdu en silence.
                raise ValueError(
                    f"texte hors bloc dans la page : {data.strip()[:60]!r}"
                )
            self.tampon.append(data)


def rendre_privacy_md(page: str, origine: str) -> str:
    """PRIVACY.md tel qu'il doit être, tiré de /confidentialite déjà remplie."""
    convertisseur = _VersMarkdown(origine)
    convertisseur.feed(page)
    convertisseur.close()
    corps = "\n".join(convertisseur.lignes).strip()
    canonique = f"Version canonique : {origine}/confidentialite"
    return f"{ENTETE_PRIVACY}\n\n{corps}\n\n{canonique}\n"


def _exclude_docs(racine: Path) -> list[str]:
    texte = chemins(racine)["mkdocs"].read_text(encoding="utf-8")
    bloc = re.search(r"^exclude_docs: \|\n((?:  .*\n)+)", texte, re.M)
    return [ligne.strip() for ligne in bloc.group(1).splitlines()] if bloc else []


def _texte_normalise(page: str, balises: bool = False) -> str:
    """La page en minuscules, entités décodées, espaces repliées, apostrophes
    typographiques ramenées à « ' ». Sans `balises`, le texte lu par un
    visiteur (balises ôtées) ; avec, la source entière — une promesse peut
    vivre dans un attribut, comme la `<meta name="description">`."""
    texte = page if balises else re.sub(r"<[^>]+>", " ", page)
    texte = html.unescape(texte)
    texte = texte.replace("\u00a0", " ").replace("\u202f", " ").replace("’", "'")
    return re.sub(r"\s+", " ", texte).strip().lower()


def _instructions_nginx(texte: str) -> list[tuple[list[str], list | None]]:
    """La configuration nginx en arbre : (mots, enfants ou None).

    Juste assez pour lire `server`, `location`, `access_log`, `error_log` et
    `log_format` — les chaînes entre guillemets restent un seul mot, un `#`
    hors guillemets ouvre un commentaire.
    """
    jetons: list[str] = []
    i = 0
    while i < len(texte):
        c = texte[i]
        if c == "#":
            fin = texte.find("\n", i)
            i = len(texte) if fin < 0 else fin
        elif c in "'\"":
            fin = texte.find(c, i + 1)
            if fin < 0:
                raise ValueError("guillemet non fermé dans la configuration nginx")
            jetons.append(texte[i + 1 : fin])
            i = fin + 1
        elif c in ";{}":
            jetons.append(c)
            i += 1
        elif c.isspace():
            i += 1
        else:
            m = re.match(r"[^\s;{}'\"#]+", texte[i:])
            assert m
            jetons.append(m.group(0))
            i += len(m.group(0))

    def bloc(pos: int) -> tuple[list, int]:
        instructions: list = []
        mots: list[str] = []
        while pos < len(jetons):
            j = jetons[pos]
            pos += 1
            if j == ";":
                instructions.append((mots, None))
                mots = []
            elif j == "{":
                enfants, pos = bloc(pos)
                instructions.append((mots, enfants))
                mots = []
            elif j == "}":
                return instructions, pos
            else:
                mots.append(j)
        return instructions, pos

    return bloc(0)[0]


def _parcourir(instructions: list) -> list[list[str]]:
    """Toutes les directives simples, à toute profondeur."""
    toutes: list[list[str]] = []
    for mots, enfants in instructions:
        if enfants is None:
            toutes.append(mots)
        else:
            toutes.extend(_parcourir(enfants))
    return toutes


def problemes_nginx(racine: Path = RACINE) -> list[str]:
    """Ce qui, dans zz-diapason.conf, rendrait fausse la phrase « journaux
    nginx sans adresse IP ni chaîne de requête » (D11).

    Chaque bloc `server` doit porter son propre `access_log` (sinon il hérite
    du format `combined` de nginx.conf, IP comprise) et son propre
    `error_log` au niveau `crit` au plus bavard. Chaque `access_log`, à toute
    profondeur, emploie un `log_format` défini dans ce fichier et sans
    variable d'adresse ou de requête.
    """
    chemin = chemins(racine)["nginx"]
    if not chemin.exists():
        return [f"{chemin.name} introuvable : impossible de vérifier ses journaux"]
    arbre = _instructions_nginx(chemin.read_text(encoding="utf-8"))
    formats = {
        mots[1]: " ".join(mots[2:])
        for mots in _parcourir(arbre)
        if mots and mots[0] == "log_format" and len(mots) >= 3
    }
    problemes: list[str] = []
    serveurs = [enfants for mots, enfants in arbre if mots == ["server"] and enfants]
    if not serveurs:
        problemes.append(f"{chemin.name} : aucun bloc server trouvé")
    for n, serveur in enumerate(serveurs, 1):
        directes = {mots[0] for mots, enfants in serveur if enfants is None and mots}
        for directive in ("access_log", "error_log"):
            if directive not in directes:
                problemes.append(
                    f"{chemin.name}, server n°{n} : pas de {directive} propre — "
                    "il hérite de nginx.conf, adresse IP comprise"
                )
    for mots in _parcourir(arbre):
        if not mots:
            continue
        if mots[0] == "access_log":
            if mots[1:2] == ["off"]:
                continue
            if len(mots) < 3:
                problemes.append(
                    f"{chemin.name} : « access_log {mots[1]} » sans format — "
                    "c'est `combined`, adresse IP et chaîne de requête comprises"
                )
            elif mots[2] not in formats:
                problemes.append(
                    f"{chemin.name} : le format « {mots[2]} » n'est pas défini ici"
                )
            elif bavardes := _VARIABLES_BAVARDES.findall(formats[mots[2]]):
                problemes.append(
                    f"{chemin.name} : le format « {mots[2]} » écrit {bavardes}"
                )
        elif mots[0] == "error_log":
            if len(mots) < 3 or mots[2] not in _NIVEAUX_ERREUR_SOBRES:
                problemes.append(
                    f"{chemin.name} : « {' '.join(mots)} » — un journal d'erreurs "
                    "au-dessous de crit écrit « client: <IP> » à chaque refus"
                )
    return problemes


def _yaml_mkdocs(chemin: Path) -> dict:
    """mkdocs.yml porte des balises `!!python/name:` que safe_load refuse."""
    import yaml

    class Chargeur(yaml.SafeLoader):
        pass

    Chargeur.add_multi_constructor("tag:yaml.org,2002:python/", lambda *_: None)
    Chargeur.add_multi_constructor("!", lambda *_: None)
    return yaml.load(chemin.read_text(encoding="utf-8"), Loader=Chargeur) or {}


_DISTANT = re.compile(r"^(?:https?:)?//", re.I)
_CSS_DISTANT = re.compile(
    r"(?:@import\s+(?:url\()?|url\()\s*['\"]?(?:https?:)?//", re.I
)


def problemes_ressources_tierces(racine: Path = RACINE) -> list[str]:
    """Ce qui ferait charger une police, une feuille ou un script chez un
    tiers par une page de ce site — que la politique dit ne pas faire.

    24/09/2026 : seul index.html était regardé. Les guides, sous /docs/ du
    même domaine, chargeaient Google Fonts (thème Material : sans
    `font: false`, il tire Roboto ou la police nommée), jsDelivr (DocSearch)
    et un @import de Google Fonts dans ardechine.css. Chaque lecteur était
    annoncé à deux tiers que la politique ne nommait pas.
    """
    c = chemins(racine)
    problemes: list[str] = []
    for cle in ("mkdocs", "mkdocs_api"):
        chemin = c[cle]
        if not chemin.exists():
            continue
        conf = _yaml_mkdocs(chemin)
        theme = conf.get("theme") or {}
        if theme.get("name") == "material" and theme.get("font") is not False:
            problemes.append(
                f"{chemin.name} : theme.font n'est pas false — Material charge "
                "ses polices depuis Google Fonts"
            )
        for liste in ("extra_css", "extra_javascript"):
            for entree in conf.get(liste) or []:
                cible = (
                    entree
                    if isinstance(entree, str)
                    else (entree or {}).get("path", "")
                )
                if _DISTANT.match(str(cible)):
                    problemes.append(f"{chemin.name} : {liste} charge {cible}")
    feuilles = [
        *sorted((racine / "docs").rglob("*.css")),
        *sorted(c["accueil"].glob("*.css")),
    ]
    for feuille in feuilles:
        if _CSS_DISTANT.search(feuille.read_text(encoding="utf-8")):
            problemes.append(
                f"{feuille.relative_to(racine)} importe une ressource distante"
            )
    for nom, chemin in (("index.html", c["index"]), *((n, c[n]) for n in PAGES)):
        texte = chemin.read_text(encoding="utf-8")
        for police in _POLICES_DISTANTES:
            if police in texte:
                problemes.append(f"{nom} charge encore une police distante ({police})")
    return problemes


_BALISE_CHARGEANTE = re.compile(
    r"<(?P<balise>link|script|img|iframe|source|video|audio|embed)\b(?P<attrs>[^>]*)>",
    re.I,
)
_REL_NAVIGATION = frozenset({"canonical", "alternate", "prev", "next", "author", "me"})


def problemes_du_site_construit(dossier: Path) -> list[str]:
    """Le site MkDocs construit, lu comme un navigateur le chargerait.

    La configuration ne dit pas tout : le thème Material tire Mermaid
    d'unpkg.com dès qu'une page porte un diagramme, sans qu'aucune ligne de
    mkdocs.yml ne le nomme. Seul le HTML construit le montre.
    """
    problemes: set[str] = set()
    for page in sorted(dossier.rglob("*.html")):
        texte = page.read_text(encoding="utf-8", errors="replace")
        for m in _BALISE_CHARGEANTE.finditer(texte):
            attrs = m.group("attrs")
            cible = re.search(r'\b(?:href|src)\s*=\s*["\']([^"\']+)', attrs, re.I)
            if not cible or not _DISTANT.match(cible.group(1)):
                continue
            rel = re.search(r'\brel\s*=\s*["\']([^"\']+)', attrs, re.I)
            if rel and set(rel.group(1).lower().split()) <= _REL_NAVIGATION:
                continue
            hote = re.sub(r"^(?:https?:)?//", "", cible.group(1)).split("/", 1)[0]
            problemes.add(
                f"site construit : <{m.group('balise').lower()}> charge {hote}"
            )
        if 'class="mermaid"' in texte:
            problemes.add(
                "site construit : un diagramme Mermaid fait charger mermaid.js "
                "depuis unpkg.com par le thème Material"
            )
    for feuille in sorted(dossier.rglob("*.css")):
        if _CSS_DISTANT.search(feuille.read_text(encoding="utf-8", errors="replace")):
            problemes.add(
                f"site construit : {feuille.relative_to(dossier)} importe une "
                "ressource distante"
            )
    return sorted(problemes)


def problemes_de_publication(racine: Path = RACINE) -> list[str]:
    """Tout ce qui interdit de mettre les pages légales en ligne aujourd'hui.

    Liste vide = publiable. C'est la question que `deployer-site.sh` pose
    quand le drapeau `.publier-legal` existe.
    """
    c = chemins(racine)
    problemes = [f"hebergeur.json — {m}" for m in lire_hebergeur(racine)[1]]
    valeurs, _ = valeurs_de_rendu(racine)
    pages = {}
    for nom in PAGES:
        page = c[nom].read_text(encoding="utf-8")
        pages[nom] = page
        if MARQUEUR in page:
            problemes.append(f"{nom} porte encore « {MARQUEUR} … »")
        try:
            if rendre_page(page, valeurs) != page:
                problemes.append(
                    f"{nom} n'est pas à jour : relancer scripts/gen_privacy_md.py"
                )
        except KeyError as exc:
            problemes.append(f"{nom} : {exc}")
    problemes.extend(problemes_ressources_tierces(racine))
    problemes.extend(problemes_nginx(racine))
    accueil = c["index"].read_text(encoding="utf-8")
    lectures = (_texte_normalise(accueil), _texte_normalise(accueil, balises=True))
    for phrase in FAUSSES_PROMESSES_ACCUEIL:
        if any(phrase in lecture for lecture in lectures):
            problemes.append(
                f"index.html dit encore « {phrase} », que le compte rend faux"
            )
    for lien in LIENS_ACCUEIL:
        if lien not in accueil:
            problemes.append(f"index.html ne porte pas le lien {lien} (§5 « Liens »)")
    origine = valeurs.get("publication.origineSite", "")
    if not origine.startswith(MARQUEUR):
        attendu = rendre_privacy_md(pages["confidentialite.html"], origine)
        actuel = (
            c["privacy"].read_text(encoding="utf-8") if c["privacy"].exists() else ""
        )
        if actuel != attendu:
            problemes.append("PRIVACY.md n'est pas la copie de /confidentialite")
    if any("confidentialite.md" in motif for motif in _exclude_docs(racine)):
        problemes.append(
            "mkdocs.yml exclut encore docs/confidentialite.md (exclude_docs)"
        )
    return problemes


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--verifier",
        action="store_true",
        help="n'écrit rien ; sort en 1 si la publication doit être refusée",
    )
    parseur.add_argument(
        "--verifier-site",
        metavar="DOSSIER",
        type=Path,
        help="n'écrit rien ; sort en 1 si le site construit charge un tiers",
    )
    args = parseur.parse_args(argv)
    c = chemins()

    if args.verifier_site:
        problemes = problemes_du_site_construit(args.verifier_site)
        if problemes:
            print(
                "✗ Le site construit charge des ressources tierces :", file=sys.stderr
            )
            for p in problemes:
                print(f"    - {p}", file=sys.stderr)
            return 1
        print("✓ Le site construit ne charge rien chez un tiers.")
        return 0

    if args.verifier:
        problemes = problemes_de_publication()
        if problemes:
            print("✗ Pages légales NON publiables :", file=sys.stderr)
            for p in problemes:
                print(f"    - {p}", file=sys.stderr)
            return 1
        print("✓ Pages légales publiables.")
        return 0

    valeurs, manquants = valeurs_de_rendu()
    if manquants:
        print(
            "✗ Refus : deploy/vps/comptes/hebergeur.json n'est pas complet.\n"
            "  Aucune page n'est écrite tant qu'un fait n'a pas été relevé :",
            file=sys.stderr,
        )
        for m in manquants:
            print(f"    - {m}", file=sys.stderr)
        return 1

    for nom in PAGES:
        page = c[nom].read_text(encoding="utf-8")
        rendue = rendre_page(page, valeurs)
        if rendue != page:
            c[nom].write_text(rendue, encoding="utf-8")
            print(f"→ {nom} rempli")
    if c["drapeau"].exists():
        page = c["confidentialite.html"].read_text(encoding="utf-8")
        c["privacy"].write_text(
            rendre_privacy_md(page, valeurs["publication.origineSite"]),
            encoding="utf-8",
        )
        print("→ PRIVACY.md engendré depuis /confidentialite")
    else:
        print(
            "  PRIVACY.md laissé tel quel : pas de drapeau\n"
            "  deploy/vps/accueil/.publier-legal. Il décrit un produit sans serveur\n"
            "  de comptes ; le changer avant l'ouverture\n"
            "  publierait sur GitHub une politique qui ne vaut pas encore."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
