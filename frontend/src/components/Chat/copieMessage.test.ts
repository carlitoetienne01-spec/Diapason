import { afterEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { copierMessage, htmlDeLaReponse } from './copieMessage';
import { sanitizeNoteHtml } from '../../features/succes/noteSanitize';

function element(html: string) {
  const el = document.createElement('div');
  el.innerHTML = html;
  return el;
}
function lire(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const lecteur = new FileReader();
    lecteur.onload = () => resolve(String(lecteur.result));
    lecteur.onerror = reject;
    lecteur.readAsText(blob);
  });
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('copie des réponses vers une note', () => {
  it('conserve 100 lignes, quatre colonnes et les titres après nettoyage par Notes', () => {
    const lignes = Array.from({ length: 100 }, (_, i) => `| ${101 + i} | awake | awoke | awoken |`);
    const markdown = ['### Verbes', '', '**Deuxième tranche**', '',
      '| N° | Infinitif | Passé Simple | Participe Passé |', '|:---:|:---|:---|:---|', ...lignes].join('\n');
    const rendu = element(renderToStaticMarkup(createElement(ReactMarkdown, { remarkPlugins: [remarkGfm], children: markdown })));
    const note = element(sanitizeNoteHtml(htmlDeLaReponse(rendu)));
    expect(note.querySelectorAll('tbody tr')).toHaveLength(100);
    expect(note.querySelectorAll('th')).toHaveLength(4);
    expect(note.querySelectorAll('td')).toHaveLength(400);
    expect(note.querySelector('th')?.style.textAlign).toBe('center');
    expect(note.querySelector('tbody tr')?.textContent).toBe('101awakeawokeawoken');
    expect(note.querySelector('tbody tr:last-child')?.textContent).toBe('200awakeawokeawoken');
    expect(note.querySelector('strong')?.textContent).toBe('Deuxième tranche');
    expect(note.querySelector('h3')?.textContent).toBe('Verbes');
  });
  it('retire les outils et le thème sans modifier la réponse affichée ni son code', () => {
    const source = element('<p style="color:white">Texte <em>italique</em></p><div class="code-block-wrapper"><div>python<button>Copier</button></div><pre><code>&lt;script&gt;\nprint(1)</code></pre></div><ul><li>Un</li></ul><a href="https://example.com">Lien</a>');
    const avant = source.innerHTML;
    const copie = element(htmlDeLaReponse(source));
    expect(source.innerHTML).toBe(avant);
    expect(copie.querySelector('button')).toBeNull();
    expect(copie.textContent).not.toContain('python');
    expect(copie.querySelector('code')?.textContent).toBe('<script>\nprint(1)');
    expect(copie.querySelector('script')).toBeNull();
    expect(copie.querySelector('[style]')).toBeNull();
    expect(copie.querySelector('li')?.textContent).toBe('Un');
    expect(copie.querySelector('a')?.getAttribute('href')).toBe('https://example.com');
  });
  it('écrit HTML et Markdown dans le même élément du presse-papiers', async () => {
    class Item { constructor(public formats: Record<string, Blob>) {} }
    vi.stubGlobal('ClipboardItem', Item);
    const write = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { write } });
    await copierMessage('**bonjour**', element('<p><strong>bonjour</strong></p>'));
    const items = write.mock.calls[0][0] as Item[];
    expect(items).toHaveLength(1);
    expect(await lire(items[0].formats['text/plain'])).toBe('**bonjour**');
    expect(await lire(items[0].formats['text/html'])).toContain('<strong>bonjour</strong>');
  });
  it('le code et les mots de l’utilisateur restent du texte exact', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    await copierMessage('<table> **texte**');
    expect(writeText).toHaveBeenCalledWith('<table> **texte**');
  });
  it('un refus remonte au bouton au lieu d’annoncer Copié', async () => {
    vi.stubGlobal('ClipboardItem', class {});
    vi.stubGlobal('navigator', { clipboard: { write: vi.fn().mockRejectedValue(new Error('Denied')) } });
    await expect(copierMessage('test', element('<p>test</p>'))).rejects.toThrow('Denied');
  });
  it('le repli transmet les deux formats et retire son gestionnaire', async () => {
    vi.stubGlobal('ClipboardItem', undefined);
    const setData = vi.fn();
    const exec = vi.fn(() => {
      const event = new Event('copy', { cancelable: true });
      Object.defineProperty(event, 'clipboardData', { value: { setData } });
      document.dispatchEvent(event);
      return event.defaultPrevented;
    });
    Object.defineProperty(document, 'execCommand', { configurable: true, value: exec });
    try {
      await copierMessage('**test**', element('<strong>test</strong>'));
      expect(setData).toHaveBeenCalledWith('text/plain', '**test**');
      expect(setData).toHaveBeenCalledWith('text/html', '<strong>test</strong>');
      expect(exec()).toBe(false);
      expect(setData).toHaveBeenCalledTimes(2);
      exec.mockImplementation(() => false);
      await expect(copierMessage('test', element('test'))).rejects.toThrow();
    } finally { delete (document as Partial<Document>).execCommand; }
  });
});
