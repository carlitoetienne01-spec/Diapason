"""Lecture d'une page web : texte principal, titre et dates déclarées.

21 septembre 2026 : « Qui est le premier ministre du Canada ? » — web_search
rendait cinq extraits (brave, région ca-fr) dont AUCUN ne disait qui est le
titulaire : des bouts pris au hasard dans les pages Wikipédia « Premier
ministre du Canada », « Mark Carney », « Justin Trudeau », « Liste des
Premiers ministres ». Le 9b a répondu « Justin Trudeau [3] ». Le corps de
fr.wikipedia.org/wiki/Premier_ministre_du_Canada, lui, porte dans l'infobox
la ligne « Titulaire actuel | Mark Carney | depuis le 14 mars 2025 » et dans
le premier vrai paragraphe « Mark Carney, le premier ministre actuel, a
prêté serment le 14 mars 2025, après la démission de Justin Trudeau ».

Le mode « URL dans la requête » de web_search (``WebSearchTool._fetch_url``)
ne pouvait pas le lire : un ``<[^>]+>`` sur tout le HTML rend 6 000
caractères de menu et de bandeau cookies, jamais le corps. D'où cet outil :
la zone principale une fois le bruit retiré, les blocs en ordre de document,
les lignes de tableau jointes par « | » (``text_content()`` collait
« Titulaire actuelMark Carneydepuis le 14 mars 2025 »), et les dates prises
là où la page les déclare — jamais devinées (§5 du cahier : une date que la
page ne porte pas n'existe pas).

Revue du 21 septembre au soir, contre des pages réelles et des pages
piégées : le bruit était retiré sans regarder s'il ENGLOBAIT le contenu
(``body.has-sidebar`` de WordPress, le ``<form>`` unique d'ASP.NET) et la
page revenait vide, en succès ; ``<header>`` était du bruit même dans un
``<article>``, et le patron HTML5 le plus courant perdait son titre et sa
date ; une bombe gzip matérialisait 67 Mo d'un seul morceau ; un serveur qui
goutte était lu 50 s dans un fil que l'exécuteur avait abandonné. Chaque
correction porte sa date dans le code.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
import unicodedata
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin

from diapason.core.registry import ToolRegistry
from diapason.core.types import ToolResult
from diapason.security.ssrf import check_ssrf
from diapason.tools._stubs import BaseTool, ToolSpec
from diapason.tools.web_search import domaine

logger = logging.getLogger(__name__)

# Une page plus lourde est coupée à la lecture, pas chargée entière : la page
# Wikipédia du premier ministre pèse 220 Ko compressés, un article de presse
# 300 Ko avec ses scripts. 2 Mo laissent de la marge sans qu'une page piégée
# ou un flux sans fin remplisse la mémoire du serveur. La borne porte sur les
# octets DÉCOMPRESSÉS (voir _lire_borne).
TAILLE_MAX_OCTETS = 2_000_000
# Budget TOTAL du téléchargement, redirections comprises, tenu par une
# horloge dans la boucle de lecture. 21/09 : ce délai ne bornait que chaque
# attente réseau (httpx l'applique par opération, pas au total), et un
# serveur qui goutte 2 Ko/s a été lu 50 s de suite — dans un fil que
# l'exécuteur avait cessé d'attendre à 20 s. Le fil ne meurt pas parce qu'on
# ne l'attend plus.
DELAI_S = 10.0
# Chaque attente réseau (connexion, un morceau) : 8 s, pour que le pire cas
# — l'échéance tombe pendant une attente — reste sous les 20 s de
# l'exécuteur (10 + 8 = 18). Wikipédia répond en moins d'une seconde, un
# site gouvernemental en deux ou trois.
DELAI_OPERATION_S = 8.0
# agentic_stream tronque tout résultat d'outil à 4 000 caractères
# (MAX_TOOL_RESULT_CHARS) : composer en dessous, pour choisir ce qui reste
# plutôt que de laisser la coupe tomber au milieu du passage utile.
LIMITE_CARACTERES = 3600
# Le début de la page porte l'infobox et le premier paragraphe — sur
# Wikipédia, c'est là que sont le titulaire et sa date (21/09). 1 200
# caractères couvrent les deux et laissent 2 000 aux passages ciblés.
TAILLE_DEBUT = 1200
# ±300 caractères autour d'un mot du focus : une phrase avant, une après —
# de quoi lire « a prêté serment le 14 mars 2025 » autour de « actuel »
# sans emporter le paragraphe entier.
FENETRE = 300
# Un titre plus long qu'une ligne est un bourrage : 300 caractères, c'est
# trois fois le plus long titre de Wikipédia. 21/09 : un <title> de 5 000
# caractères faisait sortir composer() à 5 049, au-delà de la limite qu'il
# promet — et agentic_stream aurait coupé à 4 000, au milieu.
TITRE_MAX = 300
# http → https → www → page : trois sauts pour une page honnête. Au-delà de
# cinq, on refuse. Chaque saut repasse par check_ssrf AVANT d'être joint :
# suivre les redirections dans httpx aurait déjà envoyé la requête à
# l'adresse interne au moment de la relire.
MAX_REDIRECTIONS = 5
# Un <article> qui porte moins que cela est un teaser ou une carte, pas le
# corps : trois phrases de résumé font 300 caractères. Même seuil pour un
# <form> : en dessous c'est un formulaire, au-dessus c'est une enveloppe.
ARTICLE_MIN_CARACTERES = 500
# Accept-Encoding est dit explicitement parce que la décompression se fait
# ICI, bornée (voir _lire_borne) : httpx annoncerait aussi br et zstd, qu'on
# ne saurait pas borner.
ENTETES_REQUETE = {
    "User-Agent": "Mozilla/5.0 (compatible; Diapason/1.0; +https://github.com/diapason)",
    "Accept-Encoding": "gzip, deflate",
}
TYPES_LISIBLES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
COUPE = "[… texte coupé]"


@dataclass(frozen=True)
class Page:
    """Ce qu'une page déclare : dates en AAAA-MM-JJ ou "", texte une ligne
    par bloc."""

    url: str
    titre: str
    publie: str
    modifie: str
    texte: str


class PageIllisible(ValueError):
    """Le HTML ne peut pas être lu en entier ; le message se rend tel quel."""


# ---------------------------------------------------------------------------
# Dates — un petit analyseur déterministe, jamais une devinette
# ---------------------------------------------------------------------------

_MOIS = {
    "janvier": 1,
    "janv": 1,
    "jan": 1,
    "january": 1,
    "fevrier": 2,
    "fevr": 2,
    "fev": 2,
    "feb": 2,
    "february": 2,
    "mars": 3,
    "mar": 3,
    "march": 3,
    "avril": 4,
    "avr": 4,
    "apr": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "jun": 6,
    "june": 6,
    "juillet": 7,
    "juil": 7,
    "jul": 7,
    "july": 7,
    "aout": 8,
    "aug": 8,
    "august": 8,
    "septembre": 9,
    "sept": 9,
    "sep": 9,
    "september": 9,
    "octobre": 10,
    "oct": 10,
    "october": 10,
    "novembre": 11,
    "nov": 11,
    "november": 11,
    "decembre": 12,
    "dec": 12,
    "december": 12,
}
_JOURS_SEMAINE = frozenset(
    "lundi mardi mercredi jeudi vendredi samedi dimanche"
    " lun mar mer jeu ven sam dim"
    " monday tuesday wednesday thursday friday saturday sunday"
    " mon tue wed thu fri sat sun le".split()
)
# ISO 8601 : la date, puis rien ou une heure. « 2026-09-02 » nu passe ;
# « 2026-09 » ne passe pas (pas de jour : on ne l'inventerait pas).
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:$|[T ]\d{2}:\d{2})")
# « 14 mars 2025 », « 1er juillet 1867 », « 14 March 2025 », « 14 Aug 2026 ».
_JOUR_MOIS_AN = re.compile(
    r"^(\d{1,2})(?:er|e|st|nd|rd|th)?\s+([a-z]+)\.?,?\s+(\d{4})(?!\d)"
)
# « March 14, 2025 », « Mar 14 2025 ».
_MOIS_JOUR_AN = re.compile(
    r"^([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)"
)
# RFC 2822 (en-tête Last-Modified). parsedate_to_datetime est plus laxiste
# que cela ; le garde-fou évite qu'il accepte une forme qu'on ne veut pas.
_RFC2822 = re.compile(
    r"^(?:[a-z]{3},\s*)?\d{1,2}\s+[a-z]{3}\s+\d{4}\s+\d{2}:\d{2}", re.I
)


def _aplatir(texte: str) -> str:
    """Minuscules sans accents, MÊME LONGUEUR que l'entrée : les indices
    trouvés dans la copie plate valent dans le texte d'origine."""
    sortie = []
    for c in texte:
        decompose = unicodedata.normalize("NFKD", c)
        base = decompose[0] if decompose else c
        bas = base.lower()
        sortie.append(bas if len(bas) == 1 else base)
    return "".join(sortie)


def _jour_valide(an: int, mois: int, jour: int) -> str:
    try:
        return date(an, mois, jour).isoformat()
    except ValueError:
        return ""


def date_iso(brute: str) -> str:
    """AAAA-MM-JJ, ou "" pour tout ce qui n'est pas une date sans ambiguïté.

    « 06/17/2016 - 20:07 » (pm.gc.ca, 21/09) est refusé : on ne sait pas si
    c'est juin ou le 17e mois. La date d'un instant horodaté est gardée telle
    que déclarée, sans passer au fuseau du poste : c'est ce que la page dit.
    """
    texte = " ".join(str(brute or "").split())
    if not texte:
        return ""
    m = _ISO.match(texte)
    if m:
        return _jour_valide(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    plat = _aplatir(texte)
    # « mar » est mardi ET March : on essaie d'abord la chaîne entière, et
    # seulement ensuite sans son premier mot s'il est un jour de semaine.
    candidats = [plat]
    premier, _, reste = plat.partition(" ")
    if reste and premier.rstrip(",.") in _JOURS_SEMAINE:
        candidats.append(reste)
    for candidat in candidats:
        m = _JOUR_MOIS_AN.match(candidat)
        if m and m.group(2) in _MOIS:
            return _jour_valide(int(m.group(3)), _MOIS[m.group(2)], int(m.group(1)))
        m = _MOIS_JOUR_AN.match(candidat)
        if m and m.group(1) in _MOIS:
            return _jour_valide(int(m.group(3)), _MOIS[m.group(1)], int(m.group(2)))
    if _RFC2822.match(texte):
        try:
            return parsedate_to_datetime(texte).date().isoformat()
        except (TypeError, ValueError):
            return ""
    return ""


# ---------------------------------------------------------------------------
# Analyse HTML (lxml, importé dans les fonctions)
# ---------------------------------------------------------------------------

_DECLARATION_XML = re.compile(r"^\s*<\?xml[^>]*\?>")
# Tout ce qui n'est pas le corps de la page. Les tables restent : l'infobox
# Wikipédia en est une et c'est elle qui porte « Titulaire actuel ».
# <header> et <form> n'y sont pas : ils ont leur propre règle dans _est_bruit.
_BALISES_BRUIT = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "nav",
        "footer",
        "aside",
        "iframe",
        "svg",
        "button",
        "input",
        "select",
        "textarea",
        "dialog",
    }
)
# Un <header> est une bannière de site — sauf sous l'un de ceux-ci, où c'est
# l'en-tête du CONTENU. 21/09 : <article><header><h1>…<time datetime></header>
# est le patron HTML5 canonique (WordPress : entry-header, entry-date
# published) ; le retirer perdait le titre ET la date, et le palier « puis
# <time> d'un article » ne se déclenchait jamais.
_PORTEURS_DE_CONTENU = frozenset({"article", "main"})
# Un <article> sous l'une de ces balises est une carte de barre latérale,
# pas le corps : il ne protège pas ses ancêtres.
_ENVELOPPES_BRUIT = frozenset({"aside", "nav", "footer", "header"})
# « banner » n'y est pas : il suit la règle de <header> dans _est_bruit.
_ROLES_BRUIT = frozenset(
    {
        "navigation",
        "contentinfo",
        "button",
        "menu",
        "menubar",
        "search",
        "dialog",
        "complementary",
    }
)
# Un MOT de la classe ou de l'id, borné par début, fin, tiret, souligné ou
# blanc : « toc » retire « vector-toc », pas « stock-price ». « bandeau »
# est propre à fr.wikipedia (revue du 21/09 : son premier <time>, « février
# 2025 », vivait dans un bandeau d'avertissement). « dropdown » et
# « portlet » : le sélecteur de 53 langues de Wikipédia vit dans
# <div class="vector-dropdown mw-portlet"> — DANS le <header> du <main>,
# que l'on garde désormais pour son <h1>.
_MOTS_BRUIT = re.compile(
    r"(?:^|[-_\s])(?:mw-editsection|references?|navbox|navigation|toc|hatnote"
    r"|bandeau|cookies?|consent|breadcrumbs?|sidebar|share|comments?"
    r"|dropdown|portlet|modal|popup)(?:$|[-_\s])",
    re.I,
)
# Un bloc se rend d'un tenant, sur sa ligne ; un bloc imbriqué dans un bloc
# déjà pris n'est pas repris. 21/09 : h5, h6, caption et summary manquaient,
# et leurs intitulés disparaissaient.
_BLOCS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "dt",
        "dd",
        "blockquote",
        "figcaption",
        "pre",
        "tr",
        "caption",
        "summary",
    }
)
_META_PUBLIE = (
    "article:published_time",
    "publication_date",
    "date",
    "dc.date",
    "dcterms.created",
)
_META_MODIFIE = (
    "article:modified_time",
    "og:updated_time",
    "last_modified_date",
    "dc.date.modified",
    "dcterms.modified",
)
_MARQUE_DATE = re.compile(r"published|date", re.I)


def _analyser(html: str) -> Any:
    """Racine <html> d'un document lxml ; un document vide donne un squelette
    plutôt qu'une exception.

    21/09 : au-delà de 256 niveaux d'imbrication, libxml2 s'arrêtait
    (ERR_RESOURCE_LIMIT) et TOUT ce qui suivait le sous-arbre profond était
    perdu — en silence, en succès. ``huge_tree`` porte la borne à 2 048
    niveaux (aucune page réelle n'en approche ; la mémoire reste tenue par
    TAILLE_MAX_OCTETS) et, au-delà, la page est REFUSÉE plutôt que rendue
    amputée : les parcours de ce module sont itératifs, pas récursifs, pour
    ne pas troquer la limite de libxml2 contre une RecursionError Python.
    """
    from lxml import etree
    from lxml import html as lxml_html

    texte = _DECLARATION_XML.sub("", html or "", count=1)
    if not texte.strip():
        return lxml_html.document_fromstring("<html><body></body></html>")
    parseur = lxml_html.HTMLParser(huge_tree=True)
    try:
        doc = lxml_html.document_fromstring(texte, parser=parseur)
    except (ValueError, etree.ParserError):
        return lxml_html.document_fromstring("<html><body></body></html>")
    # Le journal d'erreurs du parseur n'est pas fiable d'un fil à l'autre :
    # sous la suite complète (xdist + to_thread), une page plate héritait
    # d'un ERR_RESOURCE_LIMIT laissé par une autre analyse et était refusée
    # (21/09). L'arbre, lui, ne ment pas : libxml2 s'arrête à 2 048 niveaux,
    # et un arbre qui les atteint a été coupé.
    if _profondeur(doc) >= PROFONDEUR_MAX_LIBXML:
        raise PageIllisible(
            "Lecture impossible : HTML trop imbriqué, la page serait rendue amputée"
        )
    return doc


# Mesuré le 21/09 avec lxml 6.1.1 / libxml2 2.14 : 2 045 <div> imbriqués
# donnent un arbre de 2 047 niveaux entier ; 2 050 donnent 2 048 niveaux et
# tout ce qui suit est perdu.
PROFONDEUR_MAX_LIBXML = 2048


def _profondeur(doc: Any) -> int:
    maxi = 0
    pile = [(doc, 1)]
    while pile:
        el, niveau = pile.pop()
        if niveau > maxi:
            maxi = niveau
        pile.extend((enfant, niveau + 1) for enfant in el)
    return maxi


# Entre deux de ces balises, un blanc : text_content() collait « Premier
# point » et « Sous-point » d'un <li> imbriqué (21/09). Les balises en ligne
# (<b>, <a>, <sup>) restent collées : « 1<sup>er</sup> juillet » et
# « <b>Mark Carney</b>, » ne prennent pas d'espace parasite. Dans texte_de,
# une de ces balises sans bloc dessous (<div>Texte</div>) fait sa propre
# ligne.
_SEPARATEURS = frozenset(
    {
        "p",
        "div",
        "li",
        "ul",
        "ol",
        "tr",
        "td",
        "th",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "dt",
        "dd",
        "dl",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "caption",
        "section",
        "article",
        "main",
        "header",
        "footer",
        "aside",
        "nav",
        "figure",
        "figcaption",
        "details",
        "summary",
        "address",
        "fieldset",
        "form",
        "pre",
    }
)


# Dans une cellule, un <br> ou un <li> sépare des VALEURS : l'infobox réelle
# de fr.wikipedia (21/09) met « Titulaire actuel », « Mark Carney » et
# « depuis le 14 mars 2025 » dans une seule <td>, séparés par des <br/>.
_COUPURES_CELLULE = frozenset({"br", "li"})
_COUPURE = "\x1f"


def _borne(tag: str, coupures: bool) -> str:
    if coupures and tag in _COUPURES_CELLULE:
        return _COUPURE
    return " " if tag in _SEPARATEURS else ""


def _morceaux(el: Any, coupures: bool) -> str:
    """Le texte de l'élément et de sa descendance, sans sa queue — parcours
    en pile, pas en récursion (voir _analyser)."""
    morceaux = [el.text or ""]
    # Chaque cadre : (enfants restants, borne à fermer, queue à recoller).
    pile: list[tuple[Any, str, str]] = [(iter(el), "", "")]
    while pile:
        enfants, borne, queue = pile[-1]
        enfant = next(enfants, None)
        if enfant is None:
            pile.pop()
            morceaux.append(borne)
            morceaux.append(queue)
            continue
        if not isinstance(enfant.tag, str):  # commentaire, instruction
            morceaux.append(enfant.tail or "")
            continue
        b = _borne(enfant.tag, coupures)
        morceaux.append(b)
        morceaux.append(enfant.text or "")
        pile.append((iter(enfant), b, enfant.tail or ""))
    return "".join(morceaux)


def _texte_plat(el: Any) -> str:
    return " ".join(_morceaux(el, coupures=False).split())


def _texte_cellule(el: Any) -> str:
    brut = _morceaux(el, coupures=True)
    valeurs = (" ".join(v.split()) for v in brut.split(_COUPURE))
    return " | ".join(v for v in valeurs if v)


def _retirer(el: Any) -> None:
    """Retire un élément en gardant sa queue (le « . » après un <sup>)."""
    parent = el.getparent()
    if parent is None:
        return
    if el.tail:
        precedent = el.getprevious()
        if precedent is not None:
            precedent.tail = (precedent.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _sous(el: Any, balises: Iterable[str]) -> bool:
    """Vrai si un ancêtre porte l'une de ces balises."""
    parent = el.getparent()
    while parent is not None:
        if parent.tag in balises:
            return True
        parent = parent.getparent()
    return False


def _est_bruit(el: Any, proteges: set[Any]) -> bool:
    if el in proteges:
        return False
    tag = el.tag
    role = (el.get("role") or "").strip().lower()
    if tag == "header" or role == "banner":
        if not _sous(el, _PORTEURS_DE_CONTENU):
            return True
    elif tag == "form":
        # 21/09 : ASP.NET WebForms enveloppe TOUT le corps dans un seul
        # <form id="form1"> ; le retirer rendait la page vide. Un formulaire
        # qui porte plus de texte qu'un teaser est une enveloppe.
        if len(_texte_plat(el)) < ARTICLE_MIN_CARACTERES:
            return True
    elif tag in _BALISES_BRUIT or role in _ROLES_BRUIT:
        return True
    # Un en-tête ou une enveloppe gardés par leur balise passent quand même
    # par la classe et aria-hidden : <header class="cookie-banner"> reste
    # du bruit, même dans <main>.
    if (el.get("aria-hidden") or "").strip().lower() == "true":
        return True
    return bool(
        _MOTS_BRUIT.search(el.get("class") or "")
        or _MOTS_BRUIT.search(el.get("id") or "")
    )


def _proteges(racine: Any) -> set[Any]:
    """Le corps, les zones candidates et tout ce qui les ENGLOBE : jamais
    retirés, quelle que soit leur classe.

    21/09 : WordPress (Twenty Seventeen, ``twentyseventeen_body_classes``)
    pose « has-sidebar » sur <body>, un thème met <main> dans
    <div class="with-sidebar">, un autre ferme un menu mobile avec
    aria-hidden sur l'enveloppe de la page — trois pages rendues vides, en
    succès, parce que le bruit était retiré sans regarder s'il englobait le
    contenu. Un <article> sous <aside>/<nav>/<footer> ne protège rien : c'est
    une carte, pas le corps.
    """
    candidats: list[Any] = list(racine.iter("main"))
    candidats += racine.xpath("//*[@role='main']")
    candidats += racine.xpath("//*[@id='mw-content-text' or @id='content']")
    candidats += [
        a
        for a in racine.iter("article")
        if len(_texte_plat(a)) >= ARTICLE_MIN_CARACTERES
        and not _sous(a, _ENVELOPPES_BRUIT)
    ]
    corps = racine.find("body")
    if corps is not None:
        candidats.append(corps)
    proteges: set[Any] = set()
    for candidat in candidats:
        el = candidat
        while el is not None and el not in proteges:
            proteges.add(el)
            el = el.getparent()
    return proteges


def zone_principale(doc: Any) -> Any:
    """L'élément qui porte le corps de la page, débarrassé du bruit.

    Travaille sur une COPIE du document : retirer les <script> du document
    lui-même aurait emporté le JSON-LD, et dates_de_page appelée ensuite
    n'aurait plus rien trouvé — en silence. La copie coûte quelques dizaines
    de millisecondes sur 400 Ko ; l'ordre d'appel n'a plus d'importance.
    """
    racine = copy.deepcopy(doc)
    proteges = _proteges(racine)
    for el in list(racine.iter()):
        if isinstance(el.tag, str) and _est_bruit(el, proteges):
            _retirer(el)
    articles = [
        a
        for a in racine.iter("article")
        if len(_texte_plat(a)) >= ARTICLE_MIN_CARACTERES
    ]
    # Un seul article étoffé : c'est le corps. Plusieurs (une page de
    # listage), et c'est le conteneur qui les porte tous qu'il faut.
    if len(articles) == 1:
        return articles[0]
    for main in racine.iter("main"):
        return main
    for el in racine.xpath("//*[@role='main']"):
        return el
    for identifiant in ("mw-content-text", "content"):
        for el in racine.xpath(f"//*[@id='{identifiant}']"):
            return el
    corps = racine.find("body")
    return corps if corps is not None else racine


def _mixtes(zone: Any) -> set[Any]:
    """Les éléments de la zone qui portent un bloc quelque part sous eux :
    on y DESCEND ; les autres se rendent d'un tenant."""
    mixtes: set[Any] = set()
    for bloc in zone.iter(*_BLOCS):
        parent = bloc.getparent()
        while parent is not None and parent not in mixtes:
            mixtes.add(parent)
            if parent is zone:
                break
            parent = parent.getparent()
    return mixtes


def _ligne_de_bloc(el: Any) -> str | None:
    """None pour un <tr> sans cellule : on y descend alors comme dans un
    conteneur (21/09 : lxml garde <tr><p>…</p></tr>, et marquer le <tr>
    « pris » avec zéro cellule perdait le paragraphe)."""
    if el.tag != "tr":
        return _texte_plat(el)
    cellules = [
        _texte_cellule(c)
        for c in el
        if isinstance(c.tag, str) and c.tag in ("th", "td")
    ]
    if not cellules:
        return None
    return " | ".join(c for c in cellules if c)


def texte_de(zone: Any) -> str:
    """Une ligne par bloc, en ordre de document ; les cellules d'une ligne de
    tableau sont jointes par « | ».

    Le texte HORS bloc n'est pas perdu : 21/09, « <h1>Titre</h1><div>180
    caractères</div> » ne rendait que « Titre », parce qu'un seul bloc
    suffisait à désactiver le repli « d'un tenant ». Un conteneur sans bloc
    dessous (<div>, <td> orphelin, <section>) fait sa ligne ; du texte nu
    entre deux blocs aussi ; les balises en ligne (<a>, <b>, <time>)
    prolongent la ligne en cours.
    """
    lignes: list[str] = []
    mixtes = _mixtes(zone)

    def poser(ligne: str) -> None:
        ligne = " ".join(ligne.split())
        if len(ligne) >= 2:
            lignes.append(ligne)

    # Chaque cadre : (élément, enfants restants, ligne en cours).
    pile: list[tuple[Any, Any, list[str]]] = [(zone, iter(zone), [zone.text or ""])]
    while pile:
        el, enfants, course = pile[-1]
        enfant = next(enfants, None)
        if enfant is None:
            pile.pop()
            poser("".join(course))
            if pile:
                pile[-1][2].append(el.tail or "")
            continue
        if not isinstance(enfant.tag, str):  # commentaire, instruction
            course.append(enfant.tail or "")
            continue
        tag = enfant.tag
        if tag in _BLOCS:
            ligne = _ligne_de_bloc(enfant)
            if ligne is not None:
                poser("".join(course))
                course.clear()
                poser(ligne)
                course.append(enfant.tail or "")
                continue
        if tag in _BLOCS or enfant in mixtes:
            poser("".join(course))
            course.clear()
            pile.append((enfant, iter(enfant), [enfant.text or ""]))
            continue
        if tag in _SEPARATEURS:
            poser("".join(course))
            course.clear()
            poser(_texte_plat(enfant))
            course.append(enfant.tail or "")
            continue
        course.append(_morceaux(enfant, coupures=False))
        course.append(enfant.tail or "")
    return "\n".join(lignes)


def titre_de(doc: Any) -> str:
    """og:title, sinon <title>, sinon le premier h1, borné à TITRE_MAX.
    « — Wikipédia » reste : c'est le nom de la source."""
    for meta in doc.iter("meta"):
        cle = (meta.get("property") or meta.get("name") or "").strip().lower()
        if cle == "og:title":
            titre = " ".join((meta.get("content") or "").split())
            if titre:
                return titre[:TITRE_MAX]
    for balise in ("title", "h1"):
        el = doc.find(f".//{balise}")
        if el is not None:
            titre = _texte_plat(el)
            if titre:
                return titre[:TITRE_MAX]
    return ""


def _objets_ld(donnees: Any) -> list[dict[str, Any]]:
    """Les objets d'un JSON-LD : l'objet, la liste, et le contenu de @graph."""
    objets: list[dict[str, Any]] = []
    file = [donnees]
    while file:
        courant = file.pop(0)
        if isinstance(courant, list):
            file.extend(courant)
        elif isinstance(courant, dict):
            objets.append(courant)
            graphe = courant.get("@graph")
            if isinstance(graphe, list):
                file.extend(graphe)
    return objets


def _valeur_ld(obj: dict[str, Any], cle: str) -> str:
    valeur = obj.get(cle)
    if isinstance(valeur, list):
        valeur = valeur[0] if valeur else ""
    return str(valeur or "")


def _porte_une_date(el: Any, zone: Any) -> bool:
    """Un <time> compte s'il est dans un <article> ou se dit published/date —
    sauf dans une table : l'infobox réelle de fr.wikipedia (21/09) porte
    « depuis le <time class="date-lien" datetime="2025-03-14"> », un fait
    sur le titulaire, que la règle de classe aurait pris pour la date de la
    page dès que le JSON-LD manque."""
    dans_article = zone.tag == "article"
    parent = el.getparent()
    while parent is not None and parent is not zone:
        if parent.tag == "table":
            return False
        if parent.tag == "article":
            dans_article = True
        parent = parent.getparent()
    return dans_article or bool(
        _MARQUE_DATE.search(el.get("class") or "")
        or _MARQUE_DATE.search(el.get("itemprop") or "")
    )


def dates_de_page(doc: Any, entetes: Mapping[str, str] | None) -> tuple[str, str]:
    """(publie, modifie), chacun pris à la première source qui le déclare :
    JSON-LD, puis <meta>, puis <time> (publie seulement), puis l'en-tête
    Last-Modified (modifie seulement) — et celui-ci uniquement quand la page
    ne déclare RIEN : sur une page rendue à la volée, Last-Modified vaut
    l'instant de la requête, pas une date d'article.
    """
    publie = modifie = ""
    for script in doc.iter("script"):
        if (script.get("type") or "").strip().lower() != "application/ld+json":
            continue
        try:
            donnees = json.loads(script.text or "")
        except (ValueError, RecursionError):
            # 21/09 : 100 000 crochets ouvrants faisaient sortir une
            # RecursionError de json.loads, et toute la page était refusée
            # pour un script illisible. Un JSON-LD illisible s'ignore.
            continue
        for obj in _objets_ld(donnees):
            publie = publie or date_iso(_valeur_ld(obj, "datePublished"))
            modifie = modifie or date_iso(_valeur_ld(obj, "dateModified"))
    if not (publie and modifie):
        metas: dict[str, str] = {}
        for meta in doc.iter("meta"):
            cle = (meta.get("property") or meta.get("name") or "").strip().lower()
            contenu = (meta.get("content") or "").strip()
            if cle and contenu and cle not in metas:
                metas[cle] = contenu
        for cle in _META_PUBLIE:
            publie = publie or date_iso(metas.get(cle, ""))
        for cle in _META_MODIFIE:
            modifie = modifie or date_iso(metas.get(cle, ""))
    if not publie:
        zone = zone_principale(doc)
        for el in zone.iter("time"):
            brut = (el.get("datetime") or "").strip()
            if not brut:
                continue
            if _porte_une_date(el, zone):
                publie = date_iso(brut)
            break
    if not modifie:
        # Revue du 21/09 : en.wikipedia.org/wiki/Prime_Minister_of_Canada n'a
        # pas de dateModified dans son JSON-LD — sa seule date était sa
        # création (2001), prise pour son âge. MediaWiki écrit la dernière
        # modification en pied de page (« La dernière modification de cette
        # page a été faite le 14 août 2026 », « This page was last edited on
        # 11 September 2026 »).
        modifie = _derniere_modification_mediawiki(doc)
    if not publie and not modifie and entetes:
        bas = {str(k).lower(): str(v) for k, v in entetes.items()}
        modifie = date_iso(bas.get("last-modified", ""))
    return publie, modifie


_DATE_EN_CLAIR = re.compile(
    r"(\d{1,2}(?:er)?\s+[A-Za-zéû]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},\s+\d{4})"
)


def _derniere_modification_mediawiki(doc: Any) -> str:
    for el in doc.iter():
        if el.get("id") == "footer-info-lastmod":
            m = _DATE_EN_CLAIR.search(" ".join((el.text_content() or "").split()))
            return date_iso(m.group(1)) if m else ""
    return ""


def extraire(html: str, url: str, entetes: Mapping[str, str] | None = None) -> Page:
    """Titre, dates et texte principal d'un document HTML — sans réseau.
    Lève PageIllisible quand le HTML ne peut pas être lu en entier."""
    doc = _analyser(html)
    titre = titre_de(doc)
    publie, modifie = dates_de_page(doc, entetes)
    texte = texte_de(zone_principale(doc))
    return Page(url=url, titre=titre, publie=publie, modifie=modifie, texte=texte)


def _a_du_texte(texte: str) -> bool:
    """Au moins une lettre ou un chiffre : trois octets nuls deviennent
    « ��� » sous lxml, que strip() garde."""
    return any(c.isalnum() for c in texte)


def _page_texte_brut(texte: str, url: str, entetes: Mapping[str, str] | None) -> Page:
    lignes = [" ".join(ligne.split()) for ligne in (texte or "").splitlines()]
    bas = {str(k).lower(): str(v) for k, v in (entetes or {}).items()}
    return Page(
        url=url,
        titre="",
        publie="",
        modifie=date_iso(bas.get("last-modified", "")),
        texte="\n".join(ligne for ligne in lignes if ligne),
    )


# ---------------------------------------------------------------------------
# Composition — ce que le modèle lira
# ---------------------------------------------------------------------------

# « actuel » et « current » sont UTILES : c'est le mot qui distingue le
# titulaire de ses prédécesseurs. « est », « qui » tombent par la longueur.
_MOTS_VIDES = frozenset(
    """
    dans avec pour quel quelle quels quelles sont etre avoir cette ceux celle
    celles chez sans sous vers entre comme aussi plus moins tout tous toute
    toutes depuis encore autre autres meme memes mais donc elle elles nous
    vous leur leurs comment combien quand quoi pourquoi
    what who whom whose the this that these those when where which does have
    has had from into about been were will would could should there their
    they them than then also some more most very just only your over under
    after before while because
    """.split()
)
_MOT = re.compile(r"[a-z0-9]+")


def _mots_utiles(focus: str) -> list[str]:
    vus: list[str] = []
    for mot in _MOT.findall(_aplatir(focus or "")):
        if len(mot) >= 4 and mot not in _MOTS_VIDES and mot not in vus:
            vus.append(mot)
    return vus


def _reculer(texte: str, pos: int) -> int:
    """Recule jusqu'à un blanc (40 caractères au plus) pour ne pas couper un
    mot."""
    if pos >= len(texte):
        return len(texte)
    k = pos
    while k > 0 and k > pos - 40 and not texte[k].isspace():
        k -= 1
    return k if k > pos - 40 else pos


def _avancer(texte: str, pos: int) -> int:
    k = max(pos, 1)
    while k < len(texte) and k < pos + 40 and not texte[k - 1].isspace():
        k += 1
    return k if k < pos + 40 else pos


@dataclass(frozen=True)
class _Fenetre:
    debut: int
    fin: int
    score: int


def _fenetres(texte: str, mots: list[str], apres: int) -> list[_Fenetre]:
    """Fenêtres ±FENETRE autour de chaque occurrence, hors de ce que le
    début montre déjà, notées par le nombre de mots du focus qu'elles
    portent."""
    plat = _aplatir(texte)
    motifs = [re.compile(r"\b" + re.escape(m)) for m in mots]
    fenetres: list[_Fenetre] = []
    for motif in motifs:
        for m in motif.finditer(plat):
            debut, fin = max(0, m.start() - FENETRE), min(len(plat), m.end() + FENETRE)
            if fin <= apres:
                continue
            debut = _avancer(texte, max(debut, apres)) if debut > apres else apres
            fin = _reculer(texte, fin)
            if fin - debut < 2:
                continue
            morceau = plat[debut:fin]
            score = sum(1 for autre in motifs if autre.search(morceau))
            fenetres.append(_Fenetre(debut, fin, score))
    return fenetres


def _fusionner(intervalles: list[tuple[int, int]]) -> list[tuple[int, int]]:
    fusion: list[tuple[int, int]] = []
    for a, b in sorted(intervalles):
        if fusion and a <= fusion[-1][1]:
            fusion[-1] = (fusion[-1][0], max(fusion[-1][1], b))
        else:
            fusion.append((a, b))
    return fusion


def _choisir(fenetres: list[_Fenetre], budget: int) -> list[tuple[int, int]]:
    """Les fenêtres les plus riches d'abord (revue du 21/09 : la vraie page
    Wikipédia dit « premier ministre » quarante fois avant la phrase qui
    porte aussi « actuel »), rendues ensuite en ordre de document."""
    retenues: list[tuple[int, int]] = []
    utilise = 0
    for f in sorted(fenetres, key=lambda f: (-f.score, f.debut)):
        nouveau = (f.fin - f.debut) - sum(
            max(0, min(f.fin, b) - max(f.debut, a)) for a, b in retenues
        )
        if nouveau <= 0:
            continue
        cout = nouveau + 3  # « … »
        if utilise + cout > budget:
            continue
        retenues = _fusionner(retenues + [(f.debut, f.fin)])
        utilise += cout
    return retenues


def _couper(corps: str, budget: int) -> str:
    place = budget - len(COUPE) - 1
    if place <= 0:
        return COUPE[: max(budget, 0)]
    return corps[:place].rstrip() + " " + COUPE


def composer(page: Page, focus: str = "", limite: int = LIMITE_CARACTERES) -> str:
    """L'en-tête numéroté [1] (agentic_stream renumérote d'après
    metadata["sources"]), la source, le début de la page, puis les passages
    autour des mots du focus. Jamais plus de ``limite`` caractères ; si du
    texte est omis, la fin le dit — et seulement alors."""
    dom = domaine(page.url)
    titre = " ".join((page.titre or page.url).split())[:TITRE_MAX]
    entete = f"[1] {titre} — {dom}"
    if page.publie:
        entete += f" · publié {page.publie}"
    if page.modifie:
        entete += f" · modifié {page.modifie}"
    tete = f"{entete}\nSource: {page.url}\n"
    if len(tete) > limite:
        # Une URL démesurée ou une limite minuscule : l'en-tête seul
        # dépassait (21/09 : limite 60 → 100 caractères rendus).
        tete = tete[:limite]
    budget = limite - len(tete)
    texte = page.texte
    fin_debut = _reculer(texte, TAILLE_DEBUT)
    mots = _mots_utiles(focus)
    choisies: list[tuple[int, int]] = []
    debut = ""
    if mots and len(texte) > fin_debut:
        debut = "Début : " + texte[:fin_debut]
        reste = budget - len(debut) - len("\nPassages : ") - len(COUPE) - 1
        choisies = _choisir(_fenetres(texte, mots, fin_debut), reste)
    if not choisies:
        corps = "Début : " + texte
        if len(corps) > budget:
            corps = _couper(corps, budget)
        return tete + corps
    passages = " … ".join(texte[a:b].strip() for a, b in choisies)
    corps = f"{debut}\nPassages : {passages}"
    # 21/09 : « [… texte coupé] » venait dès qu'il y avait des passages, même
    # quand début + passages couvraient tout le texte (1 242 caractères rendus
    # en entier, annoncés coupés). Le marqueur ne vient que si ce qui est
    # montré n'atteint pas la fin ; les trous entre fenêtres portent « … ».
    if _fusionner([(0, fin_debut), *choisies]) != [(0, len(texte))]:
        corps += " " + COUPE
    if len(corps) > budget:
        corps = _couper(corps, budget)
    return tete + corps


# ---------------------------------------------------------------------------
# Réseau
# ---------------------------------------------------------------------------


class _Refus(Exception):
    """URL refusée avant tout appel réseau (SSRF)."""


class _Arret(Exception):
    """Téléchargement arrêté pour une raison qui se dit telle quelle."""


@dataclass(frozen=True)
class _Telechargement:
    url: str
    statut: int
    type_mime: str
    octets: bytes
    entetes: dict[str, str]


def _decompresseur(encodage: str, premier: bytes) -> Any:
    """Le décompresseur zlib qui convient à l'encodage annoncé.

    « deflate » est en principe un flux zlib (RFC 1950), mais certains
    serveurs (IIS) envoient le deflate nu (RFC 1951) ; l'en-tête zlib se
    reconnaît à ses deux premiers octets.
    """
    if encodage in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if (
        len(premier) >= 2
        and premier[0] & 0x0F == 8
        and ((premier[0] << 8) | premier[1]) % 31 == 0
    ):
        return zlib.decompressobj(zlib.MAX_WBITS)
    return zlib.decompressobj(-zlib.MAX_WBITS)


def _lire_borne(reponse: Any, encodage: str, echeance: float) -> bytes:
    """Au plus TAILLE_MAX_OCTETS, DÉCOMPRESSÉS, quel que soit le morceau reçu.

    21/09 : iter_bytes() décompresse chaque morceau brut en entier avant que
    la borne ne soit regardée — un seul morceau de 64 Ko d'une bombe gzip
    (1 Go de zéros pour 972 Ko) livrait 67 Mo d'un coup, +131 Mo de RSS.
    iter_raw() rend le brut ; zlib avec ``max_length`` ne matérialise jamais
    plus que ce qui reste du plafond. L'horloge est relue à chaque morceau :
    c'est elle qui borne un serveur qui goutte.
    """
    encodage = (encodage or "").strip().lower()
    if encodage not in ("", "identity", "gzip", "x-gzip", "deflate"):
        raise _Arret(f"Lecture impossible : encodage {encodage} non pris en charge")
    decompresseur = None
    tampon = bytearray()
    for brut in reponse.iter_raw():
        if time.monotonic() > echeance:
            raise _Arret("Lecture impossible : trop lent")
        reste = TAILLE_MAX_OCTETS - len(tampon)
        if encodage in ("", "identity"):
            tampon += brut[:reste]
        else:
            if decompresseur is None:
                decompresseur = _decompresseur(encodage, brut)
            try:
                tampon += decompresseur.decompress(brut, reste)
            except zlib.error:
                raise _Arret(
                    "Lecture impossible : contenu compressé illisible"
                ) from None
        if len(tampon) >= TAILLE_MAX_OCTETS:
            break
    return bytes(tampon)


def _telecharger(url: str) -> _Telechargement:
    """GET borné à TAILLE_MAX_OCTETS et à DELAI_S au total, redirections
    suivies à la main pour que check_ssrf voie chaque adresse AVANT qu'on la
    joigne. Un type qu'on ne lira pas (PDF, image) n'est pas téléchargé."""
    import httpx

    echeance = time.monotonic() + DELAI_S
    courante = url
    for _ in range(MAX_REDIRECTIONS + 1):
        refus = check_ssrf(courante)
        if refus:
            raise _Refus(refus)
        if time.monotonic() > echeance:
            raise _Arret("Lecture impossible : trop lent")
        with httpx.stream(
            "GET",
            courante,
            follow_redirects=False,
            timeout=DELAI_OPERATION_S,
            headers=ENTETES_REQUETE,
        ) as reponse:
            entetes = {str(k).lower(): str(v) for k, v in reponse.headers.items()}
            statut = int(reponse.status_code)
            if 300 <= statut < 400 and entetes.get("location"):
                courante = urljoin(courante, entetes["location"])
                continue
            type_mime = entetes.get("content-type", "").split(";")[0].strip().lower()
            octets = b""
            if not type_mime or type_mime in TYPES_LISIBLES:
                octets = _lire_borne(
                    reponse, entetes.get("content-encoding", ""), echeance
                )
            return _Telechargement(courante, statut, type_mime, octets, entetes)
    raise httpx.TooManyRedirects(f"plus de {MAX_REDIRECTIONS} redirections")


_CHARSET_ENTETE = re.compile(r"charset=\"?([\w-]+)", re.I)
_CHARSET_META = re.compile(rb"<meta[^>]+charset=[\"']?([\w-]+)", re.I)


def _decoder(octets: bytes, type_complet: str) -> str:
    m = _CHARSET_ENTETE.search(type_complet or "")
    charset = m.group(1) if m else ""
    if not charset:
        m2 = _CHARSET_META.search(octets[:4096])
        charset = m2.group(1).decode("ascii", "replace") if m2 else "utf-8"
    try:
        return octets.decode(charset, errors="replace")
    except (LookupError, ValueError):
        # 21/09 : « charset=idna » (un codec qui existe mais n'est pas un
        # texte : « Unsupported error handling: replace ») et « undefined »
        # sortaient une UnicodeError brute de l'outil — UnicodeError est une
        # ValueError, LookupError ne la couvrait pas. Un charset qu'on ne sait
        # pas lire est lu comme de l'UTF-8.
        return octets.decode("utf-8", errors="replace")


@ToolRegistry.register("web_read")
class WebReadTool(BaseTool):
    """Read one web page: main text, title and dates it declares."""

    tool_id = "web_read"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_read",
            description=(
                "Read one web page: main text, title and publication date."
                " Use it after web_search when the extracts do not state the"
                " fact asked; cite the page by its [N]."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Page URL (http/https)."},
                    "focus": {
                        "type": "string",
                        "description": (
                            "Words to look for; the passages around them"
                            " are returned first."
                        ),
                    },
                },
                "required": ["url"],
            },
            category="search",
            timeout_seconds=20.0,
        )

    # Les messages sont en français, tous : ce ``content`` est lu par le
    # modèle, affiché par la carte d'outil et PRONONCÉ par le chemin vocal.
    # 21/09 : deux messages en anglais et sept en français dans le même
    # outil, selon la branche d'erreur.
    def execute(self, **params: Any) -> ToolResult:
        url = str(params.get("url") or "").strip()
        focus = str(params.get("focus") or "")
        if not url:
            return ToolResult(
                tool_name="web_read", content="Aucune URL fournie.", success=False
            )
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult(
                tool_name="web_read",
                content="L'URL doit commencer par http:// ou https://.",
                success=False,
            )
        try:
            lu = _telecharger(url)
        except _Refus as exc:
            return ToolResult(
                tool_name="web_read",
                content=f"Adresse refusée : {exc}",
                success=False,
                metadata={"url": url},
            )
        except _Arret as exc:
            return ToolResult(
                tool_name="web_read",
                content=str(exc),
                success=False,
                metadata={"url": url},
            )
        except ImportError:
            return ToolResult(
                tool_name="web_read", content="httpx n'est pas installé.", success=False
            )
        except Exception as exc:  # noqa: BLE001 - la classe suffit, jamais la trace
            logger.debug("web_read %s : %s", url, exc)
            return ToolResult(
                tool_name="web_read",
                content=f"Lecture impossible : {type(exc).__name__}",
                success=False,
                metadata={"url": url},
            )
        if lu.statut >= 400:
            return ToolResult(
                tool_name="web_read",
                content=f"Lecture impossible : HTTP {lu.statut}",
                success=False,
                metadata={"url": lu.url, "status": lu.statut},
            )
        if lu.type_mime == "application/pdf":
            return ToolResult(
                tool_name="web_read",
                content="Cette page est un PDF, non lisible ici.",
                success=False,
                metadata={"url": lu.url},
            )
        # Un serveur muet sur le type est lu comme du HTML : l'analyseur est
        # tolérant, et refuser « Type non lisible :  » n'aiderait personne.
        if lu.type_mime and lu.type_mime not in TYPES_LISIBLES:
            return ToolResult(
                tool_name="web_read",
                content=f"Type non lisible : {lu.type_mime}",
                success=False,
                metadata={"url": lu.url},
            )
        try:
            # Le décodage est SOUS le try (21/09 : appelé au-dessus, un
            # charset exotique sortait de l'outil avec sa trace).
            brut = _decoder(lu.octets, lu.entetes.get("content-type", ""))
            if lu.type_mime == "text/plain":
                page = _page_texte_brut(brut, lu.url, lu.entetes)
            else:
                page = extraire(brut, lu.url, lu.entetes)
        except ImportError:
            return ToolResult(
                tool_name="web_read", content="lxml n'est pas installé.", success=False
            )
        except PageIllisible as exc:
            return ToolResult(
                tool_name="web_read",
                content=str(exc),
                success=False,
                metadata={"url": lu.url},
            )
        except Exception as exc:  # noqa: BLE001 - un HTML monstrueux ne doit pas tracer
            logger.debug("web_read %s : analyse impossible : %s", url, exc)
            return ToolResult(
                tool_name="web_read",
                content=f"Lecture impossible : {type(exc).__name__}",
                success=False,
                metadata={"url": lu.url},
            )
        if not _a_du_texte(page.texte):
            # 21/09 : un corps vide, une SPA (div#root vide + script), des
            # octets nuls rendaient « Début : » vide en SUCCÈS — et
            # agentic_stream comptait la page comme une vérification faite,
            # avec une pastille [N] vers une source qui ne dit rien (§100).
            return ToolResult(
                tool_name="web_read",
                content="Lecture impossible : page sans texte lisible",
                success=False,
                metadata={"url": page.url},
            )
        dom = domaine(page.url)
        return ToolResult(
            tool_name="web_read",
            content=composer(page, focus),
            success=True,
            metadata={
                "url": page.url,
                "title": page.titre,
                "published": page.publie,
                "modified": page.modifie,
                "chars": len(page.texte),
                # Pour l'interface (pastille [N] cliquable) et pour la
                # renumérotation d'agentic_stream — même forme que web_search.
                "sources": [
                    {
                        "ref": 1,
                        "title": page.titre or dom,
                        "url": page.url,
                        "date": page.modifie or page.publie,
                        "sender": dom,
                    }
                ],
            },
        )


__all__ = ["WebReadTool", "Page", "PageIllisible", "extraire", "composer", "date_iso"]
