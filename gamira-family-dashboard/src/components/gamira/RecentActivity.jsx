import React from "react";
import { Link } from "react-router-dom";

function relativeTime(value) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  const minutes = Math.round((Date.now() - at.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return at.toLocaleDateString();
}

/**
 * The last few timeline events.
 *
 * Replaces a component that listed three invented activities ("Mom took Blood
 * Pressure Tablet, 8:02 AM") regardless of what any family had recorded.
 */
export default function RecentActivity({ events = [], limit = 4 }) {
  const rows = events.slice(0, limit);

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold text-foreground">Recent Activity</h3>
        <Link to="/timeline" className="text-[13px] font-semibold text-primary">View All</Link>
      </div>
      <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
        {rows.length === 0 ? (
          <p className="px-4 py-6 text-center text-[13px] text-muted-foreground">
            Nothing has happened yet today.
          </p>
        ) : (
          rows.map((event) => (
            <div key={event.id} className="flex items-center gap-3 px-4 py-3">
              <div className="w-2 h-2 rounded-full bg-primary shrink-0" />
              <p className="flex-1 text-[13px] text-foreground truncate">
                {event.title}
                {event.family_member_name ? ` · ${event.family_member_name}` : ""}
              </p>
              <span className="text-[11px] text-muted-foreground shrink-0">
                {relativeTime(event.created_date)}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
