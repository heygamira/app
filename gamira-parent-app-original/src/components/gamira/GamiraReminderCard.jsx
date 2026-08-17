import { cn } from '@/lib/utils';
import { Check } from 'lucide-react';

export default function GamiraReminderCard({ time, title, status, done, onToggle }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-3.5 shadow-sm">
      <button
        onClick={onToggle}
        aria-label="Toggle complete"
        className={cn(
          'flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition active:scale-90',
          done ? 'bg-success/15' : 'border-2 border-border'
        )}
      >
        {done && <Check className="h-5 w-5 text-success" strokeWidth={3} />}
      </button>
      <div className="flex-1">
        <p className={cn('text-[15px] font-semibold leading-tight', done ? 'text-muted-foreground line-through' : 'text-foreground')}>
          {title}
        </p>
        <p className="text-[12px] text-muted-foreground">{time} · {status}</p>
      </div>
    </div>
  );
}
