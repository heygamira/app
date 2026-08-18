import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { HelpCircle, Loader2 } from 'lucide-react';

/**
 * The confirmation a voice action has to pass through.
 *
 * The wording comes from the backend, which built it from the row it is about
 * to change — "Mark Metformin scheduled for 8:00 AM as taken?". The model never
 * writes this text, so what is shown and what will run cannot differ.
 *
 * Read as well as heard: Gamira says the same sentence out loud, and it is on
 * screen at the app's normal size with two large buttons. Nothing here relies
 * on colour to say which is which.
 *
 * Rendered through a portal for the same reason the SOS dialog is: the bar it
 * would otherwise sit inside uses a CSS transform, which becomes the containing
 * block for `position: fixed` and cuts the dialog off at the bottom.
 */
export default function VoiceConfirmDialog({
  open,
  prompt,
  busy = false,
  onConfirm,
  onCancel,
  yesLabel = 'Yes, do it',
  noLabel = 'No, leave it',
}) {
  const confirmRef = useRef(null);

  // Escape declines. Someone who did not mean to ask for this needs a way out
  // that is not a small button, and declining is always the safe answer.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape' && !busy) onCancel?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, busy, onCancel]);

  // Move focus to the dialog so a screen reader announces it and a keyboard
  // user is not left behind on the page underneath.
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  const dialog = (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[110] flex items-center justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => !busy && onCancel?.()}
        >
          <motion.div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="voice-confirm-title"
            onClick={(event) => event.stopPropagation()}
            initial={{ scale: 0.9, y: 20 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.9, y: 20 }}
            className="my-auto w-full max-w-sm rounded-3xl border border-border bg-card p-6 text-center shadow-2xl"
          >
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/15">
              {busy ? (
                <Loader2 className="h-7 w-7 animate-spin text-primary" />
              ) : (
                <HelpCircle className="h-7 w-7 text-primary" />
              )}
            </div>

            <p className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
              Gamira is asking
            </p>
            {/* The exact action and target, as the backend worded it. */}
            <h2
              id="voice-confirm-title"
              className="mt-1 text-xl font-bold leading-snug text-foreground"
            >
              {prompt}
            </h2>
            <p className="mt-2 text-[15px] text-muted-foreground">
              Nothing has changed yet.
            </p>
            {/*
              The buttons are not the only way out of this, and somebody who
              cannot easily reach the phone should not have to discover that.
              Gamira is still listening — saying yes or no does the same thing.
            */}
            {!busy && (
              <p className="mt-3 text-[15px] font-medium text-primary">
                Or just say “yes” or “no”.
              </p>
            )}

            <div className="mt-6 flex flex-col gap-3">
              <button
                ref={confirmRef}
                type="button"
                onClick={onConfirm}
                disabled={busy}
                className="h-14 rounded-2xl bg-primary text-[17px] font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-70"
              >
                {busy ? 'Recording…' : yesLabel}
              </button>
              <button
                type="button"
                onClick={onCancel}
                disabled={busy}
                className="h-14 rounded-2xl border border-border bg-card text-[17px] font-semibold text-foreground transition active:scale-95 disabled:opacity-70"
              >
                {noLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  return createPortal(dialog, document.body);
}
