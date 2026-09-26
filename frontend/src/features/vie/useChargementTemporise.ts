import { useEffect, useRef } from 'react';

/**
 * Le délai entre deux frappes dans la recherche et la relecture. 180 ms :
 * assez pour absorber une frappe courante (~120 ms entre deux touches), sous
 * le seuil où l'on sent l'attente.
 */
export const DELAI_FRAPPE_MS = 180;

/**
 * Lance `charger` TOUT DE SUITE au montage, puis temporise seulement quand
 * `frappe` (la recherche tapée) change.
 *
 * Jusqu'au 18 sept. 2026, Tâches, Projets et Notes retardaient même leur
 * premier chargement de 180 ms — le débounce de frappe s'appliquait au
 * montage, où il n'y a rien à absorber. Ajouté à un état vide par montage,
 * chaque retour sur la page coûtait 180 ms de spinner avant même la première
 * requête, pour un serveur qui répond en 20-40 ms.
 *
 * `charger` peut changer d'identité sans que `frappe` change (une autre
 * dépendance du `useCallback`) : la relecture est alors immédiate, comme au
 * montage — c'est la temporisation qui est réservée à la frappe, pas
 * l'inverse.
 */
export function useChargementTemporise(charger: () => void, frappe: string, delaiMs = DELAI_FRAPPE_MS): void {
  const derniereFrappe = useRef<string | null>(null);
  useEffect(() => {
    if (derniereFrappe.current === null || derniereFrappe.current === frappe) {
      derniereFrappe.current = frappe;
      charger();
      return;
    }
    const timer = window.setTimeout(() => {
      derniereFrappe.current = frappe;
      charger();
    }, delaiMs);
    return () => window.clearTimeout(timer);
  }, [charger, frappe, delaiMs]);
}
