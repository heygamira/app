import React from "react";
import { Calendar } from "lucide-react";

function formatWhen(value) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Upcoming appointments.
 *
 * The two sample doctors that used to live in this file have been removed: a
 * family should never see an appointment that nobody booked.
 */
export default function UpcomingAppointments({ appointments = [] }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold text-foreground">Upcoming Appointments</h3>
      </div>

      {appointments.length === 0 ? (
        <div className="p-4 bg-white rounded-[18px] shadow-soft border border-border/50 text-center">
          <p className="text-[13px] text-muted-foreground">No appointments are scheduled.</p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {appointments.map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50"
            >
              <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
                <Calendar className="w-5 h-5 text-primary" strokeWidth={2} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-foreground truncate">{a.title}</p>
                <p className="text-[11px] text-muted-foreground truncate">
                  {[a.clinician, a.location, a.family_member_name].filter(Boolean).join(" · ")}
                </p>
              </div>
              <span className="text-[11px] font-medium text-primary shrink-0">{formatWhen(a.starts_at)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
