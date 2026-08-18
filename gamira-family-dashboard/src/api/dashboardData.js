// Translation between the Gamira API and the shapes the dashboard screens use.
//
// The API calls a cared-for person a "senior profile"; the dashboard has always
// called them a "family member". Keeping that translation in one file means the
// screens do not each invent their own mapping, and renaming a field on either
// side is a single edit here.

import {
  appointments,
  doses,
  emergencyContacts,
  families,
  healthReadings,
  medications,
  reminders,
  seniors,
  timeline,
} from '@/api/gamiraClient';

// --------------------------------------------------------------------------
// Family members (senior profiles)
// --------------------------------------------------------------------------

// Age is derived here rather than stored: a stored age silently goes stale.
export function ageFrom(dateOfBirth) {
  if (!dateOfBirth) return null;
  const born = new Date(dateOfBirth);
  if (Number.isNaN(born.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - born.getFullYear();
  const monthDelta = now.getMonth() - born.getMonth();
  if (monthDelta < 0 || (monthDelta === 0 && now.getDate() < born.getDate())) age -= 1;
  return age >= 0 ? age : null;
}

export function toMember(senior) {
  return {
    id: senior.id,
    family_id: senior.family_id,
    name: senior.preferred_name,
    role: senior.relationship_label || '',
    photo_url: senior.avatar_url || '',
    phone: senior.phone || '',
    date_of_birth: senior.date_of_birth || '',
    age: ageFrom(senior.date_of_birth),
    gender: senior.gender || '',
    blood_group: senior.blood_group || '',
    conditions: senior.conditions || [],
    allergies: senior.allergies || [],
    notes: senior.notes || '',
    timezone: senior.timezone,
    language: senior.language,
    consent_status: senior.consent_status,
  };
}

function fromMember(member) {
  const payload = {};
  if (member.name !== undefined) payload.preferred_name = member.name;
  if (member.role !== undefined) payload.relationship_label = member.role;
  if (member.photo_url !== undefined) payload.avatar_url = member.photo_url || null;
  if (member.phone !== undefined) payload.phone = member.phone;
  if (member.date_of_birth) payload.date_of_birth = member.date_of_birth;
  if (member.gender !== undefined) payload.gender = member.gender;
  if (member.blood_group !== undefined) payload.blood_group = member.blood_group;
  if (member.conditions !== undefined) payload.conditions = member.conditions;
  if (member.allergies !== undefined) payload.allergies = member.allergies;
  if (member.notes !== undefined) payload.notes = member.notes;
  if (member.timezone) payload.timezone = member.timezone;
  if (member.language) payload.language = member.language;
  return payload;
}

export function splitList(value) {
  return String(value || '')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export const membersApi = {
  list: (familyId) => seniors.list(familyId).then((rows) => rows.map(toMember)),
  get: (memberId) => seniors.get(memberId).then(toMember),
  create: (familyId, member) =>
    seniors.create(familyId, fromMember(member)).then(toMember),
  update: (memberId, member) =>
    seniors.update(memberId, fromMember(member)).then(toMember),
  remove: (memberId) => seniors.archive(memberId),
};

// --------------------------------------------------------------------------
// Medicines
// --------------------------------------------------------------------------

function describeSchedules(schedules) {
  if (!schedules?.length) return 'No dose times set';
  const times = schedules.map((schedule) => schedule.local_time).sort();
  if (times.length === 1) return `Once daily at ${times[0]}`;
  return `${times.length} times daily: ${times.join(', ')}`;
}

export function toMedicine(medication, memberName) {
  return {
    id: medication.id,
    name: medication.name,
    dosage: medication.strength || '',
    form: medication.form || '',
    frequency: describeSchedules(medication.schedules),
    times: (medication.schedules || []).map((schedule) => schedule.local_time),
    schedules: medication.schedules || [],
    instructions: medication.instructions || '',
    prescriber: medication.prescriber || '',
    start_date: medication.start_date || '',
    end_date: medication.end_date || '',
    status: medication.status,
    family_member_id: medication.senior_profile_id,
    family_member_name: memberName || '',
    created_date: medication.created_at,
  };
}

export const medicinesApi = {
  list: (memberId, memberName) =>
    medications
      .list(memberId)
      .then((rows) => rows.map((row) => toMedicine(row, memberName))),

  // The dashboard shows every person at once, so one screen load fans out over
  // the visible members rather than asking the API for a cross-family list it
  // deliberately does not offer.
  listForMembers: async (members) => {
    const results = await Promise.all(
      members.map((member) =>
        medications
          .list(member.id)
          .then((rows) => rows.map((row) => toMedicine(row, member.name)))
          .catch(() => [])
      )
    );
    return results.flat();
  },

  get: (medicationId, memberName) =>
    medications.get(medicationId).then((row) => toMedicine(row, memberName)),

  create: (memberId, { name, dosage, form, instructions, prescriber, startDate, times }) =>
    medications
      .create(memberId, {
        name,
        strength: dosage || null,
        form: form || null,
        instructions: instructions || null,
        prescriber: prescriber || null,
        start_date: startDate || null,
        schedules: (times || []).map((time) => ({ local_time: time })),
      })
      .then((row) => toMedicine(row)),

  archive: (medicationId) => medications.archive(medicationId),
};

// --------------------------------------------------------------------------
// Doses
// --------------------------------------------------------------------------

export const dosesApi = {
  today: (memberId) => doses.list(memberId),
  markTaken: (doseEventId, note) => doses.markTaken(doseEventId, { note }),
  markSkipped: (doseEventId, note) => doses.markSkipped(doseEventId, { note }),

  listForMembers: async (members) => {
    const results = await Promise.all(
      members.map((member) =>
        doses
          .list(member.id)
          .then((rows) =>
            rows.map((row) => ({
              ...row,
              family_member_id: member.id,
              family_member_name: member.name,
            }))
          )
          .catch(() => [])
      )
    );
    return results.flat();
  },
};

// --------------------------------------------------------------------------
// Timeline
// --------------------------------------------------------------------------

export function toTimelineEvent(event, memberName) {
  return {
    id: event.id,
    type: event.type,
    title: event.title,
    description: event.description || '',
    family_member_id: event.senior_profile_id,
    family_member_name: memberName || '',
    created_date: event.occurred_at,
  };
}

export const timelineApi = {
  list: (memberId, memberName, options) =>
    timeline
      .list(memberId, options)
      .then((rows) => rows.map((row) => toTimelineEvent(row, memberName))),

  listForMembers: async (members, options) => {
    const results = await Promise.all(
      members.map((member) =>
        timeline
          .list(member.id, options)
          .then((rows) => rows.map((row) => toTimelineEvent(row, member.name)))
          .catch(() => [])
      )
    );
    return results
      .flat()
      .sort((a, b) => new Date(b.created_date).getTime() - new Date(a.created_date).getTime());
  },
};

// --------------------------------------------------------------------------
// Health readings
// --------------------------------------------------------------------------

// Unit and plausibility rules are enforced by the backend. This list keeps the
// form's options in step with what the API will accept.
export const HEALTH_METRICS = [
  { key: 'heart_rate', label: 'Heart rate', unit: 'bpm' },
  { key: 'blood_pressure_systolic', label: 'Blood pressure (systolic)', unit: 'mmHg' },
  { key: 'blood_pressure_diastolic', label: 'Blood pressure (diastolic)', unit: 'mmHg' },
  { key: 'oxygen_saturation', label: 'Oxygen saturation', unit: '%' },
  { key: 'blood_glucose', label: 'Blood glucose', unit: 'mg/dL' },
  { key: 'body_temperature', label: 'Body temperature', unit: 'C' },
  { key: 'weight', label: 'Weight', unit: 'kg' },
  { key: 'steps', label: 'Steps', unit: 'steps' },
  { key: 'sleep_duration', label: 'Sleep', unit: 'hours' },
];

export function metricLabel(metric) {
  return HEALTH_METRICS.find((entry) => entry.key === metric)?.label || metric;
}

export function metricUnit(metric) {
  return HEALTH_METRICS.find((entry) => entry.key === metric)?.unit || '';
}

export function toReading(reading, memberName) {
  return {
    id: reading.id,
    metric: reading.metric,
    label: metricLabel(reading.metric),
    value: reading.value,
    unit: reading.unit,
    source: reading.source,
    recorded_at: reading.measured_at,
    note: reading.note || '',
    family_member_id: reading.senior_profile_id,
    family_member_name: memberName || '',
  };
}

export const healthApi = {
  list: (memberId, memberName, options) =>
    healthReadings
      .list(memberId, options)
      .then((rows) => rows.map((row) => toReading(row, memberName))),

  listForMembers: async (members, options) => {
    const results = await Promise.all(
      members.map((member) =>
        healthReadings
          .list(member.id, options)
          .then((rows) => rows.map((row) => toReading(row, member.name)))
          .catch(() => [])
      )
    );
    return results
      .flat()
      .sort((a, b) => new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime());
  },

  create: (memberId, { metric, value, measuredAt = null, note = null }) =>
    healthReadings
      .create(memberId, {
        metric,
        value: Number(value),
        unit: metricUnit(metric),
        source: 'manual_family',
        measured_at: measuredAt || new Date().toISOString(),
        note: note || null,
      })
      .then((row) => toReading(row)),
};

// --------------------------------------------------------------------------
// Reminders, contacts, appointments, notes
// --------------------------------------------------------------------------

export function toReminder(reminder, memberName) {
  return {
    id: reminder.id,
    title: reminder.title,
    type: reminder.type,
    instructions: reminder.instructions || '',
    time: reminder.local_time || '',
    days_of_week: reminder.days_of_week || '',
    status: reminder.status,
    // Set only on a reminder Gamira proposed from something she heard. The
    // reason travels with it because a suggestion whose reasoning is invisible
    // is one a family can only guess at, and guessing is not consent.
    suggestion_reason: reminder.suggestion_reason || '',
    family_member_id: reminder.senior_profile_id,
    family_member_name: memberName || '',
    created_date: reminder.created_at,
  };
}

export const remindersApi = {
  list: (memberId, memberName) =>
    reminders.list(memberId).then((rows) => rows.map((row) => toReminder(row, memberName))),

  listForMembers: async (members) => {
    const results = await Promise.all(
      members.map((member) =>
        reminders
          .list(member.id)
          .then((rows) => rows.map((row) => toReminder(row, member.name)))
          .catch(() => [])
      )
    );
    return results.flat();
  },

  create: (memberId, { title, type, instructions, time, daysOfWeek }) =>
    reminders
      .create(memberId, {
        title,
        type: type || 'other',
        instructions: instructions || null,
        local_time: time || null,
        days_of_week: daysOfWeek || '',
      })
      .then((row) => toReminder(row)),

  update: (reminderId, patch) => reminders.update(reminderId, patch).then((row) => toReminder(row)),
  remove: (reminderId) => reminders.remove(reminderId),
};

export const contactsApi = {
  list: (memberId) => emergencyContacts.list(memberId),
  create: (memberId, { name, phone, relationship, isPrimary }) =>
    emergencyContacts.create(memberId, {
      name,
      phone,
      relationship_label: relationship || null,
      is_primary: Boolean(isPrimary),
    }),
  remove: (contactId) => emergencyContacts.remove(contactId),
};

export const appointmentsApi = {
  list: (memberId) => appointments.list(memberId),
  create: (memberId, body) => appointments.create(memberId, body),

  listForMembers: async (members) => {
    const results = await Promise.all(
      members.map((member) =>
        appointments
          .list(member.id)
          .then((rows) =>
            rows.map((row) => ({
              ...row,
              family_member_id: member.id,
              family_member_name: member.name,
            }))
          )
          .catch(() => [])
      )
    );
    return results
      .flat()
      .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime());
  },
};

export const notesApi = {
  list: (familyId, memberId) => families.notes(familyId, memberId),
  create: (familyId, body) => families.createNote(familyId, body),
};
