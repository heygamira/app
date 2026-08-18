import { AnimatePresence, motion } from 'framer-motion';
import { Bell, X } from 'lucide-react';

/**
 * Gamira, having said something first.
 *
 * She has already spoken the sentence out loud by the time this appears; the
 * card is the written copy, for anyone who did not catch it or was not in the
 * room. That ordering matters — the voice is the point, and the card is the
 * fallback, not the other way round.
 *
 * A card, not a dialog. Nothing here is urgent enough to take over the screen
 * or to need answering, and dismissing it is one large tap. The dose itself is
 * still on the schedule below, where it can be recorded properly.
 */
export default function ProactiveNudge({ nudge, onDismiss, onTalk }) {
  return (
    <AnimatePresence>
      {nudge && (
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          className="mb-4 rounded-3xl border border-primary/30 bg-primary/5 p-4"
          role="status"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary/15">
              <Bell className="h-6 w-6 text-primary" strokeWidth={2} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium uppercase tracking-wide text-primary">
                Gamira
              </p>
              <p className="mt-0.5 text-[17px] font-semibold leading-snug text-foreground">
                {nudge.title}
              </p>
              <p className="mt-1 text-[15px] leading-snug text-muted-foreground">
                {nudge.say}
              </p>
            </div>
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-muted-foreground active:bg-muted"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {onTalk && (
            <button
              type="button"
              onClick={onTalk}
              className="mt-3 h-12 w-full rounded-2xl bg-primary text-[16px] font-semibold text-primary-foreground transition active:scale-[0.98]"
            >
              Talk to Gamira
            </button>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
