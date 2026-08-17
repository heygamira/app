import React, { useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ClipboardList, Clock, FileText, MessageCircle, Phone, Pill, ShieldAlert, UserPlus } from "lucide-react";

const actions = [
  { label: "Summary", icon: ClipboardList, path: "/ai-summary", bg: "bg-primary/10", color: "text-primary" },
  { label: "Add Medicine", icon: Pill, path: "/add-medicine", bg: "bg-success/10", color: "text-success" },
  { label: "Emergency", icon: ShieldAlert, path: "/emergency", bg: "bg-destructive/10", color: "text-destructive" },
  { label: "Add Member", icon: UserPlus, path: "/add-member", bg: "bg-amber-500/10", color: "text-amber-500" },
  { label: "Ask", icon: MessageCircle, path: "/ai-assistant", bg: "bg-violet-500/10", color: "text-violet-500" },
  { label: "Reports", icon: FileText, path: "/reports", bg: "bg-primary/10", color: "text-primary" },
  { label: "Timeline", icon: Clock, path: "/timeline", bg: "bg-success/10", color: "text-success" },
  { label: "Contacts", icon: Phone, path: "/emergency", bg: "bg-amber-500/10", color: "text-amber-500" },
];

export default function QuickActions() {
  const navigate = useNavigate();
  const ref = useRef(null);
  const drag = useRef({ active: false, startX: 0, scrollLeft: 0, moved: false });

  const onDown = (e) => {
    const el = ref.current;
    if (!el) return;
    drag.current = { active: true, startX: e.pageX, scrollLeft: el.scrollLeft, moved: false };
  };
  const onMove = (e) => {
    if (!drag.current.active) return;
    const el = ref.current;
    if (!el) return;
    const dx = e.pageX - drag.current.startX;
    if (Math.abs(dx) > 4) drag.current.moved = true;
    el.scrollLeft = drag.current.scrollLeft - dx;
  };
  const onUp = () => {
    drag.current.active = false;
  };
  const onClick = (e, path) => {
    if (drag.current.moved) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    navigate(path);
  };

  return (
    <div
      ref={ref}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onMouseLeave={onUp}
      className="flex gap-2.5 overflow-x-auto no-scrollbar -mx-5 px-5 pb-1 cursor-grab active:cursor-grabbing select-none"
    >
      {actions.map((a) => {
        const Icon = a.icon;
        return (
          <button
            key={a.label}
            onClick={(e) => onClick(e, a.path)}
            className="flex flex-col items-center gap-2 py-3.5 px-3 bg-white rounded-[18px] shadow-soft border border-border/50 hover:shadow-card transition-shadow active:scale-[0.98] shrink-0 w-[72px]"
          >
            <div className={`w-10 h-10 rounded-2xl flex items-center justify-center ${a.bg}`}>
              <Icon className={`w-5 h-5 ${a.color}`} strokeWidth={2} />
            </div>
            <span className="text-[10px] font-semibold text-foreground text-center leading-tight">{a.label}</span>
          </button>
        );
      })}
    </div>
  );
}
