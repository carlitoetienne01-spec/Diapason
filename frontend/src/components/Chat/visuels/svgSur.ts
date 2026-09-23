import DOMPurify from 'dompurify';
import { SOURCE_MAX } from './formatVisuel';

export interface PaletteVisuel { fond: string; texte: string; accent: string; bord: string; secondaire: string; police: string }
export interface SvgPret { svg: string; png?: string; width: number; height: number; title: string }

/** Le SVG est affiché comme IMAGE isolée. Pas de HTML, d'événement, de
 * ressource distante ni de script provenant du modèle (23/09/2026). */
export function nettoyerSvg(source: string, palette: PaletteVisuel, stylesDuMoteur = false): SvgPret {
  if (source.length > (stylesDuMoteur ? 500_000 : SOURCE_MAX) || /<!DOCTYPE|<!ENTITY/i.test(source)) throw new Error('svg');
  const xml = new DOMParser().parseFromString(source, 'image/svg+xml');
  if (xml.querySelector('parsererror') || xml.documentElement.localName !== 'svg') throw new Error('svg');
  const nettoye = DOMPurify.sanitize(source, {
    USE_PROFILES: { svg: true },
    FORBID_TAGS: ['script', 'foreignObject', 'image', 'a', 'animate', 'animateMotion', 'animateTransform', 'set', 'filter', ...(stylesDuMoteur ? [] : ['style'])],
    FORBID_ATTR: ['tabindex'],
  });
  const doc = new DOMParser().parseFromString(nettoye, 'image/svg+xml');
  const svg = doc.documentElement;
  if (svg.localName !== 'svg' || svg.querySelectorAll('*').length > 2500) throw new Error('svg');
  const variables: Record<string, string> = {
    '--color-bg': palette.fond, '--color-bg-secondary': palette.fond,
    '--color-text': palette.texte, '--color-text-secondary': palette.secondaire,
    '--color-accent': palette.accent, '--color-border': palette.bord,
  };
  for (const el of [svg, ...svg.querySelectorAll('*')]) {
    if (el.localName === 'style') {
      // Mermaid ajoute ses propres animations CSS. Leur suppression ne doit
      // pas emporter les couleurs des nœuds (test visuel du 23/09/2026).
      el.textContent = (el.textContent ?? '').replace(/@keyframes[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}/gi, '');
      if (/@|\\|(?:https?:|data:|\/\/)|url\(\s*['"]?[^#]/i.test(el.textContent)) el.remove();
    }
    if (el.hasAttribute('style')) {
      const declarations = document.createElement('span').style;
      declarations.cssText = el.getAttribute('style') || '';
      for (const nom of ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'font-size', 'font-weight', 'text-anchor', 'opacity', 'dominant-baseline']) {
        const valeur = declarations.getPropertyValue(nom);
        if (valeur) el.setAttribute(nom, valeur);
      }
      el.removeAttribute('style');
    }
    for (const attr of [...el.attributes]) {
      const nom = attr.localName.toLowerCase();
      if (nom.startsWith('on') || (nom === 'href' && !/^#[\w:.-]+$/.test(attr.value))
        || /url\(/i.test(attr.value) && !/^url\(\s*['"]?#[\w:.-]+['"]?\s*\)$/.test(attr.value)) {
        el.removeAttributeNode(attr); continue;
      }
      if (/var\(/.test(attr.value)) {
        const remplace = attr.value.replace(/var\(\s*(--[\w-]+)\s*\)/g, (_, cle) => variables[cle] ?? palette.texte);
        if (/var\(/.test(remplace)) el.removeAttributeNode(attr); else el.setAttribute(attr.name, remplace);
      }
    }
  }
  const vue = (svg.getAttribute('viewBox') ?? '').trim().split(/[\s,]+/).map(Number);
  let width: number, height: number;
  if (vue.length === 4 && vue.every(Number.isFinite) && vue[2] > 0 && vue[3] > 0) [width, height] = vue.slice(2);
  else {
    width = Number(svg.getAttribute('width')); height = Number(svg.getAttribute('height'));
    if (!(width > 0 && height > 0)) throw new Error('svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  }
  if (width > 10_000 || height > 10_000 || width / height > 20 || height / width > 20) throw new Error('size');
  svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  svg.setAttribute('width', String(width)); svg.setAttribute('height', String(height));
  svg.setAttribute('color', palette.texte); svg.setAttribute('font-family', palette.police);
  if (!svg.hasAttribute('fill')) svg.setAttribute('fill', palette.texte);
  return { svg: new XMLSerializer().serializeToString(svg), width, height,
    title: svg.querySelector('title')?.textContent?.slice(0, 180) || '' };
}

export const urlSvg = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

export function preparerMermaid(source: string): string {
  if (source.length > 12_000 || source.split('\n').length > 160) throw new Error('size');
  // Qwen 9b ajoute « style A fill:… » malgré la consigne (essai réel du
  // 23/09/2026). Ignorer sa décoration, pas ses nœuds ni leurs relations.
  const propre = source.split('\n').flatMap(ligne => {
    if (!/^\s*(?:style|classDef|linkStyle)\s/.test(ligne)) return [ligne];
    // « style A fill:red; A-->B » garde bien la relation après le style.
    return ligne.split(';').filter(partie => !/^\s*(?:style|classDef|linkStyle)\s/.test(partie));
  }).join('\n');
  verifierMermaid(propre);
  return propre;
}

export function verifierMermaid(source: string): void {
  // La configuration appartient à Diapason ; aucun frontmatter/directive,
  // CSS, lien ou icône distante ne peut la remplacer depuis le modèle.
  if (source.length > 12_000 || source.split('\n').length > 160) throw new Error('size');
  if (/^\s*---|%%\{|^\s*(?:click|style|classDef|linkStyle)\b|<|https?:|data:/im.test(source)) throw new Error('mermaid');
  if (!/^\s*(?:flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|mindmap|timeline)\b/.test(source)) throw new Error('mermaid');
}
