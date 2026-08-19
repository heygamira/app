import React from "react";
import Sparkline from "./Sparkline";

/**
 * One reading, or a dash when it is no longer current.
 *
 * A watch that has been taken off does not stop having sent a last reading,
 * and showing that number as though it were now is inventing data: nobody
 * reading this card can tell "98 bpm" from "98 bpm, yesterday, before the
 * watch went in a drawer". `stale` is that difference, and it belongs on the
 * family's screen at least as much as on the person's own.
 */
export default function MetricCard({ icon: Icon, iconBg, iconColor, name, value, unit, sparkData, sparkColor, stale = false }) {
  return (
    <div className="flex flex-col p-4 bg-white rounded-[18px] shadow-soft border border-border/50 hover:shadow-card transition-shadow">
      <div className="flex items-center justify-between">
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${iconBg}`}>
          <Icon className={`w-[18px] h-[18px] ${iconColor}`} strokeWidth={1.75} />
        </div>
        {!stale && <Sparkline data={sparkData} color={sparkColor} width={48} height={20} />}
      </div>
      <p className="mt-3 text-[11px] font-medium text-muted-foreground">{name}</p>
      {stale ? (
        <div className="mt-0.5 flex items-baseline gap-1">
          <span className="text-xl font-bold tracking-tight text-muted-foreground/50">&mdash;&mdash;</span>
          <span className="text-[11px] font-medium text-muted-foreground">not reporting</span>
        </div>
      ) : (
        <div className="mt-0.5 flex items-baseline gap-1">
          <span className="text-xl font-bold text-foreground tracking-tight">{value}</span>
          {unit && <span className="text-[11px] font-medium text-muted-foreground">{unit}</span>}
        </div>
      )}
    </div>
  );
}