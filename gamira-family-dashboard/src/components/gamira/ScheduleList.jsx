import React from "react";
import { useNavigate } from "react-router-dom";
import { Pill, UtensilsCrossed, Phone, Dumbbell, Droplet, Bell, Calendar, Check, ChevronRight } from "lucide-react";

const typeMeta = {
  medication: { icon: Pill, bg: "bg-primary/10", color: "text-primary" },
  meal: { icon: UtensilsCrossed, bg: "bg-success/10", color: "text-success" },
  activity: { icon: Dumbbell, bg: "bg-amber-500/10", color: "text-amber-500" },
  hydration: { icon: Droplet, bg: "bg-primary/10", color: "text-primary" },
  appointment: { icon: Calendar, bg: "bg-amber-500/10", color: "text-amber-500" },
  call: { icon: Phone, bg: "bg-primary/10", color: "text-primary" },
  other: { icon: Bell, bg: "bg-muted", color: "text-muted-foreground" },
};

const statusStyles = {
  taken: "bg-success/10 text-success",
  due: "bg-primary/10 text-primary",
  reminded: "bg-primary/10 text-primary",
  late: "bg-amber-500/10 text-amber-500",
  skipped: "bg-muted text-muted-foreground",
  missed: "bg-destructive/10 text-destructive",
  active: "bg-primary/10 text-primary",
  paused: "bg-muted text-muted-foreground",
  completed: "bg-success/10 text-success",
};

const statusLabels = {
  taken: "Taken",
  due: "Due",
  reminded: "Reminded",
  late: "Late",
  skipped: "Skipped",
  missed: "Missed",
  active: "Scheduled",
  paused: "Paused",
  completed: "Done",
};

/**
 * Today's schedule.
 *
 * `items` are built by the calling screen from real dose events and reminders.
 * There is deliberately no placeholder row: an empty schedule must look empty,
 * because a family reading an invented "Blood Pressure Tablet — Done" would be
 * misled about whether a dose was actually taken.
 */
export default function ScheduleList({ items = [], loading = false, onConfirm, busyId = null }) {
  const navigate = useNavigate();
  const rows = items.slice(0, 3);
  const more = items.length - rows.length;

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold text-foreground">Today&apos;s Schedule</h3>
        <span className="text-[13px] font-medium text-muted-foreground">
          {loading ? "…" : `${items.length} ${items.length === 1 ? "item" : "items"}`}
        </span>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-[18px] bg-white/60 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 px-4 py-6 text-center">
          <p className="text-[13px] text-muted-foreground">
            Nothing is scheduled for today.
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 overflow-hidden divide-y divide-border/50">
          {rows.map((item) => {
            const meta = typeMeta[item.type] || typeMeta.other;
            const Icon = meta.icon;
            const canConfirm = Boolean(onConfirm && item.doseId);
            return (
              <div key={item.id} className="flex items-center gap-3.5 px-4 py-3.5 hover:bg-secondary/30 transition-colors">
                <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 ${meta.bg}`}>
                  <Icon className={`w-5 h-5 ${meta.color}`} strokeWidth={2} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[14px] font-semibold text-foreground leading-tight truncate">{item.title}</p>
                  <p className="text-[12px] text-muted-foreground mt-0.5 truncate">{item.subtitle}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <div className="flex flex-col items-end gap-1.5">
                    <span className="text-[12px] font-semibold text-foreground">{item.time}</span>
                    <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold ${statusStyles[item.status] || statusStyles.other}`}>
                      {statusLabels[item.status] || item.status}
                    </span>
                  </div>
                  {canConfirm && (
                    <button
                      onClick={() => onConfirm(item)}
                      disabled={busyId === item.doseId}
                      className="w-9 h-9 rounded-xl bg-success/10 flex items-center justify-center disabled:opacity-50"
                      aria-label={`Mark ${item.title} as taken`}
                    >
                      <Check className="w-4 h-4 text-success" strokeWidth={2.5} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {more > 0 && (
        <button
          onClick={() => navigate("/reminders")}
          className="w-full mt-2 flex items-center justify-center gap-1 py-2.5 rounded-[18px] bg-white text-primary text-[13px] font-semibold shadow-soft border border-border/50 hover:bg-secondary/30 transition-colors"
        >
          More ({more}) <ChevronRight className="w-4 h-4" strokeWidth={2} />
        </button>
      )}
    </section>
  );
}
