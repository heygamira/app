// One day, in the order it actually happens.
//
// Doses and routines are two tables and two API calls, and every screen that
// showed them kept them as two lists sorted separately. On screen that reads as
// a schedule that is not in order: a 09:00 routine sitting below a 20:00 dose,
// because it was in the second list rather than later in the day.
//
// Sorting is on the stored `HH:MM`, not on anything shown. The displayed time
// is 12-hour ("9:00 AM"), and sorting that as text puts 11 AM before 9 AM and
// every PM hour among the AMs.

/**
 * `HH:MM`, zero-padded, for comparison.
 *
 * The backend stores times padded already, so this is belt and braces rather
 * than a fix — but an unpadded "9:00" sorts *after* "11:00" as a string, and
 * that is a silent wrong order rather than an error, so it is worth not
 * depending on every writer getting it right forever.
 */
export function sortableTime(localTime) {
  if (!localTime) return '99:99'; // no time: last, deterministically
  const [rawHours, rawMinutes = '0'] = String(localTime).split(':');
  const hours = Number(rawHours);
  const minutes = Number(rawMinutes);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return '99:99';
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

/**
 * Order two schedule rows: by time, then stably.
 *
 * The tiebreak matters. Several things commonly share a time — two tablets at
 * 08:00, a routine at the same hour — and without one, React reorders them on
 * every poll and the list flickers under the person reading it.
 */
export function compareScheduleRows(a, b) {
  const byTime = sortableTime(a.localTime).localeCompare(sortableTime(b.localTime));
  if (byTime !== 0) return byTime;
  // Medicine first at the same minute: it is the one with a consequence.
  if (a.kind !== b.kind) return a.kind === 'dose' ? -1 : 1;
  return String(a.title || '').localeCompare(String(b.title || ''));
}

/**
 * Merge doses and reminders into one ordered day.
 *
 * @param {Array<object>} doses      dose events, with `scheduled_local_time`
 * @param {Array<object>} reminders  reminders, with `local_time`
 * @param {object} options
 * @param {(dose: object) => object} options.doseRow      shape one dose for the screen
 * @param {(reminder: object) => object} options.reminderRow
 * @param {(reminder: object) => boolean} [options.includeReminder]
 * @returns {Array<object>} rows carrying at least `{ kind, localTime, title }`
 */
export function mergeSchedule(doses, reminders, options) {
  const {
    doseRow,
    reminderRow,
    includeReminder = (reminder) => reminder.status === 'active',
  } = options;
  const rows = [
    ...doses.map((dose) => ({
      kind: 'dose',
      localTime: dose.scheduled_local_time,
      ...doseRow(dose),
    })),
    ...reminders.filter(includeReminder).map((reminder) => ({
      kind: 'reminder',
      localTime: reminder.local_time || '',
      ...reminderRow(reminder),
    })),
  ];
  return rows.sort(compareScheduleRows);
}

/**
 * Minutes from now until a local `HH:MM`; negative once it has passed, `null`
 * when there is nothing to compare (no time at all).
 *
 * `timezone` is the senior's own, which is the authority — comparing against
 * the browser's clock means a device set to the wrong place, or one that has
 * travelled, silently shifts every "next up" and every ago/until label.
 */
export function minutesUntil(localTime, timezone, now = new Date()) {
  if (!localTime) return null;
  const [hours, minutes] = String(localTime).split(':').map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null;

  let hour = now.getHours();
  let minute = now.getMinutes();
  if (timezone) {
    try {
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: timezone,
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).formatToParts(now);
      const value = (type) => Number(parts.find((part) => part.type === type)?.value ?? 0);
      hour = value('hour') % 24;
      minute = value('minute');
    } catch {
      // An unknown timezone is not a reason to stop showing a schedule.
    }
  }
  return hours * 60 + minutes - (hour * 60 + minute);
}

/**
 * Today's rows, in the order the day is actually still happening: whatever is
 * next first, soonest to furthest out — then, only after everything still
 * ahead, whatever has already gone by. A row that is both past and marked
 * done is dropped rather than ordered at all: it happened, and does not need
 * to keep sitting at the top of somebody's day once it has.
 *
 * A dose gone quietly past with nothing recorded (missed, not taken) is kept
 * — it is still the one thing most worth noticing — so only `done` rows are
 * ever removed, never merely-late ones.
 */
export function orderTodaySchedule(rows, timezone, now = new Date()) {
  const dated = rows
    .map((row) => ({ row, delta: minutesUntil(row.localTime, timezone, now) }))
    .filter(({ row, delta }) => !(row.done && delta !== null && delta < 0));

  const upcoming = dated.filter(({ delta }) => delta === null || delta >= 0);
  const past = dated.filter(({ delta }) => delta !== null && delta < 0);

  upcoming.sort((a, b) => (a.delta ?? Infinity) - (b.delta ?? Infinity) || compareScheduleRows(a.row, b.row));
  past.sort((a, b) => compareScheduleRows(a.row, b.row));

  return [...upcoming, ...past].map(({ row }) => row);
}
