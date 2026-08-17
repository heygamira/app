import React from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight } from "lucide-react";

/**
 * This week's confirmed doses.
 *
 * The ring used to show a hardcoded "86" wellness score and "up 4% this week".
 * There is no wellness score in Gamira, and there was no week-on-week
 * comparison behind that number. This shows the one figure the data supports:
 * how many scheduled doses were confirmed out of those that were recorded.
 */
export default function WeeklyReport({ taken = 0, resolved = 0, days = 7 }) {
  const navigate = useNavigate();
  const pct = resolved > 0 ? Math.round((taken / resolved) * 100) : 0;
  const r = 28;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;

  return (
    <div className="flex items-center gap-4 p-4 bg-white rounded-[20px] shadow-soft border border-border/50">
      <div className="relative w-16 h-16 shrink-0">
        <svg className="w-16 h-16 -rotate-90" viewBox="0 0 70 70">
          <circle cx="35" cy="35" r={r} fill="none" stroke="currentColor" strokeWidth="6" className="text-secondary" />
          <circle
            cx="35" cy="35" r={r} fill="none" stroke="#2563EB" strokeWidth="6" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={offset}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-[15px] font-bold text-foreground">{resolved ? `${pct}` : "—"}</span>
        </div>
      </div>
      <div className="flex-1">
        <p className="text-[14px] font-semibold text-foreground">Doses confirmed</p>
        <p className="text-[12px] text-muted-foreground mt-0.5">
          {resolved
            ? `${taken} of ${resolved} recorded doses in the last ${days} days.`
            : `No doses have been recorded in the last ${days} days.`}
        </p>
      </div>
      <button
        onClick={() => navigate("/reports")}
        className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center hover:bg-secondary/70 transition-colors shrink-0"
        aria-label="Open reports"
      >
        <ChevronRight className="w-5 h-5 text-primary" strokeWidth={2} />
      </button>
    </div>
  );
}
