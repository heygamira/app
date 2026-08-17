import React from "react";
import Sparkline from "./Sparkline";

export default function MetricCard({ icon: Icon, iconBg, iconColor, name, value, unit, sparkData, sparkColor }) {
  return (
    <div className="flex flex-col p-4 bg-white rounded-[18px] shadow-soft border border-border/50 hover:shadow-card transition-shadow">
      <div className="flex items-center justify-between">
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${iconBg}`}>
          <Icon className={`w-[18px] h-[18px] ${iconColor}`} strokeWidth={1.75} />
        </div>
        <Sparkline data={sparkData} color={sparkColor} width={48} height={20} />
      </div>
      <p className="mt-3 text-[11px] font-medium text-muted-foreground">{name}</p>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className="text-xl font-bold text-foreground tracking-tight">{value}</span>
        {unit && <span className="text-[11px] font-medium text-muted-foreground">{unit}</span>}
      </div>
    </div>
  );
}