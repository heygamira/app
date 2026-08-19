import { AnimatePresence, motion } from 'framer-motion';
import { Watch } from 'lucide-react';

/**
 * Their watch flagged a reading, and Gamira has asked about it.
 *
 * She asks out loud — that is the point, and it is what reaches somebody who
 * is not looking at the phone. This card is for the two cases where speaking
 * does not work: the microphone is unavailable, or they would simply rather
 * tap. Without it, the only way to stop the family being told would be to not
 * have the problem.
 *
 * The wording keeps the judgement with the device, exactly as the dashboard's
 * banner does. It repeats what the watch said, attributes it, and says nothing
 * about whether the number is good or bad — because Gamira does not know, and
 * neither does the backend, and telling somebody their heart rate is
 * "high" is a thing only their doctor may do.
 *
 * Amber, not red. Nobody has pressed anything.
 */
export default function WellbeingCheckCard({ check, onAnswer, busy = false }) {
  return (
    <AnimatePresence>
      {check && (
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -12 }}
          className="rounded-3xl border border-warning/40 bg-warning/10 p-4"
          role="status"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-warning/20">
              <Watch className="h-6 w-6 text-warning" strokeWidth={2} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium uppercase tracking-wide text-warning">
                {check.source_device || 'Your watch'}
              </p>
              <p className="mt-0.5 text-[17px] font-semibold leading-snug text-foreground">
                How are you feeling?
              </p>
              <p className="mt-1 text-[15px] leading-snug text-muted-foreground">
                {check.reason} Gamira has not assessed this reading.
              </p>
            </div>
          </div>

          <div className="mt-3 flex gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => onAnswer(true)}
              className="h-14 flex-1 rounded-2xl bg-primary text-[16px] font-semibold text-primary-foreground transition active:scale-[0.98] disabled:opacity-60"
            >
              I&rsquo;m alright
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAnswer(false)}
              className="h-14 flex-1 rounded-2xl border border-border bg-card text-[16px] font-semibold text-foreground transition active:scale-[0.98] disabled:opacity-60"
            >
              Not really
            </button>
          </div>
          {/* Says what the second button does before it is pressed. Somebody
              should never find out afterwards that tapping a button told
              their family something. */}
          <p className="mt-2 text-[13px] leading-snug text-muted-foreground">
            If you are not feeling right, your family will be told so they can
            call you.
          </p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
