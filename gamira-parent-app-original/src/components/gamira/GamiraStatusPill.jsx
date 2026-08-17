import { cn } from '@/lib/utils';

export default function GamiraStatusPill({ active, label, sublabel }) {
  return (
    <div className="inline-flex items-center gap-2.5 rounded-full border border-border bg-card px-3.5 py-2 shadow-sm">
      <span className="relative flex h-2.5 w-2.5">
        {active && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
        )}
        <span
          className={cn(
            'relative inline-flex h-2.5 w-2.5 rounded-full',
            active ? 'bg-success' : 'bg-muted-foreground/50'
          )}
        />
      </span>
      <div className="flex flex-col leading-tight">
        <span className="text-[13px] font-semibold text-foreground">{label}</span>
        {sublabel && (
          <span className={cn('text-[11px] font-medium', active ? 'text-success' : 'text-muted-foreground')}>
            {sublabel}
          </span>
        )}
      </div>
    </div>
  );
}
