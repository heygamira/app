// Translation between the Gamira API and what this app puts on screen.
//
// The Parent App is one person's own device, so everything here is scoped to
// that person. Nothing in this file invents a value: a metric with no reading
// says it has none.

import {
  Activity,
  Droplet,
  Footprints,
  Heart,
  Moon,
  Scale,
  Thermometer,
  Wind,
} from 'lucide-react';

/** Dose statuses that still need a decision from the person taking it. */
export const OPEN_DOSE_STATUSES = ['due', 'reminded', 'late', 'missed'];

/** Dose statuses that have been settled. */
export const CLOSED_DOSE_STATUSES = ['taken', 'skipped', 'cancelled'];

export function ageFrom(dateOfBirth) {
  if (!dateOfBirth) return null;
  const born = new Date(dateOfBirth);
  if (Number.isNaN(born.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - born.getFullYear();
  const months = now.getMonth() - born.getMonth();
  if (months < 0 || (months === 0 && now.getDate() < born.getDate())) age -= 1;
  return age >= 0 ? age : null;
}

// Keyed by the backend's HealthMetric values. Blood pressure is two stored
// metrics but one reading to a person, so it is displayed as one card.
export const METRIC_CARDS = [
  {
    id: 'blood_pressure',
    keys: ['blood_pressure_systolic', 'blood_pressure_diastolic'],
    labelKey: 'bloodPressure',
    fallbackLabel: 'Blood Pressure',
    unit: 'mmHg',
    icon: Activity,
    iconBg: 'bg-primary/10',
    iconColor: 'text-primary',
    sparkColor: 'hsl(var(--primary))',
  },
  {
    id: 'heart_rate',
    keys: ['heart_rate'],
    labelKey: 'heartRate',
    fallbackLabel: 'Heart Rate',
    unit: 'bpm',
    icon: Heart,
    iconBg: 'bg-rose-500/10',
    iconColor: 'text-rose-500',
    sparkColor: 'hsl(var(--destructive))',
  },
  {
    id: 'oxygen_saturation',
    keys: ['oxygen_saturation'],
    labelKey: 'oxygenLevel',
    fallbackLabel: 'Oxygen Level',
    unit: '%',
    icon: Wind,
    iconBg: 'bg-blue-500/10',
    iconColor: 'text-blue-500',
    sparkColor: 'hsl(var(--primary))',
  },
  {
    id: 'body_temperature',
    keys: ['body_temperature'],
    labelKey: 'temperature',
    fallbackLabel: 'Temperature',
    unit: '°C',
    icon: Thermometer,
    iconBg: 'bg-amber-500/10',
    iconColor: 'text-amber-500',
    sparkColor: 'hsl(var(--warning))',
  },
  {
    id: 'blood_glucose',
    keys: ['blood_glucose'],
    labelKey: 'bloodSugar',
    fallbackLabel: 'Blood Sugar',
    unit: 'mg/dL',
    icon: Droplet,
    iconBg: 'bg-violet-500/10',
    iconColor: 'text-violet-500',
    sparkColor: 'hsl(var(--accent))',
  },
  {
    id: 'sleep_duration',
    keys: ['sleep_duration'],
    labelKey: 'sleep',
    fallbackLabel: 'Sleep',
    unit: 'hrs',
    icon: Moon,
    iconBg: 'bg-indigo-500/10',
    iconColor: 'text-indigo-500',
    sparkColor: 'hsl(var(--accent))',
  },
  {
    id: 'steps',
    keys: ['steps'],
    labelKey: 'steps',
    fallbackLabel: 'Steps',
    unit: '',
    icon: Footprints,
    iconBg: 'bg-emerald-500/10',
    iconColor: 'text-emerald-500',
    sparkColor: 'hsl(var(--success))',
  },
  {
    id: 'weight',
    keys: ['weight'],
    labelKey: 'weight',
    fallbackLabel: 'Weight',
    unit: 'kg',
    icon: Scale,
    iconBg: 'bg-success/10',
    iconColor: 'text-success',
    sparkColor: 'hsl(var(--success))',
  },
];

/**
 * Group readings by metric, newest first inside each metric.
 *
 * @param {Array<{metric: string, value: number, measured_at: string}>} readings
 * @returns {Map<string, Array<any>>}
 */
export function groupReadings(readings = []) {
  const grouped = new Map();
  for (const reading of readings) {
    if (!grouped.has(reading.metric)) grouped.set(reading.metric, []);
    grouped.get(reading.metric).push(reading);
  }
  for (const series of grouped.values()) {
    series.sort((a, b) => new Date(b.measured_at).getTime() - new Date(a.measured_at).getTime());
  }
  return grouped;
}

/**
 * Turn one card definition into what the screen shows, or null when nothing
 * has been recorded for it.
 */
export function readCard(card, grouped) {
  const series = card.keys.map((key) => grouped.get(key) || []);
  if (series.every((entries) => entries.length === 0)) return null;

  if (card.id === 'blood_pressure') {
    const systolic = series[0][0];
    const diastolic = series[1][0];
    if (!systolic || !diastolic) return null;
    return {
      ...card,
      value: `${round(systolic.value)}/${round(diastolic.value)}`,
      unit: card.unit,
      // The systolic trend is the one a chart of a single line can honestly show.
      spark: sparkOf(series[0]),
      measuredAt: systolic.measured_at,
    };
  }

  const latest = series[0][0];
  return {
    ...card,
    value: format(card.id, latest.value),
    unit: card.unit,
    spark: sparkOf(series[0]),
    measuredAt: latest.measured_at,
  };
}

function round(value) {
  return Number.isInteger(value) ? value : Math.round(value * 10) / 10;
}

function format(metricId, value) {
  if (metricId === 'steps') return Math.round(value).toLocaleString();
  return String(round(value));
}

// Oldest -> newest, which is the direction a sparkline reads. One reading is
// not a trend, so it draws nothing rather than a flat invented line.
function sparkOf(series) {
  if (series.length < 2) return [];
  return [...series].reverse().map((reading) => Number(reading.value) || 0);
}

/** "in 25 minutes" / "2 hours ago", from a local HH:MM in the person's day. */
export function untilLocalTime(localTime) {
  if (!localTime) return null;
  const [hours, minutes] = String(localTime).split(':').map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null;
  const target = new Date();
  target.setHours(hours, minutes, 0, 0);
  return Math.round((target.getTime() - Date.now()) / 60000);
}

export function describeMinutes(deltaMinutes) {
  if (deltaMinutes === null) return '';
  const past = deltaMinutes < 0;
  const total = Math.abs(deltaMinutes);
  if (total < 1) return 'now';
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  const parts = [];
  if (hours) parts.push(`${hours} ${hours === 1 ? 'hour' : 'hours'}`);
  if (minutes && !hours) parts.push(`${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`);
  const span = parts.join(' ') || 'a moment';
  return past ? `${span} ago` : `in ${span}`;
}

/** Format a local HH:MM as a 12-hour clock time, which is what this app shows. */
export function clockTime(localTime) {
  if (!localTime) return '';
  const [hours, minutes] = String(localTime).split(':').map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return String(localTime);
  const suffix = hours >= 12 ? 'PM' : 'AM';
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${hour12}:${String(minutes).padStart(2, '0')} ${suffix}`;
}
