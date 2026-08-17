import React from "react";
import { motion } from "framer-motion";
import { careStatusMeta, initialOf } from "@/lib/careStatus";

export default function MemberSelector({
  members = [],
  value,
  onChange,
  allowAll = false,
  /** @type {(memberId: string) => string} */
  statusFor = (_memberId) => "none",
}) {
  const items = [];
  if (allowAll) items.push({ id: "all", label: "All Family", photo: null, role: "", status: "none", age: null });
  members.forEach((m) =>
    items.push({
      id: m.id,
      label: m.name,
      photo: m.photo_url,
      role: m.role,
      status: statusFor(m.id),
      age: m.age,
    })
  );

  const sel = items.find((it) => it.id === value) || items[0];
  if (!sel) return null;

  const selMeta = careStatusMeta(sel.status);

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${selMeta.dot}`} />
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Viewing</p>
        </div>
        <p className="text-[17px] font-bold text-foreground leading-tight mt-0.5 truncate">{sel.label}</p>
        <p className="text-[11px] text-muted-foreground leading-tight truncate">
          {sel.role ? sel.role : "Family"}
          {sel.age ? ` · ${sel.age} yrs` : ""}
        </p>
      </div>

      <div className="flex items-center gap-2 shrink-0 overflow-x-auto overflow-y-hidden touch-pan-x no-scrollbar -mx-1 px-1 py-1">
        {items.map((it) => {
          const active = it.id === value;
          return (
            <button
              key={it.id}
              onClick={() => onChange(it.id)}
              className="relative shrink-0 flex items-center justify-center"
              style={{ width: 44, height: 44 }}
              aria-label={it.label}
            >
              <motion.div
                animate={{ scale: active ? 1 : 0.74, opacity: active ? 1 : 0.5 }}
                transition={{ type: "spring", stiffness: 380, damping: 30 }}
                className={`w-11 h-11 rounded-full overflow-hidden flex items-center justify-center bg-secondary ring-2 ring-offset-2 ring-offset-background ${
                  active ? careStatusMeta(it.status).ring : "ring-transparent"
                }`}
              >
                {it.photo ? (
                  <img src={it.photo} alt="" className="w-full h-full object-cover" />
                ) : (
                  <span className={`text-[14px] font-bold ${active ? "text-foreground" : "text-muted-foreground"}`}>
                    {initialOf(it.label)}
                  </span>
                )}
              </motion.div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
