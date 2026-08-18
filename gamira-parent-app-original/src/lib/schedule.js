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
