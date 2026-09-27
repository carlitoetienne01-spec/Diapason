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
  const compact = layout.slice(layout.indexOf('if (estCompact) {\n    return ('), layout.indexOf('  return (\n    <div className="h-full w-full overflow-hidden relative">'));

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

  it('ne fait reculer la page qu’au téléphone, roue ouverte, et la roue reste hors du bloc qui recule', () => {
    // 26/09/2026, surimpression : le recul (scale 0.95) vit dans roue.css et
    // ne s'applique que sous [data-diapason-mobile] ET [data-roue-ouverte],
    // que seule la roue écrit — le bureau et le mini-panneau ne bougent pas.
    expect(layout.match(/data-recul-page/g)?.length, 'un seul bloc qui recule').toBe(1);
    expect(compact, 'le mini-panneau n’a pas de bloc qui recule').not.toContain('data-recul-page');
    const apresRecul = layout.slice(layout.indexOf('data-recul-page'));
    expect(apresRecul, 'la roue est montée APRÈS le bloc qui recule, pas dedans').toMatch(
      /\{estMobile && <RoueNavigation \/>\}/,
    );
    const css = sansCommentaires(lire('features/roue/roue.css'));
    expect(css, 'le recul exige le mode téléphone ET la roue ouverte').toMatch(
      /html\[data-diapason-mobile='1'\]\[data-roue-ouverte\] \[data-recul-page\] \{\s*transform: scale\(0\.95\);/,
    );
    expect(css, 'le bloc contenant des position:fixed est permanent au téléphone').toMatch(
      /html\[data-diapason-mobile='1'\] \[data-recul-page\] \{\s*will-change: transform;\s*transition: transform 180ms ease-out;/,
    );
    const roueTsx = sansCommentaires(lire('features/roue/RoueNavigation.tsx'));
    expect(roueTsx, 'seule la roue écrit data-roue-ouverte').toContain("racine.setAttribute('data-roue-ouverte', '')");
    const partout = ['components/Layout.tsx', 'App.tsx', 'main.tsx'].map((f) => sansCommentaires(lire(f))).join('\n');
    expect(partout, 'personne d’autre ne l’écrit').not.toContain('data-roue-ouverte');
  });

  it('ne réserve la bande de la roue qu’au téléphone, autour de la seule Discussion', () => {
    const lignes = layout.split('\n').filter((l) => l.includes('--reserve-roue'));
    expect(lignes.length).toBe(1);
    // 26/09/2026, contre-épreuve : réservée autour de chaque page, la bande
    // faisait 68 px morts en bas de l'écran, où rien ne défilait.
    expect(lignes[0], 'au téléphone, sur la Discussion seulement').toContain("estMobile && pathname === '/'");
    expect(layout, 'la colonne se laisse viser par index.css').toContain('data-colonne-page=""');
    const css = lire('index.css');
    expect(css, 'ailleurs, la bande vit dans le défileur de la page').toMatch(
      /\[data-colonne-page\] > \.overflow-y-auto \{\s*padding-bottom: calc\(var\(--reserve-roue\) \+ 1rem\) !important;/,
    );
  });
});

describe('useTransitionDesPages.ts', () => {
  const crochet = sansCommentaires(lire('lib/useTransitionDesPages.ts'));
  const layout = sansCommentaires(lire('components/Layout.tsx'));

  it('n’anime les pages et ne retient leur position qu’au téléphone', () => {
    // 27/09/2026, lot 2 « soyeux » : le crochet est appelé partout (règle
    // des crochets), mais chacun de ses deux effets sort d'abord hors du
    // téléphone — le bureau et le mini-panneau n'ont ni écouteur, ni
    // animation, ni position reprise.
    expect(layout, 'Layout branche le crochet sur la colonne').toContain('useTransitionDesPages(colonneRef, pathname);');
    expect(layout.match(/ref=\{colonneRef\}/g)?.length, 'une seule colonne visée, celle du téléphone et du bureau').toBe(1);
    const compact = layout.slice(layout.indexOf('if (estCompact) {\n    return ('), layout.indexOf('  return (\n    <div className="h-full w-full overflow-hidden relative">'));
    expect(compact, 'le mini-panneau n’a pas de colonne visée').not.toContain('colonneRef');
    const effets = crochet.match(/use(?:Layout)?Effect\(\(\) => \{\s*[^\n]*\n\s*[^\n]*/g) ?? [];
    expect(effets.length, 'deux effets').toBe(2);
    expect(effets[0], 'retenir : sort hors du téléphone').toMatch(/if \(!estMobile \|\| !colonne\) return undefined;/);
    expect(effets[1], 'animer et reprendre : sort hors du téléphone').toMatch(/useLayoutEffect\(\(\) => \{\s*if \(!estMobile\) return undefined;/);
  });

  it('anime la colonne, jamais la racine de la page qui est son défileur', () => {
    // 27/09/2026, trace CDP à ×4 : animer la racine (le défileur des Notes)
    // fait repeindre tout son contenu, 39 → 97 ms de peinture médiane ; la
    // colonne, stable, la laisse à 46.
    expect(crochet).toContain('entree.current = colonne.animate(IMAGES_ENTREE, OPTIONS_ENTREE);');
    expect(crochet, 'aucune animation posée sur la page elle-même').not.toMatch(/firstElementChild[\s\S]*\.animate\(/);
  });

  it('écoute le défilement sans jamais retenir le doigt', () => {
    expect(crochet, 'l’écoute du défilement est passive').toContain("colonne.addEventListener('scroll', surDefilement, { capture: true, passive: true });");
    expect(crochet, 'les reprises de main aussi').toContain('colonne.addEventListener(type, arreter, { capture: true, passive: true });');
    expect(crochet, 'aucun preventDefault sur le chemin du doigt').not.toContain('preventDefault');
  });

  it('vise le même défileur qu’index.css', () => {
    const decisions = lire('lib/transitionPage.ts');
    expect(decisions).toContain("export const SELECTEUR_DEFILEUR_PAGE = ':scope > .overflow-y-auto';");
    expect(lire('index.css'), 'la bande de la roue vit dans ce même défileur').toContain('[data-colonne-page] > .overflow-y-auto {');
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

  it('le voile ferme par sa fonction pure, et le nom du dialogue reste aux lecteurs d’écran', () => {
    // 26/09/2026, surimpression : le titre visible a disparu (la page derrière
    // situe déjà), mais le dialogue doit toujours s'annoncer « Aller à ».
    expect(roue).toContain("if (toucherDuVoile(surUnBouton, clicAIgnorer()) === 'fermer') fermerEtRendreLeFocus();");
    expect(roue).toMatch(/<h2 id="roue-titre" className="sr-only">/);
    expect(roue, 'l’opacité lisible se mesure sur la capsule du nom').toContain(
      'opaciteMinimale(capsule.color, capsule.backgroundColor)',
    );
    // 27/09/2026 : la capsule entière s'estompait avec son nom, et la page
    // passait à travers. La place porte la PRÉSENCE (opaque tant qu'elle se
    // touche) ; le nom et la pastille portent l'estompage.
    expect(roue).toContain('place.style.opacity = String(p.presence);');
    expect(roue).toContain('nom.style.opacity = String(p.estompe);');
    const css = sansCommentaires(lire('features/roue/roue.css'));
    expect(css, 'la capsule a un fond plein, sans flou').toMatch(/\.roue-element \{[^}]*background: var\(--color-surface\);/);
    expect(css, 'aucun flou dans la roue').not.toMatch(/backdrop-filter|filter:\s*blur/);
  });
});

describe('pageParesseuse.tsx', () => {
  it('rend au montage le module déjà arrivé', () => {
    const page = sansCommentaires(lire('lib/pageParesseuse.tsx'));
    expect(page).toMatch(/useState\(\(\) => composantInitial<[^>]+>>\(memo, Paresseuse\)\)/);
  });
});
