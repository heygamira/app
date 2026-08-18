// Ordering a day by the clock.
//
// The same helper as the Parent App's `src/lib/schedule.js`, kept in step by
// hand because the two apps do not share a package. If you change one, change
// the other: a family looking at the dashboard and the person looking at their
// own phone must see the same day in the same order.

/**
 * `HH:MM`, zero-padded, for comparison.
 *
 * The backend stores times padded already, so this is belt and braces — but an
 * unpadded "9:00" sorts *after* "11:00" as a string, and that is a silently
 * wrong order rather than an error.
 */
export function sortableTime(localTime) {
  if (!localTime) return "99:99"; // no time: last, deterministically
  const [rawHours, rawMinutes = "0"] = String(localTime).split(":");
  const hours = Number(rawHours);
  const minutes = Number(rawMinutes);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return "99:99";
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/** Order by time, then stably, so equal times do not reshuffle on every poll. */
export function byLocalTime(getTime) {
  return (a, b) => sortableTime(getTime(a)).localeCompare(sortableTime(getTime(b)));
}
