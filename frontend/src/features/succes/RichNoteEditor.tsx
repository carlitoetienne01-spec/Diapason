import { useEffect, useLayoutEffect, useRef } from 'react';
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
  NOTE_FONT_SIZE_COMMANDS,
  NOTE_PAGE_BACKGROUNDS,
  NOTE_PAGE_FORMATS,
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
import type {
  SuccesNoteDocLang,
  SuccesNotePageBackground,
  SuccesNotePageFormat,
} from './types';

type Props = {
  content: string;
  pageFormat: SuccesNotePageFormat;
  pageBackground: SuccesNotePageBackground;
  fontFamily: string;
  docLang: SuccesNoteDocLang;
  color: string;
  onContentChange: (html: string) => void;
  onMetaChange: (patch: {
    pageFormat?: SuccesNotePageFormat;
    pageBackground?: SuccesNotePageBackground;
    fontFamily?: string;
    docLang?: SuccesNoteDocLang;
    color?: string;
  }) => void;
  editorKey: string;
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
function lignesDuBloc(el: HTMLElement, editorTop: number): number[] {
  const range = document.createRange();
  range.selectNodeContents(el);
  const tops: number[] = [];
  for (const rect of Array.from(range.getClientRects())) {
    if (rect.height <= 0) continue;
    const top = rect.top - editorTop;
    if (tops.length === 0 || top - tops[tops.length - 1] > rect.height / 2) {
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

function measuredBlocks(editor: HTMLElement): Array<PageBlock & { el: HTMLElement }> {
  const editorTop = editor.getBoundingClientRect().top;
  return collectBlockNodes(editor).map((el) => {
    const rect = el.getBoundingClientRect();
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
    return {
      el,
      top: rect.top - editorTop,
      height: Math.max(rect.height, 1),
      kind,
      lines: coupable ? lignesDuBloc(el, editorTop) : undefined,
    };
  });
}

function applyOverflowGaps(editor: HTMLElement, page: HTMLElement) {
  const style = getComputedStyle(page);
  const pageHeight = cssLengthToPx(
    style.getPropertyValue('--note-page-height'),
    page.offsetHeight || 1,
  );
  const margin = cssLengthToPx(style.getPropertyValue('--note-margin'), 32);
  const contentHeight = pageHeight - 2 * margin;
  if (contentHeight < 80) return;
  editor.querySelectorAll(`.${OVERFLOW_GAP_CLASS}`).forEach((node) => node.remove());
  const collected = measuredBlocks(editor);
  const plan = overflowGapPlan(
    collected.map(({ top, height, kind }) => ({ top, height, kind })),
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
    const point = positionDeLigne(target, y, editor.getBoundingClientRect().top);
    if (!point) continue;
    const range = document.createRange();
    range.setStart(point.node, point.offset);
    range.collapse(true);
    range.insertNode(makeInlineGap(hauteur, gap.fill, margin));
  }
}

export function RichNoteEditor({
  content,
  pageFormat,
  pageBackground,
  fontFamily,
  docLang,
  color,
  onContentChange,
  onMetaChange,
  editorKey,
}: Props) {
  const editorRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const applyingGaps = useRef(false);
  const suppressObserverUntil = useRef(0);

  const paginate = () => {
    const page = pageRef.current;
    const editor = editorRef.current;
    if (!page || !editor) return;
    applyingGaps.current = true;
    suppressObserverUntil.current = Date.now() + 150;
    try {
      applyOverflowGaps(editor, page);
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
  }, [editorKey, pageFormat, fontFamily]); // eslint-disable-line react-hooks/exhaustive-deps -- remount content on note switch

  useEffect(() => {
    const page = pageRef.current;
    if (!page || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (Date.now() < suppressObserverUntil.current) return;
      paginate();
    });
    observer.observe(page);
    return () => observer.disconnect();
  }, [editorKey, pageFormat]);

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
          defaultValue="3"
          onChange={(event) => runCommand('fontSize', event.target.value)}
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_FONT_SIZE_COMMANDS.map((size) => (
            <option key={size.id} value={size.id}>
              {size.label}
            </option>
          ))}
        </select>
        <label className="size-8 rounded-lg flex items-center justify-center cursor-pointer" title="Couleur du texte" style={toolbarBtnStyle}>
          <input
            type="color"
            defaultValue="#1A2232"
            className="absolute opacity-0 size-0"
            onChange={(event) => runCommand('foreColor', event.target.value)}
          />
          <span className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>A</span>
        </label>
        <label className="size-8 rounded-lg flex items-center justify-center cursor-pointer" title="Surlignage" style={toolbarBtnStyle}>
          <input
            type="color"
            defaultValue="#fef08a"
            className="absolute opacity-0 size-0"
            onChange={(event) => runCommand('hiliteColor', event.target.value)}
          />
          <Highlighter size={14} />
        </label>
        <Sep />
        <select
          aria-label="Format de page"
          value={pageFormat}
          onChange={(event) =>
            onMetaChange({ pageFormat: event.target.value as SuccesNotePageFormat })
          }
          className="h-8 rounded-lg px-2 text-xs bg-transparent outline-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          {NOTE_PAGE_FORMATS.map((format) => (
            <option key={format.id} value={format.id}>
              {format.label}
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

      <div className="succes-note-desk min-h-0 flex-1 overflow-auto rounded-xl px-2 py-3">
        <div
          ref={pageRef}
          className={`succes-note-page succes-note-format-${pageFormat} succes-note-bg-${pageBackground}`}
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
  );
}

function Sep() {
  return <span className="w-px h-5 mx-0.5 shrink-0" style={{ background: 'var(--color-border)' }} />;
}
