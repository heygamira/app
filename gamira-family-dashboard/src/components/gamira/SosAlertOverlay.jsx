import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Phone, ShieldAlert } from "lucide-react";

/** Two short tones. Synthesised so the alert needs no asset to load. */
function beep() {
  try {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return;
    const ctx = new Ctor();
    [0, 0.35].forEach((offset) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + offset + 0.25);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + offset);
      osc.stop(ctx.currentTime + offset + 0.3);
    });
    setTimeout(() => ctx.close(), 1500);
  } catch {
    // Autoplay policy, no audio device — the visual alert stands on its own.
  }
}

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
  const announced = useRef(null);

  useEffect(() => {
    if (alert && announced.current !== alert.id) {
      announced.current = alert.id;
      beep();
    }
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
