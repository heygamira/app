import { AnimatePresence, motion } from 'framer-motion';
import { Bell, Check, X } from 'lucide-react';

/**
 * Gamira, having said something first.
 *
 * She has already started saying it by the time this appears; the card is here
 * for anyone who did not catch it or was not in the room. That ordering
 * matters — the voice is the point and the card is the fallback, not the other
 * way round.
 *
 * ## Why it is this small
 *
 * It was three times this size: a heading, a paragraph explaining that she had
 * spoken, and a full-width "Talk to Gamira" button. That is a lot of screen for
 * "time for a glass of water", and it sat above the day's schedule pushing
 * everything down — so a spoken reminder cost more of the screen than the
 * medicine card it was about.
 *
 * It is now the same shape and the same height as the schedule rows below it,
 * with one action on the right, because that is what it is: a row about a thing
 * that is due. It does not repeat her sentence — she said it — and it does not
 * offer a button to start a conversation that is already happening.
 *
 * ## Going away
 *
 * Three ways, all of them ordinary: the action, the small cross, and saying so
 * out loud. The third is the one that matters in a room where the phone is
 * across it, and it is not this component's business — the provider dismisses
 * the card when the thing it is about is recorded, whichever way that happened.
 */
export default function ProactiveNudge({ nudge, onDismiss, onDone, busy = false }) {
  const isDose = Boolean(nudge?.doseId);
  return (
    <AnimatePresence>
      {nudge && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="flex items-center gap-3 rounded-2xl border border-accent/30 bg-accent/5 p-3"
          role="status"
        >
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/15">
            <Bell className="h-5 w-5 text-accent" strokeWidth={2} />
          </div>

          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold leading-tight text-foreground">
              {nudge.title}
            </p>
            <p className="text-[13px] leading-tight text-muted-foreground">
              Gamira mentioned this
            </p>
          </div>

          {onDone && (
            <button
              type="button"
              onClick={onDone}
              disabled={busy}
              className="flex h-11 shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[15px] font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-50"
            >
              <Check className="h-5 w-5" /> {isDose ? 'Taken' : 'Done'}
            </button>
          )}

          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss"
            className="flex h-11 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground active:bg-muted"
          >
            <X className="h-5 w-5" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
