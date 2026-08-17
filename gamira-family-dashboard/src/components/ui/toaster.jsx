import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { useToast } from '@/components/ui/use-toast';

export function Toaster() {
  const { toasts, dismiss } = useToast();

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed inset-x-0 bottom-24 z-[100] flex flex-col items-center gap-2 px-5 sm:bottom-6"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            layout
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.97 }}
            transition={{ duration: 0.18 }}
            role="status"
            className={cn(
              'pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-lg border p-4 shadow-lg',
              t.variant === 'destructive'
                ? 'border-destructive/30 bg-destructive text-white'
                : 'border-border bg-card text-card-foreground',
            )}
          >
            <div className="min-w-0 flex-1">
              {t.title && <p className="text-sm font-medium">{t.title}</p>}
              {t.description && (
                <p
                  className={cn(
                    'text-sm',
                    t.title && 'mt-1',
                    t.variant === 'destructive' ? 'text-white/80' : 'text-muted-foreground',
                  )}
                >
                  {t.description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 rounded-md p-1 opacity-60 transition-opacity hover:opacity-100"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export default Toaster;
