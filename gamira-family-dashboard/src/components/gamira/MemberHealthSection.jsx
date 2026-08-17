import React from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Flag } from "lucide-react";
import HealthOverview, { METRIC_DISPLAY, METRIC_ORDER, byMetric } from "./HealthOverview";

/**
 * One person's health page body.
 *
 * The "All Metrics" list shows every metric the backend supports. A metric with
 * no reading says so rather than showing a plausible number: an invented
 * "Blood Sugar 95 mg/dL" is indistinguishable from a real measurement.
 */
export default function MemberHealthSection({ member, readings = [] }) {
  const grouped = byMetric(readings);

  return (
    <section className="space-y-4">
      <HealthOverview readings={readings} memberName={member?.name} memberId={member?.id} />

      <div>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          All Metrics
        </p>
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
          {METRIC_ORDER.map((metric) => {
            const latest = grouped.get(metric)?.[0];
            // A device that flagged its own reading writes the reason onto it.
            // Gamira shows that the device said so — it does not agree or
            // disagree, and it never flags a reading of its own accord.
            const flagged = Boolean(latest?.note && latest.source === "device");
            return (
              <Link
                key={metric}
                to={`/health/${metric}${member?.id ? `?member=${member.id}` : ""}`}
                className="w-full flex items-center justify-between px-4 py-3.5 hover:bg-secondary/30 transition-colors"
              >
                <span className="min-w-0">
                  <span className="text-[14px] font-medium text-foreground">
                    {METRIC_DISPLAY[metric].name}
                  </span>
                  {flagged && (
                    <span className="mt-0.5 flex items-start gap-1 text-[11px] leading-snug text-warning">
                      <Flag className="mt-[1px] h-3 w-3 shrink-0" strokeWidth={2.5} />
                      <span className="truncate">{latest.note}</span>
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-1.5">
                  {latest ? (
                    <span
                      className={`text-[13px] font-semibold ${
                        flagged ? "text-warning" : "text-foreground"
                      }`}
                    >
                      {latest.value} {latest.unit}
                    </span>
                  ) : (
                    <span className="text-[12px] text-muted-foreground">Not recorded</span>
                  )}
                  <ChevronRight className="w-4 h-4 text-muted-foreground" strokeWidth={2} />
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}
