import { describe, expect, it } from 'vitest';

import { etiquetteDuModele, modeleDeLaReponse } from './modeleDeLaReponse';

describe('le modèle affiché sous une réponse', () => {
  it('prend le modèle écrit par le serveur, pas celui du sélecteur', () => {
    // 20/09/2026 : « qwen3.8:27b-mlx » s'affichait alors que le 9b avait répondu.
    expect(modeleDeLaReponse('qwen3.8:27b-mlx', 'qwen3.5:9b', undefined)).toEqual({
      model_id: 'qwen3.5:9b',
    });
  });

  it('garde le sélecteur quand le serveur ne dit rien (erreur avant le premier fragment)', () => {
    expect(modeleDeLaReponse('qwen3.8:27b-mlx', undefined, undefined)).toEqual({
      model_id: 'qwen3.8:27b-mlx',
    });
    expect(modeleDeLaReponse('qwen3.8:27b-mlx', '  ', undefined).model_id).toBe(
      'qwen3.8:27b-mlx',
    );
  });

  it('n’attribue aucun modèle à la voie éclair, même si ses fragments en portent un', () => {
    // Les fragments éclair reprennent le modèle du sélecteur (forme OpenAI) ;
    // aucun modèle n'a répondu, donc aucun ne doit être affiché.
    expect(modeleDeLaReponse('qwen3.8:27b-mlx', 'qwen3.8:27b-mlx', undefined, true)).toEqual({});
    expect(etiquetteDuModele(modeleDeLaReponse('x', 'x', undefined, true))).toBe('');
  });

  it('nomme l’origine seulement quand un tour a vraiment été rerouté', () => {
    expect(
      modeleDeLaReponse('qwen3.8:27b-mlx', 'qwen3.5:9b', {
        model: 'qwen3.5:9b',
        from: 'qwen3.8:27b-mlx',
        reason: 'tour léger',
      }),
    ).toEqual({ model_id: 'qwen3.5:9b', routed_from: 'qwen3.8:27b-mlx' });
    expect(
      modeleDeLaReponse('qwen3.5:9b', 'qwen3.5:9b', { from: 'qwen3.5:9b' }).routed_from,
      'un faux « rerouté » vers lui-même ne s’affiche pas',
    ).toBeUndefined();
    expect(modeleDeLaReponse('x', 'x', { from: null }).routed_from).toBeUndefined();
  });

  it('écrit « léger ← lourd » dans le résumé, le modèle seul sinon', () => {
    expect(etiquetteDuModele({ model_id: 'qwen3.5:9b', routed_from: 'qwen3.8:27b-mlx' })).toBe(
      'qwen3.5:9b ← qwen3.8:27b-mlx',
    );
    expect(etiquetteDuModele({ model_id: 'qwen3.5:9b' })).toBe('qwen3.5:9b');
    expect(etiquetteDuModele({})).toBe('');
  });
});
