import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from '@tauri-apps/plugin-notification';

import { isTauri } from '../../lib/api';
import { listSuccesHabits } from './api';
import { localIsoDate } from './habitCalendar';
import type { SuccesHabit } from './types';

const FIRED_STORAGE_KEY = 'diapason-succes-habit-reminder-fired';
const HOURLY_START = 10;
const HOURLY_END = 23;
const POLL_MS = 60_000;

type ReminderSlot = { hour: number; minute: number; slotId: string };

type FiredMap = Record<string, string>;

let timerIds: number[] = [];
let pollId: number | null = null;
let started = false;
let syncing: Promise<void> | null = null;
let pendingResync = false;

function parseHm(raw: string | null | undefined): { hour: number; minute: number } | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec((raw ?? '').trim());
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return null;
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return { hour, minute };
}

function reminderSlots(habit: Pick<SuccesHabit, 'reminderTime'>): ReminderSlot[] {
  const explicit = parseHm(habit.reminderTime);
  if (explicit) {
    return [
      {
        hour: explicit.hour,
        minute: explicit.minute,
        slotId: `${explicit.hour}:${String(explicit.minute).padStart(2, '0')}`,
      },
    ];
  }
  const slots: ReminderSlot[] = [];
  for (let hour = HOURLY_START; hour <= HOURLY_END; hour += 1) {
    slots.push({ hour, minute: 0, slotId: `h${hour}` });
  }
  return slots;
}

function fireKey(habitId: string, date: string, slotId: string) {
  return `${habitId}|${date}|${slotId}`;
}

function loadFired(): FiredMap {
  try {
    const raw = localStorage.getItem(FIRED_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as FiredMap;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function saveFired(map: FiredMap) {
  try {
    localStorage.setItem(FIRED_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // ignore quota / private mode
  }
}

function pruneFired(map: FiredMap, keepDate: string): FiredMap {
  const next: FiredMap = {};
  for (const [key, date] of Object.entries(map)) {
    if (date === keepDate) next[key] = date;
  }
  return next;
}

function clearTimers() {
  for (const id of timerIds) window.clearTimeout(id);
  timerIds = [];
}

function slotDate(date: string, hour: number, minute: number): Date {
  const [y, m, d] = date.split('-').map(Number);
  return new Date(y, m - 1, d, hour, minute, 0, 0);
}

function notificationCopy(habit: SuccesHabit, hour: number): { title: string; body: string } {
  const icon = habit.icon?.trim() || '✨';
  const name = habit.name.trim() || 'Habitude';
  const hourLabel = `${String(hour).padStart(2, '0')}h`;
  return {
    title: `${icon} ${name}`,
    body: `Rappel ${hourLabel} — cochez-la dans Succès tant que Diapason est ouvert.`,
  };
}

export async function ensureHabitReminderPermission(): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === 'granted';
    }
    return granted;
  } catch {
    return false;
  }
}

async function fireNotification(habit: SuccesHabit, slot: ReminderSlot) {
  const granted = await ensureHabitReminderPermission();
  if (!granted) return;
  const copy = notificationCopy(habit, slot.hour);
  try {
    sendNotification({ title: copy.title, body: copy.body });
  } catch {
    // plugin may throw if the OS blocks delivery
  }
}

function scheduleTimeout(delayMs: number, fn: () => void) {
  const id = window.setTimeout(fn, delayMs);
  timerIds.push(id);
}

/**
 * Recompute today's habit reminder timers and catch-up notifications.
 * Desktop Tauri only delivers immediate notifications, so we schedule in-process.
 */
export async function resyncHabitReminders(): Promise<void> {
  if (!isTauri()) return;
  if (syncing) {
    pendingResync = true;
    return syncing;
  }

  syncing = (async () => {
    clearTimers();
    const today = localIsoDate();
    let fired = pruneFired(loadFired(), today);
    saveFired(fired);

    const granted = await ensureHabitReminderPermission();
    if (!granted) return;

    let habits: SuccesHabit[];
    try {
      habits = await listSuccesHabits(today);
    } catch {
      return;
    }

    const now = Date.now();

    for (const habit of habits) {
      if (!habit.due || habit.done) continue;
      const slots = reminderSlots(habit);
      if (!slots.length) continue;

      let latestPast: ReminderSlot | null = null;
      for (const slot of slots) {
        const when = slotDate(today, slot.hour, slot.minute);
        if (when.getTime() <= now) latestPast = slot;
      }

      for (const slot of slots) {
        const key = fireKey(habit.id, today, slot.slotId);
        if (fired[key]) continue;

        const when = slotDate(today, slot.hour, slot.minute);
        const at = when.getTime();

        if (at > now) {
          const delay = at - now;
          scheduleTimeout(delay, () => {
            void (async () => {
              const current = pruneFired(loadFired(), localIsoDate());
              if (current[key]) return;
              try {
                const fresh = await listSuccesHabits(localIsoDate());
                const live = fresh.find((item) => item.id === habit.id);
                if (!live || !live.due || live.done) {
                  current[key] = today;
                  saveFired(current);
                  return;
                }
                await fireNotification(live, slot);
              } catch {
                await fireNotification(habit, slot);
              }
              current[key] = today;
              saveFired(current);
            })();
          });
          continue;
        }

        // Past slot: catch-up only the latest one; silence older hourly slots.
        if (latestPast && slot.slotId === latestPast.slotId) {
          await fireNotification(habit, slot);
        }
        fired[key] = today;
      }
    }

    saveFired(fired);
  })().finally(() => {
    syncing = null;
    if (pendingResync) {
      pendingResync = false;
      void resyncHabitReminders();
    }
  });

  return syncing;
}

export function startHabitReminderScheduler() {
  if (!isTauri() || started) return;
  started = true;
  void resyncHabitReminders();
  pollId = window.setInterval(() => {
    void resyncHabitReminders();
  }, POLL_MS);

  const onFocus = () => {
    void resyncHabitReminders();
  };
  window.addEventListener('focus', onFocus);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') onFocus();
  });
}

export function stopHabitReminderScheduler() {
  started = false;
  clearTimers();
  if (pollId != null) {
    window.clearInterval(pollId);
    pollId = null;
  }
}
