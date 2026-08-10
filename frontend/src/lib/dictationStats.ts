/** Local dictation usage stats (Diapason-inspired polish). */

const STORAGE_KEY = 'openjarvis.dictation.stats';

export type DictationStats = {
  sessions: number;
  characters: number;
  lastAt: string | null;
};

export function loadDictationStats(): DictationStats {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { sessions: 0, characters: 0, lastAt: null };
    const parsed = JSON.parse(raw) as DictationStats;
    return {
      sessions: Number(parsed.sessions) || 0,
      characters: Number(parsed.characters) || 0,
      lastAt: parsed.lastAt ?? null,
    };
  } catch {
    return { sessions: 0, characters: 0, lastAt: null };
  }
}

export function recordDictationStat(charCount: number): DictationStats {
  const prev = loadDictationStats();
  const next: DictationStats = {
    sessions: prev.sessions + 1,
    characters: prev.characters + Math.max(0, charCount),
    lastAt: new Date().toISOString(),
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore quota
  }
  return next;
}
