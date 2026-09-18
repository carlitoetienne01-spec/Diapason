"""Le raisonnement du réseau côté serveur — statuts, voisinage, impact.

Miroir de ``frontend/src/features/succes/reseau.ts`` (chantier réseau,
18 septembre 2026). Jusque-là, aucun outil vocal ne connaissait les arêtes :
« qu'est-ce que je peux faire dans AgriCulture ? » n'avait pas de réponse,
et relier deux tâches passait par la souris seule — ce que le §82 refuse.
Pur : (tâches, arêtes) en entrée, jamais la base. Une arête se lit
« from débloque to » : ``to`` attend ``from``.

Les deux modules doivent rendre la MÊME réponse aux mêmes questions ;
``tests/succes/test_reseau.py`` rejoue la fixture AgriCulture de
``reseau.test.ts`` pour le vérifier.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

Statut = Literal["done", "feasible", "blocked"]
Sens = Literal["amont", "aval"]


def cle_titre(titre: str) -> str:
    """Un tri « à la française » sans dépendre de la locale du Mac.

    ``localeCompare(..., 'fr')`` côté client place « âne » avant « zèbre » ;
    un tri par points de code met « â » (U+00E2) APRÈS « z ». On retire les
    accents et la casse pour comparer, sans toucher au titre affiché.
    """
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFKD", titre) if not unicodedata.combining(c)
    )
    return sans_accents.casefold()


@dataclass
class Reseau:
    taches: list[dict[str, Any]]
    par_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    amont: dict[str, list[str]] = field(default_factory=dict)
    aval: dict[str, list[str]] = field(default_factory=dict)


def construire_reseau(
    taches: list[Mapping[str, Any]], aretes: list[Mapping[str, Any]]
) -> Reseau:
    """Les arêtes dont un bout n'existe plus sont écartées — des fantômes."""
    reseau = Reseau(taches=[dict(t) for t in taches])
    for tache in reseau.taches:
        tid = str(tache["id"])
        reseau.par_id[tid] = tache
        reseau.amont[tid] = []
        reseau.aval[tid] = []
    for arete in aretes:
        de, vers = str(arete["fromTaskId"]), str(arete["toTaskId"])
        if de not in reseau.par_id or vers not in reseau.par_id:
            continue
        reseau.amont[vers].append(de)
        reseau.aval[de].append(vers)
    return reseau


def _faite(reseau: Reseau, tid: str) -> bool:
    tache = reseau.par_id.get(tid)
    # Une tâche inconnue est traitée comme faite : elle ne bloque rien.
    return tache is None or bool(tache.get("done"))


def statut_de(reseau: Reseau, tid: str) -> Statut:
    if _faite(reseau, tid):
        return "done"
    attend = any(not _faite(reseau, pid) for pid in reseau.amont.get(tid, []))
    return "blocked" if attend else "feasible"


def chaine(reseau: Reseau, tid: str, sens: Sens) -> list[tuple[str, int]]:
    """Parcours en largeur, sans le départ, chaque tâche une seule fois.

    « Une seule fois » est porteur : une boucle relayée par un pair (t1→t2
    ET t2→t1, acceptée à la réception pour ne pas figer les appareils)
    tournerait sinon sans fin.
    """
    voisins = reseau.amont if sens == "amont" else reseau.aval
    vus = {tid}
    resultat: list[tuple[str, int]] = []
    frontiere = [tid]
    profondeur = 0
    while frontiere:
        profondeur += 1
        suivante: list[str] = []
        for courant in frontiere:
            proches = sorted(
                (
                    reseau.par_id[v]
                    for v in voisins.get(courant, [])
                    if v in reseau.par_id
                ),
                key=lambda t: cle_titre(str(t["title"])),
            )
            for proche in proches:
                pid = str(proche["id"])
                if pid in vus:
                    continue
                vus.add(pid)
                resultat.append((pid, profondeur))
                suivante.append(pid)
        frontiere = suivante
    return resultat


def voisines_ordonnees(reseau: Reseau, tid: str, sens: Sens) -> list[str]:
    """En amont, les ouvertes d'abord (les vraies raisons du blocage), puis
    par titre ; en aval, par titre."""
    ids = (reseau.amont if sens == "amont" else reseau.aval).get(tid, [])
    taches = [reseau.par_id[v] for v in ids if v in reseau.par_id]
    if sens == "amont":
        taches.sort(key=lambda t: (bool(t.get("done")), cle_titre(str(t["title"]))))
    else:
        taches.sort(key=lambda t: cle_titre(str(t["title"])))
    return [str(t["id"]) for t in taches]


def ce_que_debloque(reseau: Reseau, tid: str) -> list[str]:
    """Les successeures qu'achever ``tid`` ouvre : celles dont toutes les
    autres attentes sont déjà faites. Le calcul ignore l'état de ``tid``
    lui-même — lu avant la coche, il dit « terminer ceci ouvre… » ; lu sur
    l'état rechargé après, il dit ce qui vient de s'ouvrir (§100)."""
    resultat = []
    for sid in reseau.aval.get(tid, []):
        if _faite(reseau, sid):
            continue
        autres = [pid for pid in reseau.amont.get(sid, []) if pid != tid]
        if all(_faite(reseau, pid) for pid in autres):
            resultat.append(sid)
    return sorted(resultat, key=lambda s: cle_titre(str(reseau.par_id[s]["title"])))


def impact(reseau: Reseau, tid: str) -> int:
    """Combien de tâches ouvertes attendent, de près ou de loin, ``tid``."""
    return sum(1 for mid, _ in chaine(reseau, tid, "aval") if not _faite(reseau, mid))


def faisables(reseau: Reseau) -> list[str]:
    """Les faisables maintenant, celles qui libèrent le plus d'abord, puis
    par titre : la première est la tâche à faire ce soir."""
    ouvertes = [
        t for t in reseau.taches if statut_de(reseau, str(t["id"])) == "feasible"
    ]
    ouvertes.sort(
        key=lambda t: (-impact(reseau, str(t["id"])), cle_titre(str(t["title"])))
    )
    return [str(t["id"]) for t in ouvertes]


__all__ = [
    "Reseau",
    "Sens",
    "Statut",
    "ce_que_debloque",
    "chaine",
    "cle_titre",
    "construire_reseau",
    "faisables",
    "impact",
    "statut_de",
    "voisines_ordonnees",
]
