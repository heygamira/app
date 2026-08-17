import React from "react";
import { Pill } from "lucide-react";

export default function MedicationStatus({ taken = 0, total = 0, memberName, onClick }) {
  const pct = total > 0 ? Math.round((taken / total) * 100) : 0;
  return (
    <button onClick={onClick} className="w-full text-left p-4 bg-white rounded-[20px] shadow-soft border border-border/50 hover:shadow-card transition-shadow">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center">
            <Pill className="w-[18px] h-[18px] text-primary" strokeWidth={2} />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-foreground">
              Today's Medication{memberName ? ` · ${memberName}` : ""}
            </p>
            <p className="text-[11px] text-muted-foreground">{taken} of {total} taken</p>
          </div>
        </div>
        <span className="text-[13px] font-bold text-primary">{pct}%</span>
      </div>
      <div className="mt-3 h-2 rounded-full bg-secondary overflow-hidden">
        <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </button>
  );
}