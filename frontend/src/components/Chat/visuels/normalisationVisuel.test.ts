import { describe, expect, it } from 'vitest';
import { nettoyerJsonVisuel, reconnaitreVisuel } from './formatVisuel';

describe('Réparer le format sans inventer de données', () => {
  it('reconnaît le json réellement renvoyé par Qwen', () => {
    const texte = '{"title":"Mesures","type":"scatter","series":[{"name":"A","x":[1,2,3],"y":[2,4,5]}],"sample":false}';
    expect(reconnaitreVisuel('json', texte)).toEqual({ genre: 'diapason-plotly', source: texte });
  });
  it('n’interprète pas un programme ou des données ordinaires comme une figure', () => {
    expect(reconnaitreVisuel('python', 'print(1)')).toBeNull();
    expect(reconnaitreVisuel('json', '{"type":"scatter","series":[1]}')).toBeNull();
    expect(reconnaitreVisuel('json', '{"nom":"A","age":12}')).toBeNull();
  });
  it('enlève seulement les virgules finales hors chaînes', () => {
    const source = '{"title":"a,} \\" b","x":[1,-2.5,3e4,],}';
    expect(JSON.parse(nettoyerJsonVisuel(source))).toEqual({ title: 'a,} " b', x: [1, -2.5, 30000] });
  });
  it('ne complète jamais une liste tronquée ou une mesure manquante', () => {
    const source = '{"x":[1,2,';
    expect(nettoyerJsonVisuel(source)).toBe(source);
    expect(reconnaitreVisuel('json', source)).toBeNull();
  });
  it('reconnaît les alias et réserve les matrices au moteur vectoriel', () => {
    expect(reconnaitreVisuel('PLOTLY', '{}')?.genre).toBe('diapason-plotly');
    expect(reconnaitreVisuel('xml', '<svg viewBox="0 0 10 10"/>')?.genre).toBe('svg');
    expect(reconnaitreVisuel('json', '{"title":"M","type":"heatmap","matrix":[[1,2]]}')?.genre).toBe('diapason-matplotlib');
  });
});
