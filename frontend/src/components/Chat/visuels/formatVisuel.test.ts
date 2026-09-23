import { describe, expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import type { Root } from 'mdast';
import { blocFerme, lireGraphique, remarkVisuels } from './formatVisuel';
import { nettoyerSvg, preparerMermaid, verifierMermaid, type PaletteVisuel } from './svgSur';

const palette: PaletteVisuel = { fond: '#fff', texte: '#111', accent: '#123456', bord: '#888', secondaire: '#444', police: 'sans-serif' };
const graphe = { title: 'Évolution', type: 'line', xKey: 'mois', series: [{ key: 'valeur', label: 'Valeur' }], data: [{ mois: 'Janvier', valeur: 12 }], sample: true };
const svg = (corps: string) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300">${corps}</svg>`;

describe('visuels conservés dans le Markdown de la discussion', () => {
  it('attend la clôture exacte même avec un flux reçu par petits fragments', () => {
    const texte = '````svg\n<svg/>\n```\n````';
    for (let i = 0; i < texte.length; i++) expect(blocFerme(texte.slice(0, i))).toBe(false);
    expect(blocFerme(texte)).toBe(true);
    expect(blocFerme('~~~mermaid\ngraph TD\n~~~')).toBe(true);
    expect(blocFerme('```svg\n<svg/>\n~~~')).toBe(false);
  });
  it('annote huit visuels, laisse les autres et le code ordinaire intacts', async () => {
    const texte = Array.from({ length: 9 }, () => '```svg\n<svg/>\n```').join('\n\n') + '\n\n```python\nprint(1)\n```';
    const processeur = unified().use(remarkParse).use(remarkVisuels);
    const arbre = await processeur.run(processeur.parse(texte), { value: texte }) as Root;
    expect(arbre.children.filter(n => n.data?.hProperties?.['data-visual-complete'] === 'yes')).toHaveLength(8);
    expect(arbre.children[8].data).toBeUndefined();
    expect(arbre.children[9].data).toBeUndefined();
    const partiel = '```mermaid\ngraph TD';
    const fin = await processeur.run(processeur.parse(partiel), { value: partiel }) as Root;
    expect(fin.children[0].data?.hProperties?.['data-visual-complete']).toBe('no');
  });
  it('garde les nombres reçus, sans arrondi ni série inventée', () => {
    expect(lireGraphique(JSON.stringify(graphe)).data).toEqual(graphe.data);
    expect(lireGraphique(JSON.stringify(graphe)).sample).toBe(true);
    expect(lireGraphique(JSON.stringify({ ...graphe, sample: false })).source).toBeUndefined();
  });
  it.each([
    { data: [{ mois: 'Janvier', valeur: '12' }] },
    { data: [{ mois: 'Janvier', valeur: null }] },
    { data: [{ mois: 'Janvier', valeur: 1e30 }] },
    { data: Array.from({ length: 301 }, () => graphe.data[0]) },
    { series: [{ key: '__proto__', label: 'Non' }] },
    { series: [graphe.series[0], graphe.series[0]] },
    { type: 'pie', data: [{ mois: 'Janvier', valeur: -1 }] },
    { type: 'pie', data: [{ mois: 'Janvier', valeur: 0 }] },
    { type: 'javascript' },
  ])('refuse un graphique invalide (cas %#)', changement => {
    expect(() => lireGraphique(JSON.stringify({ ...graphe, ...changement }))).toThrow();
  });
});

describe('dessins isolés, sans code ni ressource distante du modèle', () => {
  it('conserve les formes, les renvois locaux et les couleurs du thème', () => {
    const r = nettoyerSvg(svg('<title>Titre</title><defs><linearGradient id="g"><stop stop-color="var(--color-accent)"/></linearGradient></defs><rect width="50" height="50" fill="url(#g)"/><text fill="var(--color-text)">bonjour</text>'), palette);
    expect(r.svg).toContain('#123456');
    expect(r.svg).toContain('url(#g)');
    expect(r.svg).toContain('#111');
    expect(r.title).toBe('Titre');
    expect(r.width).toBe(600);
  });
  it('conserve les couleurs du moteur en retirant ses animations internes', () => {
    const r = nettoyerSvg(svg('<style>@keyframes dash { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } } .node { fill: #123456; }</style><rect class="node" style="stroke:#654321"/>'), palette, true);
    expect(r.svg).toContain('.node { fill: #123456; }');
    expect(r.svg).toContain('stroke="rgb(101, 67, 33)"');
    expect(r.svg).not.toContain('@keyframes');
  });
  it('retire scripts, événements, HTML, images et liens externes', () => {
    const r = nettoyerSvg(svg('<script>alert(1)</script><foreignObject><div>HTML</div></foreignObject><image href="https://example.com/x"/><use href="https://example.com/x#y"/><rect onload="alert(2)" style="fill:red" fill="url(https://example.com/x)"/>'), palette);
    expect(r.svg).not.toMatch(/script|onload|foreignObject|https:|style=/);
    expect(r.svg).toContain('<rect');
  });
  it.each(['<!DOCTYPE svg><svg/>', '<svg>', '<svg viewBox="0 0 0 2"/>', '<svg viewBox="0 0 100000 2"/>'])('refuse les documents invalides : %s', s => {
    expect(() => nettoyerSvg(s, palette)).toThrow();
  });
  it.each(['---\nconfig:\n---\ngraph TD', '%%{init: {}}%%\ngraph TD', 'graph TD\nclick A "https://example.com"', 'graph TD\nA[<img src=x>]', 'graph TD\nclassDef secret fill:red', 'graph TD\n' + 'A-->B\n'.repeat(161)])('refuse une configuration Mermaid fournie par le modèle', s => {
    expect(() => verifierMermaid(s)).toThrow();
  });
  it('accepte les diagrammes déclaratifs', () => {
    expect(() => verifierMermaid('flowchart LR\nA[Idée] --> B[Projet]')).not.toThrow();
    expect(() => verifierMermaid('sequenceDiagram\nAlice->>Bob: Bonjour')).not.toThrow();
  });
  it('adapte la sortie réelle de Qwen au thème sans perdre ses liens', () => {
    const brut = 'flowchart LR\nA((Idée)) --> B(Projet)\nB --> C(Résultat)\nstyle A fill:#e1f5fe,stroke:#01579b,stroke-width:2px\nstyle B fill:red; B --> D[Suite]\nclassDef exemple fill:blue;';
    const adapte = preparerMermaid(brut);
    expect(adapte).not.toMatch(/style|classDef|fill:/);
    expect(adapte).toContain('A((Idée)) --> B(Projet)');
    expect(adapte).toContain('B --> C(Résultat)');
    expect(adapte).toContain('B --> D[Suite]');
  });
});
