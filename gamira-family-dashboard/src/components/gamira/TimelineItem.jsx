import React from "react";
import {
  Activity,
  CalendarPlus,
  CheckCircle2,
  FileText,
  Pill,
  ShieldAlert,
  SkipForward,
  StickyNote,
  UserPlus,
  XCircle,
} from "lucide-react";

// Keyed by the backend's TimelineEventType values.
const typeMeta = {
  medication_taken: { icon: Pill, className: "text-success bg-success/10" },
  medication_skipped: { icon: SkipForward, className: "text-muted-foreground bg-muted" },
  medication_missed: { icon: XCircle, className: "text-destructive bg-destructive/10" },
  medication_added: { icon: Pill, className: "text-primary bg-primary/10" },
  reminder_completed: { icon: CheckCircle2, className: "text-success bg-success/10" },
  health_reading_added: { icon: Activity, className: "text-primary bg-primary/10" },
  appointment_scheduled: { icon: CalendarPlus, className: "text-amber-500 bg-amber-500/10" },
  sos_triggered: { icon: ShieldAlert, className: "text-destructive bg-destructive/10" },
  member_joined: { icon: UserPlus, className: "text-primary bg-primary/10" },
  note_added: { icon: StickyNote, className: "text-violet-500 bg-violet-500/10" },
};

export default function TimelineItem({ event }) {
  const meta = typeMeta[event.type] || { icon: FileText, className: "text-muted-foreground bg-muted" };
  const Icon = meta.icon;
  const at = new Date(event.created_date);

  return (
    <div className="flex items-start gap-3 px-4 py-3.5">
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${meta.className}`}>
        <Icon className="w-[18px] h-[18px]" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-semibold text-foreground">{event.title}</p>
        {event.description && (
          <p className="text-[12px] text-muted-foreground mt-0.5">{event.description}</p>
        )}
        {event.family_member_name && (
          <p className="text-[11px] text-muted-foreground/80 mt-0.5">{event.family_member_name}</p>
        )}
      </div>
      <span className="text-[11px] text-muted-foreground shrink-0" title={at.toLocaleString()}>
        {Number.isNaN(at.getTime()) ? "" : at.toLocaleDateString()}
      </span>
    </div>
  );
}
