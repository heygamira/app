import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, Check, Loader2, Phone } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { Haptics, ImpactStyle } from '@capacitor/haptics';

/**
 * The SOS button.
 *
 * Two steps, in this order, because each does something different:
 *
 *   1. `onAlert` records the press so the rest of the family sees it in their
 *      Gamira app. Nobody is called, messaged or dispatched by that.
 *   2. `onCall` opens the phone dialer, which is still the only thing that
 *      reliably reaches a person.
 *
 * The dialog says exactly that. A button that implied help was on the way
 * would be the most dangerous control in the product.
 *
 * ## The countdown
 *
 * Both ways in now count down before they send. That is a change of default —
 * a press used to wait indefinitely for a second press — and it is the right
 * one for this person: reaching a confirm button is the thing they may not be
 * able to do, and it is exactly what pressing SOS says they cannot do. So the
 * default falls towards *sending*, which is also the recoverable direction:
 * what it raises is an in-app message to their own family, and a false one
 * costs a phone call.
 *
 * The countdown was already written and was unreachable. `autoConfirmSeconds`
 * defaulted to 0 and nothing ever passed a value, so the voice path — the one
 * for somebody who cannot reach the screen — fired on the next tick with no
 * countdown and no cancel window, while the tool description told the model a
 * cancellable countdown was running. The model was being made to say something
 * untrue about an emergency.
 *
 * ## Why the callbacks are held in refs
 *
 * They were not, and it produced the worst bug in the app. `onCountdownStart`
 * is passed as an inline arrow, so it had a new identity on every render of
 * the page above; that gave `begin` a new identity; `begin` was in the
 * dependency array of the effect that opens this dialog; so the effect re-fired
 * on *every parent render*, resetting the countdown to its start and re-opening
 * a dialog somebody had just closed. `onAlert` did the same to the tick
 * effect's `setTimeout`, so the number could not go down either.
 *
 * The page above re-renders several times a second while Gamira is speaking —
 * every chunk of transcript is a state update — and this dialog is on screen
 * precisely when she is speaking. So the two fed each other.
 *
 * Keeping them in refs is not a workaround for a careless parent. A dialog
 * that counts down to raising an emergency must not depend on how often
 * anything above it happens to re-render.
 *
 * ## Cancelling
 *
 * `cancelCountdown` on the ref is what a spoken "cancel" reaches, through the
 * client tool allowlist. It returns whether anything was actually stopped, so
 * Gamira can tell "I stopped it" from "that has already gone to your family" —
 * two things that must never be confused.
 *
 * Once it *has* gone, `onCancelAlert` withdraws it. The alert is not deleted
 * and the family is told it was cancelled: an emergency that silently vanishes
 * is worse for them than the false alarm was.
 *
 * Either way the dialog then closes itself. It did not, and the result was the
 * screen contradicting the room: she had said out loud that the alert was
 * withdrawn, the family's dashboard had already shown it as cancelled, and the
 * person was still looking at "Your family knows" with no obvious way out. A
 * withdrawal by voice never touched this component at all — `withdrawn()` on
 * the ref is how it hears about one now.
 */
export default function GamiraSOSButton({
  label,
  onAlert,
  onCall,
  onCancelAlert,
  callLabel,
  confirmTitle,
  confirmMsg,
  yesLabel,
  cancelLabel,
  openSignal = 0,
  controlRef = null,
  // Seconds between the screen opening and the alert going to the family.
  // Long enough to say "cancel" or reach a large button; short enough that
  // somebody who really needs help is not waiting through it.
  countdownSeconds = 10,
  onCountdownStart,
}) {
  // Held rather than closed over: see the note above. Nothing here may enter a
  // dependency array, or this component's timing becomes the parent's problem.
  const handlersRef = useRef({ onAlert, onCancelAlert, onCountdownStart });
  handlersRef.current = { onAlert, onCancelAlert, onCountdownStart };

  const [open, setOpen] = useState(false);
  // 'ask' | 'sending' | 'sent' | 'failed' | 'cancelling' | 'cancelled'
  const [phase, setPhase] = useState('ask');
  const [error, setError] = useState('');
  // Seconds left before this raises itself, or null when nothing is counting.
  const [countdown, setCountdown] = useState(null);
  const [alertId, setAlertId] = useState(null);

  const begin = useCallback(() => {
    Haptics.impact({ style: ImpactStyle.Heavy }).catch(() => {});
    setPhase('ask');
    setError('');
    setAlertId(null);
    setOpen(true);
    setCountdown(countdownSeconds >= 0 ? countdownSeconds : null);
    if (countdownSeconds > 0) handlersRef.current.onCountdownStart?.(countdownSeconds);
  }, [countdownSeconds]);

  // `openSignal` is bumped when something outside this component asks for the
  // SOS screen — the voice assistant's `prepare_sos`. Once per *bump*, not once
  // per render: the effect can run as often as React likes, and only a changed
  // value opens anything.
  const lastSignalRef = useRef(0);
  useEffect(() => {
    if (!openSignal || lastSignalRef.current === openSignal) return;
    lastSignalRef.current = openSignal;
    begin();
  }, [openSignal, begin]);

  const close = () => {
    setOpen(false);
    setPhase('ask');
    setError('');
    setCountdown(null);
    setAlertId(null);
  };

  const confirm = useCallback(async () => {
    Haptics.impact({ style: ImpactStyle.Heavy }).catch(() => {});
    setCountdown(null);
    const raise = handlersRef.current.onAlert;
    if (!raise) {
      setPhase('sent');
      return;
    }
    setPhase('sending');
    try {
      const raised = await raise();
      setAlertId(raised?.id || null);
      setPhase('sent');
    } catch (err) {
      setError(err?.message || 'Could not reach Gamira.');
      setPhase('failed');
    }
  }, []);

  /**
   * Stop the countdown, if one is running. Returns whether it was.
   *
   * Exposed on the ref so a spoken "cancel" can reach it. It stops the timer
   * *and* closes the screen: somebody who has said they are alright has
   * finished with this, and leaving a red dialog in front of them would be a
   * second thing to dismiss.
   */
  const cancelCountdown = useCallback(() => {
    if (!open || phase !== 'ask' || countdown === null) return false;
    close();
    return true;
  }, [open, phase, countdown]);

  const cancelAlert = useCallback(async () => {
    const withdraw = handlersRef.current.onCancelAlert;
    if (!alertId || !withdraw) return false;
    setPhase('cancelling');
    try {
      await withdraw(alertId);
      setPhase('cancelled');
      return true;
    } catch (err) {
      setError(err?.message || 'Could not withdraw the alert.');
      setPhase('failed');
      return false;
    }
  }, [alertId]);

  /**
   * The alert was withdrawn somewhere other than this dialog — out loud,
   * through `cancel_my_sos`, which is the backend's tool and never comes near
   * this component.
   *
   * Shows the outcome and then closes, rather than closing on the spot: this
   * is a screen about an emergency, and it should say what happened to it
   * before it disappears.
   */
  const withdrawn = useCallback(() => {
    if (!open) return false;
    setCountdown(null);
    setPhase('cancelled');
    return true;
  }, [open]);

  // "Cancelled" is an outcome, not a state to sit in. Once it has been read,
  // the dialog goes on its own — nobody should have to dismiss a screen about
  // an alert that no longer exists.
  useEffect(() => {
    if (phase !== 'cancelled') return undefined;
    const timer = setTimeout(close, 3500);
    return () => clearTimeout(timer);
  }, [phase]);

  useImperativeHandle(
    controlRef,
    () => ({
      cancelCountdown,
      withdrawn,
      open: begin,
      get counting() {
        return countdown !== null;
      },
    }),
    [cancelCountdown, withdrawn, begin, countdown]
  );

  // Tick the countdown, and raise the alert when it runs out. Any interaction
  // with the dialog stops it: somebody who is reading and deciding is somebody
  // who does not need it decided for them.
  //
  // `confirm` is stable now, so this timeout survives a parent render. It did
  // not, and a dialog that restarts its own one-second timer several times a
  // second never reaches zero.
  useEffect(() => {
    if (countdown === null || phase !== 'ask') return undefined;
    if (countdown <= 0) {
      setCountdown(null);
      confirm();
      return undefined;
    }
    const timer = setTimeout(() => setCountdown((n) => (n === null ? null : n - 1)), 1000);
    return () => clearTimeout(timer);
  }, [countdown, phase, confirm]);

  // Escape closes it too. Someone who opened this by accident needs a way out
  // that does not involve finding a small button.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape' && phase !== 'sending') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, phase]);

  const heading =
    phase === 'sent'
      ? 'Your family knows'
      : phase === 'cancelled'
        ? 'Cancelled'
        : phase === 'failed'
          ? 'Gamira could not send the alert'
          : confirmTitle;

  const body =
    phase === 'sent'
      ? 'They can see this alert in their Gamira app. Gamira has not called anyone for you.'
      : phase === 'cancelled'
        ? 'Your family has been told you are alright. The alert stays in your record.'
        : phase === 'failed'
          ? error
          : confirmMsg;

  // The dialog is rendered into <body>, not where this button sits. The SOS
  // button lives in a bar that uses a CSS transform, and a transformed
  // ancestor becomes the containing block for `position: fixed` — so without
  // the portal the backdrop only covered that bar: the dialog was cut off at
  // the bottom of the screen, and tapping outside it did nothing.
  const dialog = (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={close}
          role="dialog"
          aria-modal="true"
        >
          <motion.div
            onClick={(event) => event.stopPropagation()}
            initial={{ scale: 0.9, y: 20 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.9, y: 20 }}
            // my-auto inside the scrolling backdrop: on a short window the
            // dialog scrolls rather than running off the bottom edge.
            className="my-auto w-full max-w-sm rounded-3xl border border-border bg-card p-6 text-center shadow-2xl"
          >
            <div
              className={`mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full ${
                phase === 'sent' || phase === 'cancelled'
                  ? 'bg-success/15'
                  : 'bg-destructive/15'
              }`}
            >
              {phase === 'sending' || phase === 'cancelling' ? (
                <Loader2 className="h-7 w-7 animate-spin text-destructive" />
              ) : phase === 'sent' || phase === 'cancelled' ? (
                <Check className="h-7 w-7 text-success" />
              ) : phase === 'failed' ? (
                <AlertCircle className="h-7 w-7 text-destructive" />
              ) : (
                <Phone className="h-7 w-7 text-destructive" />
              )}
            </div>

            <h3 className="text-xl font-bold text-foreground">{heading}</h3>
            <p className="mt-1 text-[15px] text-muted-foreground">{body}</p>

            {countdown !== null && phase === 'ask' && (
              <>
                {/* The number, big enough to read across a room, with a bar
                    that shows the same thing without needing to be read. */}
                <p className="mt-4 text-5xl font-bold tabular-nums text-destructive">
                  {countdown}
                </p>
                <div className="mx-auto mt-2 h-1.5 w-40 overflow-hidden rounded-full bg-destructive/20">
                  <motion.div
                    className="h-full rounded-full bg-destructive"
                    initial={{ width: '100%' }}
                    animate={{ width: `${(countdown / countdownSeconds) * 100}%` }}
                    transition={{ duration: 0.9, ease: 'linear' }}
                  />
                </div>
                <p className="mt-2 text-[15px] font-semibold text-foreground">
                  Telling your family — say &ldquo;cancel&rdquo; or press below
                </p>
              </>
            )}

            <div className="mt-6 flex flex-col gap-3">
              {phase === 'ask' || phase === 'sending' ? (
                <button
                  onClick={confirm}
                  disabled={phase === 'sending'}
                  className="h-14 rounded-2xl bg-destructive text-[15px] font-semibold text-white transition active:scale-95 disabled:opacity-70"
                >
                  {phase === 'sending' ? 'Sending…' : yesLabel}
                </button>
              ) : null}

              {(phase === 'sent' || phase === 'failed' || phase === 'cancelled') && onCall ? (
                <button
                  onClick={() => {
                    close();
                    onCall();
                  }}
                  className="h-14 rounded-2xl bg-destructive text-[15px] font-semibold text-white transition active:scale-95"
                >
                  {callLabel}
                </button>
              ) : null}

              {/* It has gone, and they are alright after all. Their family is
                  told that too — a red alert that quietly disappears leaves
                  them worse off than the false alarm did. */}
              {phase === 'sent' && alertId && onCancelAlert ? (
                <button
                  onClick={cancelAlert}
                  className="h-14 rounded-2xl border border-border bg-card text-[15px] font-semibold text-foreground transition active:scale-95"
                >
                  I&rsquo;m alright — tell them
                </button>
              ) : null}

              {phase === 'failed' ? (
                <button
                  onClick={confirm}
                  className="h-14 rounded-2xl border border-border bg-card text-[15px] font-semibold text-foreground transition active:scale-95"
                >
                  Try again
                </button>
              ) : null}

              {/* While the countdown runs this is the safety valve, so it stops
                  looking like the quiet secondary option. */}
              <button
                onClick={close}
                disabled={phase === 'cancelling'}
                className={`h-14 rounded-2xl border text-[15px] font-semibold transition active:scale-95 disabled:opacity-70 ${
                  countdown !== null
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border bg-card text-foreground'
                }`}
              >
                {phase === 'sent' || phase === 'cancelled'
                  ? 'Close'
                  : countdown !== null
                    ? "No, I'm alright"
                    : cancelLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  return (
    <>
      <motion.button
        onClick={begin}
        whileTap={{ scale: 0.94 }}
        className="flex h-20 w-20 flex-col items-center justify-center rounded-full bg-destructive text-white"
        style={{ boxShadow: '0 10px 30px rgba(239,68,68,0.45)' }}
        aria-label={label}
      >
        <Phone className="h-6 w-6" fill="currentColor" />
        <span className="text-[11px] font-bold tracking-wide">{label}</span>
      </motion.button>

      {createPortal(dialog, document.body)}
    </>
  );
}
