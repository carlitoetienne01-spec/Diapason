"""Tests de l'outil web_read.

21 septembre 2026 : « Qui est le premier ministre du Canada ? » — les cinq
extraits de web_search ne nommaient pas le titulaire, et le 9b a répondu
« Justin Trudeau [3] ». La page Wikipédia, elle, porte « Titulaire actuel |
Mark Carney | depuis le 14 mars 2025 » dans son infobox ; le lecteur d'URL
de web_search rendait 6 000 caractères de menu et jamais le corps. Tout ici
tourne sans réseau : fixtures HTML en chaînes, téléchargement remplacé.

La revue du 21 septembre au soir a ajouté les pages piégées : bruit qui
englobe le contenu, <header> d'article, bombe gzip, serveur qui goutte, page
vide rendue en succès (§100), « [… texte coupé] » sans rien de coupé (§5).
"""

from __future__ import annotations

import gzip
import importlib
import zlib
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from diapason.core.registry import ToolRegistry
from diapason.security.ssrf import is_private_ip
from diapason.tools import web_read
from diapason.tools.web_read import (
    DELAI_S,
    LIMITE_CARACTERES,
    TAILLE_DEBUT,
    TAILLE_MAX_OCTETS,
    TITRE_MAX,
    Page,
    WebReadTool,
    composer,
    date_iso,
    dates_de_page,
    extraire,
    texte_de,
    titre_de,
    zone_principale,
)

URL_WIKI = "https://fr.wikipedia.org/wiki/Premier_ministre_du_Canada"

# (a) Façon Wikipédia : main + mw-content-text, hatnote, infobox en table,
# bandeau court, référence en <sup>, [modifier], JSON-LD, nav, footer,
# bandeau cookies, og:title.
WIKI = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Premier ministre du Canada — Wikipédia</title>
<meta property="og:title" content="Premier ministre du Canada — Wikipédia">
<script type="application/ld+json">{"@context":"https://schema.org",
"@type":"Article","name":"Premier ministre du Canada",
"datePublished":"2002-11-24T09:22:21Z","dateModified":"2026-08-14T13:27:33Z"}
</script>
<style>.mw-body{margin:0}</style>
</head><body>
<header id="mw-head"><nav><ul><li>Accueil</li><li>Portails</li></ul></nav></header>
<div id="cookie-banner">Ce site utilise des témoins. <button>Accepter</button></div>
<main id="content">
<h1 id="firstHeading">Premier ministre du Canada</h1>
<div id="mw-content-text"><div class="mw-parser-output">
<div class="hatnote">Pour les articles homonymes, voir Premier ministre.</div>
<table class="infobox">
<caption>Premier ministre du Canada</caption>
<tr><th scope="row">Titulaire actuel</th><td>Mark Carney</td>
<td><time datetime="2025-03-14">depuis le 14 mars 2025</time></td></tr>
<tr><th scope="row">Création</th><td>1<sup>er</sup> juillet 1867</td></tr>
</table>
<p class="mw-empty-elt"></p>
<p>Voir aussi le portail.</p>
<p><b>Mark Carney</b>, le premier ministre actuel, a prêté serment le
14 mars 2025, après la démission de Justin Trudeau<sup class="reference"
id="cite_ref-2"><a href="#cite_note-2">[2]</a></sup>.</p>
<h2><span class="mw-headline">Histoire</span><span class="mw-editsection">[<a
href="#">modifier</a>]</span></h2>
<ul><li>Premier point<ul><li>Sous-point imbriqué</li></ul></li>
<li>Second point</li></ul>
<div class="toc"><ul><li>Sommaire 1</li></ul></div>
</div></div>
</main>
<aside class="sidebar">Outils de la barre latérale</aside>
<footer><p>Texte du pied de page sous licence.</p></footer>
</body></html>"""

# (b) Drupal : un <article> étoffé et une meta inanalysable (pm.gc.ca, 21/09).
DRUPAL = """<html><head>
<title>Le premier ministre | Premier ministre du Canada</title>
<meta property="article:published_time" content="ven, 06/17/2016 - 20:07">
</head><body>
<header><nav><a href="/">Accueil</a></nav></header>
<article>
<h1>Le très honorable Mark Carney</h1>
<p>Mark Carney est le vingt-quatrième premier ministre du Canada. Avant
d'entrer en politique, il a été gouverneur de la Banque du Canada et
gouverneur de la Banque d'Angleterre, et a présidé le Conseil de stabilité
financière. Il a grandi à Edmonton, en Alberta, et a étudié à Harvard puis
à Oxford. Il a été assermenté le 14 mars 2025 et a mené son parti aux
élections générales du printemps suivant. Son gouvernement a fait de la
réponse aux droits de douane américains et de la construction de logements
ses deux premières priorités, ainsi que la diversification des échanges.</p>
</article>
<footer>Gouvernement du Canada</footer>
</body></html>"""

# (c) Banque du Canada : dates en <meta name=…>.
BANQUE = """<html><head><title>Taux directeur - Banque du Canada</title>
<meta name="publication_date" content="2010-06-01">
<meta name="last_modified_date" content="2026-09-02">
</head><body><main>
<h1>Taux directeur</h1>
<p>Le taux cible du financement à un jour est de 2,25 %.</p>
<table><tr><th>Date</th><th>Taux cible</th></tr>
<tr><td>2 septembre 2026</td><td>2,25</td></tr></table>
</main></body></html>"""

# (d)/(e) Rien de daté dans le document.
SANS_DATE = """<html><head><title>Sans date</title></head>
<body><main><p>Rien de daté ici, mais un vrai paragraphe.</p></main></body></html>"""

# (f) Ni article ni main : des div.
DIVS = """<html><head><title>Vieille page</title></head><body>
<div id="page"><div class="wrap"><p>Un paragraphe dans des div.</p>
<p>Un second paragraphe.</p></div></div></body></html>"""

# Un article court (teaser) dans un main qui porte le vrai contenu.
TEASER = """<html><body><main>
<article><p>Résumé court.</p></article>
<p>Le contenu principal de la page, qui n'est pas dans l'article.</p>
</main></body></html>"""

CORPS_LONG = "Le corps du billet, assez long pour dépasser le seuil du teaser. " * 10

# WordPress (Twenty Seventeen) : body.has-sidebar, <article><header> avec
# le h1 et <time class="entry-date published">, aside.sidebar avec une carte
# <article> étoffée — revue du 21/09.
WORDPRESS = f"""<html><head><title>Billet</title></head>
<body class="post-template-default single has-sidebar">
<div id="page" class="site"><div id="content" class="site-content">
<main id="main" class="site-main">
<article class="post">
<header class="entry-header"><h1 class="entry-title">Le titre du billet</h1>
<p class="byline">Par X, <time class="entry-date published"
datetime="2025-03-14T10:00:00-04:00">14 mars 2025</time></p></header>
<div class="entry-content"><p>{CORPS_LONG}</p></div>
</article>
</main>
<aside id="secondary" class="widget-area sidebar"><article class="widget">
<p>{"Carte de barre latérale, assez longue pour passer le seuil. " * 10}</p>
</article></aside>
</div></div></body></html>"""

# ASP.NET WebForms : un seul <form id="form1"> enveloppe TOUT le corps.
WEBFORMS = f"""<html><head><title>Service en ligne</title></head><body>
<form method="post" action="./Default.aspx" id="form1">
<div class="aspNetHidden"><input type="hidden" name="__VIEWSTATE" value="x"></div>
<div><h1>Permis de conduire</h1><p>{CORPS_LONG}</p></div>
</form></body></html>"""

ENTETES_HTML = {"content-type": "text/html; charset=utf-8"}


def _doc(html: str) -> Any:
    return web_read._analyser(html)


class TestLesDates:
    """§5 : une date est prise telle que la page la déclare, ou pas du tout."""

    @pytest.mark.parametrize(
        ("brute", "attendu"),
        [
            pytest.param("2026-09-02", "2026-09-02", id="iso nu"),
            pytest.param("2002-11-24T09:22:21Z", "2002-11-24", id="iso avec Z"),
            pytest.param("2026-08-14T13:27:33+00:00", "2026-08-14", id="iso fuseau"),
            pytest.param("2026-08-14 13:27", "2026-08-14", id="iso espace"),
            pytest.param("Thu, 14 Aug 2026 13:27:33 GMT", "2026-08-14", id="rfc 2822"),
            pytest.param("14 mars 2025", "2025-03-14", id="jour mois français"),
            pytest.param("1er juillet 1867", "1867-07-01", id="1er juillet"),
            pytest.param("3 février 2024", "2024-02-03", id="accent"),
            pytest.param("3 fevrier 2024", "2024-02-03", id="sans accent"),
            pytest.param("14 Mars 2025", "2025-03-14", id="majuscule"),
            pytest.param("jeudi 14 mars 2025", "2025-03-14", id="jour de semaine"),
            pytest.param("March 14, 2025", "2025-03-14", id="mois jour anglais"),
            pytest.param("14 March 2025", "2025-03-14", id="jour mois anglais"),
            pytest.param("Mar 14, 2025", "2025-03-14", id="mar = March, pas mardi"),
            pytest.param("  2026-09-02\n", "2026-09-02", id="blancs autour"),
        ],
    )
    def test_les_formes_sans_ambiguite_sont_normalisees(self, brute, attendu):
        assert date_iso(brute) == attendu, f"{brute!r} doit donner {attendu}"

    @pytest.mark.parametrize(
        "brute",
        [
            pytest.param("ven, 06/17/2016 - 20:07", id="drupal pm.gc.ca"),
            pytest.param("06/17/2016 - 20:07", id="mm/jj/aaaa"),
            pytest.param("jeu, 01/01/1970", id="jj/mm/aaaa"),
            pytest.param("14-03-2025", id="tirets ambigus"),
            pytest.param("février 2025", id="mois sans jour"),
            pytest.param("2026-09", id="iso sans jour"),
            pytest.param("2025", id="année seule"),
            pytest.param("30 février 2025", id="jour inexistant"),
            pytest.param("2025-13-01", id="mois inexistant"),
            pytest.param("hier", id="relatif"),
            pytest.param("", id="vide"),
            pytest.param(None, id="None"),
        ],
    )
    def test_une_forme_ambigue_ou_inconnue_rend_vide(self, brute):
        assert date_iso(brute) == "", f"{brute!r} ne doit pas être deviné (§5)"

    def test_le_json_ld_prime_et_le_time_de_l_infobox_est_ignore(self):
        assert dates_de_page(_doc(WIKI), ENTETES_HTML) == ("2002-11-24", "2026-08-14")

    def test_sans_json_ld_le_time_de_l_infobox_n_est_pas_une_date_de_page(self):
        """§5 : le <time> « depuis le 14 mars 2025 » est un fait sur le
        titulaire, pas la date de la page — la prendre serait deviner."""
        html = WIKI.replace("application/ld+json", "text/x-rien")
        assert dates_de_page(_doc(html), ENTETES_HTML) == ("", ""), (
            "un <time> d'infobox n'est pas une date de page (§5)"
        )

    def test_un_time_de_classe_date_dans_une_table_reste_ignore(self):
        """Revue du 21/09 : l'infobox réelle porte class="date-lien"."""
        html = SANS_DATE.replace(
            "<main>",
            '<main><table><tr><td><time class="date-lien" datetime="2025-03-14">'
            "14 mars 2025</time></td></tr></table>",
        )
        assert dates_de_page(_doc(html), None) == ("", "")

    def test_un_time_dans_un_article_donne_publie(self):
        html = DRUPAL.replace(
            "<h1>", '<time datetime="2025-03-14T10:00:00-04:00">14 mars</time><h1>'
        )
        assert dates_de_page(_doc(html), None) == ("2025-03-14", "")

    def test_un_time_dans_l_en_tete_d_un_article_donne_publie(self):
        """21/09 : <time class="published"> vivait dans <article><header> et
        n'était jamais lu — <header> était du bruit même dans un article, et
        une date DÉCLARÉE n'était pas rendue (§5, dans l'autre sens)."""
        assert dates_de_page(_doc(WORDPRESS), None) == ("2025-03-14", ""), (
            "le <time> de l'en-tête d'article est la date de publication"
        )

    def test_un_time_marque_published_hors_article_donne_publie(self):
        html = SANS_DATE.replace(
            "<main>",
            '<main><time class="entry-published" datetime="2024-01-02">x</time>',
        )
        assert dates_de_page(_doc(html), None) == ("2024-01-02", "")

    def test_le_premier_time_seul_compte(self):
        """Un <time> sans marque en tête ne cède pas la place au suivant."""
        html = SANS_DATE.replace(
            "<main>",
            '<main><time datetime="2020-01-01">a</time>'
            '<time class="published" datetime="2024-01-02">b</time>',
        )
        assert dates_de_page(_doc(html), None) == ("", "")

    def test_la_meta_drupal_inanalysable_ne_donne_rien(self):
        assert dates_de_page(_doc(DRUPAL), None) == ("", "")

    def test_les_meta_de_la_banque_du_canada(self):
        assert dates_de_page(_doc(BANQUE), None) == ("2010-06-01", "2026-09-02")

    def test_l_entete_last_modified_seul_donne_modifie(self):
        entetes = {"Last-Modified": "Thu, 14 Aug 2026 13:27:33 GMT"}
        assert dates_de_page(_doc(SANS_DATE), entetes) == ("", "2026-08-14")

    def test_l_entete_ne_supplante_pas_une_date_declaree(self):
        """Une page rendue à la volée porte un Last-Modified de l'instant."""
        entetes = {"last-modified": "Mon, 21 Sep 2026 12:00:00 GMT"}
        assert dates_de_page(_doc(BANQUE), entetes) == ("2010-06-01", "2026-09-02")

    def test_rien_de_date_rend_deux_vides(self):
        assert dates_de_page(_doc(SANS_DATE), None) == ("", "")

    def test_le_json_ld_en_liste_et_en_graph(self):
        html = SANS_DATE.replace(
            "</head>",
            '<script type="application/ld+json">[{"@graph":[{"@type":"WebPage"},'
            '{"@type":"Article","datePublished":"2021-05-06"}]}]</script></head>',
        )
        assert dates_de_page(_doc(html), None) == ("2021-05-06", "")

    def test_un_json_ld_casse_est_ignore(self):
        html = SANS_DATE.replace(
            "</head>", '<script type="application/ld+json">{pas du json</script></head>'
        )
        assert dates_de_page(_doc(html), None) == ("", "")

    def test_un_json_ld_trop_profond_n_est_pas_une_raison_de_refuser_la_page(self):
        """21/09 : 100 000 crochets faisaient sortir une RecursionError de
        json.loads, et la page entière était refusée pour un script."""
        html = SANS_DATE.replace(
            "</head>",
            '<script type="application/ld+json">'
            + "[" * 100_000
            + "]" * 100_000
            + "</script></head>",
        )
        assert dates_de_page(_doc(html), None) == ("", "")
        assert "vrai paragraphe" in extraire(html, "https://example.com/").texte, (
            "un JSON-LD illisible s'ignore, il ne condamne pas la page"
        )

    @pytest.mark.parametrize(
        ("pied", "attendu"),
        [
            (
                "La dernière modification de cette page a été faite le 14 août "
                "2026 à 15:27.",
                "2026-08-14",
            ),
            (
                "This page was last edited on 11 September 2026, at 00:05 (UTC).",
                "2026-09-11",
            ),
            ("Page sans date de modification.", ""),
        ],
        ids=["fr", "en", "sans-date"],
    )
    def test_le_pied_mediawiki_donne_la_derniere_modification(self, pied, attendu):
        """Revue du 21/09 : en.wikipedia.org/wiki/Prime_Minister_of_Canada n'a
        pas de dateModified dans son JSON-LD ; sa seule date, la création
        (2001), passait pour son âge — « sources datées de 2001 »."""
        html = (
            '<html><head><title>Page</title><script type="application/ld+json">'
            '{"@type":"Article","datePublished":"2001-07-31T08:51:11Z"}</script>'
            "</head><body><main><p>Un vrai paragraphe qui fait plus de soixante "
            "caractères pour compter comme du texte.</p></main>"
            f'<footer><ul><li id="footer-info-lastmod"> {pied}</li></ul></footer>'
            "</body></html>"
        )
        assert dates_de_page(
            _doc(html), {"last-modified": "Sun, 20 Sep 2026 18:44:52 GMT"}
        ) == (
            "2001-07-31",
            attendu,
        ), (
            "le pied de page avant l'en-tête HTTP, et jamais l'en-tête quand la "
            "page déclare"
        )


class TestLaZonePrincipale:
    """La zone est choisie APRÈS le retrait du bruit — mais le bruit ne doit
    jamais emporter ce qui englobe le contenu (revue du 21/09)."""

    def test_le_bruit_est_retire_et_l_infobox_gardee(self):
        zone = zone_principale(_doc(WIKI))
        texte = zone.text_content()
        for bruit in (
            "Accueil",
            "témoins",
            "Pour les articles homonymes",
            "[2]",
            "modifier",
            "Sommaire",
            "barre latérale",
            "licence",
        ):
            assert bruit not in texte, f"« {bruit} » est du bruit"
        assert "Titulaire actuel" in texte, "l'infobox est une table et reste"

    def test_sans_article_c_est_main(self):
        assert zone_principale(_doc(WIKI)).tag == "main"

    def test_un_article_etoffe_est_la_zone(self):
        assert zone_principale(_doc(DRUPAL)).tag == "article"

    def test_un_article_court_cede_a_main(self):
        zone = zone_principale(_doc(TEASER))
        assert zone.tag == "main", "un teaser de 13 caractères n'est pas le corps"

    def test_sans_article_ni_main_c_est_le_corps(self):
        assert zone_principale(_doc(DIVS)).tag == "body"

    def test_role_main_puis_id_content(self):
        assert (
            zone_principale(_doc('<div role="main"><p>x</p></div>')).get("role")
            == "main"
        )
        assert (
            zone_principale(_doc('<div id="content"><p>x</p></div>')).get("id")
            == "content"
        )

    def test_le_document_n_est_pas_mute(self):
        """Retirer les <script> du document lui-même emporterait le JSON-LD."""
        doc = _doc(WIKI)
        zone_principale(doc)
        assert doc.find(".//script") is not None, "le JSON-LD doit survivre"
        assert dates_de_page(doc, None) == ("2002-11-24", "2026-08-14")

    def test_un_mot_de_bruit_ne_matche_pas_dans_un_autre_mot(self):
        zone = zone_principale(_doc('<main><p class="stock-price">42 $</p></main>'))
        assert "42 $" in zone.text_content(), "« stock » n'est pas « toc »"

    @pytest.mark.parametrize(
        "html",
        [
            pytest.param(
                '<body class="single has-sidebar"><main><p>Texte visible.</p>'
                "</main></body>",
                id="body.has-sidebar (WordPress Twenty Seventeen)",
            ),
            pytest.param(
                '<body><div class="layout with-sidebar"><main><p>Texte visible.'
                '</p></main><aside class="sidebar">x</aside></div></body>',
                id="div.with-sidebar autour de main",
            ),
            pytest.param(
                '<body><main class="entry has-comments"><p>Texte visible.</p>'
                "</main></body>",
                id="main.has-comments",
            ),
            pytest.param(
                '<body><div aria-hidden="true"><main><p>Texte visible.</p></main>'
                "</div></body>",
                id="aria-hidden sur l'enveloppe",
            ),
            pytest.param(
                '<body class="cookie-consent"><div id="content"><p>Texte visible.'
                "</p></div></body>",
                id="body.cookie-consent avec #content",
            ),
        ],
    )
    def test_le_bruit_qui_englobe_le_contenu_n_est_pas_retire(self, html):
        """21/09 : WordPress pose « has-sidebar » sur <body> ; la page
        revenait vide, en succès — 760 caractères d'article perdus."""
        texte = texte_de(zone_principale(_doc(html)))
        assert texte == "Texte visible.", (
            "un ancêtre du contenu n'est jamais du bruit, quelle que soit sa classe"
        )

    def test_un_form_englobant_garde_le_corps(self):
        """21/09 : ASP.NET WebForms enveloppe tout le <body> dans un seul
        <form id="form1"> ; la page revenait vide."""
        texte = texte_de(zone_principale(_doc(WEBFORMS)))
        assert texte.startswith("Permis de conduire\nLe corps du billet"), texte

    def test_un_petit_formulaire_reste_du_bruit(self):
        html = (
            "<main><form><label>Chercher</label><input><button>OK</button></form>"
            "<p>Texte visible.</p></main>"
        )
        assert texte_de(zone_principale(_doc(html))) == "Texte visible."

    def test_l_en_tete_d_un_article_est_garde_la_banniere_du_site_non(self):
        """21/09 : <article><header><h1> est le patron HTML5 canonique ;
        le retirer perdait le titre. Le <header> hors article/main reste une
        bannière."""
        texte = texte_de(zone_principale(_doc(WORDPRESS)))
        assert texte.startswith("Le titre du billet\nPar X, 14 mars 2025"), texte
        assert "Accueil" not in texte_de(zone_principale(_doc(DRUPAL))), (
            "le <header> du site, hors article, est du bruit"
        )

    def test_un_en_tete_de_section_dans_main_est_garde(self):
        html = (
            '<main><header class="page-header"><h1>Taux directeur</h1>'
            "<p>Le taux cible est de 2,25 %.</p></header><p>Le reste.</p></main>"
        )
        assert (
            texte_de(zone_principale(_doc(html)))
            == "Taux directeur\nLe taux cible est de 2,25 %.\nLe reste."
        )

    def test_un_en_tete_garde_par_sa_balise_passe_encore_par_sa_classe(self):
        html = (
            '<main><header class="cookie-banner"><p>Témoins acceptés.</p></header>'
            "<p>Texte visible.</p></main>"
        )
        assert texte_de(zone_principale(_doc(html))) == "Texte visible."

    def test_un_article_de_barre_laterale_ne_protege_pas_l_aside(self):
        zone = zone_principale(_doc(WORDPRESS))
        assert zone.tag == "article"
        assert "Carte de barre latérale" not in texte_de(zone), (
            "l'article de l'aside est une carte : l'aside part avec elle"
        )


class TestLeTexte:
    """Une ligne par bloc, en ordre de document ; rien de ce qui est visible
    n'est perdu (revue du 21/09 : le texte hors bloc l'était)."""

    def test_la_ligne_de_l_infobox_est_jointe_par_des_barres(self):
        """21/09 : text_content() collait « Titulaire actuelMark Carneydepuis
        le 14 mars 2025 » et le 9b ne pouvait pas y lire le titulaire."""
        lignes = texte_de(zone_principale(_doc(WIKI))).splitlines()
        assert "Titulaire actuel | Mark Carney | depuis le 14 mars 2025" in lignes, (
            "les cellules d'une ligne sont jointes par « | » (§5 : lisible tel quel)"
        )

    def test_la_reference_et_modifier_sont_absents(self):
        texte = texte_de(zone_principale(_doc(WIKI)))
        assert "[2]" not in texte
        assert "modifier" not in texte
        assert (
            "Mark Carney, le premier ministre actuel, a prêté serment le 14 mars 2025,"
            " après la démission de Justin Trudeau." in texte
        ), "la queue du <sup> (le point final) doit survivre à son retrait"

    def test_le_sup_sans_classe_reste(self):
        assert "Création | 1er juillet 1867" in texte_de(zone_principale(_doc(WIKI)))

    def test_hatnote_cookies_et_toc_absents(self):
        texte = texte_de(zone_principale(_doc(WIKI)))
        for bruit in ("homonymes", "témoins", "Sommaire", "Voir aussi le portail"):
            if bruit == "Voir aussi le portail":
                assert bruit in texte, (
                    "un bandeau court en <p> est gardé (c'est du texte)"
                )
            else:
                assert bruit not in texte

    def test_un_li_imbrique_n_est_pas_repris(self):
        texte = texte_de(zone_principale(_doc(WIKI)))
        assert texte.count("Sous-point imbriqué") == 1
        assert "Premier point Sous-point imbriqué" in texte, "un blanc entre les blocs"

    def test_un_bloc_dans_une_cellule_reste_dans_sa_ligne(self):
        html = "<main><table><tr><td><p>A</p></td><td><p>B</p></td></tr></table></main>"
        assert texte_de(zone_principale(_doc(html))) == "A | B"

    def test_un_br_dans_une_cellule_separe_des_valeurs(self):
        """L'infobox réelle (21/09) met titulaire, nom et date dans une <td>."""
        html = (
            "<main><table><tr><td><b>Titulaire actuel</b><br><b>Mark Carney</b><br>"
            'depuis le <time datetime="2025-03-14">14 mars 2025</time></td></tr>'
            "</table></main>"
        )
        assert (
            texte_de(zone_principale(_doc(html)))
            == "Titulaire actuel | Mark Carney | depuis le 14 mars 2025"
        )

    def test_l_ordre_du_document_est_respecte(self):
        texte = texte_de(zone_principale(_doc(WIKI)))
        assert texte.index("Titulaire actuel") < texte.index("prêté serment")

    def test_les_blocs_minuscules_sont_ignores(self):
        assert texte_de(zone_principale(_doc("<main><p>a</p><p>ab</p></main>"))) == "ab"

    def test_une_page_sans_bloc_rend_son_texte_d_un_tenant(self):
        assert texte_de(
            zone_principale(_doc("<body><div>Juste du texte</div></body>"))
        ) == ("Juste du texte")

    def test_le_texte_hors_bloc_n_est_pas_perdu_des_qu_un_bloc_existe(self):
        """21/09 : « <h1>Titre</h1><div>180 caractères</div> » ne rendait que
        « Titre » — un seul bloc suffisait à désactiver le repli."""
        html = "<main><h1>Titre</h1><div>Paragraphe sans balise p.</div></main>"
        assert (
            texte_de(zone_principale(_doc(html))) == "Titre\nParagraphe sans balise p."
        ), "un <div> de texte à côté d'un bloc fait sa ligne"

    def test_du_texte_nu_entre_deux_blocs_fait_sa_ligne(self):
        html = "<main>Intro nue <a>avec lien</a>.<p>Para.</p>Fin nue.</main>"
        assert (
            texte_de(zone_principale(_doc(html)))
            == "Intro nue avec lien.\nPara.\nFin nue."
        )

    def test_un_paragraphe_orphelin_dans_un_tr_est_lu(self):
        """21/09 : lxml garde <tr><p>…</p></tr> ; le <tr> était marqué pris
        avec zéro cellule et le paragraphe sauté."""
        html = (
            "<main><table><tr><p>Orphelin dans un tr.</p></tr></table>"
            "<p>Après.</p></main>"
        )
        assert texte_de(zone_principale(_doc(html))) == "Orphelin dans un tr.\nAprès."

    def test_caption_h5_h6_summary_et_td_orphelin_sont_lus(self):
        """21/09 : « Cinq », « Six », « Légende importante » et le résumé
        d'un <details> disparaissaient — pas des blocs, et pas repris."""
        html = (
            "<main><h5>Cinq</h5><h6>Six</h6>"
            "<table><caption>Légende importante</caption><tr><td>ab</td></tr></table>"
            "<details><summary>Résumé</summary>Le détail caché.</details>"
            "<table><td>Cellule sans tr</td></table></main>"
        )
        assert texte_de(zone_principale(_doc(html))).splitlines() == [
            "Cinq",
            "Six",
            "Légende importante",
            "ab",
            "Résumé",
            "Le détail caché.",
            "Cellule sans tr",
        ]

    def test_le_titre_garde_la_source(self):
        assert titre_de(_doc(WIKI)) == "Premier ministre du Canada — Wikipédia"
        assert titre_de(_doc(BANQUE)) == "Taux directeur - Banque du Canada"
        assert titre_de(_doc("<body><h1>Seul un h1</h1></body>")) == "Seul un h1"

    def test_un_titre_demesure_est_borne(self):
        assert len(titre_de(_doc("<title>" + "t" * 5000 + "</title>"))) == TITRE_MAX

    def test_extraire_assemble_le_tout(self):
        # Champ par champ, pas par égalité de dataclass : sous la suite
        # complète, test_tool_registration recharge le module et ``Page``
        # devient une autre classe (21/09).
        page = extraire(WIKI, URL_WIKI, ENTETES_HTML)
        assert (page.url, page.titre, page.publie, page.modifie) == (
            URL_WIKI,
            "Premier ministre du Canada — Wikipédia",
            "2002-11-24",
            "2026-08-14",
        )
        lignes = page.texte.splitlines()
        assert lignes[:3] == [
            "Premier ministre du Canada",
            "Premier ministre du Canada",
            "Titulaire actuel | Mark Carney | depuis le 14 mars 2025",
        ], "le h1, la légende de l'infobox, puis sa première ligne"

    def test_un_document_vide_ne_leve_pas(self):
        page = extraire("", "https://example.com/")
        assert (page.url, page.titre, page.publie, page.modifie, page.texte) == (
            "https://example.com/",
            "",
            "",
            "",
            "",
        )

    def test_trois_cents_niveaux_ne_perdent_pas_la_suite(self):
        """21/09 : au-delà de 256 niveaux, libxml2 s'arrêtait et « Après »,
        un <p> ordinaire placé APRÈS le sous-arbre profond, disparaissait
        en silence, en succès."""
        html = (
            "<main><p>Avant.</p>"
            + "<div>" * 300
            + "Profond."
            + "</div>" * 300
            + "<p>Après.</p></main>"
        )
        assert texte_de(zone_principale(_doc(html))) == "Avant.\nProfond.\nAprès.", (
            "rien ne doit se perdre après un sous-arbre de 300 niveaux"
        )

    def test_une_page_trop_imbriquee_est_refusee_pas_amputee(self):
        """§5 : au-delà de la borne de libxml2 (2 048 niveaux), rendre ce
        qui a été lu ferait passer une page amputée pour la page."""
        html = (
            "<main><p>Avant.</p>" + "<div>" * 3000 + "x" + "</div>" * 3000 + "</main>"
        )
        with pytest.raises(web_read.PageIllisible, match="trop imbriqué"):
            extraire(html, "https://example.com/")


def _page_longue(phrase: str, position: int = 10_000) -> Page:
    """Un texte de 20 000 caractères de remplissage, la phrase visée loin
    après le début."""
    bourre = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 400)[
        :position
    ]
    texte = bourre + "\n" + phrase + "\n" + ("Sed do eiusmod tempor incididunt. " * 400)
    return Page("https://example.com/long", "Longue page", "", "", texte[:20_000])


class TestComposer:
    """Ce que le modèle lit : jamais plus que la limite, et « coupé » dit
    seulement quand quelque chose l'est (§5)."""

    def test_l_en_tete_porte_numero_domaine_et_dates(self):
        page = extraire(WIKI, URL_WIKI, ENTETES_HTML)
        lignes = composer(page).splitlines()
        assert lignes[0] == (
            "[1] Premier ministre du Canada — Wikipédia — fr.wikipedia.org"
            " · publié 2002-11-24 · modifié 2026-08-14"
        )
        assert lignes[1] == f"Source: {URL_WIKI}"
        assert lignes[2].startswith("Début : ")

    def test_le_focus_fait_remonter_le_passage(self):
        page = extraire(WIKI, URL_WIKI, ENTETES_HTML)
        contenu = composer(page, "qui est le premier ministre actuel")
        assert "Mark Carney, le premier ministre actuel" in contenu

    def test_le_focus_va_chercher_loin_dans_le_texte(self):
        phrase = (
            "Mark Carney, le premier ministre actuel, a prêté serment le 14 mars 2025."
        )
        page = _page_longue(phrase)
        avec = composer(page, "qui est le premier ministre actuel")
        sans = composer(page)
        assert phrase in avec, (
            "le passage est à 10 000 caractères : seul le focus l'atteint"
        )
        assert phrase not in sans, (
            "sans focus, le début s'étend et s'arrête à la limite"
        )
        assert "Passages : " in avec
        assert "Passages" not in sans

    def test_la_limite_est_respectee_et_la_coupe_annoncee(self):
        page = _page_longue("Le passage cherché est ici.")
        for focus in ("", "passage cherché"):
            contenu = composer(page, focus)
            assert len(contenu) <= LIMITE_CARACTERES, "agentic_stream tronque à 4 000"
            assert contenu.endswith("[… texte coupé]")

    def test_une_limite_explicite_est_respectee(self):
        page = _page_longue("Le passage cherché est ici.")
        contenu = composer(page, "passage cherché", limite=800)
        assert len(contenu) <= 800
        assert contenu.endswith("[… texte coupé]")

    def test_la_coupe_n_est_pas_annoncee_quand_tout_est_rendu(self):
        """21/09 : 1 242 caractères rendus en entier (début 1 200 + un passage
        jusqu'à la fin) finissaient par « [… texte coupé] » — dire coupé ce
        qui ne l'est pas, c'est faire semblant (§5)."""
        texte = ("Mot " * 300).strip() + "\nLa phrase cherchée est ici, tout à la fin."
        page = Page("https://example.com/", "Titre", "", "", texte)
        contenu = composer(page, "phrase cherchée")
        assert "Passages : " in contenu, "la phrase est après le début : un passage"
        assert contenu.endswith("tout à la fin."), "rien n'a été omis"
        assert "[… texte coupé]" not in contenu

    def test_la_coupe_est_annoncee_quand_un_trou_reste_apres_le_passage(self):
        texte = (
            ("Mot " * 300).strip() + "\nLa phrase cherchée est ici.\n" + "Mot " * 300
        )
        page = Page("https://example.com/", "Titre", "", "", texte.strip())
        assert composer(page, "phrase cherchée").endswith("[… texte coupé]")

    def test_sans_focus_le_debut_s_etend(self):
        texte = "Mot " * 700  # 2 800 caractères, plus que TAILLE_DEBUT
        page = Page("https://example.com/", "Titre", "", "", texte.strip())
        contenu = composer(page)
        assert contenu.endswith(texte.strip()[-20:]), (
            "tout le texte tient : rien de coupé"
        )
        assert "[… texte coupé]" not in contenu
        assert len(contenu) > TAILLE_DEBUT

    def test_rien_de_date_ne_dit_rien(self):
        page = Page("https://example.com/a", "Titre", "", "", "Texte.")
        contenu = composer(page)
        assert "date inconnue" not in contenu
        assert "publié" not in contenu and "modifié" not in contenu
        assert contenu.startswith(
            "[1] Titre — example.com\nSource: https://example.com/a\n"
        )

    def test_une_seule_date_est_annoncee_seule(self):
        page = Page("https://example.com/a", "Titre", "", "2026-09-02", "Texte.")
        assert (
            composer(page).splitlines()[0]
            == "[1] Titre — example.com · modifié 2026-09-02"
        )

    def test_un_focus_de_mots_vides_ne_fait_pas_de_passages(self):
        page = _page_longue("Le passage cherché est ici.")
        assert "Passages" not in composer(page, "qui est dans the what")

    def test_les_mots_du_focus_ignorent_accents_et_casse(self):
        page = _page_longue("Il a PRÊTÉ serment.")
        assert "PRÊTÉ serment" in composer(page, "prete")

    def test_sans_titre_l_url_tient_lieu_de_nom(self):
        page = Page("https://example.com/robots.txt", "", "", "", "User-agent: *")
        assert composer(page).startswith(
            "[1] https://example.com/robots.txt — example.com"
        )

    def test_le_passage_n_est_pas_repete_depuis_le_debut(self):
        page = extraire(WIKI, URL_WIKI, ENTETES_HTML)
        contenu = composer(page, "titulaire")
        assert contenu.count("Titulaire actuel | Mark Carney") == 1

    @pytest.mark.parametrize("longueur", [300, 3500, 5000])
    def test_un_titre_demesure_ne_fait_pas_deborder(self, longueur):
        """21/09 : un <title> de 5 000 caractères faisait sortir composer() à
        5 049 — agentic_stream aurait coupé à 4 000, au milieu."""
        page = _page_longue("Le passage cherché est ici.")
        page = Page(page.url, "t" * longueur, "", "", page.texte)
        for focus in ("", "passage cherché"):
            contenu = composer(page, focus)
            assert len(contenu) <= LIMITE_CARACTERES, "la limite est une promesse"
            assert "Début : " in contenu, "le titre borné laisse la place au texte"

    @pytest.mark.parametrize("limite", [20, 60, 120, 400, 800])
    def test_une_limite_minuscule_est_tenue(self, limite):
        page = _page_longue("Le passage cherché est ici.")
        assert len(composer(page, "passage cherché", limite=limite)) <= limite


@pytest.fixture
def telechargement(monkeypatch):
    """Remplace le téléchargement : (url, statut, type, octets, entêtes)."""

    def poser(
        octets: bytes = b"",
        statut: int = 200,
        type_mime: str = "text/html",
        url: str = URL_WIKI,
        entetes: dict[str, str] | None = None,
        erreur: Exception | None = None,
    ):
        appels: list[str] = []

        def faux(u: str) -> web_read._Telechargement:
            appels.append(u)
            if erreur is not None:
                raise erreur
            return web_read._Telechargement(
                url, statut, type_mime, octets, entetes or {"content-type": type_mime}
            )

        monkeypatch.setattr(web_read, "_telecharger", faux)
        return appels

    return poser


def _ssrf_hors_ligne(url: str) -> str | None:
    """check_ssrf sans DNS : refuse une adresse IP littérale privée."""
    from urllib.parse import urlsplit

    hote = urlsplit(url).hostname or ""
    return f"URL resolves to private IP: {hote}" if is_private_ip(hote) else None


class _FauxHttpx:
    """httpx.stream remplacé : une liste de réponses, une par URL jointe.
    « morceaux » sont les octets BRUTS du fil (iter_raw), compressés ou non."""

    def __init__(self, reponses: dict[str, dict[str, Any]]):
        self.reponses = reponses
        self.jointes: list[str] = []
        self.corps_lus: list[str] = []

    @contextmanager
    def stream(self, methode: str, url: str, **options: Any):
        self.jointes.append(url)
        rep = self.reponses[url]
        lus = self.corps_lus

        class Reponse:
            status_code = rep.get("statut", 200)
            headers = rep.get("entetes", {"Content-Type": "text/html"})

            @staticmethod
            def iter_raw():
                lus.append(url)
                yield from rep.get("morceaux", [b"<p>ok</p>"])

        yield Reponse()


class _Horloge:
    """time.monotonic() qui avance d'un pas à chaque lecture."""

    def __init__(self, pas: float):
        self.pas = pas
        self.instant = 1000.0

    def monotonic(self) -> float:
        self.instant += self.pas
        return self.instant


class TestExecute:
    """§100 : jamais de faux SUCCESS — une page vide, refusée, coupée ou
    trop lente le dit, et le dit en français."""

    def test_le_succes_porte_le_contenu_et_les_sources(self, telechargement):
        telechargement(WIKI.encode("utf-8"))
        r = WebReadTool().execute(
            url=URL_WIKI, focus="qui est le premier ministre actuel"
        )
        assert r.success is True
        assert r.tool_name == "web_read"
        assert "Titulaire actuel | Mark Carney" in r.content
        assert "· modifié 2026-08-14" in r.content
        assert r.metadata["url"] == URL_WIKI
        assert r.metadata["title"] == "Premier ministre du Canada — Wikipédia"
        assert r.metadata["published"] == "2002-11-24"
        assert r.metadata["modified"] == "2026-08-14"
        assert r.metadata["chars"] == len(extraire(WIKI, URL_WIKI).texte)
        source = r.metadata["sources"][0]
        assert source["ref"] == 1, "agentic_stream renumérote d'après ce [1]"
        assert source["date"] == "2026-08-14", (
            "la date de la source est la modification"
        )
        assert source["sender"] == "fr.wikipedia.org"
        assert source["url"] == URL_WIKI

    def test_http_404(self, telechargement):
        telechargement(b"<p>Introuvable</p>", statut=404)
        r = WebReadTool().execute(url=URL_WIKI)
        assert r.success is False
        assert r.content == "Lecture impossible : HTTP 404"
        assert r.metadata == {"url": URL_WIKI, "status": 404}

    def test_un_pdf_est_refuse(self, telechargement):
        telechargement(b"%PDF-1.4", type_mime="application/pdf")
        r = WebReadTool().execute(url="https://example.com/doc.pdf")
        assert r.success is False
        assert r.content == "Cette page est un PDF, non lisible ici."

    def test_un_type_inconnu_est_refuse(self, telechargement):
        telechargement(b"\x89PNG", type_mime="image/png")
        r = WebReadTool().execute(url="https://example.com/a.png")
        assert r.success is False
        assert r.content == "Type non lisible : image/png"

    def test_un_type_non_lisible_n_est_pas_telecharge(self, monkeypatch):
        faux = _FauxHttpx(
            {
                "https://example.com/doc.pdf": {
                    "entetes": {"Content-Type": "application/pdf"},
                    "morceaux": [b"%PDF" * 100_000],
                }
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        lu = web_read._telecharger("https://example.com/doc.pdf")
        assert lu.type_mime == "application/pdf" and lu.octets == b""
        assert faux.corps_lus == [], "un PDF de 2 Mo ne se télécharge pas pour rien"

    def test_du_texte_brut_est_lu_tel_quel(self, telechargement):
        telechargement(
            b"User-agent: *\nDisallow: /wiki/Special:\n",
            type_mime="text/plain",
            url="https://example.com/robots.txt",
            entetes={
                "content-type": "text/plain",
                "last-modified": "Thu, 14 Aug 2026 13:27:33 GMT",
            },
        )
        r = WebReadTool().execute(url="https://example.com/robots.txt")
        assert r.success is True
        assert "Disallow: /wiki/Special:" in r.content
        assert "· modifié 2026-08-14" in r.content
        assert r.metadata["title"] == ""

    @pytest.mark.parametrize(
        ("octets", "type_mime"),
        [
            pytest.param(
                b"<html><head><title>SPA</title></head><body></body></html>",
                "text/html",
                id="corps vide",
            ),
            pytest.param(
                b'<html><body><div id="root"></div><script>app()</script>'
                b"</body></html>",
                "text/html",
                id="SPA : div#root vide + script",
            ),
            pytest.param(b"\x00\x00\x00", "text/html", id="octets nuls"),
            pytest.param(b"", "text/plain", id="texte brut vide"),
        ],
    )
    def test_une_page_sans_texte_ne_reussit_pas(
        self, telechargement, octets, type_mime
    ):
        """21/09 : « Début : » vide rendu en SUCCÈS ; agentic_stream comptait
        la page comme une vérification faite et posait une pastille [N] vers
        une source qui ne dit rien — un faux SUCCESS (§100)."""
        telechargement(octets, type_mime=type_mime, url="https://example.com/p")
        r = WebReadTool().execute(url="https://example.com/p")
        assert r.success is False, "une page vide n'est pas une page lue (§100)"
        assert r.content == "Lecture impossible : page sans texte lisible"
        assert "sources" not in r.metadata, "pas de pastille vers une source muette"

    def test_une_adresse_interne_est_refusee_sans_appel_reseau(self, monkeypatch):
        """Rien ne joint 127.0.0.1, 10.x, 169.254.x ni .local : check_ssrf
        parle AVANT httpx, et son verdict est rendu au modèle."""

        def jamais(*args, **kwargs):
            raise AssertionError("aucun appel réseau ne doit partir")

        monkeypatch.setattr(httpx, "stream", jamais)
        r = WebReadTool().execute(url="http://127.0.0.1/")
        assert r.success is False, "une adresse interne n'est jamais lue"
        assert (
            r.content.startswith("Adresse refusée : ") and "127.0.0.1" in r.content
        ), "le message de check_ssrf est rendu, en français, sans le cacher"

    def test_telecharger_refuse_avant_tout_appel(self, monkeypatch):
        def jamais(*args, **kwargs):
            raise AssertionError("aucun appel réseau ne doit partir")

        monkeypatch.setattr(httpx, "stream", jamais)
        with pytest.raises(web_read._Refus):
            web_read._telecharger("http://169.254.169.254/latest/meta-data/")

    def test_une_redirection_vers_une_adresse_interne_est_refusee(self, monkeypatch):
        faux = _FauxHttpx(
            {
                "https://example.com/": {
                    "statut": 302,
                    "entetes": {"Location": "http://127.0.0.1:8000/admin"},
                },
                "http://127.0.0.1:8000/admin": {"morceaux": [b"<p>secret</p>"]},
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/")
        assert r.success is False
        assert "127.0.0.1" in r.content
        assert faux.jointes == ["https://example.com/"], (
            "l'adresse interne n'est jamais jointe"
        )

    def test_une_redirection_relative_est_suivie(self, monkeypatch):
        faux = _FauxHttpx(
            {
                "https://example.com/a": {"statut": 301, "entetes": {"location": "/b"}},
                "https://example.com/b": {
                    "entetes": {"Content-Type": "text/html; charset=utf-8"},
                    "morceaux": [b"<main><p>Page B.</p></main>"],
                },
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/a")
        assert r.success is True
        assert r.metadata["url"] == "https://example.com/b", "l'URL finale est rendue"
        assert "Page B." in r.content

    def test_une_page_de_trois_mo_est_coupee_sans_lever(self, monkeypatch):
        morceau = b"<p>" + b"x" * 65_530 + b"</p>"
        total = 3_000_000 // len(morceau) + 1
        servis: list[int] = []

        def morceaux():
            for i in range(total):
                servis.append(i)
                yield morceau

        faux = _FauxHttpx({"https://example.com/gros": {"morceaux": morceaux()}})
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        lu = web_read._telecharger("https://example.com/gros")
        assert len(lu.octets) == TAILLE_MAX_OCTETS
        assert len(servis) < total, (
            "la lecture s'arrête au plafond, elle ne charge pas tout"
        )
        # Un générateur NEUF : le premier est épuisé (21/09, ce test passait
        # avec un corps vide parce qu'une page vide était un succès).
        faux = _FauxHttpx({"https://example.com/gros": {"morceaux": morceaux()}})
        monkeypatch.setattr(httpx, "stream", faux.stream)
        r = WebReadTool().execute(url="https://example.com/gros")
        assert r.success is True, "un HTML coupé se lit quand même"
        assert r.metadata["chars"] > TAILLE_MAX_OCTETS * 0.9

    def test_un_gzip_est_decompresse_ici(self, monkeypatch):
        html = "<main><p>Élève à Québec, page compressée.</p></main>".encode()
        faux = _FauxHttpx(
            {
                "https://example.com/gz": {
                    "entetes": {
                        "Content-Type": "text/html; charset=utf-8",
                        "Content-Encoding": "gzip",
                    },
                    "morceaux": [gzip.compress(html)],
                }
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/gz")
        assert r.success is True and "Élève à Québec, page compressée." in r.content

    @pytest.mark.parametrize(
        ("wbits", "nom"),
        [
            (zlib.MAX_WBITS, "deflate zlib (RFC 1950)"),
            (-zlib.MAX_WBITS, "deflate nu (IIS)"),
        ],
    )
    def test_les_deux_deflate_sont_lus(self, monkeypatch, wbits, nom):
        c = zlib.compressobj(wbits=wbits)
        brut = c.compress(b"<main><p>Page en deflate.</p></main>") + c.flush()
        faux = _FauxHttpx(
            {
                "https://example.com/df": {
                    "entetes": {
                        "Content-Type": "text/html",
                        "Content-Encoding": "deflate",
                    },
                    "morceaux": [brut],
                }
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/df")
        assert "Page en deflate." in r.content, nom

    def test_une_bombe_gzip_ne_materialise_jamais_plus_que_le_plafond(
        self, monkeypatch
    ):
        """21/09 : iter_bytes() décompressait chaque morceau brut en entier
        avant la borne — 64 Ko d'une bombe (1 Go de zéros pour 972 Ko)
        livraient 67 Mo d'un coup, +131 Mo de RSS."""
        bombe = gzip.compress(b"\0" * 20_000_000)  # 20 Mo → ~20 Ko, un seul morceau
        assert len(bombe) < 65_536
        tailles: list[int] = []
        vrai = web_read._decompresseur

        class Espion:
            def __init__(self, encodage, premier):
                self.vrai = vrai(encodage, premier)

            def decompress(self, donnees, max_length=0):
                sortie = self.vrai.decompress(donnees, max_length)
                tailles.append(len(sortie))
                return sortie

        monkeypatch.setattr(web_read, "_decompresseur", Espion)
        faux = _FauxHttpx(
            {
                "https://example.com/bombe": {
                    "entetes": {
                        "Content-Type": "text/html",
                        "Content-Encoding": "gzip",
                    },
                    "morceaux": [bombe],
                }
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        lu = web_read._telecharger("https://example.com/bombe")
        assert len(lu.octets) == TAILLE_MAX_OCTETS
        assert tailles and max(tailles) <= TAILLE_MAX_OCTETS, (
            "aucun appel ne matérialise plus que le plafond"
        )

    def test_un_encodage_inconnu_est_refuse(self, monkeypatch):
        faux = _FauxHttpx(
            {
                "https://example.com/br": {
                    "entetes": {"Content-Type": "text/html", "Content-Encoding": "br"},
                    "morceaux": [b"\x1b\x2c\x00"],
                }
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/br")
        assert r.success is False
        assert r.content == "Lecture impossible : encodage br non pris en charge"

    def test_un_gzip_menteur_est_refuse_sans_trace(self, monkeypatch):
        faux = _FauxHttpx(
            {
                "https://example.com/faux-gz": {
                    "entetes": {
                        "Content-Type": "text/html",
                        "Content-Encoding": "gzip",
                    },
                    "morceaux": [b"<p>pas du gzip</p>"],
                }
            }
        )
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/faux-gz")
        assert r.success is False
        assert r.content == "Lecture impossible : contenu compressé illisible"

    def test_un_serveur_qui_goutte_est_arrete_a_l_echeance(self, monkeypatch):
        """21/09 : DELAI_S bornait chaque attente, pas le total — 100 Ko à
        2 Ko/s ont été lus 50 s dans un fil que l'exécuteur avait abandonné
        à 20 s. L'horloge est relue à chaque morceau."""
        horloge = _Horloge(pas=DELAI_S / 4)
        monkeypatch.setattr(web_read, "time", horloge)
        servis: list[int] = []

        def goutte():
            for i in range(1000):
                servis.append(i)
                yield b"<p>x</p>"

        faux = _FauxHttpx({"https://example.com/lent": {"morceaux": goutte()}})
        monkeypatch.setattr(httpx, "stream", faux.stream)
        monkeypatch.setattr(web_read, "check_ssrf", _ssrf_hors_ligne)
        r = WebReadTool().execute(url="https://example.com/lent")
        assert r.success is False
        assert r.content == "Lecture impossible : trop lent"
        assert len(servis) < 10, "la lecture s'arrête à l'échéance, pas au bout"

    def test_un_timeout_rend_la_classe_sans_trace(self, telechargement):
        telechargement(erreur=httpx.ReadTimeout("trop long"))
        r = WebReadTool().execute(url=URL_WIKI)
        assert r.success is False
        assert r.content == "Lecture impossible : ReadTimeout"
        assert "Traceback" not in r.content and "trop long" not in r.content

    def test_url_vide(self):
        r = WebReadTool().execute(url="")
        assert r.success is False and r.content == "Aucune URL fournie."
        assert WebReadTool().execute().content == "Aucune URL fournie."

    def test_url_ftp(self):
        r = WebReadTool().execute(url="ftp://example.com/fichier")
        assert r.success is False
        assert r.content == "L'URL doit commencer par http:// ou https://."

    def test_l_url_finale_apres_redirection_est_celle_des_metadata(
        self, telechargement
    ):
        telechargement(WIKI.encode("utf-8"), url=URL_WIKI + "?x=1")
        r = WebReadTool().execute(url=URL_WIKI)
        assert r.metadata["url"] == URL_WIKI + "?x=1"
        assert r.metadata["sources"][0]["url"] == URL_WIKI + "?x=1"

    def test_le_charset_de_l_entete_est_respecte(self, telechargement):
        html = "<html><body><main><p>Élève à Québec.</p></main></body></html>"
        telechargement(
            html.encode("latin-1"),
            entetes={"content-type": "text/html; charset=iso-8859-1"},
        )
        r = WebReadTool().execute(url="https://example.com/latin")
        assert "Élève à Québec." in r.content

    @pytest.mark.parametrize(
        "charset", ["idna", "undefined", "base64", "x-truc", "zlib"]
    )
    def test_un_charset_exotique_ne_fait_pas_sortir_d_exception(
        self, telechargement, charset
    ):
        """21/09 : « charset=idna » sortait une UnicodeError brute de
        l'outil (« Unsupported error handling: replace ») — _decoder était
        appelé HORS du try et ne rattrapait que LookupError."""
        html = b"<html><body><main><p>Texte lisible.</p></main></body></html>"
        telechargement(html, entetes={"content-type": f"text/html; charset={charset}"})
        r = WebReadTool().execute(url="https://example.com/cs")
        assert r.success is True and "Texte lisible." in r.content, (
            "un charset qu'on ne sait pas lire est lu comme de l'UTF-8"
        )

    def test_une_page_trop_imbriquee_est_refusee_en_execute(self, telechargement):
        html = (
            "<main><p>Avant.</p>" + "<div>" * 3000 + "x" + "</div>" * 3000 + "</main>"
        )
        telechargement(html.encode())
        r = WebReadTool().execute(url="https://example.com/p")
        assert r.success is False
        assert r.content.startswith("Lecture impossible : HTML trop imbriqué")

    def test_tous_les_messages_sont_en_francais(self, telechargement):
        """21/09 : deux messages en anglais et sept en français dans le même
        outil — ce content est lu par le modèle et PRONONCÉ par la voix."""
        messages = [
            WebReadTool().execute(url="").content,
            WebReadTool().execute(url="ftp://x").content,
        ]
        telechargement(b"", statut=500)
        messages.append(WebReadTool().execute(url="https://example.com/").content)
        for message in messages:
            assert not any(mot in message for mot in ("No ", "must", "provided")), (
                message
            )


class TestEnregistrement:
    def test_le_module_enregistre_web_read(self):
        """Le conftest vide les registres avant chaque test : réimporter le
        module rejoue le décorateur, c'est lui qu'on vérifie."""
        importlib.reload(web_read)
        assert ToolRegistry.contains("web_read")
        assert ToolRegistry.get("web_read") is web_read.WebReadTool

    def test_tool_id_et_spec(self):
        outil = WebReadTool()
        assert outil.tool_id == "web_read"
        assert outil.is_local is False, "il lit le réseau : le mode local le refuse"
        assert outil.spec.name == "web_read"
        assert outil.spec.category == "search"
        assert outil.spec.timeout_seconds == 20.0
        assert outil.spec.parameters["required"] == ["url"]

    def test_to_openai_function(self):
        fn = WebReadTool().to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "web_read"
        assert set(fn["function"]["parameters"]["properties"]) == {"url", "focus"}
        assert "web_search" in fn["function"]["description"], (
            "la description dit au modèle QUAND lire une page"
        )
