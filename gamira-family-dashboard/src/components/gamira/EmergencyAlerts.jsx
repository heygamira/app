import React from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ShieldCheck } from "lucide-react";

/**
 * Today's alerts.
 *
 * The card used to always read "All Clear — family is safe and monitored".
 * Gamira does not monitor anyone: it records what someone enters or confirms.
 * Saying otherwise invites a family to stop checking.
 */
export default function EmergencyAlerts({ missed = [] }) {
  const navigate = useNavigate();
  const hasAlerts = missed.length > 0;

  return (
    <button
      onClick={() => navigate(hasAlerts ? "/reminders" : "/emergency")}
      className={`w-full flex items-center gap-3 p-4 bg-white rounded-[20px] shadow-soft text-left hover:shadow-card transition-shadow border ${
        hasAlerts ? "border-destructive/30" : "border-border/50"
      }`}
    >
      <div
        className={`w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 ${
          hasAlerts ? "bg-destructive/10" : "bg-success/10"
        }`}
      >
        {hasAlerts ? (
          <AlertTriangle className="w-5 h-5 text-destructive" strokeWidth={2} />
        ) : (
          <ShieldCheck className="w-5 h-5 text-success" strokeWidth={2} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[14px] font-semibold text-foreground">
          {hasAlerts
            ? `${missed.length} missed ${missed.length === 1 ? "dose" : "doses"} today`
            : "No missed doses recorded"}
        </p>
        <p className="text-[12px] text-muted-foreground truncate">
          {hasAlerts
            ? missed
                .map((dose) => `${dose.medication_name} · ${dose.family_member_name}`)
                .join(", ")
            : "Gamira reports only what has been recorded."}
        </p>
      </div>
    </button>
  );
}
