// Shared vocabulary for what a dose event means on screen.
//
// The design shows a coloured dot beside each person. It used to read
// "All Good" / "Needs Care" / "Critical", which is a claim about someone's
// health that Gamira has no basis to make: the backend stores whether a dose
// was confirmed, not whether a person is well. These labels say only what was
// actually recorded.

/** Dose statuses that still need someone to act. */
export const OPEN_DOSE_STATUSES = ['due', 'reminded', 'late'];

export const CARE_STATUS = {
  missed: { label: 'Dose missed', dot: 'bg-destructive', pill: 'bg-destructive/10 text-destructive', ring: 'ring-destructive' },
  late: { label: 'Dose late', dot: 'bg-amber-500', pill: 'bg-amber-500/10 text-amber-500', ring: 'ring-warning' },
  on_track: { label: 'On track', dot: 'bg-success', pill: 'bg-success/10 text-success', ring: 'ring-success' },
  none: { label: 'No doses', dot: 'bg-muted-foreground/40', pill: 'bg-muted text-muted-foreground', ring: 'ring-primary' },
};

/**
 * Reduce one person's dose events to a single status.
 *
 * @param {Array<{status: string}>} doses
 * @returns {'missed' | 'late' | 'on_track' | 'none'}
 */
export function careStatusFor(doses = []) {
  if (!doses.length) return 'none';
  if (doses.some((dose) => dose.status === 'missed')) return 'missed';
  if (doses.some((dose) => dose.status === 'late')) return 'late';
  return 'on_track';
}

export function careStatusMeta(key) {
  return CARE_STATUS[key] || CARE_STATUS.none;
}

/** First letter of a name, for avatars where no photo has been uploaded. */
export function initialOf(name) {
  return String(name || '?').trim().charAt(0).toUpperCase() || '?';
}
