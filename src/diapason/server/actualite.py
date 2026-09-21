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

import json
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

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
    r"\b(?:president(?:e)?|premier(?:e)? ministre|ministre|maire(?:sse)?|"
    r"gouverneur(?:e)?|chancelier(?:e)?|roi|reine|pape|pdg|ceo|directeur|"
    r"directrice|entraineur(?:e)?|chef(?:fe)? (?:du gouvernement|de l'etat|d'etat)|"
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
    "d'après les résultats : cite chaque fait par le numéro de sa source, "
    "comme [1], et donne la date de l'information quand elle est indiquée. "
    "Si les extraits ne donnent pas le fait demandé, appelle web_read sur "
    "l'URL de la source la plus pertinente avant de répondre. "
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


# Ce qui se périme en jours (météo, résultats, cours), et ce qui relève des
# journaux plutôt que du web général.
_TRES_FRAIS = re.compile(
    r"\b(?:aujourd.hui|hier|ce (?:soir|matin|week.end)|cette (?:semaine|nuit)|"
    r"meteo|temperature|pleuvoir|pluie|neige|scores?|matchs?|cours (?:du|de l')|"
    r"bourse|today|tonight|weather|right now)\b"
)
_JOURNAUX = re.compile(
    r"\b(?:meteo|pleuvoir|pluie|neige|elections?|sondages?|nouvelles|actualites?|"
    r"news|que se passe.t.il|qu'arrive.t.il|quoi de neuf|matchs?|coupe|"
    r"championnats?|finales?|scores?|quel temps|greves?|manifestations?|"
    r"seismes?|ouragans?|incendies?)\b"
)


def parametres_de_recherche(question: str) -> dict[str, Any]:
    """Fraîcheur et vertical décidés par le code, pas par le modèle.

    Une semaine pour ce qui se périme en jours, un an pour un titulaire ou
    une version ; les journaux d'abord pour ce qui fait l'actualité. Le
    modèle peut préciser davantage, jamais relâcher : ces clés ne sont posées
    que si l'appel ne les porte pas déjà.
    """
    plat = _normaliser(question).replace("’", "'")
    parametres: dict[str, Any] = {
        "recency": "week" if _TRES_FRAIS.search(plat) else "year"
    }
    if _JOURNAUX.search(plat):
        parametres["news"] = True
    return parametres


_FRAICHEURS_ORDONNEES = ("day", "week", "month", "year")


def completer_arguments(arguments: str, question: str) -> str:
    """Pose recency/news sur un appel web_search ; le modèle précise, jamais ne relâche.

    Revue du 20/09 : `recency: "recent"` (invalide) partait sans fraîcheur,
    `month` remplaçait la semaine décidée par le code, `news: false` éteignait
    le vertical. Le plus strict des deux gagne ; l'invalide vaut absent.
    """
    try:
        donnees = json.loads(arguments) if arguments else {}
    except (ValueError, TypeError):
        return arguments
    if not isinstance(donnees, dict):
        return arguments
    voulu = parametres_de_recherche(question)
    du_modele = str(donnees.get("recency") or "").lower()
    if du_modele not in _FRAICHEURS_ORDONNEES:
        donnees["recency"] = voulu["recency"]
    else:
        donnees["recency"] = min(
            du_modele, voulu["recency"], key=_FRAICHEURS_ORDONNEES.index
        )
    if voulu.get("news"):
        donnees["news"] = True
    return json.dumps(donnees, ensure_ascii=False)


# Ce que la réponse affirme et que les sources ne portent pas : années,
# nombres à unité, suites de mots capitalisés (noms propres). Un signal,
# jamais un verdict — les flexions et les traductions font des faux positifs.
_ANNEE = re.compile(r"\b(?:19|20)\d\d\b")
# Revue du 20/09 : « 2,75 % », « 1,63 $ », « 18 °C » — le \b final exigeait une
# lettre après le symbole ; ce sont pourtant les valeurs qui changent le plus.
_NOMBRE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:%|\$|€|°\s?[CF]?|km|kg|ans?|millions?|milliards?)(?!\w)"
)
_NOM_PROPRE = re.compile(
    r"\b[A-ZÀ-Ý][\wÀ-ÿ'’-]+(?:\s+(?:d[eu]s?|de la|du|la|le|van|von|el|al))?"
    r"(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'’-]+)+\b"
)


# Un début de phrase porte une majuscule sans être un nom : « Le Canada »,
# « Selon Radio-Canada ». On retire ces têtes avant de juger la suite.
_TETES_COMMUNES = frozenset(
    "le la les un une des du de d' au aux ce cette ces cet il elle ils elles on "
    "en et ou mais donc or ni car si selon depuis dans pour par sur sous avec "
    "sans apres avant quand comme voici voila c'est il y a the a an in on at "
    "actuellement aujourd'hui cependant toutefois pourtant ainsi alors puis "
    "ensuite enfin aussi encore hier demain maintenant notamment effectivement "
    "bref oui non d'apres selon premier premiere ministre president presidente "
    "monsieur madame m. mme dr".split()
)


def _sans_tete_commune(nom: str) -> str:
    mots = nom.split()
    while mots and _normaliser(mots[0]) in _TETES_COMMUNES:
        mots = mots[1:]
    return " ".join(mots) if len(mots) >= 2 else ""


def _nom_retrouve(nom: str, corpus: str) -> bool:
    """Un nom est retrouvé si une suite de deux de ses mots l'est, ou son dernier
    mot seul (le patronyme) — « Actuellement Mark Carney » ne doit pas alerter
    quand les sources disent « Mark Carney » (revue du 20/09)."""
    mots = [_normaliser(m) for m in nom.split()]
    if _normaliser(nom) in corpus:
        return True
    for i in range(len(mots) - 1):
        if f"{mots[i]} {mots[i + 1]}" in corpus:
            return True
    dernier = mots[-1] if mots else ""
    if len(dernier) < 4:
        return False
    return re.search(rf"\b{re.escape(dernier)}\b", corpus) is not None


def _compacter(valeur: str) -> str:
    """« 2,75 % » et « 2.75% » sont la même valeur."""
    return re.sub(r"\s+", "", _normaliser(valeur)).replace(",", ".")


def _valeur_retrouvee(valeur: str, corpus_compact: str) -> bool:
    """« 5 % » n'est pas dans « 2,75 % » : la valeur doit commencer à un chiffre
    qui n'en prolonge pas un autre."""
    motif = r"(?<![\d.])" + re.escape(_compacter(valeur)) + r"(?!\d)"
    return re.search(motif, corpus_compact) is not None


def elements_hors_sources(reponse: str, sources: str, question: str = "") -> list[str]:
    """Les affirmations datées ou nommées de la réponse absentes des sources.

    Les mots de la question ne comptent pas (ils viennent de Carlito), ni
    l'année du jour (le contexte MAINTENANT la donne au modèle).
    """
    if not reponse.strip() or not sources.strip():
        return []
    from datetime import date

    corpus = _normaliser(sources) + "\n" + _normaliser(question)
    corpus_compact = _compacter(sources) + "\n" + _compacter(question)
    annee_du_jour = str(date.today().year)
    candidats: list[str] = []
    candidats += [a for a in _ANNEE.findall(reponse) if a != annee_du_jour]
    candidats += [m.strip() for m in _NOMBRE.findall(reponse)]
    # Un mot seul en début de phrase porte aussi une majuscule : on ne retient
    # que les suites d'au moins deux mots capitalisés (Mark Carney, Coupe Stanley).
    for m in _NOM_PROPRE.finditer(reponse):
        nom = _sans_tete_commune(m.group(0).strip())
        if nom:
            candidats.append(nom)
    manquants: list[str] = []
    for c in candidats:
        if c in manquants:
            continue
        if c[0].isdigit():
            if not _valeur_retrouvee(c, corpus_compact):
                manquants.append(c)
        elif not _nom_retrouve(c, corpus):
            manquants.append(c)
    return manquants[:6]


# ---------------------------------------------------------------------------
# Ce que le code sait des sources avant que le modèle rédige (21/09/2026).
#
# « Qui est le premier ministre du Canada ? » : la recherche a tourné, cinq
# sources datées d'hier et d'avant-hier, et le 9b a écrit « Justin Trudeau
# [3] ». Aucun extrait ne nommait le titulaire ; la page Wikipédia du poste
# le fait, dans son infobox (« Titulaire actuel | Mark Carney »). Le modèle
# ne saura jamais seul qu'un extrait pris au hasard ne répond pas : le code
# lit la page du poste, relève qui les sources désignent comme titulaire, et
# le lui dit — avec le numéro de la source. Il mesure aussi l'âge des
# sources : une réponse sur des pages d'il y a deux ans doit le dire.
# ---------------------------------------------------------------------------

# Les fonctions dont le titulaire change sans que le modèle le sache — au
# féminin aussi (revue du 21/09 : « Qui est la mairesse de Montréal ? »
# passait de tête), et sans leurs adjoints (« vice-président »).
_TITULAIRES = re.compile(
    r"\b(?:(?<!vice-)(?<!vice )president(?:e)?|premier(?:e)? ministre|ministre|"
    r"maire(?:sse)?|gouverneur(?:e)?|chancelier(?:e)?|roi|reine|pape|pdg|ceo|"
    r"(?<!taux )directeur|directrice|entraineur(?:e)?|capitaine|chef(?:fe)?|"
    r"prime minister|(?<!vice )president|governor|chancellor|king|queen|pope|"
    r"mayor|head of state|head coach)\b"
)
# La question doit demander UN NOM : « Quel est le salaire du premier
# ministre ? » nomme la fonction sans chercher son titulaire (revue du 21/09 :
# la page du poste était lue et le modèle sommé de « répondre avec ce nom »).
_DEMANDE_UN_NOM = re.compile(
    r"\b(?:qui|who|c'est qui|comment s'appelle|quel est le nom|nom d[eu]|"
    r"what is the name)\b"
)
# « Titulaire actuel » (infobox), « incumbent », « current holder » parlent
# d'une fonction par nature. « actuel », « current », « depuis », « en poste »
# parlent de n'importe quoi — « Katie Telford is currently a producer »
# désignait une titulaire (21/09) : ceux-là exigent le mot de la fonction
# collé. « titulaire » seul ne vaut rien : « Premier titulaire | John A.
# Macdonald », « titulaire précédent » (revue du 21/09 : neuf pages de poste
# sur dix désignaient un ancien).
_EN_PLACE_PAR_NATURE = re.compile(
    r"\b(?:titulaire actuel(?:le)?|incumbent|current (?:office ?)?holder)\b", re.I
)
_EN_PLACE = re.compile(
    r"\b(?:actuel(?:le|lement)?|en poste|en fonction|en exercice|depuis le|"
    r"current(?:ly)?|since)\b",
    re.I,
)
# Un marqueur qui parle du passé : « premier titulaire », « ancien titulaire »,
# « en poste de 2015 à 2025 », « en fonction jusqu'en 2020 ».
_MARQUEUR_HISTORIQUE_AVANT = re.compile(
    r"\b(?:premier|premiere|ancien(?:ne)?|ex|precedent(?:e)?|dernier(?:e)?|"
    r"first|former|previous|last|late)\W{0,3}$",
    re.I,
)
_MARQUEUR_HISTORIQUE_APRES = re.compile(
    r"^\W{0,3}(?:d[eu] \d{4}|from \d{4}|jusqu'(?:en|au)|until|\(?\d{4}\s?[-–]\s?\d{4})",
    re.I,
)
# La fonction demandée en français et en anglais : les pages Wikipédia
# anglaises disent « prime minister » quand la question dit « premier
# ministre ». Le mot seul (« ministre ») vaut pour tous les ministères, sauf
# le premier — « le premier ministre actuel » répondait à « qui est le
# ministre des Finances ? » (21/09).
_FONCTIONS_EQUIVALENTES: dict[str, str] = {
    "premier ministre": r"premi[eè]re? ministre|prime minister",
    "president": r"(?<!vice-)(?<!vice )president(?:e)?",
    "ministre": r"(?<!premier[ _])(?<!premiere[ _])(?<!prime[ _])(?:ministre|minister)",
    "maire": r"maire(?:sse)?|mayor",
    "gouverneur": r"gouverneur(?:e)?|governor",
    "chancelier": r"chancelier(?:e)?|chancellor",
    "roi": r"\broi\b|\bking\b",
    "reine": r"\breine\b|\bqueen\b",
    "pape": r"\bpape\b|\bpope\b",
    "pdg": r"\bpdg\b|\bceo\b|chief executive",
    "ceo": r"\bpdg\b|\bceo\b|chief executive",
    "directeur": r"directeur|directrice|director",
    "directrice": r"directeur|directrice|director",
    "entraineur": r"entraineur(?:e)?|head coach|\bcoach\b",
    "capitaine": r"capitaine|captain",
    "chef": r"\bchef(?:fe)?\b|\bhead\b|\bleader\b",
    "prime minister": r"premi[eè]re? ministre|prime minister",
    "governor": r"gouverneur(?:e)?|governor",
    "chancellor": r"chancelier(?:e)?|chancellor",
    "king": r"\broi\b|\bking\b",
    "queen": r"\breine\b|\bqueen\b",
    "pope": r"\bpape\b|\bpope\b",
    "mayor": r"maire(?:sse)?|mayor",
    "head coach": r"entraineur(?:e)?|head coach|\bcoach\b",
}
# Ce qui précède un nom quand il n'est PAS le titulaire : « après la démission
# de Justin Trudeau », « former prime minister … », « the late Queen ».
# Relevé sur la page Wikipédia du poste, le 21/09 : le prédécesseur est à
# 40 caractères du mot « actuel ».
_PREDECESSEUR = re.compile(
    r"(?:ancien(?:ne)?s?|ex|former|previous|precedent(?:e)?s?|predecesseur|"
    r"predecessor|demission d[e']|succed(?:e|ant|er) a|succeed(?:ed|ing|s)|"
    r"took over from|takes over from|remplace|replaced|apres|after|late|"
    r"sortant(?:e)?|feu|defunt(?:e)?)\W{0,3}$",
    re.I,
)
# Les mots d'une fonction ne sont pas un nom (« Prime Minister of Canada »),
# et collés à un nom ils n'en font pas un autre (« Prime Minister Mark
# Carney » et « Mark Carney » sont le même homme — revue du 21/09).
_MOTS_DE_FONCTION = frozenset(
    "prime minister ministre president presidente premier premiere governor "
    "gouverneur gouverneure general generale chancellor chancelier king queen "
    "roi reine pope pape mayor maire mairesse head state chef cheffe "
    "gouvernement etat cabinet parliament parlement canada quebec ontario "
    "ottawa france pdg ceo director directeur directrice coach entraineur "
    "captain capitaine sir dame lord lady honorable honourable tres right "
    "excellence majesty majeste "
    # Les intitulés de ministères s'écrivent en majuscules en anglais :
    # « Minister of Finance and National Revenue » faisait un titulaire de
    # « National Revenue » (21/09).
    "finance finances revenue revenu national nationale foreign affairs "
    "affaires defence defense health sante education justice interior "
    "interieur treasury tresor secretary secretaire industry industrie "
    "environment environnement transport labour travail immigration "
    "citizenship trade commerce economy economie energy energie public safety "
    "securite of and et des du de la le".split()
)
# Les mots de la question qui disent DE QUOI la fonction est la fonction :
# « Canada », « Québec », « Montréal », « Apple ». Une source dont l'en-tête
# ne porte aucun d'eux ne parle pas de ce poste — « premier ministre du
# Québec » recevait Mark Carney (revue du 21/09).
_MOTS_VIDES_DE_QUESTION = frozenset(
    "actuel actuelle actuellement aujourd'hui maintenant encore toujours "
    "quel quelle quels quelles dans avec pour sans sous vers chez cette ceux "
    "celle celles comment combien quand pourquoi what who whom whose which "
    "when where current currently today right now name nom".split()
)
_PORTEE_DU_MARQUEUR = 120
_AVANT_LE_NOM = 30
_AVANT_LE_MARQUEUR = 25
_EN_TETE_DE_SOURCE = re.compile(r"^\[(\d+)\]\s*(.*)$", re.M)
_DATE_ISO = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


def _plat(question: str) -> str:
    return _normaliser(question).replace("’", "'")


def question_de_titulaire(question: str) -> bool:
    """Une question qui demande le NOM d'une personne en fonction."""
    plat = _plat(question)
    if not plat:
        return False
    if _FAIT_SUFFISANT.search(plat) and re.search(
        r"\bqui (?:dirige|preside|gouverne)", plat
    ):
        return True
    return (
        _TITULAIRES.search(plat) is not None
        and _DEMANDE_UN_NOM.search(plat) is not None
    )


def _fonction_demandee(question: str) -> str:
    m = _TITULAIRES.search(_plat(question))
    return m.group(0) if m else ""


def _motif_de_la_fonction(question: str) -> re.Pattern[str] | None:
    """Le mot de la fonction demandée, dans les deux langues ; None quand la
    question n'en nomme pas (« Qui dirige le Canada ? ») — deux fonctions,
    deux noms, un faux désaccord (revue du 21/09)."""
    fonction = _fonction_demandee(question)
    fonction = re.sub(r"(?:premiere?|premier) ministre", "premier ministre", fonction)
    fonction = re.sub(r"president(?:e)?$", "president", fonction)
    for cle, motif in _FONCTIONS_EQUIVALENTES.items():
        if fonction.startswith(cle):
            return re.compile(motif, re.I)
    return re.compile(re.escape(fonction), re.I) if fonction else None


# Un lieu se dit autrement dans la page que dans la question : « États-Unis »
# → « United States », « Royaume-Uni » → « britannique ». Les radicaux (cinq
# lettres) couvrent « Canada »/« canadien », « Québec »/« québécois ».
_LIEUX_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "etats": ("united states", "etats unis", "usa", "americain", "american"),
    "unis": ("united states", "etats unis", "usa", "americain", "american"),
    "royaume": ("united kingdom", "royaume uni", "britan", "british", "england"),
    "france": ("france", "francais", "french"),
    "allemagne": ("allemagne", "germany", "german", "allemand"),
    "espagne": ("espagne", "spain", "spanish", "espagnol"),
    "italie": ("italie", "italy", "italian", "italien"),
    "japon": ("japon", "japan", "japanese", "japonais"),
    "chine": ("chine", "china", "chinese", "chinois"),
    "russie": ("russie", "russia", "russian", "russe"),
    "mexique": ("mexique", "mexico", "mexican", "mexicain"),
    "bresil": ("bresil", "brazil", "brazilian", "bresilien"),
    "haiti": ("haiti", "haitian", "haitien"),
}
_MOTS_GRAMMATICAUX = frozenset("des du de la le les et of the and une un".split())


def _ressort(question: str) -> set[str]:
    """Les mots de la question qui situent la fonction : pays, ville, société."""
    plat = _TITULAIRES.sub(" ", _plat(question)).replace("'", " ").replace("-", " ")
    return {
        m
        for m in re.findall(r"[a-z]{4,}", plat)
        if m not in _MOTS_VIDES_DE_QUESTION and m not in _MOTS_GRAMMATICAUX
    }


def _situe(ressort: set[str], en_tete_plat: str) -> bool:
    """L'en-tête d'une source situe-t-il la fonction demandée ?"""
    if not ressort:
        return True
    for mot in ressort:
        if mot[:5] in en_tete_plat:
            return True
        if any(eq in en_tete_plat for eq in _LIEUX_EQUIVALENTS.get(mot, ())):
            return True
    return False


_LISTE = re.compile(r"^(?:liste|list of)\b")


def page_de_reference(sources: Sequence[dict[str, Any]], question: str) -> str:
    """L'URL de la page qui décrit la FONCTION, à lire en entier.

    D'abord une page dont le titre porte la fonction demandée (« Premier
    ministre du Canada — Wikipédia », « Maire de Montréal » pour « la
    mairesse »), en écartant les listes (« Liste des Premiers ministres » ne
    dit pas qui est en poste) et, entre deux, celle dont le titre reprend le
    plus de mots de la question (« du Canada » avant « du Québec ») ; sinon
    la première page Wikipédia ; sinon rien — on ne lit pas une page au
    hasard.
    """
    fonction = _motif_de_la_fonction(question)
    if fonction is None:
        return ""
    candidates = [s for s in sources if isinstance(s, dict) and s.get("url")]
    mots = _ressort(question)
    meilleure: tuple[int, int, str] | None = None
    for rang, s in enumerate(candidates):
        titre = _plat(str(s.get("title") or ""))
        if fonction.search(titre) and not _LISTE.match(titre):
            score = sum(1 for m in mots if m in titre)
            if meilleure is None or score > meilleure[0]:
                meilleure = (score, rang, str(s["url"]))
    if meilleure is not None:
        return meilleure[2]
    # Sans page de la fonction, une page Wikipédia — celle dont le titre situe
    # la question, avant une biographie : « Qui est le président actuel du
    # Canada ? » lisait la biographie de Justin Trudeau (essai du 21/09).
    for rang, s in enumerate(candidates):
        url = str(s["url"])
        titre = _normaliser(str(s.get("title") or ""))
        if "wikipedia.org" in url and not _LISTE.match(titre):
            score = sum(1 for m in mots if m in titre)
            if meilleure is None or score > meilleure[0]:
                meilleure = (score, rang, url)
    return meilleure[2] if meilleure is not None else ""


def _blocs_de_sources(corpus: str) -> list[tuple[int, str, str, str]]:
    """(numéro, date, en-tête, texte) par source, d'après les lignes « [N] … »."""
    blocs: list[tuple[int, str, str, str]] = []
    positions = list(_EN_TETE_DE_SOURCE.finditer(corpus))
    for i, m in enumerate(positions):
        fin = positions[i + 1].start() if i + 1 < len(positions) else len(corpus)
        texte = corpus[m.start() : fin]
        dates = _DATE_ISO.findall(m.group(2))
        # L'en-tête et la ligne « Source: url » disent de quoi parle la page.
        lignes = texte.split("\n")
        en_tete = " ".join(lignes[:2]).replace("_", " ")
        blocs.append((int(m.group(1)), max(dates) if dates else "", en_tete, texte))
    return blocs


def _est_un_nom(nom: str) -> bool:
    mots = [_normaliser(m) for m in nom.split()]
    return bool(mots) and not all(m in _MOTS_DE_FONCTION for m in mots)


def _sans_fonction_en_tete(nom: str) -> str:
    """« Prime Minister Mark Carney » → « Mark Carney » : le titre collé au
    nom ne fait pas un second titulaire."""
    mots = nom.split()
    while mots and (
        _normaliser(mots[0]) in _TETES_COMMUNES
        or _normaliser(mots[0]) in _MOTS_DE_FONCTION
    ):
        mots = mots[1:]
    return " ".join(mots) if len(mots) >= 2 else ""


def _cle_de_nom(nom: str) -> str:
    """Deux mentions du même homme comptent une fois : le patronyme suffit."""
    mots = [_normaliser(m) for m in nom.split()]
    return mots[-1] if mots and len(mots[-1]) >= 4 else " ".join(mots)


def titulaires_selon_sources(corpus: str, question: str = "") -> list[dict[str, Any]]:
    """Qui les sources désignent comme titulaire en place, et où.

    Seules comptent les sources dont l'en-tête situe la fonction demandée
    (« Canada » pour « premier ministre du Canada »). Dans chacune, ligne par
    ligne : le nom propre le plus proche d'un marqueur de fonction en cours
    (« Titulaire actuel », « incumbent » ; ou « actuel », « current »,
    « depuis » collés au mot de la fonction), sauf marqueur historique
    (« premier titulaire », « en poste de 2015 à 2025 ») ou nom précédé d'un
    mot de prédécesseur. Un signal tiré des sources, jamais une vérité : la
    réponse cite, le code compare. Résultat trié : le plus récent d'abord.
    """
    fonction = _motif_de_la_fonction(question)
    if fonction is None:
        return []
    ressort = _ressort(question)
    trouves: dict[str, dict[str, Any]] = {}
    # Ligne par ligne : une ligne est un paragraphe, une rangée d'infobox ou
    # un extrait. Sur le bloc entier, « …du Canada\nTitulaire actuel » faisait
    # un nom de « Canada Titulaire » (constaté le 21/09).
    for ref, date, en_tete, texte in _blocs_de_sources(corpus):
        en_tete_plat = _normaliser(en_tete).replace("-", " ")
        if not _situe(ressort, en_tete_plat):
            continue
        # « Titulaire actuel » désigne la fonction de SA page : la fonction
        # demandée doit ouvrir la page (titre, début), sinon c'est l'infobox
        # d'un autre poste — la page du premier ministre parle bien quelque
        # part « du ministre des Finances » (revue du 21/09).
        tete_de_page = _normaliser(en_tete + " " + texte[:400]).replace("_", " ")
        fonction_du_bloc = fonction.search(tete_de_page) is not None
        for ligne in texte.split("\n"):
            for nom, par_nature in _titulaires_de_la_ligne(
                ligne, fonction, fonction_du_bloc
            ):
                cle = _cle_de_nom(nom)
                connu = trouves.get(cle)
                if connu is None or (date and date > connu["date"]):
                    trouves[cle] = {
                        "nom": nom,
                        "ref": ref,
                        "date": date,
                        "par_nature": par_nature or bool(connu and connu["par_nature"]),
                    }
    # Une rangée « Titulaire actuel | Nom » l'emporte sur les phrases : la
    # page du pape désignait Léon XIV (infobox) ET Robert Francis Prevost
    # (« élu pape … est le pape actuel ») — le même homme (revue du 21/09).
    if any(t["par_nature"] for t in trouves.values()):
        trouves = {k: t for k, t in trouves.items() if t["par_nature"]}
    return sorted(
        (
            {"nom": t["nom"], "ref": t["ref"], "date": t["date"]}
            for t in trouves.values()
        ),
        key=lambda t: t["date"],
        reverse=True,
    )


def _sans_accents_meme_longueur(texte: str) -> str:
    """Les accents en moins, chaque caractère à sa place : les positions des
    noms (relevées sur l'original, pour les majuscules) restent valables sur
    le texte où l'on cherche les marqueurs. ``_normaliser`` change la longueur
    (« œ » → « oe », « ß » → « ss »)."""
    sortie = []
    for c in texte:
        plat = "".join(
            ch
            for ch in unicodedata.normalize("NFKD", c)
            if not unicodedata.combining(ch)
        )
        sortie.append(plat if len(plat) == 1 else c)
    return "".join(sortie)


# Un marqueur générique (« actuel », « current ») ne désigne le titulaire que
# collé à la fonction : « current prime minister », « premier ministre
# actuel », « l'actuel premier ministre » — deux mots d'écart au plus.
# « …the 23rd prime minister from 2015 to 2025. His former chief of staff
# Katie Telford is currently a producer » avait « prime minister » à
# 75 caractères de « currently » (21/09).
_MOTS_D_ECART = 2
# Entre la grappe « fonction + marqueur » et le nom, seulement ce qui lie un
# sujet à son attribut : « X est le premier ministre actuel », « le premier
# ministre actuel, X », « Titulaire actuel | X », « the current prime minister
# is X ». « Le premier ministre actuel doit rencontrer Donald Trump » désignait
# Trump : le nom le plus proche n'est pas le sujet (revue du 21/09).
_MOTS_DE_LIAISON = frozenset(
    "est is was devient becomes became le la l the du de des of d un une a an "
    "actuel actuelle current nouveau nouvelle new et and".split()
)
_ORDINAL = re.compile(r"^\d+(?:e|er|re|eme|th|st|nd|rd)?$")


def _liaison_ok(gap: str) -> bool:
    """« Incumbent | Pope Leo XIV » : le titre collé au nom (« Pope ») est
    dans l'écart, il ne le rompt pas."""
    mots = re.findall(r"[a-z0-9']+", _normaliser(gap))
    if len(mots) > 6:
        return False
    return all(
        m in _MOTS_DE_LIAISON or m in _MOTS_DE_FONCTION or _ORDINAL.match(m)
        for m in mots
    )


# Un marqueur dont la grappe parle du passé ne désigne personne : « since
# the first president, George Washington », « premier titulaire », « en poste
# de 2015 à 2025 ».
_GRAPPE_HISTORIQUE = re.compile(
    r"\b(?:first|premier|premiere|former|ancien(?:ne)?|late|previous|"
    r"dernier(?:e)?|last|inaugural|precedent(?:e)?)\b",
    re.I,
)


def _grappe(
    plat: str, marque: re.Match[str], fonction: re.Pattern[str], par_nature: bool
) -> tuple[int, int] | None:
    """L'étendue « fonction + marqueur » autour d'un marqueur, ou None si un
    marqueur générique n'est pas collé à la fonction."""
    if par_nature:
        return marque.start(), marque.end()
    depart = max(0, marque.start() - 80)
    avant = plat[depart : marque.start()]
    apres = plat[marque.end() : marque.end() + 80]
    devant = re.compile(
        rf"(?:{fonction.pattern})\W+(?:\w+\W+){{0,{_MOTS_D_ECART}}}$", re.I
    )
    derriere = re.compile(
        rf"^\W+(?:\w+\W+){{0,{_MOTS_D_ECART}}}(?:{fonction.pattern})", re.I
    )
    m1 = devant.search(avant)
    m2 = derriere.search(apres)
    if m1 is None and m2 is None:
        return None
    debut = depart + m1.start() if m1 else marque.start()
    fin = marque.end() + m2.end() if m2 else marque.end()
    return debut, fin


def _marqueur_historique(
    plat: str, grappe: tuple[int, int], fonction: re.Pattern[str]
) -> bool:
    debut, fin = grappe
    avant = plat[max(0, debut - _AVANT_LE_MARQUEUR) : debut]
    apres = plat[fin : fin + 30]
    # La fonction elle-même peut porter « premier » (premier ministre) : on
    # juge la grappe sans elle.
    reste = fonction.sub(" ", plat[debut:fin])
    return (
        _GRAPPE_HISTORIQUE.search(reste) is not None
        or _MARQUEUR_HISTORIQUE_AVANT.search(avant) is not None
        or _MARQUEUR_HISTORIQUE_APRES.search(apres) is not None
    )


def _noms_de_la_ligne(ligne: str) -> list[tuple[int, int, str]]:
    noms = []
    for m in _NOM_PROPRE.finditer(ligne):
        nom = _sans_fonction_en_tete(m.group(0).strip())
        if nom and _est_un_nom(nom):
            debut = m.start() + m.group(0).index(nom.split()[0])
            noms.append((debut, debut + len(nom), nom))
    return noms


def _titulaires_de_la_ligne(
    ligne: str, fonction: re.Pattern[str], fonction_du_bloc: bool = True
) -> list[tuple[str, bool]]:
    """(nom, désigné par un marqueur de nature) par marqueur retenu de la ligne."""
    trouves: list[tuple[str, bool]] = []
    noms = _noms_de_la_ligne(ligne)
    if not noms:
        return trouves
    plat = _sans_accents_meme_longueur(ligne).replace("’", "'")
    marques = [(m, True) for m in _EN_PLACE_PAR_NATURE.finditer(plat)]
    marques += [(m, False) for m in _EN_PLACE.finditer(plat)]
    for marque, par_nature in marques:
        if par_nature and not fonction_du_bloc:
            continue
        grappe = _grappe(plat, marque, fonction, par_nature)
        if grappe is None or _marqueur_historique(plat, grappe, fonction):
            continue
        debut_grappe, fin_grappe = grappe
        meilleur = None
        for debut, fin, nom in noms:
            if fin <= debut_grappe:
                liaison, distance = plat[fin:debut_grappe], debut_grappe - fin
            elif debut >= fin_grappe:
                liaison, distance = plat[fin_grappe:debut], debut - fin_grappe
            else:
                continue
            if distance > _PORTEE_DU_MARQUEUR or not _liaison_ok(liaison):
                continue
            if _PREDECESSEUR.search(plat[max(0, debut - _AVANT_LE_NOM) : debut]):
                continue
            if meilleur is None or distance < meilleur[0]:
                meilleur = (distance, nom)
        if meilleur is not None:
            trouves.append((meilleur[1], par_nature))
    return trouves


# Au-delà de cet âge, la source la plus récente ne suffit plus à répondre sans
# le dire : sept jours pour ce qui se périme en jours (météo, cours, scores),
# un an pour un titulaire ou une version — « 1 year ago » compris.
_AGE_MAX_JOURS_TRES_FRAIS = 7
_AGE_MAX_JOURS = 365


def sources_datees(sources: Sequence[dict[str, Any]], question: str) -> str:
    """La date de la source la plus récente si elle est trop vieille pour la
    question ; "" si les sources sont assez fraîches — ou si l'une d'elles
    n'est pas datée : sans date, on ne dit rien (§5 ; revue du 21/09 — la
    source non datée est souvent la bonne)."""
    from datetime import date, timedelta

    liste = [s for s in sources if isinstance(s, dict)]
    if not liste:
        return ""
    dates = sorted(str(s.get("date") or "") for s in liste)
    if not all(_DATE_ISO.fullmatch(d) for d in dates):
        return ""
    plat = _plat(question)
    age_max = _AGE_MAX_JOURS_TRES_FRAIS if _TRES_FRAIS.search(plat) else _AGE_MAX_JOURS
    plus_recente = dates[-1]
    if plus_recente <= (date.today() - timedelta(days=age_max)).isoformat():
        return plus_recente
    return ""


def _libelle(t: dict[str, Any]) -> str:
    libelle = f"{t['nom']} [{t['ref']}]"
    if t.get("date"):
        libelle += f" ({t['date']})"
    return libelle


def note_avant_redaction(
    sources: Sequence[dict[str, Any]], corpus: str, question: str
) -> tuple[str, dict[str, Any]]:
    """(consigne SYSTEM pour le modèle ou "", données pour l'interface).

    Deux constats mécaniques, chacun posé seulement s'il est établi : l'âge
    des sources quand elles sont trop vieilles pour la question, et le nom
    que les sources désignent comme titulaire quand la question en cherche
    un. Deux noms différents → retenir le plus récent et nommer le désaccord.
    Le tout recalculé à chaque passage : ce qui est rendu REMPLACE la note
    et les données précédentes.
    """
    lignes: list[str] = []
    donnees: dict[str, Any] = {}
    vieille = sources_datees(sources, question)
    if vieille:
        lignes.append(
            f"Les sources trouvées datent au plus du {vieille} : dis-le dans ta "
            "réponse, la situation a pu changer depuis."
        )
        donnees["sourcesDatees"] = vieille
    if question_de_titulaire(question):
        titulaires = titulaires_selon_sources(corpus, question)
        if len(titulaires) == 1:
            seul = _libelle(titulaires[0])
            lignes.append(
                f"Les sources désignent {seul} comme titulaire actuel : appuie-toi "
                "dessus et cite cette source ; ne nomme pas un prédécesseur "
                "comme titulaire."
            )
        elif titulaires:
            lignes.append(
                "Les sources désignent plusieurs titulaires : "
                + " ; ".join(_libelle(t) for t in titulaires)
                + ". Retiens la source la plus récente et nomme le désaccord."
            )
    return "\n".join(lignes), donnees


def _nomme_un_predecesseur(nom: str, corpus: str) -> bool:
    """Le nom apparaît dans les sources précédé d'un mot de prédécesseur
    (« après la démission de Justin Trudeau », « former … »)."""
    for ligne in corpus.split("\n"):
        plat = _sans_accents_meme_longueur(ligne)
        for debut, _fin, candidat in _noms_de_la_ligne(ligne):
            if _cle_de_nom(candidat) != _cle_de_nom(nom):
                continue
            if _PREDECESSEUR.search(plat[max(0, debut - _AVANT_LE_NOM) : debut]):
                return True
    return False


def desaccord_sur_le_titulaire(
    reponse: str, corpus: str, question: str
) -> dict[str, Any] | None:
    """La réponse nomme quelqu'un que les sources ne désignent pas comme
    titulaire : {"reponse": nom, "sources": [noms]}, sinon None.

    Seulement quand les sources désignent UN titulaire (deux, c'est déjà un
    désaccord entre elles, pas avec la réponse), que la réponse nomme au
    moins une personne, et que cette personne est bien donnée comme
    prédécesseur quelque part dans les sources — sans cela, le signal
    reposerait sur l'extraction seule, qui se trompe (revue du 21/09).
    """
    if not question_de_titulaire(question):
        return None
    titulaires = titulaires_selon_sources(corpus, question)
    if len(titulaires) != 1:
        return None
    attendu = titulaires[0]["nom"]
    noms_de_la_reponse: list[str] = []
    for _debut, _fin, nom in _noms_de_la_ligne(reponse.replace("\n", " ")):
        if nom not in noms_de_la_reponse:
            noms_de_la_reponse.append(nom)
    if not noms_de_la_reponse:
        return None
    if any(_cle_de_nom(n) == _cle_de_nom(attendu) for n in noms_de_la_reponse):
        return None
    if any(_nom_retrouve(attendu, _normaliser(n)) for n in noms_de_la_reponse):
        return None
    coupable = next(
        (n for n in noms_de_la_reponse if _nomme_un_predecesseur(n, corpus)), None
    )
    if coupable is None:
        return None
    return {"reponse": coupable, "sources": [attendu]}
