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
/** Le début du rendu hors mini-panneau (le téléphone et le bureau). */
const RETOUR_TELEPHONE_ET_BUREAU = '  return (\n    <div className="h-full w-full overflow-hidden mobile:overflow-visible relative">';
const lire = (chemin: string) => readFileSync(join(__dirname, chemin), 'utf8');
const sansCommentaires = (code: string) =>
  code.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');

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

  it('au téléphone, le défileur de la page est le bloc contenant de ses absolus', () => {
    // 27/09/2026, contre-épreuve : le libellé sr-only de « Roue à gauche »
    // (Réglages) avait la colonne pour bloc contenant, échappait au défileur
    // et rendait le DOCUMENT défilable de 117 px — la cloche et le voyant
    // partaient avec lui. Le banc mesure le document sur les 17 pages et les
    // 7 apparences ; ce test tient la règle qui l'empêche.
    expect(css).toContain(`${MOBILE} [data-colonne-page] > .overflow-y-auto {\n  position: relative;\n}`);
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

describe('RoueNavigation.tsx — le câblage (contre-épreuve « soyeux », 27/09/2026)', () => {
  // 27/09/2026, contre-épreuve : l'APPEL des fonctions pures de la roue
  // n'était tenu par aucun test.
  const roue = sansCommentaires(lire('features/roue/RoueNavigation.tsx'));

  it('l’opacité lisible se mesure sur une capsule NON allumée, et la géométrie la borne (mutants J1, O4)', () => {
    expect(roue).toContain('const temoin = elementsRef.current.find((el, i) => el && i !== allumeRef.current);');
    expect(roue).toMatch(/geometrieRoue\(\{ largeur: r\.width, hauteur: r\.height, cote, haut: 0, bas: r\.height - 68, opaciteLisible \}\)/);
    const geo = sansCommentaires(lire('features/roue/geometrieRoue.ts'));
    expect(geo, 'la mesure passe par la borne').toContain('opaciteLisible: opaciteLisibleBornee(entree.opaciteLisible),');
  });
});

describe('pageParesseuse.tsx', () => {
  it('rend au montage le module déjà arrivé', () => {
    const page = sansCommentaires(lire('lib/pageParesseuse.tsx'));
    expect(page).toMatch(/useState\(\(\) => composantInitial<[^>]+>>\(memo, Paresseuse\)\)/);
  });
});
