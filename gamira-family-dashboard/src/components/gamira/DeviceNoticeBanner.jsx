import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

/**
 * Something worth a look, over whatever screen is open. Never an emergency.
 *
 * Three things arrive here now: a reading a paired device flagged, a flagged
 * reading nobody answered when Gamira asked about it, and an alert somebody
 * withdrew because they said they were alright.
 *
 * Amber and dismissible, on purpose. A watch reporting that a number left the
 * range configured on it is not a person pressing SOS, and giving the two the
 * same treatment would teach a family to ignore both. The wording keeps the
 * judgement with whoever made it: Gamira never says a reading is bad, and the
 * "nobody answered" notice reports the silence rather than diagnosing it.
 */
export default function DeviceNoticeBanner({ notices = [], onAcknowledge }) {
  const navigate = useNavigate();
  const notice = notices[0] || null;

  return (
    <AnimatePresence>
      {notice && (
        <motion.div
          initial={{ y: -60, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -60, opacity: 0 }}
          transition={{ type: "spring", stiffness: 380, damping: 30 }}
          className="fixed inset-x-0 top-0 z-[90] px-3 pt-3"
          role="status"
        >
          <div className="mx-auto flex max-w-md items-start gap-3 rounded-[18px] border border-warning/40 bg-warning/10 p-3.5 shadow-card backdrop-blur">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-warning/20">
              <Activity className="h-[18px] w-[18px] text-warning" strokeWidth={2} />
            </div>

            <button
              onClick={() => {
                onAcknowledge?.(notice.id);
                // Where the explanation actually is. A cancelled alert is not
                // on the health screen, and sending somebody there to look for
                // it would be a small lie about where their information lives.
                navigate(
                  notice.related_entity_type === "health_reading"
                    ? "/health"
                    : "/notifications"
                );
              }}
              className="min-w-0 flex-1 text-left"
            >
              <p className="text-[13px] font-semibold leading-tight text-foreground">
                {notice.title}
              </p>
              <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">
                {notice.body}
              </p>
              {notices.length > 1 && (
                <p className="mt-1 text-[11px] font-semibold text-warning">
                  {notices.length - 1} more notice
                  {notices.length > 2 ? "s" : ""}
                </p>
              )}
            </button>

            <button
              onClick={() => onAcknowledge?.(notice.id)}
              aria-label="Dismiss"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-black/5"
            >
              <X className="h-4 w-4" strokeWidth={2} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
