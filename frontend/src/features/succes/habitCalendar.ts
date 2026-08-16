import type { SuccesHabit } from './types';

export type HabitDayCellState =
  | 'before-start'
  | 'after-end'
  | 'future'
  | 'future-off'
  | 'today-pending'
  | 'today-done'
  | 'today-off'
  | 'missed'
  | 'off-past'
  | 'past-done';

export function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function parseLocalIso(iso: string) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export function daysInMonth(year: number, monthIndex: number) {
  return new Date(year, monthIndex + 1, 0).getDate();
}

export function isLeapYear(year: number) {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

export function daysInYear(year: number) {
  return isLeapYear(year) ? 366 : 365;
}

/** Sunday=0 … Saturday=6 — matches backend `_sunday_weekday`. */
export function sundayWeekday(iso: string) {
  return parseLocalIso(iso).getDay();
}

export function isLastWeekdayOccurrence(iso: string) {
  const value = parseLocalIso(iso);
  const next = new Date(value);
  next.setDate(value.getDate() + 7);
  return next.getMonth() !== value.getMonth();
}

export function habitTrackingStart(habit: Pick<SuccesHabit, 'startDate' | 'createdAt'>) {
  if (habit.startDate && /^\d{4}-\d{2}-\d{2}/.test(habit.startDate)) {
    return habit.startDate.slice(0, 10);
  }
  if (habit.createdAt && /^\d{4}-\d{2}-\d{2}/.test(habit.createdAt)) {
    return habit.createdAt.slice(0, 10);
  }
  return localIsoDate();
}

export function habitTrackingEnd(habit: Pick<SuccesHabit, 'endDate'>) {
  if (habit.endDate && /^\d{4}-\d{2}-\d{2}/.test(habit.endDate)) {
    return habit.endDate.slice(0, 10);
  }
  return '';
}

export function isHabitDueOnDate(
  habit: Pick<SuccesHabit, 'frequency' | 'weeklyDays' | 'monthWeekSlots' | 'monthWeekDay' | 'startDate' | 'endDate' | 'createdAt'>,
  iso: string,
) {
  const start = habitTrackingStart(habit);
  const end = habitTrackingEnd(habit);
  if (iso < start) return false;
  if (end && iso > end) return false;

  if (habit.frequency === 'daily') return true;

  const weekday = sundayWeekday(iso);
  if (habit.frequency === 'weekly') {
    const days = habit.weeklyDays ?? [];
    return !days.length || days.includes(weekday);
  }

  const slots = habit.monthWeekSlots ?? [];
  if (weekday !== (habit.monthWeekDay ?? 1) || !slots.length) return false;
  const day = parseLocalIso(iso).getDate();
  const occurrence = Math.floor((day - 1) / 7) + 1;
  return slots.includes(occurrence) || (slots.includes('last') && isLastWeekdayOccurrence(iso));
}

export function habitLogKey(habitId: string, iso: string) {
  return `${habitId}_${iso}`;
}

export function habitDayCellState(
  habit: SuccesHabit,
  iso: string,
  logs: Record<string, boolean>,
  todayIso: string,
): HabitDayCellState {
  const start = habitTrackingStart(habit);
  const end = habitTrackingEnd(habit);
  const done = !!logs[habitLogKey(habit.id, iso)];
  if (iso < start) return 'before-start';
  if (end && iso > end) return 'after-end';
  const due = isHabitDueOnDate(habit, iso);

  if (iso > todayIso) return due ? 'future' : 'future-off';
  if (iso === todayIso) {
    if (!due) return done ? 'today-done' : 'today-off';
    return done ? 'today-done' : 'today-pending';
  }
  if (!due) return done ? 'past-done' : 'off-past';
  return done ? 'past-done' : 'missed';
}

export function cellIsToggleable(state: HabitDayCellState) {
  return (
    state === 'today-pending' ||
    state === 'today-done' ||
    state === 'today-off' ||
    state === 'missed' ||
    state === 'off-past' ||
    state === 'past-done'
  );
}

/** GitHub-style year grid: columns = weeks (Mon→Sun), cells = days. */
export function buildYearWeeks(year: number): Date[][] {
  const total = daysInYear(year);
  const days: Date[] = [];
  for (let i = 0; i < total; i += 1) {
    days.push(new Date(year, 0, 1 + i));
  }
  const weeks: Date[][] = [];
  let current: Date[] = [];
  for (const day of days) {
    const mondayBased = (day.getDay() + 6) % 7;
    if (mondayBased === 0 && current.length > 0) {
      weeks.push(current);
      current = [day];
    } else {
      current.push(day);
    }
  }
  if (current.length) weeks.push(current);
  return weeks;
}

export function annualLevel(count: number, habitTotal: number) {
  if (count <= 0 || habitTotal <= 0) return 0;
  if (count >= habitTotal) return 4;
  if (count >= 2) return 3;
  return 2;
}
