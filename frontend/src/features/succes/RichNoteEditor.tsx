import { useEffect, useRef } from 'react';
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
import { PAGE_BREAK_HTML } from './notePages';
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

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const sanitized = sanitizeNoteHtml(content);
    if (editor.innerHTML !== sanitized) {
      editor.innerHTML = sanitized;
    }
  }, [editorKey]); // eslint-disable-line react-hooks/exhaustive-deps -- remount content on note switch

  const emitContent = () => {
    const editor = editorRef.current;
    if (!editor) return;
    onContentChange(sanitizeNoteHtml(editor.innerHTML));
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

      <div className="min-h-0 flex-1 overflow-auto rounded-xl px-2 py-3" style={{ background: 'var(--color-bg-secondary)' }}>
        <div
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
