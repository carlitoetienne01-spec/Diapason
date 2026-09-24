"""Pages légales : rien ne sort sans être relevé, rien ne diverge.

`docs/development/compte-chiffre.md` §5 et étape 6, écrits le 24/09/2026.
Quatre échecs que ces tests existent pour empêcher :

- une politique de confidentialité qui promet un lieu, une durée ou une
  adresse que personne n'a relevés (la conception précédente comptait sur
  un instantané Hostinger qu'elle n'avait jamais vu) ;
- `PRIVACY.md` et `/confidentialite` qui disent deux choses différentes ;
- une page légale mise en ligne par `deployer-site.sh`, qui publie tout
  `accueil/` à chaque déploiement de la documentation, des semaines avant
  l'ouverture des comptes et à côté d'un accueil qui dit « pas de serveur » ;
- une page qui résume le §2.9 au lieu de le reprendre, et perd en route ce
  que le serveur voit quand même.

Aucun test ne contacte un serveur : `ssh`, `rsync` et `curl` sont remplacés
par des doublures qui notent leurs arguments.
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pathspec
import pytest

RACINE = Path(__file__).resolve().parents[1]
SPEC = RACINE / "docs" / "development" / "compte-chiffre.md"
ACCUEIL = RACINE / "deploy" / "vps" / "accueil"
DRAPEAU = ACCUEIL / ".publier-legal"

_compteur = iter(range(10_000))


def _generateur(racine: Path = RACINE):
    """Le module du générateur, chargé depuis `racine` (le vrai dépôt ou une copie)."""
    chemin = racine / "scripts" / "gen_privacy_md.py"
    nom = f"gen_privacy_md_{next(_compteur)}"
    spec = importlib.util.spec_from_file_location(nom, chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


GEN = _generateur()


def _normaliser(texte: str) -> str:
    texte = texte.replace("\u00a0", " ").replace("\u202f", " ").replace("’", "'")
    return re.sub(r"\s+", " ", texte).strip()


def _texte_de_page(page: str) -> str:
    """Le texte lu par un visiteur : balises ôtées sans espace ajoutée."""
    return _normaliser(html.unescape(re.sub(r"<[^>]+>", "", page)))


def _normaliser_md(ligne: str) -> str:
    ligne = ligne.replace("**", "").replace("`", "")
    # Les renvois internes de la conception (« (§3.9, D11) ») n'ont pas de
    # sens pour un visiteur : la page les omet.
    ligne = re.sub(r"\s*\((?:§|D\d)[^)]*\)", "", ligne)
    return _normaliser(ligne).rstrip(" ;:.")


def _page(nom: str) -> str:
    return (ACCUEIL / nom).read_text(encoding="utf-8")


def _puces_quand_meme() -> list[str]:
    texte = SPEC.read_text(encoding="utf-8")
    bloc = texte[texte.index("**Quand même**") : texte.index("### 2.10")]
    return [_normaliser_md(m.group(1)) for m in re.finditer(r"^\s*- (.+)$", bloc, re.M)]


# Les phrases que la spécification donne entre guillemets et que les pages
# doivent porter mot pour mot. Chacune est aussi cherchée dans la
# spécification : si Carlito la réécrit là-bas, ce test le dit ici.
#
# 24/09/2026 : la phrase du §3.12 (« local_only bloque toute sortie, sauf
# l'envoi de données déjà chiffrées… ») en est RETIRÉE. Mot pour mot, elle
# contredisait la page même : la vérification des mises à jour, le premier
# téléchargement du modèle et la recherche YouTube passent le verrou, et le
# trafic du compte porte aussi l'adresse, authKey et les codes.
# TestHonnetete la remplace ; l'écart est à reporter dans la spécification.
PHRASES_CONFIDENTIALITE = (
    # §5, point 4 (A2′)
    "Une copie du seul fichier de base ne permet pas de deviner les mots de "
    "passe. Une copie de toute la machine, par exemple une sauvegarde de "
    "l'hébergeur, le permet, au prix d'un calcul coûteux par essai.",
    # §2.9, dernière puce
    "Un serveur hostile peut donc se connecter au compte, sans pouvoir le déchiffrer.",
)
PHRASES_CONDITIONS = (
    "le service est hébergé chez un tiers, qui peut l'interrompre sans préavis ; "
    "vos données restent sur vos appareils.",
    "la perte du serveur efface les comptes, pas les données des appareils",
    "la synchronisation n'est pas une sauvegarde",
)

# Les douze points que §5 exige de /confidentialite, et la section qui porte
# chacun. Un point sans section est un point que la page a oublié.
POINTS_DU_5 = {
    1: "en-bref",
    2: "compte",
    3: "oubli",
    4: "copie-de-la-machine",
    5: "restauration",
    6: "sous-traitants",
    7: "transferts",
    8: "durees",
    9: "verrou-local",
    10: "droits",
    11: "cadre",
    12: "cadre",
}

# Des valeurs de test, visiblement fictives : elles ne sortent jamais du
# dossier temporaire.
HEBERGEUR_REMPLI = {
    "hebergeur": {
        "nom": "Hébergeur d'essai",
        "lieuServeur": "Ville d'essai, Pays d'essai",
        "tiersAdministrateur": "Personne d'autre n'administre la machine d'essai.",
    },
    "sauvegardes": {
        "frequence": "une fois par semaine",
        "conservation": "deux semaines",
        "lieu": "Ville d'essai",
    },
    "instantane": {"description": "Aucun instantané n'existe sur la machine d'essai."},
    "copieHorsVps": {
        "description": "Une copie d'essai part chaque jour vers une machine d'essai."
    },
    "resend": {
        "conservation": "trente jours d'essai",
        "suiviVerifie": "Suivi désactivé, vérifié par un test le 1er janvier 2099.",
    },
    "contact": {
        "adresse": "contact@exemple.invalid",
        "responsable": "La personne d'essai",
    },
    "conditions": {"ageMinimum": 16, "droitApplicable": "le droit d'essai"},
    "publication": {
        "origineSite": "https://exemple.invalid",
        "enVigueurLe": "1er janvier 2099",
        "validationJuridique": "relu par un juriste d'essai",
    },
    "releve": {"le": "1er janvier 2099", "par": "un test"},
}


def _copier_depot(cible: Path) -> Path:
    """Les seuls fichiers que le générateur et le déployeur lisent, copiés."""
    for relatif in (
        "deploy/vps/deployer-site.sh",
        "deploy/vps/accueil/index.html",
        "deploy/vps/accueil/accueil.css",
        "deploy/vps/accueil/confidentialite.html",
        "deploy/vps/accueil/conditions.html",
        "deploy/vps/comptes/hebergeur.json",
        "deploy/vps/nginx/zz-diapason.conf",
        "scripts/gen_privacy_md.py",
        "PRIVACY.md",
        "mkdocs.yml",
        "mkdocs.api.yml",
        *(
            str(css.relative_to(RACINE))
            for css in sorted((RACINE / "docs" / "stylesheets").glob("*.css"))
        ),
    ):
        destination = cible / relatif
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RACINE / relatif, destination)
    (cible / "deploy" / "vps" / "accueil" / ".publier-legal").unlink(missing_ok=True)
    return cible


def _remplir_hebergeur(racine: Path, **surcharges: dict) -> None:
    donnees = json.loads(json.dumps(HEBERGEUR_REMPLI))
    for section, valeurs in surcharges.items():
        donnees[section].update(valeurs)
    (racine / "deploy/vps/comptes/hebergeur.json").write_text(
        json.dumps(donnees, ensure_ascii=False), encoding="utf-8"
    )


def _generer(racine: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(racine / "scripts" / "gen_privacy_md.py"), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _accueil_corrige(racine: Path) -> None:
    """Ce que l'étape 13 fera à l'accueil : ni Google Fonts, ni « pas de
    serveur », et un pied qui mène aux deux pages."""
    index = racine / "deploy/vps/accueil/index.html"
    lignes = [
        ligne
        for ligne in index.read_text(encoding="utf-8").splitlines(keepends=True)
        if "fonts.g" not in ligne
    ]
    texte = "".join(lignes)
    for phrase in GEN.FAUSSES_PROMESSES_ACCUEIL:
        texte = re.sub(re.escape(phrase), "[phrase réécrite]", texte, flags=re.I)
    texte = texte.replace(
        "</footer>",
        '<p><a href="/confidentialite">Confidentialité</a> '
        '<a href="/conditions">Conditions</a></p>\n</footer>',
    )
    index.write_text(texte, encoding="utf-8")


def _remplacer(chemin: Path, avant: str, apres: str) -> None:
    texte = chemin.read_text(encoding="utf-8")
    assert avant in texte, f"{chemin.name} ne porte plus « {avant} »"
    chemin.write_text(texte.replace(avant, apres), encoding="utf-8")


def _nginx_corrige(racine: Path) -> None:
    """Ce que D11 exige de zz-diapason.conf : un format sans IP ni requête,
    un journal d'erreurs à crit, dans CHAQUE bloc server."""
    conf = racine / "deploy/vps/nginx/zz-diapason.conf"
    _remplacer(
        conf,
        "access_log /var/log/nginx/diapason.access.log;",
        "access_log /var/log/nginx/diapason.access.log diapason_api;",
    )
    _remplacer(
        conf,
        "error_log  /var/log/nginx/diapason.error.log;",
        "error_log  /var/log/nginx/diapason.error.log crit;",
    )
    _remplacer(
        conf,
        "    listen [::]:80;\n",
        "    listen [::]:80;\n"
        "    access_log /var/log/nginx/diapason.access.log diapason_api;\n"
        "    error_log  /var/log/nginx/diapason.error.log crit;\n",
    )
    conf.write_text(
        'log_format diapason_api \'[$time_local] "$request_method $uri" $status '
        "$body_bytes_sent $request_time';\n" + conf.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _guides_sans_tiers(racine: Path) -> None:
    """Les guides sans Google Fonts ni jsDelivr : polices du système, pas de
    DocSearch distant."""
    mkdocs = racine / "mkdocs.yml"
    _remplacer(mkdocs, "  font:\n    text: VT323\n    code: VT323\n", "  font: false\n")
    mkdocs.write_text(
        "".join(
            ligne
            for ligne in mkdocs.read_text(encoding="utf-8").splitlines(keepends=True)
            if "cdn.jsdelivr" not in ligne
        ),
        encoding="utf-8",
    )
    _remplacer(
        racine / "mkdocs.api.yml",
        "  name: material\n",
        "  name: material\n  font: false\n",
    )
    for css in (racine / "docs").rglob("*.css"):
        css.write_text(
            re.sub(
                r"(?m)^@import url\([^)]*\);?\n?", "", css.read_text(encoding="utf-8")
            ),
            encoding="utf-8",
        )


def _publiable(racine: Path) -> None:
    """Une copie du dépôt dans l'état exact que l'étape 13 doit atteindre."""
    _remplir_hebergeur(racine)
    (racine / "deploy/vps/accueil/.publier-legal").write_text("", encoding="utf-8")
    resultat = _generer(racine)
    assert resultat.returncode == 0, resultat.stderr
    _accueil_corrige(racine)
    _nginx_corrige(racine)
    _guides_sans_tiers(racine)
    _remplacer(racine / "mkdocs.yml", "  /confidentialite.md\n", "")


class TestHebergeurJson:
    """§5 « Tests » : les valeurs Hostinger viennent de hebergeur.json, et un
    `null` y interdit la sortie de la page."""

    def test_le_fichier_porte_exactement_les_champs_attendus(self):
        """Un champ mal orthographié resterait `null` pour toujours sans que
        rien ne le dise : la page le citerait sous son vrai nom, vide."""
        donnees = json.loads(GEN.chemins()["hebergeur"].read_text(encoding="utf-8"))
        assert set(GEN._aplatir(donnees)) == set(GEN.CHAMPS), (
            "hebergeur.json et CHAMPS (scripts/gen_privacy_md.py) "
            "ne nomment pas les mêmes faits"
        )
        _, manquants = GEN.lire_hebergeur()
        assert not [m for m in manquants if "champ inconnu" in m], (
            f"lire_hebergeur voit des champs inconnus : {manquants}"
        )

    def test_un_champ_inconnu_fait_refuser_la_generation(self, tmp_path):
        """Une faute de frappe (« lieuServuer ») laisserait le vrai champ
        `null` et ferait croire le fait relevé ; elle est nommée et refusée."""
        racine = _copier_depot(tmp_path)
        _remplir_hebergeur(racine, sauvegardes={"lieuServuer": "Ville d'essai"})
        resultat = _generer(racine)
        assert resultat.returncode == 1, "un champ inconnu a été accepté"
        assert "sauvegardes.lieuServuer : champ inconnu" in resultat.stderr, (
            f"le refus doit nommer le champ inconnu : {resultat.stderr}"
        )

    def test_la_page_dit_ce_qui_manque_au_lieu_de_l_inventer(self):
        """§5 et consigne D3/D17 : un fait non relevé apparaît dans la page
        comme « [à fournir : …] », jamais comme une valeur plausible."""
        _, manquants = GEN.lire_hebergeur()
        cles_manquantes = {m.split(" : ", 1)[0] for m in manquants}
        pages = _page("confidentialite.html") + _page("conditions.html")
        for m in GEN._CRENEAU.finditer(pages):
            if m.group("cle") in cles_manquantes:
                assert m.group("contenu") == html.escape(
                    GEN.marqueur(m.group("cle")), quote=False
                ), (
                    f"le créneau {m.group('cle')} porte une valeur "
                    "alors que hebergeur.json "
                    f"ne l'a pas relevée : {m.group('contenu')!r}"
                )

    def test_un_fait_non_releve_fait_refuser_la_generation(self, tmp_path):
        """« La page REFUSE de se générer tant qu'il manque » : rien n'est
        écrit, pas même les créneaux déjà connus."""
        racine = _copier_depot(tmp_path)
        _remplir_hebergeur(racine, hebergeur={"lieuServeur": None})
        avant = {n: (racine / "deploy/vps/accueil" / n).read_bytes() for n in GEN.PAGES}
        resultat = _generer(racine)
        assert resultat.returncode == 1, (
            "le générateur doit refuser un hebergeur.json incomplet"
        )
        assert "hebergeur.lieuServeur" in resultat.stderr, (
            "le refus doit nommer le champ manquant"
        )
        for nom, octets in avant.items():
            assert (racine / "deploy/vps/accueil" / nom).read_bytes() == octets, (
                f"{nom} a été réécrit malgré le refus"
            )

    @pytest.mark.parametrize(
        ("section", "valeurs"),
        [
            ("sauvegardes", {"lieu": "à confirmer"}),
            # 24/09/2026 : les six suivants sortaient en code 0 et étaient
            # écrits dans la page — « à relever » est le mot même du §5.
            ("sauvegardes", {"lieu": "Hostinger (à relever)"}),
            ("sauvegardes", {"lieu": "N/A"}),
            ("sauvegardes", {"lieu": "?"}),
            ("sauvegardes", {"lieu": "-"}),
            ("sauvegardes", {"lieu": "null"}),
            ("sauvegardes", {"lieu": "None"}),
            ("sauvegardes", {"lieu": ""}),
            ("sauvegardes", {"lieu": "   "}),
            ("resend", {"conservation": "TBD"}),
            ("contact", {"adresse": "pas une adresse"}),
            ("publication", {"origineSite": "https://exemple.invalid/"}),
            ("conditions", {"ageMinimum": 0}),
        ],
    )
    def test_un_bouche_trou_ne_compte_pas_pour_une_valeur(
        self, tmp_path, section, valeurs
    ):
        """Remplir un champ de « à confirmer » pour faire taire le refus
        publierait « à confirmer » comme lieu des sauvegardes."""
        racine = _copier_depot(tmp_path)
        _remplir_hebergeur(racine, **{section: valeurs})
        cle = f"{section}.{next(iter(valeurs))}"
        resultat = _generer(racine)
        assert resultat.returncode == 1, f"{cle} = {valeurs} a été accepté"
        assert cle in resultat.stderr, f"le refus doit nommer {cle} : {resultat.stderr}"
        page = (racine / "deploy/vps/accueil/confidentialite.html").read_text(
            encoding="utf-8"
        )
        assert GEN.MARQUEUR in page, "la page a été écrite malgré le refus"

    @pytest.mark.parametrize(
        "valeur", ["Boston, États-Unis", "Nouvelle-Écosse", "une fois par semaine"]
    )
    def test_une_vraie_valeur_n_est_pas_prise_pour_un_bouche_trou(
        self, tmp_path, valeur
    ):
        """Le filtre des bouche-trous cherche des mots entiers : un vrai lieu
        ne doit pas être refusé parce qu'il contiendrait « nan » ou « none »."""
        racine = _copier_depot(tmp_path)
        _remplir_hebergeur(racine, sauvegardes={"lieu": valeur})
        _, manquants = _generateur(racine).lire_hebergeur(racine)
        assert manquants == [], f"« {valeur} » refusé à tort : {manquants}"


class TestPages:
    """§5 : ce que /confidentialite et /conditions disent, et comment."""

    def test_aucune_ressource_distante(self):
        """§5 « Tests » : aucune référence à fonts.googleapis. Plus
        largement, lire la politique ne doit annoncer le lecteur à personne."""
        for nom in GEN.PAGES:
            page = _page(nom)
            for police in ("fonts.googleapis", "fonts.gstatic"):
                assert police not in page, f"{nom} charge {police}"
            distantes = re.findall(
                r'<(?:link|script|img|iframe)[^>]+(?:href|src)="(https?:[^"]+)"', page
            )
            assert not distantes, f"{nom} charge des ressources distantes : {distantes}"

    def test_les_pages_suivent_la_peau_du_site(self):
        """Une page légale qui ne ressemble pas au site passe pour un
        hameçon : même feuille, même langue, même barre que l'accueil."""
        for nom in GEN.PAGES:
            page = _page(nom)
            assert '<html lang="fr">' in page, f"{nom} doit être en français d'abord"
            assert '<link rel="stylesheet" href="accueil.css">' in page, (
                f"{nom} doit reprendre accueil.css"
            )
            assert '<header class="barre">' in page, (
                f"{nom} doit reprendre la barre de l'accueil"
            )
        styles = [
            re.search(r"<style>.*?</style>", _page(n), re.S).group(0) for n in GEN.PAGES
        ]
        assert styles[0] == styles[1], "les deux pages légales ont divergé de style"

    def test_les_pages_disent_ce_que_le_service_applique(self):
        """Anti-divergence : chaque durée, quota ou délai de la page est
        celui du tableau VALEURS_DU_SERVICE, et chaque trou porte son
        marqueur. Une page corrigée à la main sans le tableau est refusée."""
        valeurs, _ = GEN.valeurs_de_rendu()
        for nom in GEN.PAGES:
            page = _page(nom)
            assert GEN.rendre_page(page, valeurs) == page, (
                f"{nom} ne dit pas ce que le service applique. Corrige le <span "
                "data-valeur> à la main (le générateur refuse tant que hebergeur.json "
                "est incomplet), ou VALEURS_DU_SERVICE si c'est la page qui a raison."
            )

    def test_chaque_creneau_est_connu(self):
        """Un créneau dont la clé n'existe nulle part ne serait jamais rempli."""
        connus = set(GEN.CHAMPS) | set(GEN.VALEURS_DU_SERVICE)
        for nom in GEN.PAGES:
            inconnus = set(GEN.creneaux(_page(nom))) - connus
            assert not inconnus, f"{nom} porte des créneaux inconnus : {inconnus}"

    def test_le_paragraphe_2_9_est_repris_tel_quel(self):
        """§5 point 2 : « le §2.9 tel quel ». Un résumé perdrait la
        suppression visible à la taille, ou `globalSeq`."""
        texte = _texte_de_page(_page("confidentialite.html"))
        puces = _puces_quand_meme()
        assert len(puces) >= 20, (
            f"le §2.9 de la spécification n'a pas été lu ({len(puces)} puces)"
        )
        for puce in puces:
            assert puce in texte, (
                f"/confidentialite ne reprend pas le §2.9 : « {puce} »"
            )

    def test_les_phrases_imposees_sont_dites_mot_pour_mot(self):
        """§5 point 4 (A2′), §3.12 (`local_only`) et §5 /conditions donnent
        leur texte entre guillemets : il est repris tel quel, et la
        spécification le porte encore."""
        spec = _normaliser(
            SPEC.read_text(encoding="utf-8").replace("`", "").replace("**", "")
        )
        for nom, phrases in (
            ("confidentialite.html", PHRASES_CONFIDENTIALITE),
            ("conditions.html", PHRASES_CONDITIONS),
        ):
            texte = _texte_de_page(_page(nom)).lower()
            for phrase in phrases:
                assert phrase.lower() in spec.lower(), (
                    f"la spécification ne dit plus « {phrase} »"
                )
                assert phrase.lower() in texte, f"{nom} ne dit pas « {phrase} »"

    def test_les_douze_points_du_paragraphe_5_ont_leur_section(self):
        """§5 énumère douze choses que /confidentialite dit ; une section
        absente est un point oublié."""
        page = _page("confidentialite.html")
        for point, ancre in POINTS_DU_5.items():
            assert f'<section id="{ancre}">' in page, (
                f"point {point} du §5 : section #{ancre} absente"
            )

    def test_les_conditions_ne_promettent_aucun_preavis(self):
        """§5 /conditions : « préavis de 30 jours » ne peut pas être tenu tant
        que la machine et le domaine ne sont pas à Carlito (D3)."""
        texte = _texte_de_page(_page("conditions.html"))
        assert "préavis de" not in texte, (
            "les conditions promettent un préavis intenable"
        )
        assert "sans préavis" in texte, (
            "les conditions doivent dire l'interruption sans préavis"
        )
        assert GEN.VALEURS_DU_SERVICE["service.versionConditions"].isdigit(), (
            "termsVersion est un entier (§5)"
        )

    def test_rien_ne_prétend_que_la_telemetrie_est_absente(self):
        """§5 point 11 dit « aucune analytique » ; l'application a pourtant une
        télémétrie, désactivée par défaut. La page doit la nommer plutôt que
        la taire — §5 du cahier, ne jamais faire semblant."""
        texte = _texte_de_page(_page("confidentialite.html"))
        assert "télémétrie" in texte.lower(), (
            "la page tait la télémétrie de l'application"
        )


def _section(page: str, ancre: str) -> str:
    m = re.search(rf'<section id="{ancre}">(.*?)</section>', page, re.S)
    assert m, f"section #{ancre} absente"
    return _texte_de_page(m.group(1))


# Pour chaque point du §5 (et les trois puces « Jamais » du §2.9), les
# phrases qui le portent, dans la section qui le porte. 24/09/2026 : une
# section VIDE satisfaisait le test des douze points ; retirer la puce
# Resend, la puce Monarx ou tout le texte des transferts laissait la suite
# verte.
PHRASES_PAR_SECTION = {
    "en-bref": ("Le compte est facultatif. Sans compte, rien ne part",),
    "compte": (
        "votre mot de passe, votre clé de récupération, ni aucune des clés",
        "les titres, les messages, les images, le modèle employé",
        "les identifiants locaux, les noms de collection et les noms de vos appareils",
    ),
    "serveur-compromis": (
        "deviner votre mot de passe hors ligne",
        "S'il le devine, il lit tout ce que le compte garde",
        "couper le service, ou l'effacer",
        "voir tout ce qui est listé ci-dessus",
        "se connecter à votre compte",
        "cacher une suppression à un appareil qui ne l'a jamais vue",
        "simuler un retour en arrière",
    ),
    "oubli": (
        "votre clé de récupération, ou un autre de vos appareils resté déverrouillé",
        "rien ne s'efface de soi-même",
        "Quelqu'un qui contrôle votre boîte courriel pourrait le faire aussi",
    ),
    "restauration": ("un compte supprimé est supprimé de nouveau",),
    "sous-traitants": (
        "Resend, aux États-Unis",
        "Monarx",
        "La copie de la base hors du serveur",
        "GitHub voit alors votre adresse IP",
    ),
    "transferts": (
        "Resend, aux États-Unis",
        "y compris l'accès des autorités de ces pays",
        "tant que votre mot de passe n'est pas deviné",
    ),
    "durees": (
        "Si les copies récentes échouent, la dernière copie valide est gardée",
        "Le journal de sécurité du serveur",
        "un condensé de son préfixe (/24 ou /48)",
        "Chez Resend",
    ),
    "verrou-local": (
        "le trafic du compte, après que vous avez activé un compte",
        "la vérification des mises à jour",
        "le premier téléchargement du moteur et du modèle",
        "YouTube",
        "appareils appairés",
    ),
    "suppression": (
        "le journal de sécurité du serveur",
        "les compteurs de délais de connexion et d'envoi de courriels",
        "la copie de la base hors du serveur",
        "il faut d'abord réinitialiser le compte",
    ),
    "droits": (
        "nous répondons seulement à l'adresse du compte",
        "réinitialisez-le d'abord",
    ),
    "cadre": (
        "Aucune analytique, aucune publicité, aucune revente",
        "Loi 25",
        "LPRPDE",
        "RGPD",
    ),
}

# Des phrases que les contre-épreuves du 24/09/2026 ont trouvées fausses,
# chacune avec ce que le code fait vraiment. Aucune ne doit revenir.
PROMESSES_FAUSSES = {
    "Vos conversations, elles, restent illisibles.": (
        "un mot de passe deviné ouvre l'AMK, donc tout le chiffré"
    ),
    "n'obtiendrait pas : lire vos conversations": (
        "vrai seulement tant que le mot de passe n'est pas deviné"
    ),
    "aucune ne quitte l'appareil.": (
        "authKey, tirée du mot de passe, part à chaque connexion"
    ),
    "ne vous demandera jamais votre mot de passe ni votre clé de récupération.": (
        "l'application les demande ; seul le courriel ne le fait jamais"
    ),
    "bloque toute sortie": "mises à jour, modèle et YouTube passent le verrou",
    "qui ne sont pas des envois de Diapason": "la recherche YouTube en est un",
    "jamais écrite": "le préfixe /24 est écrit dans limites, sous un HMAC",
    "les journaux nginx, sans adresse IP": (
        "un journal d'erreurs à crit peut encore porter « client: <IP> »"
    ),
    "environ 15 jours, sans adresse IP": (
        "idem, et le journal d'erreurs général de la machine n'est pas à Diapason"
    ),
    "après 72 heures": "le délai n'efface rien : il faut reset/complete",
    "Le suivi des ouvertures et des clics est désactivé": "rien ne le vérifie",
}


class TestHonnetete:
    """§5 du cahier, ne jamais faire semblant : la politique ne promet que ce
    que le service, le site et nginx font vraiment."""

    @pytest.mark.parametrize("ancre", sorted(PHRASES_PAR_SECTION))
    def test_chaque_point_est_dit_dans_sa_section(self, ancre):
        """§5 points 1 à 12 et §2.9 « Jamais » : une section présente mais
        vidée de sa phrase est un point oublié."""
        texte = _section(_page("confidentialite.html"), ancre).lower()
        for phrase in PHRASES_PAR_SECTION[ancre]:
            assert _normaliser(phrase).lower() in texte, (
                f"#{ancre} ne dit plus « {phrase} »"
            )

    @pytest.mark.parametrize("phrase", sorted(PROMESSES_FAUSSES))
    def test_aucune_promesse_fausse_ne_revient(self, phrase):
        """Chaque phrase a été trouvée fausse face au code (voir la raison) :
        la réécrire ferait de nouveau mentir la page à ceux qui la lisent."""
        page = _texte_de_page(_page("confidentialite.html")).lower()
        assert _normaliser(phrase).lower() not in page, (
            f"/confidentialite dit de nouveau « {phrase} » — faux : "
            f"{PROMESSES_FAUSSES[phrase]}"
        )

    def test_les_conditions_ne_ferment_aucun_compte_sans_outil(self):
        """Aucune route ni aucun outil ne ferme un compte à la place de son
        titulaire : la clause promettait un pouvoir que personne n'a."""
        texte = _texte_de_page(_page("conditions.html")).lower()
        assert "peut être fermé" not in texte, (
            "les conditions promettent une fermeture que rien ne permet"
        )


class TestValeursDuService:
    """§5 « Tests » : « les durées sont importées des constantes du
    service ». VALEURS_DU_SERVICE est une recopie ; ce test la confronte au
    service, pour qu'une constante changée là-bas rougisse ici."""

    def test_chaque_valeur_promise_est_celle_du_service(self):
        from diapason_comptes import jetons, routes_identite, secrets_serveur
        from diapason_comptes.base import JOUR_MS

        heure_ms = 3_600_000
        for constante, unite in (
            (jetons.DUREE_SESSION_MS, JOUR_MS),
            (jetons.GRACE_PURGE_SESSION_MS, JOUR_MS),
            (jetons.DUREE_CODE_MS, 60_000),
            (routes_identite.DELAI_REINITIALISATION_MS, heure_ms),
            (routes_identite.DELAI_REINITIALISATION_ACTIF_MS, JOUR_MS),
        ):
            assert constante % unite == 0, (
                f"{constante} ms ne se dit pas en unités entières : la page arrondirait"
            )
        attendus = {
            "service.sessionInactivite": f"{jetons.DUREE_SESSION_MS // JOUR_MS} jours",
            "service.graceSession": f"{jetons.GRACE_PURGE_SESSION_MS // JOUR_MS} jours",
            "service.codeValidite": f"{jetons.DUREE_CODE_MS // 60_000} minutes",
            "service.delaiReinit": (
                f"{routes_identite.DELAI_REINITIALISATION_MS // heure_ms} heures"
            ),
            "service.delaiReinitActif": (
                f"{routes_identite.DELAI_REINITIALISATION_ACTIF_MS // JOUR_MS} jours"
            ),
            "service.fenetreActivite": (
                f"{routes_identite.FENETRE_ACTIVITE_JOURS} derniers jours"
            ),
            "service.quotaCompte": (
                f"{secrets_serveur.QUOTA_COMPTE_OCTETS // 2**20} Mio"
            ),
            "service.gardeBase": f"{secrets_serveur.GARDE_BASE_OCTETS // 10**9} Go",
            "service.versionConditions": str(routes_identite.CONDITIONS_VERSION),
        }
        for cle, attendu in attendus.items():
            assert GEN.VALEURS_DU_SERVICE[cle] == attendu, (
                f"la page promet {cle} = {GEN.VALEURS_DU_SERVICE[cle]!r}, "
                f"le service applique {attendu!r}"
            )


class TestPrivacyMd:
    """§5 : `PRIVACY.md` devient une copie engendrée, protégée par un test
    anti-divergence (modèle gen_agents_md.py)."""

    def test_privacy_md_suit_le_drapeau(self):
        """Avec le drapeau, PRIVACY.md est la copie exacte de la page. Sans
        lui, il ne décrit pas encore un serveur de comptes : GitHub le
        publierait avant l'ouverture, à côté d'un accueil qui dit le contraire."""
        privacy = (RACINE / "PRIVACY.md").read_text(encoding="utf-8")
        if DRAPEAU.exists():
            valeurs, _ = GEN.valeurs_de_rendu()
            attendu = GEN.rendre_privacy_md(
                _page("confidentialite.html"), valeurs["publication.origineSite"]
            )
            assert privacy == attendu, (
                "PRIVACY.md a dérivé de /confidentialite. "
                "Régénère-le DANS CE COMMIT :\n"
                "  .venv/bin/python scripts/gen_privacy_md.py"
            )
        else:
            assert "serveur de comptes" not in privacy, (
                "PRIVACY.md décrit le compte avant l'ouverture "
                "(pas de drapeau .publier-legal)"
            )

    def test_la_conversion_garde_la_structure_et_le_2_9(self):
        """Une conversion qui aplatirait les listes imbriquées ferait lire
        « Compte : » suivi de rien sur GitHub."""
        md = GEN.rendre_privacy_md(
            _page("confidentialite.html"), "https://exemple.invalid"
        )
        assert md.startswith(GEN.ENTETE_PRIVACY), (
            "l'en-tête « ne pas corriger ici » manque"
        )
        assert "\n## Si vous créez un compte\n" in md, (
            "les titres de section sont perdus"
        )
        assert "\n- **Compte** :\n  - l'adresse courriel" in md, (
            "la liste imbriquée du §2.9 est aplatie"
        )
        assert "(https://exemple.invalid/conditions)" in md, (
            "un lien relatif est resté relatif"
        )
        assert "<" not in md.split("-->", 1)[1], "du HTML a fui dans le Markdown"
        for puce in _puces_quand_meme():
            assert puce in _normaliser_md(md), f"PRIVACY.md perd le §2.9 : « {puce} »"

    def test_sans_drapeau_le_generateur_remplit_les_pages_mais_pas_privacy_md(
        self, tmp_path
    ):
        """Les faits relevés, les pages se remplissent ; PRIVACY.md attend le
        drapeau, pour partir dans le même commit que les pages."""
        racine = _copier_depot(tmp_path)
        _remplir_hebergeur(racine)
        avant = (racine / "PRIVACY.md").read_bytes()
        resultat = _generer(racine)
        assert resultat.returncode == 0, resultat.stderr
        for nom in GEN.PAGES:
            page = (racine / "deploy/vps/accueil" / nom).read_text(encoding="utf-8")
            assert GEN.MARQUEUR not in page, (
                f"{nom} garde un marqueur alors que tout est relevé"
            )
        assert "Ville d'essai, Pays d'essai" in (
            racine / "deploy/vps/accueil/confidentialite.html"
        ).read_text(encoding="utf-8"), "le lieu relevé n'a pas été écrit dans la page"
        assert (racine / "PRIVACY.md").read_bytes() == avant, (
            "PRIVACY.md réécrit sans drapeau"
        )

    def test_avec_drapeau_le_generateur_ecrit_privacy_md(self, tmp_path):
        racine = _copier_depot(tmp_path)
        _publiable(racine)
        gen = _generateur(racine)
        page = (racine / "deploy/vps/accueil/confidentialite.html").read_text(
            encoding="utf-8"
        )
        assert (racine / "PRIVACY.md").read_text(
            encoding="utf-8"
        ) == gen.rendre_privacy_md(page, "https://exemple.invalid"), (
            "PRIVACY.md n'est pas la copie de la page remplie"
        )


class TestVerrouDePublication:
    """Étape 6, garde-fou : `deployer-site.sh` refuse de publier
    confidentialite.html et conditions.html tant que `accueil/.publier-legal`
    n'existe pas. Joué dans une copie du dépôt, avec des doublures de `ssh`,
    `rsync` et `curl` : aucun serveur n'est contacté."""

    @pytest.fixture
    def banc(self, tmp_path):
        racine = _copier_depot(tmp_path / "depot")
        subprocess.run(["git", "init", "-q", str(racine)], check=True)
        (racine / "site").mkdir()
        (racine / "site" / "index.html").write_text("site", encoding="utf-8")
        # Le Python du venv n'exécute que le générateur ; la construction
        # mkdocs est hors sujet ici et ne doit rien écrire dans le vrai dépôt.
        venv = racine / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text(
            "#!/bin/sh\n"
            f'case "$1" in */gen_privacy_md.py) exec "{sys.executable}" "$@";; esac\n'
            "exit 0\n",
            encoding="utf-8",
        )
        (venv / "python").chmod(0o755)
        doublures = tmp_path / "doublures"
        doublures.mkdir()
        journal = tmp_path / "appels.jsonl"
        for outil in ("ssh", "rsync", "curl", "scp"):
            chemin = doublures / outil
            chemin.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                f"open({str(journal)!r}, 'a').write(json.dumps(sys.argv) + '\\n')\n"
                "if sys.argv[0].endswith('curl'): print('200', end='')\n",
                encoding="utf-8",
            )
            chemin.chmod(0o755)

        def lancer(committer: bool = True):
            # Le déployeur exige un arbre commité (docs/, et avec le drapeau
            # les pages légales) : le banc committe dans SON dépôt jetable,
            # sauf quand le test veut justement un arbre sale.
            if committer:
                subprocess.run(["git", "-C", str(racine), "add", "-A"], check=True)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(racine),
                        "-c",
                        "user.name=banc",
                        "-c",
                        "user.email=banc@exemple.invalid",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "--no-verify",
                        "-m",
                        "banc",
                    ],
                    check=True,
                )
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("DIAPASON_VPS_HOST", "DIAPASON_PUBLIER_QUAND_MEME")
            }
            env["PATH"] = f"{doublures}{os.pathsep}{env.get('PATH', '')}"
            resultat = subprocess.run(
                ["bash", str(racine / "deploy/vps/deployer-site.sh")],
                capture_output=True,
                text=True,
                env=env,
                timeout=120,
            )
            appels = (
                [json.loads(ligne) for ligne in journal.read_text().splitlines()]
                if journal.exists()
                else []
            )
            return resultat, appels

        return racine, lancer

    @staticmethod
    def _rsync_accueil(appels: list[list[str]]) -> list[str]:
        envois = [
            a
            for a in appels
            if a[0].endswith("rsync") and any("accueil/" in x for x in a)
        ]
        assert len(envois) == 1, f"un seul rsync de l'accueil attendu, vu : {envois}"
        return envois[0]

    @staticmethod
    def _exclus(appel: list[str]) -> set[str]:
        return {appel[i + 1] for i, x in enumerate(appel[:-1]) if x == "--exclude"}

    def test_sans_drapeau_les_pages_legales_restent_sur_le_mac(self, banc):
        racine, lancer = banc
        resultat, appels = lancer()
        assert resultat.returncode == 0, resultat.stderr
        exclus = self._exclus(self._rsync_accueil(appels))
        assert {"/confidentialite.html", "/conditions.html"} <= exclus, (
            f"les pages légales partent sans drapeau : exclusions = {exclus}"
        )
        assert "/.publier-legal" in exclus, "le drapeau lui-même partirait en ligne"
        assert "retenues" in resultat.stdout, (
            "le déployeur doit dire qu'il retient les pages"
        )

    def test_sans_drapeau_les_pages_deja_en_ligne_sont_retirees(self, banc):
        """« rsync --delete » épargne ce qui est exclu : sans retrait
        explicite, des pages publiées une fois restaient en ligne après le
        retrait du drapeau (constaté le 24/09/2026 sur un rsync local)."""
        _, lancer = banc
        resultat, appels = lancer()
        assert resultat.returncode == 0, resultat.stderr
        retraits = [
            a for a in appels if a[0].endswith("ssh") and any("rm -f" in x for x in a)
        ]
        assert retraits, f"aucun retrait des pages légales sans drapeau : {appels}"
        commande = " ".join(retraits[0])
        for nom in (
            "/var/www/diapason/confidentialite.html",
            "/var/www/diapason/conditions.html",
        ):
            assert nom in commande, f"le retrait oublie {nom} : {commande}"

    def test_drapeau_et_fait_non_releve_refusent_tout_le_deploiement(self, banc):
        """Le drapeau dit « je veux publier » ; un `null` dans hebergeur.json
        dit « on ne sait pas ». Le second l'emporte, avant tout contact."""
        racine, lancer = banc
        (racine / "deploy/vps/accueil/.publier-legal").write_text("", encoding="utf-8")
        resultat, appels = lancer()
        assert resultat.returncode != 0, (
            "publication acceptée avec un hebergeur.json incomplet"
        )
        assert "hebergeur.json" in resultat.stderr, (
            "le refus doit nommer hebergeur.json"
        )
        assert appels == [], f"le serveur a été contacté malgré le refus : {appels}"

    def test_drapeau_et_accueil_contradictoire_refusent(self, banc):
        """§5 : « un test refuse “pas de serveur” dans index.html » dès que la
        page de confidentialité part — l'une des deux mentirait."""
        racine, lancer = banc
        _publiable(racine)
        index = racine / "deploy/vps/accueil/index.html"
        index.write_text(
            index.read_text(encoding="utf-8") + "<p>Il n'y a pas de serveur.</p>",
            encoding="utf-8",
        )
        resultat, appels = lancer()
        assert resultat.returncode != 0, (
            "publiée à côté d'un accueil qui dit « pas de serveur »"
        )
        assert "pas de serveur" in resultat.stderr, (
            "le refus doit citer la phrase fautive"
        )
        assert appels == [], f"le serveur a été contacté malgré le refus : {appels}"

    def test_drapeau_et_tout_en_ordre_publient_les_pages(self, banc):
        racine, lancer = banc
        _publiable(racine)
        resultat, appels = lancer()
        assert resultat.returncode == 0, resultat.stderr
        exclus = self._exclus(self._rsync_accueil(appels))
        assert not {"/confidentialite.html", "/conditions.html"} & exclus, (
            f"les pages restent retenues malgré le drapeau : {exclus}"
        )
        assert "/.publier-legal" in exclus, "le drapeau lui-même partirait en ligne"
        assert not [a for a in appels if any("rm -f" in x for x in a)], (
            "les pages légales sont retirées alors que le drapeau les publie"
        )

    def test_drapeau_et_arbre_sale_refusent(self, banc):
        """§5 « un seul commit » : le site part de l'arbre de travail, et
        seul docs/ était regardé. Une page corrigée à la main, jamais
        commitée, serait partie en ligne."""
        racine, lancer = banc
        _publiable(racine)
        lancer()  # committe l'état publiable…
        page = racine / "deploy/vps/accueil/conditions.html"
        page.write_text(page.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        resultat, appels = lancer(committer=False)  # …puis le salit
        assert resultat.returncode != 0, "publiée depuis un arbre non commité"
        assert "conditions.html" in resultat.stderr, (
            f"le refus doit nommer le fichier non commité : {resultat.stderr}"
        )
        # Le premier lancement a publié ; seul le second doit n'avoir rien fait.
        assert not [a for a in appels[len(appels) // 2 :] if a[0].endswith("rsync")], (
            "le serveur a reçu un rsync malgré le refus"
        )

    @staticmethod
    def _defaut_police(racine: Path) -> None:
        index = racine / "deploy/vps/accueil/index.html"
        _remplacer(
            index,
            "</head>",
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=VT323">'
            "\n</head>",
        )

    @staticmethod
    def _defaut_privacy(racine: Path) -> None:
        privacy = racine / "PRIVACY.md"
        privacy.write_text(privacy.read_text(encoding="utf-8") + " ", encoding="utf-8")

    @staticmethod
    def _defaut_exclude_docs(racine: Path) -> None:
        _remplacer(
            racine / "mkdocs.yml",
            "exclude_docs: |\n",
            "exclude_docs: |\n  /confidentialite.md\n",
        )

    @staticmethod
    def _defaut_creneau(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/accueil/conditions.html",
            '<span data-valeur="service.gardeBase">2 Go</span>',
            '<span data-valeur="service.gardeBase">3 Go</span>',
        )

    @staticmethod
    def _defaut_marqueur(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/accueil/conditions.html",
            "</body>",
            "<!-- [à fournir : oubli] -->\n</body>",
        )

    @staticmethod
    def _defaut_promesse_coupee(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/accueil/index.html",
            "</main>",
            "<p>Rien n'est envoyé\n  à&nbsp;un serveur.</p>\n</main>",
        )

    @staticmethod
    def _defaut_titre(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/accueil/index.html",
            "</main>",
            "<p>Rien n&#39;en sort.</p>\n</main>",
        )

    @staticmethod
    def _defaut_lien(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/accueil/index.html",
            '<a href="/conditions">Conditions</a>',
            "",
        )

    @staticmethod
    def _defaut_champ_inconnu(racine: Path) -> None:
        chemin = racine / "deploy/vps/comptes/hebergeur.json"
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        donnees["hebergeur"]["lieuServuer"] = "Ville d'essai"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _defaut_bouche_trou(racine: Path) -> None:
        chemin = racine / "deploy/vps/comptes/hebergeur.json"
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        donnees["sauvegardes"]["lieu"] = "Hostinger (à relever)"
        chemin.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _defaut_nginx_combined(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/nginx/zz-diapason.conf",
            "    access_log /var/log/nginx/diapason.access.log diapason_api;\n"
            "    error_log  /var/log/nginx/diapason.error.log crit;\n}",
            "    access_log /var/log/nginx/diapason.access.log;\n"
            "    error_log  /var/log/nginx/diapason.error.log crit;\n}",
        )

    @staticmethod
    def _defaut_nginx_format_ip(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/nginx/zz-diapason.conf",
            "'[$time_local] ",
            "'$remote_addr [$time_local] ",
        )

    @staticmethod
    def _defaut_nginx_erreurs(racine: Path) -> None:
        _remplacer(
            racine / "deploy/vps/nginx/zz-diapason.conf",
            "error_log  /var/log/nginx/diapason.error.log crit;\n}",
            "error_log  /var/log/nginx/diapason.error.log;\n}",
        )

    @staticmethod
    def _defaut_nginx_heritage(racine: Path) -> None:
        conf = racine / "deploy/vps/nginx/zz-diapason.conf"
        _remplacer(
            conf,
            "    listen [::]:80;\n"
            "    access_log /var/log/nginx/diapason.access.log diapason_api;\n",
            "    listen [::]:80;\n",
        )

    @staticmethod
    def _defaut_police_des_guides(racine: Path) -> None:
        _remplacer(racine / "mkdocs.yml", "  font: false\n", "")

    @staticmethod
    def _defaut_script_des_guides(racine: Path) -> None:
        _remplacer(
            racine / "mkdocs.yml",
            "extra_javascript:\n",
            "extra_javascript:\n  - https://cdn.jsdelivr.net/npm/@docsearch/js@3\n",
        )

    @staticmethod
    def _defaut_import_css(racine: Path) -> None:
        css = racine / "docs/stylesheets/ardechine.css"
        css.write_text(
            "@import url('https://fonts.googleapis.com/css2?family=VT323');\n"
            + css.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    @staticmethod
    def _defaut_site_construit(racine: Path) -> None:
        (racine / "site" / "index.html").write_text(
            '<script src="https://unpkg.com/mermaid@10/dist/mermaid.min.js"></script>',
            encoding="utf-8",
        )

    @staticmethod
    def _defaut_mermaid(racine: Path) -> None:
        (racine / "site" / "index.html").write_text(
            '<pre class="mermaid">graph TD</pre>', encoding="utf-8"
        )

    DEFAUTS = {
        "_defaut_police": "fonts.googleapis",
        "_defaut_privacy": "PRIVACY.md n'est pas la copie",
        "_defaut_exclude_docs": "exclude_docs",
        "_defaut_creneau": "conditions.html n'est pas à jour",
        "_defaut_marqueur": "conditions.html porte encore",
        "_defaut_promesse_coupee": "envoyé à un serveur",
        "_defaut_titre": "rien n'en sort",
        "_defaut_lien": 'href="/conditions"',
        "_defaut_champ_inconnu": "hebergeur.lieuServuer : champ inconnu",
        "_defaut_bouche_trou": "bouche-trou",
        "_defaut_nginx_combined": "sans format",
        "_defaut_nginx_format_ip": "remote_addr",
        "_defaut_nginx_erreurs": "au-dessous de crit",
        "_defaut_nginx_heritage": "pas de access_log propre",
        "_defaut_police_des_guides": "theme.font",
        "_defaut_script_des_guides": "extra_javascript charge",
        "_defaut_import_css": "ardechine.css importe",
        "_defaut_site_construit": "<script> charge unpkg.com",
        "_defaut_mermaid": "Mermaid",
    }

    @pytest.mark.parametrize("defaut", sorted(DEFAUTS))
    def test_un_seul_defaut_suffit_a_refuser(self, banc, defaut):
        """24/09/2026 : six contrôles du vérificateur survivaient à leur
        suppression, parce que `_publiable` corrige tout d'un coup et
        qu'aucun test ne rejouait « drapeau + UN défaut ». Ici, chaque défaut
        est réintroduit seul, commité : le refus doit le nommer, avant tout
        contact avec le serveur."""
        racine, lancer = banc
        _publiable(racine)
        getattr(self, defaut)(racine)
        resultat, appels = lancer()
        assert resultat.returncode != 0, f"{defaut} n'a pas fait refuser la publication"
        assert self.DEFAUTS[defaut] in resultat.stderr, (
            f"{defaut} : le refus ne nomme pas le défaut « {self.DEFAUTS[defaut]} » :\n"
            f"{resultat.stderr}"
        )
        assert not [a for a in appels if a[0].endswith(("rsync", "ssh"))], (
            f"{defaut} : le serveur a été contacté malgré le refus : {appels}"
        )


class TestLeDepotReel:
    """Ce que le dépôt tel qu'il est commité dit de son propre verrou."""

    def test_le_depot_est_publiable_des_que_le_drapeau_existe(self):
        """§5 « Tests » : « si ce fichier contient null, le test échoue ». Il
        échoue dès que la publication est demandée ; avant, le verrou doit
        être fermé pour une raison qu'il sait dire."""
        problemes = GEN.problemes_de_publication()
        if DRAPEAU.exists():
            assert problemes == [], "drapeau .publier-legal posé, mais :\n" + "\n".join(
                problemes
            )
        else:
            # 24/09/2026 : « problemes != [] » ne prouvait rien — la liste
            # n'est jamais vide tant que index.html charge Google Fonts. Ce
            # qui doit être dit, c'est CHAQUE null de hebergeur.json.
            donnees = json.loads(GEN.chemins()["hebergeur"].read_text(encoding="utf-8"))
            nuls = [cle for cle, v in GEN._aplatir(donnees).items() if v is None]
            for cle in nuls:
                assert any(
                    f"hebergeur.json — {cle} : non relevé" in p for p in problemes
                ), f"le vérificateur tait le fait non relevé {cle}"
            assert nuls or problemes, (
                "sans drapeau, le vérificateur ne trouve rien à refuser : "
                "pose le drapeau "
                "accueil/.publier-legal dans le commit de l'étape 13, ou le verrou ment"
            )

    def test_la_page_de_documentation_renvoie_vers_la_page_canonique(self):
        """§5 : docs/confidentialite.md renvoie, il ne recopie pas — une
        troisième copie divergerait à son tour."""
        doc = (RACINE / "docs" / "confidentialite.md").read_text(encoding="utf-8")
        assert "](/confidentialite)" in doc, (
            "docs/confidentialite.md ne renvoie pas vers la page"
        )
        assert "globalSeq" not in doc and "Resend" not in doc, (
            "docs/confidentialite.md recopie la politique"
        )

    def test_la_page_de_documentation_reste_hors_du_site_sans_drapeau(self):
        """Publiée avant l'ouverture, elle pointerait vers un /confidentialite
        que le déployeur retient : un 404 sous le nom « Confidentialité »."""
        exclus = pathspec.GitIgnoreSpec.from_lines(GEN._exclude_docs(RACINE))
        if not DRAPEAU.exists():
            assert exclus.match_file("confidentialite.md"), (
                "mkdocs.yml doit exclure docs/confidentialite.md "
                "tant que le drapeau manque"
            )

    def test_la_telemetrie_n_est_plus_dite_activee_par_defaut(self):
        """§5 : docs/telemetry.md et sa version anglaise disaient la télémétrie
        « Activée par défaut » / « On by default », faux face à
        AnalyticsConfig.enabled = False.

        La première version lisait la ligne 10 par son numéro : l'ajout d'une
        phrase en tête de page (24/09/2026) l'a fait lire une ligne vide et
        échouer sur une page pourtant juste. On cherche désormais les
        phrases, dans les deux langues."""
        from diapason.core.config import AnalyticsConfig

        assert AnalyticsConfig().enabled is False, (
            "le défaut a changé : corrige la documentation"
        )
        docs = RACINE / "docs"
        francais = (docs / "telemetry.md").read_text(encoding="utf-8")
        anglais = (docs / "telemetry.en.md").read_text(encoding="utf-8")
        assert "Désactivée par défaut" in francais, (
            "docs/telemetry.md doit dire la télémétrie désactivée par défaut"
        )
        assert "Off by default" in anglais, (
            "docs/telemetry.en.md doit dire la télémétrie désactivée par défaut"
        )
        for page, texte, faux in (
            ("telemetry.md", francais, "Activée par défaut"),
            ("telemetry.md", francais, "envoie par défaut"),
            ("telemetry.en.md", anglais, "On by default"),
            ("telemetry.en.md", anglais, "telemetry** by default"),
        ):
            assert faux not in texte, f"docs/{page} dit encore « {faux} »"
