import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';

export default function ConfirmDialog({ open, title, message, confirmText = 'Remove', onConfirm, onCancel }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onCancel}
        >
          <motion.div
            onClick={(e) => e.stopPropagation()}
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            className="w-full max-w-sm rounded-3xl border border-border bg-card p-6 shadow-xl"
          >
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/15">
              <AlertTriangle className="h-6 w-6 text-red-500" />
            </div>
            <h2 className="text-xl font-bold text-foreground">{title}</h2>
            <p className="mt-1 text-base text-muted-foreground">{message}</p>
            <div className="mt-6 flex flex-col gap-2">
              <button
                type="button"
                onClick={onConfirm}
                className="h-12 rounded-xl bg-red-500 text-base font-semibold text-white transition active:scale-95"
              >
                {confirmText}
              </button>
              <button
                type="button"
                onClick={onCancel}
                className="h-12 rounded-xl bg-muted text-base font-semibold text-foreground transition active:scale-95"
              >
                Cancel
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
