"""Vérifier les dessins exportés avant leur écriture hors de l'application."""

import re
import xml.etree.ElementTree as ET

from .store import SuccesError

BALISES = {
    "svg",
    "g",
    "defs",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "title",
    "desc",
    "marker",
    "linearGradient",
    "radialGradient",
    "stop",
    "clipPath",
    "mask",
    "pattern",
    "style",
    "use",
}
LOCAL = re.compile(r"url\(\s*['\"]?#[\w:.-]+['\"]?\s*\)", re.I)


def verifier_export(data: bytes, extension: str) -> None:
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise SuccesError("Ce fichier n'est pas un PDF.")
        return
    if extension == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if extension != ".svg":
        raise SuccesError("Le contenu ne correspond pas au format du fichier.")
    if (
        len(data) > 500_000
        or b"<!DOCTYPE" in data.upper()
        or b"<!ENTITY" in data.upper()
    ):
        raise SuccesError(
            "Ce SVG est trop grand ou contient une déclaration interdite."
        )
    try:
        racine = ET.fromstring(data.decode("utf-8-sig"))
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise SuccesError("Ce fichier n'est pas un SVG valide.") from exc
    if racine.tag != "{http://www.w3.org/2000/svg}svg":
        raise SuccesError("Ce fichier n'est pas un SVG valide.")
    elements = list(racine.iter())
    if len(elements) > 2500:
        raise SuccesError("Ce SVG contient trop d'éléments.")
    for el in elements:
        if (
            not el.tag.startswith("{http://www.w3.org/2000/svg}")
            or el.tag.split("}")[-1] not in BALISES
        ):
            raise SuccesError("Ce SVG contient un élément non autorisé.")
        for nom, valeur in el.attrib.items():
            nom = nom.split("}")[-1].lower()
            if (
                nom.startswith("on")
                or nom == "href"
                and not re.fullmatch(r"#[\w:.-]+", valeur)
            ):
                raise SuccesError("Ce SVG contient une action ou un lien externe.")
            verifier_style(valeur)
        if el.tag.endswith("}style"):
            verifier_style(el.text or "")


def verifier_style(valeur: str) -> None:
    # Même hors du WebView, un export ne doit pas contacter une ressource
    # distante : seuls les renvois internes (dégradés, flèches) sont permis.
    reste = LOCAL.sub("", valeur)
    if re.search(r"url\s*\(|@|\\|://|data:", reste, re.I):
        raise SuccesError("Ce SVG contient une ressource externe ou un style interdit.")
