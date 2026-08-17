import React from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight, ClipboardList, ListChecks } from "lucide-react";

/**
 * What the records show.
 *
 * This used to render two fixed sentences ("Mom's blood pressure has been
 * stable for 5 days", "Dad's step count improved 18%") that were written into
 * the file and had nothing to do with the family reading them. Every line here
 * is now counted from records the backend returned, and the card says so.
 */
export default function AIInsights({ lines = [], disclaimer }) {
  const navigate = useNavigate();

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold text-foreground flex items-center gap-1.5">
          <ClipboardList className="w-4 h-4 text-primary" strokeWidth={2} />
          What the records show
        </h3>
        <button
          onClick={() => navigate("/ai-summary")}
          className="inline-flex items-center text-[13px] font-semibold text-primary"
        >
          Full summary <ChevronRight className="w-4 h-4" strokeWidth={2} />
        </button>
      </div>

      <div className="space-y-2.5">
        {lines.length === 0 ? (
          <div className="p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50">
            <p className="text-[13px] text-muted-foreground">
              Nothing has been recorded yet. Add a medicine or a reading and this
              fills in.
            </p>
          </div>
        ) : (
          lines.map((line, i) => (
            <div
              key={i}
              className="flex items-start gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50"
            >
              <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-primary/10">
                <ListChecks className="w-[18px] h-[18px] text-primary" strokeWidth={2} />
              </div>
              <p className="text-[13px] text-foreground leading-relaxed pt-1">{line}</p>
            </div>
          ))
        )}
      </div>

      {disclaimer && (
        <p className="mt-2 px-1 text-[11px] text-muted-foreground leading-relaxed">{disclaimer}</p>
      )}
    </section>
  );
}
