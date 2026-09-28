import { CalendarDays, Check } from 'lucide-react';
import { useContexteNavigation } from './contexteNavigation';
import { correspondALaRecherche } from './navigation';

export function PanneauContextuel({ chemin, recherche }: { chemin: string; recherche: string }) {
  const contexte = useContexteNavigation((s) => s.contexte);
  // Une page paresseuse n'a pas encore publié : ne jamais garder les
  // commandes de la page précédente pendant son chargement.
  if (!contexte || contexte.chemin !== chemin) return null;
  const groupes = contexte.groupes.map((g) => ({
    ...g, choix: g.choix.filter((c) => correspondALaRecherche(c.libelle, recherche)),
  })).filter((g) => g.choix.length);
  return <>
    {contexte.date && !recherche && <label className="navigation-date">
      <span><CalendarDays size={16} />Date du calendrier</span>
      <input type="date" aria-label="Date du calendrier" value={contexte.date.valeur}
        onChange={(e) => { if (e.target.value) contexte.date?.choisir(e.target.value); }} />
    </label>}
    {groupes.map((g) => <div key={g.titre} role="group" aria-label={g.titre}>
      <div className="navigation-section-entete">{g.titre}</div>
      {g.choix.map((c) => <button key={c.id} className="navigation-ligne navigation-choix" onClick={c.choisir} aria-pressed={c.actif}>
        <span>{c.libelle}</span>{c.actif && <Check size={15} aria-hidden="true" />}
      </button>)}
    </div>)}
    {!groupes.length && recherche && <p className="navigation-message">Aucun résultat.</p>}
  </>;
}
