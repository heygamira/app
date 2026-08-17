import { useEffect, useRef } from "react";

// How often screens re-read the record. Anything written elsewhere — a dose
// confirmed in the Parent App, a reading sent by a paired watch — appears
// within this window. 0 (the default) disables polling.
export const POLL_MS = Number(import.meta.env.VITE_POLL_MS ?? 0) || 0;

/**
 * Re-run `callback` every `ms` while the tab is visible.
 *
 * Polling is a stand-in for the push delivery Gamira does not have yet. It is
 * paused on a hidden tab so a background window does not keep the API busy,
 * and it fires once on return so the screen is never stale after a switch.
 *
 * @param {() => void | Promise<void>} callback
 * @param {number} [ms]
 */
export function usePoll(callback, ms = POLL_MS) {
  const latest = useRef(callback);
  latest.current = callback;

  useEffect(() => {
    if (!ms) return undefined;

    let timer = null;
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };
    const start = () => {
      stop();
      timer = setInterval(() => latest.current(), ms);
    };

    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        latest.current();
        start();
      }
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ms]);
}

export default usePoll;
