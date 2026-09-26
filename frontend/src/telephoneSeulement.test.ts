import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * « Le bureau et le mini-panneau ne changent pas » (chantier de la fluidité,
 * 26/09/2026). Contre-épreuve du même jour : chacune de ces mutations
 * laissait les 1 580 tests verts — la roue montée partout (A1), la barre
 * latérale retirée au Mac (A2), le préchargement lancé au bureau (A3), la
 * cloche du téléphone revenue à 5 s (A8). Aucun test ne lisait Layout.tsx,
 * App.tsx ni ApprovalBell.tsx : on les lit ici comme du texte, à la manière
 * de routesVie.test.ts, faute de tests de composants dans ce dépôt.
 */
const lire = (chemin: string) => readFileSync(join(__dirname, chemin), 'utf8');
const sansCommentaires = (code: string) =>
  code.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');

describe('Layout.tsx', () => {
  const layout = sansCommentaires(lire('components/Layout.tsx'));
  const compact = layout.slice(layout.indexOf('if (estCompact) {\n    return ('), layout.indexOf('  return (\n    <div className="flex flex-col h-full w-full overflow-hidden relative" style'));

  it('ne monte la roue qu’au téléphone, une seule fois, hors du mini-panneau', () => {
    expect(layout.match(/<RoueNavigation\b/g)?.length, 'une seule roue').toBe(1);
    expect(layout, 'la roue sous estMobile').toMatch(/\{estMobile && <RoueNavigation \/>\}/);
    expect(compact.length, 'la branche du mini-panneau est trouvée').toBeGreaterThan(100);
    expect(compact, 'le mini-panneau n’a pas de roue').not.toContain('RoueNavigation');
  });

  it('garde la barre latérale et son voile au Mac', () => {
    expect(layout).toMatch(/\{!estMobile && <Sidebar \/>\}/);
    expect(layout).toMatch(/\{!estMobile && sidebarOpen && \(/);
    expect(layout.match(/<Sidebar\b/g)?.length, 'une seule barre latérale').toBe(1);
  });

  it('ne réserve la bande de la roue qu’au téléphone', () => {
    for (const ligne of layout.split('\n').filter((l) => l.includes('--reserve-roue'))) {
      expect(ligne, 'la réserve de la roue dépend d’estMobile').toContain('estMobile');
    }
  });
});

describe('App.tsx', () => {
  const app = sansCommentaires(lire('App.tsx'));

  it('ne précharge les pages qu’au téléphone', () => {
    const effet = app.slice(app.lastIndexOf('useEffect(() => {', app.indexOf('piloterPrechargement(PAGES')), app.indexOf('piloterPrechargement(PAGES'));
    expect(effet.trim(), 'l’effet du préchargement commence par sortir hors du téléphone').toMatch(
      /^useEffect\(\(\) => \{\s*if \(!estMobile\) return;/,
    );
  });
});

describe('ApprovalBell.tsx', () => {
  it('relève la cloche au rythme du téléphone au téléphone, du Mac au Mac', () => {
    const cloche = sansCommentaires(lire('components/ApprovalBell.tsx'));
    expect(cloche, 'la cadence vient de cadenceCloche.ts, selon estMobile').toContain(
      'intervalleCloche(approvals.length, estMobile)',
    );
    expect(cloche, 'aucun intervalle en dur').not.toMatch(/setInterval\([^)]*,\s*\d/);
  });
});

describe('RoueNavigation.tsx', () => {
  const roue = sansCommentaires(lire('features/roue/RoueNavigation.tsx'));

  it('branche le retour d’Android et l’inertie sur leurs fonctions pures', () => {
    expect(roue).toContain('pontNatif.surRetour(() => reponseAuRetour(ouverteRef.current, fermerEtRendreLeFocus))');
    expect(roue).toContain('return rendreInertes(freresARendreInertes(moi));');
  });
});

describe('pageParesseuse.tsx', () => {
  it('rend au montage le module déjà arrivé', () => {
    const page = sansCommentaires(lire('lib/pageParesseuse.tsx'));
    expect(page).toMatch(/useState\(\(\) => composantInitial<[^>]+>>\(memo, Paresseuse\)\)/);
  });
});
