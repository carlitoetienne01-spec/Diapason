// @vitest-environment node
//
// Le lien du manifeste porte le cookie de session (plan mobile, point 4 de
// « Ce qui reste de la phase 2 » — 26/09/2026). Servi par la passerelle du
// tailnet, `/manifest.webmanifest` est une route `session` : demandé sans
// cookie, il rend 401. On lit ce que le vrai plugin injectera dans
// index.html, à partir de la vraie configuration de Vite.

import { join } from 'node:path';

import { resolveConfig } from 'vite';
import { describe, expect, it } from 'vitest';

type ApiPwa = { webManifestData: () => { toLinkTag: () => string } | undefined };

describe('Le manifeste est demandé avec le cookie de session', () => {
  it('le lien injecté porte crossorigin="use-credentials"', async () => {
    const config = await resolveConfig(
      { configFile: join(process.cwd(), 'vite.config.ts'), logLevel: 'silent' },
      'build',
      'production',
    );
    const pwa = config.plugins.find((p) => p.name === 'vite-plugin-pwa') as { api?: ApiPwa } | undefined;
    expect(pwa?.api, 'le plugin PWA doit être chargé pour la construction servie par le serveur').toBeTruthy();
    const lien = pwa!.api!.webManifestData()?.toLinkTag() ?? '';
    expect(lien, 'sans cet attribut, la passerelle répond 401 au manifeste').toContain(
      'crossorigin="use-credentials"',
    );
  }, 30_000);
});
