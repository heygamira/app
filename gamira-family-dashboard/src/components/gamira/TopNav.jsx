import React, { useEffect, useState } from "react";
import { Bell, Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { useTheme } from "@/lib/ThemeContext";
import { notifications as notificationsApi } from "@/api/gamiraClient";
import { initialOf } from "@/lib/careStatus";

export default function TopNav({ title }) {
  const navigate = useNavigate();
  const { user, isAuthenticated } = useAuth();
  const { theme, toggle } = useTheme();
  const [unread, setUnread] = useState(0);

  // The dot is a claim that something is waiting, so it is driven by real
  // unread notifications rather than shown permanently.
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    notificationsApi
      .list({ unreadOnly: true, limit: 20 })
      .then((rows) => {
        if (!cancelled) setUnread(rows.length);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  return (
    <header className="sticky top-0 z-30 glass border-b border-border/60">
      <div className="mx-auto max-w-md flex items-center justify-between px-5 h-16">
        <div className="flex flex-col">
          <span className="text-[19px] font-bold tracking-tight text-foreground">{title || "Gamira"}</span>
          {!title && (
            <span className="text-[10px] font-medium text-muted-foreground -mt-0.5 tracking-wide uppercase">
              Family Dashboard
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 -mr-2">
          <button
            onClick={toggle}
            className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-secondary/60 transition-colors"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? (
              <Sun className="w-5 h-5 text-foreground" strokeWidth={2} />
            ) : (
              <Moon className="w-5 h-5 text-foreground" strokeWidth={2} />
            )}
          </button>
          <button
            onClick={() => navigate("/notifications")}
            className="relative w-10 h-10 flex items-center justify-center rounded-xl hover:bg-secondary/60 transition-colors"
            aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          >
            <Bell className="w-5 h-5 text-foreground" strokeWidth={2} />
            {unread > 0 && (
              <span className="absolute top-2.5 right-2.5 w-2 h-2 bg-primary rounded-full ring-2 ring-background" />
            )}
          </button>
          <button
            onClick={() => navigate("/profile")}
            className="w-9 h-9 rounded-full overflow-hidden ring-2 ring-white shadow-soft active:scale-95 transition-transform bg-secondary flex items-center justify-center"
            aria-label="Profile"
          >
            {user?.photo_url ? (
              <img src={user.photo_url} alt="" className="w-full h-full object-cover" />
            ) : (
              <span className="text-[13px] font-bold text-muted-foreground">{initialOf(user?.name)}</span>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
