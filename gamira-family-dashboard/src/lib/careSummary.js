// Deterministic care summaries.
//
// Every line below is counted from records the backend returned. Nothing is
// inferred, predicted or phrased as advice: a summary that a family acts on
// must be reproducible from the data, and a language model is not needed to
// count doses. AI narration is a later phase and will sit on top of these same
// figures rather than replace them.

const DISCLAIMER =
  'Counted directly from recorded data. Gamira does not interpret these figures or give medical advice.';

function withinDays(value, days) {
  if (!value) return false;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return false;
  return Date.now() - at.getTime() <= days * 24 * 60 * 60 * 1000;
}

export function buildCareSummary({ member, meds = [], records = [], events = [], days = 7 }) {
  const recent = events.filter((event) => withinDays(event.created_date, days));
  const taken = recent.filter((event) => event.type === 'medication_taken').length;
  const skipped = recent.filter((event) => event.type === 'medication_skipped').length;
  const missed = recent.filter((event) => event.type === 'medication_missed').length;
  const activeMeds = meds.filter((med) => med.status === 'active');

  const lines = [];
  const who = member?.name || 'This person';

  lines.push(
    activeMeds.length
      ? `${who} has ${activeMeds.length} active ${
          activeMeds.length === 1 ? 'medicine' : 'medicines'
        }: ${activeMeds.map((med) => med.name).join(', ')}.`
      : `${who} has no active medicines recorded.`
  );

  if (taken || skipped || missed) {
    const parts = [];
    if (taken) parts.push(`${taken} confirmed`);
    if (skipped) parts.push(`${skipped} skipped`);
    if (missed) parts.push(`${missed} missed`);
    lines.push(`Over the last ${days} days: ${parts.join(', ')}.`);
  } else {
    lines.push(`No doses were recorded in the last ${days} days.`);
  }

  const latest = new Map();
  for (const reading of records) {
    const seen = latest.get(reading.metric);
    if (!seen || new Date(reading.recorded_at) > new Date(seen.recorded_at)) {
      latest.set(reading.metric, reading);
    }
  }
  if (latest.size) {
    lines.push(
      `Most recent readings: ${[...latest.values()]
        .map((reading) => `${reading.label} ${reading.value} ${reading.unit}`)
        .join(', ')}.`
    );
  } else {
    lines.push('No health readings have been recorded yet.');
  }

  if (member?.conditions?.length) {
    lines.push(`Recorded conditions: ${member.conditions.join(', ')}.`);
  }
  if (member?.allergies?.length) {
    lines.push(`Recorded allergies: ${member.allergies.join(', ')}.`);
  }

  return { lines, disclaimer: DISCLAIMER, counts: { taken, skipped, missed } };
}

export function buildFamilySummary({ members = [], meds = [], events = [], days = 7 }) {
  const recent = events.filter((event) => withinDays(event.created_date, days));
  const lines = [
    `${members.length} ${members.length === 1 ? 'person' : 'people'} in this family.`,
    `${meds.filter((med) => med.status === 'active').length} active medicines across the family.`,
  ];

  for (const member of members) {
    const forMember = recent.filter((event) => event.family_member_id === member.id);
    const taken = forMember.filter((event) => event.type === 'medication_taken').length;
    const missed = forMember.filter((event) => event.type === 'medication_missed').length;
    const skipped = forMember.filter((event) => event.type === 'medication_skipped').length;
    lines.push(
      `${member.name}: ${taken} confirmed, ${skipped} skipped, ${missed} missed in the last ${days} days.`
    );
  }

  return { lines, disclaimer: DISCLAIMER };
}
