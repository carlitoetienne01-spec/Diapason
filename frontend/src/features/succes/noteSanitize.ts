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

/** Luminance relative WCAG d'une couleur CSS, ou `null` si on ne sait pas la lire. */
export function luminance(css: string): number | null {
  const brut = css.trim().toLowerCase();
  let rgb: number[] | null = null;
  const nombres = brut.match(/^rgba?\(([^)]+)\)$/);
  if (nombres) {
    const parts = nombres[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (parts.length >= 3 && parts.slice(0, 3).every((n) => Number.isFinite(n))) {
      rgb = parts.slice(0, 3);
    }
  } else if (/^#[0-9a-f]{3}$/.test(brut)) {
    rgb = [1, 2, 3].map((i) => parseInt(brut[i] + brut[i], 16));
  } else if (/^#[0-9a-f]{6}$/.test(brut)) {
    rgb = [1, 3, 5].map((i) => parseInt(brut.slice(i, i + 2), 16));
  } else if (brut === 'white') {
    rgb = [255, 255, 255];
  } else if (brut === 'black') {
    rgb = [0, 0, 0];
  }
  if (!rgb) return null;
  const canal = (v: number) => {
    const c = Math.min(255, Math.max(0, v)) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * canal(rgb[0]) + 0.7152 * canal(rgb[1]) + 0.0722 * canal(rgb[2]);
}

/** Le rapport de contraste WCAG entre une couleur et le papier blanc. */
export function contrasteSurBlanc(css: string): number | null {
  const l = luminance(css);
  if (l === null) return null;
  return 1.05 / (l + 0.05);
}

/**
 * Le seuil en dessous duquel une couleur de texte est jetée.
 *
 * 3,0 est le minimum WCAG AA pour du GRAND texte — le plancher le plus
 * indulgent de la norme. On ne cherche pas à imposer un style, seulement à
 * refuser l'illisible : au-dessus, la couleur voulue est conservée telle
 * quelle, même si elle n'est pas idéale.
 */
const CONTRASTE_MINIMUM = 3.0;

/**
 * Retirer d'un `style` les couleurs de TEXTE qu'on ne pourrait pas lire.
 *
 * 30 août 2026, constaté sur une note de Carlito. Un guide collé depuis une
 * application en THÈME SOMBRE portait
 * `<div style="caret-color: rgb(255,255,255); color: rgb(255,255,255)">` —
 * WebKit sérialise le style CALCULÉ quand on copie, thème compris. Tout ce
 * qui ne déclarait pas sa propre couleur héritait donc du blanc, sur du
 * papier blanc : un tableau entier de vingt-cinq lignes s'affichait vide
 * alors que « Python », « 550 à 750 h » et « 1,5 / 5 » y étaient bel et bien,
 * et le bloc « RÉPONSE DIRECTE » était illisible.
 *
 * Seule la déclaration fautive tombe : le reste du style — taille, graisse,
 * alignement, fond — est conservé, et la couleur héritée du papier prend le
 * relais. Les couleurs voulues et lisibles (le bleu des titres, le rouge des
 * avertissements) passent intactes.
 *
 * Le contraste se mesure contre le BLANC, qui est le papier par défaut. Une
 * couleur qui échoue sur blanc échoue aussi sur le sépia, et sur le papier
 * sombre l'encre héritée est claire : jeter est correct sur les cinq fonds.
 */
export function nettoyerCouleursIllisibles(style: string): string {
  // `caret-color` compte autant que `color` : un curseur blanc sur papier
  // blanc est un curseur qu'on ne voit pas, et c'est exactement ce que le
  // collage depuis un thème sombre pose partout. Constaté en corrigeant une
  // assertion de test trop lâche — `caret-color` CONTIENT « color: ».
  if (!/(^|;)\s*(caret-)?color\s*:/i.test(style)) return style;
  return style
    .split(';')
    .filter((declaration) => {
      const [propriete, ...reste] = declaration.split(':');
      const nom = propriete.trim().toLowerCase();
      if (nom !== 'color' && nom !== 'caret-color') return true;
      const contraste = contrasteSurBlanc(reste.join(':'));
      // Une couleur qu'on ne sait pas lire (un mot-clé exotique, une
      // fonction) est CONSERVÉE : refuser ce qu'on ne comprend pas
      // effacerait des mises en forme légitimes.
      return contraste === null || contraste >= CONTRASTE_MINIMUM;
    })
    .join(';');
}

function cleanStyle(value: string) {
  if (/url\s*\(|expression\s*\(|javascript:|@import|behavior\s*:/i.test(value)) return '';
  return nettoyerCouleursIllisibles(value);
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
