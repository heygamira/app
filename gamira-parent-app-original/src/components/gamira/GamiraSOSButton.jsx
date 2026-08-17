import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, Check, Loader2, Phone } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

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
 */
export default function GamiraSOSButton({
  label,
  onAlert,
  onCall,
  callLabel,
  confirmTitle,
  confirmMsg,
  yesLabel,
  cancelLabel,
  openSignal = 0,
}) {
  const [open, setOpen] = useState(false);
  // 'ask' | 'sending' | 'sent' | 'failed'
  const [phase, setPhase] = useState('ask');
  const [error, setError] = useState('');

  // `openSignal` is bumped when something outside this component asks for the
  // SOS screen — the voice assistant's `prepare_sos`, for instance. It opens
  // the same dialog with the same confirmation. It cannot press it: `phase`
  // starts at 'ask' either way, so a person still has to say yes.
  useEffect(() => {
    if (!openSignal) return;
    setPhase('ask');
    setError('');
    setOpen(true);
  }, [openSignal]);

  const close = () => {
    setOpen(false);
    setPhase('ask');
    setError('');
  };

  const confirm = async () => {
    if (!onAlert) {
      setPhase('sent');
      return;
    }
    setPhase('sending');
    try {
      await onAlert();
      setPhase('sent');
    } catch (err) {
      setError(err?.message || 'Could not reach Gamira.');
      setPhase('failed');
    }
  };

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
                phase === 'sent' ? 'bg-success/15' : 'bg-destructive/15'
              }`}
            >
              {phase === 'sending' ? (
                <Loader2 className="h-7 w-7 animate-spin text-destructive" />
              ) : phase === 'sent' ? (
                <Check className="h-7 w-7 text-success" />
              ) : phase === 'failed' ? (
                <AlertCircle className="h-7 w-7 text-destructive" />
              ) : (
                <Phone className="h-7 w-7 text-destructive" />
              )}
            </div>

            {phase === 'sent' ? (
              <>
                <h3 className="text-xl font-bold text-foreground">Your family knows</h3>
                <p className="mt-1 text-[15px] text-muted-foreground">
                  They can see this alert in their Gamira app. Gamira has not called
                  anyone for you.
                </p>
              </>
            ) : phase === 'failed' ? (
              <>
                <h3 className="text-xl font-bold text-foreground">
                  Gamira could not send the alert
                </h3>
                <p className="mt-1 text-[15px] text-muted-foreground">{error}</p>
              </>
            ) : (
              <>
                <h3 className="text-xl font-bold text-foreground">{confirmTitle}</h3>
                <p className="mt-1 text-[15px] text-muted-foreground">{confirmMsg}</p>
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

              {(phase === 'sent' || phase === 'failed') && onCall ? (
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

              {phase === 'failed' ? (
                <button
                  onClick={confirm}
                  className="h-14 rounded-2xl border border-border bg-card text-[15px] font-semibold text-foreground transition active:scale-95"
                >
                  Try again
                </button>
              ) : null}

              <button
                onClick={close}
                className="h-14 rounded-2xl border border-border bg-card text-[15px] font-semibold text-foreground transition active:scale-95"
              >
                {phase === 'sent' ? 'Close' : cancelLabel}
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
        onClick={() => setOpen(true)}
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
