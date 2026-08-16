import type {
  SuccesNoteDocLang,
  SuccesNotePageBackground,
  SuccesNotePageFormat,
} from './types';

export const NOTE_PAGE_FORMATS: Array<{ id: SuccesNotePageFormat; label: string }> = [
  { id: 'a4', label: 'A4' },
  { id: 'letter', label: 'Lettre US' },
  { id: 'a5', label: 'A5' },
  { id: 'wide', label: 'Page large' },
  { id: 'narrow', label: 'Page étroite' },
  { id: 'full', label: 'Sans marge' },
  { id: 'reading', label: 'Lecture' },
];

export const NOTE_PAGE_BACKGROUNDS: Array<{ id: SuccesNotePageBackground; label: string }> = [
  { id: 'default', label: 'Blanc' },
  { id: 'lined', label: 'Ligné' },
  { id: 'grid', label: 'Quadrillé' },
  { id: 'sepia', label: 'Sépia' },
  { id: 'dark', label: 'Sombre' },
];

export const NOTE_FONTS = [
  'Press Start 2P',
  'VT323',
  'Special Elite',
  'Inter',
  'Poppins',
  'Roboto',
  'Lato',
  'Open Sans',
  'Merriweather',
  'Montserrat',
  'Source Serif 4',
  'Nunito',
  'Playfair Display',
] as const;

export const NOTE_DOC_LANGS: Array<{ id: SuccesNoteDocLang; label: string }> = [
  { id: 'fr', label: 'Français (France)' },
  { id: 'ht', label: 'Kreyòl Ayisyen' },
];

export const NOTE_FONT_SIZE_COMMANDS = [
  { id: '1', label: 'Très petit' },
  { id: '2', label: 'Petit' },
  { id: '3', label: 'Normal' },
  { id: '4', label: 'Grand' },
  { id: '5', label: 'Très grand' },
  { id: '6', label: 'Énorme' },
  { id: '7', label: 'Max' },
] as const;

export function noteFontCss(fontFamily: string) {
  const name = fontFamily.replace(/'/g, "\\'");
  const stacks: Record<string, string> = {
    'Press Start 2P': `'Press Start 2P', ui-monospace, monospace`,
    VT323: `'VT323', ui-monospace, monospace`,
    'Special Elite': `'Special Elite', 'Courier New', ui-monospace, monospace`,
    Inter: `'Inter', ui-sans-serif, system-ui, sans-serif`,
    Poppins: `'Poppins', ui-sans-serif, system-ui, sans-serif`,
    Roboto: `'Roboto', ui-sans-serif, system-ui, sans-serif`,
    Lato: `'Lato', ui-sans-serif, system-ui, sans-serif`,
    'Open Sans': `'Open Sans', ui-sans-serif, system-ui, sans-serif`,
    Merriweather: `'Merriweather', ui-serif, Georgia, serif`,
    Montserrat: `'Montserrat', ui-sans-serif, system-ui, sans-serif`,
    'Source Serif 4': `'Source Serif 4', ui-serif, Georgia, serif`,
    Nunito: `'Nunito', ui-sans-serif, system-ui, sans-serif`,
    'Playfair Display': `'Playfair Display', ui-serif, Georgia, serif`,
  };
  return stacks[fontFamily] ?? `'${name}', ui-sans-serif, system-ui, sans-serif`;
}
