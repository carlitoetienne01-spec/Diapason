import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useAppStore } from '../../lib/store';
import { ajouterEtape, memeEtape, type EtapeNavigation, type HistoriqueNavigation } from './navigation';

export function useHistoriqueNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeId = useAppStore((s) => s.activeId);
  const chemin = location.pathname + location.search;
  const discussion = location.pathname === '/' ? activeId : null;
  const [historique, setHistorique] = useState<HistoriqueNavigation>(() => ({
    etapes: [{ chemin, discussion }], position: 0,
  }));
  const retourEnCours = useRef<EtapeNavigation | null>(null);

  useEffect(() => {
    const etape = { chemin, discussion };
    if (retourEnCours.current) {
      if (memeEtape(retourEnCours.current, etape)) retourEnCours.current = null;
      return;
    }
    setHistorique((precedent) => ajouterEtape(precedent, etape));
  }, [chemin, discussion, location.key]);

  const aller = (sens: -1 | 1) => {
    const position = historique.position + sens;
    const cible = historique.etapes[position];
    if (!cible) return;
    const etape = { ...cible };
    // 28/09/2026 : une discussion supprimée depuis la liste ne doit pas
    // bloquer tous les prochains retours en attendant un ID inexistant.
    if (etape.chemin === '/' && !useAppStore.getState().conversations.some((c) => c.id === etape.discussion)) {
      etape.discussion = useAppStore.getState().activeId;
    }
    retourEnCours.current = etape;
    setHistorique({ ...historique, position });
    if (etape.discussion) useAppStore.getState().selectConversation(etape.discussion);
    navigate(etape.chemin);
  };

  return {
    precedent: historique.position > 0,
    suivant: historique.position < historique.etapes.length - 1,
    aller,
  };
}
