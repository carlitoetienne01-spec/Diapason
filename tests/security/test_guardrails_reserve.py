"""§5 : la réserve du flux se déduit des motifs, elle ne se promet pas.

Le 27/09/2026, ``_STREAM_HOLDBACK`` est passé de 128 à 48 caractères sur la
foi d'un commentaire — « les motifs FIXES tiennent en 36 caractères au plus »
— que rien ne dérivait des motifs (le vrai maximum est 31, ``private_key``).
Une entrée ajoutée aux motifs pouvait dépasser la marge en silence : le flux
aurait diffusé le début d'un secret avant que sa fin n'arrive pour le faire
reconnaître, et le reste, seul dans le tampon, n'aurait plus ressemblé à rien.

Ce que le flux applique n'est pas ``scanner.py`` : ``SecretScanner`` et
``PIIScanner`` y délèguent à l'extension PyO3, dont les motifs sont compilés
depuis ``rust/crates/diapason-security/src/scanner.rs`` ; les ``PATTERNS``
Python ne servent qu'au repli. Les deux tables sont donc lues ici, et chaque
motif doit tomber dans l'une de trois classes :

- borné : sa plus longue correspondance, regards avant compris, tient
  STRICTEMENT dans la réserve ;
- ``JETONS`` : non borné, mais aucun de ses atomes ne consomme l'un des blancs
  où ``_safe_prefix`` coupe — le mot entier reste retenu ;
- ``AFFECTATIONS`` : non borné et traversant les blancs, retenu dès son
  mot-clé par ``_OPEN_ASSIGNMENT`` — démontré sur la grammaire des deux
  motifs par ``TestRetenueDesAffectations``, pas seulement échantillonné.
"""

from __future__ import annotations

import functools
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from diapason.security.guardrails import (
    _OPEN_ASSIGNMENT,
    _STREAM_BOUNDARY,
    _STREAM_HOLDBACK,
    _safe_prefix,
)
from diapason.security.scanner import PIIScanner, SecretScanner

try:  # Python 3.11 et suivants
    from re import _constants as sre
    from re import _parser as sre_parse
except ImportError:  # Python 3.10 : les mêmes modules, sous leurs anciens noms
    import sre_constants as sre
    import sre_parse

RACINE = Path(__file__).resolve().parents[2]
SCANNER_RS = RACINE / "rust" / "crates" / "diapason-security" / "src" / "scanner.rs"

# Non bornés, mais faits de caractères qu'aucun blanc n'interrompt : une clé,
# une adresse, une URI. _safe_prefix ne coupe jamais un mot : il les retient
# en entier, quelle que soit leur longueur.
JETONS = frozenset(
    {
        "openai_key",
        "anthropic_key",
        "github_token",
        "db_connection_string",
        "slack_token",
        "stripe_key",
        "email",
    }
)
# Non bornés ET traversant les blancs (« password = \n '…' ») : seule la
# retenue de _OPEN_ASSIGNMENT, ouverte dès le mot-clé, les protège.
AFFECTATIONS = frozenset({"password_assignment", "generic_api_key"})

AVANT = "Une introduction française, claire et sans donnée confidentielle. " * 8

# Une répétition ouverte est déroulée au-delà de la réserve : l'exemple doit
# éprouver le recul jusqu'au blanc et _OPEN_ASSIGNMENT, pas la réserve fixe,
# qui retiendrait n'importe quoi de plus court qu'elle.
_DEROULE = _STREAM_HOLDBACK + 1
# Les blancs d'abord : toute classe qui en tolère un en reçoit un, puisque
# c'est précisément là que _safe_prefix coupe.
_CANDIDATS = "".join(
    dict.fromkeys(
        _STREAM_BOUNDARY
        + "aZ09"
        + string.ascii_letters
        + string.digits
        + string.punctuation
        + "é"
    )
)

_CONSOMMATEURS = (sre.LITERAL, sre.NOT_LITERAL, sre.ANY, sre.IN)
_REGARDS = (sre.ASSERT, sre.ASSERT_NOT)
_REPETITIONS = tuple(
    getattr(sre, nom)
    for nom in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT")
    if hasattr(sre, nom)
)
_ATOMIQUE = getattr(sre, "ATOMIC_GROUP", None)
_CATEGORIES = {
    sre.CATEGORY_DIGIT: r"\d",
    sre.CATEGORY_NOT_DIGIT: r"\D",
    sre.CATEGORY_SPACE: r"\s",
    sre.CATEGORY_NOT_SPACE: r"\S",
    sre.CATEGORY_WORD: r"\w",
    sre.CATEGORY_NOT_WORD: r"\W",
}


@dataclass(frozen=True)
class Motif:
    fichier: str
    table: str
    nom: str
    source: str
    drapeaux: int

    def __str__(self) -> str:
        return f"{self.fichier} {self.table} « {self.nom} »"


def motifs_python() -> list[Motif]:
    # _scan_python compile chaque motif avec re.IGNORECASE.
    return [
        Motif("scanner.py", f"{classe.__name__}.PATTERNS", nom, source, re.IGNORECASE)
        for classe in (SecretScanner, PIIScanner)
        for nom, (source, _niveau, _description) in classe.PATTERNS.items()
    ]


_TABLE_RS = re.compile(
    r"static (\w+_PATTERNS): Lazy<Vec<PatternDef>> = Lazy::new\(\|\| \{(.*?)\n\}\);",
    re.DOTALL,
)
_MOTIF_RS = re.compile(
    r'pattern!\(\s*"(\w+)",\s*(?://[^\n]*\n\s*)*r(#*)"(.*?)"\2\s*,', re.DOTALL
)


def motifs_rust() -> list[Motif]:
    texte = SCANNER_RS.read_text(encoding="utf-8")
    motifs = []
    for table, corps in _TABLE_RS.findall(texte):
        lus = _MOTIF_RS.findall(corps)
        assert len(lus) == corps.count("pattern!("), (
            f"scanner.rs {table} : un motif n'est pas lu (chaîne non brute ?) ; "
            "la réserve du flux ne serait pas vérifiée pour lui"
        )
        # La regex de Rust est sensible à la casse, sauf (?i) que re lit aussi.
        motifs += [
            Motif("scanner.rs", table, nom, source, 0) for nom, _dieses, source in lus
        ]
    assert len(motifs) == texte.count("pattern!("), (
        "scanner.rs : un motif vit hors des tables *_PATTERNS ; apprends ce test "
        "à le lire avant de le laisser au flux"
    )
    return motifs


def tous_les_motifs() -> list[Motif]:
    return motifs_python() + motifs_rust()


def arbre(motif: Motif):
    return sre_parse.parse(motif.source, motif.drapeaux)


def noeuds(elements, drapeaux: int):
    """Chaque nœud de l'arbre, regards compris, avec ses drapeaux en vigueur."""
    for op, av in elements:
        yield op, av, drapeaux
        if op is sre.SUBPATTERN:
            yield from noeuds(av[3], (drapeaux | av[1]) & ~av[2])
        elif op is sre.BRANCH:
            for branche in av[1]:
                yield from noeuds(branche, drapeaux)
        elif op in _REPETITIONS:
            yield from noeuds(av[2], drapeaux)
        elif op in _REGARDS:
            yield from noeuds(av[1], drapeaux)
        elif op is _ATOMIQUE:
            yield from noeuds(av, drapeaux)
        elif op is sre.GROUPREF_EXISTS:
            for branche in av[1:]:
                if branche is not None:
                    yield from noeuds(branche, drapeaux)


def classe(elements) -> str:
    negation, parties = "", []
    for op, av in elements:
        if op is sre.NEGATE:
            negation = "^"
        elif op is sre.LITERAL:
            parties.append(re.escape(chr(av)))
        elif op is sre.RANGE:
            parties.append(f"{re.escape(chr(av[0]))}-{re.escape(chr(av[1]))}")
        elif op is sre.CATEGORY and av in _CATEGORIES:
            parties.append(_CATEGORIES[av])
        else:
            raise AssertionError(f"{op} {av} : élément de classe inconnu de ce test")
    return f"[{negation}{''.join(parties)}]"


def accepte(op, av, car: str, drapeaux: int) -> bool:
    """L'atome ``(op, av)`` peut-il consommer le caractère ``car`` ?"""
    drapeaux &= ~re.VERBOSE
    if op is sre.ANY:
        return car != "\n" or bool(drapeaux & re.DOTALL)
    if op is sre.LITERAL:
        return re.fullmatch(re.escape(chr(av)), car, drapeaux) is not None
    if op is sre.NOT_LITERAL:
        return re.fullmatch(re.escape(chr(av)), car, drapeaux) is None
    if op is sre.IN:
        return re.fullmatch(classe(av), car, drapeaux) is not None
    raise AssertionError(f"{op} {av} : atome inconnu de ce test, apprends-le-lui")


_ACCEPTES: dict[tuple[int, str, int], list[str]] = {}


def acceptes(op, av, drapeaux: int) -> list[str]:
    cle = (int(op), repr(av), drapeaux)
    if cle not in _ACCEPTES:
        _ACCEPTES[cle] = [c for c in _CANDIDATS if accepte(op, av, c, drapeaux)]
    return _ACCEPTES[cle]


def derouler(elements, drapeaux: int, rang: int) -> list[str]:
    """Des correspondances maximales, construites depuis l'arbre du motif.

    Chaque répétition bornée va jusqu'à son maximum, chaque répétition ouverte
    au-delà de la réserve ; chaque alternative donne son exemple, et une
    classe de deux caractères au plus (les deux guillemets, ``=`` et ``:``)
    est déclinée en entier. Dans une répétition, le caractère tourne parmi
    ceux que la classe accepte, blancs en tête.
    """
    textes = [""]
    for op, av in elements:
        if op is sre.AT or op in _REGARDS:
            continue
        if op is sre.SUBPATTERN:
            suites = derouler(av[3], (drapeaux | av[1]) & ~av[2], rang)
        elif op is sre.BRANCH:
            suites = [t for branche in av[1] for t in derouler(branche, drapeaux, rang)]
        elif op is _ATOMIQUE:
            suites = derouler(av, drapeaux, rang)
        elif op in _REPETITIONS:
            bas, haut, sous = av
            fois = bas + _DEROULE if haut >= sre.MAXREPEAT else haut
            suites = ["".join(derouler(sous, drapeaux, i)[0] for i in range(fois))]
        elif op is sre.LITERAL:
            # Sa casse telle qu'écrite : décliner chaque lettre sous IGNORECASE
            # engendrait 2^15 variantes de « PRIVATE KEY » pour rien.
            suites = [chr(av)]
        else:
            possibles = acceptes(op, av, drapeaux)
            assert possibles, f"{op} {av} : aucun caractère candidat ne convient"
            suites = (
                possibles
                if op is sre.IN and rang == 0 and len(possibles) <= 2
                else [possibles[rang % len(possibles)]]
            )
        textes = [t + s for t in textes for s in suites]
    return textes


def exemples(motif: Motif) -> list[str]:
    racine = arbre(motif)
    return derouler(racine, racine.state.flags, 0)


def portee(motif: Motif) -> tuple[int, int]:
    """Plus longue correspondance, et ce que ses regards avant lisent en plus.

    ``getwidth()`` compte un regard avant pour zéro. Or une correspondance
    dont le regard dépasse la réserve peut n'apparaître qu'une fois son début
    diffusé. La largeur de chaque regard s'ajoute donc en entier : c'est un
    MAJORANT. Des regards tous posés en tête, comme ceux d'ipv4_public, ne
    lisent ensemble que la largeur du plus large d'entre eux, pas leur somme.
    Aucun chiffre ici : le message d'échec du test de largeur les calcule.
    """
    racine = arbre(motif)
    regards = sum(
        av[1].getwidth()[1]
        for op, av, _drapeaux in noeuds(racine, racine.state.flags)
        if op in _REGARDS
    )
    return racine.getwidth()[1], regards


class TestReserveDuFlux:
    """§5 : chaque motif appliqué au flux est borné sous la réserve, ou classé."""

    def test_les_deux_tables_de_scanner_rs_sont_lues_en_entier(self):
        """§5 : mesurer le repli Python seul laisserait l'extension sans contrôle."""
        motifs = motifs_rust()
        assert {m.table for m in motifs} == {"SECRET_PATTERNS", "PII_PATTERNS"}, (
            "scanner.rs a changé de forme : la réserve serait vérifiée sur le "
            "repli Python, pas sur ce que l'extension applique"
        )
        assert {"private_key", "email"} <= {m.nom for m in motifs}, (
            "la lecture de scanner.rs doit rendre ses vrais motifs"
        )

    def test_l_extension_reconnait_les_motifs_lus_dans_scanner_rs(self):
        """§5 : ce qui est mesuré ici doit être ce que l'extension compile."""
        scanners = {"SECRET_PATTERNS": SecretScanner(), "PII_PATTERNS": PIIScanner()}
        if any(objet._rust_impl is None for objet in scanners.values()):
            pytest.skip("accélérateur Rust absent ; scanner.rs reste mesuré")
        fautes = []
        for motif in motifs_rust():
            for exemple in exemples(motif):
                trouves = scanners[motif.table].scan(exemple).findings
                if motif.nom not in {f.pattern_name for f in trouves}:
                    fautes.append(
                        f"{motif} : l'extension ne reconnaît pas {exemple!r}, que "
                        "re lit comme une correspondance. L'extension chargée "
                        "n'est pas compilée depuis ce scanner.rs (maturin develop), "
                        "ou re et le moteur de Rust divergent sur ce motif."
                    )
                    break
        assert not fautes, "\n".join(fautes)

    def test_le_classement_ne_nomme_que_des_motifs_existants(self):
        """§5 : une classe périmée ferait croire vérifié un motif disparu."""
        noms = {m.nom for m in tous_les_motifs()}
        perimes = sorted((JETONS | AFFECTATIONS) - noms)
        assert not perimes, (
            f"{perimes} : classés ici mais absents des scanners, retire-les"
        )
        assert not JETONS & AFFECTATIONS, "un motif appartient à une seule classe"

    def test_chaque_motif_tient_dans_la_reserve_ou_est_classe(self):
        """§5 : un motif fixe plus long que la réserve fuirait par son début."""
        fautes = []
        for motif in tous_les_motifs():
            racine = arbre(motif)
            if any(
                op in _REGARDS and av[0] < 0
                for op, av, _drapeaux in noeuds(racine, racine.state.flags)
            ):
                fautes.append(
                    f"{motif} regarde en arrière : une fois le début diffusé, le "
                    "tampon ne le contient plus et le motif ne se reconnaît plus."
                )
                continue
            if motif.nom in JETONS | AFFECTATIONS:
                continue
            largeur, regards = portee(motif)
            if largeur + regards >= sre.MAXREPEAT:
                fautes.append(
                    f"{motif} n'est pas borné et n'est pas classé. Range-le dans "
                    "JETONS s'il ne consomme aucun blanc, dans AFFECTATIONS si "
                    "_OPEN_ASSIGNMENT (guardrails.py) le retient dès son "
                    "mot-clé ; sinon borne-le."
                )
            elif largeur + regards >= _STREAM_HOLDBACK:
                detail = f" dont {regards} lus par ses regards avant" if regards else ""
                fautes.append(
                    f"{motif} couvre jusqu'à {largeur + regards} caractères"
                    f"{detail}, la réserve du flux n'en garde que "
                    f"{_STREAM_HOLDBACK} : son début partirait avant que sa fin "
                    "ne le fasse reconnaître. Relève _STREAM_HOLDBACK "
                    f"(guardrails.py) au-dessus de {largeur + regards}, ou "
                    "range-le dans JETONS s'il ne consomme aucun blanc."
                )
        assert not fautes, "\n".join(fautes)

    def test_un_jeton_ne_consomme_aucun_blanc_ou_le_flux_coupe(self):
        """§5 : _safe_prefix recule jusqu'au blanc ; un jeton qui en avale fuit."""
        # Python et Rust s'accordent sur ces six blancs pour \s, \d, \w et « . ».
        fautes = []
        for motif in tous_les_motifs():
            if motif.nom not in JETONS:
                continue
            racine = arbre(motif)
            blancs = sorted(
                {
                    car
                    for op, av, drapeaux in noeuds(racine, racine.state.flags)
                    if op in _CONSOMMATEURS
                    for car in _STREAM_BOUNDARY
                    if accepte(op, av, car, drapeaux)
                }
            )
            if blancs:
                fautes.append(
                    f"{motif} peut consommer {blancs!r} : _safe_prefix recule "
                    "jusqu'au dernier blanc et couperait ce motif en deux. Sors-le "
                    "de JETONS : borne-le sous la réserve, ou fais-le retenir par "
                    "_OPEN_ASSIGNMENT et range-le dans AFFECTATIONS."
                )
        assert not fautes, "\n".join(fautes)

    def test_aucune_coupure_ne_diffuse_le_debut_d_un_motif(self):
        """§5 : chaque début de correspondance maximale reste dans le tampon.

        Un échantillon, pas une preuve : derouler() pousse chaque répétition
        à son maximum, jamais à zéro, ne prend qu'un caractère par occurrence
        d'une classe de plus de deux, et que la première alternative d'une
        branche répétée. Pour les AFFECTATIONS, il éprouve _OPEN_ASSIGNMENT
        sur des exemples qui débordent la réserve ; la démonstration est
        TestRetenueDesAffectations.
        """
        fautes = []
        for motif in tous_les_motifs():
            for exemple in exemples(motif):
                assert re.fullmatch(motif.source, exemple, motif.drapeaux), (
                    f"{motif} : l'exemple engendré {exemple!r} ne correspond pas, "
                    "corrige derouler() avant de conclure"
                )
                fuite = premiere_fuite(exemple)
                if fuite is not None:
                    debut, diffuse = fuite
                    fautes.append(
                        f"{motif} : coupé après {debut!r}, le flux diffuse "
                        f"{diffuse!r} avant que la suite ne le fasse reconnaître. "
                        + a_revoir(motif)
                    )
                    break  # un exemple suffit à nommer le motif à revoir
        assert not fautes, "\n".join(fautes)


def a_revoir(motif: Motif) -> str:
    if motif.nom in AFFECTATIONS:
        return (
            "_OPEN_ASSIGNMENT (guardrails.py) ne retient pas ce début : "
            "apprends-lui ce mot-clé ou cette forme d'affectation."
        )
    if motif.nom in JETONS:
        return "Un blanc s'y glisse : ce n'est plus un jeton."
    return f"Il déborde la réserve de {_STREAM_HOLDBACK} caractères."


def premiere_fuite(exemple: str) -> tuple[str, str] | None:
    """La première coupure de ``exemple`` dont ``_safe_prefix`` diffuse le début."""
    for coupure in range(1, len(exemple)):
        texte = AVANT + exemple[:coupure]
        libere = _safe_prefix(texte)
        if libere > len(AVANT):
            return exemple[:coupure], texte[len(AVANT) : libere]
    return None


# ---------------------------------------------------------------------------
# AFFECTATIONS : la démonstration
# ---------------------------------------------------------------------------
#
# 28/09/2026 : test_aucune_coupure_ne_diffuse_le_debut_d_un_motif passait
# encore, 6 sur 6, avec « [=:]? » à la place de « [=:] » dans
# password_assignment — un séparateur facultatif que _OPEN_ASSIGNMENT ne
# connaît pas. Un vrai flux diffusait alors « password "correct horse… »
# avant le guillemet fermant. derouler() n'engendre jamais la branche vide
# d'un « ? » : l'échantillon ne pouvait pas le voir. Ce qui suit lit la
# grammaire des deux motifs au lieu d'en tirer des exemples.

_DRAPEAUX_EN_LIGNE = ((re.IGNORECASE, "i"), (re.DOTALL, "s"))
_POSSESSIF = getattr(sre, "POSSESSIVE_REPEAT", None)


@functools.cache
def tout_unicode() -> str:
    """Chaque point de code : une inclusion de classes s'y vérifie en entier."""
    return "".join(map(chr, range(sys.maxunicode + 1)))


def aplatir(elements, drapeaux: int):
    """Les nœuds d'une suite, ses groupes (capturants ou non) dépliés."""
    for op, av in elements:
        if op is sre.SUBPATTERN:
            yield from aplatir(av[3], (drapeaux | av[1]) & ~av[2])
        else:
            yield op, av, drapeaux


def mots(noeuds) -> frozenset[str] | None:
    """Le langage de ``noeuds`` s'il est fini et fait de littéraux, sinon None."""
    langue = frozenset({""})
    for op, av, drapeaux in noeuds:
        if op is sre.LITERAL:
            suites = frozenset({chr(av)})
        elif op is sre.IN and all(o is sre.LITERAL for o, _a in av):
            suites = frozenset(chr(a) for _o, a in av)
        elif op is sre.BRANCH:
            branches = [mots(list(aplatir(b, drapeaux))) for b in av[1]]
            if None in branches:
                return None
            suites = frozenset().union(*branches)
        else:
            return None
        langue = frozenset(debut + suite for debut in langue for suite in suites)
    return langue


def tete_litterale(noeuds) -> int:
    """Combien de nœuds de tête forment des mots-clés littéraux."""
    tete = 0
    while tete < len(noeuds) and mots(noeuds[: tete + 1]) is not None:
        tete += 1
    return tete


def casses(tete) -> list[bool]:
    """Pour chaque littéral des mots-clés : se lit-il sans égard à la casse ?

    Lu littéral par littéral, pas sur les drapeaux globaux : un « (?-i:…) »
    autour des mots-clés de _OPEN_ASSIGNMENT les rendrait sensibles à la
    casse sous un re.IGNORECASE qui dirait le contraire.
    """
    return [
        bool(drapeaux & re.IGNORECASE)
        for op, av, lu_sous in tete
        for sous_op, _av, drapeaux in noeuds([(op, av)], lu_sous)
        if sous_op in (sre.LITERAL, sre.IN)
    ]


@dataclass(frozen=True)
class Maillon:
    """Un caractère d'une même classe, répété de ``bas`` à ``haut`` fois."""

    classe: str
    drapeaux: int
    bas: int
    haut: int
    categorie: bool  # \s, \d, \w : re et Rust ne les lisent pas pareil

    @property
    def unique(self) -> bool:
        return (self.bas, self.haut) == (1, 1)

    def en_ligne(self) -> str:
        """La classe et ses drapeaux en ligne : re les compose sans les mêler."""
        actifs = "".join(let for d, let in _DRAPEAUX_EN_LIGNE if self.drapeaux & d)
        eteints = "".join(let for d, let in _DRAPEAUX_EN_LIGNE if not self.drapeaux & d)
        return f"(?{actifs}{'-' if eteints else ''}{eteints}:{self.classe})"

    def __str__(self) -> str:
        # Un \x1c brut ne s'imprime pas : « [^\S-] » cachait « [^\S\x1c-\x1f] ».
        lisible = "".join(c if c.isprintable() else repr(c)[1:-1] for c in self.classe)
        if self.unique:
            return lisible
        if (self.bas, self.haut) == (0, 1):
            return f"{lisible}?"
        if self.haut >= sre.MAXREPEAT:
            return f"{lisible}*" if self.bas == 0 else f"{lisible}{{{self.bas},}}"
        return f"{lisible}{{{self.bas},{self.haut}}}"


def maillon(op, av, drapeaux: int) -> Maillon | None:
    bas = haut = 1
    if op in _REPETITIONS:
        bas, haut, sous = av
        sous = list(aplatir(sous, drapeaux))
        if len(sous) != 1:
            return None
        op, av, drapeaux = sous[0]
    if op is sre.LITERAL:
        source = re.escape(chr(av))
    elif op is sre.NOT_LITERAL:
        source = f"[^{re.escape(chr(av))}]"
    elif op is sre.ANY:
        source = "."
    elif op is sre.IN:
        source = classe(av)
    else:
        return None
    categorie = op is sre.IN and any(o is sre.CATEGORY for o, _a in av)
    return Maillon(source, drapeaux & (re.IGNORECASE | re.DOTALL), bas, haut, categorie)


@dataclass(frozen=True)
class Forme:
    """« Mots-clés littéraux, puis maillons » : la forme d'une affectation."""

    mots_cles: frozenset[str]
    casse: bool  # un mot-clé au moins se lit sans égard à la casse
    maillons: tuple[Maillon, ...]


def forme_du_motif(motif: Motif) -> Forme | None:
    """La forme de ``motif``, ou None s'il n'a pas celle d'une affectation.

    Ses ancres et ses regards sont omis : ils ne font que retrancher des
    correspondances, et démontrer la retenue d'un langage plus large la
    démontre pour le sien.
    """
    racine = arbre(motif)
    noeuds = [
        noeud
        for noeud in aplatir(racine, racine.state.flags)
        if noeud[0] is not sre.AT and noeud[0] not in _REGARDS
    ]
    tete = tete_litterale(noeuds)
    maillons = [maillon(*noeud) for noeud in noeuds[tete:]]
    if not tete or None in maillons:
        return None
    return Forme(mots(noeuds[:tete]), any(casses(noeuds[:tete])), tuple(maillons))


def chaine(noeuds) -> list[tuple[bool, Maillon]] | None:
    """Les maillons de la retenue : ``(False, étoile)`` ou ``(True, entrée)``.

    Une étoile répète sa classe de zéro à l'infini ; une entrée est un
    caractère unique qui ouvre un groupe facultatif courant jusqu'à la fin.
    Une telle chaîne accepte chacune de ses coupures. Toute autre forme
    (répétition possessive, maillon obligatoire, groupe au milieu) rend None.
    """
    lus = []
    for rang, (op, av, drapeaux) in enumerate(noeuds):
        if _POSSESSIF is not None and op is _POSSESSIF:
            return None
        if op in _REPETITIONS and av[:2] == (0, 1) and rang == len(noeuds) - 1:
            sous = list(aplatir(av[2], drapeaux))
            if not sous or (_POSSESSIF is not None and sous[0][0] is _POSSESSIF):
                return None
            entree, suite = maillon(*sous[0]), chaine(sous[1:])
            if entree is None or not entree.unique or suite is None:
                return None
            return [*lus, (True, entree), *suite]
        lu = maillon(op, av, drapeaux)
        if lu is None or (lu.bas, lu.haut) != (0, sre.MAXREPEAT):
            return None
        lus.append((False, lu))
    return lus


def retenue() -> tuple[frozenset[str], bool, list[tuple[bool, Maillon]]]:
    """_OPEN_ASSIGNMENT lu comme mots-clés, puis une chaîne de maillons."""
    racine = sre_parse.parse(_OPEN_ASSIGNMENT.pattern, _OPEN_ASSIGNMENT.flags)
    noeuds = list(aplatir(racine, racine.state.flags))
    # \Z en queue n'ôte rien : la démonstration fait finir la correspondance
    # au bout du texte, là où \Z la veut.
    if noeuds and noeuds[-1][:2] == (sre.AT, sre.AT_END_STRING):
        noeuds = noeuds[:-1]
    tete = tete_litterale(noeuds)
    lus = chaine(noeuds[tete:])
    assert tete and lus is not None, (
        "_OPEN_ASSIGNMENT (guardrails.py) n'a plus la forme « mots-clés, "
        "étoiles, entrées facultatives emboîtées, \\Z » que ce test sait lire : "
        "la démonstration ne s'applique plus, apprends-lui cette forme."
    )
    return mots(noeuds[:tete]), all(casses(noeuds[:tete])), lus


@functools.cache
def hors_de(dedans: str, dehors: str) -> str | None:
    """Un point de code que la classe ``dedans`` admet et ``dehors`` refuse."""
    trouve = re.search(f"(?={dedans})(?!{dehors})", tout_unicode())
    return None if trouve is None else tout_unicode()[trouve.start()]


def representant(m: Maillon) -> str:
    return next(c for c in _CANDIDATS if re.fullmatch(m.en_ligne(), c))


def mesure_rust(motif: Motif, rang: int) -> frozenset[str] | None:
    """Les caractères que l'extension admet au maillon ``rang`` de ``motif``.

    Mesurés, pas déduits : le \\s de Rust n'est pas celui de re (re y met
    U+001C..U+001F). Une sonde par point de code — hors surrogats, qu'une
    chaîne Rust ne porte pas —, le reste du motif intact autour. None sans
    extension : scanner.rs n'est alors appliqué nulle part.
    """
    scanner = {"SECRET_PATTERNS": SecretScanner, "PII_PATTERNS": PIIScanner}[
        motif.table
    ]()
    if scanner._rust_impl is None:
        return None
    # Une ancre collée au maillon (\b, ^, $) jugerait la sonde sur ses seuls
    # voisins : un caractère refusé là passerait au milieu d'une vraie
    # répétition, et la mesure mentirait par défaut.
    racine = arbre(motif)
    brut = [n for n in aplatir(racine, racine.state.flags) if n[0] not in _REGARDS]
    lus = [j for j, noeud in enumerate(brut) if noeud[0] is not sre.AT]
    place = lus[tete_litterale([brut[j] for j in lus]) + rang]
    assert all(
        brut[j][0] is not sre.AT for j in (place - 1, place + 1) if 0 <= j < len(brut)
    ), (
        f"{motif} : une ancre touche son maillon {rang}, la sonde ne mesurerait "
        "plus toute sa classe. Apprends à ce test à la mesurer autrement."
    )
    forme = forme_du_motif(motif)
    # Au moins un caractère par maillon : un maillon facultatif que
    # l'extension chargée exige encore (scanner.rs modifié, pas recompilé)
    # rendrait sinon la sonde muette, et masquerait le vrai message.
    avant = min(forme.mots_cles) + "".join(
        representant(m) * max(m.bas, 1) for m in forme.maillons[:rang]
    )
    fois = max(forme.maillons[rang].bas, 1)
    apres = "".join(representant(m) * max(m.bas, 1) for m in forme.maillons[rang + 1 :])
    admis = set()
    # Par blocs de 65 536 : les 1,1 million de sondes d'un coup montaient à
    # 177 Mo (tracemalloc, 28/09/2026) dans chaque ouvrier de -n auto ; par
    # blocs, 14 Mo.
    for bloc in range(0, sys.maxunicode + 1, 0x10000):
        texte = "\n".join(
            avant + chr(point) * fois + apres
            for point in range(bloc, bloc + 0x10000)
            if not 0xD800 <= point <= 0xDFFF
        )
        for trouve in scanner.scan(texte).findings:
            lu = trouve.matched_text
            if (
                trouve.pattern_name == motif.nom
                and len(lu) > len(avant)
                and lu == avant + lu[len(avant)] * fois + apres
            ):
                admis.add(lu[len(avant)])
    assert representant(forme.maillons[rang]) in admis, (
        f"{motif} : la sonde du maillon {rang} ne trouve même pas "
        f"{representant(forme.maillons[rang])!r} ; elle ne mesure rien, "
        "corrige-la avant de conclure"
    )
    return frozenset(admis)


# Une classe se lit de la même façon à tout rang de tout motif : une seule
# mesure par classe. Quatre (deux \s dans chacune des deux affectations)
# coûtaient une seconde à chaque passage.
_MESURES: dict[tuple[str, int], frozenset[str] | None] = {}


def debordement(motif: Motif, forme: Forme, rang: int, cible: Maillon) -> str | None:
    """Un caractère que le maillon ``rang`` admet et que ``cible`` refuse."""
    m = forme.maillons[rang]
    mesure = None
    if motif.fichier == "scanner.rs" and m.categorie:
        if (m.classe, m.drapeaux) not in _MESURES:
            _MESURES[m.classe, m.drapeaux] = mesure_rust(motif, rang)
        mesure = _MESURES[m.classe, m.drapeaux]
    if mesure is None:
        return hors_de(m.en_ligne(), cible.en_ligne())
    return next(
        (c for c in sorted(mesure) if not re.fullmatch(cible.en_ligne(), c)), None
    )


def premier_maillon_sans_place(motif, forme, a_loger, lus) -> int | None:
    """Le rang du premier maillon qu'aucun alignement ne loge ; None sinon.

    Un maillon loge dans une étoile qui contient sa classe — plusieurs de
    suite peuvent s'y loger —, ou dans une entrée s'il est un caractère
    unique qu'elle contient. Une étoile peut rester vide ; une entrée ne se
    saute pas, puisque tout ce qui la suit est dans son groupe.
    """

    @functools.cache
    def echec(i: int, k: int) -> int | None:
        if i == len(a_loger):
            return None
        if k == len(lus):
            return i
        entree, cible = lus[k]
        essais = []
        if (not entree or a_loger[i].unique) and debordement(
            motif, forme, i, cible
        ) is None:
            essais.append(echec(i + 1, k + 1 if entree else k))
        if not entree:
            essais.append(echec(i, k + 1))
        if not essais:
            return i
        return None if None in essais else max(essais)

    return echec(0, 0)


class TestRetenueDesAffectations:
    """§5 : _OPEN_ASSIGNMENT retient chaque début d'affectation — démontré."""

    def test_une_affectation_est_retenue_des_son_mot_cle(self):
        """§5 : un début d'affectation ne part jamais, sur tout Unicode.

        Soit M une correspondance commencée en s, dont le tampon ne tient
        encore que les t − s premiers caractères. _safe_prefix libère au plus
        min(t − réserve, début de _OPEN_ASSIGNMENT) : le recul au blanc ne fait
        que descendre. Deux cas :

        1. t − s < longueur du mot-clé ≤ réserve : t − réserve < s ;
        2. sinon texte[s:t] = mot-clé · maillons complets · maillon entamé.
           Si _OPEN_ASSIGNMENT connaît ce mot-clé (en ignorant la casse chaque
           fois que le motif l'ignore) et loge chaque maillon, dans l'ordre,
           dans sa propre chaîne, il accepte texte[s:t] jusqu'à \\Z : sa
           recherche, qui rend la correspondance la plus à gauche, commence
           en s ou avant.

        Le dernier maillon, s'il est un caractère unique (le guillemet
        fermant), n'entre dans aucun début strict : il n'a rien à loger.
        Chaque inclusion de classes se vérifie sur les 1 114 112 points de
        code ; une catégorie de scanner.rs (\\s) se mesure dans l'extension.
        """
        mots_retenus, casse_retenue, lus = retenue()
        fautes = []
        for motif in tous_les_motifs():
            if motif.nom not in AFFECTATIONS:
                continue
            forme = forme_du_motif(motif)
            if forme is None:
                fautes.append(
                    f"{motif} n'a plus la forme « mots-clés, puis classes "
                    "répétées » : la démonstration ne s'y applique pas. Borne-le, "
                    "ou apprends à ce test à lire sa forme."
                )
                continue
            if motif.fichier == "scanner.rs" and (
                forme.casse or any(m.drapeaux & re.IGNORECASE for m in forme.maillons)
            ):
                fautes.append(
                    f"{motif} ignore la casse : le (?i) de Rust ne se lit pas "
                    "comme celui de re, apprends à ce test à le mesurer."
                )
            inconnus = sorted(forme.mots_cles - mots_retenus)
            if inconnus:
                fautes.append(
                    f"{motif} : _OPEN_ASSIGNMENT (guardrails.py) ne connaît pas "
                    f"{inconnus} ; le flux diffuserait ce début d'affectation."
                )
            if forme.casse and not casse_retenue:
                fautes.append(
                    f"{motif} ignore la casse, _OPEN_ASSIGNMENT non : "
                    f"« {max(forme.mots_cles).upper()} = '… » partirait dans le flux."
                )
            trop_longs = sorted(m for m in forme.mots_cles if len(m) > _STREAM_HOLDBACK)
            if trop_longs:
                fautes.append(
                    f"{motif} : {trop_longs} dépassent la réserve de "
                    f"{_STREAM_HOLDBACK} caractères ; leur début partirait avant "
                    "que _OPEN_ASSIGNMENT ne les reconnaisse."
                )
            a_loger = forme.maillons
            if a_loger and a_loger[-1].unique:
                a_loger = a_loger[:-1]
            rang = premier_maillon_sans_place(motif, forme, a_loger, tuple(lus))
            if rang is not None:
                raisons = []
                for entree, cible in lus:
                    car = debordement(motif, forme, rang, cible)
                    if car is not None:
                        raisons.append(f"{cible} refuse {car!r} (U+{ord(car):04X})")
                    elif entree and not a_loger[rang].unique:
                        raisons.append(f"l'entrée {cible} ne prend qu'un caractère")
                    else:
                        raisons.append(f"{cible} le contient, mais pas à ce rang")
                fautes.append(
                    f"{motif} : son maillon {rang}, {a_loger[rang]}, ne loge nulle "
                    "part dans _OPEN_ASSIGNMENT (guardrails.py) — "
                    + " ; ".join(raisons)
                    + ". Un début d'affectation qui s'arrête là partirait dans le "
                    "flux : apprends cette forme à _OPEN_ASSIGNMENT."
                )
        assert not fautes, "\n".join(fautes)
