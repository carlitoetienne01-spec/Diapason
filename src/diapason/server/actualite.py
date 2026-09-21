"""Une question d'actualité se vérifie sur le web avant d'être répondue.

20 septembre 2026, 22:30, dans le mini-panneau : « Qui est le président
actuel du Canada ? » → « Le président actuel du Canada est Justin Trudeau,
23e Premier ministre, en poste depuis 2015. » En 5,1 s, sans un seul appel
d'outil. Deux erreurs dans une phrase : le Canada n'a pas de président, et
le nom vient de l'entraînement du modèle, pas de septembre 2026. Le 9b
avait web_search sous la main et la règle « web_search — ce qui est récent »
dans son identité ; il a répondu de mémoire parce qu'il CROYAIT savoir.

Un petit modèle ne devine pas qu'un fait a pu changer : il faut le lui dire
au tour même, et vérifier qu'il l'a fait. Trois pièces :

- ``question_d_actualite`` reconnaît une question dont la réponse dépend du
  moment (fonction en cours, prix, résultat, sortie, météo, « actuel »,
  « aujourd'hui », une année récente) et qui ne porte pas sur les données
  personnelles de Carlito — celles-là ont leurs propres outils.
- ``consigne_actualite`` se pose au tour courant, comme le rappel des
  questions interactives : c'est là que le 9b obéit (constat du 19/09).
- ``CONSIGNE_FERME`` sert une seule relance quand le premier passage n'a
  quand même appelé aucun outil ; si la relance échoue aussi, la réponse
  part avec un avertissement en tête plutôt que comme une vérité.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from diapason.core.types import Message, Role

# Ce qui dépend du moment. Les accents sont retirés avant la recherche.
_MARQUEURS = re.compile(
    r"\b(?:actuel(?:le|lement)?|en ce moment|aujourd.hui|ces jours.ci|hier|"
    r"ce (?:soir|matin|week.end|mois)|cette (?:annee|semaine|nuit)|"
    r"dernier(?:e|es|s)?|recent(?:e|es|s|ement)?|"
    r"20(?:2[4-9]|3\d)|"
    r"current(?:ly)?|latest|right now|today|nowadays|these days|recently)\b"
)
# Ce qui change de titulaire ou de valeur sans prévenir. Revue du 20/09 :
# « résultat », « version », « match », « nouveau » seuls attrapaient
# « Écris le résultat de 2+2 » et « Écris un nouveau poème ».
_SUJETS = re.compile(
    r"\b(?:president(?:e)?|premier(?:e)? ministre|ministre|maire|gouverneur(?:e)?|"
    r"chancelier(?:e)?|roi|reine|pape|pdg|ceo|directeur|directrice|entraineur|"
    r"capitaine|champion(?:ne)?|vainqueur|gagnant(?:e)?|laureat(?:e)?|"
    r"prix|cout[e]?|tarif|taux|cours (?:du|de l')|bourse|inflation|"
    r"meteo|temperature|previsions?|pleuvoir|pluie|neige|neiger|"
    r"score|classement|election|sondage|coupe|championnat|tournoi|finale|"
    r"version|resultats? (?:du|de la|des)|salaire minimum|smic|loyer|essence|"
    r"carburant|nouvelles|actualites?|news|"
    r"prime minister|governor|price|weather|forecast)\b"
)
# Ces formes suffisent seules : elles désignent un titulaire ou un résultat
# par nature (revue du 20/09 : « Qui dirige le Canada ? » passait de tête).
_FAIT_SUFFISANT = re.compile(
    r"\b(?:qui (?:dirige|preside|gouverne|a (?:gagne|remporte))|"
    r"que se passe.t.il|qu'arrive.t.il|quoi de neuf|what's happening|who won)\b"
)
# La forme d'une question de fait : on cherche un titulaire, une valeur, une
# date. « Dis-moi qui est le président » et « J'aimerais savoir qui est… »
# en sont ; « Écris un nouveau poème » n'en est pas.
_QUESTION_DE_FAIT = re.compile(
    r"\b(?:qui (?:est|sont|dirige|preside|gouverne|a (?:gagne|remporte))|"
    r"quel(?:le|s|les)? (?:est|sont|temps|prix|taux|score|age|version)|"
    r"combien (?:coute|vaut|fait|font|de)|quand (?:est|sera|sort|aura lieu|commence)|"
    r"ou en est|c'est qui|c'est combien|est.ce que .+ (?:est|sont|toujours|encore)|"
    r"who is|who are|what is the|how much)\b"
)
# Les données de Carlito ne se cherchent pas sur le web : un possessif, une
# première personne conjuguée, un mot de ses modules. « Dis-moi » et « je
# veux savoir » n'excluent rien (revue du 20/09 : ils éteignaient tout).
_PERSONNEL = re.compile(
    r"\b(?:mon|ma|mes|nos|notre|my|our|ai.je|j'ai|dois.je|je dois|puis.je)\b|"
    r"\b(?:taches?|notes?|projets?|agenda|rendez.vous|rappels?|mails?|"
    r"courriels?|messages?|fichiers?|documents?|ecran|budget|depenses?|"
    r"planning|programme|horaire|emploi du temps)\b"
)
# Une définition, une traduction, une production ou l'histoire ancienne ne
# dépendent pas du jour. « C'est quoi un président ? » se définit ; « C'est
# quoi le taux directeur en 2026 ? » se cherche.
_INTEMPOREL = re.compile(
    r"^(?:que veut dire|que signifie|traduis|comment (?:dit.on|on dit|utiliser)|"
    r"c'est quoi (?:un|une|des)\s|definis|explique|decris|"
    r"qu'est.ce que c'est qu|"
    r"(?:ecris|redige|corrige|raconte|invente|compose|cree|genere|resume|"
    r"reformule|imagine|propose)\b)|"
    r"\b(?:histoire|biographie|en 1\d\d\d|en 20(?:0\d|1\d|2[0-3]))\b"
)


def _normaliser(texte: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texte.casefold())
        if not unicodedata.combining(c)
    ).strip()


def question_d_actualite(texte: str) -> bool:
    """Vrai si la réponse dépend du moment et ne concerne pas ses données.

    Une question de fait (« qui est », « quel est le prix ») sur un titulaire,
    une valeur ou avec un marqueur de temps ; ou un marqueur ET un sujet sans
    forme interrogative (« la météo à Ottawa aujourd'hui »).
    """
    plat = _normaliser(texte).replace("’", "'")
    if not plat or _PERSONNEL.search(plat) or _INTEMPOREL.search(plat):
        return False
    if _FAIT_SUFFISANT.search(plat):
        return True
    marqueur = bool(_MARQUEURS.search(plat))
    sujet = bool(_SUJETS.search(plat))
    if _QUESTION_DE_FAIT.search(plat):
        return marqueur or sujet
    return marqueur and sujet


def question_courante_d_actualite(messages: Sequence[Message]) -> bool:
    demande = next((m for m in reversed(messages) if m.role == Role.USER), None)
    if demande is None or demande.images:
        return False
    return question_d_actualite(demande.content or "")


CONSIGNE = (
    "Cette question porte sur une réalité qui a pu changer depuis ton "
    "entraînement : une fonction en cours, un prix, un résultat, une date. "
    "Appelle web_search maintenant avec une requête précise, puis réponds "
    "d'après les résultats en donnant la date de l'information et sa source. "
    "Si la recherche ne rend rien d'utile, dis que tu n'as pas pu vérifier — "
    "ne réponds pas de mémoire à cette question."
)
CONSIGNE_FERME = (
    "Tu as répondu sans appeler web_search. Cette réponse n'a pas été "
    "affichée. Appelle web_search maintenant, sans écrire de texte avant "
    "l'appel ; tu répondras après avoir lu les résultats."
)
AVERTISSEMENT = "⚠︎ Non vérifié en ligne — réponse de mémoire, qui peut dater.\n\n"
AVERTISSEMENT_RECHERCHE = (
    "⚠︎ La recherche web n'a rien donné — réponse de mémoire, qui peut dater.\n\n"
)
AVEU = "Je n'ai pas pu vérifier cette information en ligne."
# Ce que web_search rend quand il n'a rien : pas une vérification.
_RECHERCHE_VIDE = re.compile(
    r"^\s*(?:no results|aucun r[ée]sultat|search error|error)", re.I
)


def recherche_concluante(nom: str, succes: bool, contenu: str) -> bool:
    """Un web_search qui a rendu quelque chose : la seule vérification qui compte."""
    if nom != "web_search" or not succes:
        return False
    return bool(contenu.strip()) and not _RECHERCHE_VIDE.search(contenu)


def consigne_actualite(
    messages: Sequence[Message], texte: str = CONSIGNE
) -> list[Message]:
    """La consigne au tour courant, après la demande, comme le rappel des questions."""
    return [*messages, Message(role=Role.SYSTEM, content=texte)]
