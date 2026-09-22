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
# « demain » est un marqueur (essai du 21/09 : « Va-t-il pleuvoir demain à
# Montréal ? » passait sans consigne ni page officielle).
_MARQUEURS = re.compile(
    r"\b(?:actuel(?:le|lement)?|en ce moment|aujourd.hui|ces jours.ci|hier|demain|"
    r"apres.demain|ce (?:soir|matin|week.end|mois)|cette (?:annee|semaine|nuit)|"
    r"dernier(?:e|es|s)?|recent(?:e|es|s|ement)?|"
    r"20(?:2[4-9]|3\d)|"
    r"current(?:ly)?|latest|right now|today|tonight|tomorrow|nowadays|these days|"
    r"recently)\b"
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
    r"(?:va|vont|fera|fait|y a|y aura)[- ]t[- ](?:il|elle|ils|elles)|"
    r"est.ce qu'il (?:va|fera|fait|pleut|neige)|"
    r"who is|who are|what is the|how much|will it|is it going to)\b"
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


def _plat(question: str) -> str:
    return _normaliser(question).replace("’", "'")


# Ce que l'horloge locale répond : ni mémoire, ni web. Revue vocale du
# 21/09 : « Quelle est la date aujourd'hui ? » recevait la consigne, le
# modèle appelait current_time, et la voix concluait « je le dis de
# mémoire, sans avoir pu vérifier en ligne » — faux sur la provenance.
_HORLOGE = re.compile(
    r"\b(?:quel(?:le)?(?: est)? (?:la |le |l')?(?:heure|date)\b|"
    r"quel jour (?:on est|sommes|est-on|est-ce)|quel jour\s*\??$|"
    r"l'heure(?: qu'il est| actuelle)?\b|il est quelle heure|"
    r"la date d'aujourd'hui|on est (?:quel|le combien)|"
    r"what time|what day|what's the date|what is the date)"
)


def question_d_actualite(texte: str) -> bool:
    """Vrai si la réponse dépend du moment et ne concerne pas ses données.

    Une question de fait (« qui est », « quel est le prix ») sur un titulaire,
    une valeur ou avec un marqueur de temps ; ou un marqueur ET un sujet sans
    forme interrogative (« la météo à Ottawa aujourd'hui »).
    """
    plat = _normaliser(texte).replace("’", "'")
    if not plat or _PERSONNEL.search(plat) or _INTEMPOREL.search(plat):
        return False
    if _HORLOGE.search(plat):
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
AVEU = "Je n'ai pas pu vérifier cette information en ligne."
# Pour les clients qui ne lisent pas l'événement « verification » (curl, SDK
# OpenAI) : le client de bureau, lui, affiche le niveau et n'en veut pas
# dans le texte (21/09).
AVERTISSEMENT = "⚠︎ Non vérifié en ligne — réponse de mémoire, qui peut dater.\n\n"
AVERTISSEMENT_RECHERCHE = (
    "⚠︎ La recherche web n'a rien donné — réponse de mémoire, qui peut dater.\n\n"
)


# Une donnée d'identité dans la question : un NAS ou un numéro à neuf
# chiffres, un téléphone, une adresse postale. Revue vocale du 21/09 :
# « vérifie ça » après une question qui les portait les envoyait au web.
_IDENTITE = re.compile(
    r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b|"
    r"\b\+?1?[ -]?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b|"
    r"\b\d{1,5},? (?:rue|avenue|boulevard|boul\.?|chemin|rang|place|street|road|"
    r"drive|ave\.?)\b"
)


def question_personnelle(texte: str) -> bool:
    """Les données de Carlito ne se cherchent pas sur le web."""
    plat = _plat(texte)
    return _PERSONNEL.search(plat) is not None or _IDENTITE.search(plat) is not None


# 21/09/2026 (P2 du jury) : la reconnaissance d'une question d'actualité est
# lexicale et le restera. Carlito doit pouvoir forcer la vérification à la
# main, au clavier et à la voix (§82) : le bouton « Vérifier en ligne » pose
# verifyOnline sur la requête, et « Vérifie ça » tapé ou dicté suffit.
# Le message ENTIER est une demande, et le verbe veut un complément :
# « Vérifie que mon script compile » n'en est pas une, « Vérifie ça en
# ligne. », « C'est vrai ? », « t'es sûr de ça ? » en sont. Revue du 21/09 :
# « Confirme », « Check », « Sure », « Vraiment » nus étaient pris pour des
# demandes — un « Confirme » qui acquiesce à « je crée la tâche ? » créait la
# tâche puis affichait « je n'ai pas pu vérifier ».
_DEMANDE_DE_VERIFICATION = re.compile(
    r"^(?:"
    # « (peux-tu) vérifie(r)(-le/-moi) ça (en ligne) (svp) »
    r"(?:(?:peux.tu |tu peux |est.ce que tu peux |pourrais.tu |can you |could you |"
    r"please )?"
    r"(?:verifie[rsz]?|verify|check(?:e[rsz]?)?|confirme[rsz]?|confirm)"
    r"(?:"
    # « vérifie-le », « confirme-moi ça » : le clitique est l'objet
    r"[- ](?:le|la|les)(?:\s+(?:en ligne|sur le web|sur internet|online|on the web))?"
    r"|(?:[- ]moi|[- ]nous)?\s*"
    r"(?:(?:ca|sa|cela|ceci|ce que tu dis|"
    r"cette (?:information|reponse|affirmation|info)|"
    r"l'information|la reponse|l'info|this|that|it|tout ca|tout cela)"
    r"(?:\s+(?:en ligne|sur le web|sur internet|online|on the web))?|"
    r"(?:en ligne|sur le web|sur internet|online|on the web))"
    r")"
    r"[\s,]*(?:s'il te plait|s'il vous plait|stp|svp|please)?)"
    # « c'est vrai (ça) ? », « est-ce (que c'est) vrai ? », « c'est sûr ? »
    r"|(?:ah bon, )?c'est (?:vrai|sur|exact|certain)(?: ca| cela)?\s*\?"
    r"|est.ce (?:que c'est )?(?:vrai|sur|exact)(?: ca)?\s*\?"
    r"|is (?:that|this|it) (?:true|right|correct)\s*\?"
    # « t'es sûr (de ça) ? », « tu en es certain ? », « are you sure ? »
    r"|(?:t(?:u es|'es|u en es|'en es)|es.tu|vous etes) (?:sur|sure|certain|certaine)"
    r"(?: de (?:ca|cela|toi|cette reponse|cette info|cette information))?\s*\?"
    r"|are you sure\s*\?"
    # « vraiment ? », « ah bon ? » — interrogatifs seulement
    r"|vraiment\s*\?|ah bon\s*\?|serieux\s*\?|really\s*\?"
    r")[\s.!?]*$"
)
# Une demande de vérification est courte : elle renvoie à ce qui précède.
_DEMANDE_MAX = 80
CONSIGNE_DEMANDEE = (
    "Une vérification en ligne est demandée pour : « {question} ». Appelle "
    "web_search maintenant avec une requête précise, sans écrire de texte "
    "avant l'appel ; puis réponds d'après les résultats : cite chaque fait "
    "par le numéro de sa source, comme [1], et donne la date de "
    "l'information. Si la recherche ne rend rien d'utile, dis que tu n'as "
    "pas pu vérifier — ne confirme jamais de mémoire."
)


def est_une_demande_de_verification(texte: str) -> bool:
    """« Vérifie ça », « c'est vrai ? », « check this online » — une demande
    courte qui porte sur ce qui vient d'être dit."""
    plat = _plat(texte)
    return (
        bool(plat)
        and len(plat) <= _DEMANDE_MAX
        and (_DEMANDE_DE_VERIFICATION.search(plat) is not None)
    )


def question_a_verifier(messages: Sequence[Message], forcee: bool = False) -> str:
    """Ce qu'il faut chercher : la question qui précède la demande, en
    sautant TOUTES les demandes de vérification consécutives (revue du
    21/09 : une seconde pression vérifiait « Vérifie ça en ligne. »). Avec
    le bouton (``forcee``), le dernier message EST la demande, quel que soit
    son libellé — traduit ou reformulé. Sans question avant : le message
    lui-même s'il n'est pas une demande nue, sinon "" (rien à vérifier)."""
    utilisateur = [m.content or "" for m in messages if m.role == Role.USER]
    if not utilisateur:
        return ""
    if not forcee and not est_une_demande_de_verification(utilisateur[-1]):
        return utilisateur[-1]
    for texte in reversed(utilisateur[:-1]):
        if not est_une_demande_de_verification(texte):
            return texte
    # Rien avant : une affirmation envoyée seule avec le bouton se vérifie
    # elle-même ; une demande nue (« Vérifie ça ») n'a rien à vérifier.
    return "" if est_une_demande_de_verification(utilisateur[-1]) else utilisateur[-1]


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
    r"\b(?:aujourd.hui|hier|demain|ce (?:soir|matin|week.end)|cette (?:semaine|nuit)|"
    r"meteo|temperature|pleuvoir|pluie|neige|scores?|matchs?|cours (?:du|de l')|"
    r"bourse|today|tonight|tomorrow|weather|right now)\b"
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
    qui n'en prolonge pas un autre. « 40,5 millions » EST dans « 40.5 million »
    (source anglaise, essai du 21/09) : l'unité se compare sans son pluriel."""
    compact = _compacter(valeur)
    motif = r"(?<![\d.])" + re.escape(compact) + r"(?!\d)"
    if re.search(motif, corpus_compact) is not None:
        return True
    m = re.match(r"^([\d.]+)(.*)$", compact)
    if not m:
        return False
    nombre, unite = m.group(1), m.group(2)
    if unite.endswith("s"):
        motif = r"(?<![\d.])" + re.escape(nombre + unite.rstrip("s")) + r"(?!\d)"
        if re.search(motif, corpus_compact) is not None:
            return True
    # « 2,25 % » quand la page dit « 2,25 » dans une colonne de taux (essai du
    # 21/09) : un nombre à décimales ou à trois chiffres est assez précis
    # pour se retrouver sans son unité ; « 5 % » ne l'est pas.
    if "." in nombre or len(nombre) >= 3:
        motif = r"(?<![\d.])" + re.escape(nombre) + r"(?![\d.])"
        return re.search(motif, corpus_compact) is not None
    return False


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
_DOMAINES_DE_REFERENCE = (
    "wikipedia.org",
    ".gc.ca",
    "canada.ca",
    "quebec.ca",
    "gouv.qc.ca",
    "ottawa.ca",
    "montreal.ca",
    "toronto.ca",
    "vatican.va",
    "elysee.fr",
    "gouvernement.fr",
    "whitehouse.gov",
    "un.org",
)


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
        url = str(s["url"])
        # La page DU poste : un titre qui commence par la fonction (« Premier
        # ministre du Canada — Wikipédia »), ou un site de référence qui la
        # porte (pm.gc.ca). Essai du 21/09 : « Le premier ministre Carney
        # rencontre… » d'un journal était lu comme la page du poste.
        # Banc du 21/09 : « Pape à Paris : où voir Léon XIV… » (sortiraparis)
        # commençait par la fonction et passait pour la page du poste. Seuls
        # les sites de référence comptent.
        de_reference = any(d in url for d in _DOMAINES_DE_REFERENCE)
        m = fonction.search(titre)
        if m and not _LISTE.match(titre) and de_reference:
            score = sum(1 for m in mots if m in titre)
            if meilleure is None or score > meilleure[0]:
                meilleure = (score, rang, url)
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
        donnees["sourcesDatedAt"] = vieille
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
    titulaire : {"answer": nom, "sources": [noms]}, sinon None.

    Seulement quand les sources désignent UN titulaire (deux, c'est déjà un
    désaccord entre elles, pas avec la réponse), que la réponse nomme au
    moins une personne, et que cette personne est bien donnée comme
    prédécesseur quelque part dans les sources — sans cela, le signal
    reposerait sur l'extraction seule, qui se trompe (revue du 21/09).
    """
    if not question_de_titulaire(question):
        return None
    titulaires = titulaires_selon_sources(corpus, question)
    if not titulaires:
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
    if len(titulaires) > 1:
        # Plusieurs titulaires : le plus récent est attendu, à condition que
        # sa source soit strictement plus récente ; la réponse qui nomme un
        # autre titulaire sans lui recevait « Vérifié en ligne » (revue du
        # 21/09). Sans date qui tranche, silence.
        date = titulaires[0]["date"]
        if not date or any(t["date"] == date for t in titulaires[1:]):
            return None
        anciens = {_cle_de_nom(t["nom"]): t["nom"] for t in titulaires[1:]}
        coupable = next(
            (
                anciens[_cle_de_nom(n)]
                for n in noms_de_la_reponse
                if _cle_de_nom(n) in anciens
            ),
            None,
        )
    else:
        coupable = next(
            (n for n in noms_de_la_reponse if _nomme_un_predecesseur(n, corpus)), None
        )
    if coupable is None:
        return None
    return {"answer": coupable, "sources": [attendu]}


# ---------------------------------------------------------------------------
# Le niveau de vérification, calculé par le code (P1 du jury, 21/09/2026).
#
# « ⚠︎ Non vérifié en ligne » était un préfixe de texte : il se copiait avec
# la réponse, se prononçait à voix haute, et ne distinguait pas une réponse
# qui cite ses sources d'une réponse qui les ignore. Trois niveaux, jamais
# déclarés par le modèle : ce que la boucle sait (une recherche a rendu
# quelque chose), ce que la réponse fait (elle cite des [N] qui existent), et
# ce que le contrôle a trouvé (rien, ou des éléments hors sources, ou un
# titulaire qui n'est pas celui des sources).
# ---------------------------------------------------------------------------

VERIFIE = "verified"
PARTIEL = "partial"
DE_MEMOIRE = "memory"
_CITATION = re.compile(r"\[(\d+)\]")


# La réponse dit elle-même qu'elle n'a pas trouvé (banc du 21/09 : « Les
# résultats de la recherche ne mentionnent pas le vainqueur de la Coupe
# Stanley 2026 … il faudrait attendre » sous un badge vert, avec trois [N]).
# Les verbes au singulier et au pluriel, écrits — « (?:nt)? » formait
# « permetnt », « ditnt », et « Les résultats ne permettent pas de
# déterminer le vainqueur [1] » était vérifié (revue du 21/09, 22 h).
_VERBES_D_AVEU = (
    r"(?:mentionne(?:nt)?|donne(?:nt)?|precise(?:nt)?|indique(?:nt)?|"
    r"permet(?:tent)?|contien(?:t|nent)|confirme(?:nt)?|revele(?:nt)?|"
    r"annonce(?:nt)?|di(?:t|sent)|montre(?:nt)?|fourni(?:t|ssent)|"
    r"repond(?:ent)?|parle(?:nt)?|nomme(?:nt)?|identifie(?:nt)?|"
    r"rapporte(?:nt)?|specifie(?:nt)?|detaille(?:nt)?|couvre(?:nt)?|"
    r"abord(?:e|ent)|traite(?:nt)?|evoque(?:nt)?)"
)
# Ce qui a été CHERCHÉ : « les prévisions ne mentionnent pas de pluie [6] »
# est une réponse (revue du 21/09). « données » et « recherches » nus
# désignent souvent le fait lui-même (« les données ne montrent pas de
# récession au T2 [1] », revue du 21/09, 22 h) : ils n'entrent qu'avec un
# qualificatif de recherche, ou avec les verbes de la consultation
# (mentionne, précise, indique, donne, permet, contient, fournit, nomme).
_SUJET_D_AVEU = (
    r"(?:resultats?|sources?|articles?|extraits?|pages?|resumes?|informations?|"
    r"(?:donnees?|recherches?)(?= (?:\[\d+\] )?(?:de (?:la |ma |cette )?recherche|"
    r"consult[eé]e?s?|trouv[eé]e?s?|obtenue?s?|fournie?s?|lue?s?|ci.dessus|"
    r"retourn[eé]e?s?|affich[eé]e?s?|disponibles?|actuel(?:le)?s?)))"
    r"(?: \[\d+\])?(?: ci.dessus)?"
    r"(?: (?:de (?:la |ma |cette )?recherche(?: web)?|consult[eé]e?s?|"
    r"actuel(?:le)?s?|disponibles?|trouv[eé]e?s?|lue?s?|obtenue?s?|fournie?s?|"
    r"cit[eé]e?s?|retourn[eé]e?s?|affich[eé]e?s?|recueillie?s?)){0,2}"
)
_SUJET_FAIBLE = r"(?:donnees?|recherches?)(?: \[\d+\])?"
_VERBES_DE_CONSULTATION = (
    r"(?:mentionne(?:nt)?|precise(?:nt)?|indique(?:nt)?|donne(?:nt)?|"
    r"permet(?:tent)?|contien(?:t|nent)|fourni(?:t|ssent)|nomme(?:nt)?|"
    r"identifie(?:nt)?|specifie(?:nt)?)"
)
_ADVERBES = r"(?: toujours| plus| donc| malheureusement| encore| non plus)?"
# « Il faut attendre le 29 octobre pour la prochaine décision [1] » est une
# réponse (revue du 21/09, 22 h) : la date qui suit dit le monde, pas la
# recherche.
_PAS_UNE_DATE = (
    r"(?! (?:le |la |l'|les )?(?:\d|lundi|mardi|mercredi|jeudi|vendredi|samedi|"
    r"dimanche|janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|"
    r"octobre|novembre|decembre|demain|ce soir|cette nuit|la semaine|le mois))"
)
_NON_REPONSE = re.compile(
    _SUJET_D_AVEU
    + r" n(?:e |')(?:le |la |les |l')?"
    + _VERBES_D_AVEU
    + _ADVERBES
    + r" (?:pas|aucun|rien|ni)|"
    + _SUJET_FAIBLE
    + r" n(?:e |')(?:le |la |les |l')?"
    + _VERBES_DE_CONSULTATION
    + _ADVERBES
    + r" (?:pas|aucun|rien)|"
    r"je n'(?:ai|a) pas (?:trouve|pu trouver|pu obtenir|pu verifier|pu identifier|"
    r"pu determiner|pu confirmer|reussi a)|"
    r"je n'ai (?:rien trouve|trouve aucun)|je ne trouve pas|nous n'avons pas trouve|"
    r"je ne (?:peux|parviens|arrive) pas (?:a )?(?:determiner|confirmer|trouver|"
    r"identifier|etablir|dire|savoir|repondre)|"
    r"je ne suis pas en mesure de|il n'est pas possible de (?:determiner|"
    r"confirmer|trouver|identifier|etablir|savoir|dire)|je ne sais pas|"
    r"impossible de (?:trouver|determiner|identifier)|"
    r"impossible de (?:savoir|dire) (?:qui|quel|lequel|laquelle|combien)|"
    r"aucun(?:e)? (?:(?:des )?(?:resultats?|sources?|articles?|extraits?|"
    r"informations?|donnees?|pages?) )?ne (?:le |la |les |l')?"
    + _VERBES_D_AVEU
    + r"|rien n'indique (?:le |la |les |l'|qui |quel|combien |quand |ou |dans |parmi )|"
    r"rien ne (?:mentionne|confirme|precise|permet de (?:trouver|determiner|savoir|"
    r"dire|confirmer|identifier))|"
    r"n(?:e |')(?:est|sont|apparai(?:t|ssent)|figure(?:nt)?) pas "
    r"(?:mentionne|indique|precise|confirme|nomme|specifie|detaille|fourni|"
    r"donne|identifie|clair|disponible|dans les (?:resultats|sources|extraits))"
    r"(?:e?s?)\b|"
    r"n(?:e |')(?:apparai(?:t|ssent)|figure(?:nt)?) (?:pas |nulle part )?"
    r"(?:dans|parmi) les (?:resultats|sources|extraits|articles)|"
    r"n'(?:ait|aient) pas encore eu lieu|"
    r"pas (?:d'|de )(?:information|donnee|resultat|chiffre)s? "
    r"(?:disponible|precis|exact|officiel|sur|pour)|"
    r"il (?:faudrait|faut|faudra) (?:attendre|chercher|consulter|verifier)"
    + _PAS_UNE_DATE
    + r"|je (?:vous |te )?(?:recommande|suggere|conseille|invite a) (?:de )?"
    r"(?:consulter|verifier|chercher)|"
    r"results? (?:do|does)(?: not|n't) (?:mention|include|show|give|say)|"
    r"(?:could|couldn't|can't|cannot|unable to) ?(?:not )?(?:find|determine)|"
    r"no (?:results?|information) (?:found|available)|"
    r"(?:is|are) not (?:mentioned|specified|available|listed) in the"
)
CONSIGNE_AUTRE_REQUETE = (
    "Les résultats ne donnaient pas le fait demandé. Appelle web_search "
    "maintenant avec une requête DIFFÉRENTE — d'autres mots, en anglais, ou "
    "le nom du site officiel — sans restreindre la fraîcheur (recency: year, "
    "news: false), ou web_read sur la source la plus prometteuse, sans écrire "
    "de texte avant l'appel ; puis réponds d'après les nouveaux résultats en "
    "citant [N], ou dis que tu n'as pas trouvé. Ne suppose rien sur ce qui a "
    "eu lieu ou non."
)
# La PROMESSE SANS L'ACTE : « je vais lire l'article complet » en fin de
# réponse (banc du 21/09, but gagnant de la finale), et rien ne le lit.
# Elle compte même à côté d'une phrase citée — c'est le modèle lui-même qui
# dit que sa réponse ne suffit pas. « Je vais chercher le score si tu veux »
# est une offre, pas une promesse (revue du 21/09, 22 h).
_PROMESSE = re.compile(
    r"(?:je (?:vais|dois) (?:(?:donc |maintenant |d'abord )?"
    r"(?:relancer|lire|consulter|ouvrir|verifier|chercher|rechercher|affiner|"
    r"approfondir|regarder|examiner|effectuer|lancer|faire))|"
    r"(?:laissez?|permets?|permettez)(?:[- ]moi)? (?:de )?(?:relancer|lire|"
    r"consulter|verifier|chercher)|"
    r"let me (?:check|read|search|look)|i (?:will|'ll) (?:check|read|search|look))"
    r"(?!.*\b(?:si (?:tu|vous) (?:le )?(?:veux|voulez|souhaite[sz])|si besoin|"
    r"si necessaire|if you (?:want|like|wish)))"
)
# Le 9b enchaîne l'aveu et ce dont PARLENT les résultats : « Les articles
# parlent surtout des contrats des Panthers [1][2] » n'affirme rien sur la
# question (revue du 21/09, 22 h : cette phrase couvrait l'aveu et rendait
# « vérifié »).
_DESCRIPTION_DES_SOURCES = re.compile(
    r"^(?:ils?|elles?|ces|les|ceux.ci|celles.ci)(?: (?:\w+|\[\d+\])){0,3}? "
    r"(?:parlent?|portent?|traitent?|concernent?|datent?|evoquent?|"
    r"se limitent?|se concentrent?|decrivent?|abordent?|couvrent?|"
    r"ne (?:parlent?|portent?|traitent?) que|sont (?:consacr|centr)e?s? sur|"
    r"(?:sont|est) (?:des|un|une) (?:articles?|resume|page))"
)


# Une phrase, ou une proposition : « Les Hurricanes ont gagné [7] ; les
# sources ne précisent pas le score » porte les deux. La virgule coupe
# devant une réserve (« … 4-2 [1], les sources ne précisent pas le buteur »,
# revue du 21/09, 22 h : la phrase entière passait pour un aveu).
_PHRASES = re.compile(
    r"(?<=[.!?;:])\s+|\n+|\s+[—–]\s+|"
    r"\s+(?:mais|cependant|toutefois|bien que|alors que|même si|meme si|"
    r"tandis que|sauf que|néanmoins|neanmoins)\s+|"
    r",\s+(?=(?:les |la |le |l'|il |ils |elles? |aucun|rien|je |nous |ce ))"
)
# Les mots de la question et leurs frères dans l'aveu : « Qui a gagné » →
# « le vainqueur n'est pas mentionné » (revue du 21/09, 22 h).
_FRERES = (
    frozenset(
        "gagne gagner gagnant gagnante vainqueur vainqueurs champion "
        "championne champions remporte remporter remporte victoire "
        "victorieux laureat laureate elu elue winner won winners".split()
    ),
    frozenset("score scores pointage marque resultat final".split()),
    frozenset("date jour quand dates".split()),
    frozenset("nom nomme appelle prenom name".split()),
    frozenset("prix cout tarif montant price cost".split()),
    frozenset("temps meteo previsions weather forecast".split()),
    frozenset("taux pourcentage rate".split()),
    frozenset("morts deces victimes bilan decedes tues".split()),
    frozenset("buteur marqueur marque scorer".split()),
    frozenset("heure horaire heures".split()),
)


def _frere(mot: str) -> frozenset[str] | None:
    for famille in _FRERES:
        if mot in famille:
            return famille
    return None


def _mots_demandes(question: str) -> set[str]:
    """Les mots pleins de la question, sans ses noms propres : « Canada »,
    « Ottawa », « Banque » nomment le cadre, pas le fait demandé (revue du
    21/09, 22 h : « les sources ne précisent pas le vent à Ottawa » sous
    « Quel temps fera-t-il à Ottawa ? » passait pour une non-réponse)."""
    propres: set[str] = set()
    for rang, brut in enumerate(re.findall(r"[\wÀ-ÿ'’-]+", question)):
        if rang and brut[:1].isupper():
            propres.update(_MOT_DE_QUESTION.findall(_plat(brut)))
    mots = set(_MOT_DE_QUESTION.findall(_plat(question)))
    mots -= _MOTS_VIDES_DE_QUESTION | _MOTS_GRAMMATICAUX | propres
    return {m for m in mots if not m.isdigit()}


# Ce que l'aveu dit ne pas avoir : après le verbe (« ne précisent pas [le]
# score »), ou devant « n'est pas mentionné » (« Le score exact du septième
# match n'est pas… »). Les deux premiers mots pleins.
_DETERMINANTS = frozenset(
    "le la les l un une du des de d au aux ce cet cette ces son sa ses leur "
    "leurs mon ma mes encore toujours exactement clairement explicitement "
    "precisement vraiment non plus donc pas".split()
)
_OBJET_APRES = re.compile(r" (?:pas|aucun|rien|ni)\b(.*)$")
_SUJET_DEVANT = re.compile(r"^n(?:e |')(?:est|sont|apparai|figure)")


def _objet_de_l_aveu(aveu_plat: str) -> set[str]:
    m = _NON_REPONSE.search(aveu_plat)
    if not m:
        return set()
    portion = m.group(0)
    texte = ""
    if _SUJET_DEVANT.match(portion):
        # « Le score exact du septième match n'est pas spécifié » : l'objet
        # est le sujet, devant.
        texte = aveu_plat[: m.start()]
    else:
        apres = _OBJET_APRES.search(portion + aveu_plat[m.end() :])
        if apres and apres.group(1).strip():
            texte = apres.group(1)
        elif re.match(r"je n'(?:ai|a) |impossible de|rien n'indique|rien ne ", portion):
            texte = aveu_plat[m.end() :]
    jetons = [t.strip("'") for t in re.findall(r"[a-z']+", texte)]
    jetons = [t for t in jetons if t not in _DETERMINANTS and len(t) >= 3]
    return set(jetons[:2])


def est_une_non_reponse(
    reponse: str, orale: bool = False, question: str | None = None
) -> bool:
    """La réponse avoue ne pas avoir trouvé le fait dans les sources — et
    n'affirme rien d'autre ; ou elle promet d'aller le chercher.

    Revue du 21/09 : « Les Hurricanes ont gagné [7] ; les sources ne
    précisent pas le score » déclenchait une lecture, un passage de plus et
    la réponse en double. Une phrase qui avoue à côté d'une phrase qui
    affirme (une citation [N] ; à l'oral, un nom, un nombre) est une réponse
    avec une réserve — SAUF si l'aveu porte sur ce qui était demandé : « Le
    score exact … n'est pas spécifié dans les résultats » sous « Quel a été
    le score … ? » (banc du 21/09, 22 h) est une non-réponse malgré le [6]
    de la phrase d'avant. Le critère : l'OBJET de l'aveu (« le score », « le
    vainqueur ») est un mot de la question, ou son frère (« gagné »), et
    n'est pas dans une phrase qui cite. Et une PROMESSE (« je vais lire
    l'article complet ») en dernière phrase compte toujours : rien ne la
    tiendra. Ce dont PARLENT les résultats n'est pas une affirmation.
    """
    phrases = [ph for ph in _PHRASES.split(reponse or "") if ph.strip()]
    if not phrases:
        return False
    if _PROMESSE.search(_plat(phrases[-1])):
        return True
    aveux: list[str] = []
    affirmations: list[str] = []
    for ph in phrases:
        plat = _plat(ph)
        m = _NON_REPONSE.search(plat)
        if m or _PROMESSE.search(plat):
            aveux.append(plat)
            # « Les Panthers ont gagné 4-2 [1], les sources ne précisent pas
            # le buteur » : ce qui précède l'aveu dans la même phrase affirme.
            avant = ph[: m.start()] if m else ""
            if avant.strip() and _affirme(avant, orale, question):
                affirmations.append(avant)
            continue
        if _DESCRIPTION_DES_SOURCES.match(plat):
            continue
        if _affirme(ph, orale, question):
            affirmations.append(ph)
    if not aveux:
        return False
    if not affirmations:
        return True
    return _l_aveu_porte_sur_la_question(aveux, affirmations, question)


def _affirme(phrase: str, orale: bool, question: str | None) -> bool:
    if orale:
        return _affirme_a_l_oral(phrase, question)
    return _CITATION.search(phrase) is not None


def _l_aveu_porte_sur_la_question(
    aveux: Sequence[str], affirmations: Sequence[str], question: str | None
) -> bool:
    """L'objet d'un aveu est un mot demandé (ou son frère) qu'aucune phrase
    qui affirme ne porte."""
    if not question:
        return False
    demandes = _mots_demandes(question)
    if not demandes:
        return False
    familles = {m: (_frere(m) or frozenset({m})) for m in demandes}
    affirmes: set[str] = set()
    for ph in affirmations:
        affirmes.update(_MOT_DE_TITRE.findall(_plat(ph)))
    for aveu in aveux:
        objet = _objet_de_l_aveu(aveu)
        for mot, famille in familles.items():
            if objet & famille and not (famille & affirmes):
                return True
    return False


# À l'oral le modèle écrit parfois le nombre en lettres (« Quinze degrés »).
_NOMBRE_DIT = re.compile(
    r"\b(?:zero|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|"
    r"treize|quatorze|quinze|seize|vingt|trente|quarante|cinquante|soixante|"
    r"cent|mille|million|milliard)s?\b"
)


def _affirme_a_l_oral(phrase: str, question: str | None = None) -> bool:
    """Un nombre, ou un nom propre hors tête de phrase — qui ne soit pas un
    mot de la question (« Coupe Stanley » redit le sujet, n'affirme rien ;
    revue du 21/09, 22 h)."""
    if re.search(r"\d", phrase) or _NOMBRE_DIT.search(_plat(phrase)):
        return True
    sujet = set(_MOT_DE_TITRE.findall(_plat(question or "")))
    mots = phrase.split()
    return any(
        re.match(r"^[A-ZÀ-Ý][\wÀ-ÿ'’-]{2,}", m)
        and not set(_MOT_DE_TITRE.findall(_plat(m))) <= sujet
        for m in mots[1:]
    )


# Banc du 21/09, « Qui a gagné la Coupe Stanley en 2026 ? » : neuf sources
# dont nhl.com « 2026 Stanley Cup Final » daté de juin, et le 9b avoue ne pas
# trouver le vainqueur — il ne va pas le chercher dans la page. Le code y va :
# la source dont le titre reprend le plus de mots de la question, fraîche et
# de référence de préférence, pas encore lue.
_MOT_DE_QUESTION = re.compile(r"[a-z]{4,}|(?:19|20)\d\d")
_AGREGATEURS = ("msn.com", "news.google.", "flipboard.com", "news.yahoo.")
_JOURS_RECENTS = 30
CONSIGNE_PAGE_LUE = (
    "Le début de la source [{ref}] a été lu par le code : c'est le texte "
    "ci-dessus. Réponds d'après lui en citant [{ref}] ; si le "
    "fait n'y est pas non plus, appelle web_search avec une requête "
    "différente, ou dis que tu n'as pas trouvé. Ne suppose rien sur ce qui a "
    "eu lieu ou non."
)
# Quand il ne reste aucun tour d'outil : pas de « appelle web_search » qu'on
# n'exécuterait pas (revue du 21/09 : promesse affichée, tour perdu).
CONSIGNE_PAGE_LUE_SANS_OUTIL = (
    "Le début de la source [{ref}] a été lu par le code : c'est le texte "
    "ci-dessus. Réponds d'après lui en citant [{ref}], ou dis "
    "que tu n'as pas trouvé — n'annonce aucune recherche. Ne suppose rien sur "
    "ce qui a eu lieu ou non."
)


# Les mots qui traversent la langue : « premier ministre du Canada » doit
# reconnaître « Prime Minister » et non « Canada Day celebrations ».
_LEXIQUE = {
    "coupe": ("cup",),
    "premier": ("prime",),
    "ministre": ("minister",),
    "maire": ("mayor",),
    "taux": ("rate",),
    "president": ("president",),
    "election": ("election",),
    "elections": ("election",),
    "championnat": ("championship",),
    "vainqueur": ("winner", "champion"),
    "gagnant": ("winner", "champion"),
    "champion": ("champion", "winner"),
    "finale": ("final",),
    "meteo": ("weather", "forecast"),
    "prix": ("price",),
    "inflation": ("inflation",),
    "version": ("version",),
    "sortie": ("release",),
}
_MOT_DE_TITRE = re.compile(r"[a-z]{2,}|(?:19|20)\d\d")


def sources_prometteuses(
    sources: Sequence[dict[str, Any]],
    question: str,
    deja_lues: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Les sources à lire quand la réponse avoue n'avoir pas trouvé, la plus
    prometteuse d'abord (vide : rien ne s'impose).

    Un point par mot du TITRE atteint par un mot entier de la question
    (quatre lettres, ou sa traduction du lexique) — entier : « temps » n'est
    pas dans « printemps » ; par mot du titre, pas de la question : « président »
    se traduit par lui-même et comptait double (revue du 21/09, 22 h) ; deux
    par année de la question, et deux de moins pour une AUTRE année (« Coupe
    Stanley 2025 : les Panthers » gagnait sur « 2026 Stanley Cup Final ») ;
    sans année dans la question, l'année en cours est implicite : un point
    pour elle, deux de moins pour une année d'AVANT l'année passée — en
    janvier, l'édition de l'année passée est encore la dernière (revue du
    21/09, 22 h : au 15 janvier 2027, « 2026 Stanley Cup Final » était
    écartée pour un aperçu des séries 2027) ; un point si le site est de
    référence ; un demi-point si la source a une date ISO de moins de trente
    jours. Deux points nets au moins avant de lire : un seul mot commun
    (« Canada ») ne dit pas le sujet. Jamais un agrégateur (MSN ne se lit
    pas). À égalité, la première pastille.
    """
    from datetime import date, timedelta

    from diapason.tools.web_search import url_canonique

    mots = set(_MOT_DE_QUESTION.findall(_plat(question)))
    mots -= _MOTS_VIDES_DE_QUESTION | _MOTS_GRAMMATICAUX
    if not mots:
        return []
    annees = {m for m in mots if m.isdigit()}
    lexique = set()
    for m in mots:
        lexique.update(_LEXIQUE.get(m, ()))
    annee_en_cours = str(date.today().year)
    lues = {url_canonique(u) for u in deja_lues}
    recent = (date.today() - timedelta(days=_JOURS_RECENTS)).isoformat()
    classees: list[tuple[float, int, dict[str, Any]]] = []
    for rang, src in enumerate(sources):
        if not isinstance(src, dict) or not src.get("url"):
            continue
        url = str(src["url"])
        if url_canonique(url) in lues:
            continue
        if any(d in url for d in _AGREGATEURS):
            continue
        jetons = set(_MOT_DE_TITRE.findall(_plat(str(src.get("title") or ""))))
        atteints = {
            t for t in jetons if (t in mots and not t.isdigit()) or t in lexique
        }
        communs = len(atteints)
        if communs == 0:
            continue
        score: float = communs
        annees_du_titre = {t for t in jetons if t.isdigit()}
        if annees:
            score += 2 * len(annees & annees_du_titre)
            if annees_du_titre - annees:
                score -= 2
        else:
            if annee_en_cours in annees_du_titre:
                score += 1
            annee_passee = str(int(annee_en_cours) - 1)
            if any(a < annee_passee for a in annees_du_titre):
                score -= 2
        if any(d in url for d in _DOMAINES_DE_REFERENCE):
            score += 1
        if score < 2:
            continue
        date_src = str(src.get("date") or "")
        if _DATE_ISO.fullmatch(date_src) and date_src >= recent:
            score += 0.5
        classees.append((score, rang, src))
    classees.sort(key=lambda t: (-t[0], t[1]))
    return [src for _score, _rang, src in classees]


def source_la_plus_prometteuse(
    sources: Sequence[dict[str, Any]],
    question: str,
    deja_lues: Sequence[str] = (),
) -> dict[str, Any] | None:
    """La première de ``sources_prometteuses``, ou None."""
    classees = sources_prometteuses(sources, question, deja_lues)
    return classees[0] if classees else None


def niveau_de_verification(
    reponse: str,
    sources: Sequence[dict[str, Any]],
    verification_faite: bool,
    signal: dict[str, Any] | None = None,
    dernier_passage: str | None = None,
    question: str | None = None,
) -> str:
    """verified / partial / memory.

    De mémoire tant qu'aucune recherche n'a rendu quelque chose ; partiel
    quand la réponse ne cite aucune source, cite un numéro qui n'existe pas,
    ou que le contrôle a relevé quelque chose ; vérifié sinon. La
    non-réponse se juge sur le DERNIER passage : « je dois lire la page… »
    suivi du chiffre trouvé est une réponse (banc du 21/09).
    """
    if not verification_faite:
        return DE_MEMOIRE
    connus = {s.get("ref") for s in sources if isinstance(s, dict)}
    cites = {int(n) for n in _CITATION.findall(reponse or "")}
    if not cites or not cites <= connus:
        return PARTIEL
    # « [1] » tout seul n'est pas une réponse vérifiée (revue du 21/09).
    if not _CITATION.sub("", reponse or "").strip():
        return PARTIEL
    # Une réponse qui dit n'avoir pas trouvé n'est pas vérifiée, même citée.
    if est_une_non_reponse(
        dernier_passage if dernier_passage is not None else reponse, question=question
    ):
        return PARTIEL
    # Revue du 21/09 : le [1] de la non-réponse suffisait ; la reprise qui
    # répond sans citer était « vérifiée ». Le dernier passage cite, lui aussi.
    if dernier_passage is not None:
        cites_a_la_fin = {int(n) for n in _CITATION.findall(dernier_passage)}
        if not cites_a_la_fin or not cites_a_la_fin <= connus:
            return PARTIEL
    if signal and (
        signal.get("notFound")
        or signal.get("disagreement")
        or signal.get("sourcesDatedAt")
    ):
        return PARTIEL
    return VERIFIE


# ---------------------------------------------------------------------------
# Les numéros des sources, continus sur tout le tour (chat et voix).
# ---------------------------------------------------------------------------

_NUMERO_DE_LIGNE = re.compile(r"^\[(\d+)\]", re.M)


def renumeroter(
    contenu: str,
    sources: list[dict[str, Any]],
    deja: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Une seconde recherche ne recommence pas à [1] : ses numéros suivent, et
    une page déjà vue garde son premier numéro (revue du 20/09 : deux
    recherches rendaient deux pastilles vers le même article)."""
    from diapason.tools.web_search import url_canonique

    connus = {url_canonique(str(d.get("url") or "")): d["ref"] for d in deja}
    prochain = len(deja) + 1
    correspondance: dict[int, int] = {}
    nouvelles: list[dict[str, Any]] = []
    for src in sources:
        if not isinstance(src, dict) or not isinstance(src.get("ref"), int):
            continue
        cle = url_canonique(str(src.get("url") or ""))
        if cle in connus:
            correspondance[src["ref"]] = connus[cle]
            continue
        correspondance[src["ref"]] = prochain
        connus[cle] = prochain
        nouvelles.append({**src, "ref": prochain})
        prochain += 1
    if not correspondance:
        return contenu, []
    texte = _NUMERO_DE_LIGNE.sub(
        lambda m: f"[{correspondance.get(int(m.group(1)), int(m.group(1)))}]",
        contenu,
    )
    return texte, nouvelles


def sous_l_url_demandee(
    sources: list[dict[str, Any]], url: str
) -> list[dict[str, Any]]:
    """La page lue garde la pastille de l'URL demandée : après une
    redirection (http → https, www), web_read rend l'URL finale et la page
    déjà [2] recevait une quatrième pastille (revue du 21/09)."""
    if not url:
        return sources
    return [
        {**src, "url": url} if isinstance(src, dict) and src.get("url") != url else src
        for src in sources
    ]
