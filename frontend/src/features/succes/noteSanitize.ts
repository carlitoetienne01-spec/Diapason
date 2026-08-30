const ALLOWED_TAGS = new Set([
  'P', 'BR', 'DIV', 'SPAN', 'B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'DEL',
  'MARK', 'SMALL', 'SUB', 'SUP', 'UL', 'OL', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'BLOCKQUOTE', 'PRE', 'CODE', 'A', 'HR', 'IMG', 'FONT',
  'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'TD', 'TH',
]);

const DROP_TAGS = new Set([
  'SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'SVG', 'MATH', 'LINK', 'META',
  'FORM', 'INPUT', 'BUTTON', 'TEXTAREA', 'BASE',
]);

function cleanStyle(value: string) {
  if (/url\s*\(|expression\s*\(|javascript:|@import|behavior\s*:/i.test(value)) return '';
  return value;
}

/** Sanitize note HTML before injecting into contentEditable (whitelist, no on*). */
export function sanitizeNoteHtml(html: string) {
  if (!html) return '';
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(String(html), 'text/html');
  } catch {
    return String(html).replace(/<[^>]*>/g, '');
  }

  function walk(src: Node, dst: HTMLElement) {
    for (const child of Array.from(src.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        dst.appendChild(document.createTextNode(child.nodeValue ?? ''));
        continue;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      const element = child as HTMLElement;
      const tag = element.tagName;
      if (DROP_TAGS.has(tag)) continue;
      // Gouttières de pagination : elles n'existent que dans l'éditeur.
      if (/\bsucces-overflow-gap\b/.test(element.getAttribute('class') || '')) continue;
      if (!ALLOWED_TAGS.has(tag)) {
        walk(element, dst);
        continue;
      }
      const next = document.createElement(tag);
      for (const attr of Array.from(element.attributes)) {
        const name = attr.name.toLowerCase();
        const value = attr.value;
        if (name.startsWith('on')) continue;
        if (name === 'style') {
          const cleaned = cleanStyle(value);
          if (cleaned) next.setAttribute('style', cleaned);
          continue;
        }
        if (name === 'href') {
          if (/^\s*(https?:|mailto:|#)/i.test(value)) {
            next.setAttribute('href', value);
            next.setAttribute('rel', 'noopener noreferrer nofollow');
            next.setAttribute('target', '_blank');
          }
          continue;
        }
        if (name === 'src') {
          if (/^\s*data:image\//i.test(value)) next.setAttribute('src', value);
          continue;
        }
        if (name === 'colspan' || name === 'rowspan') {
          const span = Number(value);
          if (Number.isInteger(span) && span >= 1 && span <= 50) {
            next.setAttribute(name, String(span));
          }
          continue;
        }
        if (
          name === 'alt' ||
          name === 'title' ||
          name === 'width' ||
          name === 'height' ||
          name === 'class' ||
          name === 'color' ||
          name === 'face' ||
          name === 'scope'
        ) {
          next.setAttribute(name, value);
        }
      }
      walk(element, next);
      dst.appendChild(next);
    }
  }

  const frag = document.createElement('div');
  walk(doc.body, frag);
  return frag.innerHTML;
}

export function stripNoteHtml(html: string) {
  if (!html) return '';
  try {
    const doc = new DOMParser().parseFromString(String(html), 'text/html');
    return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
  } catch {
    return String(html).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  }
}

export function countNoteWords(html: string) {
  const text = stripNoteHtml(html);
  if (!text) return 0;
  return text.split(/\s+/).filter(Boolean).length;
}
