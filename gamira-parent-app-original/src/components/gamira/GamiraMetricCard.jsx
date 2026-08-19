import { cn } from '@/lib/utils';

function Sparkline({ data, color }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * 100},${20 - ((v - min) / range) * 16 - 2}`)
    .join(' ');
  return (
    <svg viewBox="0 0 100 20" preserveAspectRatio="none" className="h-8 w-full overflow-visible">
      <polyline
        points={pts}
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ stroke: color }}
      />
    </svg>
  );
}

/**
 * One reading, or an honest dash where one would be.
 *
 * `stale` is the whole reason this component has a second state. A watch that
 * has been switched off does not stop having sent a last reading, and drawing
 * that number in the present tense is inventing data — the reader has no way
 * to tell "98 bpm now" from "98 bpm, some time yesterday, before the watch was
 * put in a drawer". So it shows a dash and says the watch is not reporting.
 */
export default function GamiraMetricCard({
  icon: Icon,
  iconBg = '',
  iconColor = '',
  label,
  value,
  unit = '',
  status = '',
  data = [],
  sparkColor = 'currentColor',
  stale = false,
}) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className={cn('flex h-10 w-10 items-center justify-center rounded-xl', iconBg)}>
          <Icon className={cn('h-5 w-5', iconColor)} />
        </div>
        {status && (
          <span className="rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-semibold text-success">
            {status}
          </span>
        )}
      </div>
      <p className="text-[13px] text-muted-foreground">{label}</p>
      {stale ? (
        <>
          <p className="text-2xl font-bold leading-none text-muted-foreground/50">
            &mdash;&mdash;
          </p>
          <p className="text-[12px] leading-tight text-muted-foreground">
            Not reporting
          </p>
        </>
      ) : (
        <p className="text-2xl font-bold leading-none text-foreground">
          {value}{' '}
          {unit && (
            <span className="text-sm font-semibold text-muted-foreground">{unit}</span>
          )}
        </p>
      )}
      {data && !stale && (
        <div className="mt-1">
          <Sparkline data={data} color={sparkColor || 'hsl(var(--primary))'} />
        </div>
      )}
    </div>
  );
}
