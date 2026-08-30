import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Heading1,
  Heading2,
  Heading3,
  Highlighter,
  Italic,
  List,
  ListOrdered,
  Minus,
  Redo2,
  Scissors,
  Underline,
  Undo2,
} from 'lucide-react';

import {
  NOTE_DOC_LANGS,
  NOTE_FONTS,
  NOTE_FONT_SIZES,
  styleDeTaille,
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
import { fitZoom, NOTE_ZOOMS } from './noteZoom';
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
  if (gap.mode === 'sheet') {
    const band = document.createElement('div');
    band.className = 'succes-overflow-gutter';
    band.style.marginTop = `${gap.fill + margin}px`;
    inner.appendChild(band);
  }
  if (before.tagName === 'TR') {
    const row = document.createElement('tr');
    row.className = OVERFLOW_GAP_CLASS;
    row.contentEditable = 'false';
    row.setAttribute('aria-hidden', 'true');
    const cell = document.createElement('td');
    cell.colSpan = 50;
    cell.appendChild(inner);
    row.appendChild(cell);
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
  const tops: number[] = [];
  for (const rect of Array.from(range.getClientRects())) {
    if (rect.height <= 0) continue;
    // Ces rectangles sont en pixels ÉCRAN : `transform: scale()` les réduit.
    // Les hauteurs de bloc, elles, viennent de `offsetTop`/`offsetHeight`,
    // des unités de LAYOUT que le zoom ne touche pas. Mélanger les deux
    // ferait bouger la pagination à chaque redimensionnement de fenêtre —
    // exactement ce qu'on est en train de supprimer.
    const top = (rect.top - editorTop) / zoom;
    const hauteur = rect.height / zoom;
    if (tops.length === 0 || top - tops[tops.length - 1] > hauteur / 2) {
      tops.push(top);
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

/** La cale posée DANS un paragraphe, entre deux de ses lignes. */
function makeInlineGap(hauteur: number, fill: number, margin: number): HTMLElement {
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
  const band = document.createElement('span');
  band.className = 'succes-overflow-gutter';
  band.style.cssText = `position:absolute;left:0;right:0;top:${fill + margin}px`;
  cale.appendChild(band);
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
  const editorLayoutTop = editor.offsetTop;
  return collectBlockNodes(editor).map((el) => {
    const kind: PageBlock['kind'] =
      el.tagName === 'HR' && el.classList.contains(PAGE_BREAK_CLASS)
        ? 'break'
        : /^H[1-6]$/.test(el.tagName)
          ? 'heading'
          : 'block';
    // Les lignes ne se mesurent que là où une coupe est permise : un titre,
    // une ligne de tableau et un saut manuel partent entiers, et appeler
    // `getClientRects` sur chacun coûterait sans rien apporter.
    const coupable = kind === 'block' && el.tagName !== 'TR' && el.tagName !== 'IMG';
    // `offsetTop` est relatif au premier ancêtre positionné — la feuille —
    // et non à l'éditeur : on retranche celui de l'éditeur pour rester dans
    // son repère, comme le faisait `getBoundingClientRect`.
    const top = offsetDepuis(el, editor) - editorLayoutTop;
    return {
      el,
      top,
      height: Math.max(el.offsetHeight, 1),
      kind,
      lines: coupable ? lignesDuBloc(el, editorTop, zoom) : undefined,
    };
  });
}

/** Le haut d'un élément dans le repère de layout de la feuille. */
function offsetDepuis(el: HTMLElement, editor: HTMLElement): number {
  let total = 0;
  let noeud: HTMLElement | null = el;
  // Une puce vit dans un <ul>, une ligne dans un <table> : leur `offsetTop`
  // est relatif à ce parent, pas à la feuille.
  while (noeud && noeud !== editor.offsetParent && noeud !== editor) {
    total += noeud.offsetTop;
    noeud = noeud.offsetParent as HTMLElement | null;
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
    // `y` est en unités de layout ; `positionDeLigne` compare des rectangles
    // d'écran. Le zoom fait le pont entre les deux.
    const point = positionDeLigne(target, y * zoom, editor.getBoundingClientRect().top);
    if (!point) continue;
    const range = document.createRange();
    range.setStart(point.node, point.offset);
    range.collapse(true);
    range.insertNode(makeInlineGap(hauteur, gap.fill, margin));
  }
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
  // `null` = « Largeur de page », le réglage par défaut de Word.
  const [zoomChoisi, setZoomChoisi] = useState<number | null>(null);
  // L'encre du papier courant, et non une constante : #1A2232 est exactement
  // la couleur du papier du fond Sombre — contraste 1,00 sur 1.
  const [encreCourante, setEncreCourante] = useState('#1a2232');
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
  const appliquerStyle = (declaration: string) => {
    rendreLaSelection();
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.isCollapsed) return;
    document.execCommand('fontSize', false, '7');
    for (const marque of Array.from(editor.querySelectorAll('font[size="7"]'))) {
      const span = document.createElement('span');
      span.setAttribute('style', declaration);
      while (marque.firstChild) span.appendChild(marque.firstChild);
      marque.replaceWith(span);
    }
    emitContent();
  };

  const paginate = () => {
    const page = pageRef.current;
    const editor = editorRef.current;
    if (!page || !editor) return;
    applyingGaps.current = true;
    suppressObserverUntil.current = Date.now() + 150;
    try {
      const feuilles = applyOverflowGaps(editor, page, zoomRef.current);
      onPageCount?.(feuilles);
    } finally {
      applyingGaps.current = false;
    }
  };

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const sanitized = sanitizeNoteHtml(content);
    if (sanitizeNoteHtml(editor.innerHTML) !== sanitized) {
      editor.innerHTML = sanitized;
    }
    paginate();
  }, [editorKey, pageFormat, pageSize, pageOrientation, pageMargins, fontFamily]); // eslint-disable-line react-hooks/exhaustive-deps -- remount content on note switch

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
      const zoom = zoomChoisi ?? fitZoom(desk.clientWidth, papier);
      if (Math.abs(zoom - zoomRef.current) < 0.001) return;
      zoomRef.current = zoom;
      frame.style.setProperty('--note-zoom', String(zoom));
      // La pagination se mesure en unités de LAYOUT, que le zoom ne touche
      // pas : elle n'a donc pas à être refaite. Seuls les rectangles de ligne
      // en dépendent, et ils sont relus au prochain passage.
    };

    ajuster();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(ajuster);
    observer.observe(desk);
    return () => observer.disconnect();
  }, [zoomChoisi, pageFormat, pageSize, pageOrientation, pageMargins]);

  useEffect(() => {
    const page = pageRef.current;
    if (!page || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (Date.now() < suppressObserverUntil.current) return;
      paginate();
    });
    observer.observe(page);
    return () => observer.disconnect();
  }, [editorKey, pageFormat, pageSize, pageOrientation, pageMargins]);

  const emitContent = () => {
    if (applyingGaps.current) return;
    const editor = editorRef.current;
    if (!editor) return;
    onContentChange(sanitizeNoteHtml(editor.innerHTML));
    paginate();
  };

  /** Forces a new page in the folder icon's sheet count. */
  const insertPageBreak = () => {
    editorRef.current?.focus();
    runCommand('insertHTML', PAGE_BREAK_HTML);
    emitContent();
  };

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
        <button type="button" title="Annuler" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('undo')}>
          <Undo2 size={14} />
        </button>
        <button type="button" title="Rétablir" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('redo')}>
          <Redo2 size={14} />
        </button>
        <Sep />
        <button type="button" title="Gras" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('bold')}>
          <Bold size={14} />
        </button>
        <button type="button" title="Italique" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('italic')}>
          <Italic size={14} />
        </button>
        <button type="button" title="Souligné" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('underline')}>
          <Underline size={14} />
        </button>
        <Sep />
        <button type="button" title="Aligner à gauche" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('justifyLeft')}>
          <AlignLeft size={14} />
        </button>
        <button type="button" title="Centrer" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('justifyCenter')}>
          <AlignCenter size={14} />
        </button>
        <button type="button" title="Aligner à droite" className={toolbarBtn} style={toolbarBtnStyle} onClick={() => runCommand('justifyRight')}>
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
          value=""
          onMouseDown={garderLaSelection}
          onChange={(event) => {
            const points = Number(event.target.value);
            if (points) appliquerStyle(styleDeTaille(points));
            event.target.value = '';
          }}
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          <option value="">Taille</option>
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
          aria-label="Zoom"
          value={zoomChoisi === null ? 'ajuste' : String(Math.round(zoomChoisi * 100))}
          onChange={(event) => {
            const cran = NOTE_ZOOMS.find((z) => z.id === event.target.value);
            setZoomChoisi(cran ? cran.valeur : null);
          }}
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_ZOOMS.map((cran) => (
            <option key={cran.id} value={cran.id}>
              {cran.label}
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
        <label
          className="h-8 flex items-center gap-1.5 rounded-lg px-2 cursor-pointer"
          title="Couleur du cartable"
          style={{ border: '1px solid var(--color-border)' }}
        >
          <span
            className="size-4 rounded-full"
            style={{ background: color, boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.2)' }}
          />
          <span className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>
            Cartable
          </span>
          <input
            type="color"
            value={color}
            className="absolute opacity-0 size-0"
            onChange={(event) => onMetaChange({ color: event.target.value })}
          />
        </label>
        <select
          aria-label="Langue du document"
          value={docLang}
          onChange={(event) =>
            onMetaChange({ docLang: event.target.value as SuccesNoteDocLang })
          }
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_DOC_LANGS.map((lang) => (
            <option key={lang.id} value={lang.id}>
              {lang.label}
            </option>
          ))}
        </select>
      </div>

      <div
        ref={deskRef}
        className="succes-note-desk min-h-0 flex-1 overflow-auto rounded-xl px-2 py-3"
      >
        {/* Le cadre réserve la place réellement occupée : `transform: scale()`
            ne change pas la boîte de layout, donc sans lui le bureau ne
            défilerait pas quand la page dépasse. */}
        <div ref={frameRef} className="succes-note-frame">
          <div className="succes-note-scale">
        <div
          ref={pageRef}
          className={`succes-note-page succes-note-bg-${pageBackground}`}
          data-size={mise.size}
          data-orientation={mise.orientation}
          data-margins={mise.margins}
          data-font={fontFamily}
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
  );
}

function Sep() {
  return <span className="w-px h-5 mx-0.5 shrink-0" style={{ background: 'var(--color-border)' }} />;
}
