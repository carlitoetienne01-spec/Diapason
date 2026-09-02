"""L'API de la loterie.

Les champs qui passent sur le fil sont en anglais camelCase, comme partout
ailleurs dans ce projet — même émis par un module français.

Les routes de lecture et la simulation sont SYNCHRONES : Starlette les exécute
dans un fil, alors qu'une coroutine ferait tourner leurs lectures SQLite et
leurs deux millions de tirages sur la boucle d'événements, gelant le serveur
entier. Seule la moisson est `async`, parce qu'elle attend le réseau.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from diapason.loterie import reference
from diapason.loterie.depot import DepotTirages
from diapason.loterie.equite import examiner, frequences
from diapason.loterie.lots import (
    PRIX_PARTICIPATION,
    PROBABILITES,
    TABLE,
    probabilite_de_gagner,
)
from diapason.loterie.moisson import SOURCE, moissonner
from diapason.loterie.simulation import (
    TIRAGES_MAX,
    GrilleInvalide,
    esperance_par_participation,
    simuler,
)
from diapason.loterie.tirages import (
    COMBINAISONS,
    GRAND_NUMERO_MAX,
    NUMERO_MAX,
    NUMEROS_PAR_TIRAGE,
)
from diapason.loterie.validation import controler

router = APIRouter(prefix="/v1/loterie", tags=["loterie"])

_depot: DepotTirages | None = None


def _magasin() -> DepotTirages:
    global _depot
    if _depot is None:
        _depot = DepotTirages()
    return _depot


def set_depot_for_tests(depot: DepotTirages | None) -> None:
    global _depot
    _depot = depot


class Grille(BaseModel):
    numbers: list[int] = Field(min_length=5, max_length=5)
    grandNumber: int = Field(ge=1, le=GRAND_NUMERO_MAX)
    draws: int = Field(default=5200, ge=1, le=TIRAGES_MAX)
    seed: int | None = None


def _jeu() -> dict[str, Any]:
    return {
        "name": "Grande Vie",
        "alsoKnownAs": "Daily Grand",
        "pick": NUMEROS_PAR_TIRAGE,
        "from": NUMERO_MAX,
        "grandNumberFrom": GRAND_NUMERO_MAX,
        "combinations": COMBINAISONS,
        "ticketPrice": PRIX_PARTICIPATION,
        "expectedReturn": round(esperance_par_participation(), 4),
        "anyPrizeOdds": round(1 / float(probabilite_de_gagner()), 2),
        "prizes": [
            {
                "matched": lot.bons,
                "grandNumber": lot.grand,
                "label": lot.libelle,
                "value": lot.valeur,
                "oneIn": round(1 / float(PROBABILITES[(lot.bons, lot.grand)]), 2),
            }
            for lot in TABLE
        ],
    }


@router.get("/etat")
def etat() -> dict[str, Any]:
    """Ce qu'on a, ce qu'il vaut, et ce qu'il dit.

    Le verdict d'équité n'est rendu QUE si le contrôle croisé passe. Publier un
    test calculé sur des données non vérifiées serait exactement la fausse
    assurance que ce module existe pour écarter.
    """
    depot = _magasin()
    tirages = depot.tous()
    controle = controler(tirages)
    verdict = examiner(tirages) if controle.concordant else None
    return {
        "game": _jeu(),
        "source": SOURCE,
        "drawCount": len(tirages),
        "firstDraw": tirages[0].jour.isoformat() if tirages else None,
        "lastDraw": tirages[-1].jour.isoformat() if tirages else None,
        "validation": {
            "agrees": controle.concordant,
            "reason": controle.raison,
            "harvested": controle.tirages_moissonnes,
            "expected": controle.tirages_attendus,
            "sum": controle.somme_moissonnee,
            "expectedSum": controle.somme_attendue,
            "mismatches": {
                str(n): {"harvested": a, "official": b}
                for n, (a, b) in controle.ecarts.items()
            },
            "reference": {
                "source": reference.SOURCE,
                "takenOn": reference.RELEVE_LE.isoformat(),
                "draws": reference.TIRAGES,
                "from": reference.PREMIER_TIRAGE.isoformat(),
                "to": reference.DERNIER_TIRAGE.isoformat(),
            },
        },
        "fairness": None
        if verdict is None
        else {
            "draws": verdict.tirages,
            "expectedPerNumber": round(verdict.attendu, 2),
            "standardDeviation": round(verdict.ecart_type, 2),
            "chiSquare": round(verdict.khi2, 2),
            "degreesOfFreedom": verdict.degres,
            "pValue": round(verdict.valeur_p, 4),
            "fair": verdict.equitable,
            "hottest": {
                "number": verdict.plus_frequent[0],
                "count": verdict.plus_frequent[1],
                "sigma": round(
                    (verdict.plus_frequent[1] - verdict.attendu) / verdict.ecart_type, 2
                ),
            },
            "coldest": {
                "number": verdict.moins_frequent[0],
                "count": verdict.moins_frequent[1],
                "sigma": round(
                    (verdict.moins_frequent[1] - verdict.attendu) / verdict.ecart_type,
                    2,
                ),
            },
            "expectedExtremeSigma": round(verdict.ecart_max_attendu, 2),
        },
    }


@router.get("/frequences")
def liste_frequences() -> dict[str, Any]:
    """La fréquence de chaque numéro — pour la voir, pas pour en jouer un."""
    tirages = _magasin().tous()
    freq = frequences(tirages)
    return {
        "drawCount": len(tirages),
        "frequencies": [{"number": n, "count": c} for n, c in sorted(freq.items())],
    }


@router.post("/moisson")
async def lancer_la_moisson() -> dict[str, Any]:
    """Aller chercher l'archive. Une seconde de repos entre deux pages."""
    depot = _magasin()
    recolte = await moissonner(depot)
    tirages = await asyncio.to_thread(depot.tous)
    controle = controler(tirages)
    return {
        "pagesRead": recolte.pages_lues,
        "drawsRead": recolte.tirages_lus,
        "drawsNew": recolte.tirages_neufs,
        "stoppedBecause": recolte.arret,
        "drawCount": len(tirages),
        "validation": {"agrees": controle.concordant, "reason": controle.raison},
    }


@router.post("/simulation")
def lancer_la_simulation(grille: Grille) -> dict[str, Any]:
    """Dérouler des années de tirages contre une grille."""
    try:
        resultat = simuler(
            grille.numbers, grille.grandNumber, grille.draws, graine=grille.seed
        )
    except GrilleInvalide as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "draws": resultat.tirages,
        "spent": resultat.depense,
        "won": resultat.gagne,
        "balance": resultat.solde,
        "byPrize": resultat.par_categorie,
        "expectedPerTicket": round(resultat.esperance, 4),
        "ticketPrice": PRIX_PARTICIPATION,
    }
