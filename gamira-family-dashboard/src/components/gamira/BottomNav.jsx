import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LayoutGrid, Heart, BellRing, Users, MoreHorizontal } from "lucide-react";

const tabs = [
  { id: "dashboard", label: "Dashboard", path: "/", icon: LayoutGrid },
  { id: "health", label: "Health", path: "/health", icon: Heart },
  { id: "reminders", label: "Reminders", path: "/reminders", icon: BellRing },
  { id: "family", label: "Family", path: "/family", icon: Users },
  { id: "more", label: "More", path: "/more", icon: MoreHorizontal },
];

export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <nav className="fixed bottom-0 inset-x-0 z-30 glass border-t border-border/60 pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto max-w-md flex items-center justify-around px-2 h-16">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = location.pathname === tab.path;
          return (
            <button
              key={tab.id}
              onClick={() => navigate(tab.path)}
              className="flex flex-col items-center justify-center gap-1 flex-1 h-full py-1.5 transition-colors"
            >
              <div className={`w-12 h-7 flex items-center justify-center rounded-full transition-colors ${isActive ? "bg-primary/10" : ""}`}>
                <Icon
                  className={`w-[22px] h-[22px] transition-colors ${isActive ? "text-primary" : "text-muted-foreground"}`}
                  strokeWidth={isActive ? 2.25 : 1.75}
                />
              </div>
              <span className={`text-[10px] font-medium transition-colors ${isActive ? "text-primary" : "text-muted-foreground"}`}>
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}