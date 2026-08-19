import { cn } from '@/lib/utils';
import { Clock, Check } from 'lucide-react';

/**
 * One thing on today's schedule.
 *
 * `action` is rendered inside the card, on the right. The taken button used to
 * be a full-width bar rendered *after* each open row, so the last one floated
 * between the schedule and the health section looking like a page-level
 * action — a big blue button apparently belonging to nothing, which for a dose
 * confirmation is the wrong thing to be ambiguous about. Keeping it in the
 * card keeps it attached to the medicine it records.
 */
export default function GamiraScheduleCard({ time, title, subtitle = null, done = false, icon: Icon, onClick = undefined, action = null }) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center gap-3 rounded-2xl border border-border bg-card p-3.5 shadow-sm transition',
        onClick && 'cursor-pointer active:scale-[0.99]'
      )}
    >
      <div className="w-14 shrink-0 text-center">
        <p className="text-[13px] font-semibold text-foreground">{time}</p>
      </div>
      <div
        className={cn(
          'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
          done ? 'bg-success/15' : 'bg-accent/10'
        )}
      >
        {done ? (
          <Check className="h-5 w-5 text-success" strokeWidth={3} />
        ) : Icon ? (
          <Icon className="h-5 w-5 text-accent" />
        ) : (
          <Clock className="h-5 w-5 text-primary" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-semibold leading-tight text-foreground">{title}</p>
        <p className="text-[12px] text-muted-foreground">{subtitle}</p>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
