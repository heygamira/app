import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Phone, ShieldAlert } from "lucide-react";
import { alarmAudible, startAlarm, stopAlarm } from "@/lib/alarm";

function timeAgo(value) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  const seconds = Math.max(0, Math.round((Date.now() - at.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return at.toLocaleString();
}

/**
 * The SOS alert, over whatever screen is open.
 *
 * It states what actually happened — someone pressed SOS and Gamira recorded
 * it — and what did not: nobody has been called, and no emergency service has
 * been contacted. Acknowledging marks it read for this member only; it does
 * not resolve anything for anyone else.
 */
export default function SosAlertOverlay({ alerts = [], onAcknowledge }) {
  const navigate = useNavigate();
  const acknowledge = (id) => onAcknowledge?.(id);
  const alert = alerts[0] || null;

  // Sound for as long as there is an unanswered emergency on screen, not once
  // when it arrives. Somebody who was out of the room when it landed still
  // needs to hear it when they come back.
  useEffect(() => {
    if (!alert) return undefined;
    startAlarm();
    return stopAlarm;
  }, [alert]);

  return (
    <AnimatePresence>
      {alert && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-destructive/90 p-5 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          role="alertdialog"
          aria-live="assertive"
        >
          <motion.div
            initial={{ scale: 0.92, y: 16 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.92, y: 16 }}
            className="w-full max-w-sm rounded-[28px] bg-white p-6 text-center shadow-2xl"
          >
            <motion.div
              animate={{ scale: [1, 1.08, 1] }}
              transition={{ repeat: Infinity, duration: 1.4 }}
              className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10"
            >
              <ShieldAlert className="h-8 w-8 text-destructive" strokeWidth={2} />
            </motion.div>

            <p className="text-[12px] font-bold uppercase tracking-wide text-destructive">
              SOS · {timeAgo(alert.created_at)}
            </p>
            <h2 className="mt-1 text-[22px] font-bold leading-tight text-foreground">
              {alert.title}
            </h2>
            {alert.body && (
              <p className="mt-2 text-[14px] leading-snug text-muted-foreground">
                {alert.body}
              </p>
            )}

            <p className="mt-4 rounded-2xl bg-muted p-3 text-[12px] leading-snug text-muted-foreground">
              Gamira has shown this to your family inside the app. It has not
              called anyone and has not contacted emergency services.
            </p>

            {alerts.length > 1 && (
              <p className="mt-3 text-[12px] font-semibold text-destructive">
                {alerts.length - 1} more alert{alerts.length > 2 ? "s" : ""} waiting
              </p>
            )}

            {!alarmAudible() && (
              /* The browser will not let a page make a sound before anybody has
                 touched it. Say so, rather than leaving somebody to assume an
                 emergency would always be audible. */
              <p className="mt-3 text-[12px] text-muted-foreground">
                This alert is silent — tap anywhere in Gamira once so it can make
                a sound next time.
              </p>
            )}

            <div className="mt-5 flex flex-col gap-2.5">
              <button
                onClick={() => {
                  acknowledge(alert.id);
                  navigate("/emergency");
                }}
                className="flex h-14 items-center justify-center gap-2 rounded-2xl bg-destructive text-[15px] font-semibold text-white transition active:scale-95"
              >
                <Phone className="h-5 w-5" />
                Call them
              </button>
              <button
                onClick={() => acknowledge(alert.id)}
                className="h-12 rounded-2xl border border-border bg-white text-[14px] font-semibold text-foreground transition active:scale-95"
              >
                I have seen this
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
