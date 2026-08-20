import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { WifiOff } from "lucide-react";
import { useOnlineStatus } from "@/lib/useOnlineStatus";

/**
 * A wrapped native app is expected to behave gracefully offline, not just
 * error per-request the way a browser tab quietly would. This says so.
 */
export default function OfflineBanner() {
  const online = useOnlineStatus();

  return (
    <AnimatePresence>
      {!online && (
        <motion.div
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 40, opacity: 0 }}
          transition={{ type: "spring", stiffness: 380, damping: 30 }}
          className="fixed inset-x-0 bottom-20 z-[80] px-3"
          role="status"
        >
          <div className="mx-auto flex max-w-md items-center gap-2 rounded-2xl border border-border/60 bg-foreground/90 px-3.5 py-2.5 text-white shadow-card backdrop-blur">
            <WifiOff className="h-4 w-4 shrink-0" strokeWidth={2} />
            <p className="text-[12px] font-medium leading-snug">
              You're offline. Gamira will catch up once you're back online.
            </p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
