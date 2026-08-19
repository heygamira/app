import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";

// Only rendered by TopNav when there is a real choice to make. A user in one
// family should never see a control that implies there might be another.
export default function FamilySwitcher() {
  const { families, activeFamily, selectFamily } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (families.length < 2 || !activeFamily) return null;

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 -ml-0.5 rounded-lg px-1 hover:bg-secondary/60 transition-colors"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="text-[10px] font-medium text-muted-foreground -mt-0.5 tracking-wide uppercase truncate max-w-[140px]">
          {activeFamily.name}
        </span>
        <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" strokeWidth={2.5} />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-2 w-56 rounded-2xl border border-border bg-card shadow-float p-1.5 z-40"
        >
          {families.map((family) => {
            const active = family.id === activeFamily.id;
            return (
              <button
                key={family.id}
                role="option"
                aria-selected={active}
                onClick={() => {
                  selectFamily(family.id);
                  setOpen(false);
                }}
                className="w-full flex items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-left text-[14px] font-medium hover:bg-secondary/60 transition-colors"
              >
                <span className="truncate text-foreground">{family.name}</span>
                {active && <Check className="w-4 h-4 text-primary shrink-0" strokeWidth={2.5} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
