import { useNavigate } from "react-router-dom";
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bell, BellRing, Check, Pill, ShieldAlert, Users } from "lucide-react";
import { notifications as notificationsApi } from "@/api/gamiraClient";
import EmptyState from "@/components/gamira/EmptyState";

// Keyed by the backend's NotificationType values.
const typeMeta = {
  medication_reminder: { icon: Pill, className: "text-primary bg-primary/10" },
  missed_dose: { icon: AlertTriangle, className: "text-destructive bg-destructive/10" },
  reminder: { icon: BellRing, className: "text-amber-500 bg-amber-500/10" },
  sos: { icon: ShieldAlert, className: "text-destructive bg-destructive/10" },
  family_update: { icon: Users, className: "text-primary bg-primary/10" },
  system: { icon: Bell, className: "text-muted-foreground bg-muted" },
};

export default function Notifications() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setItems(await notificationsApi.list({ limit: 50 }));
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const markOpened = async (id) => {
    try {
      await notificationsApi.markOpened(id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const unread = items.filter((item) => item.status !== "opened").length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Notifications</h1>
        <p className="text-[13px] text-muted-foreground mt-0.5">
          {loading ? "Loading…" : `${unread} unread`}
        </p>
      </div>

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2.5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-[18px] bg-white/60 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={Bell}
          title="No notifications"
          description="Dose reminders and alerts appear here once push delivery is switched on."
        />
      ) : (
        <div className="space-y-2.5">
          {items.map((n) => {
            const meta = typeMeta[n.type] || typeMeta.system;
            const Icon = meta.icon;
            const opened = n.status === "opened";
            return (
              <div
                key={n.id}
                className={`flex items-start gap-3 p-3.5 rounded-[18px] shadow-soft border border-border/50 ${
                  opened ? "bg-white" : "bg-primary/[0.03]"
                }`}
              >
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${meta.className}`}>
                  <Icon className="w-[18px] h-[18px]" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-semibold text-foreground">{n.title}</p>
                  {n.body && <p className="text-[12px] text-muted-foreground mt-0.5">{n.body}</p>}
                  <p className="text-[11px] text-muted-foreground/80 mt-1">
                    {new Date(n.created_at).toLocaleString()} · {n.status}
                  </p>
                  {/*
                    A nudge to ring somebody arrives without its reasoning
                    attached, which asks the reader to trust a judgement they
                    cannot see. This is the way through to it.
                  */}
                  {n.type === "family_update" && (
                    <button
                      onClick={() => navigate("/gamira-noticed")}
                      className="mt-1.5 text-[12px] font-semibold text-primary"
                    >
                      Why Gamira said this
                    </button>
                  )}
                </div>
                {!opened && (
                  <button
                    onClick={() => markOpened(n.id)}
                    className="w-8 h-8 rounded-lg bg-success/10 flex items-center justify-center shrink-0"
                    aria-label="Mark as read"
                  >
                    <Check className="w-4 h-4 text-success" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="px-1 text-[11px] text-muted-foreground leading-relaxed">
        This list is the delivery record the backend keeps. Push notifications to
        phones arrive with Firebase Cloud Messaging, which is not connected yet.
      </p>
    </div>
  );
}
