import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

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
/** Le début du rendu hors mini-panneau (le téléphone et le bureau). */
const RETOUR_TELEPHONE_ET_BUREAU = '  return (\n    <div className="h-full w-full overflow-hidden mobile:overflow-visible relative">';
const lire = (chemin: string) => readFileSync(join(__dirname, chemin), 'utf8');
const sansCommentaires = (code: string) =>
  code.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');

/** Tous les fichiers de src/ d'une extension, tests exclus. */
function fichiers(extensions: readonly string[], dossier = __dirname): string[] {
  return readdirSync(dossier, { withFileTypes: true }).flatMap((e) => {
    const chemin = join(dossier, e.name);
    if (e.isDirectory()) return fichiers(extensions, chemin);
    return extensions.some((x) => e.name.endsWith(x)) && !/\.test\.tsx?$/.test(e.name) ? [chemin] : [];
  });
}

/** Les <div> ouverts (non auto-fermés) et fermés d'un morceau de JSX ; les
 *  accolades sont suivies, un `=>` dans un attribut ne ferme pas la balise. */
function equilibreDesDiv(jsx: string): { ouverts: number; fermes: number } {
  let ouverts = 0;
  for (let i = jsx.indexOf('<div'); i >= 0; i = jsx.indexOf('<div', i + 1)) {
    if (!/[\s>]/.test(jsx[i + 4] ?? '')) continue;
    let accolades = 0;
    let j = i + 4;
    for (; j < jsx.length; j += 1) {
      if (jsx[j] === '{') accolades += 1;
      else if (jsx[j] === '}') accolades -= 1;
      else if (jsx[j] === '>' && accolades === 0) break;
    }
    if (jsx[j - 1] !== '/') ouverts += 1;
  }
  return { ouverts, fermes: (jsx.match(/<\/div>/g) ?? []).length };
}

type Regle = { selecteurs: string[]; corps: string; media: string | null };

/** Les règles d'une feuille (sans commentaires), @media déplié, @layer traversé. */
function regles(css: string, media: string | null = null): Regle[] {
  const sortie: Regle[] = [];
  let i = 0;
  while (i < css.length) {
    const ouvre = css.indexOf('{', i);
    if (ouvre < 0) break;
    const tete = css.slice(i, ouvre).trim();
    let profondeur = 1;
    let j = ouvre + 1;
    while (j < css.length && profondeur > 0) {
      if (css[j] === '{') profondeur += 1;
      else if (css[j] === '}') profondeur -= 1;
      j += 1;
    }
    const corps = css.slice(ouvre + 1, j - 1);
    const enTete = tete.slice(tete.lastIndexOf(';') + 1).trim();
    if (enTete.startsWith('@media') || enTete.startsWith('@supports')) sortie.push(...regles(corps, enTete));
    else if (enTete.startsWith('@layer')) sortie.push(...regles(corps, media));
    else if (!enTete.startsWith('@')) {
      sortie.push({ selecteurs: enTete.split(',').map((x) => x.trim()).filter(Boolean), corps, media });
    }
    i = j;
  }
  return sortie;
}

/** Les déclarations `propriété: valeur` d'un corps de règle. */
function declarations(corps: string): [string, string][] {
  return corps
    .split(';')
    .map((d) => d.trim())
    .filter((d) => d.includes(':') && !d.includes('{'))
    .map((d) => [d.slice(0, d.indexOf(':')).trim(), d.slice(d.indexOf(':') + 1).trim()] as [string, string]);
}

const TOUTES_LES_FEUILLES = () => fichiers(['.css']).map((f) => ({ f, css: sansCommentaires(readFileSync(f, 'utf8')) }));
const MOBILE = "html[data-diapason-mobile='1']";

describe('Layout.tsx', () => {
  const layout = sansCommentaires(lire('components/Layout.tsx'));
  const compact = layout.slice(layout.indexOf('if (estCompact) {\n    return ('), layout.indexOf(RETOUR_TELEPHONE_ET_BUREAU));

  it('ne monte la roue qu’au téléphone, une seule fois, hors du mini-panneau', () => {
    expect(layout.match(/<RoueNavigation\b/g)?.length, 'une seule roue').toBe(1);
    expect(layout, 'la roue sous estMobile').toMatch(/\{estMobile && <RoueNavigation \/>\}/);
    expect(compact.length, 'la branche du mini-panneau est trouvée').toBeGreaterThan(100);
    expect(compact, 'le mini-panneau n’a pas de roue').not.toContain('RoueNavigation');
  });

  it('garde la barre latérale et son voile au Mac', () => {
    expect(layout).toMatch(/\{!estMobile && <Sidebar \/>\}/);
    // 28/09/2026 : le rail du bureau montre son panneau selon la page
    // (panneauVisible) ; la garde « rien de tout cela au téléphone » reste.
    expect(layout).toMatch(/\{!estMobile && panneauVisible\(sidebarOpen, pathname\) && \(/);
    expect(layout.match(/<Sidebar\b/g)?.length, 'une seule barre latérale').toBe(1);
  });

  it('ne fait reculer la page qu’au téléphone, roue ouverte, et la roue reste hors du bloc qui recule', () => {
    // 26/09/2026, surimpression : le recul (scale 0.95) vit dans roue.css et
    // ne s'applique que sous [data-diapason-mobile] ET [data-roue-ouverte],
    // que seule la roue écrit — le bureau et le mini-panneau ne bougent pas.
    expect(layout.match(/data-recul-page/g)?.length, 'un seul bloc qui recule').toBe(1);
    expect(compact, 'le mini-panneau n’a pas de bloc qui recule').not.toContain('data-recul-page');
    // « Après, pas dedans » (27/09/2026, contre-épreuve, mutant A) : chercher
    // la roue APRÈS l'attribut restait vrai quand elle était montée DANS le
    // bloc — elle aurait reculé à 95 % avec la page, et son voile fixe aurait
    // eu le bloc transformé pour bloc contenant. Entre l'ouverture du bloc
    // et la roue, les <div> ouverts et fermés doivent s'équilibrer : le bloc
    // est refermé quand la roue arrive. Et la roue est la frère DIRECT du
    // bloc (freresARendreInertes le rend inerte, lui) : dernière enfant du
    // cadre, suivie de sa fermeture.
    const debutRecul = layout.lastIndexOf('<div', layout.indexOf('data-recul-page'));
    const ligneRoue = layout.indexOf('{estMobile && <RoueNavigation />}');
    expect(debutRecul, 'le bloc qui recule est trouvé').toBeGreaterThan(0);
    expect(ligneRoue, 'la roue suit le bloc').toBeGreaterThan(debutRecul);
    const { ouverts, fermes } = equilibreDesDiv(layout.slice(debutRecul, ligneRoue));
    expect(ouverts, 'la roue est montée APRÈS la fermeture du bloc qui recule, pas dedans').toBe(fermes);
    expect(layout.slice(ligneRoue), 'la roue est la dernière enfant du cadre, frère direct du bloc').toMatch(
      /^\{estMobile && <RoueNavigation \/>\}\s*<\/div>\s*\);/,
    );
    const cadre = layout.slice(layout.lastIndexOf('<div', debutRecul - 1), debutRecul);
    expect(cadre, 'le bloc qui recule est le premier enfant du cadre').toMatch(/^<div className="h-full w-full [^"]*">\s*$/);
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
    expect(layout, 'Layout branche le crochet sur la colonne').toContain("useTransitionDesPages(colonneRef, pathname, state?.diapasonRoue ? state.directionRoue : undefined);");
    expect(layout.match(/ref=\{colonneRef\}/g)?.length, 'une seule colonne visée, celle du téléphone et du bureau').toBe(1);
    const compact = layout.slice(layout.indexOf('if (estCompact) {\n    return ('), layout.indexOf(RETOUR_TELEPHONE_ET_BUREAU));
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
    const suivi = sansCommentaires(lire('lib/suiviDesPages.ts'));
    expect(suivi).toContain('entree = colonne.animate(directionRoue ? [');
    expect(suivi.match(/\.animate\(/g)?.length, 'une seule animation, sur la colonne').toBe(1);
    expect(crochet, 'le crochet n’anime rien lui-même').not.toContain('.animate(');
    expect(crochet, 'il branche le suivi sur la colonne, avant la peinture').toContain(
      'return suivi.current?.naviguer(colonneRef.current, chemin, directionRoue);',
    );
  });

  it('écoute le défilement sans jamais retenir le doigt', () => {
    const suivi = sansCommentaires(lire('lib/suiviDesPages.ts'));
    expect(crochet, 'l’écoute du défilement est passive').toContain("colonne.addEventListener('scroll', surDefilement, { capture: true, passive: true });");
    expect(suivi, 'les reprises de main aussi').toContain('colonne.addEventListener(type, arreter, { capture: true, passive: true });');
    expect(crochet + suivi, 'aucun preventDefault sur le chemin du doigt').not.toContain('preventDefault');
  });

  it('vise le même défileur qu’index.css', () => {
    const decisions = lire('lib/transitionPage.ts');
    expect(decisions).toContain("export const SELECTEUR_DEFILEUR_PAGE = ':scope > .overflow-y-auto';");
    expect(lire('index.css'), 'la bande de la roue vit dans ce même défileur').toContain('[data-colonne-page] > .overflow-y-auto {');
  });
});

describe('index.css — la barre de défilement (lot 3 « soyeux »)', () => {
  // 27/09/2026. La barre dessinée (::-webkit-scrollbar) est peinte par le fil
  // principal : au téléphone, chaque image d'un défilement repeignait la page
  // (trace CDP à ×4, six glissés : 170 à 211 Paint avec elle, 0 à 11 sans).
  const css = sansCommentaires(lire('index.css'));

  it('ne dessine la barre de défilement qu’au bureau et au mini-panneau', () => {
    const selecteurs = [...css.matchAll(/([^{}]*::-webkit-scrollbar[^{}]*)\{/g)].map((m) => m[1].trim());
    expect(selecteurs.length, 'les règles de la barre sont trouvées').toBeGreaterThanOrEqual(4);
    for (const s of selecteurs) {
      expect(s, `« ${s} » doit exclure le téléphone`).toContain(":not([data-diapason-mobile='1'])");
    }
    expect(css, 'la barre du bureau garde ses 6 px').toMatch(
      /html:not\(\[data-diapason-mobile='1'\]\) ::-webkit-scrollbar \{\s*width: 6px;\s*height: 6px;/,
    );
  });
});

describe('index.css — l’élan du défilement (lot 3 « soyeux »)', () => {
  // 27/09/2026. Au téléphone, le rebond de fin de liste d'Android (l'étirement)
  // ne joue que sur le défileur RACINE ; Chromium n'y promeut le défileur d'une
  // page que s'il remplit la fenêtre, qu'aucun ancêtre ne le coupe et qu'il n'a
  // pas de barre dessinée. Mesuré sur l'émulateur : chacune des trois
  // conditions, seule, suffisait à tout bloquer (la barre dessinée : le bloc
  // précédent).
  const css = sansCommentaires(lire('index.css'));
  const layout = sansCommentaires(lire('components/Layout.tsx'));

  it('au téléphone, rien ne coupe entre le défileur de la page et la fenêtre', () => {
    expect(css, 'body et #root ne coupent plus au téléphone').toContain(
      `${MOBILE} body,\n${MOBILE} #root {\n  overflow: visible;\n}`,
    );
    // 27/09/2026, contre-épreuve : <html> rendu visible, tout débord de la
    // colonne rendait le DOCUMENT défilable au doigt (12 px à chaque entrée
    // de page, 117 aux Réglages en Phosphore) — la cloche et le voyant
    // descendaient avec lui. <html> garde son hidden : la fenêtre ne défile
    // jamais au doigt, et l'étirement joue toujours (émulateur).
    const surHtml = regles(css).filter((r) =>
      r.selecteurs.some((x) => /^html(\[[^\]]*\])*$/.test(x) && x.includes('data-diapason-mobile')),
    );
    for (const r of surHtml) {
      const o = declarations(r.corps).find(([p]) => /^overflow(-y)?$/.test(p));
      expect(o?.[1] ?? 'hidden', `« ${r.selecteurs.join(', ')} » rendrait la fenêtre défilable au doigt`).toMatch(/hidden|clip/);
    }
    expect(css, 'au bureau, ils coupent toujours').toMatch(/html, body, #root \{\s*height: 100%;\s*width: 100%;\s*overflow: hidden;/);
    expect(layout, 'le cadre de Layout ne coupe pas au téléphone').toContain(RETOUR_TELEPHONE_ET_BUREAU);
    expect(layout, '<main> non plus').toMatch(/<main className="[^"]*\boverflow-hidden mobile:overflow-visible\b/);
  });

  it('au téléphone, le défileur de la page touche le haut de la fenêtre et porte les bandes du voyant et de la cloche', () => {
    expect(css, 'la colonne et le bloc qui recule rendent leur marge haute, seulement quand la page a un défileur').toContain(
      `${MOBILE} [data-recul-page]:has([data-colonne-page] > .overflow-y-auto),\n${MOBILE} [data-colonne-page]:has(> .overflow-y-auto) {\n  padding-top: 0 !important;\n}`,
    );
    const bande = css.match(/html\[data-diapason-mobile='1'\] \[data-colonne-page\] > \.overflow-y-auto::before \{\s*content: '';\s*display: block;\s*height: calc\((\d+)px \+ var\(--bande-barre-fermee, 0px\)\);/);
    expect(bande, 'la bande passe DANS le défileur').not.toBeNull();
    const voyant = layout.match(/data-recul-page="" className="[^"]*" style=\{\{ paddingTop: '(\d+)px' \}\}/);
    expect(voyant, 'Layout réserve la bande du voyant').not.toBeNull();
    expect(bande?.[1], 'la bande du voyant a la même hauteur dans le défileur que dans Layout').toBe(voyant?.[1]);
  });

  it('le libellé de « Roue à gauche » reste dans le défileur des Réglages, sans positionner le défileur', () => {
    // 27/09/2026, contre-épreuve : ce libellé sr-only avait la colonne pour
    // bloc contenant, échappait au défileur et rendait le DOCUMENT défilable
    // de 117 px (Phosphore). Le premier remède — `position: relative` sur
    // tout défileur de page — faisait repeindre les Notes à chaque image d'un
    // défilement (trace CDP, six glissés : 124 Paint contre 2). Le banc
    // mesure le document sur les 17 pages et les 7 apparences ; ce test tient
    // le remède ciblé et interdit le premier.
    const reglages = sansCommentaires(lire('pages/SettingsPage.tsx'));
    const roue = reglages.slice(reglages.indexOf("t('settings.roue.gauche')} description"));
    expect(roue.slice(0, 400), 'le label de l’interrupteur est positionné').toContain('<label className="relative inline-flex');
    const surDefileur = regles(css).filter((r) => r.selecteurs.some((x) => /\[data-colonne-page\] > \.overflow-y-auto$/.test(x)));
    for (const r of surDefileur) {
      expect(declarations(r.corps).map(([p]) => p), 'le défileur de page n’est jamais positionné : il repeindrait à chaque image').not.toContain('position');
    }
  });

  it('au téléphone, le voile modal assombrit aussi la bande où la page défile', () => {
    expect(css).toContain(`${MOBILE} .voile-modal {\n  top: 0;\n  border-top: var(--bande-barre-fermee, 0px) solid transparent;\n}`);
    expect(css, 'au bureau, il part toujours sous la bande').toMatch(/\.voile-modal \{\s*position: fixed;\s*top: var\(--bande-barre-fermee, 0px\);/);
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
    expect(roue).toContain("if (toucherDuVoile(cibleEstUnBouton(e.target), clicAIgnorer()) === 'fermer') fermerEtRendreLeFocus();");
    expect(roue).toMatch(/<h2 id="roue-titre" className="sr-only">/);
    expect(roue, 'l’opacité lisible se mesure sur la capsule du nom').toContain(
      'opaciteMinimale(capsule.color, capsule.backgroundColor)',
    );
    // 27/09/2026 : la capsule entière s'estompait avec son nom, et la page
    // passait à travers. La place porte la PRÉSENCE (opaque tant qu'elle se
    // touche) ; le nom et la pastille portent l'estompage.
    expect(roue).toContain('place.style.opacity = String(p.presence);');
    expect(roue.match(/place\.style\.opacity = /g)?.length, 'rien d’autre n’écrit l’opacité de la capsule').toBe(1);
    expect(roue).toContain('nom.style.opacity = String(p.estompe);');
    const css = sansCommentaires(lire('features/roue/roue.css'));
    expect(css, 'la capsule a un fond plein, sans flou').toMatch(/\.roue-element \{[^}]*background: var\(--color-surface\);/);
    expect(css, 'aucun flou dans la roue').not.toMatch(/backdrop-filter|filter:\s*blur/);
  });
});

describe('RoueNavigation.tsx — le câblage (contre-épreuve « soyeux », 27/09/2026)', () => {
  // Les fonctions pures de la roue étaient tenues, leur APPEL non : ces
  // mutations survivaient à la suite complète (1 664 tests). Chaque test
  // ci-dessous en tue une, au grain de la ligne.
  const roue = sansCommentaires(lire('features/roue/RoueNavigation.tsx'));

  /** Le corps d'un bloc qui commence par `debut`, accolades équilibrées. */
  const bloc = (debut: string) => {
    const i = roue.indexOf(debut);
    expect(i, `« ${debut} » est trouvé`).toBeGreaterThanOrEqual(0);
    let profondeur = 0;
    for (let j = roue.indexOf('{', i); j < roue.length; j += 1) {
      if (roue[j] === '{') profondeur += 1;
      else if (roue[j] === '}' && --profondeur === 0) return roue.slice(i, j + 1);
    }
    return '';
  };

  it('§82 : Échap ferme la roue et rend le focus (mutant E)', () => {
    const echap = bloc("if (e.key === 'Escape') {");
    expect(echap).toMatch(/e\.preventDefault\(\);\s*fermerEtRendreLeFocus\(\);\s*return;/);
    expect(roue, 'la touche est écoutée sur le dialogue').toMatch(/role="dialog"[^>]*onKeyDown=\{surTouche\}/);
  });

  it('§82 : le toucher du voile est branché sur le dialogue (mutant F)', () => {
    const dialogue = roue.slice(roue.lastIndexOf('<div', roue.indexOf('role="dialog"')), roue.indexOf('>', roue.indexOf('onClick={surVoile}')) + 1);
    expect(dialogue, 'le voile est l’élément role="dialog"').toContain('role="dialog"');
    expect(dialogue, 'son toucher passe par surVoile').toContain('onClick={surVoile}');
    expect(roue.match(/onClick=\{surVoile\}/g)?.length, 'une seule fois').toBe(1);
  });

  it('§82 : le retour d’Android est branché roue OUVERTE, et seulement alors (mutant H)', () => {
    expect(roue).toMatch(
      /useEffect\(\(\) => \{\s*if \(!ouverte \|\| !pontNatif\) return undefined;\s*return pontNatif\.surRetour\(\(\) => reponseAuRetour\(ouverteRef\.current, fermerEtRendreLeFocus\)\);\s*\}, \[ouverte, fermerEtRendreLeFocus\]\);/,
    );
  });

  it('la page dessous est inerte roue OUVERTE, et seulement alors (mutant I)', () => {
    // df89435a : 44 boutons de la page restaient lisibles sous l'écran
    // « Aller à ». Au banc, roue ouverte : 21 boutons exposés.
    expect(roue).toMatch(
      /const moi = racineRef\.current;\s*if \(!ouverte \|\| !moi\) return undefined;\s*return rendreInertes\(freresARendreInertes\(moi\)\);\s*\}, \[ouverte\]\);/,
    );
    expect(roue, 'la racine de la roue ne crée pas de boîte : ses frères sont ceux du cadre de Layout').toMatch(
      /<div ref=\{racineRef\} data-roue="" style=\{\{ display: 'contents' \}\}>/,
    );
  });

  it('le glissé depuis le bord : la bande, puis la direction, dans le bon ordre des axes (mutants O1, O2)', () => {
    expect(roue).toContain('if (!commenceDansLaBande(t.clientX, t.clientY, window.innerWidth, window.innerHeight, c)) return;');
    expect(roue).toContain('const decision = decisionDuBord(t.clientX - b.x, t.clientY - b.y, suite.cote);');
  });

  it('clavier ouvert, le bouton se retire : l’attribut est posé et retiré (mutant O3)', () => {
    expect(roue).toMatch(
      /if \(ouvert\) racine\.setAttribute\('data-clavier-ouvert', ''\);\s*else racine\.removeAttribute\('data-clavier-ouvert'\);/,
    );
  });

  it('l’opacité lisible se mesure sur une capsule NON allumée, et la géométrie la borne (mutants J1, O4)', () => {
    expect(roue).toContain('const temoin = elementsRef.current.find((el, i) => el && i !== allumeRef.current);');
    expect(roue).toMatch(/geometrieRoue\(\{ largeur: r\.width, hauteur: r\.height, cote, haut: 0, bas: r\.height - 68, opaciteLisible \}\)/);
    const geo = sansCommentaires(lire('features/roue/geometrieRoue.ts'));
    expect(geo, 'la mesure passe par la borne').toContain('opaciteLisible: opaciteLisibleBornee(entree.opaciteLisible),');
  });

  it('les écouteurs tactiles posés sur la fenêtre sont passifs (mutant L1)', () => {
    // 27/09/2026 : ces quatre écouteurs sont sur le chemin de CHAQUE
    // défilement de chaque page. Non passifs, chaque touchmove attendrait le
    // fil principal.
    expect(roue).toContain('const options = { passive: true } as const;');
    for (const type of ['touchstart', 'touchmove', 'touchend', 'touchcancel']) {
      expect(roue).toMatch(new RegExp(`window\\.addEventListener\\('${type}', \\w+, options\\);`));
    }
  });
});

describe('src/ — le chemin du doigt (contre-épreuve « soyeux », 27/09/2026)', () => {
  /**
   * Les seuls écouteurs `wheel` non passifs admis : chacun est posé sur SON
   * élément (le zoom d'une photo, la carte mentale), jamais sur la fenêtre ni
   * sur une page, et une molette n'arrive pas d'un doigt.
   */
  const NON_PASSIFS_ADMIS = [
    "features/vie/PhotoPleinCadre.tsx: el.addEventListener('wheel', surMolette, { passive: false });",
    "features/vie/MindMapView.tsx: svg.addEventListener('wheel', onWheel, { passive: false });",
    // 28/09/2026 : seulement la grille de projets, après 400 ms de prise.
    // Le test DOM installerGesteProjets garantit que les glissés ordinaires
    // restent natifs ; annuler le déplacement ne doit jamais l'enregistrer.
    "features/vie/installerGesteCartables.ts: grille.addEventListener('touchmove', mouvement, { passive: false });",
    "features/vie/installerGesteCartables.ts: grille.addEventListener('touchend', fin, { passive: false });",
    "features/vie/installerGesteCartables.ts: grille.addEventListener('touchcancel', fin, { passive: false });",
  ];

  it('tout écouteur touch… ou wheel est passif, ou figure dans la liste commentée', () => {
    const trouves: string[] = [];
    for (const f of fichiers(['.ts', '.tsx'])) {
      const code = sansCommentaires(readFileSync(f, 'utf8'));
      const nom = relative(__dirname, f);
      for (const m of code.matchAll(/(\w+)\.addEventListener\(\s*'(touch\w+|wheel)',\s*(\w+),\s*([^)]*)\)/g)) {
        const ligne = `${nom}: ${m[0]};`;
        trouves.push(ligne);
        const options = m[4].trim();
        const passif =
          /passive: true/.test(options) ||
          (/^\w+$/.test(options) && new RegExp(`const ${options} = \\{ passive: true \\} as const;`).test(code));
        if (!passif) expect(NON_PASSIFS_ADMIS, `« ${ligne} » retient le doigt`).toContain(ligne);
      }
    }
    expect(trouves.length, 'les écouteurs sont bien trouvés (la roue en pose quatre)').toBeGreaterThanOrEqual(6);
  });
});

describe('Les gardes en négatif (contre-épreuve « soyeux », 27/09/2026)', () => {
  // Les gardes précédents vérifiaient qu'une règle EXISTE, jamais qu'aucune
  // autre ne la contredise : six mutations survivaient (B1, B2, L3, L4, P1,
  // P2). On parcourt ici toutes les feuilles et Layout.tsx.
  const feuilles = TOUTES_LES_FEUILLES();
  const toutes = feuilles.flatMap(({ f, css }) => regles(css).map((r) => ({ ...r, f: relative(__dirname, f) })));

  it('toute règle qui vise [data-recul-page] exige le téléphone (mutants B1, B2)', () => {
    let vues = 0;
    for (const r of toutes) {
      for (const sel of r.selecteurs.filter((x) => x.includes('data-recul-page'))) {
        vues += 1;
        expect(sel.startsWith(MOBILE), `${r.f} : « ${sel} » s’appliquerait au bureau`).toBe(true);
      }
    }
    expect(vues, 'les règles du recul sont trouvées').toBeGreaterThanOrEqual(3);
  });

  it('aucune barre dessinée au téléphone, dans aucune feuille (mutant P1)', () => {
    let vues = 0;
    for (const r of toutes) {
      for (const sel of r.selecteurs.filter((x) => x.includes('::-webkit-scrollbar'))) {
        vues += 1;
        expect(sel, `${r.f} : « ${sel} » doit exclure le téléphone`).toContain(":not([data-diapason-mobile='1'])");
      }
    }
    expect(vues).toBeGreaterThanOrEqual(4);
  });

  it('au téléphone, rien ne coupe entre le défileur de la page et la fenêtre (mutants L3, L4)', () => {
    // Le sujet d'un sélecteur : son dernier composé. Ces ancêtres du défileur
    // ne doivent jamais recevoir overflow hidden ou clip au téléphone ; la
    // règle de base du bureau (html, body, #root) est tenue plus haut, avec
    // l'annulation qui la suit au téléphone.
    // <html> n'y est pas : il GARDE son hidden au téléphone (la fenêtre ne
    // défile jamais au doigt), et c'est un ancêtre de la fenêtre, pas du
    // défileur — il n'éteint pas l'étirement (émulateur, 27/09/2026).
    const ANCETRES = /^(body|#root|main|\[data-colonne-page\]|\[data-recul-page\])$/;
    const BASE_DU_BUREAU = ['html', 'body', '#root'];
    for (const r of toutes) {
      const coupe = declarations(r.corps).some(([p, v]) => /^overflow(-[xy])?$/.test(p) && /\b(hidden|clip)\b/.test(v));
      if (!coupe) continue;
      for (const sel of r.selecteurs) {
        const sujet = sel.split(/\s+|>/).filter(Boolean).pop() ?? '';
        if (!ANCETRES.test(sujet)) continue;
        if (BASE_DU_BUREAU.includes(sel)) continue;
        expect(sel, `${r.f} : « ${sel} » couperait au téléphone`).toContain(":not([data-diapason-mobile='1'])");
      }
    }
    const layout = sansCommentaires(lire('components/Layout.tsx'));
    const cheminDuDefileur = layout.slice(layout.indexOf(RETOUR_TELEPHONE_ET_BUREAU), layout.indexOf('data-colonne-page=""') + 400);
    for (const m of cheminDuDefileur.matchAll(/className="([^"]*)"/g)) {
      const classes = m[1].split(/\s+/);
      const coupe = classes.some((c) => /^overflow(-[xy])?-(hidden|clip)$/.test(c));
      if (coupe) expect(classes, `« ${m[1]} » couperait au téléphone`).toContain('mobile:overflow-visible');
    }
  });

  it('la colonne ne porte jamais de transform permanent, ni de calque (mutant P2)', () => {
    // Un transform laissé sur la colonne fait d'elle le bloc contenant des
    // position:fixed de la page (le volet d'une tâche des Projets) : l'entrée
    // l'anime 180 ms, `fill: 'none'`, et rien ne doit le poser à demeure.
    for (const r of toutes) {
      if (!r.selecteurs.some((x) => x.includes('data-colonne-page'))) continue;
      for (const [p] of declarations(r.corps)) {
        expect(['transform', 'translate', 'scale', 'rotate', 'will-change', 'perspective', 'filter'], `${r.f} : « ${r.selecteurs.join(', ')} » pose ${p}`).not.toContain(p);
      }
    }
    const layout = sansCommentaires(lire('components/Layout.tsx'));
    const colonne = layout.slice(layout.lastIndexOf('<div', layout.indexOf('data-colonne-page=""')), layout.indexOf('>', layout.indexOf('data-colonne-page=""') + 200));
    expect(colonne, 'aucune classe de transform sur la colonne').not.toMatch(/\b(transform|translate-|scale-|rotate-|will-change)/);
  });

  it('dans la roue et le recul, seuls transform, opacity et visibility s’animent (mutants D1, D2)', () => {
    const roueCss = regles(sansCommentaires(lire('features/roue/roue.css')));
    const mobiles = regles(sansCommentaires(lire('index.css'))).filter((r) => r.selecteurs.some((x) => x.startsWith(MOBILE)));
    let vues = 0;
    for (const r of [...roueCss, ...mobiles]) {
      for (const [p, v] of declarations(r.corps)) {
        if (!['transition', 'transition-property', 'will-change'].includes(p)) continue;
        vues += 1;
        const proprietes = v.split(',').map((x) => x.trim().split(/\s+/)[0]);
        for (const q of proprietes) {
          expect(['transform', 'opacity', 'visibility', 'none'], `« ${r.selecteurs.join(', ')} » anime ${q}`).toContain(q);
        }
      }
    }
    expect(vues, 'les transitions de la roue sont trouvées').toBeGreaterThanOrEqual(6);
  });

  it('« Supprimer les animations » : tout ce qui transite dans la roue y reçoit transition: none (mutant C)', () => {
    const r = regles(sansCommentaires(lire('features/roue/roue.css')));
    const reduit = /prefers-reduced-motion:\s*reduce/;
    const animes = r
      .filter((x) => !x.media || !reduit.test(x.media))
      .filter((x) => declarations(x.corps).some(([p, v]) => p === 'transition' && v !== 'none'))
      .flatMap((x) => x.selecteurs);
    const coupes = new Set(
      r
        .filter((x) => x.media && reduit.test(x.media))
        .filter((x) => declarations(x.corps).some(([p, v]) => p === 'transition' && v === 'none'))
        .flatMap((x) => x.selecteurs),
    );
    expect(animes.length, 'les transitions sont trouvées').toBeGreaterThanOrEqual(5);
    for (const sel of animes) expect(coupes.has(sel), `« ${sel} » bouge encore sous « Supprimer les animations »`).toBe(true);
  });

  it('une capsule de la roue n’est jamais translucide : aucune opacité posée en dur (mutant J2)', () => {
    // Le composant écrit l'opacité de la PLACE (sa présence) et celle du nom ;
    // la capsule reste opaque tant qu'elle se touche. La place naît à 0,
    // avant la première mesure.
    for (const regle of regles(sansCommentaires(lire('features/roue/roue.css')))) {
      for (const sel of regle.selecteurs) {
        const opacite = declarations(regle.corps).find(([p]) => p === 'opacity')?.[1];
        if (opacite === undefined) continue;
        if (/\.roue-element(?!::before)(\[[^\]]*\])?$/.test(sel) || /\.roue-element\s*$/.test(sel)) {
          throw new Error(`« ${sel} » pose opacity: ${opacite} sur la capsule`);
        }
        if (/\.roue-place$/.test(sel)) expect(opacite, 'la place naît invisible, rien d’autre').toBe('0');
      }
    }
  });
});

describe('pageParesseuse.tsx', () => {
  it('rend au montage le module déjà arrivé', () => {
    const page = sansCommentaires(lire('lib/pageParesseuse.tsx'));
    expect(page).toMatch(/useState\(\(\) => composantInitial<[^>]+>>\(memo, Paresseuse\)\)/);
  });
});
