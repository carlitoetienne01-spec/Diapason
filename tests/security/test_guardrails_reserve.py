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
  mot-clé par ``_OPEN_ASSIGNMENT``.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

import pytest

from diapason.security.guardrails import (
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
        sur des exemples qui débordent la réserve, il ne le démontre pas.
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
