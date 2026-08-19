import React from "react";
import { Link } from "react-router-dom";
import { Activity, Droplet, Footprints, Heart, Moon, Scale, Thermometer, Wind } from "lucide-react";
import MetricCard from "./MetricCard";

// Keyed by the backend's HealthMetric values. Anything the API can return has
// an entry here; nothing here exists that the API cannot return.
export const METRIC_DISPLAY = {
  heart_rate: { icon: Heart, bg: "bg-primary/10", color: "text-primary", name: "Heart Rate", line: "#2563EB" },
  blood_pressure_systolic: { icon: Droplet, bg: "bg-primary/10", color: "text-primary", name: "BP Systolic", line: "#2563EB" },
  blood_pressure_diastolic: { icon: Droplet, bg: "bg-primary/10", color: "text-primary", name: "BP Diastolic", line: "#2563EB" },
  oxygen_saturation: { icon: Wind, bg: "bg-primary/10", color: "text-primary", name: "Oxygen", line: "#2563EB" },
  blood_glucose: { icon: Activity, bg: "bg-violet-500/10", color: "text-violet-500", name: "Blood Glucose", line: "#8B5CF6" },
  body_temperature: { icon: Thermometer, bg: "bg-amber-500/10", color: "text-amber-500", name: "Temperature", line: "#F59E0B" },
  weight: { icon: Scale, bg: "bg-success/10", color: "text-success", name: "Weight", line: "#22C55E" },
  steps: { icon: Footprints, bg: "bg-success/10", color: "text-success", name: "Steps", line: "#22C55E" },
  sleep_duration: { icon: Moon, bg: "bg-violet-500/10", color: "text-violet-500", name: "Sleep", line: "#8B5CF6" },
};

export const METRIC_ORDER = Object.keys(METRIC_DISPLAY);

/**
 * How old a reading a *device* sent may be and still be shown as a number.
 *
 * A watch reports continuously, so its last reading means "now" only while it
 * is still reporting. A reading somebody typed in is not stale — a weight from
 * last week is still their weight — so this only applies to device sources.
 */
export const LIVE_READING_MINUTES = 10;

export function isStale(reading, now = Date.now()) {
  if (!reading || reading.source !== 'device') return false;
  const at = new Date(reading.recorded_at).getTime();
  if (Number.isNaN(at)) return false;
  return now - at > LIVE_READING_MINUTES * 60_000;
}

/**
 * Group readings by metric, newest first within each metric.
 *
 * @param {Array<{metric: string, value: number, unit: string, recorded_at: string}>} readings
 */
export function byMetric(readings = []) {
  const grouped = new Map();
  for (const reading of readings) {
    if (!grouped.has(reading.metric)) grouped.set(reading.metric, []);
    grouped.get(reading.metric).push(reading);
  }
  for (const series of grouped.values()) {
    series.sort((a, b) => new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime());
  }
  return grouped;
}

/**
 * Health overview.
 *
 * Only metrics that actually have a reading are shown. The previous version
 * filled every card with invented defaults (72 bpm, 120/80, a fake sparkline),
 * which reads as a live measurement of a real person when nothing has been
 * recorded at all.
 */
export default function HealthOverview({ readings = [], memberName, memberId }) {
  const grouped = byMetric(readings);
  const present = METRIC_ORDER.filter((metric) => grouped.has(metric));

  return (
    <section>
      <h3 className="text-base font-bold text-foreground mb-3">
        Health Overview{memberName ? ` · ${memberName}` : ""}
      </h3>

      {present.length === 0 ? (
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 px-4 py-6 text-center">
          <p className="text-[13px] text-muted-foreground">No readings have been recorded yet.</p>
          <Link
            to={memberId ? `/health/heart_rate?member=${memberId}` : "/health"}
            className="mt-2 inline-block text-[13px] font-semibold text-primary"
          >
            Add the first reading
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {present.map((metric) => {
            const cfg = METRIC_DISPLAY[metric];
            const series = grouped.get(metric);
            const latest = series[0];
            // Sparkline wants oldest → newest.
            const spark = [...series].reverse().map((r) => Number(r.value) || 0);
            return (
              <Link
                key={metric}
                to={memberId ? `/health/${metric}?member=${memberId}` : `/health/${metric}`}
              >
                <MetricCard
                  icon={cfg.icon}
                  iconBg={cfg.bg}
                  iconColor={cfg.color}
                  name={cfg.name}
                  value={latest.value}
                  unit={latest.unit}
                  sparkData={spark}
                  sparkColor={cfg.line}
                  stale={isStale(latest)}
                />
              </Link>
            );
          })}
        </div>
      )}
    </section>
  );
}
