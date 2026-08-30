import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Code,
  Eraser,
  Heading1,
  Heading2,
  Heading3,
  Highlighter,
  Italic,
  List,
  Link2,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  Scissors,
  Strikethrough,
  Table,
  Underline,
  Undo2,
} from 'lucide-react';

import {
  NOTE_DOC_LANGS,
  NOTE_FONTS,
  NOTE_FONT_SIZES,
  pointsDepuisPx,
  styleDeTaille,
  tailleAffichee,
  NOTE_PAGE_BACKGROUNDS,
  NOTE_PAGE_MARGINS,
  NOTE_PAGE_ORIENTATIONS,
  NOTE_PAGE_SIZES,
  boitePage,
  miseEnPageDeLaNote,
  noteFontCss,
} from './noteFormats';
import {
  OVERFLOW_GAP_CLASS,
  PAGE_BREAK_CLASS,
  PAGE_BREAK_HTML,
  PAGE_GUTTER_PX,
  cssLengthToPx,
  overflowGapHeight,
  overflowGapPlan,
  type OverflowGap,
  type PageBlock,
} from './notePages';
import { sanitizeNoteHtml } from './noteSanitize';
import { fitZoom } from './noteZoom';
import { PanneauNavigation } from './PanneauNavigation';
import type {
  SuccesNoteDocLang,
  SuccesNotePageBackground,
  SuccesNotePageFormat,
  SuccesNotePageMargins,
  SuccesNotePageOrientation,
  SuccesNotePageSize,
} from './types';

type Props = {
  content: string;
  pageFormat: SuccesNotePageFormat;
  pageSize?: SuccesNotePageSize;
  pageOrientation?: SuccesNotePageOrientation;
  pageMargins?: SuccesNotePageMargins;
  pageBackground: SuccesNotePageBackground;
  fontFamily: string;
  docLang: SuccesNoteDocLang;
  color: string;
  onContentChange: (html: string) => void;
  onMetaChange: (patch: {
    pageFormat?: SuccesNotePageFormat;
    pageSize?: SuccesNotePageSize;
    pageOrientation?: SuccesNotePageOrientation;
    pageMargins?: SuccesNotePageMargins;
    pageBackground?: SuccesNotePageBackground;
    fontFamily?: string;
    docLang?: SuccesNoteDocLang;
    color?: string;
  }) => void;
  editorKey: string;
  /**
   * Le nombre RÉEL de feuilles dessinées, remonté après chaque pagination.
   *
   * Le pied de page affichait jusqu'ici une estimation par volume de texte,
   * juste sous un éditeur qui, lui, mesure : « 20 pages » sous 43 feuilles,
   * relevé sur une vraie note. Seul l'éditeur sait combien il en a dessiné.
   */
  onPageCount?: (feuilles: number) => void;
  /**
   * Le zoom voulu, ou `null` pour « Largeur de page ».
   *
   * Il vit dans la BARRE D'ÉTAT, en bas à droite, comme la réglette de Word —
   * et non dans la barre d'outils du haut, où Carlito ne l'attendait pas.
   */
  zoom?: number | null;
  /** Le zoom RÉELLEMENT appliqué, pour que la réglette affiche le vrai chiffre. */
  onZoomEffectif?: (zoom: number) => void;
  /** La page actuellement sous les yeux, mise à jour au défilement. */
  onPageCourante?: (page: number) => void;
  /** Le volet de navigation — pages en miniature et plan des titres. */
  navigation?: boolean;
  onFermerNavigation?: () => void;
  /** La page marquée, où la lecture s'était arrêtée. 0 : aucune. */
  marqueur?: number;
  /**
   * Sauter à une page. Le JETON change à chaque demande, y compris pour la
   * même page : sans lui, redemander deux fois « page 12 » ne ferait rien la
   * seconde fois, puisque la valeur n'aurait pas changé.
   */
  saut?: { page: number; jeton: number } | null;
};

function runCommand(command: string, value?: string) {
  document.execCommand(command, false, value);
}

function makeOverflowGap(
  gap: OverflowGap,
  gutter: number,
  margin: number,
  before: HTMLElement,
): HTMLElement {
  const inner = document.createElement('div');
  inner.className = 'succes-overflow-gap-inner';
  inner.style.height = `${overflowGapHeight(gap, gutter, margin)}px`;
  const estLigne = before.tagName === 'TR';
  if (gap.mode === 'sheet' && !estLigne) {
    const band = document.createElement('div');
    band.className = 'succes-overflow-gutter';
    band.style.marginTop = `${gap.fill + margin}px`;
    inner.appendChild(band);
  }
  if (estLigne) {
    const row = document.createElement('tr');
    row.className = OVERFLOW_GAP_CLASS;
    row.contentEditable = 'false';
    row.setAttribute('aria-hidden', 'true');
    const cell = document.createElement('td');
    cell.colSpan = 50;
    cell.appendChild(inner);
    row.appendChild(cell);
    // La bande d'une cale de TABLEAU se pose sur la FEUILLE, comme celle
    // d'une ligne fractionnée.
    //
    // Dans la cellule, sa largeur vaut `100% + marges` où 100 % désigne le
    // TABLEAU, pas la page — et un tableau collé depuis Word porte souvent
    // son propre `margin-left`. Mesuré ici : 815 px de bande pour 816 px de
    // feuille, mais décalés de 9 px, ce qui laisse une lisière de papier
    // visible à gauche de la séparation. En absolu sur la feuille, la bande
    // couvre la boîte de remplissage — c'est-à-dire la feuille entière —
    // sans arithmétique.
    if (gap.mode === 'sheet') {
      bandeSurLaFeuille(
        inner,
        before.closest('.succes-note-page'),
        `gap-${Date.now().toString(36)}-r${gap.beforeIndex}`,
        gap.fill + margin,
      );
    }
    return row;
  }
  const wrap = document.createElement('div');
  wrap.className = OVERFLOW_GAP_CLASS;
  wrap.contentEditable = 'false';
  wrap.setAttribute('aria-hidden', 'true');
  wrap.appendChild(inner);
  return wrap;
}

/**
 * Le haut de chaque ligne d'un bloc, dans le repère de l'éditeur.
 *
 * `Range.getClientRects()` rend un rectangle par ligne d'un contenu en ligne.
 * Deux fragments d'une même ligne (un mot en gras, un lien) partagent leur
 * `top` : on les fusionne à un demi-interligne près, sinon chaque mot mis en
 * forme compterait pour une ligne et la coupe tomberait n'importe où.
 */
function lignesDuBloc(el: HTMLElement, editorTop: number, zoom: number): number[] {
  const range = document.createRange();
  range.selectNodeContents(el);
  // TRIER avant de fusionner.
  //
  // `getClientRects` rend les rectangles dans l'ordre du DOCUMENT, pas dans
  // l'ordre visuel. Pour une LIGNE DE TABLEAU, cela veut dire : toutes les
  // lignes de la première cellule, puis toutes celles de la deuxième, qui
  // repartent du haut. Sans tri, la fusion « garder ce qui descend » rejetait
  // en bloc la deuxième colonne — la ligne se croyait donc plus courte
  // qu'elle n'est, et la coupe ne couvrait pas toute sa hauteur.
  //
  // Constaté le 30 août 2026 sur une ligne de 1 964 px : 71 lignes mesurées
  // ne s'étalaient que sur 1 729 px, et une seule coupure était posée là où
  // il en fallait deux.
  const bruts: Array<{ top: number; hauteur: number }> = [];
  for (const rect of Array.from(range.getClientRects())) {
    if (rect.height <= 0) continue;
    // Ces rectangles sont en pixels ÉCRAN : `transform: scale()` les réduit.
    // Les hauteurs de bloc, elles, viennent de `offsetTop`/`offsetHeight`,
    // des unités de LAYOUT que le zoom ne touche pas. Mélanger les deux
    // ferait bouger la pagination à chaque redimensionnement de fenêtre.
    bruts.push({ top: (rect.top - editorTop) / zoom, hauteur: rect.height / zoom });
  }
  bruts.sort((a, b) => a.top - b.top);
  const tops: number[] = [];
  for (const r of bruts) {
    // Deux fragments d'une même ligne — un mot en gras, deux colonnes côte à
    // côte — partagent leur haut : on les fusionne à un demi-interligne près.
    if (tops.length === 0 || r.top - tops[tops.length - 1] > r.hauteur / 2) {
      tops.push(r.top);
    }
  }
  return tops;
}

/**
 * Le premier caractère dont le rendu commence à la hauteur `y`.
 *
 * Recherche binaire sur les nœuds texte, avec un `Range` d'un seul caractère :
 * O(log n) rectangles par coupe, contre O(n) pour un balayage.
 */
function positionDeLigne(
  el: HTMLElement,
  y: number,
  editorTop: number,
): { node: Text; offset: number } | null {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let node = walker.nextNode() as Text | null;
  while (node) {
    const len = node.data.length;
    if (len > 0) {
      range.setStart(node, len - 1);
      range.setEnd(node, len);
      if (range.getBoundingClientRect().top - editorTop >= y - 1) {
        let bas = 0;
        let haut = len - 1;
        let trouve = -1;
        while (bas <= haut) {
          const milieu = (bas + haut) >> 1;
          range.setStart(node, milieu);
          range.setEnd(node, milieu + 1);
          if (range.getBoundingClientRect().top - editorTop >= y - 1) {
            trouve = milieu;
            haut = milieu - 1;
          } else {
            bas = milieu + 1;
          }
        }
        if (trouve >= 0) return { node, offset: trouve };
      }
    }
    node = walker.nextNode() as Text | null;
  }
  return null;
}

/**
 * Fractionner une LIGNE de tableau à la hauteur `y`.
 *
 * Une ligne n'est pas un bloc : c'est plusieurs cellules côte à côte. La
 * couper veut dire poser la même cale dans CHACUNE, à la même hauteur —
 * sinon les colonnes se désalignent et le tableau se disloque.
 *
 * Une cellule dont le contenu s'arrête avant la coupure reçoit la cale en
 * fin : elle doit descendre comme les autres, sans quoi sa bordure s'arrête
 * au milieu de la page.
 *
 * La bande grise ne peut pas vivre dans une cellule : `width: 100%` y
 * désigne la cellule, pas la feuille. Elle est donc posée en absolu sur la
 * feuille, au-dessus des bordures — ce qu'un saut de page fait dans Word.
 */
function couperLaLigne(
  ligne: HTMLElement,
  y: number,
  editorTop: number,
  hauteur: number,
  fill: number,
  margin: number,
  zoom: number,
): void {
  const cellules = Array.from(ligne.children) as HTMLElement[];
  if (cellules.length === 0) return;
  for (const cellule of cellules) {
    const cale = document.createElement('div');
    cale.className = OVERFLOW_GAP_CLASS;
    cale.contentEditable = 'false';
    cale.setAttribute('aria-hidden', 'true');
    cale.style.cssText = `height:${hauteur}px;width:100%;user-select:none`;
    const point = positionDeLigne(cellule, y, editorTop);
    if (point) {
      const plage = document.createRange();
      plage.setStart(point.node, point.offset);
      plage.collapse(true);
      plage.insertNode(cale);
    } else {
      cellule.appendChild(cale);
    }
  }
  // La bande, une seule, par-dessus le tableau — POSITIONNÉE PLUS TARD.
  //
  // Les cales sont posées de bas en haut : au moment où celle-ci est créée,
  // celles qui la surplombent n'existent pas encore et la pousseront ensuite.
  // Une bande en position absolue, elle, ne suit pas. Mesuré : posée à
  // 45 131 px alors que sa cale finissait à 58 650 — un grand vide au milieu
  // d'un bloc, sans la moindre séparation pour l'expliquer.
  //
  // On note donc seulement À QUI elle appartient ; `placerLesBandesFlottantes`
  // fait le calcul une fois que plus rien ne bouge.
  const premiere = cellules[0].querySelector<HTMLElement>(`.${OVERFLOW_GAP_CLASS}`);
  if (!premiere) return;
  bandeSurLaFeuille(
    premiere,
    ligne.closest('.succes-note-page'),
    `gap-${Date.now().toString(36)}-${Math.round(y)}`,
    fill + margin,
  );
}

/**
 * Rattacher une bande de séparation à la FEUILLE plutôt qu'à la cale.
 *
 * Une bande vit à l'intérieur du bloc qu'elle coupe, et sa largeur y vaut
 * `100 % + marges` — où 100 % désigne CE BLOC. Pour un bloc pleine largeur
 * cela tombe juste ; pour un tableau qui porte son propre `margin-left`, ou
 * pour un paragraphe indenté, cela ne tombe plus. Mesuré le 30 août 2026 sur
 * « Guide/Programmation » : 8 bandes sur 54 mesuraient 608 px pour une feuille
 * de 636, décalées de 28 — une lisière de papier restait visible à gauche de
 * la séparation, et la cale de tableau, elle, tombait à 192 px sur 816.
 *
 * Posée en absolu sur la feuille, la bande couvre la boîte de remplissage,
 * c'est-à-dire la feuille entière, sans aucune arithmétique de marges.
 * La position verticale, elle, ne peut pas être calculée ici : les cales sont
 * posées de bas en haut, et celles qui surplombent celle-ci n'existent pas
 * encore. `placerLesBandesFlottantes` s'en charge quand plus rien ne bouge.
 */
function bandeSurLaFeuille(
  cale: HTMLElement,
  feuille: HTMLElement | null,
  cle: string,
  decalage: number,
): void {
  if (!feuille) return;
  cale.setAttribute('data-bande', cle);
  const bande = document.createElement('div');
  bande.className = `${OVERFLOW_GAP_CLASS} succes-overflow-gutter-flottant`;
  bande.contentEditable = 'false';
  bande.setAttribute('aria-hidden', 'true');
  bande.setAttribute('data-pour', cle);
  bande.setAttribute('data-decalage', String(decalage));
  bande.style.cssText = 'position:absolute;left:0;right:0;top:-9999px';
  feuille.appendChild(bande);
}

/** Poser les bandes des lignes fractionnées, une fois toutes les cales en place. */
function placerLesBandesFlottantes(page: HTMLElement, zoom: number): void {
  const hautPage = page.getBoundingClientRect().top;
  for (const bande of Array.from(
    page.querySelectorAll<HTMLElement>(':scope > .succes-overflow-gutter-flottant'),
  )) {
    const cle = bande.getAttribute('data-pour');
    const cale = cle
      ? page.querySelector<HTMLElement>(`[data-bande="${cle}"]`)
      : null;
    if (!cale) {
      bande.remove();
      continue;
    }
    const decalage = Number(bande.getAttribute('data-decalage')) || 0;
    // Écran → layout : `top` en CSS ne connaît pas le zoom.
    const haut = (cale.getBoundingClientRect().top - hautPage) / zoom;
    bande.style.top = `${Math.round(haut + decalage)}px`;
  }
}

/** La cale posée DANS un paragraphe, entre deux de ses lignes. */
function makeInlineGap(
  hauteur: number,
  fill: number,
  margin: number,
  feuille: HTMLElement | null,
  cle: string,
): HTMLElement {
  const cale = document.createElement('span');
  cale.className = OVERFLOW_GAP_CLASS;
  cale.contentEditable = 'false';
  cale.setAttribute('aria-hidden', 'true');
  // `width: 100%` force le retour à la ligne : la queue du paragraphe passe
  // sous la cale sans que le paragraphe soit scindé. Alignement, justification
  // et numérotation de liste survivent, ce qu'une scission en deux <p> aurait
  // perdu.
  cale.style.cssText = [
    'display:inline-block',
    'width:100%',
    `height:${hauteur}px`,
    'vertical-align:top',
    'position:relative',
    'user-select:none',
  ].join(';');
  bandeSurLaFeuille(cale, feuille, cle, fill + margin);
  return cale;
}

function collectBlockNodes(editor: HTMLElement): HTMLElement[] {
  const nodes: HTMLElement[] = [];
  for (const child of Array.from(editor.children) as HTMLElement[]) {
    if (child.classList.contains(OVERFLOW_GAP_CLASS)) continue;
    // Une liste ou une citation est un CONTENEUR, pas un bloc. Une <ul> de
    // quarante puces mesurait 990 px d'un seul tenant : plus haute qu'une
    // page, elle tombait dans le trou du « bloc géant » et traversait le
    // bureau sans une seule coupe.
    if (child.tagName === 'UL' || child.tagName === 'OL') {
      for (const li of Array.from(child.children) as HTMLElement[]) {
        if (!li.classList.contains(OVERFLOW_GAP_CLASS)) nodes.push(li);
      }
      continue;
    }
    if (child.tagName === 'BLOCKQUOTE') {
      const enfants = Array.from(child.children) as HTMLElement[];
      for (const bloc of enfants) {
        if (!bloc.classList.contains(OVERFLOW_GAP_CLASS)) nodes.push(bloc);
      }
      if (enfants.length === 0) nodes.push(child);
      continue;
    }
    if (child.tagName === 'TABLE') {
      const rows = child.querySelectorAll(
        ':scope > tr, :scope > tbody > tr, :scope > thead > tr, :scope > tfoot > tr',
      );
      for (const row of Array.from(rows) as HTMLElement[]) {
        if (!row.classList.contains(OVERFLOW_GAP_CLASS)) nodes.push(row);
      }
      continue;
    }
    nodes.push(child);
  }
  return nodes;
}

function measuredBlocks(
  editor: HTMLElement,
  zoom: number,
): Array<PageBlock & { el: HTMLElement }> {
  const editorTop = editor.getBoundingClientRect().top;
  return collectBlockNodes(editor).map((el) => {
    const kind: PageBlock['kind'] =
      el.tagName === 'HR' && el.classList.contains(PAGE_BREAK_CLASS)
        ? 'break'
        : /^H[1-6]$/.test(el.tagName)
          ? 'heading'
          : 'block';
    // Une ligne de tableau SE COUPE, comme dans Word : « Autoriser le
    // fractionnement des lignes sur plusieurs pages » y est coché par défaut.
    // Le refuser faisait partir une ligne haute d'un seul tenant et perdait
    // le reste de la page précédente — parfois presque une feuille blanche.
    // Un titre, lui, ne se coupe jamais, et une image ne se coupe pas non
    // plus : on ne fractionne pas ce qui n'a pas de lignes.
    const coupable =
      (kind === 'block' || el.tagName === 'TR') && el.tagName !== 'IMG';
    const top = offsetDepuis(el, editor);
    return {
      el,
      top,
      height: Math.max(el.offsetHeight, 1),
      kind,
      lines: coupable ? lignesDuBloc(el, editorTop, zoom) : undefined,
    };
  });
}

/**
 * Le haut d'un élément dans le repère de l'ÉDITEUR.
 *
 * `offsetTop` est relatif à `offsetParent`. Une puce vit dans un `<ul>`, une
 * ligne dans un `<table>` : il faut remonter la chaîne et additionner. Mais
 * `.succes-note-editor` porte `position: relative`, il EST donc
 * l'`offsetParent` de ses enfants directs — leur `offsetTop` est déjà dans
 * son repère, et il ne faut rien lui retrancher.
 *
 * La première version retranchait `editor.offsetTop` — 96 px, la marge haute
 * de la feuille — à des positions déjà relatives à l'éditeur. Tous les blocs
 * se croyaient 96 px plus haut, chaque page avalait donc 96 px de contenu de
 * trop, et l'erreur se répétait page après page : mesuré sur une note réelle,
 * 44 pages sur 47 trop pleines, jusqu'à 156 px de dépassement, et une
 * distance entre deux bandes de 1192 à 1307 px là où une feuille en fait
 * 1151. Une feuille dont la hauteur varie n'est plus une feuille.
 */
function offsetDepuis(el: HTMLElement, editor: HTMLElement): number {
  let total = 0;
  let noeud: HTMLElement | null = el;
  while (noeud && noeud !== editor) {
    total += noeud.offsetTop;
    const parent = noeud.offsetParent as HTMLElement | null;
    if (!parent || parent === editor || !editor.contains(parent)) return total;
    noeud = parent;
  }
  return total;
}

/** Combien de feuilles la pose de cales vient de dessiner. */
function applyOverflowGaps(
  editor: HTMLElement,
  page: HTMLElement,
  zoom: number,
): number {
  const style = getComputedStyle(page);
  const pageHeight = cssLengthToPx(
    style.getPropertyValue('--note-page-height'),
    page.offsetHeight || 1,
  );
  // Les marges ne sont plus symétriques : « Modérées » vaut 2,54 cm en haut et
  // en bas, 1,91 cm sur les côtés. La pagination ne s'intéresse qu'aux marges
  // VERTICALES — ce sont elles qui bornent la hauteur utile.
  const margeHaut = cssLengthToPx(style.getPropertyValue('--note-m-t'), 96);
  const margeBas = cssLengthToPx(style.getPropertyValue('--note-m-b'), 96);
  const margin = margeBas;
  const contentHeight = pageHeight - margeHaut - margeBas;
  if (contentHeight < 80) return 1;
  editor.querySelectorAll(`.${OVERFLOW_GAP_CLASS}`).forEach((node) => node.remove());
  // Les bandes des lignes fractionnées vivent sur la FEUILLE, pas dans
  // l'éditeur : sans cette ligne, chaque pagination en empilerait une de plus.
  page
    .querySelectorAll(`:scope > .${OVERFLOW_GAP_CLASS}`)
    .forEach((node) => node.remove());
  const collected = measuredBlocks(editor, zoom);
  // `lines` DOIT traverser : sans lui, `peutSeCouper` rend toujours faux et
  // l'on retombe sur « déplacer des blocs entiers », c'est-à-dire le défaut
  // qu'on vient de corriger. Ce champ a été oublié ici une première fois, et
  // la coupe interne n'a alors jamais eu lieu — zéro cale interne mesurée sur
  // une note de vingt pages.
  const plan = overflowGapPlan(
    collected.map(({ top, height, kind, lines }) => ({ top, height, kind, lines })),
    contentHeight,
    PAGE_GUTTER_PX,
    margin,
  );
  for (const gap of [...plan].reverse()) {
    const bloc = collected[gap.beforeIndex];
    const target = bloc?.el;
    if (!target?.parentNode) continue;
    const hauteur = overflowGapHeight(gap, PAGE_GUTTER_PX, margin);
    if (gap.atLine === undefined) {
      target.parentNode.insertBefore(
        makeOverflowGap(gap, PAGE_GUTTER_PX, margin, target),
        target,
      );
      continue;
    }
    // Coupe INTERNE : on va chercher le premier caractère de la ligne visée.
    const y = bloc.lines?.[gap.atLine];
    if (y === undefined) continue;
    // Une LIGNE de tableau se coupe dans toutes ses cellules à la fois.
    if (target.tagName === 'TR') {
      couperLaLigne(
        target,
        y * zoom,
        editor.getBoundingClientRect().top,
        hauteur,
        gap.fill,
        margin,
        zoom,
      );
      continue;
    }
    // `y` est en unités de layout ; `positionDeLigne` compare des rectangles
    // d'écran. Le zoom fait le pont entre les deux.
    const point = positionDeLigne(target, y * zoom, editor.getBoundingClientRect().top);
    if (!point) continue;
    const range = document.createRange();
    range.setStart(point.node, point.offset);
    range.collapse(true);
    range.insertNode(
      makeInlineGap(
        hauteur,
        gap.fill,
        margin,
        target.closest('.succes-note-page'),
        `gap-${Date.now().toString(36)}-i${gap.beforeIndex}-${gap.atLine}`,
      ),
    );
  }
  // Les bandes des lignes fractionnées se posent MAINTENANT : toutes les
  // cales sont en place, donc plus rien ne les poussera.
  placerLesBandesFlottantes(page, zoom);

  // LA DERNIÈRE FEUILLE DOIT ÊTRE UNE FEUILLE.
  //
  // Sans cela elle s'arrête sur le dernier mot : la page finale est plus
  // courte que les autres, ce qui n'arrive jamais dans Word et se voit
  // immédiatement. On complète avec le papier qui reste.
  let queue = 0;
  {
    // La hauteur RÉELLE du contenu, queue remise à zéro : reconstituer la fin
    // à partir du dernier bloc rate sa marge basse — `offsetHeight` ne la
    // compte pas — et la dernière feuille restait courte de 65 px.
    page.style.setProperty('--note-tail', '0px');
    const finContenu = editor.offsetHeight;
    // La cale la plus BASSE, et non la dernière du DOM : une cale posée dans
    // une cellule de tableau a un `offsetTop` relatif à sa CELLULE, et arrive
    // après des cales situées plus bas dans la page. Prendre la dernière du
    // document donnait une origine trop haute, une queue négative, donc zéro —
    // et la dernière feuille retombait à 95 px au lieu de 931.
    let debutDerniere = 0;
    for (const cale of Array.from(
      editor.querySelectorAll<HTMLElement>(`.${OVERFLOW_GAP_CLASS}`),
    )) {
      const bas = offsetDepuis(cale, editor) + cale.offsetHeight;
      if (bas > debutDerniere) debutDerniere = bas;
    }
    queue = Math.max(0, contentHeight - (finContenu - debutDerniere));
  }
  page.style.setProperty('--note-tail', `${Math.round(queue)}px`);


  // Chaque cale est une frontière de page ; il y a toujours une feuille de
  // plus que de frontières.
  return plan.length + 1;
}

export function RichNoteEditor({
  content,
  pageFormat,
  pageSize,
  pageOrientation,
  pageMargins,
  pageBackground,
  fontFamily,
  docLang,
  color,
  onContentChange,
  onMetaChange,
  onPageCount,
  zoom: zoomVoulu = null,
  onZoomEffectif,
  onPageCourante,
  navigation = false,
  onFermerNavigation,
  marqueur = 0,
  saut = null,
  editorKey,
}: Props) {
  // Une note enregistrée avant le 30 août 2026 ne porte que `pageFormat` : il
  // se décompose en trois axes à la lecture, et les trois champs neufs gagnent
  // dès qu'ils existent.
  const mise = miseEnPageDeLaNote({
    pageFormat,
    pageSize,
    pageOrientation,
    pageMargins,
  });

  const editorRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const deskRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const applyingGaps = useRef(false);
  const suppressObserverUntil = useRef(0);
  // L'encre du papier courant, et non une constante : #1A2232 est exactement
  // la couleur du papier du fond Sombre — contraste 1,00 sur 1.
  const [encreCourante, setEncreCourante] = useState('#1a2232');
  // Change à chaque pagination : c'est le signal qui fait relire le document
  // au volet de navigation, sans qu'il ait à observer le DOM lui-même.
  const [signaturePagination, setSignaturePagination] = useState(0);
  const [pageAffichee, setPageAffichee] = useState(1);
  const zoomRef = useRef(1);

  // ─── La sélection, que les contrôles de la barre faisaient perdre ────────
  //
  // Un <select> et un <input type=color> prennent NÉCESSAIREMENT le focus au
  // clic. `onBlur={emitContent}` tirait donc avant la commande, et
  // `emitContent` repagine, ce qui mute le DOM sous la sélection. Résultat :
  // la taille ou la couleur choisie n'était jamais appliquée, et n'était
  // jamais enregistrée tant qu'on ne retapait pas — §100.
  //
  // `preventDefault` sur le `mousedown` empêche le vol de focus, et la plage
  // est sauvegardée avant d'ouvrir le contrôle, restaurée avant la commande.
  const selectionGardee = useRef<Range | null>(null);

  const garderLaSelection = (event: React.MouseEvent) => {
    const selection = window.getSelection();
    const editor = editorRef.current;
    if (selection && selection.rangeCount > 0 && editor) {
      const plage = selection.getRangeAt(0);
      if (editor.contains(plage.commonAncestorContainer)) {
        selectionGardee.current = plage.cloneRange();
      }
    }
    // Sur un <select>, empêcher le défaut empêcherait aussi le menu de
    // s'ouvrir : on ne le fait que pour les boutons et les pastilles.
    if (event.currentTarget.tagName !== 'SELECT') event.preventDefault();
  };

  const rendreLaSelection = () => {
    const plage = selectionGardee.current;
    const selection = window.getSelection();
    if (!plage || !selection) return;
    selection.removeAllRanges();
    selection.addRange(plage);
  };

  /**
   * Envelopper la sélection dans un <span> portant `declaration`.
   *
   * On passe par `execCommand('fontSize', '7')` pour poser des balises
   * repères, puis on les convertit. C'est le seul moyen fiable d'envelopper
   * une sélection qui TRAVERSE plusieurs éléments : `Range.surroundContents`
   * lève sur une sélection partielle, et un découpage maison réimplémenterait
   * ce que le navigateur sait déjà faire.
   */
  /**
   * La déclaration à poser sur ce qui sera tapé ENSUITE.
   *
   * `execCommand('fontSize')` sur un curseur vide ne change rien tout de
   * suite : WebKit retient un « style de frappe » et l'applique au premier
   * caractère tapé, sous la forme d'un <font size="7">. Vérifié sur un banc
   * jetable : « avant » + curseur + fontSize(7) + frappe rend
   * `avant<font size="7">APRES</font>`. C'est ce marqueur que l'on convertit,
   * au moment où il apparaît.
   *
   * Rien ne purge cette attente, et c'est délibéré : WebKit OUBLIE son style
   * de frappe dès que le curseur bouge. Vérifié sur le même banc — armer la
   * taille dans un paragraphe, poser le curseur dans un autre, taper : zéro
   * marque produite. Le marqueur ne peut donc pas apparaître ailleurs, et une
   * purge sur `selectionchange` s'effacerait elle-même juste après l'armement,
   * `execCommand` déclenchant l'événement.
   */
  const styleEnAttente = useRef<string | null>(null);

  /** Remplacer les marques <font size="7"> par la déclaration voulue. */
  const convertirLesMarques = (editor: HTMLElement, declaration: string) => {
    let vues = 0;
    for (const marque of Array.from(editor.querySelectorAll('font[size="7"]'))) {
      const span = document.createElement('span');
      span.setAttribute('style', declaration);
      while (marque.firstChild) span.appendChild(marque.firstChild);
      marque.replaceWith(span);
      vues += 1;
    }
    return vues;
  };

  const appliquerStyle = (declaration: string) => {
    rendreLaSelection();
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection) return;
    // CURSEUR VIDE : Word applique la taille à ce qu'on va TAPER. Ici, la
    // liste ne faisait rien du tout — il fallait d'abord écrire, puis
    // sélectionner, puis choisir. On retient la déclaration et on la pose au
    // premier caractère.
    if (selection.isCollapsed) {
      if (!editor.contains(selection.getRangeAt(0).commonAncestorContainer)) return;
      document.execCommand('fontSize', false, '7');
      styleEnAttente.current = declaration;
      return;
    }
    document.execCommand('fontSize', false, '7');
    convertirLesMarques(editor, declaration);
    styleEnAttente.current = null;
    emitContent();
  };

  const paginationEnAttente = useRef<number | null>(null);

  /** Repaginer à la prochaine image, une seule fois pour toute une rafale. */
  const paginerBientot = () => {
    if (paginationEnAttente.current !== null) return;
    paginationEnAttente.current = requestAnimationFrame(() => {
      paginationEnAttente.current = null;
      paginate();
    });
  };

  useEffect(
    () => () => {
      if (paginationEnAttente.current !== null) {
        cancelAnimationFrame(paginationEnAttente.current);
      }
    },
    [],
  );

  /**
   * Où se trouve le caret, dans un repère qui survit à la pose des cales.
   *
   * Ni le nœud ni le décalage ne survivent : poser une cale insère un élément
   * DANS un paragraphe et scinde ses nœuds texte. On enregistre donc l'INDEX
   * du bloc de premier niveau et le rang du caractère dans le texte de ce
   * bloc — deux nombres, qui ne dépendent d'aucun nœud.
   *
   * Signalé par Carlito le 30 août 2026 : « si je change de format de page, le
   * curseur bogue, il reste entremêlé avec du texte ». Changer de format
   * repagine, donc retire et repose toutes les cales sous le caret.
   */
  const ouEstLeCaret = (editor: HTMLElement): { bloc: number; rang: number } | null => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;
    const plage = selection.getRangeAt(0);
    if (!editor.contains(plage.startContainer)) return null;
    const blocs = Array.from(editor.children).filter(
      (e) => !e.classList.contains(OVERFLOW_GAP_CLASS),
    );
    for (let i = 0; i < blocs.length; i++) {
      if (!blocs[i].contains(plage.startContainer)) continue;
      const avant = plage.cloneRange();
      avant.selectNodeContents(blocs[i]);
      avant.setEnd(plage.startContainer, plage.startOffset);
      return { bloc: i, rang: avant.toString().length };
    }
    return null;
  };

  const remettreLeCaret = (
    editor: HTMLElement,
    place: { bloc: number; rang: number } | null,
  ) => {
    if (!place) return;
    const blocs = Array.from(editor.children).filter(
      (e) => !e.classList.contains(OVERFLOW_GAP_CLASS),
    );
    const bloc = blocs[place.bloc];
    if (!bloc) return;
    const marcheur = document.createTreeWalker(bloc, NodeFilter.SHOW_TEXT);
    let reste = place.rang;
    let noeud = marcheur.nextNode() as Text | null;
    while (noeud) {
      // Le texte d'une cale ne compte pas : elle est vide, mais un futur
      // contenu décalerait le rang sans que personne ne s'en aperçoive.
      const dansUneCale = (noeud.parentElement as HTMLElement | null)?.closest(
        `.${OVERFLOW_GAP_CLASS}`,
      );
      if (!dansUneCale) {
        if (reste <= noeud.data.length) {
          const plage = document.createRange();
          plage.setStart(noeud, reste);
          plage.collapse(true);
          const selection = window.getSelection();
          selection?.removeAllRanges();
          selection?.addRange(plage);
          return;
        }
        reste -= noeud.data.length;
      }
      noeud = marcheur.nextNode() as Text | null;
    }
  };

  /**
   * Réserver dans le layout la hauteur RÉELLEMENT occupée par la feuille.
   *
   * `transform: scale()` ne change pas la boîte de layout : sans cette
   * hauteur écrite à la main, le bureau défilerait sur la hauteur NON mise à
   * l'échelle et laisserait un grand vide sous la dernière page. Mesuré :
   * 61 385 px réservés pour 39 878 réels.
   *
   * Appelée depuis les DEUX endroits qui la rendent fausse — la pagination,
   * qui change la hauteur, et le zoom, qui change le facteur. La première
   * version n'était appelée que par la pagination, et écrivait donc la
   * hauteur d'un zoom de 1 avant que le zoom ne soit calculé.
   */
  const reserverLaHauteur = () => {
    const frame = frameRef.current;
    const scale = pageRef.current?.parentElement;
    if (!frame || !scale) return;
    frame.style.height = `${scale.offsetHeight * zoomRef.current}px`;
  };

  /**
   * Chasser le caret des cales de pagination.
   *
   * Signalé par Carlito le 30 août 2026 : un curseur GÉANT, haut de plusieurs
   * centaines de pixels. Mesuré : `caretRangeFromPoint` au milieu d'une cale
   * de 526 px rend une position DONT L'HÔTE EST LA CALE. Le navigateur dessine
   * alors le caret à la hauteur du bloc qui l'accueille.
   *
   * `contenteditable="false"`, `user-select: none` et `pointer-events: none`
   * ne suffisent pas : ils empêchent de sélectionner le contenu de la cale,
   * pas d'y POSER un caret — la cale occupe une place réelle dans le flux, et
   * un clic dans ce vide y résout.
   *
   * On le déplace donc nous-mêmes, vers le dernier texte AVANT la cale — le
   * geste naturel étant de cliquer sous ce qu'on vient d'écrire — et à défaut
   * vers le premier texte après.
   */
  const chasserLeCaretDesCales = () => {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0) return;
    const plage = selection.getRangeAt(0);
    if (!plage.collapsed) return;
    const depart =
      plage.startContainer.nodeType === Node.TEXT_NODE
        ? plage.startContainer.parentElement
        : (plage.startContainer as HTMLElement);
    const cale = depart?.closest?.(`.${OVERFLOW_GAP_CLASS}`);
    if (!cale || !editor.contains(cale)) return;

    const marcheur = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    let avant: Text | null = null;
    let apres: Text | null = null;
    let noeud = marcheur.nextNode() as Text | null;
    while (noeud) {
      if (!noeud.parentElement?.closest(`.${OVERFLOW_GAP_CLASS}`)) {
        const position = cale.compareDocumentPosition(noeud);
        if (position & Node.DOCUMENT_POSITION_PRECEDING) avant = noeud;
        else if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
          apres = noeud;
          break;
        }
      }
      noeud = marcheur.nextNode() as Text | null;
    }
    const cible = avant ?? apres;
    if (!cible) return;
    const nouvelle = document.createRange();
    nouvelle.setStart(cible, avant ? cible.data.length : 0);
    nouvelle.collapse(true);
    selection.removeAllRanges();
    selection.addRange(nouvelle);
  };

  useEffect(() => {
    document.addEventListener('selectionchange', chasserLeCaretDesCales);
    return () =>
      document.removeEventListener('selectionchange', chasserLeCaretDesCales);
  }, []);

  /**
   * Quelle page est sous les yeux.
   *
   * Word l'affiche en permanence dans sa barre d'état — « Page 3 sur 47 » —
   * et c'est la seule façon de se situer dans un long document : le nombre
   * total, seul, ne dit pas où l'on est.
   *
   * On compte les cales entièrement passées au-dessus du tiers haut du
   * bureau. Le tiers, et non le bord : une feuille dont il reste un doigt en
   * haut de l'écran n'est plus celle qu'on lit.
   */
  const recalculerLaPage = () => {
    const desk = deskRef.current;
    const editor = editorRef.current;
    if (!desk || !editor) return;
    const repere = desk.getBoundingClientRect().top + desk.clientHeight / 3;
    let passees = 0;
    for (const cale of editor.querySelectorAll(`.${OVERFLOW_GAP_CLASS}`)) {
      if (cale.getBoundingClientRect().bottom <= repere) passees += 1;
    }
    setPageAffichee(passees + 1);
    onPageCourante?.(passees + 1);
    // Le signet suit le défilement, parce que c'est le seul moment où les
    // bornes sont sûres. Posé à la fin de la pagination, il tombait 2 676 px
    // trop bas : la police VT323 est une police WEB, et tant qu'elle n'est
    // pas chargée le document est plus long. La pagination qui suit son
    // arrivée ne repasse pas toujours par ici.
    poserLeSignet();
    placerLesNumerosDePage();
  };

  useEffect(() => {
    const desk = deskRef.current;
    if (!desk) return;
    let enAttente = false;
    const auDefilement = () => {
      // Une image par rafale : un `scroll` tire des dizaines de fois par
      // seconde, et compter cinquante cales à chaque fois ferait ramer la
      // molette sur un document de cinquante pages.
      if (enAttente) return;
      enAttente = true;
      requestAnimationFrame(() => {
        enAttente = false;
        recalculerLaPage();
      });
    };
    desk.addEventListener('scroll', auDefilement, { passive: true });
    recalculerLaPage();
    return () => desk.removeEventListener('scroll', auDefilement);
  }, [editorKey, onPageCourante]); // eslint-disable-line react-hooks/exhaustive-deps -- recalculerLaPage lit des refs

  const paginate = () => {
    const page = pageRef.current;
    const editor = editorRef.current;
    if (!page || !editor) return;
    // Le caret n'est remis que s'il était DANS l'éditeur : le replacer alors
    // qu'on tape ailleurs volerait le focus à un champ de la barre.
    const place = editor.contains(document.activeElement) ? ouEstLeCaret(editor) : null;
    applyingGaps.current = true;
    suppressObserverUntil.current = Date.now() + 150;
    try {
      const feuilles = applyOverflowGaps(editor, page, zoomRef.current);
      onPageCount?.(feuilles);
      setSignaturePagination((n) => n + 1);
      poserLeSignet();
      recalculerLaPage();
      reserverLaHauteur();
      remettreLeCaret(editor, place);
    } finally {
      applyingGaps.current = false;
    }
  };

  // Remonter le CONTENU : seulement au changement de note.
  //
  // Cet effet dépendait aussi du format et de la police, et il réaffecte
  // `editor.innerHTML`. Changer de police effaçait donc tout l'historique
  // d'annulation du navigateur — alors que ni le format ni la police
  // n'entrent dans le HTML : ils ne passent que par des variables CSS et un
  // attribut. Il n'y avait aucune raison de réécrire le document.
  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const sanitized = sanitizeNoteHtml(content);
    if (sanitizeNoteHtml(editor.innerHTML) !== sanitized) {
      editor.innerHTML = sanitized;
    }
    paginate();
  }, [editorKey]); // eslint-disable-line react-hooks/exhaustive-deps -- remount content on note switch

  // Repaginer quand la mise en page change — sans toucher au HTML.
  useLayoutEffect(() => {
    paginate();
  }, [pageFormat, pageSize, pageOrientation, pageMargins, fontFamily]); // eslint-disable-line react-hooks/exhaustive-deps -- la géométrie change, le document non

  // L'encre du papier courant. Sans cette lecture, la pastille de couleur
  // proposerait toujours #1A2232 — la couleur exacte du papier du fond
  // Sombre, soit un contraste de 1,00 sur 1 : du texte invisible, proposé par
  // défaut.
  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const couleur = getComputedStyle(page).color;
    const rgb = couleur.match(/\d+/g);
    if (!rgb || rgb.length < 3) return;
    const hex =
      '#' +
      rgb
        .slice(0, 3)
        .map((n) => Number(n).toString(16).padStart(2, '0'))
        .join('');
    setEncreCourante(hex);
  }, [pageBackground]);

  // `@page` n'accepte pas de propriété personnalisée : la taille et les marges
  // du papier doivent y être écrites en dur. On régénère donc une balise
  // <style> à chaque changement de mise en page, sans quoi l'aperçu
  // d'impression rendrait toujours du Lettre US (le défaut du navigateur) quel
  // que soit le format choisi à l'écran.
  useEffect(() => {
    const boite = boitePage(mise);
    const id = 'succes-note-print';
    let balise = document.getElementById(id) as HTMLStyleElement | null;
    if (!balise) {
      balise = document.createElement('style');
      balise.id = id;
      document.head.appendChild(balise);
    }
    balise.textContent =
      `@page { size: ${boite.w} ${boite.h};` +
      ` margin: ${boite.t} ${boite.r} ${boite.b} ${boite.l}; }`;
  }, [mise.size, mise.orientation, mise.margins]); // eslint-disable-line react-hooks/exhaustive-deps -- `mise` est reconstruit à chaque rendu

  // Mettre la feuille à l'échelle plutôt que la laisser se comprimer. La
  // largeur du papier se lit dans le CSS, donc les cinq formats et les deux
  // orientations sont couverts sans que ce code les connaisse.
  useLayoutEffect(() => {
    const desk = deskRef.current;
    const frame = frameRef.current;
    const page = pageRef.current;
    if (!desk || !frame || !page) return;

    const ajuster = () => {
      const papier = cssLengthToPx(
        getComputedStyle(page).getPropertyValue('--note-page-width'),
        793.7,
      );
      const zoom = zoomVoulu ?? fitZoom(desk.clientWidth, papier);
      if (Math.abs(zoom - zoomRef.current) < 0.001) return;
      zoomRef.current = zoom;
      frame.style.setProperty('--note-zoom', String(zoom));
      reserverLaHauteur();
      onZoomEffectif?.(zoom);
      // La pagination se mesure en unités de LAYOUT, que le zoom ne touche
      // pas : elle n'a donc pas à être refaite. Seuls les rectangles de ligne
      // en dépendent, et ils sont relus au prochain passage.
    };

    ajuster();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(ajuster);
    observer.observe(desk);
    return () => observer.disconnect();
  }, [zoomVoulu, pageFormat, pageSize, pageOrientation, pageMargins]); // eslint-disable-line react-hooks/exhaustive-deps -- onZoomEffectif est stable

  useEffect(() => {
    const page = pageRef.current;
    if (!page || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      // La hauteur réservée suit TOUJOURS, même quand on ne repagine pas :
      // c'est elle qui borne le défilement du bureau, et la laisser en retard
      // ajoute du vide sous la dernière page (mesuré : 1 250 px, soit une
      // page et quart).
      reserverLaHauteur();
      if (Date.now() < suppressObserverUntil.current) return;
      paginate();
    });
    observer.observe(page);
    return () => observer.disconnect();
  }, [editorKey, pageFormat, pageSize, pageOrientation, pageMargins]);

  /**
   * Publier le contenu, SANS repaginer dans la foulée.
   *
   * `paginate()` était appelé ici, donc à CHAQUE caractère frappé. Il fait des
   * `insertBefore` et des `remove` directement dans le DOM — et MDN est
   * explicite : `execCommand` préserve la pile d'annulation « contrairement à
   * la manipulation directe du DOM ». Les boutons Annuler et Rétablir
   * opéraient donc sur une pile détruite en permanence, et une cale insérée
   * devant le bloc du caret le déplaçait en pleine frappe.
   *
   * La pagination est désormais différée à la prochaine image : elle ne se
   * produit qu'une fois la rafale de frappe retombée.
   */
  const emitContent = () => {
    if (applyingGaps.current) return;
    const editor = editorRef.current;
    if (!editor) return;
    // Le premier caractère tapé après un choix de taille sur curseur vide
    // arrive marqué <font size="7"> : c'est ici qu'on lui donne sa taille.
    // Une seule fois — la marque consommée, l'attente s'éteint, sinon toute
    // la suite de la frappe hériterait d'une taille qu'on n'a plus demandée.
    if (styleEnAttente.current) {
      const posees = convertirLesMarques(editor, styleEnAttente.current);
      if (posees > 0) styleEnAttente.current = null;
    }
    onContentChange(sanitizeNoteHtml(editor.innerHTML));
    paginerBientot();
  };

  /**
   * Six outils manquaient pour des balises que le nettoyeur accepte DÉJÀ.
   *
   * `noteSanitize.ts` autorise `A`, `TABLE`, `BLOCKQUOTE`, `PRE`, `CODE`,
   * `S`/`STRIKE`/`DEL` — parce qu'un collage depuis une autre application en
   * produit. Mais la barre n'offrait aucun bouton pour les créer : on pouvait
   * les recevoir, jamais les écrire. §5, dans sa forme la plus littérale.
   */
  const insererUnLien = () => {
    rendreLaSelection();
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;
    const url = window.prompt('Adresse du lien');
    if (!url) return;
    // Refuser tout ce qui n'est pas http(s) : `javascript:` dans un
    // contenteditable est une exécution de script à un clic.
    if (!/^https?:\/\//i.test(url.trim())) {
      window.alert("Seules les adresses http:// et https:// sont acceptées.");
      return;
    }
    runCommand('createLink', url.trim());
    emitContent();
  };

  const insererUnTableau = () => {
    rendreLaSelection();
    const lignes = 3;
    const colonnes = 3;
    const cellule = '<td><br></td>'.repeat(colonnes);
    const corps = `<tr>${cellule}</tr>`.repeat(lignes);
    runCommand('insertHTML', `<table><tbody>${corps}</tbody></table><p><br></p>`);
    emitContent();
  };

  /** Forces a new page in the folder icon's sheet count. */
  const insertPageBreak = () => {
    editorRef.current?.focus();
    runCommand('insertHTML', PAGE_BREAK_HTML);
    emitContent();
  };

  /** Les bas de cale, dans l'ordre : la fin de chaque feuille. */
  const bornesDePage = () => {
    const editor = editorRef.current;
    if (!editor) return [] as number[];
    const haut = editor.getBoundingClientRect().top;
    const z = zoomRef.current || 1;
    // TOUTES les cales, pas seulement celles de premier niveau : une coupure
    // de page peut vivre DANS un paragraphe ou dans une ligne de tableau.
    // N'en compter que les enfants directs faisait tomber « Reprendre p. 19 »
    // sur la page 28 — neuf coupures internes manquaient à l'appel.
    return Array.from(
      editor.querySelectorAll<HTMLElement>(`.${OVERFLOW_GAP_CLASS}`),
    )
      .map((c) => (c.getBoundingClientRect().bottom - haut) / z)
      .sort((a, b) => a - b)
      // Une ligne de tableau fractionnée pose une cale par CELLULE, à la même
      // hauteur : des doublons, pas des pages.
      .filter((v, i, t) => i === 0 || v - t[i - 1] > 2);
  };

  /** Amener le haut d'une page sous les yeux. */
  const allerALaPage = (numero: number) => {
    const desk = deskRef.current;
    const editor = editorRef.current;
    if (!desk || !editor || numero < 1) return;
    const bornes = bornesDePage();
    const depart = numero === 1 ? 0 : (bornes[numero - 2] ?? 0);
    const z = zoomRef.current || 1;
    const dejaVu =
      editor.getBoundingClientRect().top - desk.getBoundingClientRect().top;
    desk.scrollTo({
      top: desk.scrollTop + dejaVu + depart * z,
      behavior: 'smooth',
    });
  };

  // Le saut demandé de l'extérieur — le marqueur de lecture, pour l'instant.
  useEffect(() => {
    if (!saut || saut.page < 1) return;
    // Après la pagination, pas avant : les bornes n'existent pas tant que les
    // cales ne sont pas posées.
    const t = window.setTimeout(() => allerALaPage(saut.page), 60);
    return () => window.clearTimeout(t);
  }, [saut?.jeton]); // eslint-disable-line react-hooks/exhaustive-deps -- le jeton EST la demande

  // La bande du marqueur, posée sur la feuille comme celles des coupures.
  //
  // Sur la FEUILLE et non dans l'éditeur : elle doit déborder dans la marge,
  // là où l'on attend un signet, et l'éditeur s'arrête au bord du texte.
  // Le marqueur lu par la pose du signet. Une réf et non la valeur capturée :
  // `poserLeSignet` est appelé depuis la PAGINATION, dont la fonction est
  // recréée à chaque rendu — la lire au moment de l'appel évite de poser le
  // signet d'un rendu périmé.
  const marqueurRef = useRef(marqueur);
  marqueurRef.current = marqueur;

  /**
   * Poser le signet de lecture sur la feuille.
   *
   * Appelé DEPUIS la pagination, quand les cales sont définitives. Un effet
   * React réagissant à la signature de pagination ne suffisait pas : la
   * pagination pose ses cales en plusieurs temps, et le signet lisait des
   * bornes intermédiaires — mesuré 2 676 px sous sa page.
   */
  /**
   * Le numéro dans le pied de chaque feuille, comme Word.
   *
   * Les feuilles ne sont pas des éléments : c'est UN fond répété sur toute la
   * hauteur du document. Il n'y a donc rien où écrire « Page 3 » — il faut le
   * poser en absolu, à la hauteur calculée de chaque pied.
   *
   * La hauteur d'un pied : le haut de la feuille, plus la marge haute, plus la
   * zone de texte, plus la moitié de la marge basse. Le numéro se trouve alors
   * dans la marge, jamais sur le texte.
   *
   * Reconstruit seulement quand la pagination a VRAIMENT changé : appelé à
   * chaque image de défilement, refabriquer soixante et un éléments serait
   * payé soixante fois par seconde pour rien.
   */
  const signatureDesNumeros = useRef('');
  const placerLesNumerosDePage = () => {
    const page = pageRef.current;
    const editor = editorRef.current;
    if (!page || !editor) return;
    const cs = getComputedStyle(page);
    const margeBas = cssLengthToPx(cs.getPropertyValue('--note-m-b'), 96);
    const z = zoomRef.current || 1;
    const hautPage = page.getBoundingClientRect().top;
    // LE BAS D'UNE FEUILLE EST LÀ OÙ SA BANDE EST PEINTE, et non à une hauteur
    // calculée. Les feuilles ne sont pas des éléments : c'est un fond continu
    // que les bandes découpent. Mesuré : les bornes de page se suivent à 1049,
    // 972, 894, 948 px — jamais au pas régulier qu'on croirait. Déduire le
    // pied d'une hauteur de papier posait donc les numéros de plus en plus
    // haut, page après page.
    const bandes = [
      ...Array.from(editor.querySelectorAll<HTMLElement>('.succes-overflow-gutter')),
      ...Array.from(
        page.querySelectorAll<HTMLElement>(':scope > .succes-overflow-gutter-flottant'),
      ),
    ]
      .map((b) => (b.getBoundingClientRect().top - hautPage) / z)
      .sort((a, b) => a - b)
      // Une ligne de tableau fractionnée pose une bande par cellule.
      .filter((v, i, t) => i === 0 || v - t[i - 1] > 2);
    // La dernière feuille n'a pas de bande : son pied se déduit du bas du
    // papier réservé.
    const finDuPapier = (page.getBoundingClientRect().height - hautPage + hautPage) / z;
    const pieds = [...bandes, finDuPapier];
    const signature = `${pieds.length}:${Math.round(pieds[0] ?? 0)}:${Math.round(
      pieds[pieds.length - 1] ?? 0,
    )}`;
    if (signature === signatureDesNumeros.current) return;
    signatureDesNumeros.current = signature;
    page.querySelectorAll(':scope > .succes-note-numero').forEach((e) => e.remove());
    // « Page 01 » et non « Page 1 » : les numéros s'alignent quand ils ont
    // tous la même largeur, et un document de plus de cent pages en prend
    // trois sans que rien ne bouge.
    const chiffres = Math.max(2, String(pieds.length).length);
    pieds.forEach((bas, i) => {
      const numero = document.createElement('div');
      numero.className = 'succes-note-numero';
      numero.setAttribute('aria-hidden', 'true');
      numero.textContent = `Page ${String(i + 1).padStart(chiffres, '0')}`;
      numero.style.top = `${Math.round(bas - margeBas / 2)}px`;
      page.appendChild(numero);
    });
  };

  const poserLeSignet = () => {
    const page = pageRef.current;
    const editor = editorRef.current;
    if (!page || !editor) return;
    page.querySelectorAll(':scope > .succes-note-signet').forEach((e) => e.remove());
    const numero = marqueurRef.current;
    if (!numero || numero < 1) return;
    const bornes = bornesDePage();
    const depart = numero === 1 ? 0 : bornes[numero - 2];
    if (depart === undefined) return;
    // L'ÉDITEUR N'EST PAS LA FEUILLE. `top: 0` sur un enfant absolu de la
    // feuille désigne le bord du papier ; le texte commence une marge plus
    // bas. Sans ce report, le signet monte de toute la marge haute.
    const z = zoomRef.current || 1;
    const report =
      (editor.getBoundingClientRect().top - page.getBoundingClientRect().top) / z;
    const signet = document.createElement('div');
    signet.className = 'succes-note-signet';
    signet.setAttribute('aria-hidden', 'true');
    signet.title = `Vous vous étiez arrêté ici, page ${numero}`;
    signet.style.top = `${Math.round(depart + report)}px`;
    page.appendChild(signet);
  };

  // Poser ou retirer le signet quand la page marquée change, sans repaginer.
  useEffect(() => {
    poserLeSignet();
  }, [marqueur]); // eslint-disable-line react-hooks/exhaustive-deps -- la pagination le repose elle-même

  // ─── L'état de la barre : ce que Word dit et que nous ne disions pas ────
  //
  // Aucun `queryCommandState` n'existait dans toute cette fonctionnalité : la
  // barre ne montrait jamais si le gras, l'italique ou une liste étaient en
  // cours. On ne pouvait le savoir qu'en regardant le texte.
  const [etats, setEtats] = useState<Record<string, boolean>>({});
  // La taille du texte sous le curseur, en points. `null` = on ne la dit pas.
  const [tailleCourante, setTailleCourante] = useState<number | null>(null);

  /**
   * Lire la taille du texte sous le curseur.
   *
   * La liste affichait « Taille » en permanence : elle ne lisait jamais le
   * document. Pour connaître la taille d'un paragraphe il fallait lui en
   * appliquer une et regarder si quelque chose bougeait.
   *
   * `getComputedStyle` rend la taille de MISE EN PAGE, pas celle de l'écran :
   * le zoom de la feuille est un `transform: scale()`, qui ne la touche pas.
   * Aucune correction de zoom n'est donc à faire ici — et en faire une
   * afficherait 9 pt sur du 12 pt à 78 %.
   */
  const lireLaTaille = useCallback(() => {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0) {
      setTailleCourante(null);
      return;
    }
    const plage = selection.getRangeAt(0);
    // Une barre qui décrit l'état d'un autre champ est pire qu'une barre muette.
    if (!editor.contains(plage.commonAncestorContainer)) {
      setTailleCourante(null);
      return;
    }
    const tailleDe = (noeud: Node | null): number | null => {
      const el =
        noeud === null
          ? null
          : noeud.nodeType === Node.ELEMENT_NODE
            ? (noeud as HTMLElement)
            : noeud.parentElement;
      if (!el) return null;
      return pointsDepuisPx(parseFloat(getComputedStyle(el).fontSize));
    };
    if (plage.collapsed) {
      setTailleCourante(tailleDe(plage.startContainer));
      return;
    }
    const racine = plage.commonAncestorContainer;
    if (racine.nodeType === Node.TEXT_NODE) {
      setTailleCourante(tailleDe(racine));
      return;
    }
    // Au-delà de ce plafond, on ne répond plus : parcourir soixante mille
    // pixels de document à chaque mouvement de souris ferait ramer la
    // sélection, et une réponse tirée d'un échantillon serait une taille
    // affirmée sans avoir été vue.
    const PLAFOND_NOEUDS = 400;
    const marcheur = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT);
    const tailles: (number | null)[] = [];
    for (let noeud = marcheur.nextNode(); noeud; noeud = marcheur.nextNode()) {
      if (!plage.intersectsNode(noeud)) continue;
      if (!(noeud.textContent || '').trim()) continue;
      tailles.push(tailleDe(noeud));
      if (tailles.length > PLAFOND_NOEUDS) {
        setTailleCourante(null);
        return;
      }
    }
    setTailleCourante(tailleAffichee(tailles));
  }, []);

  useEffect(() => {
    const COMMANDES = [
      'bold',
      'italic',
      'underline',
      'strikeThrough',
      'justifyLeft',
      'justifyCenter',
      'justifyRight',
      'justifyFull',
      'insertUnorderedList',
      'insertOrderedList',
    ];
    const relire = () => {
      // AVANT le garde-fou, pas après : le retour anticipé plus bas laissait
      // la taille figée sur le dernier texte lu, et la barre annonçait « 13 pt »
      // alors que le curseur était parti dans un autre champ. `lireLaTaille`
      // porte son propre garde-fou et rend `null` dans ce cas.
      lireLaTaille();
      const editor = editorRef.current;
      const selection = window.getSelection();
      // Ne rien dire quand la sélection est ailleurs : une barre qui décrit
      // l'état d'un autre champ est pire qu'une barre muette.
      if (
        !editor ||
        !selection ||
        selection.rangeCount === 0 ||
        !editor.contains(selection.getRangeAt(0).commonAncestorContainer)
      ) {
        setEtats({});
        return;
      }
      const suivant: Record<string, boolean> = {};
      for (const commande of COMMANDES) {
        try {
          suivant[commande] = document.queryCommandState(commande);
        } catch {
          // `queryCommandState` est déprécié comme `execCommand` : une
          // commande refusée ne doit pas emporter les neuf autres.
          suivant[commande] = false;
        }
      }
      setEtats(suivant);
    };
    document.addEventListener('selectionchange', relire);
    return () => document.removeEventListener('selectionchange', relire);
  }, [lireLaTaille]);

  /** Le style d'un bouton, teinté quand la commande est active. */
  const styleBouton = (commande?: string) =>
    commande && etats[commande]
      ? {
          ...toolbarBtnStyle,
          background: 'var(--color-accent)',
          color: 'var(--color-bg)',
        }
      : toolbarBtnStyle;

  const toolbarBtn =
    'size-8 rounded-lg flex items-center justify-center cursor-pointer shrink-0';
  const toolbarBtnStyle = {
    color: 'var(--color-text-secondary)',
    border: '1px solid transparent',
  } as const;

  return (
    <div className="min-h-0 flex-1 flex flex-col gap-3">
      <div
        className="flex flex-wrap items-center gap-1 rounded-xl p-2"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      >
        <button type="button" title="Annuler" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => { runCommand('undo'); emitContent(); }}>
          <Undo2 size={14} />
        </button>
        <button type="button" title="Rétablir" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => { runCommand('redo'); emitContent(); }}>
          <Redo2 size={14} />
        </button>
        <Sep />
        <button type="button" title="Gras" aria-pressed={Boolean(etats['bold'])} className={toolbarBtn} style={styleBouton('bold')} onClick={() => runCommand('bold')}>
          <Bold size={14} />
        </button>
        <button type="button" title="Italique" aria-pressed={Boolean(etats['italic'])} className={toolbarBtn} style={styleBouton('italic')} onClick={() => runCommand('italic')}>
          <Italic size={14} />
        </button>
        <button type="button" title="Souligné" aria-pressed={Boolean(etats['underline'])} className={toolbarBtn} style={styleBouton('underline')} onClick={() => runCommand('underline')}>
          <Underline size={14} />
        </button>
        <button
          type="button"
          title="Barré"
          aria-pressed={Boolean(etats['strikeThrough'])}
          className={toolbarBtn}
          style={styleBouton('strikeThrough')}
          onClick={() => runCommand('strikeThrough')}
        >
          <Strikethrough size={14} />
        </button>
        <button
          type="button"
          title="Lien"
          className={toolbarBtn}
          style={toolbarBtnStyle}
          onMouseDown={garderLaSelection}
          onClick={insererUnLien}
        >
          <Link2 size={14} />
        </button>
        <button
          type="button"
          title="Citation"
          className={toolbarBtn}
          style={toolbarBtnStyle}
          onClick={() => {
            runCommand('formatBlock', 'blockquote');
            emitContent();
          }}
        >
          <Quote size={14} />
        </button>
        <button
          type="button"
          title="Code"
          className={toolbarBtn}
          style={toolbarBtnStyle}
          onClick={() => {
            runCommand('formatBlock', 'pre');
            emitContent();
          }}
        >
          <Code size={14} />
        </button>
        <button
          type="button"
          title="Tableau"
          className={toolbarBtn}
          style={toolbarBtnStyle}
          onMouseDown={garderLaSelection}
          onClick={insererUnTableau}
        >
          <Table size={14} />
        </button>
        <button
          type="button"
          title="Effacer la mise en forme"
          className={toolbarBtn}
          style={toolbarBtnStyle}
          onClick={() => {
            runCommand('removeFormat');
            emitContent();
          }}
        >
          <Eraser size={14} />
        </button>
        <Sep />
        <button type="button" title="Aligner à gauche" aria-pressed={Boolean(etats['justifyLeft'])} className={toolbarBtn} style={styleBouton('justifyLeft')} onClick={() => runCommand('justifyLeft')}>
          <AlignLeft size={14} />
        </button>
        <button type="button" title="Centrer" aria-pressed={Boolean(etats['justifyCenter'])} className={toolbarBtn} style={styleBouton('justifyCenter')} onClick={() => runCommand('justifyCenter')}>
          <AlignCenter size={14} />
        </button>
        <button type="button" title="Aligner à droite" aria-pressed={Boolean(etats['justifyRight'])} className={toolbarBtn} style={styleBouton('justifyRight')} onClick={() => runCommand('justifyRight')}>
          <AlignRight size={14} />
        </button>
        <button type="button" title="Justifier" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('justifyFull')}>
          <AlignJustify size={14} />
        </button>
        <Sep />
        <button type="button" title="Liste à puces" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('insertUnorderedList')}>
          <List size={14} />
        </button>
        <button type="button" title="Liste numérotée" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('insertOrderedList')}>
          <ListOrdered size={14} />
        </button>
        <Sep />
        <button type="button" title="Titre 1" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('formatBlock', 'H1')}>
          <Heading1 size={14} />
        </button>
        <button type="button" title="Titre 2" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('formatBlock', 'H2')}>
          <Heading2 size={14} />
        </button>
        <button type="button" title="Titre 3" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('formatBlock', 'H3')}>
          <Heading3 size={14} />
        </button>
        <button type="button" title="Paragraphe" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('formatBlock', 'P')}>
          <span className="text-[10px] font-semibold">P</span>
        </button>
        <button type="button" title="Séparateur" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('insertHorizontalRule')}>
          <Minus size={14} />
        </button>
        <button
          type="button"
          title="Saut de page"
          className={toolbarBtn}
          style={toolbarBtnStyle}
          onClick={insertPageBreak}
        >
          <Scissors size={14} />
        </button>
        <Sep />
        <select
          aria-label="Police"
          value={fontFamily}
          onChange={(event) => {
            const next = event.target.value;
            onMetaChange({ fontFamily: next });
            runCommand('fontName', next);
            emitContent();
          }}
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none max-w-[140px]"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_FONTS.map((font) => (
            <option key={font} value={font} style={{ fontFamily: noteFontCss(font) }}>
              {font}
            </option>
          ))}
        </select>
        <select
          aria-label="Taille"
          title={
            tailleCourante === null
              ? 'Taille du texte'
              : `Le texte sous le curseur est en ${tailleCourante} pt`
          }
          value={tailleCourante === null ? '' : String(tailleCourante)}
          onMouseDown={garderLaSelection}
          onChange={(event) => {
            const points = Number(event.target.value);
            if (points) appliquerStyle(styleDeTaille(points));
            // Relire plutôt que supposer : si la sélection était vide,
            // `appliquerStyle` sort sans rien faire et la liste doit
            // continuer à dire la taille RÉELLE, pas celle qu'on a cliquée.
            lireLaTaille();
          }}
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          <option value="">Taille</option>
          {/* Une taille hors de la liste — un collage depuis Word en 10,5 pt —
              doit s'afficher telle quelle. L'arrondir au voisin le plus proche
              ferait dire à la barre une taille que le texte n'a pas. */}
          {tailleCourante !== null && !NOTE_FONT_SIZES.includes(tailleCourante) ? (
            <option value={tailleCourante}>{tailleCourante} pt</option>
          ) : null}
          {NOTE_FONT_SIZES.map((points) => (
            <option key={points} value={points}>
              {points} pt
            </option>
          ))}
        </select>
        <label className="size-8 rounded-lg flex items-center justify-center cursor-pointer" title="Couleur du texte" style={toolbarBtnStyle}>
          <input
            type="color"
            // L'ancienne constante était #1A2232 — EXACTEMENT le papier du
            // fond Sombre : contraste 1,00 sur 1. On lit l'encre courante.
            value={encreCourante}
            className="absolute opacity-0 size-0"
            onMouseDown={garderLaSelection}
            onChange={(event) => {
              setEncreCourante(event.target.value);
              rendreLaSelection();
              runCommand('foreColor', event.target.value);
              emitContent();
            }}
          />
          <span className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>A</span>
        </label>
        <label className="size-8 rounded-lg flex items-center justify-center cursor-pointer" title="Surlignage" style={toolbarBtnStyle}>
          <input
            type="color"
            defaultValue="#fef08a"
            className="absolute opacity-0 size-0"
            onMouseDown={garderLaSelection}
            onChange={(event) => {
              rendreLaSelection();
              runCommand('hiliteColor', event.target.value);
              emitContent();
            }}
          />
          <Highlighter size={14} />
        </label>
        <Sep />
        <select
          aria-label="Taille du papier"
          value={mise.size}
          onChange={(event) =>
            onMetaChange({ pageSize: event.target.value as SuccesNotePageSize })
          }
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_PAGE_SIZES.map((taille) => (
            <option key={taille.id} value={taille.id}>
              {taille.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Orientation"
          value={mise.orientation}
          onChange={(event) =>
            onMetaChange({
              pageOrientation: event.target.value as SuccesNotePageOrientation,
            })
          }
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_PAGE_ORIENTATIONS.map((sens) => (
            <option key={sens.id} value={sens.id}>
              {sens.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Marges"
          value={mise.margins}
          onChange={(event) =>
            onMetaChange({ pageMargins: event.target.value as SuccesNotePageMargins })
          }
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_PAGE_MARGINS.map((marge) => (
            <option key={marge.id} value={marge.id}>
              {marge.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Fond de page"
          value={pageBackground}
          onChange={(event) =>
            onMetaChange({
              pageBackground: event.target.value as SuccesNotePageBackground,
            })
          }
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_PAGE_BACKGROUNDS.map((bg) => (
            <option key={bg.id} value={bg.id}>
              {bg.label}
            </option>
          ))}
        </select>
      </div>

      <div className="min-h-0 flex-1 flex gap-2">
        {navigation ? (
          <PanneauNavigation
            editeur={editorRef.current}
            bureau={deskRef.current}
            zoom={zoomRef.current}
            pageCourante={pageAffichee}
            cle={`${editorKey}-${signaturePagination}`}
            onFermer={() => onFermerNavigation?.()}
          />
        ) : null}
      <div
        ref={deskRef}
        className="succes-note-desk min-h-0 flex-1 overflow-auto rounded-xl px-2 py-3"
      >
        {/* Le cadre réserve la place réellement occupée : `transform: scale()`
            ne change pas la boîte de layout, donc sans lui le bureau ne
            défilerait pas quand la page dépasse. */}
        <div
          ref={frameRef}
          className="succes-note-frame"
          data-size={mise.size}
          data-orientation={mise.orientation}
          data-margins={mise.margins}
          data-font={fontFamily}
        >
          <div className="succes-note-scale">
        <div
          ref={pageRef}
          className={`succes-note-page succes-note-bg-${pageBackground}`}
        >
          <div
            ref={editorRef}
            className="succes-note-editor outline-none"
            contentEditable
            suppressContentEditableWarning
            data-placeholder="Écrivez librement…"
            data-font={fontFamily}
            lang={docLang === 'ht' ? 'ht' : 'fr'}
            style={{ fontFamily: noteFontCss(fontFamily) }}
            onInput={emitContent}
            onBlur={emitContent}
          />
            </div>
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}

function Sep() {
  return <span className="w-px h-5 mx-0.5 shrink-0" style={{ background: 'var(--color-border)' }} />;
}
