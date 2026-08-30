import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const invoke = vi.hoisted(() => vi.fn());
vi.mock('@tauri-apps/api/core', () => ({ invoke }));

import { appliquerPointeur } from './pointeurNatif';

beforeEach(() => {
  vi.stubGlobal('window', {});
  invoke.mockReset();
  delete window.__TAURI_INTERNALS__;
});

afterEach(() => vi.unstubAllGlobals());

describe('le pont natif du pointeur', () => {
  it('ne dépense aucun appel quand la main ne commande rien', async () => {
    await appliquerPointeur({ active: false, action: 'MOVE', x: 0.2, y: 0.3 });
    await appliquerPointeur({ active: true, action: 'NONE' });
    expect(invoke).not.toHaveBeenCalled();
  });

  it('suit quand même le curseur pendant un NONE avec coordonnées', async () => {
    Object.assign(window, { __TAURI_INTERNALS__: {} });
    await appliquerPointeur({
      active: true,
      action: 'NONE',
      x: 0.4,
      y: 0.5,
    });
    expect(invoke).toHaveBeenCalledWith('apply_pointer_event', {
      event: {
        active: true,
        action: 'MOVE',
        x: 0.4,
        y: 0.5,
      },
    });
  });

  it('refuse de promettre un curseur dans le navigateur', async () => {
    await expect(
      appliquerPointeur({ active: true, action: 'CLICK', x: 0.2, y: 0.3 }),
    ).rejects.toThrow('application de bureau');
  });

  it('transmet intacte la commande confirmée au paquet Tauri', async () => {
    Object.assign(window, { __TAURI_INTERNALS__: {} });
    invoke.mockResolvedValue(undefined);
    const lecture = {
      active: true,
      action: 'SCROLL' as const,
      x: 0.2,
      y: 0.3,
      scrollY: -4,
      pinching: true,
    };
    await appliquerPointeur(lecture);
    expect(invoke).toHaveBeenCalledWith('apply_pointer_event', {
      event: lecture,
    });
  });
});
