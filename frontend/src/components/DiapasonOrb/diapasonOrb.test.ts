import { describe, expect, it } from 'vitest';

import {
  DIAPASON_ORB_CONFIG,
  MEMBRANES,
  MEMBRANE_GRID,
  ORB_STATE_PROFILES,
} from './config';
import { MEMBRANE_FRAGMENT, MEMBRANE_VERTEX } from './shaders';

describe('Diapason physical body', () => {
  it('uses enough independently oriented veils to read as a volume', () => {
    expect(MEMBRANES).toHaveLength(5);
    expect(new Set(MEMBRANES.map((veil) => veil.rotation.join(','))).size).toBe(5);
    for (const veil of MEMBRANES) {
      expect(veil.width).toBeGreaterThan(0.5);
      expect(veil.foldAmplitude).toBeGreaterThan(0.2);
      expect(veil.turns).toBeGreaterThan(0.5);
    }
  });

  it('keeps every adaptive tier inside the intended GPU budget', () => {
    const totals = Object.values(MEMBRANE_GRID).map(
      ({ u, v }) => u * v * MEMBRANES.length,
    );
    expect(totals).toEqual([...totals].sort((a, b) => b - a));
    expect(Math.min(...totals)).toBeGreaterThan(12_000);
    expect(Math.max(...totals)).toBeLessThan(80_000);
  });

  it('keeps the energy core smaller than the surrounding body', () => {
    expect(DIAPASON_ORB_CONFIG.core.radius).toBeLessThan(0.2);
    expect(DIAPASON_ORB_CONFIG.core.haloScale).toBeLessThan(0.75);
  });

  it('does not wash active states into a white bloom', () => {
    for (const profile of Object.values(ORB_STATE_PROFILES)) {
      expect(profile.glow).toBeLessThanOrEqual(1.05);
      expect(profile.coreActivity).toBeLessThanOrEqual(1);
    }
  });

  it('contains the cool, gold and rose currents from the reference', () => {
    const shader = `${MEMBRANE_VERTEX}\n${MEMBRANE_FRAGMENT}`;
    expect(shader).toContain('CYAN');
    expect(shader).toContain('GOLD');
    expect(shader).toContain('ROSE');
    expect(shader).toContain('ribbonCenter');
    expect(shader).toContain('foldPhase');
  });
});
